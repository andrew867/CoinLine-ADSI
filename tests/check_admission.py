"""Verify the lab admits only configured destinations and valid SIP credentials."""

import json
import subprocess


def check(extra, extension, expected):
    command = ["docker", "compose", "--profile", "verify", "run", "--rm", "-T", "--no-deps",
               *extra, "terminal-emu", "gateway", "interactive", extension]
    reply = subprocess.run(command, input="", capture_output=True, text=True, timeout=30)
    reports = [json.loads(line) for line in reply.stdout.splitlines() if line.startswith("{")]
    assert len(reports) == 1, reply.stderr
    result, = reports
    assert reply.returncode == 1 and result["sip_status"] in expected and not result["events"], result


if __name__ == "__main__":
    check([], "6599", {404})
    check(["-e", "ADSI_SIP_PASSWORD=synthetic-incorrect"], "6500", {401, 403})
    print("Verified SIP rejection of an unassigned destination and invalid credentials.")
