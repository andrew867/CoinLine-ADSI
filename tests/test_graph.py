import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from coinline_adsi import graph, providers
from coinline_adsi.main import app


ROOT = Path(__file__).parents[1]
EXAMPLE = json.loads((ROOT / "fixtures/apps/weather.graph.json").read_text(encoding="utf-8"))
INFOLINE = json.loads((ROOT / "service/coinline_adsi/infoline.json").read_text(encoding="utf-8"))
REGIONAL = json.loads((ROOT / "service/coinline_adsi/infoline-regional.json").read_text(encoding="utf-8"))
HEADERS = {"X-Coinline-CSRF": "request"}


class GraphTests(unittest.IsolatedAsyncioTestCase):
    async def test_bundled_graph_validation(self):
        self.assertEqual(graph.validate(EXAMPLE), [])
        self.assertEqual(graph.validate(INFOLINE), [])
        self.assertEqual(graph.validate(REGIONAL), [])

    async def test_weather_success_failure_and_return(self):
        for fault, expected in ((None, "DEMO WEATHER"), ("stale", "STALE DEMO WX"), ("unavailable", "DEMO WX UNAVAILABLE")):
            with self.subTest(fault=fault):
                async def lookup(operation, args):
                    return providers.fixture(operation, args, fault)

                session = graph.Session(EXAMPLE)
                self.assertTrue(session.choose("1"))
                view = await session.settle(lookup)
                self.assertEqual(view["lines"][0], expected)
                self.assertTrue(session.choose("0"))
                self.assertEqual(session.view()["node"], "welcome")
                session.timeout()
                self.assertTrue(session.view()["ended"])

    async def test_duplicate_and_automatic_cycle(self):
        fixture = copy.deepcopy(EXAMPLE)
        fixture["nodes"][0]["choices"][1]["digit"] = "1"
        self.assertIn("Menu digits must be unique.", [issue["message"] for issue in graph.validate(fixture)])
        fixture = copy.deepcopy(EXAMPLE)
        fixture["nodes"][1]["onUnavailable"] = "fetch"
        self.assertIn("Automatic transitions contain a cycle.", [issue["message"] for issue in graph.validate(fixture)])

    async def test_prefix(self):
        self.assertEqual(providers.prefix("+17095550123"), "709555")
        self.assertIsNone(providers.prefix("withheld"))
        self.assertIsNone(providers.prefix("5550123"))


class ConsoleTests(unittest.TestCase):
    def test_transit_stop_and_route_simulation(self):
        document = json.loads((ROOT / "service/coinline_adsi/infoline-travel.json").read_text(encoding="utf-8"))
        with patch.dict("os.environ", {"ADSI_ADMIN_PASSWORD": "synthetic-console"}), TestClient(app) as client:
            client.post("/api/v1/session", headers=HEADERS, json={"password": "synthetic-console"}).raise_for_status()
            response = client.post("/api/v1/simulations", headers=HEADERS, json={"graph": document}).raise_for_status()
            path=f"/api/v1/simulations/{response.json()['id']}/events"
            def press(digit):
                return client.post(path,headers=HEADERS,json={"digit":digit}).raise_for_status().json()
            for digit in "533":
                press(digit)
            self.assertEqual(press('1')['lines'][0],'BUS STOP')
            for digit in '9000':
                press(digit)
            self.assertEqual(press('#')['lines'][0],'DEMO BUS SCHEDULE')
            self.assertEqual(press('0')['node'],'transit')
            self.assertEqual(press('2')['lines'][0],'Demo route')
            self.assertEqual(press('1')['lines'][0],'Demo stop')
            self.assertEqual(press('1')['lines'][0],'DEMO BUS SCHEDULE')

    def test_screenphone_parcel_simulation(self):
        document = json.loads((ROOT / "service/coinline_adsi/infoline-screenphone.json").read_text(encoding="utf-8"))
        with patch.dict("os.environ", {"ADSI_ADMIN_PASSWORD": "synthetic-console"}), TestClient(app) as client:
            client.post("/api/v1/session", headers=HEADERS, json={"password": "synthetic-console"}).raise_for_status()
            response = client.post("/api/v1/simulations", headers=HEADERS, json={"graph": document})
            response.raise_for_status()
            path=f"/api/v1/simulations/{response.json()['id']}/events"
            def press(digit):
                result=client.post(path,headers=HEADERS,json={"digit":digit})
                result.raise_for_status()
                return result.json()
            press('5')
            self.assertEqual(press('5')['lines'][0], 'TRACK A PARCEL')
            for digit in '000000000002':
                press(digit)
            self.assertIn('Ending in 0002',press('#')['lines'])
            self.assertEqual(press('1')['lines'][0], 'DEMO FEDEX')
            self.assertEqual(press('0')['node'],'services')
            self.assertEqual(press('5')['lines'][0], 'TRACK A PARCEL')
            self.assertEqual(press('*')['node'],'parcel-unavailable')

    def test_session_and_fixture_simulator(self):
        with patch.dict("os.environ", {"ADSI_ADMIN_PASSWORD": "synthetic-console"}), TestClient(app) as client:
            self.assertEqual(client.get("/api/v1/session").status_code, 401)
            self.assertEqual(client.post("/api/v1/session", json={"password": "synthetic-console"}).status_code, 403)
            response = client.post("/api/v1/session", headers=HEADERS, json={"password": "synthetic-console"})
            self.assertEqual(response.status_code, 200, response.text)
            response = client.post("/api/v1/simulations", headers=HEADERS,
                                   json={"graph": EXAMPLE, "fault": "unavailable"})
            self.assertEqual(response.status_code, 201, response.text)
            request = f"/api/v1/simulations/{response.json()['id']}/events"
            response = client.post(request, headers=HEADERS, json={"digit": "1"})
            self.assertEqual(response.json()["lines"], ["DEMO WX UNAVAILABLE"])
            response = client.post(request, headers=HEADERS, json={"hangup": True})
            self.assertTrue(response.json()["ended"])
