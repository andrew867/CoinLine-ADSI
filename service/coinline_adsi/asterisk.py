"""Asterisk ARI call control and per-call media channels."""

import asyncio
import base64
import hmac
import json
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from uuid import uuid4

import httpx
from fastapi import WebSocket, WebSocketDisconnect
from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

from . import audio
from .link import Link, LinkFailure


LOG = logging.getLogger(__name__)
APP = "coinline"


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
    task: asyncio.Task | None = None
    link: Link | None = None


CallHandler = Callable[[str, str | None, Link, Callable[[str], Awaitable[None]]], Awaitable[None]]


class Gateway:
    def __init__(self, base: str, password: str, handler: CallHandler, limit: int = 10):
        self.base = base.rstrip("/")
        self.authorization = "Basic " + base64.b64encode(f"{APP}:{password}".encode()).decode()
        self.http = httpx.AsyncClient(base_url=self.base + "/ari/", auth=(APP, password), timeout=2, trust_env=False)
        self.handler = handler
        self.limit = limit
        self.connected = False
        self.calls: dict[str, Admission] = {}
        self.pending: dict[str, Admission] = {}

    async def _request(self, method: str, url: str, **parameters):
        response = await self.http.request(method, url, params=parameters)
        response.raise_for_status()

    async def serve(self) -> None:
        address = self.base.replace("http", "ws", 1) + f"/ari/events?app={APP}"
        try:
            while True:
                try:
                    async with connect(address, additional_headers={"Authorization": self.authorization}, proxy=None) as ws:
                        self.connected = True
                        async for raw in ws:
                            await self._event(json.loads(raw))
                except (OSError, WebSocketException, httpx.HTTPError, TimeoutError) as error:
                    LOG.info("ARI unavailable (%s)", type(error).__name__)
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
        if kind == "StasisStart" and event.get("args") and channel.get("name", "").startswith("PJSIP/"):
            if identifier in self.calls:
                return
            if len(self.calls) >= self.limit:
                with suppress(httpx.HTTPError):
                    await self._request("DELETE", f"channels/{identifier}", reason="busy")
                return
            loop = asyncio.get_running_loop()
            call = Admission(identifier, uuid4().hex, uuid4().hex, loop.create_future())
            self.calls[identifier] = self.pending[call.media_id] = call
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
        try:
            async with asyncio.timeout(5):
                await self._request("POST", f"channels/{call.channel_id}/answer")
                await self._request("POST", "bridges", bridgeId=call.bridge_id, type="mixing,proxy_media,dtmf_events")
                await self._request("POST", "channels/externalMedia", app=APP, channelId=call.media_id,
                                    external_host="coinline_media", transport="websocket", encapsulation="none",
                                    format="slin", transport_data="f(json)")
                media = await call.media
                await self._request("POST", f"bridges/{call.bridge_id}/addChannel",
                                    channel=f"{call.channel_id},{call.media_id}")
            # Let the newly bridged RTP leg start delivering media before CAS.
            await asyncio.sleep(0.25)
            call.link = Link(media.play)

            async def say(text):
                await media.play(await audio.speech(text))

            async with asyncio.timeout(15 * 60):
                await self.handler(route, caller, call.link, say)
        except (httpx.HTTPError, TimeoutError, RuntimeError, WebSocketDisconnect, OSError) as error:
            LOG.info("call ended (%s)", type(error).__name__)
            if isinstance(error, LinkFailure) and call.link and not call.link.uncertain:
                with suppress(LinkFailure, TimeoutError, RuntimeError, WebSocketDisconnect):
                    async with asyncio.timeout(2):
                        await call.link.release()
        finally:
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
            if not (start.get("event") == "MEDIA_START" and start.get("format") == "slin"):
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
