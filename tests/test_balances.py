import base64
import json
import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock

import httpx

from coinline_adsi.balances import Approvals, ProviderUnavailable, SimpleFIN
from coinline_adsi.private import PrivateBalances


class BalanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_private_call_approval_balance_and_recent_transactions(self):
        now = datetime.now(UTC)
        requests = []
        enrolled = {}

        async def query(sql, parameters):
            if "FROM bank_links WHERE phone_key" in sql:
                return enrolled.copy()
            if "FROM bank_links WHERE subject" in sql:
                return {"sealed": enrolled["sealed"]}
            if sql.startswith("INSERT INTO bank_reads"):
                return {"used": 1}
            self.fail("Unexpected database operation")

        store = type("TestStore", (), {})()
        store._one = AsyncMock(side_effect=query)
        def route(request):
            requests.append(request.url.params)
            account = {"id": "fixture-account", "conn_id": "fixture-connection", "currency": "CAD",
                       "balance": "42.17", "balance-date": int(now.timestamp())}
            if "balances-only" not in request.url.params:
                account["transactions"] = [
                    {"posted": int((now - timedelta(days=2)).timestamp()), "amount": "-2.50", "description": "Fixture purchase"},
                    {"posted": int((now - timedelta(days=1)).timestamp()), "amount": "12.00", "description": "Fixture deposit"},
                ]
            return httpx.Response(200, json={"accounts": [account]})

        async with httpx.AsyncClient(transport=httpx.MockTransport(route)) as client:
            service = PrivateBalances(store, client, b"fixture-key" * 3)
            subject = service.local_subject()
            enrolled.update(subject=subject, alias="Fixture", sealed=service.cipher.encrypt(json.dumps({
                "access": "https://fixture:fixture@bridge.simplefin.org/simplefin", "account": "fixture-account",
                "connection": "fixture-connection"}).encode()))
            screens, digits = [], []
            class FixtureLink:
                data_mode = True
                released = False
                async def transfer(self, data, **kwargs):
                    screens.append(data)
                    if b"Approval" in data:
                        self.assert_no_read()
                        challenge = next(iter(service.approvals.pending))
                        self.assert_wrong_subject(challenge)
                        code = service.approvals.approve(challenge, subject)
                        digits.extend(code + "190")
                async def selection(self, timeout):
                    return digits.pop(0)
                async def release(self):
                    self.released = True
                def assert_no_read(self):
                    if requests:
                        raise AssertionError("Provider read before approval")
                def assert_wrong_subject(self, challenge):
                    if service.approvals.approve(challenge, "foreign-subject") is not None:
                        raise AssertionError("Foreign approval accepted")
            link = FixtureLink()
            await service.call("7095550100", link, AsyncMock(), connected=True, expected_subject=subject)
            self.assertEqual(len(requests), 2)
            self.assertTrue(any(b"CAD 42.17" in screen for screen in screens))
            self.assertTrue(any(b"Fixture deposit" in screen for screen in screens))
            self.assertTrue(any(b"Fixture purchase" in screen for screen in screens))
            self.assertIn(b"GOODBYE", screens[-1])
            self.assertTrue(link.released)
            self.assertFalse(service.approvals.pending)
            await service.call("7095550100", FixtureLink(), AsyncMock(), connected=True, expected_subject="foreign-subject")
            self.assertEqual(len(requests), 2)

    async def test_connection_inspection_preserves_phone_freshness_gate(self):
        now = datetime(2026, 2, 7, 15, tzinfo=UTC)
        stamp = int((now + timedelta(minutes=15)).timestamp())
        def route(request):
            return httpx.Response(200, json={"accounts": [{"id": "fixture-account", "conn_id": "fixture-connection",
                "currency": "CAD", "balance": "42.17", "balance-date": stamp}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(route)) as client:
            adapter = SimpleFIN(client)
            url = "https://fixture:fixture@bridge.simplefin.org/simplefin"
            with self.assertRaises(ProviderUnavailable):
                await adapter.balance(url, "fixture-connection", "fixture-account", now)
            result = await adapter.balance(url, "fixture-connection", "fixture-account", now, require_current=False)
            self.assertEqual(result.freshness(now), "future")

    async def test_claim_is_saved_before_account_lookup_and_survives_restart(self):
        pending = {}
        requests = []

        async def query(sql, parameters):
            if sql.startswith("INSERT INTO bank_pending"):
                if pending:
                    return None
                pending.update(claim_id=parameters[1], access_sealed=None, choices_sealed=None)
            elif sql.startswith("UPDATE bank_pending SET access_sealed"):
                pending["access_sealed"] = parameters[0]
            elif sql.startswith("SELECT claim_id"):
                return pending.copy()
            elif sql.startswith("INSERT INTO bank_reads"):
                return {"used": 1}
            elif sql.startswith("UPDATE bank_pending SET choices_sealed"):
                pending["choices_sealed"] = parameters[0]
            else:
                self.fail("Unexpected database operation")
            return {"claim_id": pending["claim_id"]}

        store = type("TestStore", (), {})()
        store._one = AsyncMock(side_effect=query)
        access = "https://fixture:fixture@bridge.simplefin.org/simplefin"
        def route(request):
            requests.append(request.method)
            if request.method == "POST":
                return httpx.Response(200, text=access)
            if requests.count("GET") == 1:
                return httpx.Response(503)
            return httpx.Response(200, json={"accounts": [{"id": "fixture-account", "conn_id": "fixture-connection", "name": "Fixture account"}]})

        async with httpx.AsyncClient(transport=httpx.MockTransport(route)) as client:
            token = base64.b64encode(b"https://bridge.simplefin.org/simplefin/claim/demo").decode()
            service = PrivateBalances(store, client, b"fixture-key" * 3)
            with self.assertRaises(ProviderUnavailable):
                await service.claim("fixture-owner", token)
            self.assertIsNotNone(pending["access_sealed"])
            self.assertNotIn(access.encode(), pending["access_sealed"])
            restarted = PrivateBalances(store, client, b"fixture-key" * 3)
            with self.assertRaisesRegex(ProviderUnavailable, "already pending"):
                await restarted.claim("fixture-owner", token)
            choices = await restarted.resume("fixture-owner")
            self.assertEqual(choices[0]["label"], "Fixture account")
            self.assertEqual(await restarted.resume("fixture-owner"), choices)
            self.assertEqual(requests, ["POST", "GET", "GET"])
            self.assertNotIn(b"Fixture account", pending["choices_sealed"])

    async def test_recent_transactions_bound_to_enrolled_account(self):
        now = datetime(2026, 2, 7, 15, tzinfo=UTC)
        def route(request):
            self.assertNotIn("balances-only", request.url.params)
            self.assertEqual(request.url.params["account"], "fixture-account")
            self.assertEqual(int(request.url.params["end-date"]), int(now.timestamp()))
            self.assertEqual(int(request.url.params["end-date"]) - int(request.url.params["start-date"]), 30 * 86400)
            return httpx.Response(200, json={"accounts": [{"id": "fixture-account", "conn_id": "fixture-connection", "currency": "CAD", "transactions": [
                {"posted": int(now.timestamp()) - 600, "description": "Demo deposit", "amount": "42.17"},
                {"posted": 0, "description": "Pending", "amount": "-5.00"},
            ]}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(route)) as client:
            adapter = SimpleFIN(client)
            url = "https://fixture:fixture@bridge.simplefin.org/simplefin"
            records = await adapter.transactions(url, "fixture-connection", "fixture-account", now)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].amount, Decimal("42.17"))
            with self.assertRaises(ProviderUnavailable):
                await adapter.transactions(url, "wrong-connection", "fixture-account", now)

    async def test_demo_provider_claim_and_read(self):
        now = datetime(2026, 2, 7, 15, tzinfo=UTC)

        def route(request):
            if request.method == "POST":
                self.assertEqual(request.url.path, "/simplefin/claim/demo")
                return httpx.Response(200, text="https://fixture:fixture@bridge.simplefin.org/simplefin")
            self.assertEqual(request.url.params["balances-only"], "1")
            self.assertEqual(request.url.params["account"], "fixture-account")
            return httpx.Response(200, json={"accounts": [{
                "id": "fixture-account", "conn_id": "fixture-connection", "currency": "CAD",
                "balance": "-42.17", "available-balance": "100.30", "balance-date": int(now.timestamp()),
            }]})

        async with httpx.AsyncClient(transport=httpx.MockTransport(route)) as client:
            adapter = SimpleFIN(client)
            token = base64.b64encode(b"https://bridge.simplefin.org/simplefin/claim/demo").decode()
            url = await adapter.claim(token)
            result = await adapter.balance(url, "fixture-connection", "fixture-account", now)
            self.assertEqual(result.posted, Decimal("-42.17"))
            self.assertEqual(result.available, Decimal("100.30"))
            with self.assertRaises(ProviderUnavailable):
                await adapter.balance(url, "different-connection", "fixture-account", now)

    async def test_endpoint_allowlist_and_redirects(self):
        bad = base64.b64encode(b"https://example.invalid/simplefin/claim/demo").decode()
        seen = []
        def route(request):
            seen.append(request.url.host)
            return httpx.Response(302, headers={"Location": "https://example.invalid/"})
        async with httpx.AsyncClient(transport=httpx.MockTransport(route), follow_redirects=True) as client:
            adapter = SimpleFIN(client)
            with self.assertRaises(ProviderUnavailable):
                await adapter.claim(bad)
            self.assertEqual(seen, [])
            with self.assertRaises(ProviderUnavailable):
                await adapter.balance("https://fixture:fixture@bridge.simplefin.org/simplefin", "x", "y")
            self.assertEqual(seen, ["bridge.simplefin.org"])


class ApprovalTests(unittest.TestCase):
    def test_code_subject_call_expiry_and_replay(self):
        tick = 10
        pending = Approvals(b"synthetic key", lambda: tick)
        challenge = pending.new("subject", "call")
        self.assertIsNone(pending.approve(challenge, "different subject"))
        secret = pending.approve(challenge, "subject")
        self.assertFalse(pending.check(challenge, "different call", secret))
        self.assertTrue(pending.check(challenge, "call", secret))
        self.assertFalse(pending.check(challenge, "call", secret))
        second = pending.new("subject", "second")
        secret = pending.approve(second, "subject")
        tick += 120
        self.assertFalse(pending.check(second, "second", secret))
