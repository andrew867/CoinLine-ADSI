import asyncio
import os
import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs
from uuid import uuid4

import httpx

from coinline_adsi import shadybank
from coinline_adsi.asterisk import Gateway
from coinline_adsi.link import CONTINUOUS_DATA, VOICE_BETWEEN_SCREENS, LinkFailure


class ShadybankTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_contract_and_unknown_transfer(self):
        calls=[]
        token='x'*43
        key='synthetic-member-service-key-0000000000'
        def send(request):
            calls.append(request)
            self.assertEqual(request.headers['X-Shadybank-Member-Key'],key)
            endpoint=request.url.path.rsplit('/',1)[1]
            if endpoint=='login':
                self.assertEqual(parse_qs(request.content.decode()),{'pan':[shadybank.DEMO_CARD],'pin':[shadybank.DEMO_PIN]})
                return httpx.Response(201,json={'token':token,'expires_in':300})
            self.assertEqual(request.headers['Authorization'],'Bearer '+token)
            if endpoint=='balance':
                return httpx.Response(200,json={'balance':'123.45','available':'110.00'})
            if endpoint=='transactions':
                return httpx.Response(200,json=[{'timestamp':'2026-02-07T10:00:00','amount':'5.00',
                    'direction':'debit','type':'purchase','counterparty':'Demo store','description':'Example'}])
            if endpoint=='transfer':
                raise httpx.ReadTimeout('Synthetic missing response')
            if endpoint=='logout':
                return httpx.Response(204)
            raise AssertionError('Unexpected endpoint')
        async with httpx.AsyncClient(transport=httpx.MockTransport(send)) as client:
            self.assertIsNone(shadybank.LiveBank(client,'http://example.test',key).base)
            self.assertIsNone(shadybank.LiveBank(client,'https://example.test','short').base)
            bank=shadybank.LiveBank(client,'https://example.test',key)
            session=await bank.login(shadybank.DEMO_CARD,shadybank.DEMO_PIN)
            self.assertEqual(await bank.balance(session),(Decimal('123.45'),Decimal('110.00')))
            self.assertEqual((await bank.activity(session))[0]['amount'],Decimal('-5.00'))
            with self.assertRaises(shadybank.UnknownTransfer):
                await bank.transfer(session,shadybank.DEMO_RECIPIENT,Decimal('1.00'),uuid4())
            self.assertEqual(sum(call.url.path.endswith('/transfer') for call in calls),1)
            await bank.logout(session)

    async def test_demo_ledger_idempotence_and_scope(self):
        bank=shadybank.DemoBank()
        with self.assertRaises(shadybank.Rejected):
            await bank.login(shadybank.DEMO_CARD,'000000')
        session=await bank.login(shadybank.DEMO_CARD,shadybank.DEMO_PIN)
        identifier=uuid4()
        receipt=await bank.transfer(session,shadybank.DEMO_RECIPIENT,Decimal('12.50'),identifier)
        self.assertEqual(await bank.transfer(session,shadybank.DEMO_RECIPIENT,Decimal('12.50'),identifier),receipt)
        self.assertEqual((await bank.balance(session))[0],Decimal('110.95'))
        with self.assertRaises(shadybank.Rejected):
            await bank.transfer(session,shadybank.DEMO_RECIPIENT,Decimal('12.51'),identifier)
        with self.assertRaises(shadybank.Rejected):
            await bank.transfer(session,shadybank.DEMO_RECIPIENT,Decimal('200.00'),uuid4())
        await bank.logout(session)
        with self.assertRaises(shadybank.Unavailable):
            await bank.balance(session)

    @staticmethod
    def link(digits):
        link=AsyncMock();link.display_active=True;link.uncertain=False
        link.connect.return_value=True
        link.selection.side_effect=digits
        return link

    @staticmethod
    def entry(card=shadybank.DEMO_CARD, pin=shadybank.DEMO_PIN):
        return [*card,'#',*pin,'#']

    @staticmethod
    def transfer():
        return ['4',*shadybank.DEMO_RECIPIENT,'#',*'1250','#']

    async def test_call_confirm_cancel_and_private_input(self):
        bank=shadybank.DemoBank()
        digits=[*self.entry(),'1','0','2','0','3','0',*self.transfer(),'0',
                *self.transfer(),'1','0','2','0','0']
        link=self.link(digits)
        await shadybank.call(bank,True,link,AsyncMock())
        self.assertEqual(bank.accounts[shadybank.DEMO_CARD].balance,Decimal('110.95'))
        self.assertEqual(len(bank.receipts),1)
        self.assertFalse(bank.sessions)
        data=b''.join(call.args[0] for call in link.transfer.await_args_list)
        self.assertIn(b'CONFIRM TRANSFER',data)
        self.assertIn(b'TRANSFER POSTED',data)
        self.assertIn(b'PENDING HOLDS',data)
        self.assertNotIn(shadybank.DEMO_CARD.encode(),data)
        self.assertNotIn(shadybank.DEMO_RECIPIENT.encode(),data)
        self.assertNotIn(shadybank.DEMO_PIN.encode(),data)
        link.release.assert_awaited_once()

    async def test_unconfirmed_display_cannot_authorize_transfer(self):
        bank=shadybank.DemoBank()
        link=self.link([*self.entry(),*self.transfer(),'1'])
        async def send(data,**kwargs):
            if b'CONFIRM TRANSFER' in data:
                link.uncertain=True
                raise LinkFailure('Unconfirmed screen')
        link.transfer.side_effect=send
        with self.assertRaises(LinkFailure):
            await shadybank.call(bank,True,link,AsyncMock())
        self.assertFalse(bank.receipts)
        self.assertFalse(bank.sessions)
        self.assertEqual(bank.accounts[shadybank.DEMO_CARD].balance,Decimal('123.45'))

    async def test_pin_cooldown_is_card_scoped_and_prompts_do_not_reveal_enrollment(self):
        now = [100.0]
        bank = shadybank.DemoBank(shadybank.MemoryPinGate(lambda: now[0]))
        async def failed(card, pin):
            link = self.link([*self.entry(card, pin), '0'])
            await shadybank.call(bank, True, link, AsyncMock())
            self.assertFalse(bank.sessions)
            frames = b''.join(event.args[0] for event in link.transfer.await_args_list)
            self.assertIn(b'LOGIN FAILED', frames)
            return frames

        for _ in range(3):
            enrolled = await failed(shadybank.DEMO_CARD, '000000')
            unknown = await failed('9000000000000099', '000000')
            self.assertEqual(enrolled, unknown)
        self.assertEqual(await failed(shadybank.DEMO_CARD, shadybank.DEMO_PIN), enrolled)
        now[0] += shadybank.PIN_COOLDOWN - 1
        await failed(shadybank.DEMO_CARD, shadybank.DEMO_PIN)
        # Another card is unaffected, and blocked requests do not extend the cooldown.
        session = await bank.login(shadybank.DEMO_RECIPIENT, shadybank.DEMO_PIN)
        await bank.logout(session)
        now[0] += 1
        session = await bank.login(shadybank.DEMO_CARD, shadybank.DEMO_PIN)
        await bank.logout(session)
        self.assertNotIn(shadybank.card_key(bank.pin_gate.key, shadybank.DEMO_CARD), bank.pin_gate.entries)

    async def test_concurrent_and_cancelled_pin_attempts_are_reserved_before_verification(self):
        calls = []
        arrived = asyncio.Event()
        async def reject(request):
            calls.append(request.url.path)
            arrived.set()
            await asyncio.sleep(.03)
            return httpx.Response(401)
        async with httpx.AsyncClient(transport=httpx.MockTransport(reject)) as client:
            bank = shadybank.LiveBank(client, 'https://example.test', 'x' * 32)
            abandoned = asyncio.create_task(bank.login(shadybank.DEMO_CARD, '000000'))
            await arrived.wait()
            abandoned.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await abandoned
            outcomes = await asyncio.gather(*(bank.login(shadybank.DEMO_CARD, '000000') for _ in range(6)),
                                             return_exceptions=True)
            self.assertTrue(all(isinstance(outcome, shadybank.Rejected) for outcome in outcomes))
            self.assertEqual(len(calls), 3)
            with self.assertRaises(shadybank.Rejected):
                await bank.login(shadybank.DEMO_CARD, shadybank.DEMO_PIN)
            self.assertEqual(len(calls), 3)

    def test_live_configuration_requires_persistent_store_and_stable_key(self):
        settings = {'ADSI_SHADYBANK_MODE': 'live', 'ADSI_SHADYBANK_URL': 'https://example.test',
                    'ADSI_SHADYBANK_SERVICE_KEY': 'x' * 32, 'ADSI_DATA_KEY': '00' * 32}
        with patch.dict(os.environ, settings, clear=True):
            self.assertEqual(shadybank.configured(None), (None, False))
            bank, demo = shadybank.configured(None, object())
            self.assertIsInstance(bank.pin_gate, shadybank.PostgresPinGate)
            self.assertFalse(demo)
            with patch.dict(os.environ, {'ADSI_SHADYBANK_MODE': 'demo'}):
                bank, demo = shadybank.configured(None, object())
                self.assertTrue(demo)
                self.assertIsInstance(bank.pin_gate, shadybank.PostgresPinGate)
            with patch.dict(os.environ, {'ADSI_DATA_KEY': ''}):
                self.assertEqual(shadybank.configured(None, object()), (None, False))

    async def test_profile_scoping(self):
        gateway=Gateway('http://example.test','fixture',AsyncMock())
        try:
            self.assertEqual(gateway.interaction_profile('shadybank'),VOICE_BETWEEN_SCREENS)
            self.assertEqual(gateway.interaction_profile('infoline'),CONTINUOUS_DATA)
            self.assertEqual(gateway.interaction_profile('emu-infoline'),CONTINUOUS_DATA)
        finally:
            await gateway.http.aclose()
