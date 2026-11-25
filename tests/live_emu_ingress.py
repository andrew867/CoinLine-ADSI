"""Test the loopback guest route with the standalone PJSUA2 terminal."""

import json
import os
import queue
import subprocess
import threading
import time
from uuid import uuid4


IMAGE = os.getenv('ADSI_EMU_TERMINAL_IMAGE', 'coinline-adsi-emu-terminal')
NETWORK = os.getenv('ADSI_EMU_TEST_NETWORK', 'host')


def command(name, digits):
    return ['docker', 'run', '--rm', '-i', '--name', name, '--network', NETWORK,
            '-e', 'ADSI_EMULATOR_PEER_ONLY=1', IMAGE, '127.0.0.1:5069', 'interactive', digits]


def read_messages(process, messages):
    for line in process.stdout:
        if line.startswith('{'):
            messages.put(json.loads(line))
    messages.put(None)


def expect(messages, line):
    deadline = time.monotonic() + 45
    while True:
        event = messages.get(timeout=max(0, deadline - time.monotonic()))
        assert event is not None, f'Call ended before {line}'
        if event.get('valid') and event.get('line') == line:
            return


def press(process, digit):
    time.sleep(0.8)  # Terminal reports frame decode before finishing D1.
    process.stdin.write(digit + '\n')
    process.stdin.flush()


def main():
    name = 'coinline-emu-probe-' + uuid4().hex[:10]
    process = subprocess.Popen(command(name, '2374'), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, text=True)
    messages = queue.Queue()
    threading.Thread(target=read_messages, args=(process, messages), daemon=True).start()
    try:
        expect(messages, 'COINLINE INFOLINE')
        press(process, '1')
        expect(messages, 'NEWS')
        press(process, '0')
        expect(messages, 'COINLINE INFOLINE')
        press(process, '0')
        assert process.wait(timeout=30) == 0
        reports = []
        while True:
            event = messages.get(timeout=5)
            if event is None:
                break
            if 'sip_status' in event:
                reports.append(event)
        report, = reports
        assert report['sip_status'] == 200 and report['passed']
        events = report['events']
        assert any(event.get('signal') == 'CAS' for event in events)
        assert any(event.get('digit') == 'A' for event in events)
        assert any(event.get('digit') == 'D' for event in events)
        assert any(event.get('valid') and event.get('mode') == 'voice' for event in events)
    finally:
        if process.poll() is None:
            try:
                press(process, 'hangup')
                process.wait(timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                subprocess.run(['docker', 'stop', '--time', '1', name], timeout=15, check=False,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    for digits in ('6500', '6501', '6503', '6504', '6505'):
        result = subprocess.run(command('coinline-emu-denied-' + uuid4().hex[:10], digits),
                                input='', capture_output=True, text=True, timeout=35)
        reports = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
        assert result.returncode != 0 and reports, (digits, result.returncode)
        assert reports[-1]['sip_status'] in (403, 404, 484), (digits, reports[-1]['sip_status'])
        assert not any(event.get('signal') == 'CAS' for event in reports[-1]['events'])
    print('Verified unauthenticated 2374 ADSI call, navigation, voice release and rejection of protected extensions.')


if __name__ == '__main__':
    main()
