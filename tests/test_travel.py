import csv
import io
import json
import tempfile
import unittest
import zipfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

from coinline_adsi import graph, providers, regional, transit, travel, wire


ROOT=Path(__file__).resolve().parents[1]
APP=json.loads((ROOT/'service/coinline_adsi/infoline-travel.json').read_text(encoding='utf-8'))


def archive(tables):
    result=io.BytesIO()
    with zipfile.ZipFile(result,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for name,rows in tables.items():
            csvfile=io.StringIO()
            writer=csv.DictWriter(csvfile,fieldnames=list(rows[0]))
            writer.writeheader(); writer.writerows(rows)
            z.writestr(name+'.txt',csvfile.getvalue())
    return result.getvalue()


def sample_tables():
    days={x:'1' for x in ('monday','tuesday','wednesday','thursday','friday','saturday','sunday')}
    return {
        'agency':[{'agency_timezone':'America/St_Johns'}],
        'stops':[{'stop_id':'s1','stop_code':'9000','stop_name':'Demo Harbour'},
                 {'stop_id':'s2','stop_code':'9001','stop_name':'Demo Mall'}],
        'routes':[{'route_id':'r9','route_short_name':'9','route_long_name':'Demo Mall'}],
        'trips':[{'trip_id':'t1','route_id':'r9','service_id':'weekday','trip_headsign':'Demo Mall'},
                 {'trip_id':'t2','route_id':'r9','service_id':'weekday','trip_headsign':'Night service'}],
        'calendar':[{'service_id':'weekday','start_date':'20260101','end_date':'20261231',**days}],
        'calendar_dates':[{'service_id':'weekday','date':'20260208','exception_type':'2'}],
        'stop_times':[{'trip_id':'t1','stop_id':'s1','departure_time':'10:15:00','pickup_type':'0'},
                      {'trip_id':'t1','stop_id':'s2','departure_time':'10:45:00','pickup_type':'1'},
                      {'trip_id':'t2','stop_id':'s1','departure_time':'25:10:00','pickup_type':'0'}],
    }


class TravelTests(unittest.IsolatedAsyncioTestCase):
    async def test_graph_navigation_and_source(self):
        self.assertEqual(graph.validate(APP),[])
        async def lookup(op,args):
            return providers.fixture(op,args)
        for digits,title in [('5311','DEMO ROAD CONDITIONS'),('5312','DEMO ROAD EVENTS'),
                             ('532','DEMO FERRY STATUS'),('5333','DEMO BUS BULLETINS'),
                             ('5331','DEMO BUS SCHEDULE'),('23','DEMO WEATHER ALERTS')]:
            s=graph.Session(APP)
            for digit in digits:
                self.assertTrue(s.choose(digit),digits)
            view=await s.settle(lookup)
            self.assertEqual(view['lines'][0],title)
            self.assertEqual(next(c['slot'] for c in view['choices'] if c['digit']=='0'),6)
            self.assertEqual(sum(wire.finish_in_voice(wire.screen(view['lines'],[(x['label'],x['digit']) for x in view['choices']],
                slots=[x['slot'] for x in view['choices']])))%256,0)
        node=next(n for n in APP['nodes'] if n['id']=='transit-notice')
        self.assertIn(transit.NOTICE,node['lines'])

    async def test_511_parsers_and_empty(self):
        now=int(datetime.now(UTC).timestamp())
        road={'Id':1,'AreaName':'Avalon-Demo','RoadwayName':'Demo highway','LocationDescription':'Demo to Sample',
              'Primary Condition':'Partly Covered','Secondary Conditions':['Slush','Ice'],'Visibility':'Poor',
              'LastUpdated':now,'EncodedPolyline':['RAW_GEOMETRY']}
        result=travel.normalize_511('roads',[road])[0]
        self.assertEqual(result['record']['status'],'Partly Covered')
        self.assertIn('Slush, Ice',result['record']['detail1'])
        self.assertNotIn('RAW_GEOMETRY',str(result))
        event={'ID':2,'RoadwayName':'Demo highway','Description':'Roadwork','IsFullClosure':True,
               'Latitude':47.5,'Longitude':-52.7,'LastUpdated':now}
        self.assertEqual(travel.normalize_511('events',[event])[0]['record']['status'],'FULL CLOSURE')
        ferry={'Id':'3','PortName':'Demo Port','ServiceName':'Demo Ferry','Status':'Off schedule','VesselNames':'MV Example',
               'Details':'Weather delay','LastUpdated':now}
        item=travel.normalize_511('ferries',[ferry])[0]
        self.assertIn('Weather delay',item['record']['detail1'])
        self.assertEqual(travel.normalize_511('advisories',[]),[])
        self.assertIsNone(travel.normalize_511('roads',{'error':'denied'}))
        self.assertIsNone(travel.normalize_511('roads',[{}]))

    async def test_511_cache_quota_and_no_credentials(self):
        calls=[]
        def send(request):
            calls.append(request)
            self.assertEqual(request.url.host,'511nl.ca')
            self.assertEqual(request.url.params['key'],'synthetic')
            return httpx.Response(200,json=[])
        with patch.dict('os.environ',{'ADSI_NL511_KEY':'','ADSI_PROVIDER_CACHE_DIR':''}):
            regional_provider=regional.Regional()
            await regional_provider.client.aclose()
            regional_provider.client=httpx.AsyncClient(transport=httpx.MockTransport(send))
            try:
                adapter=travel.Travel(regional_provider)
                self.assertIsNone(await adapter.feed('events'))
                self.assertEqual(len(calls),0)
                with patch.dict('os.environ',{'ADSI_NL511_KEY':'synthetic'}):
                    self.assertEqual(await adapter.feed('events'),[])
                    self.assertEqual(await adapter.feed('events'),[])
                    self.assertEqual(len(calls),1)
                    self.assertEqual((await adapter.lookup('events','none',True))['subject'],'No listed events')
            finally:
                await regional_provider.close()

    async def test_alert_expiration_and_identity(self):
        now=datetime(2026,2,7,12,tzinfo=UTC)
        common={'province':'NL','alert_name_en':'Snowfall warning','alert_text_en':'Use caution.','feature_name_en':'Demo Harbour',
                'status_en':'issued','risk_colour_en':'yellow','feature_id':'feature1','publication_datetime':(now-timedelta(hours=1)).isoformat(),
                'expiration_datetime':(now+timedelta(hours=1)).isoformat()}
        expired={**common,'feature_id':'feature2','expiration_datetime':now.isoformat()}
        ended={**common,'feature_id':'feature3','status_en':'ended'}
        payload={'type':'FeatureCollection','numberMatched':3,'features':[{'properties':p} for p in (common,expired,ended)]}
        result=travel.normalize_alerts(payload,now,'NL')
        self.assertEqual(len(result),1)
        self.assertIn('yellow',result[0]['record']['status'])
        self.assertEqual(travel.normalize_alerts({**payload,'features':list(reversed(payload['features']))},now,'NL')[0]['id'],result[0]['id'])
        self.assertIsNone(travel.normalize_alerts({**payload,'numberMatched':4},now,'NL'))

    async def test_metrobus_bulletins(self):
        row={'rid':1,'Title':'Demo detour','Description':'Stop temporarily moved','PostDate':'Feb 7 2026 10:00AM'}
        value=travel.normalize_bulletins([row])[0]['record']
        self.assertEqual(value['subject'],'Demo detour')
        self.assertIn('Stop temporarily moved',value['detail1'])
        self.assertIsNone(travel.normalize_bulletins({'invalid':True}))


class TransitTests(unittest.IsolatedAsyncioTestCase):
    async def test_accepted_automatic_refresh_preserves_valid_archive(self):
        raw=archive(sample_tables())
        provider=AsyncMock()
        provider.catalog={'travel':{'metrobus_gtfs':'https://example.test/gtfs.zip'}}
        provider.request.return_value=raw
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'metrobus.zip'
            with patch.dict('os.environ',{'ADSI_METROBUS_GTFS_PATH':str(path),'ADSI_METROBUS_GTFS_ACCEPTED':'0'}):
                adapter=transit.Transit(provider)
                self.assertIsNone(await adapter.load())
                provider.request.assert_not_awaited()
            with patch.dict('os.environ',{'ADSI_METROBUS_GTFS_PATH':str(path),'ADSI_METROBUS_GTFS_ACCEPTED':'1'}), \
                 patch('coinline_adsi.transit.datetime', wraps=datetime) as clock:
                clock.now.return_value=datetime(2026,2,7,12,tzinfo=UTC)
                # Simulate only the current service date check; filesystem age is tested separately.
                await adapter.refresh(path)
                self.assertEqual(path.read_bytes(),raw)
                adapter.retry_after=0
                provider.request.return_value=b'invalid archive'
                await adapter.refresh(path)
                self.assertEqual(path.read_bytes(),raw)

    async def test_gtfs_stop_schedule_calendar_and_overnight(self):
        schedule=transit.load_archive(archive(sample_tables()))
        self.assertEqual(schedule.route_list(),[('9','9 Demo Mall')])
        self.assertEqual(schedule.route_stops('9'),[('9000','9000 Demo Harbour')])
        now=datetime(2026,2,7,13,30,tzinfo=UTC) # 10:00 NST
        record=schedule.departures('9000','9',now)
        self.assertIn('10:15 R9',record['departure1'])
        self.assertIn('08 Feb 01:10 R9',record['departure2'])
        self.assertEqual(record['source'],'Scheduled, not live')
        self.assertIsNone(schedule.departures('9000','999',now))
        # Service for Feb 8 is cancelled, but a trip from Feb 7 may run after midnight.
        after=datetime(2026,2,8,4,0,tzinfo=UTC)
        self.assertIn('01:10 R9',schedule.departures('9000','9',after)['departure1'])
        self.assertFalse(schedule.active('weekday',date(2026,2,8)))
        self.assertIsNone(schedule.departures('9000','9',datetime(2027,1,1,12,tzinfo=UTC)))

    async def test_expired_file_and_numeric_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'demo.zip'; path.write_bytes(archive(sample_tables()))
            with patch.dict('os.environ',{'ADSI_METROBUS_GTFS_PATH':str(path)}):
                provider=transit.Transit()
                self.assertIsNotNone(await provider.load())
                import os
                seconds=(datetime.now(UTC)-timedelta(days=8)).timestamp()
                os.utime(path,(seconds,seconds))
                self.assertIsNone(await provider.load())
        link=AsyncMock(); link.display_active=True
        link.selection.side_effect=['9','0','0','1','*','0','#']
        self.assertEqual(await transit.collect_number(link,AsyncMock(),'BUS STOP','stop number'),'9000')
        self.assertIn(b'Submit',link.transfer.await_args.args[0])
