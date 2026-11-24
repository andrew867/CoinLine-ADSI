"""Generate a synthetic off-hook exchange as a PCM test stimulus."""

import argparse
import sys

from . import audio, wire


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--invalid", action="store_true", help="Corrupt the display checksum.")
    options = parser.parse_args()
    display = wire.LAB[:-1] + bytes((wire.LAB[-1] ^ 1,)) if options.invalid else wire.LAB
    gap = bytes(audio.RATE)
    sys.stdout.buffer.write(gap + audio.cas() + gap + audio.bell202(wire.CONNECT) + gap +
                            audio.bell202(display) + gap + audio.bell202(wire.RELEASE) + gap)


if __name__ == "__main__":
    main()
