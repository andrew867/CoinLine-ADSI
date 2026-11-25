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
from uuid import uuid4

from authlib.integrations.base_client import OAuthError
from authlib.integrations.starlette_client import OAuth
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from psycopg.errors import UniqueViolation
from starlette.middleware.sessions import SessionMiddleware

from . import wire
from .api import check_write, principal
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
        if os.getenv("ADSI_LOCAL_BANK_ENROLLMENT") == "1":
            app.include_router(router)
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
        self.recent = deque(maxlen=128)

    def indexed(self, label, value):
        return hmac.digest(self.key, f"{label}\0{value}".encode(), "sha256").hex()

    def local_subject(self):
        return self.indexed("subject", "local-enrollment-owner")

    async def claim(self, subject, token):
        self.bridge.claim_url(token)
        claim_id = uuid4()
        row = await self.store._one("INSERT INTO bank_pending(subject, claim_id) VALUES (%s,%s) "
                                    "ON CONFLICT DO NOTHING RETURNING claim_id", (subject, claim_id))
        if row is None:
            raise ProviderUnavailable("A setup is already pending. Resume it before supplying another token.")
        access = await self.bridge.claim(token)
        sealed = self.cipher.encrypt(access.encode())
        saved = await self.store._one("UPDATE bank_pending SET access_sealed=%s WHERE subject=%s AND claim_id=%s "
                                      "RETURNING claim_id", (sealed, subject, claim_id))
        if saved is None:
            raise ProviderUnavailable("The setup changed during the claim. Check the connection in SimpleFIN Bridge.")
        return await self.resume(subject)

    async def pending(self, subject):
        return await self.store._one("SELECT claim_id, access_sealed, choices_sealed FROM bank_pending WHERE subject=%s", (subject,))

    async def reserve_read(self, subject, scope):
        row = await self.store._one("INSERT INTO bank_reads(subject, scope, day, used) "
                                    "VALUES (%s,%s,(now() AT TIME ZONE 'UTC')::date,1) "
                                    "ON CONFLICT (subject,scope,day) DO UPDATE SET used=bank_reads.used+1 "
                                    "WHERE bank_reads.used<24 RETURNING used", (subject, scope))
        if row is None:
            raise ProviderUnavailable("Today's SimpleFIN read budget has been used.")

    async def resume(self, subject):
        state = await self.pending(subject)
        if not state:
            raise ProviderUnavailable("No pending setup. Enter a new Setup Token.")
        if not state["access_sealed"]:
            raise ProviderUnavailable("Claim outcome is uncertain. Check or revoke the connection in SimpleFIN Bridge before discarding this setup.")
        if state["choices_sealed"]:
            choices = json.loads(self.cipher.decrypt(bytes(state["choices_sealed"])))
            return [{"id": key, "label": item[2]} for key, item in choices.items()]
        access = self.cipher.decrypt(bytes(state["access_sealed"])).decode()
        await self.reserve_read(subject, self.indexed("list-read", access))
        rows = await self.bridge.accounts(access)
        choices = {}
        for record in rows:
            keys = [record.get(key) for key in ("id", "conn_id", "name")] if isinstance(record, dict) else []
            if len(keys) == 3 and all(isinstance(field, str) and 1 <= len(field) <= 128 for field in keys):
                account, connection, name = keys
                choices[secrets.token_urlsafe(12)] = (account, connection, name)
        if not choices:
            raise ProviderUnavailable("No eligible accounts.")
        sealed = self.cipher.encrypt(json.dumps(choices).encode())
        saved = await self.store._one("UPDATE bank_pending SET choices_sealed=%s WHERE subject=%s AND claim_id=%s "
                                      "AND choices_sealed IS NULL RETURNING claim_id", (sealed, subject, state["claim_id"]))
        if saved is None:
            return await self.resume(subject)
        return [{"id": key, "label": item[2]} for key, item in choices.items()]

    async def link(self, subject, number, choice, alias):
        number = _number(number)
        if not number:
            raise ProviderUnavailable("Enrollment expired or was invalid.")
        try:
            async with self.store.pool.connection() as db:
                state = await (await db.execute("SELECT access_sealed, choices_sealed FROM bank_pending "
                                                "WHERE subject=%s FOR UPDATE", (subject,))).fetchone()
                if not state or not state["access_sealed"] or not state["choices_sealed"]:
                    raise ProviderUnavailable("Resume the pending enrollment first.")
                choices = json.loads(self.cipher.decrypt(bytes(state["choices_sealed"])))
                if choice not in choices:
                    raise ProviderUnavailable("Invalid account selection.")
                account, connection, _ = choices[choice]
                access = self.cipher.decrypt(bytes(state["access_sealed"])).decode()
                sealed = self.cipher.encrypt(json.dumps({"access": access, "account": account, "connection": connection}).encode())
                await db.execute("INSERT INTO bank_links(subject, phone_key, alias, sealed) VALUES (%s,%s,%s,%s) "
                                 "ON CONFLICT (subject) DO UPDATE SET phone_key=EXCLUDED.phone_key,"
                                 "alias=EXCLUDED.alias,sealed=EXCLUDED.sealed,changed_at=now()",
                                 (subject, self.indexed("phone", number), alias, sealed))
                await self.store._log(db, "bank_link", subject)
                await db.execute("DELETE FROM bank_pending WHERE subject=%s", (subject,))
        except UniqueViolation:
            raise ProviderUnavailable("This line already has an enrollment.") from None

    async def discard(self, subject):
        row = await self.store._one("DELETE FROM bank_pending WHERE subject=%s AND (access_sealed IS NOT NULL OR created_at<now()-interval '2 minutes') "
                                    "RETURNING claim_id", (subject,))
        if row is None:
            raise ProviderUnavailable("Wait two minutes after beginning setup before discarding it.")

    async def unlink(self, subject):
        async with self.store.pool.connection() as db:
            await db.execute("DELETE FROM bank_links WHERE subject=%s", (subject,))
            await self.store._log(db, "bank_unlink", subject)

    async def call(self, caller, link, say, *, connected=False, expected_subject=None):
        if not (link.display_active if connected else await link.connect()):
            if connected:
                await link.release()
            await say("Private balance service unavailable.")
            return
        number = _number(caller)
        # The caller ID is only a lookup hint, never proof of identity. Render the same challenge
        # and input flow for an unlinked or ineligible caller, but do not register a real approval.
        enrolled = await self.store._one("SELECT subject, alias, sealed FROM bank_links WHERE phone_key=%s",
                                         (self.indexed("phone", number or "unavailable"),))
        if number is None or (enrolled and expected_subject is not None and enrolled["subject"] != expected_subject):
            enrolled = None
        call = secrets.token_urlsafe(24)
        registered = False
        if enrolled:
            try:
                challenge = self.approvals.new(enrolled["subject"], call)
                registered = True
            except ValueError:
                challenge = self.approvals.challenge()
        else:
            challenge = self.approvals.challenge()
        approved = False
        try:
            await link.transfer(wire.screen(["PRIVATE BALANCE", f"Approval {challenge}", "Confirm on web", "Enter approval code"], []),
                                open_input=True)
            async with asyncio.timeout(120):
                for _ in range(3):
                    code = "".join([await link.selection(60) for _ in range(8)])
                    if registered and self.approvals.check(challenge, call, code):
                        approved = True
                        break
        except TimeoutError:
            pass
        finally:
            if registered:
                self.approvals.pending.pop(challenge, None)
        if approved and enrolled:
            deadline = asyncio.get_running_loop().time() + 300
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
                await link.transfer(wire.screen(rows, [("Exit", "0"), ("Trans", "1")]), open_input=True)
                try:
                    if await link.selection(60) == "1":
                        from .balances import show_transactions
                        await show_transactions(link, await self._account_data(enrolled, transactions=True),
                                                authorize=lambda: self._active(enrolled), deadline=deadline)
                except TimeoutError:
                    pass
            except (ProviderUnavailable, InvalidToken):
                await link.transfer(wire.screen(["BALANCE UNAVAILABLE"], []))
        await link.transfer(wire.screen(["GOODBYE"], []))
        await link.release()

    async def _balance(self, enrolled, *, inspection=False):
        now = time.monotonic()
        if any(subject == enrolled["subject"] and tick > now - 60 for subject, tick in self.recent):
            raise ProviderUnavailable("Balance unavailable.")
        self.recent.append((enrolled["subject"], now))
        return await self._account_data(enrolled, inspection=inspection)

    async def _active(self, enrolled):
        record = await self.store._one("SELECT sealed FROM bank_links WHERE subject=%s", (enrolled["subject"],))
        if record is None or record["sealed"] != enrolled["sealed"]:
            raise Unlinked("Balance unavailable.")
        return record

    async def _account_data(self, enrolled, *, transactions=False, inspection=False):
        record = await self._active(enrolled)
        access = json.loads(self.cipher.decrypt(bytes(record["sealed"])))
        scope = self.indexed("account-read", access["access"] + "\0" + access["connection"] + "\0" + access["account"])
        await self.reserve_read(enrolled["subject"], scope)
        if transactions:
            balance = await self.bridge.transactions(access["access"], access["connection"], access["account"])
        else:
            balance = await self.bridge.balance(access["access"], access["connection"], access["account"], require_current=not inspection)
        await self._active(enrolled)
        return balance

    async def verify(self, subject):
        enrolled = await self.store._one("SELECT subject, sealed FROM bank_links WHERE subject=%s", (subject,))
        if not enrolled:
            raise ProviderUnavailable("Link an account first.")
        balance = await self._balance(enrolled, inspection=True)
        transactions = await self._account_data(enrolled, transactions=True)
        return {"currency": balance.currency, "as_of": balance.as_of.isoformat(),
                "posted": str(balance.posted), "available": str(balance.available) if balance.available is not None else None,
                "freshness": balance.freshness(), "transactions_shown": len(transactions)}


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
    if service and not request.app.state.oidc and os.getenv("ADSI_LOCAL_BANK_ENROLLMENT") == "1":
        principal(request)
        subject = service.local_subject()
    else:
        subject = request.session.get("subject") if request.app.state.oidc else None
    if not service or not subject:
        raise HTTPException(401, "Sign in to access enrollment.")
    return service, subject


@router.get("/bank", response_class=HTMLResponse)
async def bank_page():
    return HTMLResponse(FORM.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})


@router.get("/auth/login")
async def auth_login(request: Request, console: bool = False):
    if not request.app.state.oidc:
        return RedirectResponse("/")
    oauth, origin, _ = request.app.state.oidc
    request.session["console_intent"] = console
    return await oauth.subscriber.authorize_redirect(request, origin + "/auth/callback")


@router.get("/auth/callback")
async def auth_callback(request: Request):
    if not request.app.state.oidc:
        raise HTTPException(404, "Identity provider unavailable.")
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
    pending = await service.pending(subject)
    return JSONResponse({"linked": record is not None, "alias": record["alias"] if record else None,
            "pending": bool(pending), "claimed": bool(pending and pending["access_sealed"]),
            "local": not bool(request.app.state.oidc),
            "call_approval": bool(request.app.state.oidc or request.app.state.local_private)}, headers={"Cache-Control": "no-store"})


@router.post("/api/v1/enrollment/bank-link")
async def claim(data: Token, request: Request):
    service, subject = context(request, write=True)
    return JSONResponse(await service.claim(subject, data.token.strip()), headers={"Cache-Control": "no-store"})


@router.post("/api/v1/enrollment/resume")
async def resume(request: Request):
    service, subject = context(request, write=True)
    return JSONResponse(await service.resume(subject), headers={"Cache-Control": "no-store"})


@router.delete("/api/v1/enrollment/pending")
async def discard(request: Request):
    service, subject = context(request, write=True)
    await service.discard(subject)
    return {"pending": False}


@router.post("/api/v1/enrollment/verify")
async def verify(request: Request):
    service, subject = context(request, write=True)
    return JSONResponse(await service.verify(subject), headers={"Cache-Control": "no-store"})


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
    if not (request.app.state.oidc or request.app.state.local_private):
        raise HTTPException(403, "Private calling is disabled.")
    code = service.approvals.approve(data.challenge, subject)
    if code is None:
        raise HTTPException(404, "No approval is available.")
    return JSONResponse({"code": code}, headers={"Cache-Control": "no-store"})
