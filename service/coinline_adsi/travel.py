"""Official public traveller information, normalized before caching."""

import asyncio
import hashlib
import os
import re
import textwrap
from datetime import UTC, datetime, timedelta

from .cinema import distance_km, select_entry
from .regional import choose, choose_weather


ROAD_OPERATIONS = {'travel.road': 'roads', 'travel.events': 'events',
                   'travel.advisories': 'advisories', 'travel.ferries': 'ferries'}
TITLES = {'roads': 'ROAD CONDITIONS', 'events': 'ROAD EVENTS',
          'advisories': 'NL511 ADVISORIES', 'ferries': 'FERRY STATUS',
          'alerts': 'WEATHER ALERTS', 'bulletins': 'TRANSIT BULLETINS'}
DETAIL_FIELDS = tuple(f'detail{i}' for i in range(1, 7))
OUTPUT_FIELDS = {'displayTitle', 'subject', 'status', 'updated', 'source', *DETAIL_FIELDS}


def clean(value, limit=160):
    return ' '.join(value.split())[:limit] if isinstance(value, str) else ''


def details(value):
    chunks = textwrap.wrap(clean(value, 3000), width=150)
    if len(chunks) > len(DETAIL_FIELDS):
        chunks = chunks[:len(DETAIL_FIELDS)-1] + ['More at source website']
    return {field: chunks[i] if i < len(chunks) else '' for i, field in enumerate(DETAIL_FIELDS)}


def epoch(value):
    if type(value) not in (int, float) or not 0 < value < 4_102_444_800:
        return None
    return datetime.fromtimestamp(value, UTC)


def iso(value):
    if isinstance(value, str):
        try:
            stamp = datetime.fromisoformat(value)
            return stamp.astimezone(UTC) if stamp.tzinfo else None
        except ValueError:
            pass
    return None


def stamp(value):
    return value.strftime('%Y-%m-%d %H:%M UTC') if value else 'Report time unknown'


def row_record(kind, subject, status, detail, observed, source):
    return {'displayTitle': TITLES[kind], 'subject': clean(subject), 'status': clean(status),
            'updated': stamp(observed), 'source': source, **details(detail)}


def empty_record(kind, source):
    label = {'events': 'No listed events', 'advisories': 'No listed advisories',
             'alerts': 'No active alerts', 'bulletins': 'No listed bulletins'}.get(kind)
    if not label:
        return None
    record = row_record(kind, label, 'At last feed check', '', None, source)
    record['updated'] = 'Feed cache <2 min' if kind=='alerts' else 'Feed cache <5 min'
    return record


def normalize_511(kind, payload):
    if not isinstance(payload, list) or len(payload) > 3000:
        return None
    result = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        identifier = str(item.get('Id', item.get('ID', '')))
        if not re.fullmatch(r'[0-9]{1,15}', identifier):
            continue
        region, lat, lon = '', None, None
        observed = epoch(item.get('LastUpdated'))
        if kind == 'roads':
            subject = clean(item.get('RoadwayName'))
            area = clean(item.get('AreaName'))
            location = clean(item.get('LocationDescription'))
            status = clean(item.get('Primary Condition'))
            if not all((subject, area, location, status)):
                continue
            region = area.split('-', 1)[0]
            secondary = item.get('Secondary Conditions')
            if isinstance(secondary, list):
                secondary = ', '.join(clean(x) for x in secondary if isinstance(x, str))
            detail = '. '.join(part for part in (location, 'Secondary: '+clean(secondary) if secondary else '',
                'Visibility: '+clean(item.get('Visibility')) if item.get('Visibility') else '') if part)
            label = location
        elif kind == 'events':
            subject = clean(item.get('RoadwayName'))
            detail = clean(item.get('Description'), 900)
            if not subject or not detail:
                continue
            status = 'FULL CLOSURE' if item.get('IsFullClosure') is True else clean(item.get('EventSubType') or item.get('EventType'))
            extra = [clean(item.get('Comment'), 350), clean(item.get('DetourInstructions'), 350)]
            detail = '. '.join([detail, *(x for x in extra if x and x not in detail)])
            label = f'{subject}: {status or "Event"}'
            try:
                lat, lon = float(item['Latitude']), float(item['Longitude'])
                if not -90<=lat<=90 or not -180<=lon<=180:
                    lat, lon = None, None
            except (KeyError, ValueError, TypeError):
                lat, lon = None, None
        elif kind == 'ferries':
            subject = clean(item.get('ServiceName'))
            port = clean(item.get('PortName'))
            status = clean(item.get('Status'))
            if not subject or not port or not status:
                continue
            detail = '. '.join(x for x in (f'Port: {port}', clean(item.get('VesselNames')),
                clean(item.get('Details'), 750), clean(item.get('ScheduleName'))) if x)
            region = subject
            label = port
        else:
            subject = clean(item.get('Message') or item.get('Title'))
            if not subject:
                continue
            start, end = epoch(item.get('StartTime')), epoch(item.get('EndTime'))
            status = ('Ended advisory' if end and end<=datetime.now(UTC) else
                      'High importance' if item.get('HighImportance') is True else 'Public advisory')
            regions=item.get('Regions')
            region_text=', '.join(clean(value) for value in regions if isinstance(value,str)) if isinstance(regions,list) else ''
            detail = '. '.join(x for x in (clean(item.get('Description') or item.get('Message'), 900),
                clean(item.get('Notes'),750), 'Regions: '+region_text if region_text else '',
                'Starts '+stamp(start) if start else '', 'Ends '+stamp(end) if end else '') if x)
            observed = observed or start
            label = subject
        if observed and datetime.now(UTC)-observed > timedelta(hours=48):
            status = f'{status} (older report)'
        result.append({'id': identifier, 'label': label, 'region': region, 'area': area if kind == 'roads' else '',
                       'lat': lat, 'lon': lon, 'record': row_record(kind, subject, status, detail, observed, 'NL511')})
    return result if result or not payload else None


def normalize_alerts(payload, now, province):
    if not isinstance(payload, dict) or payload.get('type')!='FeatureCollection':
        return None
    features = payload.get('features')
    if not isinstance(features, list) or payload.get('numberMatched') != len(features):
        return None
    result = []
    for item in features:
        if not isinstance(item, dict) or not isinstance(item.get('properties'), dict):
            return None
        p = item.get('properties', {})
        if p.get('province') != province or str(p.get('status_en','')).casefold() in ('ended', 'cancelled', 'expired'):
            continue
        expires = iso(p.get('expiration_datetime'))
        published = iso(p.get('publication_datetime'))
        if not expires or not published:
            return None
        if published > now or expires <= now:
            continue
        label = clean(p.get('alert_name_en'))
        detail = clean(p.get('alert_text_en'), 3000)
        if not label or not detail:
            return None
        risk = clean(p.get('risk_colour_en'))
        area = clean(p.get('feature_name_en'))
        status = f'{label} ({risk})' if risk else label
        record = row_record('alerts', area or 'Selected location', status,
            f'Expires {stamp(expires)}. {detail}', published, 'ECCC GeoMet')
        identity = hashlib.sha256(f"{p.get('feature_id')}|{label}|{published.isoformat()}|{detail}".encode()).hexdigest()[:16]
        result.append({'id': identity, 'label': status, 'expires': expires.isoformat(), 'record': record})
    return result


def normalize_bulletins(payload):
    if not isinstance(payload, list) or len(payload)>100:
        return None
    result=[]
    for item in payload:
        if not isinstance(item,dict):
            continue
        subject=clean(item.get('Title'))
        detail=clean(item.get('Description'),3000)
        identifier=str(item.get('rid',''))
        if not subject or not detail or not re.fullmatch(r'[0-9]{1,12}',identifier):
            continue
        record=row_record('bulletins',subject,'Posted bulletin',detail,None,'Metrobus Transit')
        record['updated']=clean(item.get('PostDate')) or 'Report time unknown'
        result.append({'id':identifier,'label':subject,'record':record})
    return result if result or not payload else None


def fixture(kind):
    names = {'roads': ('Demo highway', 'Bare dry', 'Demo Harbour to Example Cove. Visibility good.'),
             'events': ('Demo highway', 'Roadwork', 'Sample one-lane closure.'),
             'advisories': ('Sample advisory', 'Public advisory', 'Example only.'),
             'ferries': ('Demo ferry service', 'Off schedule', 'Sample vessel delay.'),
             'alerts': ('Demo Harbour', 'Weather warning', 'Synthetic example only.'),
             'bulletins': ('Demo route', 'Posted bulletin', 'Sample detour.')}
    subject, status, detail = names[kind]
    record = row_record(kind, subject, status, detail, None, 'Fixture only')
    record['displayTitle'] = {'bulletins':'DEMO BUS BULLETINS','advisories':'DEMO NL511 ADVICE'}.get(kind,'DEMO '+TITLES[kind][:15])
    return record


class Travel:
    def __init__(self, regional):
        self.regional = regional

    async def feed(self, kind):
        if not self.regional:
            return None
        token = os.getenv('ADSI_NL511_KEY')
        if kind != 'bulletins' and not token:
            return None
        spec = self.regional.catalog['travel']
        async def fetch():
            if kind == 'bulletins':
                data = await self.regional.json(spec['bulletins'], params={'feed':'bulletinsshort'})
                return normalize_bulletins(data)
            if not self.regional.cache.quota('nl511', 10000, 8):
                return None
            data = await self.regional.json(spec[kind], params={'key':token,'format':'json'}, limit=5_000_000)
            return normalize_511(kind, data)
        return await self.regional.cached(f'travel:{kind}', 300, fetch, 300)

    async def alerts(self, place):
        if not self.regional:
            return None
        coords = await self.regional.coordinates(place)
        if not coords:
            return None
        lat, lon = coords.split(',')
        province = place.split('|',1)[0]
        async def fetch():
            data = await self.regional.json(self.regional.catalog['travel']['weather_alerts'],
                params={'filter':f'INTERSECTS(geometry, POINT({lon} {lat}))','limit':100,'f':'json'}, limit=5_000_000)
            return normalize_alerts(data, datetime.now(UTC), province)
        return await self.regional.cached(f'weather-alerts:{coords}:{province}', 120, fetch, 120)

    async def prepare(self, kind, link, say, inferred, enabled):
        if not enabled:
            return 'demo'
        try:
            async with asyncio.timeout(20):
                entries = await self.feed(kind)
            if entries is None:
                return None
            if not entries:
                return 'none' if empty_record(kind,'NL511' if kind!='bulletins' else 'Metrobus Transit') else None
            if kind in ('roads','ferries'):
                groups = sorted({row['region'] for row in entries})
                group = await select_entry(link,say,'Choose area' if kind=='roads' else 'Ferry service',[(g,g) for g in groups])
                if not group:
                    return None
                entries = [row for row in entries if row['region']==group]
                if kind=='roads':
                    areas = sorted({row['area'] for row in entries})
                    area = await select_entry(link,say,'Choose road area',[(a,a.split('-',1)[-1]) for a in areas])
                    if not area:
                        return None
                    entries = [row for row in entries if row['area']==area]
            elif kind=='events':
                modes = [('all','All NL')]
                if inferred and inferred[0]=='NL' and inferred[1]:
                    modes.insert(0,('local','Near your city'))
                mode = await choose(link,say,'Road events',modes)
                if not mode:
                    return None
                if mode=='local':
                    async with asyncio.timeout(12):
                        coords = await self.regional.coordinates('|'.join(inferred))
                    if not coords:
                        return None
                    point=tuple(map(float,coords.split(',')))
                    entries=[row for row in entries if row['lat'] is not None and
                             distance_km(point,(row['lat'],row['lon'])) <= 100]
                    if not entries:
                        return 'none-local|'+'|'.join(inferred)
                entries.sort(key=lambda row: (not row['record']['status'].startswith('FULL CLOSURE'), row['label']))
            return await select_entry(link,say,'Choose report',[(row['id'],row['label']) for row in entries])
        except (TimeoutError, KeyError, TypeError, ValueError):
            return None

    async def prepare_alerts(self, link, say, inferred, enabled):
        if not enabled:
            return 'demo'
        try:
            place = await choose_weather(link,say,inferred,title='Alerts')
            if not place:
                return None
            async with asyncio.timeout(20):
                rows = await self.alerts(place)
            if rows is None:
                return None
            if not rows:
                return f'{place}|none'
            selected = await select_entry(link,say,'Choose alert',[(r['id'],r['label']) for r in rows])
            return f'{place}|{selected}' if selected else None
        except (TimeoutError, KeyError, TypeError, ValueError):
            return None

    async def lookup(self, kind, selection, enabled):
        if not enabled:
            return fixture(kind)
        if kind=='alerts':
            place, separator, identifier = selection.rpartition('|')
            if not separator or '|' not in place:
                return None
            rows = await self.alerts(place)
            if rows is None:
                return None
            if identifier=='none' and not rows:
                value=empty_record(kind,'ECCC GeoMet')
                value['subject']=place.split('|',1)[1]
                value['status']='No active alerts'
                return value
            return next((r['record'] for r in rows if r['id']==identifier and iso(r['expires']) > datetime.now(UTC)),None)
        source='Metrobus Transit' if kind=='bulletins' else 'NL511'
        rows=await self.feed(kind)
        if rows is None:
            return None
        if selection=='none' and not rows:
            return empty_record(kind,source)
        if selection.startswith('none-local|') and kind=='events':
            coords = await self.regional.coordinates(selection.split('|',1)[1])
            if not coords:
                return None
            point = tuple(map(float,coords.split(',')))
            if any(row['lat'] is not None and distance_km(point,(row['lat'],row['lon'])) <= 100 for row in rows):
                return None
            record=empty_record(kind,source)
            record['subject']='No nearby events'
            record['status']='Within 100 km'
            return record
        return next((r['record'] for r in rows if r['id']==selection),None)
