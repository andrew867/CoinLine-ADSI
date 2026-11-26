"""The same-origin lab console and fixture-only simulator."""

import asyncio
import hashlib
import hmac
import os
import re
import secrets
import time
from dataclasses import dataclass, field
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field

from . import fdm, graph, parcel, providers


class Login(BaseModel):
    password: str = Field(min_length=1, max_length=128)


class AppInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    graph: dict | None = None


class DraftInput(BaseModel):
    graph: dict


class PublishInput(BaseModel):
    routes: list[str] = Field(default_factory=list, max_length=8)


class ActivateInput(PublishInput):
    revision: UUID


class ArchiveInput(BaseModel):
    disable_routes: bool = False


class SimInput(BaseModel):
    graph: dict
    fault: str | None = None


class SimEvent(BaseModel):
    digit: str | None = Field(default=None, min_length=1, max_length=1)
    timeout: bool = False
    hangup: bool = False


class Feature(BaseModel):
    text: str = Field(min_length=1, max_length=20)
    version: int = Field(ge=1, le=255)
    approved: bool = False
    launcher: bool = False


@dataclass
class Simulation:
    owner: str
    instance: graph.Session
    fault: str | None
    expires: float
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    parcel_digits: str = ""
    parcel_confirm: bool = False
    parcel_accepted: bool = False

    async def lookup(self, operation, arguments):
        return providers.fixture(operation, arguments, self.fault)

    def parcel_entry(self):
        node = self.instance.nodes[self.instance.node]
        return (not self.instance.ended and node.get("operation") == "parcel.track"
                and node["args"].get("number") == "selected" and not self.parcel_accepted)

    def parcel_event(self, digit):
        if self.parcel_confirm:
            if digit == "1":
                self.parcel_accepted = True
            elif digit == "0":
                self.instance._move(self.instance.nodes[self.instance.node]["onUnavailable"])
            elif digit != "2":
                return
            self.parcel_confirm = False
            self.parcel_digits = ""
        elif digit == "#":
            self.parcel_confirm = bool(parcel.NUMBER.fullmatch(self.parcel_digits))
            if not self.parcel_confirm:
                self.parcel_digits = ""
        elif digit == "*":
            if not self.parcel_digits:
                self.instance._move(self.instance.nodes[self.instance.node]["onUnavailable"])
            self.parcel_digits = self.parcel_digits[:-1]
        elif digit in "0123456789" and len(self.parcel_digits) < 22:
            self.parcel_digits += digit

    async def result(self):
        if self.parcel_entry():
            lines = parcel.confirmation(self.parcel_digits) if self.parcel_confirm else [
                parcel.ENTRY_LINES[0], "Demo: sample number", *parcel.ENTRY_LINES[2:]]
            keys = parcel.CONFIRM_KEYS if self.parcel_confirm else parcel.ENTRY_KEYS
            slots = [1,2,6] if self.parcel_confirm else [4,5]
            return {"node": self.instance.node, "lines": lines, "choices": [
                {"label": label, "digit": digit, "slot": slot} for (label, digit), slot in zip(keys, slots)],
                "prompt": "Fixture only. Use a synthetic tracking number.", "page": 1, "pageCount": 1,
                "ended": False, "trace": self.instance.trace[-64:]}
        view = await self.instance.settle(self.lookup)
        self.parcel_accepted = False
        return {**view, "trace": self.instance.trace[-64:]}


def check_write(request: Request) -> None:
    if request.headers.get("x-coinline-csrf") != "request":
        raise HTTPException(403, "Same-origin request required.")
    origin = request.headers.get("origin")
    expected = os.getenv("ADSI_WEB_ORIGIN", str(request.base_url).rstrip("/"))
    if origin and origin != expected:
        raise HTTPException(403, "Same-origin request required.")


def principal(request: Request) -> str:
    if request.method not in ("GET", "HEAD"):
        check_write(request)
    if request.app.state.oidc:
        operator = request.session.get("operator", {})
        identifier = operator.get("subject")
        if not identifier:
            raise HTTPException(401, "Sign in to the console.")
        request.state.role = operator["role"]
    else:
        identifier = request.cookies.get("coinline_session", "")
        if request.app.state.sessions.get(identifier, 0) <= time.monotonic():
            raise HTTPException(401, "Sign in to the local console.")
        request.state.role = "administrator"
        identifier = hashlib.sha256(identifier.encode()).hexdigest()
    return identifier


def roles(*accepted):
    def enforce(request: Request):
        principal(request)
        if request.state.role not in accepted:
            raise HTTPException(403, "This operation requires a different role.")
    return Depends(enforce)


ADMIN = roles("administrator")
AUTHOR = roles("administrator", "author")
PUBLISHER = roles("administrator", "publisher")


def database(request: Request):
    if request.app.state.db is None:
        raise HTTPException(503, "Application storage is unavailable.")
    return request.app.state.db


async def accessible(request, store, identifier):
    row = await store.application(identifier)
    if request.state.role == "author" and row["owner"] != principal(request):
        raise HTTPException(404, "Application not found.")
    return row


def checked(document):
    errors = graph.validate(document)
    if errors:
        raise HTTPException(422, errors)
    return document


def etag(match):
    if not match or not re.fullmatch(r'"\d{1,12}"', match):
        raise HTTPException(428, "Supply the current draft or configuration ETag.")
    return int(match[1:-1])


def draft_response(response: Response, row):
    response.headers["ETag"] = f'"{row["generation"]}"'
    return row


login = APIRouter(prefix="/api/v1")
api = APIRouter(prefix="/api/v1", dependencies=[Depends(principal)])


@login.post("/session")
async def sign_in(data: Login, request: Request, response: Response):
    check_write(request)
    if request.app.state.oidc:
        raise HTTPException(403, "Use the configured identity provider.")
    password = os.getenv("ADSI_ADMIN_PASSWORD")
    timestamp = time.monotonic()
    failures = request.app.state.failures
    while failures and failures[0] <= timestamp - 60:
        failures.popleft()
    if len(failures) >= 10:
        raise HTTPException(429, "Try again in a minute.")
    if not password or not hmac.compare_digest(data.password.encode(), password.encode()):
        failures.append(timestamp)
        raise HTTPException(401, "Incorrect access code.")
    sessions = request.app.state.sessions
    for key in [key for key, expires in sessions.items() if expires <= timestamp]:
        sessions.pop(key)
    if len(sessions) >= 64:
        raise HTTPException(429, "Too many active console sessions.")
    identifier = secrets.token_urlsafe(32)
    sessions[identifier] = timestamp + 3600
    response.set_cookie("coinline_session", identifier, max_age=3600, httponly=True, samesite="strict",
                        secure=request.url.scheme == "https")
    return {"role": "administrator"}


@api.get("/session")
async def whoami(request: Request):
    return {"role": request.state.role}


@login.get("/session/mode")
async def session_mode(request: Request):
    return {"oidc": bool(request.app.state.oidc)}


@api.delete("/session")
async def sign_out(request: Request, response: Response):
    if request.app.state.oidc:
        request.session.clear()
    else:
        request.app.state.sessions.pop(request.cookies.get("coinline_session", ""), None)
        response.delete_cookie("coinline_session")


@api.get("/apps")
async def applications(request: Request, store=Depends(database)):
    return await store.applications(principal(request) if request.state.role == "author" else None)


@api.post("/apps", status_code=201, dependencies=[AUTHOR])
@api.post("/apps/import", status_code=201, dependencies=[AUTHOR])
async def create(data: AppInput, response: Response, request: Request, store=Depends(database)):
    default = {"schemaVersion": 1, "entry": "welcome", "nodes": [
        {"id": "welcome", "type": "menu", "lines": ["WELCOME", "0 Exit"],
         "prompt": "Welcome. Press zero to exit.", "choices": [{"digit": "0", "label": "Exit", "target": "end"}],
         "onTimeout": "end"}, {"id": "end", "type": "end", "prompt": "Goodbye."}]}
    name = data.name.strip()
    if not name:
        raise HTTPException(422, "Enter an application name.")
    document = checked(default if data.graph is None else data.graph)
    return draft_response(response, await store.create(name, document, principal(request)))


@api.get("/apps/{identifier}")
@api.get("/apps/{identifier}/draft")
async def app_detail(identifier: UUID, response: Response, request: Request, store=Depends(database)):
    return draft_response(response, await accessible(request, store, identifier))


@api.patch("/apps/{identifier}", dependencies=[AUTHOR])
async def rename(identifier: UUID, data: AppInput, response: Response, request: Request,
                 if_match: str | None = Header(None), store=Depends(database)):
    name = data.name.strip()
    if not name:
        raise HTTPException(422, "Enter an application name.")
    await accessible(request, store, identifier)
    return draft_response(response, await store.edit(identifier, etag(if_match), name=name))


@api.put("/apps/{identifier}/draft", dependencies=[AUTHOR])
async def save(identifier: UUID, data: DraftInput, response: Response, request: Request,
               if_match: str | None = Header(None), store=Depends(database)):
    await accessible(request, store, identifier)
    return draft_response(response, await store.edit(identifier, etag(if_match), graph=checked(data.graph)))


@api.post("/apps/{identifier}/validate")
async def validate(identifier: UUID, data: DraftInput):
    errors = graph.validate(data.graph)
    return {"valid": not errors, "errors": errors}


@api.get("/apps/{identifier}/revisions")
async def revisions(identifier: UUID, request: Request, store=Depends(database)):
    await accessible(request, store, identifier)
    return await store.revisions(identifier)


@api.post("/apps/{identifier}/revisions", dependencies=[PUBLISHER])
async def publish(identifier: UUID, data: PublishInput,
                  if_match: str | None = Header(None), store=Depends(database)):
    return await store.publish(identifier, etag(if_match), data.routes, checked)


@api.post("/apps/{identifier}/activate", dependencies=[PUBLISHER])
async def activate(identifier: UUID, data: ActivateInput, store=Depends(database)):
    await store.activate(identifier, data.revision, data.routes)
    return {"ok": True}


@api.post("/apps/{identifier}/archive", dependencies=[PUBLISHER])
async def archive(identifier: UUID, data: ArchiveInput, store=Depends(database)):
    await store.archive(identifier, data.disable_routes)
    return {"ok": True}


@api.post("/apps/{identifier}/restore", dependencies=[PUBLISHER])
async def restore(identifier: UUID, store=Depends(database)):
    await store.restore(identifier)
    return {"ok": True}


@api.get("/apps/{identifier}/export")
async def export(identifier: UUID, request: Request, revision: UUID | None = None, store=Depends(database)):
    await accessible(request, store, identifier)
    return await store.export(identifier, revision)


@api.get("/routes")
async def routes(store=Depends(database)):
    return await store.routes()


@api.get("/telephony/status")
async def telephony_status(request: Request):
    gateway = request.app.state.gateway
    status = gateway.status() if gateway else {"ready": False, "active": 0}
    if gateway and os.getenv("ADSI_EMU_ENABLE") == "1":
        status["emulatorIngress"] = {"uri": "sip:2374@127.0.0.1:5069", "fromUser": "co",
                                     "firstAlertMs": round(gateway.first_alert_delay("emu-infoline") * 1000),
                                     "interactionProfile": gateway.interaction_profile("emu-infoline")}
    return status


@api.get("/profiles")
async def profiles():
    return [
        {"id": "lab", "label": "ADSI SIP lab", "columns": 20, "lines": 4, "status": "Software"},
        {"id": "vista-350", "label": "Vista 350", "status": "Physical test pending"},
        {"id": "millennium", "label": "Millennium", "status": "Physical test pending"},
    ]


@api.get("/providers")
async def provider_config(response: Response, store=Depends(database)):
    return draft_response(response, await store.setting("providers"))


@api.put("/providers", dependencies=[ADMIN])
async def set_providers(value: dict, response: Response, if_match: str | None = Header(None), store=Depends(database)):
    try:
        providers.check_config(value)
    except (TypeError, ValueError) as error:
        raise HTTPException(422, str(error)) from error
    return draft_response(response, await store.set_setting("providers", etag(if_match), value))


@api.post("/providers/test")
async def provider_test(value: dict, request: Request):
    try:
        providers.check_config(value)
    except (TypeError, ValueError) as error:
        raise HTTPException(422, str(error)) from error
    return {"valid": True, "sites": len(value.get("sites", {})), "mode": "configuration check"}


@api.get("/features")
async def feature(response: Response, store=Depends(database)):
    return draft_response(response, await store.setting("fdm"))


@api.put("/features", dependencies=[ADMIN])
async def save_feature(value: Feature, response: Response, if_match: str | None = Header(None), store=Depends(database)):
    if value.approved and os.getenv("ADSI_FDM_ENABLE") != "1":
        raise HTTPException(409, "Resident download is disabled on this deployment.")
    try:
        digest = fdm.fingerprint(value.text, value.version, value.launcher)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return draft_response(response, await store.set_setting("fdm", etag(if_match), {**value.model_dump(), "sha256": digest}))


@api.post("/simulations", status_code=201)
async def simulate(data: SimInput, request: Request, owner=Depends(principal)):
    if data.fault not in (None, "unavailable", "stale"):
        raise HTTPException(422, "Unknown simulator fault.")
    now = time.monotonic()
    sims = request.app.state.simulations
    for key in [key for key, value in sims.items() if value.expires <= now]:
        sims.pop(key)
    if len(sims) >= 128:
        raise HTTPException(429, "Too many simulations.")
    identifier = uuid4()
    instance = Simulation(owner, graph.Session(checked(data.graph)), data.fault, now + 900)
    sims[identifier] = instance
    return {"id": identifier, **await instance.result()}


def _simulation(request, identifier, owner):
    sim = request.app.state.simulations.get(identifier)
    if sim is None or sim.owner != owner or sim.expires <= time.monotonic():
        raise HTTPException(404, "Simulation not found.")
    return sim


@api.get("/simulations/{identifier}")
async def simulation(identifier: UUID, request: Request, owner=Depends(principal)):
    sim = _simulation(request, identifier, owner)
    async with sim.lock:
        return {"id": identifier, **await sim.result()}


@api.post("/simulations/{identifier}/events")
async def event(identifier: UUID, data: SimEvent, request: Request, owner=Depends(principal)):
    sim = _simulation(request, identifier, owner)
    if sum((data.digit is not None, data.timeout, data.hangup)) != 1:
        raise HTTPException(422, "Send one simulator action.")
    async with sim.lock:
        if data.hangup:
            sim.instance.ended = True
            sim.parcel_digits = ""
        elif sim.parcel_entry():
            if data.timeout:
                sim.parcel_digits = ""
                sim.parcel_confirm = False
                sim.instance._move(sim.instance.nodes[sim.instance.node]["onUnavailable"])
            else:
                sim.parcel_event(data.digit)
        elif not sim.instance.view()["ended"]:
            if data.timeout:
                sim.instance.timeout()
            else:
                sim.instance.choose(data.digit)
        return {"id": identifier, **await sim.result()}
