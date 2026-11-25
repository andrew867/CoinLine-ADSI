"""An operator-initiated resident feature for the disposable lab slot."""

from hashlib import sha256

from . import wire
from .link import Link


def artifact(text: str, version: int, launcher: bool = False) -> tuple[bytes, ...]:
    if not 1 <= len(text) <= 20 or not text.isascii() or not text.isprintable() or not 1 <= version <= 255:
        raise ValueError("Use a printable resident message of up to 20 characters and version 1 to 255.")
    record = wire.parameter
    feature_connect = record(0x83, (b"CoinLine InfoLine" if launcher else b"CoinLine Lab") +
                             b"\xffCL01" + bytes(4) + bytes([version]))
    # The launcher takes the line off hook, waits for dial tone and dials the fixed lab service.
    action = b"\x82\x846501" if launcher else b"\x98\xc1\x08"
    resident_key = record(0x80, b"\x02Info\xffInfo\xff" + action)
    resident_display = record(0x81, b"\x81\x00\xff" + text.encode("ascii") + b"\xff")
    # Main script: on idle, show display 1 and select resident key 2.
    resident_script = record(0x82, bytes.fromhex("00 01 06 02 FF 03 C1 08 FF 02 01 02 FF"))
    return tuple(wire.frame(value, kind=wire.DOWNLOAD) for value in (
        feature_connect, resident_key, resident_display, resident_script, record(0x84)))


def fingerprint(text: str, version: int, launcher: bool = False) -> str:
    return sha256(b"".join(artifact(text, version, launcher))).hexdigest()


async def install(link: Link, text: str, version: int, launcher: bool = False) -> bool:
    connect, *records = artifact(text, version, launcher)
    if not await link.connect():
        return False
    await link.transfer(connect)
    if not await link.accept_download():
        await link.release()
        return False
    for record in records:
        await link.transfer(record)
    await link.release()
    return True
