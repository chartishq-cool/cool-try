"""
Pullback Screener — detects stocks pulling back to AVWAP (within proximity band).
Fully parameterized — timeframe, tolerances, all passed at runtime.
"""

import pandas as pd
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

from screeners.avwap_engine import find_anchor_points, calculate_avwap_low
from screeners.output_formatter import to_tv
from screeners.data_fetcher import (
    FETCH_ERROR,
    FETCH_NO_DATA,
    FETCH_OK,
    FETCH_RATE_LIMITED,
    fetch_history_batch,
    get_history_window,
)


class PullbackScreener:
    """
    Pullback screener for NSE stocks.

    Supports: daily, weekly timeframes
    Parameters: all configurable at runtime (no hardcoding)
    """

    def __init__(self, stocks, market, timeframe, anchor_periods, config):
        self.diagnostics = {}
        self.stocks = stocks
        self.market = market
        self.timeframe = timeframe
        self.anchor_periods = anchor_periods

        self.proximity_low_pct = config.get('proximity_low_pct', 0.0)
        self.proximity_high_pct = config.get('proximity_high_pct', 2.0)
        self.min_turnover = config.get('min_turnover', 10_000_000)
        self.max_brief_crosses = config.get('max_brief_crosses', 5)
        self.min_periods_old = config.get('min_periods_old', 20)

        self.market_suffix = self._get_market_suffix(market)

    def _get_market_suffix(self, market):
        suffix_map = {
            'NSE': '.NS',
            'BSE': '.BO',
            'NASDAQ': '',
            'NYSE': '',
        }
        return suffix_map.get(market, '.NS')

    def _get_data(self, symbol):
        histories, statuses = fetch_history_batch(
            [symbol],
            self.timeframe,
            self.anchor_periods,
            batch_size=1,
        )
        status = statuses.get(symbol)
        if status and status.status != FETCH_OK:
            print(f"  ⚠  {self._fetch_status_label(status)}: {status.message}")

        return histories.get(symbol)

    def _fetch_status_label(self, status):
        if status.status == FETCH_RATE_LIMITED:
            return "Possible rate limit / fetch failed"
        if status.status == FETCH_ERROR:
            return "Fetch error"
        if status.status == FETCH_NO_DATA:
            return "No data"
        return "No data"

    def _check_criteria(self, data, anchor_idx, avwap_series, check):
        """
        Check if stock meets pullback criteria.

        FIX 1: avwap_series is now a pandas Series (from fixed avwap_engine).
                .iloc[i] returns a scalar float, resolving the crash:
                "ValueError: The truth value of a Series is ambiguous"

        FIX 2: Returns raw turnover (not divided by 100k) so the caller
                can compare against self.min_turnover directly.
                The /100_000 division now happens only in _screen_stock
                when building the display field 'Turnover_Lakhs'.

        Returns: (passes, dist_pct_or_msg, raw_turnover, max_consec_below)
        """
        try:
            post_data = data.iloc[anchor_idx + 1:]
            # FIX 1: avwap_series is a Series; .iloc[1:] returns a Series slice
            post_avwap = avwap_series.iloc[1:]

            if post_data.empty:
                check['status'] = 'no_post_anchor_data'
                return False, "No post-anchor data", 0, 0

            closes = post_data['Close']
            # reindex a Series → returns a Series; .iloc[i] is a scalar float
            avwap = post_avwap.reindex(closes.index, method='ffill')

            # Check for consecutive closes below AVWAP
            streaks, cur = [], 0
            for i in range(len(closes)):
                # FIX 1: avwap.iloc[i] is now a scalar — comparison is bool, not Series
                below = (i < len(avwap)) and (closes.iloc[i] < avwap.iloc[i])
                if below:
                    cur += 1
                else:
                    if cur > 0:
                        streaks.append(cur)
                    cur = 0
            if cur > 0:
                streaks.append(cur)

            max_consec = max(streaks) if streaks else 0
            num_crosses = len(streaks)
            # FIX 1: avwap_series.iloc[-1] is now a scalar float
            cmp = data['Close'].iloc[-1]
            avwap_latest = avwap_series.iloc[-1]
            dist = ((cmp - avwap_latest) / avwap_latest) * 100

            check.update(close=float(cmp), avwap=float(avwap_latest), distance_pct=float(dist),
                         crosses=num_crosses, longest_below=max_consec,
                         turnover=float(cmp * data['Volume'].iloc[-1]))
            if num_crosses > self.max_brief_crosses:
                check['status'] = 'crosses'
                return False, f"Crossed below AVWAP {num_crosses} times", 0, max_consec

            if self.proximity_low_pct <= dist <= self.proximity_high_pct:
                check['status'] = 'turnover'
                # FIX 2: return raw turnover — no /100_000 here
                raw_turnover = cmp * data['Volume'].iloc[-1]
                return True, dist, raw_turnover, max_consec

            check['status'] = 'outside_proximity'
            return False, f"Dist {dist:.2f}% out of range", 0, max_consec

        except Exception as e:
            check['status'] = 'calculation_error'
            return False, f"Error: {e}", 0, 0

    def _screen_stock(self, symbol, data):
        results = []
        hits = []
        periods = self.diagnostics.setdefault(symbol, {'periods': {}})['periods']

        for period in self.anchor_periods:
            check = periods[period] = {'status': 'insufficient_history'}
            try:
                anchors = find_anchor_points(data, [period], self.min_periods_old)

                if anchors is None:
                    if period <= self.min_periods_old:
                        check['status'] = 'anchor_age_excludes_window'
                    continue

                for key, info in anchors.items():
                    avwap = calculate_avwap_low(data, anchor_date=info['date'])

                    check.update(anchor=str(info['date'].date()), status='avwap_unavailable',
                                 history_short=len(data) < period)
                    if avwap is None:
                        continue

                    passes, result, raw_turnover, max_below = self._check_criteria(
                        data, info['idx'], avwap, check
                    )

                    # FIX 2: compare raw_turnover against self.min_turnover (both raw)
                    # Previously: turnover was in lakhs, min_turnover was raw → always False
                    if passes and raw_turnover >= self.min_turnover:
                        check['status'] = 'passed'
                        if self.timeframe == 'daily':
                            period_label = f"{period}d"
                        elif self.timeframe == 'weekly':
                            period_label = f"{period}w"
                        else:
                            period_label = f"{period}mo"

                        results.append({
                            '_period_num': period,
                            'Symbol': symbol.replace(self.market_suffix, ''),
                            'TV_Symbol': to_tv(symbol.replace(self.market_suffix, ''), self.market_suffix, self.market),
                            'Timeframe': self.timeframe.upper(),
                            'Anchor_Period': period_label,
                            'Current_Price': round(data['Close'].iloc[-1], 2),
                            # FIX 1: avwap.iloc[-1] is now a scalar float
                            'AVWAP': round(avwap.iloc[-1], 2),
                            'Distance_%': round(result, 2),
                            # FIX 2: divide by 100_000 only here for display
                            'Turnover_Lakhs': round(raw_turnover / 100_000, 1),
                            'Anchor_Date': info['date'].strftime('%d-%m-%Y'),
                            'Anchor_Low': round(info['low'], 2),
                            'Days_Since_Anchor': info['days_old'],
                            'Max_Bars_Below': max_below,
                        })

            except Exception:
                check['status'] = 'calculation_error'
                continue

        # FIX 3: find_anchor_points() only dedupes across periods passed to it
        # in a single call. Here it's called once per period (a 1-item list
        # each time), so its internal "same anchor date -> keep one" logic
        # never has more than one candidate to compare and is effectively a
        # no-op. As a result, a stock whose 52w/104w/156w low all happen to
        # be the same historical bar produced one near-identical result row
        # per period -- surfacing as duplicate entries in the Telegram message.
        # Dedupe here across all periods for this symbol: when multiple
        # periods resolve to the same Anchor_Date, keep only the shortest
        # (smallest) period.
        best_by_date = {}
        for r in results:
            d = r['Anchor_Date']
            if d not in best_by_date or r['_period_num'] < best_by_date[d]['_period_num']:
                best_by_date[d] = r
        results = list(best_by_date.values())

        for r in results:
            del r['_period_num']
            hits.append(f"{r['Anchor_Period']}:✅({r['Distance_%']:.1f}%)")

        return results, hits

    def run(self, history_batch=None):
        self.diagnostics = {}
        all_results = []

        print(f"\n{'═'*60}")
        print(f"  {self.market} {self.timeframe.upper()} PULLBACK SCREENER")
        print(f"  {datetime.now().strftime('%d %b %Y  %H:%M')}")
        print(f"{'═'*60}")
        print(f"  Stocks: {len(self.stocks)}")
        print(f"  Anchors: {self.anchor_periods}")
        print(f"  Proximity: {self.proximity_low_pct}%-{self.proximity_high_pct}%")
        print(f"{'═'*60}\n")

        histories, fetch_statuses = history_batch if history_batch is not None else fetch_history_batch(
            self.stocks,
            self.timeframe,
            self.anchor_periods,
            window=get_history_window(self.timeframe, self.anchor_periods, pullback=True),
        )

        for idx, stock in enumerate(self.stocks, 1):
            print(f"  [{idx:>3}/{len(self.stocks)}]  {stock:<18}", end="", flush=True)

            data = histories.get(stock)
            if data is None:
                status = fetch_statuses.get(stock)
                self.diagnostics[stock] = {'status': status.status if status else 'fetch_error'}
                if status is None:
                    print("  ⚠  Fetch error: missing fetch status")
                elif status.status == FETCH_NO_DATA:
                    print("  ⚠  No data")
                else:
                    message = f": {status.message}" if status.message else ""
                    print(f"  ⚠  {self._fetch_status_label(status)}{message}")
                continue

            self.diagnostics[stock] = {'status': 'evaluated', 'bars': len(data), 'periods': {}}
            results, hits = self._screen_stock(stock, data)
            all_results.extend(results)

            if hits:
                print("  →  " + "  ".join(hits))
            else:
                print("  —  no match")

        cols = [
            'Symbol', 'TV_Symbol', 'Timeframe', 'Anchor_Period',
            'Current_Price', 'AVWAP', 'Distance_%', 'Turnover_Lakhs',
            'Anchor_Date', 'Anchor_Low', 'Days_Since_Anchor', 'Max_Bars_Below',
        ]

        if all_results:
            df = pd.DataFrame(all_results, columns=cols)
            df = df.sort_values(['Turnover_Lakhs'], ascending=[False])
        else:
            df = pd.DataFrame(columns=cols)

        return df
