"""FedEx read-only tracking. Numbers and results are never written to shared caches."""

import asyncio
import os
import re
import time

import httpx

from . import wire


NUMBER = re.compile(r'[0-9]{12,22}')

ENTRY_LINES = ['TRACK A PARCEL', 'Enter tracking no.', 'Press Submit when', 'finished. * erases.']
ENTRY_KEYS = [('Erase','*'),('Submit','#')]
CONFIRM_KEYS = [('Lookup','1'),('Retry','2'),('Back','0')]


def confirmation(digits):
    return ['CONFIRM TRACKING', f'{len(digits)} digits entered', f'Ending in {digits[-4:]}', 'Look up this parcel?']


async def collect(link, say, *, demo=False):
    """Collect in one voice interval, so rapid keypad entry is not lost during FSK."""
    digits = ''
    for attempt in range(3):
        lines = ENTRY_LINES.copy()
        if demo:
            lines[1] = 'Demo: sample number'
        if attempt and not digits:
            lines[2] = 'Use 12 to 22 digits'
            lines[3] = 'Submit when ready'
        if link.display_active:
            await link.transfer(wire.screen(lines, ENTRY_KEYS, slots=[4,5]), open_input=True)
        else:
            link.open_voice_input()
            await say(('Demo only. Enter a sample number. ' if demo else 'Enter your FedEx tracking number. ') +
                      'Use 12 to 22 digits. Press pound to submit, star to erase or cancel when empty.')
        deadline = asyncio.get_running_loop().time()+60
        try:
            for __ in range(64):
                digit = await link.selection(max(0, deadline-asyncio.get_running_loop().time()))
                if digit == '*':
                    if not digits:
                        return None
                    digits = digits[:-1]
                elif digit == '#':
                    break
                elif digit in '0123456789':
                    if len(digits)>=22:
                        return None
                    digits += digit
            else:
                return None
            if NUMBER.fullmatch(digits):
                if link.display_active:
                    await link.transfer(wire.screen(confirmation(digits), CONFIRM_KEYS, slots=[1,2,6]), open_input=True)
                else:
                    link.open_voice_input()
                    await say(f'{len(digits)} digits entered, ending in {" ".join(digits[-4:])}. Press one to look up, two to retry or zero to return.')
                choice = await link.selection(30)
                if choice == '1':
                    return digits
                if choice != '2':
                    return None
            digits = ''
        except TimeoutError:
            return None
    return None


def fixture():
    return {'displayTitle':'DEMO FEDEX', 'status':'In transit', 'updated':'07 Feb 2026 10:30',
            'estimate':'Expected 09 Feb 2026', 'source':'Fixture only'}


def parse(payload, number):
    for group in payload['output']['completeTrackResults']:
        if group['trackingNumber'] != number:
            continue
        rows = group['trackResults']
        if len(rows)!=1 or rows[0].get('error'):
            return None
        row = rows[0]
        status = row['latestStatusDetail'].get('statusByLocale') or row['latestStatusDetail']['description']
        if not isinstance(status,str) or not status.strip():
            return None
        scans = row.get('scanEvents') or []
        updated = str(scans[0].get('date',''))[:25] if scans else ''
        estimate = next((item['dateTime'] for item in row.get('dateAndTimes',[]) if
                         item.get('type') in ('ESTIMATED_DELIVERY','ACTUAL_DELIVERY')), '')
        return {'displayTitle':'FEDEX TRACKING', 'status':status[:120], 'updated':updated,
                'estimate':('Delivery '+str(estimate)[:25]) if estimate else 'No delivery estimate', 'source':'FedEx'}
    return None


class Parcel:
    def __init__(self, client):
        self.client=client
        self.token=None
        self.expires=0
        self.lock=asyncio.Lock()
        self.requests=0
        self.window=0

    @staticmethod
    def configured():
        return bool(os.getenv('ADSI_FEDEX_CLIENT_ID') and os.getenv('ADSI_FEDEX_CLIENT_SECRET'))

    async def _auth(self, root, client_id, client_secret):
        async with self.lock:
            if self.token and time.monotonic()<self.expires:
                return self.token
            response=await self.client.post(root+'/oauth/token', data={'grant_type':'client_credentials',
                'client_id':client_id,'client_secret':client_secret}, timeout=8)
            response.raise_for_status()
            if len(response.content)>100_000:
                return None
            data=response.json()
            self.token=data['access_token']
            self.expires=time.monotonic()+max(0,min(int(data['expires_in']),3600)-60)
            return self.token

    async def lookup(self, number, enabled):
        if not enabled:
            return fixture()
        client_id=os.getenv('ADSI_FEDEX_CLIENT_ID')
        secret=os.getenv('ADSI_FEDEX_CLIENT_SECRET')
        if not client_id or not secret or not NUMBER.fullmatch(number):
            return None
        root='https://apis-sandbox.fedex.com' if os.getenv('ADSI_FEDEX_SANDBOX')=='1' else 'https://apis.fedex.com'
        minute=int(time.monotonic()//60)
        if self.window!=minute:
            self.window,self.requests=minute,0
        if self.requests>=10:
            return None
        self.requests+=1
        try:
            token=await self._auth(root,client_id,secret)
            if not token:
                return None
            response=await self.client.post(root+'/track/v1/trackingnumbers',
                headers={'Authorization':f'Bearer {token}', 'x-locale':'en_CA'},
                json={'includeDetailedScans':True,'trackingInfo':[{'trackingNumberInfo':{'trackingNumber':number}}]}, timeout=10)
            if response.status_code==401:
                self.token=None
            response.raise_for_status()
            result = parse(response.json(),number) if len(response.content)<=1_000_000 else None
            if result and root == 'https://apis-sandbox.fedex.com':
                result['displayTitle'] = 'FEDEX SANDBOX'
                result['source'] = 'FedEx test data'
            return result
        except (httpx.HTTPError,ValueError,TypeError,KeyError,IndexError,AttributeError):
            return None
