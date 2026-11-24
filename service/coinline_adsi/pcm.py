"""Generate a synthetic off-hook exchange as a PCM test stimulus."""

import argparse
import sys

from . import audio, fdm, wire


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--invalid", action="store_true", help="Corrupt the display checksum.")
    parser.add_argument("--resident", help="Send a synthetic resident feature with this idle display.")
    parser.add_argument("--abort", action="store_true", help="Stop the download before its script and commit.")
    options = parser.parse_args()
    display = wire.LAB[:-1] + bytes((wire.LAB[-1] ^ 1,)) if options.invalid else wire.LAB
    gap = bytes(audio.RATE)
    frames = (display,)
    if options.resident:
        frames = fdm.artifact(options.resident, 1)
        if options.abort:
            frames = frames[:3]
    sys.stdout.buffer.write(gap + audio.cas() + gap +
                            gap.join(audio.bell202(frame) for frame in (wire.CONNECT, *frames, wire.RELEASE)) + gap)


if __name__ == "__main__":
    main()
