import base64
import unittest
from datetime import UTC, datetime
from decimal import Decimal

import httpx

from coinline_adsi.balances import Approvals, ProviderUnavailable, SimpleFIN


class BalanceTests(unittest.IsolatedAsyncioTestCase):
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
