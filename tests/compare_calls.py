"""Check local synthetic call traces against the independent wire fixtures."""

import json
import sys
from pathlib import Path


def read_report(directory, scenario):
    path = directory / f"{scenario}.jsonl"
    reports = [json.loads(line) for line in path.read_text().splitlines() if line.startswith("{")]
    assert len(reports) == 1
    result, = reports
    assert result["scenario"] == scenario and result["ended"] and result["passed"]
    return result["events"]


def verify_exchange(events, expected_frames, expected_digits):
    assert events[0]["signal"] == "CAS"
    assert "".join(event["digit"] for event in events if "digit" in event) == expected_digits
    assert [event["frame"] for event in events if event.get("valid")] == expected_frames
    assert not any(event.get("valid") is False for event in events)
    assert events[-1]["signal"] == "voice"


def main():
    evidence = Path(sys.argv[1])
    fixtures = json.loads(Path("fixtures/wire/vectors.json").read_text())
    frames = {row["id"]: bytes.fromhex(row["hex"]).hex() for row in fixtures["valid"]}
    reference_frames = [frames[name] for name in ("sdc-connect", "sdc-lab", "sdc-release")]
    if sys.argv[2:] == ["--impairments"]:
        reports = [json.loads(line) for line in (evidence / "jitter.jsonl").read_text().splitlines()
                   if line.startswith("{")]
        jitter, = reports
        assert jitter["passed"] and jitter["ended"]
        verify_exchange(jitter["events"], reference_frames, "AD1D1D1")
        reports = [json.loads(line) for line in (evidence / "drop.jsonl").read_text().splitlines()
                   if line.startswith("{")]
        loss, = reports
        assert loss["ended"] and loss["sip_status"] == 200 and loss["events"][0]["signal"] == "CAS"
        accepted = [event["frame"] for event in loss["events"] if event.get("valid")]
        assert all(frame in reference_frames for frame in accepted)
        if loss["passed"]:
            assert accepted == reference_frames and loss["events"][-1]["signal"] == "voice"
        filters = json.loads((evidence / "queue.json").read_text())
        drops = sum(action["stats"]["drops"] for row in filters
                    for action in row.get("options", {}).get("actions", []))
        assert drops > 0
        print(f"Native RTP jitter passed. Recorded {drops} deterministic drops with "
              f"{'validated recovery' if loss['passed'] else 'bounded hangup'}.")
        return
    native = read_report(evidence, "reference")
    local = read_report(evidence, "lab")
    fallback = read_report(evidence, "fallback")
    verify_exchange(native, reference_frames, "AD1D1D1")
    verify_exchange(local, [frames[name] for name in ("sdc-connect", "sdc-lab-with-key", "sdc-ok", "sdc-release")],
                    "AD1D11D1D1")
    assert [event.get("signal") for event in fallback if "signal" in event] == ["CAS", "voice", "voice-response"]
    assert [event["digit"] for event in fallback if "digit" in event] == ["1"]
    print("Verified CoinLine and native Asterisk SIP/RTP exchanges against the wire fixtures, including voice recovery.")


if __name__ == "__main__":
    main()
