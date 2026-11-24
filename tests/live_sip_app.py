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
    def __init__(self, extension):
        self.messages = queue.Queue()
        self.trace = []
        self.name = "coinline-adsi-test-" + uuid4().hex[:12]
        self.process = subprocess.Popen(
            ["docker", "compose", "--profile", "verify", "run", "--name", self.name, "--rm", "-T",
             "--no-deps", "terminal-emu", "gateway", "interactive", extension],
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
def terminal(extension="6501"):
    call = TerminalCall(extension)
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


def main():
    root = f"http://127.0.0.1:{lab_value('ADSI_WEB_PORT', '8080')}/api/v1"
    with httpx.Client(base_url=root, timeout=8, headers={"X-Coinline-CSRF": "request"}, trust_env=False) as client:
        client.post("/session", json={"password": lab_value("ADSI_ADMIN_PASSWORD")}).raise_for_status()
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
                    first.press("2")
                    first.display("DEMO WEATHER")
                    later.press("0")
                    first.press("0")
                    first.display("COINLINE INFOLINE")
                    first.press("0")
                    assert later.process.wait(timeout=10) == 0
                    assert first.process.wait(timeout=10) == 0
            finally:
                client.post(f"/apps/{original}/activate",
                            json={"revision": active, "routes": ["infoline"]}).raise_for_status()
                client.post(other + "/archive", json={"disable_routes": False}).raise_for_status()
    print("Verified revision pinning across two real SIP calls.")


if __name__ == "__main__":
    main()
