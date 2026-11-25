"""Read-only SimpleFIN adapter and call-bound approval primitives."""

import base64
import binascii
import hashlib
import hmac
import re
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import unquote, urlsplit

import httpx

from . import wire
from .link import Link


BRIDGE_HOSTS = frozenset(("bridge.simplefin.org", "beta-bridge.simplefin.org"))


class ProviderUnavailable(RuntimeError):
    pass


def _url(value, claim):
    try:
        result = urlsplit(value)
        valid = result.scheme == "https" and result.hostname in BRIDGE_HOSTS and result.port in (None, 443)
    except ValueError as error:
        raise ProviderUnavailable("Invalid Bridge endpoint.") from error
    if not valid or result.query or result.fragment:
        raise ProviderUnavailable("Invalid Bridge endpoint.")
    if claim:
        if result.username is not None or not re.fullmatch(r"/simplefin/claim/[A-Za-z0-9_-]{1,256}", result.path):
            raise ProviderUnavailable("Invalid Bridge claim endpoint.")
    elif not (result.path.strip("/") == "simplefin" and result.username and result.password):
        raise ProviderUnavailable("Invalid Bridge access endpoint.")
    return result


@dataclass(frozen=True)
class Balance:
    currency: str
    posted: Decimal
    available: Decimal | None
    as_of: datetime

    def freshness(self, now=None):
        age = (now or datetime.now(UTC)) - self.as_of
        if age < timedelta(0):
            return "future"
        return "current" if age <= timedelta(hours=48) else "stale"


@dataclass(frozen=True)
class Transaction:
    posted: datetime
    amount: Decimal
    description: str
    currency: str


def _decimal(value):
    if not isinstance(value, str) or not re.fullmatch(r"-?\d{1,15}(\.\d{1,8})?", value):
        raise ValueError("invalid decimal amount")
    return Decimal(value)


class SimpleFIN:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    @staticmethod
    def claim_url(token: str) -> str:
        if not 1 <= len(token) <= 2048:
            raise ProviderUnavailable("Invalid setup token.")
        try:
            claim_url = base64.b64decode(token, validate=True).decode("ascii")
        except (UnicodeError, binascii.Error) as error:
            raise ProviderUnavailable("Invalid setup token.") from error
        _url(claim_url, claim=True)
        return claim_url

    async def claim(self, token: str) -> str:
        claim_url = self.claim_url(token)
        try:
            response = await self.client.post(claim_url, content=b"", follow_redirects=False, timeout=20)
            if response.status_code == 403:
                raise ProviderUnavailable("Setup token rejected. Check or revoke it in SimpleFIN Bridge and generate a new token.")
            if response.status_code != 200 or len(response.content) > 2048:
                raise ProviderUnavailable("Claim result unavailable. Check or revoke the connection in SimpleFIN Bridge before starting again.")
        except httpx.HTTPError:
            # A timed-out claim can still have consumed its token.
            raise ProviderUnavailable("Claim result unavailable. Check or revoke the connection in SimpleFIN Bridge before starting again.") from None
        access_url = response.text.strip()
        try:
            _url(access_url, claim=False)
        except ProviderUnavailable:
            raise ProviderUnavailable("Claim returned an unrecognized Access URL. Check the connection in SimpleFIN Bridge.") from None
        return access_url

    async def balance(self, access_url: str, connection: str, account: str, now: datetime | None = None,
                      *, require_current: bool = True) -> Balance:
        now = now or datetime.now(UTC)
        try:
            accounts = await self.accounts(access_url, account)
            matches = [record for record in accounts
                       if record.get("id") == account and record.get("conn_id") == connection]
            if len(matches) != 1:
                raise ProviderUnavailable("Balance unavailable.")
            record = matches[0]
            if not re.fullmatch(r"[A-Z]{3}", record["currency"]) or type(record["balance-date"]) is not int:
                raise ValueError("invalid balance metadata")
            observed = datetime.fromtimestamp(record["balance-date"], UTC)
            result = Balance(record["currency"], _decimal(record["balance"]),
                             _decimal(record["available-balance"]) if record.get("available-balance") is not None else None, observed)
            if require_current and result.freshness(now) != "current":
                raise ProviderUnavailable("Balance unavailable.")
            return result
        except (httpx.HTTPError, KeyError, TypeError, ValueError, InvalidOperation, OverflowError, AttributeError):
            raise ProviderUnavailable("Balance unavailable.") from None

    async def transactions(self, access_url, connection, account, now=None):
        now = now or datetime.now(UTC)
        start = now - timedelta(days=30)
        try:
            rows = await self.accounts(access_url, account, start=start, end=now)
            matches = [row for row in rows if row.get("id") == account and row.get("conn_id") == connection]
            if len(matches) != 1:
                raise ProviderUnavailable("Transactions unavailable.")
            row = matches[0]
            currency = row["currency"]
            if not re.fullmatch(r"[A-Z]{3}", currency):
                raise ValueError
            records = row.get("transactions", [])
            if not isinstance(records, list) or len(records) > 2000:
                raise ValueError
            result = []
            for record in records:
                if record.get("pending") or not record.get("posted"):
                    continue
                posted = datetime.fromtimestamp(record["posted"], UTC)
                if start <= posted <= now:
                    description = " ".join(str(record.get("description") or "Transaction").split())[:80]
                    result.append(Transaction(posted, _decimal(record["amount"]), description, currency))
            return sorted(result, key=lambda transaction: transaction.posted, reverse=True)[:10]
        except (httpx.HTTPError, KeyError, TypeError, ValueError, InvalidOperation, OverflowError, AttributeError):
            raise ProviderUnavailable("Transactions unavailable.") from None

    async def accounts(self, access_url, account=None, *, start=None, end=None):
        url = _url(access_url, claim=False)
        params = {"version": "2", "balances-only": "1"}
        if start is not None and end is not None:
            params.pop("balances-only")
            params.update({"start-date": str(int(start.timestamp())), "end-date": str(int(end.timestamp()))})
        if account is not None:
            params["account"] = account
        try:
            response = await self.client.get(f"https://{url.hostname}/simplefin/accounts",
                                             auth=(unquote(url.username), unquote(url.password)),
                                             params=params, follow_redirects=False, timeout=15)
            if response.status_code == 403:
                raise ProviderUnavailable("SimpleFIN access was rejected or revoked. Check the connection in Bridge.")
            if response.status_code == 402:
                raise ProviderUnavailable("SimpleFIN reports payment is required.")
            if response.status_code != 200 or len(response.content) > 300_000:
                raise ProviderUnavailable("Balance unavailable.")
            document = response.json()
            accounts = document["accounts"]
            if document.get("errlist") or document.get("errors"):
                errors = document.get("errlist") or []
                codes = {error.get("code") for error in errors if isinstance(error, dict) and isinstance(error.get("code"), str)}
                if "con.auth" in codes or "gen.auth" in codes:
                    raise ProviderUnavailable("SimpleFIN reports an authentication problem. Check the connection in Bridge.")
                if "act.missingdata" in codes or "act.failed" in codes:
                    raise ProviderUnavailable("SimpleFIN reports incomplete or unavailable account data. Try again later.")
                raise ProviderUnavailable("SimpleFIN reports a provider error. Check Bridge for details.")
            if not isinstance(accounts, list) or len(accounts) > 128:
                raise ProviderUnavailable("Balance unavailable.")
            return accounts
        except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError):
            raise ProviderUnavailable("Balance unavailable.") from None


@dataclass
class Approval:
    subject: str
    call: str
    expires: float
    digest: bytes | None = None
    attempts: int = 0


class Approvals:
    def __init__(self, key: bytes, clock=time.monotonic):
        self.key = key
        self.clock = clock
        self.pending: dict[str, Approval] = {}

    def _digest(self, challenge, entry, code):
        value = "\0".join((challenge, entry.subject, entry.call, code)).encode()
        return hmac.digest(self.key, value, hashlib.sha256)

    def new(self, subject: str, call: str) -> str:
        now = self.clock()
        self.pending = {key: entry for key, entry in self.pending.items() if entry.expires > now}
        if len(self.pending) >= 128 or any(entry.subject == subject for entry in self.pending.values()):
            raise ValueError("Approval already pending.")
        while True:
            challenge = f"{secrets.randbelow(10**8):08d}"
            if challenge not in self.pending:
                break
        self.pending[challenge] = Approval(subject, call, now + 120)
        return challenge

    def approve(self, challenge, subject):
        entry = self.pending.get(challenge)
        if entry is None or entry.subject != subject or entry.expires <= self.clock() or entry.digest is not None:
            return None
        code = f"{secrets.randbelow(10**8):08d}"
        entry.digest = self._digest(challenge, entry, code)
        return code

    def check(self, challenge, call, code):
        entry = self.pending.get(challenge)
        if entry is None or entry.call != call or entry.expires <= self.clock():
            return False
        entry.attempts += 1
        verified = entry.digest is not None and hmac.compare_digest(entry.digest, self._digest(challenge, entry, code))
        if verified or entry.attempts >= 3:
            self.pending.pop(challenge)
        return verified


async def show_transactions(link, transactions, *, authorize=None, deadline=None):
    import asyncio
    from .graph import handset_text
    def remaining():
        return 30 if deadline is None else min(30, deadline - asyncio.get_running_loop().time())
    if not transactions:
        if authorize:
            await authorize()
        if remaining() <= 0:
            return
        await link.transfer(wire.screen(["NO RECENT ACTIVITY", "0 Exit"], [("Exit", "0")]), open_input=True)
        try:
            await link.selection(max(0, remaining()))
        except TimeoutError:
            pass
        return
    for index, record in enumerate(transactions):
        if authorize:
            await authorize()
        if remaining() <= 0:
            return
        amount = f"{record.currency} {record.amount}"
        lines = [f"ACTIVITY {index + 1}/{len(transactions)}", record.posted.strftime("%d %b %Y"),
                 amount if len(amount) <= 20 else "Amount unavailable", handset_text(record.description)[:20] or "Transaction"]
        keys = [("Exit", "0")]
        if index + 1 < len(transactions):
            keys.append(("Next", "9"))
        await link.transfer(wire.screen(lines, keys), open_input=True)
        try:
            if await link.selection(max(0, remaining())) != "9":
                return
        except TimeoutError:
            return


async def demo_balance(link: Link, say, access_code: str, *, connected=False, transactions=False):
    if not re.fullmatch(r"[0-9]{8}", access_code):
        if connected:
            await link.release()
        await say("Balance demonstration unavailable.")
        return
    display = link.display_active if connected else await link.connect()
    if display:
        await link.transfer(wire.screen(["DEMO BALANCE", "Enter lab code"], []), open_input=True)
    else:
        link.open_voice_input()
        await say("Demo balance. Enter the eight-digit lab code.")
    verified = False
    for _ in range(3):
        digits = []
        try:
            for _ in range(8):
                digit = await link.selection(8)
                if not digit.isdecimal():
                    break
                digits.append(digit)
        except TimeoutError:
            break
        if hmac.compare_digest("".join(digits), access_code):
            verified = True
            break
    if display and verified:
        keys = [("Exit", "0"), ("Trans", "1")] if transactions else [("Exit", "0")]
        await link.transfer(wire.screen(["DEMO BALANCE", "CAD 1234.56", "As of 07 Feb 2026", "1 Trans  0 Exit" if transactions else "0 Exit"], keys),
                            open_input=True)
        try:
            if await link.selection(20) == "1" and transactions:
                await show_transactions(link, [
                    Transaction(datetime(2026, 2, 7, tzinfo=UTC), Decimal("-12.34"), "Demo groceries", "CAD"),
                    Transaction(datetime(2026, 2, 6, tzinfo=UTC), Decimal("120.00"), "Demo deposit", "CAD"),
                ])
        except TimeoutError:
            pass
        await link.transfer(wire.screen(["GOODBYE"], []))
        await link.release()
    else:
        await link.release()
        await say("Demo balance. One thousand two hundred thirty-four dollars and fifty-six cents."
                  if verified else "Balance demonstration unavailable.")
