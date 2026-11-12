"""Scan-specific results, coverage and TradingView output."""
import json
import math
from collections import defaultdict

from screeners.output_formatter import to_tv
from screeners.telegram_notifier import send_telegram_message


def clean_numbers(value):
    if isinstance(value, dict):
        return {key: clean_numbers(item) for key, item in value.items()}
    if isinstance(value, float):
        return round(value, 4) if math.isfinite(value) else None
    return value


def coverage_for(stocks):
    counts = defaultdict(int)
    for item in stocks.values():
        counts[item['status']] += 1
    counts['requested'] = len(stocks)
    counts['evaluated'] = counts.get('evaluated', 0)
    counts['skipped'] = len(stocks) - counts['evaluated']
    counts['incomplete_checks'] = sum(
        any(check['status'] in {'calculation_error', 'insufficient_history', 'avwap_unavailable', 'no_post_anchor_data', 'anchor_age_excludes_window'}
            or check.get('history_short') for check in item.get('periods', {}).values())
        for item in stocks.values()
    )
    return dict(counts)


def write_report(directory, screener, config, universe, filename):
    coverage = coverage_for(screener.diagnostics)
    meta = {
        'coverage': coverage, 'settings': config, 'universe': universe,
        'market': screener.market, 'timeframe': screener.timeframe, 'csv_file': filename,
        'lookback_unit': 'candles',
    }
    (directory / 'summary.json').write_text(json.dumps(meta), encoding='utf-8')
    # One small file per prefix keeps a single-symbol lookup cheap.
    buckets = defaultdict(dict)
    for symbol, checks in screener.diagnostics.items():
        buckets[symbol[0]][symbol] = clean_numbers(checks)
    for prefix, bucket in buckets.items():
        (directory / f'tickers-{ord(prefix)}.json').write_text(
            json.dumps(bucket, separators=(',', ':'), allow_nan=False), encoding='utf-8'
        )
    return coverage


def ticker_chunks(symbols, limit=3700):
    chunk = []
    size = 0
    for symbol in symbols:
        if chunk and size + len(symbol) + 1 > limit:
            yield ','.join(chunk)
            chunk, size = [], 0
        size += len(symbol) + bool(chunk)
        chunk.append(symbol)
    if chunk:
        yield ','.join(chunk)


def notify(screener, logic, coverage, scan_id, token, chat_id):
    suffix = screener.market_suffix
    groups = defaultdict(list)
    for symbol, item in screener.diagnostics.items():
        tv = to_tv(symbol.removesuffix(suffix) if suffix else symbol, suffix, screener.market)
        for period, check in item.get('periods', {}).items():
            if check['status'] == 'passed':
                groups[period].append(tv)
    symbols = sorted({symbol for group in groups.values() for symbol in group})
    header = (f'{screener.market} {screener.timeframe.title()} {logic.title()} · {scan_id}\n'
              f'{len(symbols)} matches · {coverage["evaluated"]}/{coverage["requested"]} evaluated'
              f' · {coverage["incomplete_checks"]} with incomplete lookbacks')
    lines = [header]
    for period in screener.anchor_periods:
        if period in groups:
            lines.extend(f'{period} candles · {chunk}' for chunk in ticker_chunks(sorted(groups[period])))
    print('Telegram summary:', send_telegram_message('\n'.join(lines), token, chat_id, plain=True))
    for chunk in ticker_chunks(symbols):
        print('Telegram TradingView:', send_telegram_message(chunk, token, chat_id, plain=True))
