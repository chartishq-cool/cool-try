"""
Telegram Notifier — sends scan results to Telegram bot.
Formats messages for both breakout and pullback results.
"""

import requests
from datetime import datetime


MESSAGE_LIMIT = 4000
PERIOD_SUFFIXES = {'daily': 'd', 'weekly': 'w', 'monthly': 'mo'}


def send_telegram_message(message, bot_token, chat_id):
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        
        # Split into ≤4096-char chunks, breaking at newlines
        chunks = []
        current = ""
        for line in message.splitlines():
            addition = (line + "\n")
            if current and len(current) + len(addition) > MESSAGE_LIMIT:
                chunks.append(current.rstrip())
                current = addition
            else:
                current += addition
        if current.strip():
            chunks.append(current.rstrip())

        for i, chunk in enumerate(chunks):
            resp = requests.post(
                url,
                json={
                    "chat_id": chat_id,
                    "text": chunk,
                    "disable_web_page_preview": True,
                },
                timeout=10,
            )
            print(f"Telegram chunk {i+1}/{len(chunks)} status: {resp.status_code}")
            if resp.status_code != 200:
                return f"Failed on chunk {i+1}: {resp.text}"

        return "OK"

    except Exception as e:
        return f"Error: {type(e).__name__}"


def _append_symbols(lines, symbols):
    lines.extend(["", "TradingView symbols"])
    batch = ""
    for symbol in symbols:
        next_batch = f"{batch}, {symbol}" if batch else symbol
        if len(next_batch) >= MESSAGE_LIMIT:
            lines.append(batch)
            batch = symbol
        else:
            batch = next_batch
    if batch:
        lines.append(batch)


def _append_results(lines, df_results, symbol_col, period_col, periods):
    symbols = {}
    by_period = {}
    if not df_results.empty:
        for symbol, period in zip(df_results[symbol_col], df_results[period_col]):
            symbols[symbol] = None
            by_period.setdefault(period, set()).add(symbol)
    lines.append("Anchor counts: " + " · ".join(
        f"{label}: {len(by_period.get(key, ()))}" for key, label in periods
    ))
    if not symbols:
        lines.append("❌ No stocks matched the criteria today.")
        return "\n".join(lines)

    summary = f"📊 Total unique stocks: {len(symbols)}"
    if 'Failed Attempts' in df_results.columns:
        pure = len({
            symbol for symbol, attempts in zip(df_results[symbol_col], df_results['Failed Attempts'])
            if attempts == 0
        })
        summary += f"  |  Pure: {pure}  |  Retry only: {len(symbols) - pure}"
    lines.append(summary)
    _append_symbols(lines, symbols)
    return "\n".join(lines)


def build_breakout_telegram_message(df_results, anchor_periods, config, market='NSE'):
    timeframe = config.get('timeframe', 'N/A')
    suffix = PERIOD_SUFFIXES.get(timeframe, '')
    tolerance = config.get('tolerance_below_avwap', 0)
    ceiling = config.get('ceiling', 0)
    sustain = config.get('sustain_periods', 0)
    lines = [
        f"📡 {market} Breakout Scanner",
        f"📅 {datetime.now().strftime('%d %b %Y')}  |  Timeframe: {timeframe}",
        f"⏱ Sustain: {sustain}  |  Ceiling: {ceiling*100:.0f}%  |  Tolerance: {tolerance*100:.0f}%",
    ]
    periods = [(period, f"{period}{suffix}") for period in dict.fromkeys(anchor_periods)]
    return _append_results(lines, df_results, 'TV Symbol', 'Anchor Period', periods)


def build_pullback_telegram_message(df_results, anchor_periods, config, market='NSE'):
    timeframe = config.get('timeframe', 'N/A')
    suffix = PERIOD_SUFFIXES.get(timeframe)
    prox_low = config.get('proximity_low_pct', 0.0)
    prox_high = config.get('proximity_high_pct', 2.0)
    lines = [
        f"📡 {market} Pullback Scanner",
        f"📅 {datetime.now().strftime('%d %b %Y')}  |  Timeframe: {timeframe}",
        f"🎯 Proximity band: {prox_low}%-{prox_high}%",
    ]
    suffixes = [suffix] if suffix else PERIOD_SUFFIXES.values()
    labels = [f"{period}{unit}" for period in dict.fromkeys(anchor_periods) for unit in suffixes]
    return _append_results(lines, df_results, 'TV_Symbol', 'Anchor_Period', [(label, label) for label in labels])
