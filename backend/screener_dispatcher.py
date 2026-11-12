"""
Screener Dispatcher — main entry point for GitHub Actions.
Routes based on payload (market, logic, timeframe, params).
Loads stock lists, executes appropriate screener, formats output.
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from dataclasses import replace
from time import monotonic
import re
import argparse

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from screeners.breakout_screener import BreakoutScreener
from screeners.pullback_screener import PullbackScreener
from screeners.data_fetcher import FETCH_NO_DATA, FetchStatus, fetch_history_batch, get_history_window
from screeners.scan_report import notify, write_report


def load_stock_list(market):
    """
    Load stock list from JSON file based on market.

    Returns:
        List of stock symbols with market suffix (e.g., ['SBIN.NS', 'INFY.NS'])
    """
    stock_file = BASE_DIR / 'stock_lists' / f"{market.lower()}_stocks.json"

    latest = stock_file.with_name(f'{market.lower()}_latest.json')
    if latest.is_file():
        stock_file = latest

    try:
        with stock_file.open(encoding='utf-8') as f:
            data = json.load(f)

        default_suffixes = {'NSE': '.NS', 'BSE': '.BO'}
        suffix = data.get('suffix', default_suffixes.get(market.upper(), ''))
        stocks = data.get('stocks') or data.get(f'{market.lower()}_stocks', [])
        symbols = list(dict.fromkeys(
            stock if not suffix or stock.endswith(suffix) else f"{stock}{suffix}"
            for stock in stocks
        ))
        return symbols, data.get('refresh', {'source': 'Bundled stock list', 'refreshed_at': None})

    except FileNotFoundError:
        print(f"❌ Stock list file not found: {stock_file}")
        return [], {}
    except Exception as e:
        print(f"❌ Error loading stock list: {e}")
        return [], {}


def get_config(logic, timeframe, params):
    """
    Build configuration dictionary from payload params.

    Note: timeframe is passed as a direct constructor argument to the screener
    classes and is not needed inside config. It was previously duplicated here
    which was harmless but confusing — removed for clarity.
    """
    config = {
        'min_turnover': params.get('min_turnover', 10_000_000),
        'timeframe': timeframe,
    }

    if logic == 'breakout':
        config.update({
            'tolerance_below_avwap': params.get('tolerance_below_avwap', 0.05),
            'ceiling': params.get('ceiling', 0.10),
            'sustain_periods': params.get('sustain_periods', 3),
            'max_failed_attempts': params.get('max_failed_attempts', 2),
        })
    else:  # pullback
        config.update({
            'proximity_low_pct': params.get('proximity_low_pct', 0.0),
            'proximity_high_pct': params.get('proximity_high_pct', 2.0),
            'max_brief_crosses': params.get('max_brief_crosses', 5),
            'min_periods_old': params.get('min_periods_old', 20),
        })

    return config


def get_anchor_periods(logic, timeframe, params):
    """
    Get anchor periods from params, or fall back to sensible defaults.
    """
    if 'anchor_periods' in params and params['anchor_periods']:
        return params['anchor_periods']

    if timeframe == 'daily':
        return [180, 365, 550, 730, 900]
    elif timeframe == 'weekly':
        return [52, 104, 156, 208, 260]
    elif timeframe == 'monthly':
        return [12, 36, 60, 84, 120]

    return []



IST = timezone(timedelta(hours=5, minutes=30))
STRATEGIES = {'breakout': BreakoutScreener, 'pullback': PullbackScreener}
SCHEDULE_DEFAULTS = {'breakout': {'max_failed_attempts': 0}, 'pullback': {'max_brief_crosses': 3}}


def scheduled_params(timeframe, logic, date):
    file = BASE_DIR / 'schedule_presets.json'
    presets = json.loads(file.read_text(encoding='utf-8')) if file.is_file() else {}
    preset = presets.get(f'{timeframe}-{logic}', {})
    override = preset.get('override') or {}
    params = override.get('params') if override.get('date') == date else None
    return {**SCHEDULE_DEFAULTS[logic], **(preset.get('defaults') or {}), **(params or {})}


def prepare(logic, timeframe, params, end):
    if not isinstance(params, dict):
        raise ValueError('Scan settings must be an object')
    periods = get_anchor_periods(logic, timeframe, params)
    maximum = {'daily': 2500, 'weekly': 520, 'monthly': 240}[timeframe]
    if not isinstance(periods, list) or not 1 <= len(periods) <= 12 or any(
        type(period) is not int or not 1 <= period <= maximum for period in periods
    ):
        raise ValueError(f'Choose 1–12 whole-number anchor periods from 1 to {maximum}')
    periods = list(dict.fromkeys(periods))
    config = get_config(logic, timeframe, params)
    window = get_history_window(timeframe, periods, pullback=logic == 'pullback', end=end)
    return config, periods, window


def scan(args):
    end = datetime.now()
    run_date = datetime.now(IST).date().isoformat()
    if args.logic == 'scheduled' and (args.market != 'NSE' or args.timeframe == 'monthly'):
        raise ValueError('Scheduled presets are available for daily and weekly NSE scans')
    strategies = list(STRATEGIES) if args.logic == 'scheduled' else [args.logic]
    setups = {
        logic: prepare(
            logic, args.timeframe,
            scheduled_params(args.timeframe, logic, run_date)
            if args.logic == 'scheduled' else json.loads(args.params),
            end,
        ) for logic in strategies
    }
    stocks, universe = load_stock_list(args.market)
    if not stocks:
        raise ValueError(f'No stocks loaded for {args.market}')

    window = next(iter(setups.values()))[2]
    window = replace(window, start=min(setup[2].start for setup in setups.values()))
    started = monotonic()
    histories, statuses = fetch_history_batch(stocks, args.timeframe, [1], window=window)
    print(f'History download took {monotonic() - started:.1f}s · {len(histories)}/{len(stocks)} symbols')

    for logic, (config, periods, strategy_window) in setups.items():
        run_id = f'{args.job_id}-{logic}' if args.logic == 'scheduled' else args.job_id
        directory = BASE_DIR / 'results' / 'runs' / run_id
        directory.mkdir(parents=True, exist_ok=True)
        screener = STRATEGIES[logic](stocks, args.market, args.timeframe, periods, config)

        # Each strategy sees its own history window even when the download is shared.
        eligible = {}
        for symbol, frame in histories.items():
            start = strategy_window.start.date().isoformat()
            sliced = frame.loc[start:] if strategy_window.start > window.start else frame
            if len(sliced) >= 10:
                eligible[symbol] = sliced
        strategy_statuses = {
            **statuses,
            **{symbol: FetchStatus(FETCH_NO_DATA) for symbol in histories if symbol not in eligible},
        }
        df = screener.run((eligible, strategy_statuses))
        filename = f'{args.market.lower()}_{logic}_{args.timeframe}_{end.strftime("%d%b%Y").lower()}.csv'
        df.to_csv(directory / filename, index=False)
        coverage = write_report(directory, screener, {**config, 'anchor_periods': periods}, universe, filename)
        print(f'{run_id} · {coverage}')
        if args.telegram_token and args.telegram_chat_id:
            notify(screener, logic, coverage, run_id, args.telegram_token, args.telegram_chat_id)


def main():
    parser = argparse.ArgumentParser(description='ARGUS Screener')
    parser.add_argument('--market', choices=['NSE', 'BSE', 'NASDAQ', 'NYSE'], default='NSE')
    parser.add_argument('--logic', choices=[*STRATEGIES, 'scheduled'], default='breakout')
    parser.add_argument('--timeframe', choices=['daily', 'weekly', 'monthly'], default='daily')
    parser.add_argument('--params', default='{}')
    parser.add_argument('--job-id', default=f'local-{int(datetime.now().timestamp())}')
    parser.add_argument('--telegram-token', default=os.getenv('TELEGRAM_BOT_TOKEN'))
    parser.add_argument('--telegram-chat-id', default=os.getenv('TELEGRAM_CHAT_ID'))
    args = parser.parse_args()
    if not re.fullmatch(r'[a-z0-9-]{1,80}', args.job_id):
        parser.error('Invalid scan ID')
    scan(args)


if __name__ == '__main__':
    main()
