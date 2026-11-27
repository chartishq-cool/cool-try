"""
Telegram Notifier — sends scan results to Telegram bot.
Formats messages for both breakout and pullback results.
"""

import requests
from datetime import datetime, timedelta, timezone
from html import escape, unescape
import re


MESSAGE_LIMIT = 4000
def _message_length(text):
    return len(text.encode('utf-16-le')) // 2


PERIOD_SUFFIXES = {'daily': 'd', 'weekly': 'w', 'monthly': 'mo'}


def send_telegram_message(message, bot_token, chat_id, *, attachment_caption=None, scan_id=None):
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        if attachment_caption is not None and _message_length(message) > MESSAGE_LIMIT:
            # Telegram limits a text message to 4096 characters. A single attachment
            # keeps the four scheduled alerts intact without leaving out any stocks.
            plain_text = unescape(re.sub(r'<[^>]+>', '', message))
            response = requests.post(
                url.removesuffix('sendMessage') + 'sendDocument',
                data={'chat_id': chat_id, 'caption': attachment_caption, 'parse_mode': 'HTML'},
                files={'document': (f'argus-{scan_id}.txt', plain_text.encode('utf-8'), 'text/plain')},
                timeout=15,
            )
            return 'OK' if response.ok else f'Attachment failed: HTTP {response.status_code}'
        
        # Split into ≤4096-char chunks, breaking at newlines
        chunks = []
        current = ""
        for line in message.splitlines():
            addition = (line + "\n")
            if current and _message_length(current + addition) > MESSAGE_LIMIT:
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
                    "parse_mode": "HTML",
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
    lines.extend(["", "<b>Copy for TradingView</b>"])
    batch = ""
    for symbol in symbols:
        symbol = escape(str(symbol))
        next_batch = f"{batch}, {symbol}" if batch else symbol
        if _message_length(next_batch) + len("<pre></pre>") + 1 > MESSAGE_LIMIT:
            if batch:
                lines.append(f"<pre>{batch}</pre>")
            batch = symbol
        else:
            batch = next_batch
    if batch:
        lines.append(f"<pre>{batch}</pre>")


def build_scheduled_telegram_message(watchlists, coverage, candle_dates, config, market, logic, scan_id):
    timeframe = config['timeframe']
    lines = [
        f'<b>{escape(market)} · {escape(timeframe.title())} {escape(logic.title())}</b>',
        f'Scan ID: <code>{escape(scan_id)}</code>',
        datetime.now(timezone(timedelta(hours=5, minutes=30))).strftime('%d %b %Y · %I:%M %p IST'),
    ]
    if candle_dates:
        date, count = candle_dates.most_common(1)[0]
        others = coverage['evaluated'] - count
        lines.append(f'Latest candle for most stocks: {date}' + (f' · {others} on other dates' if others else ''))
        if timeframe == 'weekly':
            lines.append('Weekly dates mark the start of the candle.')
    lines.append(
        f"Checked {coverage['evaluated']:,}/{coverage['requested']:,} · "
        f"Missing/invalid candle data {coverage.get('incomplete_candle', 0):,} · "
        f"Recovered {coverage.get('recovered_symbols', 0):,} · "
        f"Other skips {coverage['skipped'] - coverage.get('incomplete_candle', 0):,}"
    )
    if coverage.get('nse_recovered_symbols'):
        lines.append(f"Recovered from NSE official candles: {coverage['nse_recovered_symbols']:,}")
    caption = lines + ['']
    for group in watchlists:
        heading = f"<b>{escape(group['label'])} ({len(group['symbols'])})</b>"
        caption.append(heading)
        lines.extend(['', heading])
        if group['symbols']:
            _append_symbols(lines, group['symbols'])
    caption.append('Full TradingView lists in the attached file.')
    return '\n'.join(lines), '\n'.join(caption)


def _append_results(lines, df_results, symbol_col, period_col, periods):
    symbols = {}
    by_period = {}
    if not df_results.empty:
        for symbol, period in zip(df_results[symbol_col], df_results[period_col]):
            symbols[symbol] = None
            by_period.setdefault(period, set()).add(symbol)
    lines.extend(["", "<b>Stocks by anchor</b>", " · ".join(
        f"{escape(str(label))}: <b>{len(by_period.get(key, ()))}</b>" for key, label in periods
    )])
    if not symbols:
        lines.extend(["", "<b>0 stocks matched</b>"])
        return "\n".join(lines)

    summary = f"<b>{len(symbols)} unique stocks</b>"
    if 'Failed Attempts' in df_results.columns:
        pure = len({
            symbol for symbol, attempts in zip(df_results[symbol_col], df_results['Failed Attempts'])
            if attempts == 0
        })
        summary += f" · Pure {pure} · Retry only {len(symbols) - pure}"
    lines.extend(['', summary])
    _append_symbols(lines, symbols)
    return "\n".join(lines)


def build_breakout_telegram_message(df_results, anchor_periods, config, market='NSE'):
    timeframe = config.get('timeframe', 'N/A')
    suffix = PERIOD_SUFFIXES.get(timeframe, '')
    tolerance = config.get('tolerance_below_avwap', 0)
    ceiling = config.get('ceiling', 0)
    sustain = config.get('sustain_periods', 0)
    lines = [
        f"<b>{escape(str(market))} · {escape(str(timeframe).title())} Breakout</b>",
        f"{datetime.now(timezone(timedelta(hours=5, minutes=30))).strftime('%d %b %Y · %I:%M %p')} IST",
        "",
        f"Sustain <b>{escape(str(sustain))}</b> · Ceiling <b>{ceiling*100:g}%</b> · Tolerance <b>{tolerance*100:g}%</b>",
    ]
    periods = [(period, f"{period}{suffix}") for period in dict.fromkeys(anchor_periods)]
    return _append_results(lines, df_results, 'TV Symbol', 'Anchor Period', periods)


def build_pullback_telegram_message(df_results, anchor_periods, config, market='NSE'):
    timeframe = config.get('timeframe', 'N/A')
    suffix = PERIOD_SUFFIXES.get(timeframe)
    prox_low = config.get('proximity_low_pct', 0.0)
    prox_high = config.get('proximity_high_pct', 2.0)
    lines = [
        f"<b>{escape(str(market))} · {escape(str(timeframe).title())} Pullback</b>",
        f"{datetime.now(timezone(timedelta(hours=5, minutes=30))).strftime('%d %b %Y · %I:%M %p')} IST",
        "",
        f"Proximity <b>{escape(str(prox_low))}%–{escape(str(prox_high))}%</b>",
    ]
    suffixes = [suffix] if suffix else PERIOD_SUFFIXES.values()
    labels = [f"{period}{unit}" for period in dict.fromkeys(anchor_periods) for unit in suffixes]
    return _append_results(lines, df_results, 'TV_Symbol', 'Anchor_Period', [(label, label) for label in labels])
