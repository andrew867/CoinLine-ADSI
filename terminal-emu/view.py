"""Local web view for the standalone SIP terminal process."""

import argparse
import json
import os
import re
import subprocess
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UI = Path(__file__).with_name("view.html")


class Dialer:
    def __init__(self, binary, host):
        self.binary, self.host = binary, host
        self.lock = threading.Lock()
        self.call = None
        self.reset()

    def reset(self):
        self.state = {"lines": ["ON HOOK"], "keys": [""] * 6, "status": "Idle", "trace": [], "private": False}

    def dial(self, ext, caller=""):
        with self.lock:
            if self.call and self.call.poll() is None:
                return False
            self.reset()
            self.state["private"] = ext == "6504"
            environment = dict(os.environ)
            environment.pop("ADSI_EMULATOR_CALLER_ID", None)
            if caller:
                environment["ADSI_EMULATOR_CALLER_ID"] = caller
            command = [self.binary, self.host, "interactive", ext] if self.binary else [
                "docker", "compose", "--profile", "verify", "run", "--rm", "-T", "--no-deps",
                *(["-e", "ADSI_EMULATOR_CALLER_ID"] if caller else []),
                "terminal-emu", self.host, "interactive", ext,
            ]
            self.call = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL, text=True, encoding="utf-8", env=environment)
            self.state["status"] = "Dialing"
            threading.Thread(target=self._read, args=(self.call,), daemon=True).start()
            return True

    def _read(self, process):
        for line in process.stdout:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            with self.lock:
                if self.call is not process:
                    return
                if event.get("lines"):
                    self.state["lines"] = event["lines"]
                    self.state["keys"] = event["softkeys"]
                    self.state["status"] = event["mode"].capitalize()
                if "sample" in event and not self.state["private"]:
                    self.state["trace"] = [*self.state["trace"][-31:], event]
        process.wait()
        with self.lock:
            if self.call is process:
                self.state["status"] = "Call ended" if process.returncode == 0 else "Call failed"
                self.state["keys"] = [""] * 6
                if self.state["private"]:
                    self.state["lines"] = ["ON HOOK"]
                    self.state["trace"] = []

    def press(self, action):
        with self.lock:
            if not self.call or self.call.poll() is not None:
                return False
            try:
                self.call.stdin.write(action + "\n")
                self.call.stdin.flush()
            except OSError:
                return False
            return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8091)
    parser.add_argument("--host", default="gateway")
    parser.add_argument("--binary", help="Path to a locally installed terminal-emu")
    args = parser.parse_args()
    dialer = Dialer(args.binary, args.host)

    class Handler(BaseHTTPRequestHandler):
        def _send(self, payload, content_type="application/json", status=200):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _local(self):
            return self.headers.get("Host") in (f"127.0.0.1:{args.port}", f"localhost:{args.port}")

        def do_GET(self):
            if not self._local():
                self.send_error(HTTPStatus.FORBIDDEN)
            elif self.path == "/":
                self._send(UI.read_bytes(), "text/html; charset=utf-8")
            elif self.path == "/state":
                with dialer.lock:
                    payload = json.dumps(dialer.state).encode()
                self._send(payload)
            else:
                self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self):
            if not self._local() or self.headers.get("X-Coinline-Terminal") != "local":
                self.send_error(HTTPStatus.FORBIDDEN)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 1 <= length <= 64:
                    raise ValueError
                request = json.loads(self.rfile.read(length))
                value = request.get("value", "")
                if self.path == "/dial" and re.fullmatch(r"[0-9]{1,10}", value):
                    caller = request.get("caller", "")
                    if caller and (value not in ("6501", "6504") or not re.fullmatch(r"[2-9]\d{2}[2-9]\d{6}", caller)):
                        raise ValueError
                    result = dialer.dial(value, caller)
                elif self.path == "/press" and re.fullmatch(r"[0-9*#]|k[1-6]|hangup", value):
                    result = dialer.press(value)
                else:
                    raise ValueError
            except (ValueError, TypeError, AttributeError, OSError):
                self.send_error(HTTPStatus.BAD_REQUEST)
                return
            self._send(json.dumps({"accepted": result}).encode(), status=200 if result else 409)

        def log_message(self, *args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print(f"Terminal console at http://127.0.0.1:{args.port}", flush=True)
        try:
            server.serve_forever()
        finally:
            dialer.press("hangup")


if __name__ == "__main__":
    main()
