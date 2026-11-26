"""Read-only Cineplex listings, using an operator-authorized API credential."""

import asyncio
import math
import os
import re
import textwrap
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import graph, wire
from .regional import choose, choose_weather


def distance_km(origin, destination):
    lat1, lon1 = map(math.radians, origin)
    lat2, lon2 = map(math.radians, destination)
    a = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 6371 * 2 * math.asin(math.sqrt(min(1, max(0, a))))


def theatres(payload, origin=None, radius=100):
    if not isinstance(payload, list):
        return None
    result = []
    recognized = False
    for row in payload[:30]:
        if not isinstance(row, dict):
            continue
        key = str(row.get('locationId') or row.get('theatreId') or row.get('id') or '')
        name = row.get('name') or row.get('theatreName') or row.get('theatre')
        if re.fullmatch(r'[0-9]{1,10}', key) and isinstance(name, str) and name.strip():
            recognized = True
            distance = 0
            if origin is not None:
                try:
                    geo = row['location']['geoLocation']
                    lat, lon = float(geo['latitude']), float(geo['longitude'])
                    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
                        continue
                    distance = distance_km(origin, (lat, lon))
                    if distance > radius:
                        continue
                except (KeyError, TypeError, ValueError):
                    continue
            result.append((distance, [key, name.strip()[:100]]))
    return [item for _, item in sorted(result)] if recognized or not payload else None


def showtimes(payload, theatre, day):
    if not isinstance(payload, list):
        return None
    result = []
    for row in payload:
        if str(row['theatreId']) != theatre:
            continue
        name = row['theatre']
        for record in row['dates']:
            if datetime.fromisoformat(record['startDate']).date() != day:
                continue
            for movie in record['movies'][:60]:
                identifier = str(movie['id'])
                title = movie['name']
                if not re.fullmatch(r'[0-9]{1,10}', identifier) or not isinstance(title, str) or not title.strip():
                    continue
                times = set()
                for experience in movie['experiences']:
                    for session in experience['sessions']:
                        stamp = datetime.fromisoformat(session['showStartDateTime'])
                        if stamp.date() == day and not session.get('isInThePast'):
                            times.add(stamp.strftime('%H:%M'))
                if times:
                    result.append({'id': identifier, 'movie': title[:100], 'theatre': str(name)[:100], 'times': sorted(times)})
    return result


def record(movie, day, *, demo=False):
    times = movie['times']
    shown = times[:18]
    return {'displayTitle': 'DEMO MOVIES' if demo else 'MOVIE SHOWTIMES', 'theatre': movie['theatre'],
            'movie': movie['movie'], 'date': day.strftime('%d %b %Y'),
            'source': 'Fixture only' if demo else 'Cineplex, local time',
            **{f'times{i+1}': ' '.join(shown[i*3:i*3+3]) for i in range(6)},
            **({'times6': 'More times online'} if len(times)>18 else {})}


def fixture():
    return record({'theatre': 'Demo Harbour Cinema', 'movie': 'The Telephone Story',
                   'times': ['14:00','17:30','20:15']}, date(2026, 2, 7), demo=True)


async def select_entry(link, say, title, entries):
    """One full name per page; fixed select, previous, next and back positions."""
    if not entries:
        return None
    index = 0
    for _ in range(100):
        identifier, name = entries[index]
        label = graph.handset_text(name)
        rows = textwrap.wrap(label, width=20)[:2]
        rows += [' '] * (2-len(rows))
        options, slots = [('Select','1')], [1]
        if index:
            options.append(('Prev','4')); slots.append(4)
        if index+1 < len(entries):
            options.append(('Next','3')); slots.append(5)
        options.append(('Back','0')); slots.append(6)
        if link.display_active:
            await link.transfer(wire.screen([title, *rows, f'{index+1} of {len(entries)}'], options, slots=slots), open_input=True)
        else:
            link.open_voice_input()
            await say(f'{title}. {name}. Press one to select, three for next, four for previous, zero to return.')
        try:
            digit = await link.selection(30)
        except TimeoutError:
            return None
        if digit == '1':
            return identifier
        if digit == '0':
            return None
        if digit == '3' and index+1 < len(entries):
            index += 1
        elif digit == '4' and index:
            index -= 1
    return None


class Cinema:
    def __init__(self, regional):
        self.regional = regional

    async def _list(self, operation, key, params, parser):
        token = os.getenv('ADSI_CINEPLEX_API_KEY')
        if not self.regional or not token:
            return None
        spec = self.regional.catalog['cinema']
        async def fetch():
            if not self.regional.cache.quota('cinema', 250, 10):
                return None
            response = await self.regional.json(spec[operation], params=params,
                headers={'Ocp-Apim-Subscription-Key': token, 'Accept': 'application/json',
                         'Accept-Language': 'en'}, limit=3_000_000)
            return parser(response) if response is not None else None
        return await self.regional.cached(f'cinema:{operation}:{key}', 900, fetch, 900)

    async def nearby(self, place, day):
        province, city = place.split('|', 1)
        spec = self.regional.catalog['cinema']
        coords = await self.regional.coordinates(place)
        if not coords or province not in spec['regions']:
            return None
        lat, lon = coords.split(',')
        params = {'language': 'en', 'date': day.strftime('%m/%d/%Y'), 'city': city,
                  'region': spec['regions'][province][0], 'regionCode': province, 'country': 'Canada',
                  'latitude': lat, 'longitude': lon, 'accuracyKm': 5}
        radius = spec.get('radius_km', 100)
        if type(radius) not in (int, float) or not 1 <= radius <= 500:
            return None
        return await self._list('nearby', f'{place}:{day}:{radius}', params,
            lambda payload: theatres(payload, (float(lat), float(lon)), radius))

    async def listings(self, theatre, day):
        return await self._list('showtimes', f'{theatre}:{day}', {'language': 'en', 'locationId': theatre,
            'date': day.strftime('%m/%d/%Y')}, lambda payload: showtimes(payload, theatre, day))

    async def prepare(self, link, say, inferred, enabled):
        if not enabled:
            theatre = await select_entry(link, say, 'Demo theatre', [('demo','Demo Harbour Cinema')])
            if not theatre:
                return None
            movie = await select_entry(link, say, 'Demo movie', [('demo','The Telephone Story')])
            return 'demo' if movie else None
        if not self.regional or not os.getenv('ADSI_CINEPLEX_API_KEY'):
            return None
        try:
            place = await choose_weather(link, say, inferred, title='Movies')
            if not place:
                return None
            province = place.split('|', 1)[0]
            today = datetime.now(ZoneInfo(self.regional.catalog['cinema']['regions'][province][1])).date()
            day = await choose(link, say, 'Show date', [(today, today.strftime('Today %d %b')), (today+timedelta(days=1), 'Tomorrow')])
            if not day:
                return None
            async with asyncio.timeout(20):
                nearby = await self.nearby(place, day)
            theatre = await select_entry(link, say, 'Select theatre', nearby or [])
            if not theatre:
                return None
            async with asyncio.timeout(20):
                movies = await self.listings(theatre, day)
            movie = await select_entry(link, say, 'Select movie', [(m['id'],m['movie']) for m in movies or []])
            return f'{day}|{theatre}|{movie}' if movie else None
        except (TimeoutError, KeyError, ValueError, TypeError):
            return None

    async def lookup(self, selection, enabled):
        if not enabled:
            return fixture()
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}\|\d{1,10}\|\d{1,10}', selection):
            return None
        try:
            day, theatre, movie = selection.split('|')
            day = date.fromisoformat(day)
            found = next((m for m in await self.listings(theatre, day) or [] if m['id']==movie), None)
            return record(found, day) if found else None
        except (ValueError, KeyError, TypeError):
            return None
