"""Airport code search and an optional Aviationstack real-time flight board."""

import json
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from . import keypad
from .provider_cache import ProviderCache


SOURCE = 'https://api.apilayer.net/aviationstack/v1/flights'
AIRPORTS = json.loads(Path(__file__).with_name('airports.json').read_text(encoding='utf-8'))
INDEX = {row[0]: row for row in AIRPORTS}
ENTRIES = [(iata, f'{iata} {icao} {city}' if icao else f'{iata} {city}', (iata, icao) if icao else (iata,))
           for iata, icao, city, country in AIRPORTS]
STATUS = {'scheduled': 'SCH', 'active': 'AIR', 'landed': 'LND', 'cancelled': 'CXL',
          'incident': 'INC', 'diverted': 'DIV'}


async def choose(link, say):
    return await keypad.select(link, say, 'Airport', ENTRIES)


def fixture(operation, code):
    code = code if code in INDEX else 'YYT'
    other = [candidate for candidate in ('YYZ', 'YHZ', 'YYT') if candidate != code]
    return board(operation, code, [f'DEMO1 {other[0]} 10:00 SCH', f'DEMO2 {other[1]} 11:30 AIR'],
                 'Fixture flights', 'DEMO', 'Sample times only')


def board(operation, code, rows, source, mode, updated):
    return {'displayTitle': f'{mode} {code}', 'direction': 'Arrivals UTC' if operation == 'airport.arrivals' else 'Departures UTC',
            **{f'flight{i + 1}': rows[i] if i < len(rows) else ' ' for i in range(5)},
            'source': source, 'updated': updated}


def parse(document, code, operation, now):
    if not isinstance(document, dict) or not isinstance(document.get('data'), list):
        return None
    side = 'arrival' if operation == 'airport.arrivals' else 'departure'
    other = 'departure' if side == 'arrival' else 'arrival'
    rows = {}
    for item in document['data']:
        try:
            endpoint = item[side]
            if endpoint['iata'] != code:
                continue
            ident, airport = item['flight']['iata'], item[other]['iata']
            if not re.fullmatch(r'[A-Z0-9]{2,7}', ident) or not re.fullmatch(r'[A-Z]{3}', airport):
                continue
            stamp = datetime.fromisoformat(endpoint.get('actual') or endpoint.get('estimated') or endpoint['scheduled'])
            if stamp.tzinfo is None:
                continue
            stamp = stamp.astimezone(UTC)
            if not now - timedelta(hours=6) <= stamp <= now + timedelta(hours=24):
                continue
            status = STATUS.get(item.get('flight_status'), 'UNK')
            if endpoint.get('delay') and status == 'SCH':
                status = 'DLY'
            rows[(stamp, ident)] = f'{ident} {airport} {stamp:%d/%H:%M} {status}'
        except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
            continue
    if document['data'] and not rows:
        return None
    closest = sorted(rows, key=lambda key: (abs(key[0] - now), key))[:5]
    return [rows[key] for key in sorted(closest)] or ['No flights returned']


class Flights:
    def __init__(self, client):
        self.client = client
        self.cache = None

    def close(self):
        if self.cache is not None:
            self.cache.close()

    async def lookup(self, operation, code, live):
        if code not in INDEX:
            return None
        if not live:
            return fixture(operation, code)
        key = os.getenv('ADSI_AVIATIONSTACK_KEY')
        if not key:
            return None
        if self.cache is None:
            self.cache = ProviderCache(os.getenv('ADSI_PROVIDER_CACHE_DIR'))
        now = datetime.now(UTC)

        async def fetch():
            # Three calls per UTC day guarantee at most 93 in a 31-day month.
            if not self.cache.quota('aviationstack', 3):
                return None
            param = 'arr_iata' if operation == 'airport.arrivals' else 'dep_iata'
            try:
                async with self.client.stream('GET', SOURCE, params={'access_key': key, param: code, 'limit': 100},
                                              timeout=8) as response:
                    response.raise_for_status()
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > 1_000_000:
                            return None
                rows = parse(json.loads(content), code, operation, now)
                return {'rows': rows, 'stamp': now.isoformat()} if rows is not None else None
            except (httpx.HTTPError, ValueError, TypeError):
                return None

        snapshot = await self.cache.get(f'flight:{operation}:{code}', 900, fetch, max_age=7200)
        if snapshot is None:
            return None
        timestamp = datetime.fromisoformat(snapshot['stamp'])
        mode = 'LIVE' if now - timestamp <= timedelta(minutes=15) else 'STALE'
        return board(operation, code, snapshot['rows'], 'Aviationstack', mode, f'Fetched {timestamp:%d %b %H:%MZ}')
