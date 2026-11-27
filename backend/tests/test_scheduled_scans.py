import unittest
from collections import Counter
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from screeners.breakout_screener import BreakoutScreener
from screeners.data_fetcher import (
    FETCH_INCOMPLETE_CANDLE, _clean_history, fetch_history_batch, get_history_window,
)
from screeners.nse_daily import NseCandle, NseDailySessions
from screeners.scheduled_watchlists import scheduled_watchlists
from screeners.telegram_notifier import build_scheduled_telegram_message, send_telegram_message


def candles():
    return pd.DataFrame(
        {'Open': 99.0, 'High': 102.0, 'Low': 98.0, 'Close': 100.0,
         'Adj Close': 90.0, 'Volume': 20_000},
        index=pd.date_range('2026-10-01', periods=12),
    )


class CandleTests(unittest.TestCase):
    def test_preserves_price_adjustment_and_rejects_volume_only_row(self):
        frame = candles()
        data, status = _clean_history(frame)
        self.assertEqual(status.status, 'ok')
        self.assertAlmostEqual(data.iloc[-1]['High'], 91.8)
        self.assertEqual(data.iloc[-1]['Volume'], 20_000)
        frame.loc[frame.index[-1], 'Adj Close'] = float('nan')
        data, status = _clean_history(frame)
        self.assertIsNone(data)
        self.assertEqual(status.status, FETCH_INCOMPLETE_CANDLE)
        self.assertEqual(status.candle_issue['invalid_fields'], ['Adj Close'])
        self.assertEqual(status.candle_issue['raw_close'], 100)
        self.assertIsNone(status.candle_issue['adjusted_close'])

    def test_retries_missing_candle_without_falling_back_to_older_data(self):
        complete = candles()
        missing = complete.copy()
        missing.loc[missing.index[-1], ['Close', 'Adj Close']] = float('nan')
        for retry, recovered in [(complete, True), (complete.iloc[:-1], False)]:
            with self.subTest(recovered=recovered), patch(
                'screeners.data_fetcher._download_symbols', side_effect=[missing, retry],
            ) as download, patch('screeners.data_fetcher.time.sleep'):
                data, status = fetch_history_batch(['ABC.NS'], 'daily', [10])
                self.assertEqual(download.call_count, 2)
                self.assertEqual('ABC.NS' in data, recovered)
                self.assertEqual(status['ABC.NS'].recovered, recovered)
                self.assertEqual(status['ABC.NS'].candle_issue['invalid_fields'], ['Close', 'Adj Close'])

    def test_nse_fills_missing_daily_candle_and_keeps_cutoff(self):
        complete = candles()
        complete['Adj Close'] = complete['Close']
        cutoff = datetime(2026, 10, 12)
        window = get_history_window('daily', [10], end=cutoff, completed_sessions_only=True)
        latest, previous = (cutoff.date() - timedelta(days=n) for n in [1, 2])
        candle = NseCandle('ISIN', 100, {'Open': 102, 'High': 106, 'Low': 101, 'Close': 105, 'Volume': 45_000})
        prior = NseCandle('ISIN', 99, {'Close': 100})
        backup = NseDailySessions(latest, {'ABC.NS': candle}, previous, {'ABC.NS': prior})
        bad = complete.copy()
        bad.loc[pd.Timestamp(latest), ['Close', 'Adj Close']] = float('nan')
        for raw in [bad, complete.drop(index=pd.Timestamp(latest))]:
            with self.subTest(rows=len(raw)), patch('screeners.data_fetcher._download_symbols',
                    return_value=raw) as download, patch(
                    'screeners.data_fetcher.load_nse_daily_sessions', return_value=backup):
                data, statuses = fetch_history_batch(['ABC.NS'], 'daily', [10], window=window)
            self.assertEqual(download.call_count, 1)
            self.assertEqual(data['ABC.NS'].index.max().date(), latest)
            self.assertEqual(data['ABC.NS'].iloc[-1]['Close'], 105)
            self.assertEqual(data['ABC.NS'].iloc[-1]['Volume'], 45_000)
            self.assertEqual(statuses['ABC.NS'].recovery_source, 'nse')

        bad.loc[pd.Timestamp(previous), 'Adj Close'] = 95
        with patch('screeners.data_fetcher._download_symbols', return_value=bad), patch(
                'screeners.data_fetcher.load_nse_daily_sessions', return_value=backup), patch(
                'screeners.data_fetcher.time.sleep'):
            data, statuses = fetch_history_batch(['ABC.NS'], 'daily', [10], window=window)
        self.assertNotIn('ABC.NS', data)
        self.assertEqual(statuses['ABC.NS'].status, FETCH_INCOMPLETE_CANDLE)


class WatchlistTests(unittest.TestCase):
    def setUp(self):
        self.screener = SimpleNamespace(market='NSE', market_suffix='.NS', diagnostics={})
        self.config = {'min_turnover': 10_000_000, 'ceiling': 0.1, 'max_failed_attempts': 0,
                       'proximity_low_pct': 0, 'proximity_high_pct': 2, 'max_brief_crosses': 3}

    def test_breakout_ranks_confirmed_retries_and_pending_once(self):
        base = {'status': 'passed', 'avwap': 100, 'close': 105, 'turnover': 20_000_000,
                'distance_pct': 5, 'failed_attempts': 0}
        one = {**base, 'status': 'failed_attempts', 'failed_attempts': 1}
        two = {**one, 'failed_attempts': 2}
        pending = {**base, 'status': 'no_sustained_breakout', 'pending_above': True}
        self.screener.diagnostics = {
            'PURE.NS': {'periods': {180: one, 365: base}},
            'ONE.NS': {'periods': {180: one, 365: two}},
            'TWO.NS': {'periods': {180: two}},
            'EARLY.NS': {'periods': {180: pending}},
            'WEAK.NS': {'periods': {180: {**pending, 'turnover': 1, 'pending_above': False}}},
        }
        tiers = scheduled_watchlists('breakout', self.screener, self.config)
        self.assertEqual([g['symbols'] for g in tiers], [['NSE:PURE'], ['NSE:ONE'], ['NSE:TWO'], ['NSE:EARLY']])

    def test_pending_cross_requires_every_available_close_to_hold(self):
        screener = BreakoutScreener([], 'NSE', 'daily', [10], {'sustain_periods': 3})
        frame = pd.DataFrame({'Close': [99, 101, 99], 'AVWAP': [100, 100, 100]},
                             index=pd.date_range('2026-11-23', periods=3))
        check = {}
        screener._classify_breakouts(frame, frame.index[0], check)
        self.assertEqual(check['pending_crossings'], 1)
        self.assertFalse(check['pending_above'])
        frame.loc[frame.index[-1], 'Close'] = 101
        screener._classify_breakouts(frame, frame.index[0], check)
        self.assertTrue(check['pending_above'])

    def test_pullback_keeps_strict_then_near_then_extra_cross(self):
        base = {'status': 'passed', 'turnover': 20_000_000, 'distance_pct': 2, 'crosses': 3}
        near = {**base, 'status': 'outside_proximity', 'distance_pct': 3}
        extra = {**near, 'status': 'crosses', 'crosses': 4}
        self.screener.diagnostics = {
            'STRICT.NS': {'periods': {180: near, 365: base}},
            'NEAR.NS': {'periods': {180: near, 365: extra}},
            'EXTRA.NS': {'periods': {180: extra}},
            'BELOW.NS': {'periods': {180: {**extra, 'distance_pct': -0.1}}},
            'WIDE.NS': {'periods': {180: {**near, 'distance_pct': 3.01}}},
        }
        tiers = scheduled_watchlists('pullback', self.screener, self.config)
        self.assertEqual([g['symbols'] for g in tiers], [['NSE:STRICT'], ['NSE:NEAR'], ['NSE:EXTRA']])


class TelegramTests(unittest.TestCase):
    def test_one_alert_for_each_strategy_and_timeframe_even_if_long(self):
        for timeframe in ['daily', 'weekly']:
            for logic in ['breakout', 'pullback']:
                for size in [1, 700]:
                    with self.subTest(timeframe=timeframe, logic=logic, size=size):
                        groups = [{'label': 'Strict', 'symbols': ['NSE:ABC']},
                                  {'label': 'Relaxed', 'symbols': [f'NSE:EXTRA{n:03d}' for n in range(size)]}]
                        coverage = {'evaluated': 1000, 'requested': 1010, 'skipped': 10, 'incomplete_candle': 3}
                        message, caption = build_scheduled_telegram_message(
                            groups, coverage, Counter({'2026-11-26': 1000}),
                            {'timeframe': timeframe}, 'NSE', logic, 'scan-id',
                        )
                        self.assertLess(message.index('Strict'), message.index('Relaxed'))
                        self.assertIn('Missing/invalid candle data 3', message)
                        with patch('screeners.telegram_notifier.requests.post') as send:
                            send.return_value = SimpleNamespace(ok=True, status_code=200)
                            self.assertEqual(send_telegram_message(
                                message, 'test', 'test', attachment_caption=caption, scan_id='scan-id',
                            ), 'OK')
                        self.assertEqual(send.call_count, 1)
                        args, kwargs = send.call_args
                        if size == 1:
                            self.assertTrue(args[0].endswith('/sendMessage'))
                            self.assertIn('NSE:EXTRA000', kwargs['json']['text'])
                        else:
                            self.assertTrue(args[0].endswith('/sendDocument'))
                            self.assertIn(b'NSE:EXTRA699', kwargs['files']['document'][1])
