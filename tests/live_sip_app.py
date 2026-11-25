"""Verify that a caller retains its published revision through a route change."""

import copy
import json
import queue
import subprocess
import threading
import time
from contextlib import contextmanager
from uuid import uuid4

import httpx

from live_api import DATA, lab_value


class TerminalCall:
    def __init__(self, extension, synthetic_caller=None, resident_state=None):
        self.messages = queue.Queue()
        self.trace = []
        self.name = "coinline-adsi-test-" + uuid4().hex[:12]
        self.process = subprocess.Popen(
            ["docker", "compose", "--profile", "verify", "run", "--name", self.name, "--rm", "-T",
             "--no-deps", *(["-e", f"ADSI_EMULATOR_CALLER_ID={synthetic_caller}"] if synthetic_caller else []),
             *(["-e", f"ADSI_FDM_STATE_FILE={resident_state}"] if resident_state else []),
             "terminal-emu", "gateway", *(["launch"] if resident_state else ["interactive", extension])],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        )
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.process.stdout:
            if line.lstrip().startswith("{"):
                message = json.loads(line)
                self.trace.append(message)
                self.messages.put(message)
        self.messages.put({})

    def display(self, expected, timeout=12, *, lines=None):
        until = time.monotonic() + timeout
        while True:
            try:
                message = self.messages.get(timeout=max(0, until - time.monotonic()))
            except queue.Empty as error:
                raise AssertionError(f"Missing screen {expected}. Terminal trace: {self.trace}") from error
            if not message:
                raise AssertionError("Call ended before expected screen.")
            if message.get("valid") and message["line"] == expected and (lines is None or message["lines"] == lines):
                return

    def press(self, value):
        self.process.stdin.write(value + "\n")
        self.process.stdin.flush()


@contextmanager
def terminal(extension="6501", synthetic_caller=None, resident_state=None):
    call = TerminalCall(extension, synthetic_caller, resident_state)
    try:
        yield call
    finally:
        if call.process.poll() is None:
            try:
                call.press("hangup")
                call.process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                subprocess.run(["docker", "stop", "--time", "1", call.name],
                               timeout=8, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@contextmanager
def provider_override(client, **updates):
    original = client.get("/providers").raise_for_status()
    value = original.json()["value"]
    settings = {**value, **updates}
    current = client.put("/providers", json=settings, headers={"If-Match": original.headers["etag"]}).raise_for_status()
    try:
        yield
    finally:
        client.put("/providers", json=value, headers={"If-Match": current.headers["etag"]}).raise_for_status()


def verify_revision(client):
    with provider_override(client, regional=False, sites={}, prefixes={}):
        active = client.get("/routes").raise_for_status().json()[0]["revision_id"]
        original = next(item["id"] for item in client.get("/apps").raise_for_status().json()
                        if any(revision["id"] == active for revision in
                               client.get(f"/apps/{item['id']}/revisions").raise_for_status().json()))
        replacement = copy.deepcopy(DATA)
        replacement["nodes"][0]["lines"][0] = "REVISION B"
        with terminal() as first:
            first.display("COINLINE INFOLINE")
            response = client.post("/apps", json={"name": "SIP verification", "graph": replacement}).raise_for_status()
            other = f"/apps/{response.json()['id']}"
            try:
                client.post(other + "/revisions", headers={"If-Match": response.headers["etag"]},
                            json={"routes": ["infoline"]}).raise_for_status()
                with terminal() as later:
                    later.display("REVISION B")
                    time.sleep(0.8)
                    first.press("2")
                    first.display("WEATHER")
                    time.sleep(0.8)
                    first.press("1")
                    first.display("DEMO WEATHER")
                    time.sleep(0.8)
                    later.press("0")
                    first.press("0")
                    first.display("WEATHER")
                    time.sleep(0.8)
                    first.press("0")
                    first.display("COINLINE INFOLINE")
                    time.sleep(0.8)
                    first.press("0")
                    assert later.process.wait(timeout=10) == 0
                    assert first.process.wait(timeout=10) == 0
            finally:
                client.post(f"/apps/{original}/activate",
                            json={"revision": active, "routes": ["infoline"]}).raise_for_status()
                client.post(other + "/archive", json={"disable_routes": False}).raise_for_status()


def main():
    root = f"http://127.0.0.1:{lab_value('ADSI_WEB_PORT', '8080')}/api/v1"
    with httpx.Client(base_url=root, timeout=8, headers={"X-Coinline-CSRF": "request"}, trust_env=False) as client:
        client.post("/session", json={"password": lab_value("ADSI_ADMIN_PASSWORD")}).raise_for_status()
        verify_revision(client)
        # Select from a local synthetic prefix mapping. This tests SIP caller ID even with live feeds disabled.
        with provider_override(client, regional=False,
                               sites={"test-site": {"place": "Test", "province": "NL", "code": "s0000001", "zone": "America/St_Johns"}},
                               prefixes={"289555": "test-site"}):
            with terminal(synthetic_caller="2895550100") as call:
                call.display("COINLINE INFOLINE")
                time.sleep(0.8)
                call.press("2")
                call.display("WEATHER")
                time.sleep(0.8)
                call.press("1")
                call.display("Weather for Test?")
    print("Verified revision pinning across two real SIP calls.")
    print("Verified authenticated synthetic caller ID and prefix-based location suggestion.")


if __name__ == "__main__":
    main()
