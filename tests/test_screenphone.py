import json
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

from coinline_adsi import cinema, graph, parcel, providers, regional, wire


ROOT = Path(__file__).resolve().parents[1]
APP = json.loads((ROOT/'service/coinline_adsi/infoline-screenphone.json').read_text(encoding='utf-8'))


class ScreenphoneTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_menus_content_and_wire_budget(self):
        self.assertEqual(graph.validate(APP), [])
        session = graph.Session(APP)
        for node in APP['nodes']:
            if node['type'] != 'menu' or any('{{' in line for line in node['lines']):
                continue
            session.node = node['id']
            view = session.view()
            self.assertEqual(view['pageCount'], 1, node['id'])
            self.assertFalse(any(line.startswith(tuple(f'{d} ' for d in '0123456789')) for line in view['lines']))
            self.assertEqual(next(item['slot'] for item in view['choices'] if item['digit']=='0'),6)
            data = wire.screen(view['lines'], [(x['label'],x['digit']) for x in view['choices']],
                               slots=[x['slot'] for x in view['choices']])
            self.assertEqual(sum(wire.finish_in_voice(data))%256,0)

    async def test_paging_title_progress_and_stationary_keys(self):
        session = graph.Session(APP)
        for digit in '54':
            self.assertTrue(session.choose(digit))
        async def lookup(op,args):
            return providers.fixture(op,args)
        view = await session.settle(lookup)
        self.assertEqual(view['lines'][0], 'DEMO MOVIES')
        self.assertGreater(view['pageCount'],1)
        seen = []
        for page in range(1,view['pageCount']+1):
            view = session.view()
            self.assertEqual(view['lines'][0],'DEMO MOVIES')
            self.assertEqual(view['lines'][-1],f'Page {page}/{view["pageCount"]}')
            slots = {c['digit']:c['slot'] for c in view['choices']}
            self.assertEqual(slots['0'],6)
            self.assertEqual(slots.get('7'),4 if page>1 else None)
            self.assertEqual(slots.get('9'),5 if page<view['pageCount'] else None)
            seen.extend(view['lines'][1:3])
            if page<view['pageCount']:
                self.assertTrue(session.choose('9'))
        self.assertIn('14:00 17:30 20:15',seen)
        self.assertTrue(session.choose('7'))
        self.assertTrue(session.choose('0'))
        self.assertEqual(session.node,'services')

    async def test_parcel_input_confirm_erase_cancel(self):
        link = AsyncMock()
        link.display_active = True
        link.selection.side_effect = [*'000000000001','*','2','#','1']
        number = await parcel.collect(link, AsyncMock())
        self.assertEqual(number,'000000000002')
        first, confirmation = [call.args[0] for call in link.transfer.await_args_list]
        self.assertIn(b'Submit',first)
        self.assertIn(b'Ending in 0002',confirmation)
        self.assertNotIn(number.encode(),confirmation)
        self.assertIn(bytes.fromhex('81 06 01 01 01 13 14 01'),first)
        link.selection.side_effect = ['*']
        self.assertIsNone(await parcel.collect(link, AsyncMock()))

    async def test_cinema_parser_dedup_and_date(self):
        self.assertEqual(cinema.theatres([{'id':42,'name':'Demo Cinema'}]), [['42','Demo Cinema']])
        self.assertIsNone(cinema.theatres({'error':'denied'}))
        stamp = '2026-02-07T17:30:00'
        payload=[{'theatreId':42,'theatre':'Example cinema','dates':[{'startDate':'2026-02-07T00:00:00',
                 'movies':[{'id':3,'name':'Example film','experiences':[{'sessions':[
                    {'showStartDateTime':stamp},{'showStartDateTime':stamp},
                    {'showStartDateTime':'2026-02-08T17:30:00'},
                    {'showStartDateTime':'2026-02-07T12:30:00','isInThePast':True}]}]}]}]}]
        parsed=cinema.showtimes(payload,'42',date(2026,2,7))
        self.assertEqual(parsed[0]['times'],['17:30'])
        self.assertEqual(cinema.showtimes(payload,'43',date(2026,2,7)),[])
        self.assertEqual(cinema.record(parsed[0],date(2026,2,7))['times1'],'17:30')

    async def test_cinema_coordinate_query_cache_and_no_credential(self):
        calls=[]
        def send(request):
            calls.append(request)
            if request.url.host=='weather.gc.ca':
                return httpx.Response(200,json=[{'display_name':'Example Harbour, NL','lat':'47.5881','lon':'-52.7174'}])
            self.assertEqual(request.headers['Ocp-Apim-Subscription-Key'],'synthetic')
            self.assertEqual(request.url.params['regionCode'],'NL')
            self.assertEqual(request.url.params['latitude'],'47.588')
            self.assertEqual(request.url.params['longitude'],'-52.717')
            self.assertNotIn('postalCode',request.url.params)
            return httpx.Response(200,json=[{'theatreId':43,'theatreName':'Distant Cinema','location': {'geoLocation': {'latitude':48.95,'longitude':-57.95}}},
                {'theatreId':42,'theatreName':'Demo Cinema','location': {'geoLocation': {'latitude':47.56,'longitude':-52.75}}}])
        with patch.dict('os.environ',{'ADSI_CINEPLEX_API_KEY':'synthetic','ADSI_PROVIDER_CACHE_DIR':''}):
            adapter=regional.Regional()
            await adapter.client.aclose()
            adapter.client=httpx.AsyncClient(transport=httpx.MockTransport(send))
            try:
                movies=cinema.Cinema(adapter)
                first=await movies.nearby('NL|Example Harbour',date(2026,2,7))
                self.assertEqual(first,[['42','Demo Cinema']])
                self.assertEqual(await movies.nearby('NL|Example Harbour',date(2026,2,7)),first)
                self.assertEqual(len(calls),2)
                with patch.dict('os.environ',{'ADSI_CINEPLEX_API_KEY':''}):
                    self.assertIsNone(await movies.listings('42',date(2026,2,7)))
                self.assertEqual(len(calls),2)
            finally:
                await adapter.close()

    async def test_fedex_mock_auth_and_no_fallback(self):
        tracking='000000000002'
        result={'output':{'completeTrackResults':[{'trackingNumber':tracking,'trackResults':[
            {'latestStatusDetail':{'description':'In transit'},'scanEvents':[{'date':'2026-02-07T10:00:00Z',
                'scanLocation':{'streetLines':['Not returned']}}], 'dateAndTimes':[{'type':'ESTIMATED_DELIVERY',
                'dateTime':'2026-02-09T12:00:00Z'}]}]}]}}
        requests=[]
        def send(request):
            requests.append(request)
            if request.url.path=='/oauth/token':
                return httpx.Response(200,json={'access_token':'synthetic','expires_in':3600})
            self.assertEqual(request.url.path,'/track/v1/trackingnumbers')
            self.assertEqual(request.headers['Authorization'],'Bearer synthetic')
            return httpx.Response(200,json=result)
        with patch.dict('os.environ',{'ADSI_FEDEX_CLIENT_ID':'','ADSI_FEDEX_CLIENT_SECRET':'','ADSI_FEDEX_SANDBOX':'0'}):
            async with httpx.AsyncClient(transport=httpx.MockTransport(send)) as client:
                adapter=parcel.Parcel(client)
                self.assertIsNone(await adapter.lookup(tracking,True))
                self.assertEqual(len(requests),0)
                self.assertEqual((await adapter.lookup(tracking,False))['displayTitle'],'DEMO FEDEX')
                with patch.dict('os.environ',{'ADSI_FEDEX_CLIENT_ID':'synthetic','ADSI_FEDEX_CLIENT_SECRET':'synthetic'}):
                    output=await adapter.lookup(tracking,True)
                    self.assertEqual(output['status'],'In transit')
                    self.assertNotIn('Not returned',str(output))
                    self.assertNotIn(tracking,str(output))
                    self.assertIsNone(await adapter.lookup('000000000003',True))
                    self.assertEqual(len(requests),3)  # token reused, mismatched response rejected
