"""Asterisk ARI call control and per-call media channels."""

import asyncio
import base64
import hmac
import json
import logging
import math
from collections import Counter, deque
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from uuid import uuid4

import httpx
from fastapi import WebSocket, WebSocketDisconnect
from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

from . import audio
from .link import CONTINUOUS_DATA, VOICE_BETWEEN_SCREENS, LAB_PROMPTS, PROFILES, Link, LinkFailure


LOG = logging.getLogger(__name__)
APP = "coinline"
MEDIA_FRAME_BYTES = 320
MEDIA_PREROLL = bytes(5 * MEDIA_FRAME_BYTES)


class Media:
    def __init__(self, socket: WebSocket):
        self.socket = socket
        self.mark: tuple[str, asyncio.Future[float]] | None = None

    async def play(self, pcm: bytes) -> float:
        if self.mark is not None:
            raise RuntimeError("overlapping call audio")
        loop = asyncio.get_running_loop()
        correlator = uuid4().hex
        completion = loop.create_future()
        self.mark = (correlator, completion)
        # Idle WebSocket channels emit no PCM. Fill the receiver's playout buffer before the burst.
        pcm = MEDIA_PREROLL + pcm + bytes(-len(pcm) % MEDIA_FRAME_BYTES)
        try:
            async with asyncio.timeout(len(pcm) / (2 * audio.RATE) + 2):
                await self.socket.send_json({"command": "START_MEDIA_BUFFERING"})
                for offset in range(0, len(pcm), 6400):
                    await self.socket.send_bytes(pcm[offset:offset + 6400])
                await self.socket.send_json({"command": "STOP_MEDIA_BUFFERING", "correlation_id": correlator})
                return await completion
        finally:
            self.mark = None

    async def receive(self) -> None:
        while True:
            message = await self.socket.receive()
            if message["type"] == "websocket.disconnect":
                return
            data = message.get("text")
            if data is None:
                # This profile accepts validated DTMF from the ARI caller leg.
                continue
            event = json.loads(data)
            if event["event"] == "MEDIA_XOFF":
                return
            if self.mark and event["event"] == "MEDIA_BUFFERING_COMPLETED":
                correlator, completion = self.mark
                if event.get("correlation_id") == correlator and not completion.done():
                    completion.set_result(asyncio.get_running_loop().time())


@dataclass
class Admission:
    channel_id: str
    media_id: str
    bridge_id: str
    media: asyncio.Future[Media]
    media_stasis: asyncio.Event
    task: asyncio.Task | None = None
    link: Link | None = None


CallHandler = Callable[[str, str | None, Link, Callable[[str], Awaitable[None]]], Awaitable[None]]


class Gateway:
    def __init__(self, base: str, password: str, handler: CallHandler, limit: int = 10,
                 emu_alert_delay: float = 1.0, emu_interaction_profile: str = CONTINUOUS_DATA,
                 shadybank_profile: str = VOICE_BETWEEN_SCREENS):
        if not 0.25 <= emu_alert_delay <= 5.0:
            raise ValueError("Emulator first-alert delay must be 250 to 5000 ms.")
        if emu_interaction_profile not in PROFILES or shadybank_profile not in PROFILES:
            raise ValueError("Unknown emulator interaction profile.")
        self.base = base.rstrip("/")
        self.authorization = "Basic " + base64.b64encode(f"{APP}:{password}".encode()).decode()
        self.http = httpx.AsyncClient(base_url=self.base + "/ari/", auth=(APP, password), timeout=2, trust_env=False)
        self.handler = handler
        self.limit = limit
        self.emu_alert_delay = emu_alert_delay
        self.emu_interaction_profile = emu_interaction_profile
        self.shadybank_profile = shadybank_profile
        self.connected = False
        self.calls: dict[str, Admission] = {}
        self.pending: dict[str, Admission] = {}
        self.outcomes = Counter()
        self.latencies = deque(maxlen=256)
        self.lab_audio: dict[str, bytes] = {}

    def first_alert_delay(self, route: str) -> float:
        return self.emu_alert_delay if route == "emu-infoline" else 0.25

    def interaction_profile(self, route: str) -> str:
        if route == "shadybank":
            return self.shadybank_profile
        return self.emu_interaction_profile if route == "emu-infoline" else CONTINUOUS_DATA

    def status(self):
        samples = sorted(list(self.latencies)[-100:])
        percentile = samples[math.ceil(len(samples) * .95) - 1] if samples else None
        return {"ready": self.connected, "active": len(self.calls), "outcomes": self.outcomes,
                "response_samples": len(samples),
                "p95_dispatch_seconds": round(percentile, 4) if percentile is not None else None}

    async def _request(self, method: str, url: str, **parameters):
        response = await self.http.request(method, url, params=parameters)
        response.raise_for_status()

    async def serve(self) -> None:
        address = self.base.replace("http", "ws", 1) + f"/ari/events?app={APP}"
        try:
            while True:
                if not self.lab_audio:
                    try:
                        self.lab_audio = {prompt: await audio.speech(prompt) for prompt in LAB_PROMPTS}
                    except (OSError, RuntimeError, TimeoutError) as error:
                        # A transient speech startup failure must not leave the gateway task dead.
                        LOG.warning("Gateway prompt preparation failed (%s)", type(error).__name__)
                        await asyncio.sleep(1)
                        continue
                try:
                    async with connect(address, additional_headers={"Authorization": self.authorization}, proxy=None) as ws:
                        self.connected = True
                        async for raw in ws:
                            await self._event(json.loads(raw))
                except (OSError, WebSocketException, httpx.HTTPError, TimeoutError) as error:
                    LOG.warning("ARI unavailable (%s)", type(error).__name__)
                finally:
                    self.connected = False
                    tasks = [call.task for call in self.calls.values() if call.task]
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                await asyncio.sleep(1)
        finally:
            await self.http.aclose()

    async def _event(self, event: dict) -> None:
        channel = event.get("channel")
        if channel is None:
            return
        identifier = channel["id"]
        kind = event["type"]
        if kind == "StasisStart" and identifier in self.pending:
            self.pending[identifier].media_stasis.set()
        elif kind == "StasisStart" and event.get("args") and channel.get("name", "").startswith("PJSIP/"):
            if identifier in self.calls:
                return
            if len(self.calls) >= self.limit:
                self.outcomes["busy"] += 1
                with suppress(httpx.HTTPError):
                    await self._request("DELETE", f"channels/{identifier}", reason="busy")
                return
            loop = asyncio.get_running_loop()
            call = Admission(identifier, uuid4().hex, uuid4().hex, loop.create_future(), asyncio.Event())
            self.calls[identifier] = self.pending[call.media_id] = call
            self.outcomes["admitted"] += 1
            caller = channel.get("caller", {}).get("number")
            call.task = asyncio.create_task(self._serve_call(call, event["args"][0], caller))
        elif kind in ("StasisEnd", "ChannelDestroyed"):
            call = self.calls.get(identifier) or self.pending.get(identifier)
            if call and call.task and not call.task.done():
                call.task.cancel()
        elif kind == "ChannelDtmfReceived":
            call = self.calls.get(identifier)
            if call and call.link:
                try:
                    call.link.receive(event["digit"], asyncio.get_running_loop().time())
                except asyncio.QueueFull:
                    call.task.cancel()

    async def _serve_call(self, call: Admission, route: str, caller: str | None) -> None:
        stage = "answer"
        try:
            async with asyncio.timeout(5):
                await self._request("POST", f"channels/{call.channel_id}/answer")
                stage = "bridge_create"
                await self._request("POST", "bridges", bridgeId=call.bridge_id, type="mixing,proxy_media,dtmf_events")
                stage = "media_create"
                await self._request("POST", "channels/externalMedia", app=APP, channelId=call.media_id,
                                    external_host="coinline_media", transport="websocket", encapsulation="none",
                                    format="slin", transport_data="f(json)")
                stage = "media_ready"
                media = await call.media
                await call.media_stasis.wait()
                stage = "bridge_join"
                await self._request("POST", f"bridges/{call.bridge_id}/addChannel",
                                    channel=f"{call.channel_id},{call.media_id}")
            # Let the newly bridged RTP leg start delivering media before CAS.
            await asyncio.sleep(self.first_alert_delay(route))
            stage = "application"
            call.link = Link(media.play, observe=self.latencies.append if route == "lab" else None,
                             profile=self.interaction_profile(route))

            async def say(text):
                pcm = self.lab_audio.get(text) if route == "lab" else None
                if pcm is None:
                    pcm = await audio.speech(text)
                call.link.response_begin()
                await media.play(pcm)

            async with asyncio.timeout(15 * 60):
                await self.handler(route, caller, call.link, say)
        except (httpx.HTTPError, TimeoutError, RuntimeError, WebSocketDisconnect, OSError) as error:
            self.outcomes["failed"] += 1
            failure = f"http_{error.response.status_code}" if isinstance(error, httpx.HTTPStatusError) else type(error).__name__
            self.outcomes[f"{stage}_{failure}"] += 1
            LOG.info("call ended at %s (%s)", stage, failure)
            if isinstance(error, LinkFailure) and call.link and not call.link.uncertain:
                with suppress(LinkFailure, TimeoutError, RuntimeError, WebSocketDisconnect):
                    async with asyncio.timeout(2):
                        await call.link.release()
        except asyncio.CancelledError:
            self.outcomes[f"{stage}_cancelled"] += 1
            raise
        finally:
            self.outcomes["closed"] += 1
            self.calls.pop(call.channel_id, None)
            self.pending.pop(call.media_id, None)
            await asyncio.gather(*(self._delete(path) for path in (
                f"channels/{call.channel_id}", f"channels/{call.media_id}", f"bridges/{call.bridge_id}"
            )))

    async def _delete(self, path: str) -> None:
        with suppress(httpx.HTTPError):
            await self._request("DELETE", path)

    async def accept(self, socket: WebSocket) -> None:
        offered = socket.scope.get("subprotocols", ())
        if "media" not in offered or not hmac.compare_digest(socket.headers.get("authorization", ""), self.authorization):
            await socket.close(code=1008)
            return
        await socket.accept(subprotocol="media")
        call = None
        try:
            async with asyncio.timeout(2):
                start = await socket.receive_json()
            if not (start.get("event") == "MEDIA_START" and start.get("format") == "slin"
                    and start.get("optimal_frame_size") == MEDIA_FRAME_BYTES):
                await socket.close(code=1003)
                return
            call = self.pending.get(start.get("channel_id"))
            if call is None or call.media.done():
                await socket.close(code=1008)
                return
            media = Media(socket)
            call.media.set_result(media)
            await media.receive()
        except (WebSocketDisconnect, TimeoutError, ValueError, RuntimeError):
            pass
        finally:
            if call is not None and self.pending.get(call.media_id) is call and call.task:
                call.task.cancel()
