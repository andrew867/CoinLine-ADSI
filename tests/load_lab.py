"""Exercise the local clean SIP profile and report measured dispatch latency."""

import argparse
import json
import subprocess

import httpx

from live_api import lab_value


def call_batch(samples, parallel):
    # Each client process negotiates its own SIP and RTP sockets.
    command = (
        f"seq {samples} | xargs -P {parallel} -n 1 sh -c 'terminal-emu gateway lab' sh"
    )
    result = subprocess.run(
        ["docker", "compose", "--profile", "verify", "run", "--rm", "-T", "--no-deps",
         "--entrypoint", "sh", "terminal-emu", "-c", command],
        capture_output=True, text=True, timeout=max(60, samples * 10 // parallel),
    )
    results = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
    passed = sum(row.get("passed") is True for row in results)
    for failure in [row for row in results if row.get("passed") is not True][:3]:
        print(json.dumps({"failed_terminal": failure}))
    if len(results) != samples:
        print(json.dumps({"terminal_reports": len(results), "expected": samples}))
    return passed, result.returncode


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
