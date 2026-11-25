"""Exercise keypad narrowing and the fixture boards through SIP/RTP."""

import time

import httpx

from live_api import lab_value
from live_sip_app import provider_override, terminal


def press(call, digit, expected):
    # The terminal reports its decoded frame before the D1 acknowledgment has completed.
    time.sleep(0.8)
    call.press(digit)
    call.display(expected)


def main():
    from coinline_adsi import flights, keypad
    with httpx.Client(base_url=f'http://127.0.0.1:{lab_value("ADSI_WEB_PORT", "8080")}/api/v1',
                      headers={'X-Coinline-CSRF': 'request'}, timeout=8, trust_env=False) as client:
        client.post('/session', json={'password': lab_value('ADSI_ADMIN_PASSWORD')}).raise_for_status()
        with provider_override(client, flights=False, directory=[{'name': 'Demo library', 'number': '7002', 'detail': 'Example only'}]):
            with terminal() as call:
                call.display('COINLINE INFOLINE')
                press(call, '5', 'MORE SERVICES')
                press(call, '1', 'AIRPORT BOARDS')
                press(call, '1', 'Airport ?')
                query = ''
                for digit in '2998':
                    query += digit
                    press(call, digit, f'Airport {query}')
                press(call, '1', 'Airport 1-2' if len(keypad.matches(flights.ENTRIES, query)) > 1 else 'Airport 1-1')
                candidates = keypad.matches(flights.ENTRIES, query)
                index = [item[0] for item in candidates].index('YYT')
                for start in range(2, index + 1, 2):
                    press(call, '3', f'Airport {start + 1}-{min(start + 2, len(candidates))}')
                press(call, str(index % 2 + 1), 'DEMO YYT')
                press(call, '0', 'AIRPORT BOARDS')
                press(call, '0', 'MORE SERVICES')
                press(call, '2', 'Directory ?')
                press(call, '5', 'Directory 5')
                press(call, '1', 'Directory 1-1')
                press(call, '1', 'DIRECTORY')
    print('Verified incremental ICAO search, arrival board and directory over SIP.')


if __name__ == '__main__':
    main()
