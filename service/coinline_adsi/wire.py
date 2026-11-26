"""The single-frame off-hook ADSI profile."""

DISPLAY = 0x84
DOWNLOAD = 0x85
PAYLOAD_LIMIT = 253


def parameter(tag: int, value: bytes = b"") -> bytes:
    if len(value) > 255:
        raise ValueError("parameter exceeds one-byte length")
    return bytes((tag, len(value))) + value


def frame(*parameters: bytes, kind: int = DISPLAY) -> bytes:
    body = b"".join(parameters)
    if kind not in (DISPLAY, DOWNLOAD) or len(body) > PAYLOAD_LIMIT:
        raise ValueError("unsupported frame type or length")
    header = bytes((kind, len(body) + 1, 1))
    return header + body + bytes((-sum(header + body) & 0xFF,))


def _text(value: str, limit: int) -> bytes:
    encoded = value.encode("ascii")
    if len(encoded) > limit or any(not 32 <= item <= 126 for item in encoded):
        raise ValueError("text exceeds the printable screen field")
    return encoded


def display_line(number: int, primary: str, secondary: str = "") -> bytes:
    if not 1 <= number <= 33:
        raise ValueError("invalid information page line")
    return parameter(0x82, bytes((number, 0x40, 0xFF)) + _text(primary, 20) + b"\xff" + _text(secondary, 20))


def select_line(number: int) -> bytes:
    if not 1 <= number <= 33:
        raise ValueError("invalid information page line")
    return parameter(0x83, bytes((number,)))


def softkey(key: int, label: str, digit: str) -> bytes:
    if not 16 <= key <= 33 or len(digit) != 1 or digit not in "0123456789*#":
        raise ValueError("invalid softkey binding")
    short = label[:7]
    return parameter(0x80, bytes((key,)) + _text(label, 18) + b"\xff" + _text(short, 7) + b"\xff" + digit.encode())


def key_map(keys: list[int]) -> bytes:
    if len(keys) > 6 or any(key != 1 and not 16 <= key <= 33 for key in keys):
        raise ValueError("invalid softkey map")
    return parameter(0x81, bytes([*keys, *([1] * (6 - len(keys)))]))


VOICE_MODE = parameter(0x87, b"\0")


def information_flags(flags: bytes) -> bytes:
    """Encode an explicit two-octet information control value."""
    if len(flags) != 2:
        raise ValueError("information flags require two bytes")
    return parameter(0x84, flags)


def finish_in_voice(data: bytes) -> bytes:
    """Append an immediate voice transition to a complete SDC frame."""
    if (len(data) < 4 or data[0] != DISPLAY or data[1] != len(data) - 3
            or data[2] != 1 or sum(data) & 255):
        raise ValueError("expected a valid single SDC frame")
    return frame(data[3:-1], VOICE_MODE)


def screen(lines: list[str], choices: list[tuple[str, str]], *, information: bytes | None = None,
           slots: list[int] | None = None) -> bytes:
    if not 1 <= len(lines) <= 4:
        raise ValueError("invalid viewport height")
    slots = list(range(1, len(choices) + 1)) if slots is None else slots
    if len(slots) != len(choices) or len(set(slots)) != len(slots) or not all(1 <= slot <= 6 for slot in slots):
        raise ValueError("invalid physical softkey slots")
    keys = [softkey(15 + slot, label, digit) for slot, (label, digit) in zip(slots, choices)]
    mapping = [15 + slot if slot in slots else 1 for slot in range(1, 7)]
    return frame(
        parameter(0x94),
        parameter(0x88),
        *(display_line(index, line) for index, line in enumerate(lines, 1)),
        select_line(1),
        *keys,
        key_map(mapping),
        *([information_flags(information)] if information is not None else []),
    )


CONNECT = frame(parameter(0x8E), parameter(0x86))
LAB = frame(display_line(1, "LAB"), select_line(1), softkey(16, "Go", "1"), key_map([16]))
OK = frame(parameter(0x88), display_line(1, "OK"), select_line(1))
RELEASE = frame(parameter(0x85), VOICE_MODE)
