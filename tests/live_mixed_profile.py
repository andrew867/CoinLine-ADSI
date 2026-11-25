"""Exercise voice-between-screens against an explicitly selected isolated SIP namespace."""

import argparse
import queue
import subprocess
import threading
from uuid import uuid4

from live_emu_ingress import expect_event, press, read_messages


def run(network, image, profile):
    name = 'coinline-voice-probe-' + uuid4().hex[:10]
    command = ['docker', 'run', '--rm', '-i', '--name', name, '--network', network,
               '-e', 'ADSI_EMULATOR_PEER_ONLY=1', '-e',
               'ADSI_TERMINAL_VOICE_INPUT_ONLY=' + ('1' if profile == 'voice-between-screens' else '0'),
               image, '127.0.0.1:5069', 'interactive', '2374']
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, text=True)
    messages = queue.Queue()
    threading.Thread(target=read_messages, args=(process, messages), daemon=True).start()
    mode = 'voice' if profile == 'voice-between-screens' else 'data'

    def screen(line):
        expect_event(messages, lambda e: e.get('valid') and e.get('line') == line and
                     e.get('mode') == mode and e.get('session') is True, f'{line} in {mode} mode')

    try:
        screen('COINLINE INFOLINE')
        press(process, '1')
        screen('NEWS')
        press(process, '0')
        screen('COINLINE INFOLINE')
        # The welcome has Exit in position six; test the return-string path too.
        press(process, 'k6')
        expect_event(messages, lambda e: e.get('valid') and e.get('mode') == 'voice' and
                     e.get('session') is False, 'final session release')
        assert process.wait(timeout=30) == 0
        reports = []
        while True:
            event = messages.get(timeout=5)
            if event is None:
                break
            if 'sip_status' in event:
                reports.append(event)
        report, = reports
        assert report['sip_status'] == 200 and report['passed'], report
        events = report['events']
        assert not any(e.get('valid') is False for e in events), report
        expected_alerts = 4 if mode == 'voice' else 1
        assert sum(e.get('signal') == 'CAS' for e in events) == expected_alerts, report
        assert sum(e.get('digit') == 'A' for e in events) == expected_alerts, report
        assert sum(e.get('digit') == 'D' for e in events) == 5, report
        print(f'PASS: {profile}, {expected_alerts} genuine peer capability exchanges, keypad/softkey navigation and release')
    finally:
        if process.poll() is None:
            try:
                press(process, 'hangup')
                process.wait(timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                subprocess.run(['docker', 'stop', '--timeout', '1', name], timeout=15, check=False,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--network', required=True, help='Isolated gateway container network namespace')
    parser.add_argument('--image', required=True, help='Standalone terminal candidate image')
    parser.add_argument('--profile', choices=('continuous-data', 'voice-between-screens'), required=True)
    args = parser.parse_args()
    run(args.network, args.image, args.profile)
