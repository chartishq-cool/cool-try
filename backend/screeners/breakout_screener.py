"""
Breakout Screener — detects AVWAP breakouts across all timeframes.
Fully parameterized — timeframe, tolerances, ceilings all passed at runtime.
"""

import pandas as pd
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

from screeners.avwap_engine import calculate_avwap
from screeners.output_formatter import to_tv, format_date
from screeners.data_fetcher import (
    FETCH_ERROR,
    FETCH_NO_DATA,
    FETCH_OK,
    FETCH_RATE_LIMITED,
    fetch_history_batch,
)


class BreakoutScreener:
    """
    Breakout screener for NSE stocks.

    Supports: daily, weekly, monthly timeframes
    Parameters: all configurable at runtime (no hardcoding)

    NOTE on avwap_engine change:
    calculate_avwap() now returns a named pandas Series instead of a
    single-column DataFrame. pandas DataFrame.join(Series) works identically
    to DataFrame.join(DataFrame) when the Series has a name — it uses the
    Series name as the column name. So data.join(avwap_series) below is
    correct and produces the same 'AVWAP' column as before.
    """

    def __init__(self, stocks, market, timeframe, anchor_periods, config):
        self.diagnostics = {}
        self.stocks = stocks
        self.market = market
        self.timeframe = timeframe
        self.anchor_periods = anchor_periods

        self.tolerance_below_avwap = config.get('tolerance_below_avwap', 0.05)
        self.ceiling = config.get('ceiling', 0.10)
        self.sustain_periods = config.get('sustain_periods', 3)
        self.max_failed_attempts = config.get('max_failed_attempts', 2)
        self.min_turnover = config.get('min_turnover', 10_000_000)

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

    def _classify_breakouts(self, df_avwap, start_date, check=None):
        """
        Classify breakouts: find first successful crossover above AVWAP.

        Returns: (failed_count, successful_date, failed_dates)
        """
        sub = df_avwap.loc[start_date:].copy()
        if sub.empty:
            return 0, None, []

        above = (sub['Close'] > sub['AVWAP']).infer_objects(copy=False)
        prev = above.shift(1).infer_objects(copy=False).fillna(False)
        crossings = above & (~prev)
        crossing_dates = sub.index[crossings].tolist()

        if above.iloc[0]:
            crossing_dates = [sub.index[0]] + [d for d in crossing_dates if d != sub.index[0]]

        if check is not None:
            check.update(crossings=len(crossing_dates), pending_crossings=0,
                         sustain_failures=0, tolerance_failures=0)

        failed_count = 0
        failed_dates = []
        successful_date = None

        for cd in crossing_dates:
            future = df_avwap.loc[cd:]

            sustain_slice = future.iloc[:self.sustain_periods]
            if len(sustain_slice) < self.sustain_periods:
                if check is not None:
                    check['pending_crossings'] += 1
                continue

            if not (sustain_slice['Close'] > sustain_slice['AVWAP']).all():
                if check is not None:
                    check['sustain_failures'] += 1
                failed_count += 1
                failed_dates.append(cd)
                continue

            post_sustain = future.iloc[self.sustain_periods:]
            if post_sustain.empty:
                successful_date = cd
                break

            fell_below = post_sustain['Close'] < (
                post_sustain['AVWAP'] * (1 - self.tolerance_below_avwap)
            )
            if fell_below.any():
                if check is not None:
                    check['tolerance_failures'] += 1
                failed_count += 1
                failed_dates.append(cd)
            else:
                successful_date = cd
                break

        return failed_count, successful_date, failed_dates

    def _screen_stock(self, symbol, data):
        results = []
        hits = []
        periods = self.diagnostics.setdefault(symbol, {'periods': {}})['periods']
        end_date = datetime.now().date()

        for period in self.anchor_periods:
            check = periods[period] = {'status': 'insufficient_history'}
            try:
                if self.timeframe == 'daily':
                    anchor_date = end_date - timedelta(days=period)
                elif self.timeframe == 'weekly':
                    anchor_date = end_date - timedelta(weeks=period)
                elif self.timeframe == 'monthly':
                    anchor_date = end_date - relativedelta(months=period)
                else:
                    continue

                ts = pd.Timestamp(anchor_date)
                if data.index.tz is not None:
                    ts = ts.tz_localize(data.index.tz)

                if ts < data.index[0]:
                    continue

                earlier = data.index[data.index <= ts]
                closest = earlier[-1] if len(earlier) > 0 else data.index[0]
                df_anchor = data.loc[closest:]

                if df_anchor.empty:
                    continue

                hh_date = df_anchor['High'].idxmax()

                # avwap_series is now a named pandas Series (name='AVWAP').
                # DataFrame.join(named_Series) adds it as column 'AVWAP' — correct.
                avwap_series = calculate_avwap(data, anchor_date=hh_date)

                check.update(anchor=str(hh_date.date()), status='avwap_unavailable')
                if avwap_series is None:
                    continue

                df_avwap = data.join(avwap_series).dropna(subset=['AVWAP'])

                if df_avwap.empty:
                    continue

                failed_count, success_date, _ = self._classify_breakouts(df_avwap, hh_date, check)

                latest_date = df_avwap.index[-1]
                latest_close = df_avwap.loc[latest_date, 'Close']
                latest_avwap = df_avwap.loc[latest_date, 'AVWAP']
                latest_vol = df_avwap.loc[latest_date, 'Volume']
                turnover = latest_close * latest_vol

                check.update(close=float(latest_close), avwap=float(latest_avwap), turnover=float(turnover),
                             distance_pct=float((latest_close / latest_avwap - 1) * 100) if latest_avwap else None,
                             failed_attempts=failed_count)
                if success_date is None:
                    check['status'] = 'no_sustained_breakout'
                    continue
                if failed_count > self.max_failed_attempts:
                    check['status'] = 'failed_attempts'
                    continue
                if turnover < self.min_turnover:
                    check['status'] = 'turnover'
                    continue

                in_range = (latest_close > latest_avwap) and \
                           (latest_close <= latest_avwap * (1 + self.ceiling))

                if not in_range:
                    check['status'] = 'outside_ceiling'
                    continue
                check['status'] = 'passed'

                pct_diff = ((latest_close - latest_avwap) / latest_avwap) * 100

                if self.timeframe == 'daily':
                    periods_held = (latest_date - success_date).days
                    period_label = f"{period}d"
                elif self.timeframe == 'weekly':
                    periods_held = round((latest_date - success_date).days / 7)
                    period_label = f"{period}wk"
                else:
                    periods_held = round((latest_date - success_date).days / 30)
                    period_label = f"{period}mo"

                break_type = (
                    "PURE FIRST BREAK"
                    if failed_count == 0
                    else f"RETRY BREAK (attempt #{failed_count + 1})"
                )

                results.append({
                    'Stock': symbol.replace(self.market_suffix, ''),
                    'TV Symbol': to_tv(symbol.replace(self.market_suffix, ''), self.market_suffix, self.market),
                    'Anchor Period': period,
                    'Break Type': break_type,
                    'Failed Attempts': failed_count,
                    'Highest High Date': hh_date,
                    'Successful Breakout': success_date,
                    'Periods Held': periods_held,
                    'CMP': round(latest_close, 2),
                    'AVWAP': round(latest_avwap, 2),
                    '% Above AVWAP': round(pct_diff, 2),
                    'Ceiling Used': f"{self.ceiling*100:.0f}%",
                    'Turnover (₹)': f"{turnover:,.0f}",
                })

                hits.append(f"{period_label}:{'✅' if failed_count == 0 else '🔁'}")

            except Exception:
                check['status'] = 'calculation_error'
                continue

        return results, hits

    def run(self, history_batch=None):
        self.diagnostics = {}
        all_results = []

        print(f"\n{'═'*60}")
        print(f"  {self.market} {self.timeframe.upper()} AVWAP BREAKOUT SCANNER")
        print(f"  {datetime.now().strftime('%d %b %Y  %H:%M')}")
        print(f"{'═'*60}")
        print(f"  Stocks: {len(self.stocks)}")
        print(f"  Anchors: {self.anchor_periods}")
        print(f"  Sustain: {self.sustain_periods}  |  Ceiling: {self.ceiling*100:.0f}%")
        print(f"{'═'*60}\n")

        histories, fetch_statuses = history_batch if history_batch is not None else fetch_history_batch(
            self.stocks,
            self.timeframe,
            self.anchor_periods,
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

        if all_results:
            df = pd.DataFrame(all_results)
            df['Highest High Date'] = pd.to_datetime(df['Highest High Date'])
            df['Successful Breakout'] = pd.to_datetime(df['Successful Breakout'])
            df = df.sort_values(['Stock', 'Highest High Date', 'Successful Breakout', 'Anchor Period'])
            df = df.drop_duplicates(
                subset=['Stock', 'Highest High Date', 'Successful Breakout'],
                keep='first'
            )
            df['_sort_key'] = df['Failed Attempts']
            df = df.sort_values(['_sort_key', 'Anchor Period', 'Successful Breakout'])
            df = df.drop(columns=['_sort_key'])
            df['Highest High Date'] = df['Highest High Date'].apply(format_date)
            df['Successful Breakout'] = df['Successful Breakout'].apply(format_date)
        else:
            df = pd.DataFrame()

        return df
