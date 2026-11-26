"""ShadyBucks member banking over a private, acknowledged ADSI call."""

import asyncio
import hmac
import json
import os
import re
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, UTC
from decimal import Decimal
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from . import graph, wire


PAN = re.compile(r'[0-9]{8,19}')
PIN = re.compile(r'[0-9]{4,8}')
TOKEN = re.compile(r'[A-Za-z0-9_-]{43}')
MONEY = re.compile(r'-?(?:0|[1-9][0-9]{0,5})\.[0-9]{2}')
DEMO_CARD = '9000000000000001'
DEMO_RECIPIENT = '9000000000000002'
DEMO_PIN = '123456'


class Rejected(RuntimeError):
    pass


class Unavailable(RuntimeError):
    pass


class UnknownTransfer(RuntimeError):
    pass


def money(value):
    if not isinstance(value,str) or not MONEY.fullmatch(value):
        raise Unavailable('Invalid bank response')
    return Decimal(value)


def sb(value):
    return f'SB {value:.2f}'


def safe(value, maximum=100):
    return graph.handset_text(str(value or ''))[:maximum]


@dataclass(repr=False)
class Session:
    token: str
    expires: float
    card_last4: str

    def active(self):
        return asyncio.get_running_loop().time() < self.expires


class LiveBank:
    def __init__(self, client, url, service_key):
        self.client=client
        self.key=service_key
        try:
            parts=urlsplit(url)
            valid=(parts.scheme=='https' and parts.hostname and parts.username is None and parts.password is None
                   and not parts.query and not parts.fragment)
        except ValueError:
            valid=False
        self.base=url.rstrip('/') if valid and len(service_key)>=32 else None

    async def _request(self, method, endpoint, *, form=None, session=None, mutation=False):
        if not self.base or (session and not session.active()):
            raise Unavailable('Member service unavailable')
        headers={'X-Shadybank-Member-Key':self.key,'Accept':'application/json'}
        if session:
            headers['Authorization']='Bearer '+session.token
        try:
            async with self.client.stream(method,self.base+'/api/member/'+endpoint,headers=headers,
                                          data=form,timeout=8,follow_redirects=False) as response:
                if response.status_code in (400,401,403,409,429):
                    raise Rejected('Member request declined')
                if response.status_code not in (200,201,204):
                    raise UnknownTransfer('Transfer status unknown') if mutation else Unavailable('Member service unavailable')
                if response.status_code==204:
                    return None
                data=bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data)>100_000:
                        raise ValueError('Response too large')
                return json.loads(data)
        except (httpx.HTTPError, ValueError, TypeError):
            if mutation:
                raise UnknownTransfer('Transfer status unknown') from None
            raise Unavailable('Member service unavailable') from None

    async def login(self, pan, pin):
        if not PAN.fullmatch(pan) or not PIN.fullmatch(pin):
            raise Rejected('Member request declined')
        data=await self._request('POST','login',form={'pan':pan,'pin':pin})
        try:
            token,ttl=data['token'],data['expires_in']
            if not TOKEN.fullmatch(token) or type(ttl) is not int or not 1<=ttl<=300:
                raise ValueError('Invalid member session')
            return Session(token,asyncio.get_running_loop().time()+ttl,pan[-4:])
        except (TypeError,ValueError,KeyError):
            raise Unavailable('Member service unavailable') from None

    async def logout(self, session):
        # The server will also expire the short-lived token, even if the call is interrupted.
        if session.active():
            with suppress(Rejected,Unavailable,UnknownTransfer):
                await self._request('POST','logout',session=session)

    async def balance(self,session):
        data=await self._request('GET','balance',session=session)
        try:
            return money(data['balance']),money(data['available'])
        except (KeyError,TypeError):
            raise Unavailable('Member service unavailable') from None

    async def activity(self,session,holds=False):
        data=await self._request('GET','authorizations' if holds else 'transactions',session=session)
        if not isinstance(data,list) or len(data)>10:
            raise Unavailable('Member service unavailable')
        result=[]
        try:
            for row in data:
                amount=money(row['amount'])
                direction=row['direction']
                if amount<=0 or direction not in ('debit','credit'):
                    raise ValueError('Invalid activity')
                timestamp=datetime.fromisoformat(row['timestamp'])
                result.append({'date':timestamp.strftime('%d %b %Y'),
                               'amount':-amount if direction=='debit' else amount,
                               'name':safe(row.get('counterparty')),'detail':safe(row.get('description') or row.get('type')),
                               'expires':safe(row.get('expires')) if holds else ''})
        except (KeyError,TypeError,ValueError,AttributeError):
            raise Unavailable('Member service unavailable') from None
        return result

    async def transfer(self,session,recipient,amount,request_id):
        if not PAN.fullmatch(recipient) or amount<=0 or amount>Decimal('999999.99'):
            raise Rejected('Member request declined')
        data=await self._request('POST','transfer',session=session,mutation=True,
            form={'recipient_pan':recipient,'amount':f'{amount:.2f}','request_id':str(request_id)})
        try:
            if data['status']!='posted' or type(data['transaction_id']) is not int or data['transaction_id']<=0 or money(data['amount'])!=amount:
                raise ValueError('Unconfirmed transfer')
            return str(data['transaction_id'])
        except (TypeError,ValueError,KeyError,Unavailable):
            raise UnknownTransfer('Transfer status unknown') from None


@dataclass
class FixtureAccount:
    balance: Decimal
    activity: list = field(default_factory=list)


class DemoBank:
    """Synthetic per-process ledger, never linked to a real member account."""
    def __init__(self):
        self.accounts={DEMO_CARD:FixtureAccount(Decimal('123.45')),
                       DEMO_RECIPIENT:FixtureAccount(Decimal('42.00'))}
        self.sessions={}
        self.receipts={}
        self.lock=asyncio.Lock()

    async def login(self,pan,pin):
        if pan not in self.accounts or not hmac.compare_digest(pin,DEMO_PIN):
            raise Rejected('Member request declined')
        token=uuid4().hex
        session=Session(token,asyncio.get_running_loop().time()+300,pan[-4:])
        self.sessions[token]=pan
        return session

    def _account(self,session):
        if not session.active() or session.token not in self.sessions:
            raise Unavailable('Member service unavailable')
        return self.sessions[session.token]

    async def logout(self,session):
        self.sessions.pop(session.token,None)

    async def balance(self,session):
        account=self.accounts[self._account(session)]
        return account.balance,account.balance

    async def activity(self,session,holds=False):
        account=self.accounts[self._account(session)]
        return [] if holds else list(reversed(account.activity[-10:]))

    async def transfer(self,session,recipient,amount,request_id):
        async with self.lock:
            sender=self._account(session)
            if recipient not in self.accounts or recipient==sender or not Decimal('0')<amount<=Decimal('999999.99'):
                raise Rejected('Member request declined')
            key=(sender,request_id)
            previous=self.receipts.get(key)
            if previous:
                if previous[:2]!=(recipient,amount):
                    raise Rejected('Member request declined')
                return previous[2]
            source,target=self.accounts[sender],self.accounts[recipient]
            if source.balance<amount or target.balance+amount>Decimal('999999.99'):
                raise Rejected('Member request declined')
            source.balance-=amount; target.balance+=amount
            reference=str(len(self.receipts)+1)
            for account,value,name in ((source,-amount,'Demo recipient'),(target,amount,'Demo sender')):
                account.activity.append({'date':datetime.now(UTC).strftime('%d %b %Y'),'amount':value,'name':name,
                                         'detail':'Synthetic transfer','expires':''})
            self.receipts[key]=(recipient,amount,reference)
            return reference


def configured(client):
    mode=os.getenv('ADSI_SHADYBANK_MODE','disabled')
    if mode=='demo':
        return DemoBank(), True
    if mode=='live':
        bank=LiveBank(client,os.getenv('ADSI_SHADYBANK_URL',''),os.getenv('ADSI_SHADYBANK_SERVICE_KEY',''))
        return (bank,False) if bank.base else (None,False)
    return None,False


async def screen(link,lines,keys,slots=None):
    await link.transfer(wire.screen(lines,keys,slots=slots),open_input=True)


async def collect(link,title,lines,minimum,maximum):
    """Never echo the typed digits; collect during one acknowledged input interval."""
    await screen(link,[title,*lines],[('Erase','*'),('Submit','#')],[4,5])
    digits=''
    deadline=asyncio.get_running_loop().time()+60
    for _ in range(64):
        digit=await link.selection(max(0,deadline-asyncio.get_running_loop().time()))
        if digit=='#':
            return digits if minimum<=len(digits)<=maximum else None
        if digit=='*':
            if not digits:
                return None
            digits=digits[:-1]
        elif digit in '0123456789':
            if len(digits)>=maximum:
                return None
            digits+=digit
    return None


async def acknowledge(link,lines):
    await screen(link,lines,[('Back','0')],[6])
    await link.selection(30)


async def show_activity(link,rows,holds):
    if not rows:
        await acknowledge(link,['PENDING HOLDS' if holds else 'ACTIVITY','No entries to show'])
        return
    index=0
    for _ in range(80):
        row=rows[index]
        title=f'{"HOLDS" if holds else "ACTIVITY"} {index+1}/{len(rows)}'
        keys=[('Back','0')]; slots=[6]
        if row['detail'] or row['expires']:
            keys.append(('Detail','1'));slots.append(1)
        if index:
            keys.append(('Prev','7'));slots.append(4)
        if index+1<len(rows):
            keys.append(('Next','9'));slots.append(5)
        await screen(link,[title,row['date'],sb(row['amount']),row['name'][:20] or 'Member activity'],keys,slots)
        digit=await link.selection(40)
        if digit=='0':
            return
        if digit=='7' and index:
            index-=1
        elif digit=='9' and index+1<len(rows):
            index+=1
        elif digit=='1' and (row['detail'] or row['expires']):
            pages=graph.screen_pages({'layout':'information'},['ACTIVITY DETAIL',row['detail'] or 'Pending authorization',
                                                                  row['expires']])
            page=0
            for _ in range(40):
                detail_keys=[('Back','0')]; detail_slots=[6]
                if page:
                    detail_keys.append(('Prev','7'));detail_slots.append(4)
                if page+1<len(pages):
                    detail_keys.append(('Next','9'));detail_slots.append(5)
                await screen(link,pages[page],detail_keys,detail_slots)
                choice=await link.selection(40)
                if choice=='0': break
                if choice=='7' and page: page-=1
                if choice=='9' and page+1<len(pages): page+=1


async def transfer_menu(bank,session,link):
    recipient=await collect(link,'TRANSFER',['Recipient card no.','Submit when ready','* erases or backs'],8,19)
    if not recipient:
        return
    cents=await collect(link,'TRANSFER AMOUNT',['Enter amount cents','1250 = SB 12.50','Submit when ready'],1,8)
    if not cents or int(cents)<=0:
        return
    amount=Decimal(int(cents))/100
    await screen(link,['CONFIRM TRANSFER',f'To card ...{recipient[-4:]}',sb(amount),'Send this transfer?'],
                 [('Send','1'),('Cancel','0')],[1,6])
    if await link.selection(30)!='1':
        return
    request_id=uuid4()
    try:
        reference=await bank.transfer(session,recipient,amount,request_id)
    except Rejected:
        await acknowledge(link,['TRANSFER DECLINED','No transfer posted'])
    except (UnknownTransfer,Unavailable):
        # Do not retry a potentially committed mutation based on a lost network response.
        await acknowledge(link,['STATUS UNKNOWN','Check activity first','Do not send again'])
    else:
        await acknowledge(link,['TRANSFER POSTED',sb(amount),f'Ref {reference}'[:20]])


async def call(bank,demo,link,say):
    if bank is None:
        await say('ShadyBank is unavailable.')
        return
    if not await link.connect():
        await say('ShadyBank requires a display telephone.')
        return
    session=None
    normal=False
    try:
        async with asyncio.timeout(300):
            for attempt in range(3):
                pan=await collect(link,'DEMO SHADYBANK' if demo else 'SHADYBANK',['Enter card number','Keypad then Submit','* erases or backs'],8,19)
                if not pan:
                    break
                pin=await collect(link,'MEMBER PIN',['Enter ShadyBucks PIN','PIN is not shown','Submit when ready'],4,8)
                if not pin:
                    break
                try:
                    session=await bank.login(pan,pin)
                    break
                except Rejected:
                    await screen(link,['LOGIN FAILED','Check card and PIN'],[('Retry','1'),('Exit','0')],[1,6])
                    if await link.selection(20)!='1':
                        break
                finally:
                    pan=pin=''
            if session:
                for _ in range(60):
                    if not session.active():
                        break
                    await screen(link,['DEMO SHADYBANK' if demo else 'SHADYBANK',f'Card ...{session.card_last4}',
                                       'Select a service','ShadyBucks credits'],
                                 [('Balance','1'),('History','2'),('Holds','3'),('Send','4'),('Exit','0')],[1,2,3,4,6])
                    digit=await link.selection(60)
                    if digit=='0':break
                    if digit=='1':
                        posted,available=await bank.balance(session)
                        await acknowledge(link,['BALANCE',sb(posted),'Available',sb(available)])
                    elif digit in ('2','3'):
                        await show_activity(link,await bank.activity(session,holds=digit=='3'),digit=='3')
                    elif digit=='4':
                        await transfer_menu(bank,session,link)
            normal=True
    except (TimeoutError,Rejected,Unavailable):
        normal=True
    finally:
        if session:
            with suppress(TimeoutError,Unavailable,Rejected,httpx.HTTPError):
                await asyncio.wait_for(bank.logout(session),3)
        if normal and link.display_active and not link.uncertain:
            await link.transfer(wire.screen(['GOODBYE'],[]))
            await link.release()
