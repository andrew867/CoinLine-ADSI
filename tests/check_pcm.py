"""Exercise the standalone modem with deterministic direct-PCM inputs."""

import json
import random
import struct
import subprocess

from coinline_adsi import audio, wire


def decode(pcm):
    process = subprocess.run(
        ["docker", "compose", "--profile", "verify", "run", "--rm", "-T", "--no-deps", "terminal-emu", "pcm"],
        input=pcm, capture_output=True, timeout=30,
    )
    reports = [json.loads(line) for line in process.stdout.splitlines() if line.startswith(b"{")]
    assert len(reports) == 1, process.stderr.decode(errors="replace")
    return reports[0]


def main():
    gap = bytes(audio.RATE)
    start = gap + audio.cas() + gap + audio.bell202(wire.CONNECT) + gap
    display = audio.bell202(wire.LAB)
    end = gap + audio.bell202(wire.RELEASE) + gap
    waveform = start + display + end
    seed = random.Random(202)
    noisy = [max(-4000, min(4000, value + seed.randint(-180, 180)))
             for (value,) in struct.iter_unpack("<h", waveform)]
    report = decode(struct.pack(f"<{len(noisy)}h", *noisy))
    frames = [event["frame"] for event in report["events"] if event.get("valid")]
    assert report["passed"] and frames == [wire.CONNECT.hex(), wire.LAB.hex(), wire.RELEASE.hex()], report

    wrong = wire.LAB[:-1] + bytes([wire.LAB[-1] ^ 1])
    report = decode(start + audio.bell202(wrong) + end)
    assert not report["passed"] and any(event.get("frame") == wrong.hex() and not event["valid"]
                                        for event in report["events"]), report
    for offset in (1600, 1760):
        # Model a missing 20 ms media frame inside the data portion.
        report = decode(start + display[:offset * 2] + bytes(320) + display[offset * 2 + 320:] + end)
        assert not report["passed"]
        assert not any(event.get("valid") and event.get("line") == "LAB" for event in report["events"]), report
    print("Verified independent PCM decode with seeded noise and clipping, checksum rejection and missing-frame rejection.")


if __name__ == "__main__":
    main()
