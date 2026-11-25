"""Check a disposable resident download and read it after a process restart."""

import json
import subprocess
from uuid import uuid4

import httpx

from live_api import lab_value
from live_sip_app import terminal


def dial(state_file, *arguments, check=True):
    result = subprocess.run(
        ["docker", "compose", "--profile", "verify", "run", "--rm", "-T", "--no-deps",
         "-e", f"ADSI_FDM_STATE_FILE={state_file}", "terminal-emu", *arguments],
        capture_output=True, text=True, timeout=35, check=False,
    )
    reports = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
    if check:
        assert result.returncode == 0 and len(reports) == 1, (result.returncode, reports)
    return result.returncode, reports


def main():
    port = lab_value("ADSI_WEB_PORT", "8080")
    state_file = f"/var/lib/terminal/test-{uuid4().hex[:12]}.json"
    with httpx.Client(base_url=f"http://127.0.0.1:{port}/api/v1", timeout=8,
                      headers={"X-Coinline-CSRF": "request"}, trust_env=False) as client:
        client.post("/session", json={"password": lab_value("ADSI_ADMIN_PASSWORD")}).raise_for_status()
        prior = client.get("/features").raise_for_status()
        assert not prior.json()["value"].get("approved"), "Run this check on an idle resident test slot."
        try:
            client.put("/features", headers={"If-Match": prior.headers["etag"]},
                       json={"text": "RESIDENT LAB", "version": 2, "approved": True}).raise_for_status()
            _, reports = dial(state_file, "gateway", "fdm")
            report, = reports
            events = report["events"]
            frames = [event["frame"][6:8] for event in events
                      if event.get("valid") and event.get("frame", "").startswith("85")]
            assert report["passed"] and frames == ["83", "80", "81", "82", "84"], report
            assert [event["digit"] for event in events if "digit" in event][3:6] == ["D", "1", "B"]
            _, restarted = dial(state_file, "resident")
            assert restarted == [{"idle_display": "RESIDENT LAB", "version": 2}]
            assert not client.get("/features").raise_for_status().json()["value"].get("approved")
            current = client.get("/features").raise_for_status()
            client.put("/features", headers={"If-Match": current.headers["etag"]},
                       json={"text": "INFOLINE", "version": 3, "launcher": True, "approved": True}).raise_for_status()
            _, reports = dial(state_file, "gateway", "fdm")
            assert reports[0]["passed"]
            _, restarted = dial(state_file, "resident")
            assert restarted == [{"idle_display": "INFOLINE", "version": 3, "launch_extension": "6501"}]
            with terminal(resident_state=state_file) as call:
                call.display("COINLINE INFOLINE")
        finally:
            original = prior.json()["value"]
            current = client.get("/features").raise_for_status()
            client.put("/features", headers={"If-Match": current.headers["etag"]},
                       json={"text": original.get("text", "RESIDENT LAB"),
                             "version": original.get("version", 1), "launcher": original.get("launcher", False),
                             "approved": False}).raise_for_status()
    print("Verified resident download acceptance, wire order, one-use approval and restart persistence over SIP.")


if __name__ == "__main__":
    main()
