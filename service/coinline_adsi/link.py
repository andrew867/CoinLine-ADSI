"""Off-hook ADSI signaling with one owner for call input."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from . import audio, wire


Play = Callable[[bytes], Awaitable[float]]


@dataclass(frozen=True)
class Digit:
    value: str
    time: float


class LinkFailure(RuntimeError):
    """The active data exchange could not be confirmed."""


class Link:
    def __init__(self, play: Play, *, reply_timeout: float = 1.0, probe_timeout: float = 0.5):
        self._play = play
        self._reply_timeout = reply_timeout
        self._probe_timeout = probe_timeout
        self._digits: asyncio.Queue[Digit] = asyncio.Queue(maxsize=64)
        self._input_since: float | None = None
        self._last_ack = 0.0
        self.data_mode = False
        self.uncertain = False

    def receive(self, value: str, when: float) -> None:
        self._digits.put_nowait(Digit(value, when))

    def _discard_input(self) -> None:
        self._input_since = None
        while not self._digits.empty():
            self._digits.get_nowait()

    async def _digit(self, after: float, timeout: float) -> Digit:
        async with asyncio.timeout(timeout):
            while True:
                received = await self._digits.get()
                if received.time >= after:
                    return received

    async def connect(self) -> bool:
        self._discard_input()
        played = await self._play(audio.cas())
        try:
            reply = await self._digit(played, self._probe_timeout)
        except TimeoutError:
            return False
        if reply.value != "A":
            return False
        self.data_mode = True
        await self.transfer(wire.CONNECT)
        return True

    async def _acknowledged(self, pcm: bytes) -> bool:
        self._discard_input()
        played = await self._play(pcm)
        try:
            prefix = await self._digit(played, self._reply_timeout)
            if prefix.value != "D":
                return False
            count = await self._digit(prefix.time, self._reply_timeout)
            self._last_ack = count.time
            return count.value == "1"
        except TimeoutError:
            return False

    async def transfer(self, data: bytes, *, open_input: bool = False) -> None:
        if self.uncertain:
            raise LinkFailure("prior acknowledgment is unresolved")
        self._input_since = None
        pcm = audio.bell202(data)
        if not await self._acknowledged(pcm):
            # The default profile has no proven bound on an old D1. A retry
            # can confirm these bytes, but cannot authorize a different frame.
            await self._acknowledged(pcm)
            self.uncertain = True
            raise LinkFailure("retry left an outstanding acknowledgment")
        if open_input:
            self._input_since = asyncio.get_running_loop().time()

    async def release(self) -> None:
        if self.data_mode:
            await self.transfer(wire.RELEASE)
            self.data_mode = False

    async def accept_download(self) -> bool:
        self._input_since = None
        try:
            return (await self._digit(self._last_ack, self._reply_timeout)).value == "B"
        except TimeoutError:
            return False

    def open_voice_input(self) -> None:
        self._discard_input()
        self._input_since = asyncio.get_running_loop().time()

    async def selection(self, timeout: float = 60) -> str:
        if self._input_since is None:
            raise LinkFailure("application input is disarmed")
        prefix_time = -1.0
        async with asyncio.timeout(timeout):
            while True:
                digit = await self._digits.get()
                if digit.time < self._input_since:
                    continue
                if digit.value == "D":
                    prefix_time = digit.time
                elif len(digit.value) == 1 and digit.value in "0123456789*#":
                    if digit.time - prefix_time > self._reply_timeout:
                        return digit.value
                    prefix_time = -1.0


async def lab_call(link: Link, say: Callable[[str], Awaitable[None]]) -> None:
    if await link.connect():
        await link.transfer(wire.LAB, open_input=True)
        if await link.selection() == "1":
            await link.transfer(wire.OK)
        await link.release()
        await say("Voice restored. Goodbye.")
        return
    link.open_voice_input()
    await say("CoinLine. Press one to continue.")
    if await link.selection() == "1":
        await say("OK. Goodbye.")
