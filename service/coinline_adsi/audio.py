"""Signed 16-bit little-endian audio for the 8 kHz media adapter."""

import asyncio
import io
import math
import struct
import wave
from collections.abc import Iterable
from functools import lru_cache


RATE = 8000


def _pcm(samples: Iterable[int]) -> bytes:
    values = tuple(samples)
    return struct.pack(f"<{len(values)}h", *values)


@lru_cache(maxsize=1)
def cas() -> bytes:
    return _pcm(
        round(2600 * (math.sin(math.tau * 2130 * sample / RATE) + math.sin(math.tau * 2750 * sample / RATE)))
        for sample in range(680)
    )


@lru_cache(maxsize=64)
def bell202(data: bytes) -> bytes:
    # Each first-frame spill starts with 180 mark bits (150 ms).
    bits = [1] * 180
    for byte in data:
        bits.extend((0, *((byte >> bit) & 1 for bit in range(8)), 1))
    # Let receiver filters settle before the paced media channel drops carrier.
    bits.extend([1] * 12)
    phase = 0.0
    samples = []
    for sample in range((len(bits) * RATE + 1199) // 1200):
        frequency = 1200 if bits[sample * 1200 // RATE] else 2200
        samples.append(round(5000 * math.sin(phase)))
        phase = (phase + math.tau * frequency / RATE) % math.tau
    return _pcm(samples)


def resample_wav(data: bytes) -> bytes:
    with wave.open(io.BytesIO(data)) as source:
        if source.getnchannels() != 1 or source.getsampwidth() != 2:
            raise ValueError("speech engine must emit 16-bit mono PCM")
        source_rate = source.getframerate()
        pcm = source.readframes(source.getnframes())
    samples = [item[0] for item in struct.iter_unpack("<h", pcm)]
    return _pcm(samples[index * source_rate // RATE] for index in range(len(samples) * RATE // source_rate))


async def speech(text: str) -> bytes:
    process = await asyncio.create_subprocess_exec(
        "espeak-ng", "--stdout", "--stdin",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        async with asyncio.timeout(3):
            output, _ = await process.communicate(text.encode("utf-8"))
        if process.returncode:
            raise RuntimeError("speech generation failed")
        return resample_wav(output)
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
