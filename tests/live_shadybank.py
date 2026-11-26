"""Exercise the synthetic ShadyBank ledger through a real standalone SIP terminal."""

import time

from live_extra_services import press
from live_sip_app import terminal


CARD='9000000000000001'
RECIPIENT='9000000000000002'
PIN='123456'


def enter(call,value,expected):
    time.sleep(.8)
    for digit in value:
        call.press(digit)
    press(call,'k5',expected)


def main():
    with terminal('6508') as call:
        call.display('DEMO SHADYBANK',timeout=60)
        enter(call,CARD,'MEMBER PIN')
        enter(call,PIN,'DEMO SHADYBANK')
        press(call,'k1','BALANCE')
        press(call,'k6','DEMO SHADYBANK')
        # First cancel an otherwise valid transfer, then confirm another one.
        for confirm in (False,True):
            press(call,'k4','TRANSFER')
            enter(call,RECIPIENT,'TRANSFER AMOUNT')
            enter(call,'1250','CONFIRM TRANSFER')
            if confirm:
                press(call,'k1','TRANSFER POSTED')
                press(call,'k6','DEMO SHADYBANK')
            else:
                press(call,'k6','DEMO SHADYBANK')
        time.sleep(.8)
        call.press('k1')
        call.display('BALANCE',lines=['BALANCE','SB 110.95','Available','SB 110.95'])
        press(call,'k6','DEMO SHADYBANK')
        press(call,'k2','ACTIVITY 1/1')
        press(call,'k6','DEMO SHADYBANK')
        press(call,'k3','PENDING HOLDS')
        press(call,'k6','DEMO SHADYBANK')
        press(call,'k6','GOODBYE')
        assert call.process.wait(timeout=20)==0
        frames=str(call.trace)
        assert CARD not in frames and RECIPIENT not in frames and PIN not in frames
    with terminal('6508') as call:
        call.display('DEMO SHADYBANK',timeout=60)
        enter(call,RECIPIENT,'MEMBER PIN')
        enter(call,PIN,'DEMO SHADYBANK')
        time.sleep(.8)
        call.press('k1')
        call.display('BALANCE',lines=['BALANCE','SB 54.50','Available','SB 54.50'])
        press(call,'k6','DEMO SHADYBANK')
        press(call,'k2','ACTIVITY 1/1')
        press(call,'k6','DEMO SHADYBANK')
        press(call,'k6','GOODBYE')
        assert call.process.wait(timeout=20)==0
    print('Verified ShadyBank member login, cancelled and posted transfers, both balances, history, holds and release over SIP.')


if __name__=='__main__':
    main()
