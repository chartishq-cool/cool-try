"""
Shared AVWAP Engine — used by both breakout and pullback screeners.
Provides AVWAP calculation and anchor point finding logic.
"""

import pandas as pd


def calculate_avwap(df, anchor_date):
    """
    Calculate AVWAP anchored at a specific date, using High as typical price.

    Args:
        df: DataFrame with High, Volume columns indexed by date
        anchor_date: Start date for AVWAP calculation

    Returns:
        Named Series with AVWAP values indexed from anchor_date onwards, or None if error.

    FIX: Previously returned df_f[['AVWAP']] (a single-column DataFrame).
         DataFrame.join() accepts a named Series directly, and all downstream
         .iloc[-1] calls now return a scalar instead of a pandas row-Series,
         preventing "ValueError: The truth value of a Series is ambiguous".
    """
    try:
        df_f = df.loc[anchor_date:].copy()
        if df_f.empty or len(df_f) < 1:
            return None

        df_f['cum_vol_tp'] = (df_f['High'] * df_f['Volume']).cumsum()
        df_f['cum_vol'] = df_f['Volume'].cumsum()
        df_f['AVWAP'] = df_f['cum_vol_tp'] / df_f['cum_vol']

        # FIX: return Series (single bracket), not DataFrame (double bracket)
        return df_f['AVWAP']
    except Exception:
        return None


def calculate_avwap_low(df, anchor_date):
    """
    Calculate AVWAP anchored at a specific date, using Low as typical price.
    Used by pullback screeners.

    Args:
        df: DataFrame with Low, Volume columns indexed by date
        anchor_date: Start date for AVWAP calculation

    Returns:
        Named Series with AVWAP values indexed from anchor_date onwards, or None if error.

    FIX: Same as calculate_avwap — returns Series instead of DataFrame.
         This fixes the crash in pullback_screener._check_criteria where
         avwap_series.iloc[-1] was returning a row-Series instead of a float,
         causing chained comparisons to raise ValueError.
    """
    try:
        df_f = df.loc[anchor_date:].copy()
        if df_f.empty or len(df_f) < 1:
            return None

        df_f['cum_vol_tp'] = (df_f['Low'] * df_f['Volume']).cumsum()
        df_f['cum_vol'] = df_f['Volume'].cumsum()
        df_f['AVWAP'] = df_f['cum_vol_tp'] / df_f['cum_vol']

        # FIX: return Series (single bracket), not DataFrame (double bracket)
        return df_f['AVWAP']
    except Exception:
        return None


def find_anchor_points(data, lookback_periods, min_periods_old):
    """
    Find anchor points (lowest Low) for each lookback period.
    Excludes the most recent `min_periods_old` bars to allow anchor to develop.

    Args:
        data: DataFrame with Low column
        lookback_periods: List of periods (e.g., [52, 156, 260] for weeks)
        min_periods_old: Minimum age of anchor in periods

    Returns:
        Dictionary with period as key, containing idx, date, low, days_old, etc.
        Returns None if no valid anchors found.
    """
    try:
        anchors = {}
        for period in lookback_periods:
            recent = data.tail(period)
            if len(recent) <= min_periods_old:
                continue

            candidates = recent.iloc[:-min_periods_old] if min_periods_old else recent
            if candidates.empty:
                continue

            min_date = candidates['Low'].idxmin()
            anchor_idx = data.index.get_loc(min_date)
            days_old = (data.index[-1] - min_date).days
            bars_old = len(data.loc[min_date:]) - 1
            if bars_old >= min_periods_old:
                anchors[str(period)] = {
                    'idx': anchor_idx,
                    'date': min_date,
                    'low': candidates['Low'].min(),
                    'period': period,
                    'days_old': days_old,
                }

        return anchors if anchors else None
    except Exception:
        return None
