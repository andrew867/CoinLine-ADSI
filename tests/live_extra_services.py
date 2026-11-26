"""Exercise keypad narrowing and the fixture boards through SIP/RTP."""

import time

import httpx

from live_api import lab_value
from live_sip_app import provider_override, terminal


def press(call, digit, expected):
    # The terminal reports its decoded frame before the D1 acknowledgment has completed.
    time.sleep(0.8)
    call.press(digit)
    call.display(expected, timeout=30)


def main():
    from coinline_adsi import flights, keypad
    with httpx.Client(base_url=f'http://127.0.0.1:{lab_value("ADSI_WEB_PORT", "8080")}/api/v1',
                      headers={'X-Coinline-CSRF': 'request'}, timeout=8, trust_env=False) as client:
        client.post('/session', json={'password': lab_value('ADSI_ADMIN_PASSWORD')}).raise_for_status()
        with provider_override(client, flights=False, directory=[{'name': 'Demo library', 'number': '7002', 'detail': 'Example only'}]):
            with terminal() as call:
                call.display('COINLINE INFOLINE', timeout=60)
                press(call, '5', 'MORE SERVICES')
                press(call, '1', 'AIRPORT BOARDS')
                press(call, '1', keypad.heading('Airport', '', len(flights.ENTRIES)))
                query = ''
                for digit in '2998':
                    query += digit
                    press(call, digit, keypad.heading('Airport', query, len(keypad.matches(flights.ENTRIES, query))))
                press(call, '1', 'Airport 1-2' if len(keypad.matches(flights.ENTRIES, query)) > 1 else 'Airport 1-1')
                candidates = keypad.matches(flights.ENTRIES, query)
                index = [item[0] for item in candidates].index('YYT')
                for start in range(2, index + 1, 2):
                    press(call, '3', f'Airport {start + 1}-{min(start + 2, len(candidates))}')
                press(call, str(index % 2 + 1), 'DEMO YYT')
                press(call, '0', 'AIRPORT BOARDS')
                press(call, '0', 'MORE SERVICES')
                press(call, '2', keypad.heading('Directory', '', 1))
                press(call, '5', keypad.heading('Directory', '5', 1))
                press(call, '1', 'Directory 1-1')
                press(call, '1', 'DIRECTORY')
        with provider_override(client, cinema=False, parcel=False):
            with terminal() as call:
                call.display('COINLINE INFOLINE', timeout=60, lines=['COINLINE INFOLINE', 'Your information', 'service. Choose a', 'service to begin.'])
                press(call, '5', 'MORE SERVICES')
                press(call, '4', 'Demo theatre')
                press(call, '1', 'Demo movie')
                press(call, '1', 'DEMO MOVIES')
                press(call, 'k5', 'DEMO MOVIES')  # fixed Next
                press(call, 'k4', 'DEMO MOVIES')  # fixed Prev
                press(call, 'k6', 'MORE SERVICES')
                press(call, '5', 'TRACK A PARCEL')
                time.sleep(0.8)
                for digit in '000000000001':
                    call.press(digit)
                call.press('k4')  # erase one digit via the actual softkey return
                call.press('2')
                call.press('k5')  # submit via the actual softkey return
                call.display('CONFIRM TRACKING', timeout=30)
                press(call, 'k1', 'DEMO FEDEX')
                press(call, 'k6', 'MORE SERVICES')
    print('Verified incremental ICAO search, arrival board, directory, movie paging and parcel entry over SIP.')


if __name__ == '__main__':
    main()
