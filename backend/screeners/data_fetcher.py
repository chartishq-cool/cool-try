"""
Shared yfinance data fetch helpers for screeners.

The screeners scan thousands of symbols. Fetching each symbol through a fresh
Ticker.history call can trigger transient Yahoo/yfinance throttling, after which
all remaining symbols often look like ordinary "No data" symbols. This module
centralizes batched downloads, retries, and explicit fetch-status reporting so
screening logic can stay unchanged while data failures are easier to diagnose.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import os
import random
import time
from typing import Iterable

from dateutil.relativedelta import relativedelta
import pandas as pd
import yfinance as yf

REQUIRED_COLUMNS = ['High', 'Low', 'Close', 'Volume']
FETCH_OK = 'ok'
FETCH_NO_DATA = 'no_data'
FETCH_INSUFFICIENT_HISTORY = 'insufficient_history'
FETCH_ERROR = 'fetch_error'
FETCH_RATE_LIMITED = 'rate_limited'


@dataclass(frozen=True)
class HistoryWindow:
    start: datetime
    end: datetime
    interval: str


@dataclass
class FetchStatus:
    status: str
    message: str = ''


def get_history_window(timeframe, anchor_periods, *, end=None):
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

    return HistoryWindow(start=start, end=end, interval=interval)


def _clean_history(data):
    if data is None or data.empty:
        return None

    if not all(c in data.columns for c in REQUIRED_COLUMNS):
        return None

    cleaned = data[data['Volume'] > 0]
    if cleaned.empty:
        return None

    return cleaned


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

    return _clean_history(data)


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
        auto_adjust=True,
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
                data = _extract_symbol_frame(downloaded, symbol, len(chunk))
                if data is None:
                    statuses[symbol] = FetchStatus(
                        status=FETCH_NO_DATA,
                        message='no usable OHLCV data for symbol',
                    )
                elif len(data) < 10:
                    statuses[symbol] = FetchStatus(
                        status=FETCH_INSUFFICIENT_HISTORY,
                        message=f'only {len(data)} usable candles; minimum is 10',
                    )
                else:
                    histories[symbol] = data
                    statuses[symbol] = FetchStatus(status=FETCH_OK)

        if pause_seconds > 0 and chunk_number * batch_size < len(symbol_list):
            time.sleep(pause_seconds)

    return histories, statuses
