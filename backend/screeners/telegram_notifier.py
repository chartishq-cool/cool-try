"""
Telegram Notifier — sends scan results to Telegram bot.
Formats messages for both breakout and pullback results.
"""

import requests
from datetime import datetime


def send_telegram_message(message, bot_token, chat_id, *, plain=False):
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        
        # Split into ≤4096-char chunks, breaking at newlines
        MAX_LEN = 4000  # safe margin below 4096
        chunks = []
        current = ""
        for line in message.split("\n"):
            addition = (line + "\n")
            if len(current) + len(addition) > MAX_LEN:
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
                    **({} if plain else {"parse_mode": "Markdown"}),
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


def build_breakout_telegram_message(df_results, anchor_periods, config, market='NSE'):
    """
    Build Telegram message for breakout results.
    Groups by Pure/Retry, then by anchor period.
    """
    SEP = "─" * 30

    if df_results.empty:
        return (
            f"📡 *{market} Breakout Scanner*\n"
            f"📅 {datetime.now().strftime('%d %b %Y')}\n\n"
            f"❌ No stocks matched the criteria today."
        )

    today = datetime.now().strftime('%d %b %Y')
    pure = df_results[df_results['Failed Attempts'] == 0]
    retry = df_results[df_results['Failed Attempts'] > 0]
    anchors_str = ', '.join(str(p) for p in anchor_periods)

    timeframe = config.get('timeframe', 'N/A')
    tolerance = config.get('tolerance_below_avwap', 0)
    ceiling = config.get('ceiling', 0)
    sustain = config.get('sustain_periods', 0)

    lines = [
        f"📡 *{market} Breakout Scanner*",
        f"📅 {today}  |  Timeframe: {timeframe}  |  Anchors: {anchors_str}",
        f"⏱ Sustain: {sustain}  |  Ceiling: {ceiling*100:.0f}%  |  Tolerance: {tolerance*100:.0f}%",
    ]

    if not pure.empty:
        lines += [
            f"\n{SEP}",
            f"✅ *PURE FIRST BREAKS*  _({len(pure)} stocks)_",
            SEP,
        ]
        for period in anchor_periods:
            grp = pure[pure['Anchor Period'] == period]
            if not grp.empty:
                syms = ", ".join(grp['TV Symbol'].tolist())
                lines.append(f"*{period}* →  {syms}")
                lines.append("")

    if not retry.empty:
        lines += [
            f"\n{SEP}",
            f"🔁 *RETRY BREAKS*  _({len(retry)} stocks)_",
            SEP,
        ]
        max_attempts = int(df_results['Failed Attempts'].max())
        for attempt in range(1, max_attempts + 1):
            grp = retry[retry['Failed Attempts'] == attempt]
            if not grp.empty:
                fail_label = "1 Fail" if attempt == 1 else f"{attempt} Fails"
                syms = ", ".join(grp['TV Symbol'].tolist())
                lines.append(f"*{fail_label}* →  {syms}")
                lines.append("")

    lines += [
        f"\n{SEP}",
        f"📊 Total: {len(df_results)}   ✅ Pure: {len(pure)}   🔁 Retry: {len(retry)}",
        SEP,
    ]

    return "\n".join(lines)


def build_pullback_telegram_message(df_results, anchor_periods, config, market='NSE'):
    """
    Build Telegram message for pullback results.
    Groups by anchor period.

    FIX 1: anchor_periods is a list of ints (e.g. [52, 156]) but the
            DataFrame column 'Anchor_Period' contains strings like '52d' or '52w'.
            Filtering df[df['Anchor_Period'] == 52] always returns empty rows.
            Now iterates unique values directly from the DataFrame.

    FIX 2: config has no 'proximity_band' key — it has 'proximity_low_pct'
            and 'proximity_high_pct'. The old code always showed the
            hardcoded default '0-2%' regardless of actual settings.
    """
    SEP = "─" * 30

    if df_results.empty:
        return (
            f"📡 *{market} Pullback Scanner*\n"
            f"📅 {datetime.now().strftime('%d %b %Y')}\n\n"
            f"❌ No stocks matched the criteria today."
        )

    today = datetime.now().strftime('%d %b %Y')
    anchors_str = ', '.join(str(p) for p in anchor_periods)

    # FIX 2: build proximity string from the keys that actually exist in config
    prox_low = config.get('proximity_low_pct', 0.0)
    prox_high = config.get('proximity_high_pct', 2.0)
    proximity = f"{prox_low}%-{prox_high}%"

    lines = [
        f"📡 *{market} Pullback Scanner*",
        f"📅 {today}  |  Anchors: {anchors_str}",
        f"🎯 Proximity band: {proximity}  |  Total hits: {len(df_results)}",
        f"\n{SEP}",
    ]

    # FIX 1: iterate unique period labels from the actual DataFrame column
    # ('52d', '156d', etc.) instead of filtering by raw ints (52, 156, etc.)
    # Preserve the order by using anchor_periods as a reference.
    seen_labels = set()
    for period_int in anchor_periods:
        for suffix in ('d', 'w', 'mo'):
            label = f"{period_int}{suffix}"
            if label in seen_labels:
                continue
            grp = df_results[df_results['Anchor_Period'] == label]
            if not grp.empty:
                seen_labels.add(label)
                syms = ", ".join(grp['TV_Symbol'].tolist())
                lines.append(f"*{label}* →  {syms}")
                lines.append("")

    lines.append(SEP)

    return "\n".join(lines)
