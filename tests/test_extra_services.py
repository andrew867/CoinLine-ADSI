import json
import importlib.util
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import httpx

from coinline_adsi import directory, flights, graph, keypad, providers


ROOT = Path(__file__).resolve().parents[1]
SERVICES = json.loads((ROOT / 'service/coinline_adsi/infoline-services.json').read_text(encoding='utf-8'))


class SearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_asterisk_directory_import_excludes_hidden_and_credentials(self):
        spec = importlib.util.spec_from_file_location('import_directory', ROOT / 'deploy/import_directory.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        source = ['[private]', '7000 => 1111,Hidden example', '[public-directory]',
                  '7001 => 2222,Demo reception,invalid@example.test,,skipms=3',
                  '7002 => 3333,Hidden example,,,hidefromdir=yes', '[other]', '7003 => 4444,Other example']
        self.assertEqual(list(module.entries(source, 'public-directory')),
                         [{'name': 'Demo reception', 'number': '7001', 'detail': 'PBX extension'}])

    async def test_icao_and_iata_prefixes(self):
        self.assertEqual(keypad.signature('CYYT'), '2998')
        self.assertEqual(keypad.signature('YYT'), '998')
        for code in ('998', '2998'):
            counts = [len(keypad.matches(flights.ENTRIES, code[:i])) for i in range(len(code) + 1)]
            self.assertEqual(counts, sorted(counts, reverse=True))
            self.assertIn('YYT', [entry[0] for entry in keypad.matches(flights.ENTRIES, code)])
        self.assertIn('YYZ', flights.INDEX)
        self.assertEqual(len(flights.INDEX), len(flights.AIRPORTS))
        self.assertEqual(keypad.heading('Airport', '2998', 2), 'Airport 2998 [2]')
        self.assertLessEqual(len(keypad.heading('Directory', '23456789', 1000)), 20)

    async def test_search_backspace_and_select(self):
        link = AsyncMock()
        link.display_active = True
        link.selection.side_effect = ['9', '8', '*', '9', '8', '1', '1']
        entries = [('YYT', 'YYT CYYT', ('YYT', 'CYYT')), ('YYZ', 'YYZ CYYZ', ('YYZ', 'CYYZ'))]
        self.assertEqual(await keypad.select(link, AsyncMock(), 'Airport', entries), 'YYT')
        self.assertEqual(link.transfer.await_count, 7)
        self.assertTrue(all(call.kwargs['open_input'] for call in link.transfer.await_args_list))
        for call in link.transfer.await_args_list:
            frame = call.args[0]
            self.assertEqual(sum(frame) % 256, 0)

    async def test_cancel_no_result_and_voice_fallback(self):
        link = AsyncMock()
        link.display_active = False
        link.open_voice_input = Mock()
        link.selection.side_effect = ['2', '1', '0']
        say = AsyncMock()
        self.assertIsNone(await keypad.select(link, say, 'Airport', [('YYT', 'YYT', ('YYT',))]))
        self.assertEqual(say.await_count, 3)
        link.selection.side_effect = TimeoutError
        self.assertIsNone(await keypad.select(link, say, 'Airport', []))

    async def test_graph_fixture_and_fault(self):
        self.assertEqual(graph.validate(SERVICES), [])
        for digits, expected in [('511', 'DEMO YYT'), ('512', 'DEMO YYT'), ('52', 'DEMO DIRECTORY')]:
            session = graph.Session(SERVICES)
            for digit in digits:
                self.assertTrue(session.choose(digit))
            async def lookup(operation, args):
                return providers.fixture(operation, args)
            result = await session.settle(lookup)
            self.assertEqual(result['lines'][0], expected)
            self.assertTrue(session.choose('0'))
        session = graph.Session(SERVICES)
        for digit in '511':
            session.choose(digit)
        result = await session.settle(AsyncMock(return_value=None))
        self.assertEqual(result['lines'][0], 'BOARD UNAVAILABLE')

    async def test_directory_validation_and_selection(self):
        config = {'directory': [{'name': 'Demo Help', 'number': '7001', 'detail': 'Local extension'}]}
        providers.check_config(config)
        link = AsyncMock()
        link.display_active = True
        link.selection.side_effect = ['4', '3', '5', '7', '1', '1']
        number = await directory.choose(link, AsyncMock(), config)
        self.assertEqual(number, '7001')
        self.assertEqual(directory.lookup(config, number)['source'], 'Local directory')
        self.assertIsNone(directory.lookup({'directory': []}, 'selected'))
        with self.assertRaises(ValueError):
            providers.check_config({'directory': [{'name': 'Demo', 'number': 'SIP:invalid', 'detail': 'Example'}]})


class FlightTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def payload(now):
        return {'data': [{'flight': {'iata': 'ZZ101'}, 'flight_status': 'scheduled',
                          'arrival': {'iata': 'YYT', 'scheduled': now.isoformat(), 'delay': 20},
                          'departure': {'iata': 'YYZ', 'scheduled': now.isoformat()}}]}

    async def test_parser_date_direction_and_validation(self):
        now = datetime(2026, 1, 1, 12, 30, tzinfo=UTC)
        data = self.payload(now)
        self.assertEqual(flights.parse(data, 'YYT', 'airport.arrivals', now), ['ZZ101 YYZ 01/12:30 DLY'])
        self.assertEqual(flights.parse(data, 'YYZ', 'airport.departures', now), ['ZZ101 YYT 01/12:30 SCH'])
        self.assertIsNone(flights.parse(data, 'YHZ', 'airport.arrivals', now))
        self.assertIsNone(flights.parse({'error': {}}, 'YYT', 'airport.arrivals', now))
        self.assertEqual(flights.parse({'data': []}, 'YYT', 'airport.arrivals', now), ['No flights returned'])

    async def test_live_opt_in_cache_quota_and_no_fixture_on_failure(self):
        requests = []
        def handle(request):
            requests.append(request)
            self.assertEqual(request.url.host, 'api.apilayer.net')
            self.assertEqual(request.url.params.get('arr_iata'), 'YYT')
            return httpx.Response(200, json=self.payload(datetime.now(UTC)))
        with tempfile.TemporaryDirectory() as cache, patch.dict('os.environ', {
            'ADSI_PROVIDER_CACHE_DIR': cache, 'ADSI_AVIATIONSTACK_KEY': ''}):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
                provider = flights.Flights(client)
                self.assertIsNone(await provider.lookup('airport.arrivals', 'YYT', True))
                self.assertEqual(len(requests), 0)
                record = await provider.lookup('airport.arrivals', 'YYT', False)
                self.assertEqual(record['displayTitle'], 'DEMO YYT')
                with patch.dict('os.environ', {'ADSI_AVIATIONSTACK_KEY': 'synthetic'}):
                    first = await provider.lookup('airport.arrivals', 'YYT', True)
                    second = await provider.lookup('airport.arrivals', 'YYT', True)
                    self.assertEqual(first, second)
                    self.assertEqual(first['displayTitle'], 'LIVE YYT')
                    self.assertEqual(len(requests), 1)
                    self.assertTrue(provider.cache.quota('aviationstack', 3, cost=2))
                    self.assertIsNone(await provider.lookup('airport.arrivals', 'YHZ', True))
                    self.assertEqual(len(requests), 1)
                provider.close()
