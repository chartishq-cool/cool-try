"""Refresh exchange ticker snapshots, keeping the previous snapshot on error."""
import csv
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import re

import requests


ROOT = Path(__file__).resolve().parent / 'stock_lists'
SOURCES = {
    'NSE': 'https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv',
    'BSE': 'https://api.bseindia.com/BseIndiaAPI/api/ListofScripData_new/w?Group=&Scripcode=&segment=Equity&status=Active&scripName=',
    'NASDAQ': 'https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt',
    'NYSE': 'https://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt',
}
MINIMUM = {'NSE': 1000, 'BSE': 2000, 'NASDAQ': 2000, 'NYSE': 1000}


def load_symbols(market, response):
    unmapped = set()
    if market == 'BSE':
        rows = response.json()
        symbols = [row['scrip_id'] for row in rows]
    else:
        text = response.content.decode('utf-8-sig')
        if market == 'NSE':
            rows = csv.DictReader(io.StringIO(text))
            symbols = [row['SYMBOL'] for row in rows]
        else:
            rows = csv.DictReader(io.StringIO(text), delimiter='|')
            symbols = [
                row['Symbol'] if market == 'NASDAQ' else row['ACT Symbol']
                for row in rows if row.get('Test Issue') == 'N'
                and (market == 'NASDAQ' or row['Exchange'] == 'N')
            ]

    normalized = set()
    suffix = {'NSE': '.NS', 'BSE': '.BO'}.get(market, '')
    for raw in symbols:
        value = str(raw or '').strip().upper()
        if market in ('NASDAQ', 'NYSE') and re.fullmatch(r'[A-Z]{1,5}\.[A-Z]', value):
            value = value.replace('.', '-')
        allowed = r'[A-Z0-9][A-Z0-9&_-]{0,29}' if suffix else r'[A-Z0-9]+(?:-[A-Z])?'
        if re.fullmatch(allowed, value):
            normalized.add(value + suffix)
        elif value:
            unmapped.add(value)
    return normalized, sorted(unmapped)


def refresh(market):
    source = SOURCES[market]
    response = requests.get(source, headers={
        'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.bseindia.com/',
    }, timeout=45)
    response.raise_for_status()
    symbols, unmapped = load_symbols(market, response)
    target = ROOT / f'{market.lower()}_latest.json'
    baseline = ROOT / f'{market.lower()}_stocks.json'
    previous_data = json.loads((target if target.exists() else baseline).read_text(encoding='utf-8-sig'))
    previous = set(previous_data.get('stocks') or previous_data[f'{market.lower()}_stocks'])
    if len(symbols) < MINIMUM[market] or (target.exists() and len(symbols) < 0.8 * len(previous)):
        raise ValueError(f'Unexpectedly small directory ({len(symbols)} symbols)')
    refresh_info = {
        'source': source, 'refreshed_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'added': sorted(symbols - previous), 'removed': sorted(previous - symbols), 'unmapped': unmapped,
    }
    print(f"{market}: {len(symbols)} symbols, +{len(refresh_info['added'])}, "
          f"-{len(refresh_info['removed'])}, {len(unmapped)} unmapped")
    temp = target.with_suffix('.tmp')
    temp.write_text(json.dumps({'stocks': sorted(symbols), 'refresh': refresh_info}, indent=2) + '\n',
                    encoding='utf-8')
    temp.replace(target)


if __name__ == '__main__':
    import sys

    failed = False
    for name in SOURCES:
        try:
            refresh(name)
        except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError, OSError) as error:
            print(f'::warning::{name} refresh failed. Using the previous list. {error}')
            failed = True
    sys.exit(int(failed))
