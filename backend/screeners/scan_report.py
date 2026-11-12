"""Scan-specific results, coverage and TradingView output."""
import json
import math
from collections import defaultdict


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
