"""Application entry point."""

import asyncio
import os
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import fdm, graph
from .api import api, login
from .asterisk import Gateway
from .balances import ProviderUnavailable, demo_balance
from .link import lab_call
from .private import PrivateBalances, configure
from .providers import Providers, choose_site
from .store import DEMO_REVISION, Store, StoreError


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.sessions = {}
    app.state.simulations = {}
    app.state.failures = deque()
    app.state.db = Store() if os.getenv("ADSI_DB_HOST") else None
    app.state.providers = Providers()
    app.state.private = PrivateBalances(app.state.db, app.state.providers.client, app.state.oidc[2]) if (
        app.state.oidc and app.state.db) else None

    async def handle_call(route, caller, link, say):
        if route == "lab":
            await lab_call(link, say)
            return
        if route == "balance-demo":
            await demo_balance(link, say, os.getenv("ADSI_DEMO_PIN", ""))
            return
        if route == "private-balance":
            private = app.state.private
            if private and os.getenv("ADSI_PRIVATE_BALANCES") == "1":
                await private.call(caller, link, say)
            else:
                await say("Private balance service unavailable.")
            return
        store = app.state.db
        if route == "resident-lab":
            requested = await store.take_download() if store and os.getenv("ADSI_FDM_ENABLE") == "1" else None
            if not requested or not await fdm.install(link, requested["text"], requested["version"]):
                await say("No resident download is available.")
            return
        revision = await store.route(route) if store else None
        if revision is None:
            await say("This application is unavailable.")
            return
        config = (await store.setting("providers"))["value"]
        location = None
        assistant_used = False
        document = revision["graph"]
        if revision["id"] == DEMO_REVISION and not config.get("assistant"):
            welcome = document["nodes"][0]
            welcome["choices"] = [choice for choice in welcome["choices"] if choice["digit"] != "5"]
            welcome["lines"][-1] = "0 Exit"
            welcome["prompt"] = "CoinLine InfoLine. Press one for news, two for weather, three for stocks, four for lottery, or zero to exit."
            document["nodes"] = [node for node in document["nodes"] if node["id"] not in ("help", "help-result")]

        async def prepare(operation, arguments):
            nonlocal location, assistant_used
            if operation.startswith("weather.") and arguments.get("site") == "selected":
                if location is None:
                    location = await choose_site(config, caller, link, say)
                if not location:
                    return None
                return {"site": location}
            if operation == "assistant.answer":
                if assistant_used:
                    return None
                assistant_used = True
            return arguments

        async def lookup(operation, arguments):
            return await app.state.providers.lookup(config, operation, arguments)

        await graph.run_call(document, lookup, link, say, prepare)

    origin = os.getenv("ADSI_ARI_URL")
    task = None
    refresh_task = None
    app.state.gateway = None
    try:
        if app.state.db:
            await app.state.db.pool.open(wait=True, timeout=5)
            refresh_task = asyncio.create_task(app.state.providers.refresh(lambda: app.state.db.setting("providers")))
        if origin:
            app.state.gateway = Gateway(origin, os.environ["ADSI_ARI_PASSWORD"], handle_call)
            task = asyncio.create_task(app.state.gateway.serve())
        yield
    finally:
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if refresh_task:
            refresh_task.cancel()
            await asyncio.gather(refresh_task, return_exceptions=True)
        await app.state.providers.client.aclose()
        if app.state.db:
            await app.state.db.pool.close()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.state.oidc = configure(app)
app.include_router(login)
app.include_router(api)


@app.exception_handler(StoreError)
async def storage_error(request: Request, error: StoreError):
    return JSONResponse({"detail": str(error)}, status_code=error.status)


@app.exception_handler(ProviderUnavailable)
async def provider_error(request: Request, error: ProviderUnavailable):
    return JSONResponse({"detail": str(error)}, status_code=503, headers={"Cache-Control": "no-store"})


@app.get("/health")
async def health():
    gateway = app.state.gateway
    ready = gateway is None or gateway.connected
    return JSONResponse({"ready": ready}, status_code=200 if ready else 503)


@app.websocket("/internal/media")
async def media(socket: WebSocket):
    gateway = app.state.gateway
    if gateway is None:
        await socket.close(code=1008)
        return
    await gateway.accept(socket)


web = Path(__file__).resolve().parents[1] / "web"
if (web / "index.html").is_file():
    app.mount("/", StaticFiles(directory=web, html=True), name="web")
