"""Observe the complete 16-symbol DTMF alphabet on an isolated synthetic SIP call."""

import queue
import subprocess
import threading
from contextlib import contextmanager

from live_api import lab_value
from live_sip_app import terminal


OBSERVER = """
import asyncio
import base64
import json
import os
from websockets.asyncio.client import connect

async def main():
    base = os.environ["ADSI_ARI_URL"].replace("http", "ws", 1)
    authorization = base64.b64encode(("coinline:" + os.environ["ADSI_ARI_PASSWORD"]).encode()).decode()
    async with connect(base + "/ari/events?app=verification&subscribeAll=true",
                       additional_headers={"Authorization": "Basic " + authorization},
                       proxy=None) as socket:
        print("ready", flush=True)
        async with asyncio.timeout(30):
            async for message in socket:
                event = json.loads(message)
                if event["type"] == "ChannelDtmfReceived" and event["channel"]["name"].startswith("PJSIP/lab-"):
                    print(event["digit"], flush=True)
                if event["type"] == "ChannelDestroyed" and event["channel"]["name"].startswith("PJSIP/lab-"):
                    return

asyncio.run(main())
"""


@contextmanager
def observe():
    process = subprocess.Popen(["docker", "compose", "exec", "-T", "app", "python", "-c", OBSERVER],
                               stdout=subprocess.PIPE, text=True)
    messages = queue.Queue()

    def read():
        for line in process.stdout:
            messages.put(line.strip())
        messages.put(None)

    threading.Thread(target=read, daemon=True).start()
    try:
        assert messages.get(timeout=10) == "ready"
        yield messages
    finally:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=5)


def main():
    with observe() as messages, terminal("6502") as call:
        call.display("DEMO BALANCE", lines=["DEMO BALANCE", "Enter lab code", "", ""])
        expected = "AD1D1"
        for digit in expected:
            assert messages.get(timeout=4) == digit
        keypad = "0123456789"
        if lab_value("ADSI_DEMO_PIN", "").startswith("0"):
            keypad = "1234567890"
        for digit in keypad + "ABCD*#":
            call.press(digit)
            assert messages.get(timeout=4) == digit
        try:
            unexpected = messages.get(timeout=0.35)
        except queue.Empty:
            pass
        else:
            raise AssertionError(f"Unexpected extra keypad event: {unexpected}")
        call.press("hangup")
        assert call.process.wait(timeout=10) == 0
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "gateway", "asterisk", "-C", "/run/asterisk/asterisk.conf",
         "-rx", "core show channels count"],
        capture_output=True, text=True, timeout=10, check=True,
    )
    assert "0 active channels" in result.stdout, result.stdout
    print("Verified all 16 uplink DTMF symbols exactly once over SIP and no channels remained after hangup.")


if __name__ == "__main__":
    main()
