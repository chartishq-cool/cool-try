"""Official NSE cash candles for repairing the tail of daily Yahoo history."""

import csv
from dataclasses import dataclass
from datetime import date, timedelta
from io import BytesIO, TextIOWrapper
from math import isfinite
from zipfile import BadZipFile, ZipFile

import requests


@dataclass(frozen=True)
class NseCandle:
    isin: str
    previous_close: float
    prices: dict[str, float]


def read_bhavcopy(content, session):
    name = f'BhavCopy_NSE_CM_0_0_0_{session:%Y%m%d}_F_0000.csv'
    candles, ambiguous = {}, set()
    with ZipFile(BytesIO(content)) as archive, archive.open(name) as raw:
        rows = csv.DictReader(TextIOWrapper(raw, encoding='utf-8-sig'))
        for row in rows:
            if row['TradDt'] != session.isoformat() or row['Sgmt'] != 'CM' or row['Src'] != 'NSE':
                raise ValueError('NSE bhavcopy has an unexpected date or market')
            if row['FinInstrmTp'] != 'STK' or row['SctySrs'] not in {'EQ', 'BE', 'BZ'}:
                continue
            symbol = row['TckrSymb'].strip() + '.NS'
            if symbol in candles:
                ambiguous.add(symbol)
                continue
            try:
                prices = {key: float(row[field]) for key, field in {
                    'Open': 'OpnPric', 'High': 'HghPric', 'Low': 'LwPric',
                    'Close': 'ClsPric', 'Volume': 'TtlTradgVol',
                }.items()}
                previous = float(row['PrvsClsgPric'])
            except (TypeError, ValueError):
                continue
            low, high = prices['Low'], prices['High']
            if (row['ISIN'] and all(isfinite(v) and v > 0 for v in (*prices.values(), previous))
                    and low <= prices['Open'] <= high and low <= prices['Close'] <= high):
                candles[symbol] = NseCandle(row['ISIN'], previous, prices)
    return {symbol: candle for symbol, candle in candles.items() if symbol not in ambiguous}


def _download_session(session):
    name = f'BhavCopy_NSE_CM_0_0_0_{session:%Y%m%d}_F_0000.csv.zip'
    for host in ('nsearchives.nseindia.in', 'nsearchives.nseindia.com'):
        try:
            response = requests.get(
                f'https://{host}/content/cm/{name}',
                headers={'User-Agent': 'Mozilla/5.0', 'Accept': '*/*'},
                timeout=(5, 12),
            )
            if response.status_code == 404:
                return {}
            response.raise_for_status()
            return read_bhavcopy(response.content, session)
        except (requests.RequestException, BadZipFile, KeyError, ValueError) as exc:
            print(f'NSE bhavcopy {session} from {host}: {type(exc).__name__}', flush=True)
    # An unavailable archive is distinct from a market holiday.
    return None


@dataclass(frozen=True)
class NseDailySessions:
    latest_date: date
    latest: dict[str, NseCandle]
    previous_date: date
    previous: dict[str, NseCandle]


def load_nse_daily_sessions(cutoff):
    completed = []
    for offset in range(1, 9):
        session = cutoff - timedelta(days=offset)
        candles = _download_session(session)
        if candles is None:
            return None
        if candles:
            completed.append((session, candles))
            if len(completed) == 2:
                return NseDailySessions(*completed[0], *completed[1])
    return None
