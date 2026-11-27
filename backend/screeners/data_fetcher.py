"""
Shared yfinance data fetch helpers for screeners.

The screeners scan thousands of symbols. Fetching each symbol through a fresh
Ticker.history call can trigger transient Yahoo/yfinance throttling, after which
all remaining symbols often look like ordinary "No data" symbols. This module
centralizes batched downloads, retries, and explicit fetch-status reporting so
screening logic can stay unchanged while data failures are easier to diagnose.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from math import isfinite
import os
import random
import time
from typing import Iterable

from dateutil.relativedelta import relativedelta
import pandas as pd
import yfinance as yf

PRICE_COLUMNS = ['Open', 'High', 'Low', 'Close', 'Adj Close']
REQUIRED_COLUMNS = [*PRICE_COLUMNS, 'Volume']
FETCH_OK = 'ok'
FETCH_NO_DATA = 'no_data'
FETCH_INCOMPLETE_CANDLE = 'incomplete_candle'
FETCH_INSUFFICIENT_HISTORY = 'insufficient_history'
FETCH_ERROR = 'fetch_error'
FETCH_RATE_LIMITED = 'rate_limited'


@dataclass(frozen=True)
class HistoryWindow:
    start: datetime
    end: datetime
    interval: str
    daily_cutoff: date | None = None


@dataclass
class FetchStatus:
    status: str
    message: str = ''
    candle_issue: dict | None = None
    recovered: bool = False


def get_history_window(timeframe, anchor_periods, *, end=None, completed_sessions_only=False):
    """Return yfinance start/end/interval values for a screener timeframe."""
    end = end or datetime.now()
    max_period = max(anchor_periods)

    if timeframe == 'daily':
        start = end - timedelta(days=max_period * 2 + 100)
        interval = '1d'
    elif timeframe == 'weekly':
        start = end - timedelta(weeks=max_period + 52)
        interval = '1wk'
    elif timeframe == 'monthly':
        start = end - relativedelta(months=max_period + 12)
        interval = '1mo'
    else:
        raise ValueError(f"Unsupported timeframe: {timeframe}")

    daily_cutoff = end.date() if timeframe == 'daily' and completed_sessions_only else None
    return HistoryWindow(start=start, end=end, interval=interval, daily_cutoff=daily_cutoff)


def _clean_history(data, *, daily_cutoff=None):
    if data is not None and daily_cutoff is not None:
        data = data.loc[data.index.date < daily_cutoff]
    if data is None or data.empty:
        return None, FetchStatus(FETCH_NO_DATA, 'no candle rows returned')

    values = data.reindex(columns=REQUIRED_COLUMNS).apply(pd.to_numeric, errors='coerce')
    volume = values['Volume']
    # Batched histories align exchange dates. Ignore all-blank padding and zero-volume
    # rows, but retain a price-only or volume-only row so it can be retried.
    has_price = values[PRICE_COLUMNS].notna().any(axis=1)
    traded = values.loc[volume.ne(0) & (volume.notna() | has_price)].sort_index()
    if traded.empty:
        return None, FetchStatus(FETCH_NO_DATA, 'no traded candle rows returned')

    valid = traded.gt(0) & traded.lt(float('inf'))
    invalid = ~valid.all(axis=1)
    if invalid.any():
        bad = traded.loc[invalid].iloc[-1]
        missing = valid.columns[~valid.loc[invalid].iloc[-1]].tolist()
        details = {
            'date': bad.name.date().isoformat(),
            'latest_returned': traded.index[-1].date().isoformat(),
            'invalid_fields': missing,
            'invalid_candles': int(invalid.sum()),
            'raw_close': float(bad['Close']) if isfinite(bad['Close']) else None,
            'adjusted_close': float(bad['Adj Close']) if isfinite(bad['Adj Close']) else None,
            'volume': float(bad['Volume']) if isfinite(bad['Volume']) else None,
        }
        return None, FetchStatus(FETCH_INCOMPLETE_CANDLE, 'invalid Yahoo candle prices or volume', details)

    if len(traded) < 10:
        return None, FetchStatus(FETCH_INSUFFICIENT_HISTORY, f'only {len(traded)} usable candles; minimum is 10')

    # Match yfinance auto_adjust, with the original fields available for validation.
    ratio = traded['Adj Close'] / traded['Close']
    adjusted = traded[['Open', 'High', 'Low']].mul(ratio, axis=0)
    adjusted['Close'] = traded['Adj Close']
    adjusted['Volume'] = traded['Volume']
    return adjusted, FetchStatus(FETCH_OK)


def _extract_symbol_frame(downloaded, symbol, symbol_count):
    if downloaded is None or downloaded.empty:
        return None

    data = None

    if isinstance(downloaded.columns, pd.MultiIndex):
        first_level = downloaded.columns.get_level_values(0)
        second_level = downloaded.columns.get_level_values(1)

        if symbol in first_level:
            data = downloaded[symbol].copy()
        elif symbol in second_level:
            data = downloaded.xs(symbol, axis=1, level=1).copy()
    elif symbol_count == 1:
        data = downloaded.copy()

    return data


def _looks_rate_limited(message):
    text = str(message).lower()
    patterns = [
        '429',
        'too many requests',
        'rate limit',
        'ratelimit',
        'unauthorized',
        'forbidden',
        'crumb',
        'cookie',
        'temporarily unavailable',
    ]
    return any(pattern in text for pattern in patterns)


def _download_symbols(symbols, window, timeout):
    tickers = ' '.join(symbols)
    return yf.download(
        tickers=tickers,
        start=window.start,
        end=window.end,
        interval=window.interval,
        group_by='ticker',
        threads=False,
        progress=False,
        timeout=timeout,
        auto_adjust=False,
    )


def _chunks(items, size):
    for idx in range(0, len(items), size):
        yield items[idx:idx + size]


def fetch_history_batch(
    symbols: Iterable[str],
    timeframe,
    anchor_periods,
    *,
    batch_size=None,
    retries=None,
    pause_seconds=None,
    timeout=None,
    window=None,
):
    """
    Fetch OHLCV history for symbols in yfinance batches.

    Returns:
        tuple(dict[symbol, DataFrame], dict[symbol, FetchStatus])
    """
    symbol_list = list(symbols)
    if not symbol_list:
        return {}, {}

    window = window or get_history_window(timeframe, anchor_periods)
    batch_size = int(batch_size or os.getenv('SCREENER_YF_BATCH_SIZE', '80'))
    retries = int(retries or os.getenv('SCREENER_YF_RETRIES', '3'))
    pause_seconds = float(
        pause_seconds or os.getenv('SCREENER_YF_PAUSE_SECONDS', '0.35')
    )
    timeout = int(timeout or os.getenv('SCREENER_YF_TIMEOUT', '20'))

    histories = {}
    statuses = {}
    incomplete = []

    for chunk_number, chunk in enumerate(_chunks(symbol_list, batch_size), 1):
        last_error = None
        downloaded = None

        for attempt in range(1, retries + 1):
            try:
                downloaded = _download_symbols(chunk, window, timeout)
                if downloaded is not None and not downloaded.empty:
                    last_error = None
                    break

                last_error = 'empty batch response (possible Yahoo throttling/rate limit)'
            except Exception as exc:
                last_error = f'{type(exc).__name__}: {exc}'

            if attempt < retries:
                backoff = (
                    pause_seconds * (2 ** (attempt - 1))
                    + random.uniform(0, pause_seconds)
                )
                print(
                    f"  ↻ yfinance batch {chunk_number} retry {attempt}/{retries} "
                    f"after {last_error}; sleeping {backoff:.2f}s"
                )
                time.sleep(backoff)

        if downloaded is None or downloaded.empty:
            if (
                _looks_rate_limited(last_error)
                or 'empty batch response' in str(last_error)
            ):
                status = FETCH_RATE_LIMITED
            else:
                status = FETCH_ERROR
            message = str(last_error or 'batch download failed')
            for symbol in chunk:
                statuses[symbol] = FetchStatus(status=status, message=message)
        else:
            for symbol in chunk:
                data, status = _clean_history(_extract_symbol_frame(downloaded, symbol, len(chunk)),
                                              daily_cutoff=window.daily_cutoff)
                statuses[symbol] = status
                if status.status == FETCH_INCOMPLETE_CANDLE:
                    incomplete.append(symbol)
                if data is not None:
                    histories[symbol] = data

        if pause_seconds > 0 and chunk_number * batch_size < len(symbol_list):
            time.sleep(pause_seconds)

    if incomplete:
        print(f'Retrying {len(incomplete)} symbols with incomplete Yahoo candles')
    retry_window = window
    if window.daily_cutoff is not None:
        # Yahoo can return blank closes on the final requested day, then return
        # them with a later end date. Keep the scan cutoff when reading the retry.
        retry_window = replace(window, end=window.end + timedelta(days=1))
    for chunk in _chunks(incomplete, min(batch_size, 20)):
        if pause_seconds > 0:
            time.sleep(pause_seconds)
        try:
            downloaded = _download_symbols(chunk, retry_window, timeout)
        except Exception as exc:
            print(f'Incomplete-candle retry failed: {type(exc).__name__}')
            continue
        for symbol in chunk:
            data, status = _clean_history(_extract_symbol_frame(downloaded, symbol, len(chunk)),
                                          daily_cutoff=window.daily_cutoff)
            original_issue = statuses[symbol].candle_issue
            # Keep the original problem if the retry returns no usable history or
            # only an older candle. An older close must not become today's signal.
            if data is not None and data.index[-1].date().isoformat() >= original_issue['latest_returned']:
                histories[symbol] = data
                statuses[symbol] = FetchStatus(FETCH_OK, candle_issue=original_issue, recovered=True)

    return histories, statuses
