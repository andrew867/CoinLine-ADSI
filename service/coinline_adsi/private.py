"""Opt-in OIDC enrollment and read-only private balance calls."""

import asyncio
import base64
import hmac
import json
import os
import re
import secrets
import time
from collections import deque
from pathlib import Path

from authlib.integrations.base_client import OAuthError
from authlib.integrations.starlette_client import OAuth
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field
from psycopg.errors import UniqueViolation
from starlette.middleware.sessions import SessionMiddleware

from . import wire
from .api import check_write
from .balances import Approvals, ProviderUnavailable, SimpleFIN


FORM = Path(__file__).with_name("private.html")
router = APIRouter()


class Unlinked(ProviderUnavailable):
    pass


def _number(value):
    if not value or not re.fullmatch(r"\+?1?[2-9]\d{2}[2-9]\d{6}", value):
        return None
    return value[-10:]


def configure(app):
    discovery = os.getenv("ADSI_OIDC_DISCOVERY")
    if not discovery:
        return None
    origin = os.environ["ADSI_WEB_ORIGIN"].rstrip("/")
    if not origin.startswith("https://") or not discovery.startswith("https://"):
        raise ValueError("Private enrollment requires HTTPS origins.")
    key = bytes.fromhex(os.environ["ADSI_DATA_KEY"])
    oauth = OAuth()
    oauth.register("subscriber", client_id=os.environ["ADSI_OIDC_CLIENT"],
                   client_secret=os.environ["ADSI_OIDC_SECRET"], server_metadata_url=discovery,
                   client_kwargs={"scope": "openid"})
    cookie_key = hmac.digest(key, b"oidc browser session", "sha256").hex()
    app.add_middleware(SessionMiddleware, secret_key=cookie_key, session_cookie="coinline_subscriber",
                       https_only=True, max_age=900, same_site="lax")
    app.include_router(router)
    return oauth, origin, key


class PrivateBalances:
    def __init__(self, store, client, key):
        self.store = store
        self.bridge = SimpleFIN(client)
        self.key = key
        self.cipher = Fernet(base64.urlsafe_b64encode(hmac.digest(key, b"simplefin credentials", "sha256")))
        self.approvals = Approvals(hmac.digest(key, b"call approvals", "sha256"))
        self.staged = {}
        self.recent = deque(maxlen=128)

    def indexed(self, label, value):
        return hmac.digest(self.key, f"{label}\0{value}".encode(), "sha256").hex()

    async def claim(self, subject, token):
        now = time.monotonic()
        self.staged = {key: value for key, value in self.staged.items() if value[0] > now}
        if len(self.staged) >= 64 or subject in self.staged:
            raise ProviderUnavailable("Finish the previous setup or wait for it to expire.")
        access = await self.bridge.claim(token)
        rows = await self.bridge.accounts(access)
        choices = {}
        for record in rows:
            keys = [record.get(key) for key in ("id", "conn_id", "name")] if isinstance(record, dict) else []
            if len(keys) == 3 and all(isinstance(field, str) and 1 <= len(field) <= 128 for field in keys):
                account, connection, name = keys
                choices[secrets.token_urlsafe(12)] = (account, connection, name)
        if not choices:
            raise ProviderUnavailable("No eligible accounts.")
        self.staged[subject] = (now + 120, access, choices)
        return [{"id": key, "label": item[2]} for key, item in choices.items()]

    async def link(self, subject, number, choice, alias):
        state = self.staged.get(subject)
        number = _number(number)
        if not state or not number or state[0] <= time.monotonic() or choice not in state[2]:
            raise ProviderUnavailable("Enrollment expired or was invalid.")
        _, access, choices = state
        account, connection, _ = choices[choice]
        sealed = self.cipher.encrypt(json.dumps({"access": access, "account": account, "connection": connection}).encode())
        try:
            async with self.store.pool.connection() as db:
                await db.execute("INSERT INTO bank_links(subject, phone_key, alias, sealed) VALUES (%s,%s,%s,%s) "
                                 "ON CONFLICT (subject) DO UPDATE SET phone_key=EXCLUDED.phone_key,"
                                 "alias=EXCLUDED.alias,sealed=EXCLUDED.sealed,changed_at=now()",
                                 (subject, self.indexed("phone", number), alias, sealed))
                await self.store._log(db, "bank_link", subject)
        except UniqueViolation:
            raise ProviderUnavailable("This line already has an enrollment.") from None
        self.staged.pop(subject, None)

    async def unlink(self, subject):
        async with self.store.pool.connection() as db:
            await db.execute("DELETE FROM bank_links WHERE subject=%s", (subject,))
            await self.store._log(db, "bank_unlink", subject)
        self.staged.pop(subject, None)

    async def call(self, caller, link, say):
        number = _number(caller)
        enrolled = None if number is None else await self.store._one(
            "SELECT subject, alias, sealed FROM bank_links WHERE phone_key=%s", (self.indexed("phone", number),))
        if enrolled is None or not await link.connect():
            await say("Private balance service unavailable.")
            return
        subject = enrolled["subject"]
        call = secrets.token_urlsafe(24)
        try:
            challenge = self.approvals.new(subject, call)
        except ValueError:
            await link.release()
            return
        approved = False
        try:
            await link.transfer(wire.screen(["PRIVATE BALANCE", f"Approval {challenge}", "Confirm on web", "Enter approval code"], []),
                                open_input=True)
            async with asyncio.timeout(120):
                for _ in range(3):
                    code = "".join([await link.selection(60) for _ in range(8)])
                    if self.approvals.check(challenge, call, code):
                        approved = True
                        break
        except TimeoutError:
            pass
        finally:
            self.approvals.pending.pop(challenge, None)
        if approved:
            try:
                balance = await self._balance(enrolled)
                as_of = balance.as_of.strftime("%Y-%m-%d %H:%M UTC")
                posted = f"{balance.currency} {balance.posted}"
                available = f"{balance.currency} {balance.available}" if balance.available is not None else ""
                if max(len(posted), len(available)) > 20:
                    raise ProviderUnavailable("Balance exceeds the terminal field size.")
                rows = [posted, as_of]
                if balance.available is not None:
                    rows.extend(["Available", available])
                else:
                    rows.extend([enrolled["alias"], "0 Exit"])
                await link.transfer(wire.screen(rows, [("Exit", "0")]), open_input=True)
                try:
                    await link.selection(60)
                except TimeoutError:
                    pass
            except (ProviderUnavailable, InvalidToken):
                await link.transfer(wire.screen(["BALANCE UNAVAILABLE"], []))
        await link.transfer(wire.screen(["GOODBYE"], []))
        await link.release()

    async def _balance(self, enrolled):
        now = time.monotonic()
        if any(subject == enrolled["subject"] and tick > now - 60 for subject, tick in self.recent):
            raise ProviderUnavailable("Balance unavailable.")
        self.recent.append((enrolled["subject"], now))
        async def active():
            return await self.store._one("SELECT sealed FROM bank_links WHERE subject=%s", (enrolled["subject"],))
        record = await active()
        if record is None or record["sealed"] != enrolled["sealed"]:
            raise Unlinked("Balance unavailable.")
        access = json.loads(self.cipher.decrypt(bytes(record["sealed"])))
        balance = await self.bridge.balance(access["access"], access["connection"], access["account"])
        record = await active()
        if record is None or record["sealed"] != enrolled["sealed"]:
            raise Unlinked("Balance unavailable.")
        return balance


class Token(BaseModel):
    token: str = Field(min_length=1, max_length=2048)


class Binding(BaseModel):
    phone: str = Field(max_length=14)
    choice: str = Field(max_length=40)
    alias: str = Field(pattern=r"^[\x20-\x7e]{1,18}$")


class Challenge(BaseModel):
    challenge: str = Field(pattern=r"^\d{8}$")


def context(request, write=False):
    if write:
        check_write(request)
    service = request.app.state.private
    subject = request.session.get("subject")
    if not service or not subject:
        raise HTTPException(401, "Sign in to access enrollment.")
    return service, subject


@router.get("/bank", response_class=HTMLResponse)
async def bank_page():
    return FORM.read_text(encoding="utf-8")


@router.get("/auth/login")
async def auth_login(request: Request, console: bool = False):
    oauth, origin, _ = request.app.state.oidc
    request.session["console_intent"] = console
    return await oauth.subscriber.authorize_redirect(request, origin + "/auth/callback")


@router.get("/auth/callback")
async def auth_callback(request: Request):
    oauth, _, _ = request.app.state.oidc
    try:
        token = await oauth.subscriber.authorize_access_token(request)
        identity = token["userinfo"]
        subject = request.app.state.private.indexed("subject", identity["iss"] + "/" + identity["sub"])
    except (OAuthError, KeyError, TypeError):
        raise HTTPException(401, "Sign-in could not be verified.") from None
    console = request.session.get("console_intent")
    request.session.clear()
    request.session["subject"] = subject
    if console:
        configured = json.loads(os.getenv("ADSI_OIDC_OPERATOR_SUBJECTS", "{}"))
        role = configured.get(identity["sub"])
        if role not in ("administrator", "publisher", "author", "viewer"):
            raise HTTPException(403, "Your account has no console role.")
        request.session["operator"] = {"subject": subject, "role": role}
        return RedirectResponse("/")
    return RedirectResponse("/bank")


@router.get("/api/v1/enrollment")
async def enrollment(request: Request):
    service, subject = context(request)
    record = await service.store._one("SELECT alias FROM bank_links WHERE subject=%s", (subject,))
    return {"linked": record is not None, "alias": record["alias"] if record else None}


@router.post("/api/v1/enrollment/bank-link")
async def claim(data: Token, request: Request):
    service, subject = context(request, write=True)
    return await service.claim(subject, data.token)


@router.put("/api/v1/enrollment")
async def bind(data: Binding, request: Request):
    service, subject = context(request, write=True)
    await service.link(subject, data.phone, data.choice, data.alias)
    return {"linked": True}


@router.delete("/api/v1/enrollment")
async def unlink(request: Request):
    service, subject = context(request, write=True)
    await service.unlink(subject)
    return {"linked": False}


@router.post("/api/v1/enrollment/call-approval")
async def approve(data: Challenge, request: Request):
    service, subject = context(request, write=True)
    code = service.approvals.approve(data.challenge, subject)
    if code is None:
        raise HTTPException(404, "No approval is available.")
    return {"code": code}
