"""Metrobus scheduled departures from an operator-supplied GTFS archive."""

import asyncio
import csv
import io
import os
import re
import tempfile
import time as monotonic_time
import zipfile
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import wire
from .cinema import select_entry
from .regional import choose


ZONE = ZoneInfo('America/St_Johns')
OUTPUT_FIELDS = {'displayTitle', 'stop', 'source', 'updated', *(f'departure{i}' for i in range(1,7))}
NOTICE = ('Data used in this product or service is provided by Metrobus Transit, however Metrobus Transit assumes '
          'no responsibility for the accuracy or currency of the Data used in this product or service.')


def day_value(value):
    return datetime.strptime(value, '%Y%m%d').date()


def seconds(value):
    if not re.fullmatch(r'\d{1,2}:\d{2}:\d{2}', value):
        raise ValueError('Invalid GTFS time')
    hour, minute, second = map(int,value.split(':'))
    if hour>47 or minute>59 or second>59:
        raise ValueError('Invalid GTFS time')
    return hour*3600+minute*60+second


def service_time(day, value):
    # GTFS times are measured from noon minus twelve hours, including DST transitions.
    noon = datetime.combine(day,time(12),ZONE).astimezone(UTC)
    return noon-timedelta(hours=12)+timedelta(seconds=value)


class Schedule:
    def __init__(self, tables):
        self.stops = {}
        internal = {}
        for row in tables['stops']:
            code = row.get('stop_code') or row['stop_id']
            if not re.fullmatch(r'[0-9]{1,8}',code) or not row.get('stop_name'):
                continue
            if code in self.stops:
                raise ValueError('Ambiguous public stop code')
            self.stops[code] = row['stop_name'][:100]
            internal[row['stop_id']] = code
        self.routes = {r['route_id']:(r['route_short_name'] or r['route_id'],r.get('route_long_name',''))
                       for r in tables['routes'] if r.get('route_short_name')}
        self.trips = {r['trip_id']:r for r in tables['trips'] if r['route_id'] in self.routes}
        self.calendar = {r['service_id']:(day_value(r['start_date']),day_value(r['end_date']),
            tuple(r[x]=='1' for x in ('monday','tuesday','wednesday','thursday','friday','saturday','sunday')))
            for r in tables.get('calendar',[])}
        self.exceptions = {(r['service_id'],day_value(r['date'])):r['exception_type']=='1'
                           for r in tables.get('calendar_dates',[])}
        if not self.stops or not self.trips or not (self.calendar or self.exceptions):
            raise ValueError('Incomplete schedule')
        self.bounds = [d for start,end,_ in self.calendar.values() for d in (start,end)] + [d for _,d in self.exceptions]
        self.by_stop = {}
        self.by_route = {}
        for row in tables['stop_times']:
            code=internal.get(row['stop_id'])
            trip=self.trips.get(row['trip_id'])
            value=row.get('departure_time') or row.get('arrival_time')
            # A stop where no pickup is permitted cannot be offered as a departure.
            if not code or not trip or not value or row.get('pickup_type') in ('1','2','3'):
                continue
            route=trip['route_id']
            record=(seconds(value),trip['service_id'],self.routes[route][0],
                    row.get('stop_headsign') or trip.get('trip_headsign') or self.routes[route][1])
            self.by_stop.setdefault(code,[]).append(record)
            self.by_route.setdefault(self.routes[route][0],set()).add(code)
        if not self.by_stop:
            raise ValueError('No usable departures')

    def active(self, service, day):
        if (service,day) in self.exceptions:
            return self.exceptions[service,day]
        rule=self.calendar.get(service)
        return bool(rule and rule[0]<=day<=rule[1] and rule[2][day.weekday()])

    def route_list(self):
        values={short:long for short,long in self.routes.values()}
        return sorted([(short,f'{short} {long}'.strip()) for short,long in values.items() if short in self.by_route],
                      key=lambda row:(int(row[0]) if row[0].isdigit() else 10**9,row[0]))

    def route_stops(self, route):
        return [(code,f'{code} {self.stops[code]}') for code in sorted(self.by_route.get(route,set()),key=int)]

    def departures(self, stop, route, now):
        if stop not in self.stops or (route and stop not in self.by_route.get(route,set())):
            return None
        if now.tzinfo is None:
            raise ValueError('Expected aware current time')
        local=now.astimezone(ZONE)
        day=local.date()
        if not min(self.bounds)<=day<=max(self.bounds):
            return None
        now=now.astimezone(UTC)
        times=set()
        for offset in (-1,0,1):
            service_day=day+timedelta(days=offset)
            for value,service,short,headsign in self.by_stop.get(stop,[]):
                if (route and route!=short) or not self.active(service,service_day):
                    continue
                departure=service_time(service_day,value)
                if now<=departure<=now+timedelta(hours=24):
                    times.add((departure,short,headsign))
        shown=[]
        for departure,short,headsign in sorted(times)[:6]:
            when=departure.astimezone(ZONE)
            label=when.strftime('%H:%M') if when.date()==day else when.strftime('%d %b %H:%M')
            shown.append(f'{label} R{short} {headsign}'.strip())
        if not shown:
            shown=['No trips in next 24h']
        return {'displayTitle':'BUS SCHEDULE', 'stop':f'{stop} {self.stops[stop]}',
                'updated':local.strftime('%d %b %H:%M local'),'source':'Scheduled, not live',
                **{f'departure{i+1}':shown[i] if i<len(shown) else '' for i in range(6)}}


def load_archive(raw):
    if len(raw)>8_000_000:
        raise ValueError('GTFS archive too large')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if sum(item.file_size for item in archive.infolist())>75_000_000:
            raise ValueError('GTFS archive expands beyond limit')
        tables={}
        for name in ('agency','stops','routes','trips','stop_times','calendar','calendar_dates'):
            candidates=[item for item in archive.infolist() if item.filename==name+'.txt']
            if not candidates and name in ('calendar','calendar_dates'):
                continue
            if len(candidates)!=1 or candidates[0].file_size>25_000_000:
                raise ValueError('Invalid GTFS table')
            with archive.open(candidates[0]) as source:
                tables[name]=list(csv.DictReader(io.TextIOWrapper(source,encoding='utf-8-sig',newline='')))
        # A frequency-based feed needs a different expansion algorithm. Never claim exact times for it.
        if not tables['agency'] or any(row.get('agency_timezone')!='America/St_Johns' for row in tables['agency']):
            raise ValueError('Expected Newfoundland transit service timezone')
        if 'frequencies.txt' in archive.namelist():
            with archive.open('frequencies.txt') as source:
                if next(csv.DictReader(io.TextIOWrapper(source,encoding='utf-8-sig')),None):
                    raise ValueError('Frequency service is not supported')
        return Schedule(tables)


def fixture():
    return {'displayTitle':'DEMO BUS SCHEDULE','stop':'9000 Demo Harbour','source':'Fixture only',
            'updated':'07 Feb 2026 local','departure1':'10:15 R9 Demo Mall','departure2':'10:45 R9 Demo Mall',
            **{f'departure{i}':'' for i in range(3,7)}}


async def collect_number(link,say,title,subject,*,example=None,maximum=8):
    """Digits are collected in one input interval, with explicit Submit/Erase."""
    lines=[title,'Enter '+subject,'Submit when ready',f'Demo: {example}' if example else '* erases or backs']
    if link.display_active:
        await link.transfer(wire.screen(lines,[('Erase','*'),('Submit','#')],slots=[4,5]),open_input=True)
    else:
        link.open_voice_input()
        await say(f'Enter {subject}. Press pound to submit or star to erase or cancel when empty.'+
                  (f' Example {example}.' if example else ''))
    value=''
    deadline=asyncio.get_running_loop().time()+60
    try:
        for _ in range(40):
            digit=await link.selection(max(0,deadline-asyncio.get_running_loop().time()))
            if digit=='#':
                return value or None
            if digit=='*':
                if not value:
                    return None
                value=value[:-1]
            elif digit in '0123456789':
                if len(value)>=maximum:
                    return None
                value+=digit
    except TimeoutError:
        pass
    return None


class Transit:
    def __init__(self, regional=None):
        self.regional=regional
        self.snapshot=None
        self.version=None
        self.lock=asyncio.Lock()
        self.retry_after=0

    async def refresh(self, path):
        if not self.regional or os.getenv('ADSI_METROBUS_GTFS_ACCEPTED')!='1':
            return
        if monotonic_time.monotonic()<self.retry_after:
            return
        self.retry_after=monotonic_time.monotonic()+3600
        try:
            data=await self.regional.request(self.regional.catalog['travel']['metrobus_gtfs'],limit=8_000_000)
            if not data:
                return
            schedule=await asyncio.to_thread(load_archive,data)
            if not min(schedule.bounds)<=datetime.now(ZONE).date()<=max(schedule.bounds):
                return
            path.parent.mkdir(parents=True,exist_ok=True)
            temporary=None
            try:
                with tempfile.NamedTemporaryFile(dir=path.parent,prefix='metrobus-',suffix='.zip',delete=False) as output:
                    temporary=Path(output.name)
                    output.write(data)
                os.replace(temporary,path)
            finally:
                if temporary and temporary.exists():
                    temporary.unlink()
            stat=path.stat()
            self.snapshot=schedule
            self.version=(str(path),stat.st_mtime_ns,stat.st_size)
        except (OSError,ValueError,TypeError,KeyError,zipfile.BadZipFile,UnicodeError):
            return

    async def load(self):
        configured=os.getenv('ADSI_METROBUS_GTFS_PATH')
        if not configured and os.getenv('ADSI_METROBUS_GTFS_ACCEPTED')=='1' and os.getenv('ADSI_PROVIDER_CACHE_DIR'):
            configured=str(Path(os.environ['ADSI_PROVIDER_CACHE_DIR'])/'metrobus.zip')
        if not configured:
            return None
        path=Path(configured)
        async with self.lock:
            try:
                if not path.exists() or datetime.now(UTC)-datetime.fromtimestamp(path.stat().st_mtime,UTC)>=timedelta(days=6):
                    await self.refresh(path)
                stat=path.stat()
                age=datetime.now(UTC)-datetime.fromtimestamp(stat.st_mtime,UTC)
                if not timedelta(0)<=age<=timedelta(days=7) or stat.st_size>8_000_000:
                    return None
                version=(str(path),stat.st_mtime_ns,stat.st_size)
                if version!=self.version:
                    self.snapshot=await asyncio.to_thread(lambda: load_archive(path.read_bytes()))
                    self.version=version
                return self.snapshot
            except (OSError,ValueError,TypeError,KeyError,zipfile.BadZipFile,UnicodeError):
                return None

    async def prepare(self, mode, link, say, enabled):
        if not enabled:
            if mode=='route-selected':
                route=await choose(link,say,'Demo route',[('9','9 Demo Mall')])
                if not route:
                    return None
                chosen=await choose(link,say,'Demo stop',[('9000','9000 Demo Harbour')])
                return 'demo' if chosen else None
            return 'demo' if await collect_number(link,say,'BUS STOP','stop number',example='9000')=='9000' else None
        schedule=await self.load()
        if not schedule:
            return None
        route=''
        if mode=='route-selected':
            method=await choose(link,say,'Choose route',[('number','Enter number'),('list','Browse routes')])
            if method=='number':
                route=await collect_number(link,say,'BUS ROUTE','route number',maximum=4)
            elif method=='list':
                route=await select_entry(link,say,'Choose route',schedule.route_list())
            if not route or route not in schedule.by_route:
                return None
            method=await choose(link,say,'Choose stop',[('number','Enter stop ID'),('list','Browse stops')])
            if method=='list':
                stop=await select_entry(link,say,'Choose stop',schedule.route_stops(route))
            elif method=='number':
                stop=await collect_number(link,say,'BUS STOP','stop number')
            else:
                return None
            if not stop or stop not in schedule.by_route[route]:
                return None
        else:
            stop=await collect_number(link,say,'BUS STOP','stop number')
        return f'{stop}|{route}' if stop and stop in schedule.stops else None

    async def lookup(self, selection, enabled):
        if not enabled:
            return fixture() if selection in ('selected','route-selected','demo') else None
        stop, _, route=selection.partition('|')
        schedule=await self.load()
        if not schedule:
            return None
        return schedule.departures(stop,route,datetime.now(UTC))
