"""Exercise the local clean SIP profile and report measured dispatch latency."""

import argparse
import json
import subprocess
from uuid import uuid4

import httpx

from live_api import lab_value


def call_batch(samples, parallel):
    workers = min(samples, parallel)
    count, extra = divmod(samples, workers)
    batches = [str(count + (index < extra)) for index in range(workers)]
    # Every worker retains its own SIP stack and negotiates RTP for each new call.
    command = (f'printf "%s\\n" {" ".join(batches)} | xargs -P {workers} -n 1 '
               """sh -c 'ADSI_EMULATOR_CALLS="$1" exec terminal-emu gateway lab' sh""")
    container = "coinline-adsi-load-" + uuid4().hex[:10]
    try:
        result = subprocess.run(
            ["docker", "compose", "--profile", "verify", "run", "--name", container, "--rm", "-T", "--no-deps",
             "--entrypoint", "sh", "terminal-emu", "-c", command],
            capture_output=True, text=True, timeout=60 + 20 * max(map(int, batches)),
        )
        output, status = result.stdout, result.returncode
    except subprocess.TimeoutExpired as error:
        subprocess.run(["docker", "stop", "--time", "1", container], timeout=15,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        output, status = (error.stdout or b"").decode(errors="replace"), 1
    results = [json.loads(line) for line in output.splitlines() if line.startswith("{")]
    passed = sum(row.get("passed") is True for row in results)
    for failure in [row for row in results if row.get("passed") is not True][:3]:
        print(json.dumps({"failed_terminal": failure}))
    if len(results) != samples:
        print(json.dumps({"terminal_reports": len(results), "expected": samples}))
    return passed, status


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--calls", type=int, default=100, choices=range(1, 101), metavar="1..100")
    parser.add_argument("--parallel", type=int, default=10, choices=range(1, 11), metavar="1..10")
    args = parser.parse_args()
    root = f"http://127.0.0.1:{lab_value('ADSI_WEB_PORT', '8080')}/api/v1"
    with httpx.Client(base_url=root, headers={"X-Coinline-CSRF": "request"}, trust_env=False) as client:
        client.post("/session", json={"password": lab_value("ADSI_ADMIN_PASSWORD")}).raise_for_status()
        before = client.get("/telephony/status").raise_for_status().json()
        passed, status = call_batch(args.calls, args.parallel)
        after = client.get("/telephony/status").raise_for_status().json()
        outcomes = {key: value - before["outcomes"].get(key, 0) for key, value in after["outcomes"].items()
                    if value != before["outcomes"].get(key, 0)}
        report = {
            "requested": args.calls,
            "passed": passed,
            "parallel": args.parallel,
            "outcomes": outcomes,
            "active": after["active"],
            "dispatch_samples_in_window": after["response_samples"],
            "p95_dispatch_seconds": after["p95_dispatch_seconds"],
        }
        print(json.dumps(report))
        return (status != 0 or passed != args.calls or after["active"] != 0 or
                after["p95_dispatch_seconds"] is None or after["p95_dispatch_seconds"] > 2)


if __name__ == "__main__":
    raise SystemExit(main())
