"""Public information adapters with curated input and explicit provenance."""

import asyncio
import json
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from defusedxml import ElementTree

from . import directory, flights, graph, livefeeds, wire
from .assistant import InformationDesk
from .link import Link
from .regional import Regional


DATAMART = "https://dd.weather.gc.ca/today/citypage_weather"
ATLANTIC_ZONES = {"America/St_Johns", "America/Halifax", "America/Moncton", "America/Goose_Bay"}
DEMO_SITE = {"place": "Demo Harbour", "province": "NL", "code": "demo", "zone": "America/St_Johns"}
FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures"
if not FIXTURE_ROOT.exists():
    FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures"


def prefix(number: str | None) -> str | None:
    if not number or not re.fullmatch(r"\+?1?[2-9]\d{2}[2-9]\d{6}", number):
        return None
    return number[-10:-4]


def fixture(operation, args, fault=None):
    if fault == "unavailable":
        return None
    if operation.startswith("airport."):
        return flights.fixture(operation, args.get("airport", "YYT"))
    if operation == "directory.lookup":
        return directory.lookup({}, args.get("number", "selected"))
    if operation == "weather.current":
        case = 1 if fault == "stale" else 0
        with (FIXTURE_ROOT / "providers/weather.json").open(encoding="utf-8") as source:
            result = json.load(source)["responses"][case]
        return {**result["value"], "source": result["source"]}
    results = {
        "weather.forecast": {"displayTitle": "DEMO FORECAST", "place": "Demo Harbour",
                             "forecast": "Cloudy in the evening", "source": "Fixture Weather"},
        "news.headlines": {"displayTitle": "DEMO HEADLINES", "headline": "Harbour opens new reading room",
                           "localTime": "07 Feb 2026 10:50", "source": "Fixture News"},
        "market.quote": {"displayTitle": "DEMO MARKET", "symbol": "DEMO", "priceText": "CAD 42.75",
                         "localTime": "06 Feb 2026 16:00", "delay": "End of day", "source": "Fixture Quotes"},
        "lottery.draw": {"displayTitle": "DEMO DRAW", "drawDate": "07 Feb 2026",
                         "game": "Atlantic demo", "numbers": "04 12 20 29 37 43", "bonus": "Bonus 08",
                         "source": "Fixture Draws"},
        "assistant.answer": {"displayTitle": "INFO DESK", "answer": "ADSI sends screens and softkeys over a phone call.",
                             "source": "CoinLine glossary"},
    }
    return results.get(operation)


def check_config(config: dict) -> None:
    if set(config) - {"sites", "prefixes", "manual", "assistant", "feeds", "regional", "flights", "directory"}:
        raise ValueError("Unknown provider configuration field.")
    if type(config.get("flights", False)) is not bool:
        raise ValueError("Flights configuration is a boolean.")
    if "directory" in config:
        directory.validate(config["directory"])
    if type(config.get("regional", True)) is not bool:
        raise ValueError("Regional configuration is a boolean.")
    sites = config.get("sites", {})
    if not isinstance(sites, dict) or len(sites) > 30:
        raise ValueError("Configure up to 30 Atlantic weather sites.")
    for key, site in sites.items():
        if not re.fullmatch(r"[a-z0-9-]{1,32}", key) or set(site) != {"place", "province", "code", "zone"}:
            raise ValueError("Each weather site needs a label, province, code and time zone.")
        if site["province"] not in ("NL", "NB", "NS", "PE") or site["zone"] not in ATLANTIC_ZONES:
            raise ValueError("Choose an Atlantic province and time zone.")
        if not (re.fullmatch(r"s\d{7}", site["code"]) and 1 <= len(site["place"]) <= 40):
            raise ValueError("Use a Datamart site code and a short place label.")
    prefixes = config.get("prefixes", {})
    if not isinstance(prefixes, dict) or len(prefixes) > 10000:
        raise ValueError("Invalid prefix catalogue.")
    for number, site in prefixes.items():
        if not re.fullmatch(r"[2-9]\d{2}[2-9]\d{2}", number) or site not in sites:
            raise ValueError("Numbering entries must map a six-digit assignment to a configured site.")
    manual = config.get("manual", {})
    if not isinstance(manual, dict) or set(manual) - {"news.headlines", "market.quote", "lottery.draw"}:
        raise ValueError("Unsupported manual feed.")
    for operation, entries in manual.items():
        if not isinstance(entries, dict) or len(entries) > 80:
            raise ValueError("Invalid manual feed catalogue.")
        for value in entries.values():
            required = graph.OUTPUTS[operation] - {"displayTitle"}
            if (not isinstance(value, dict) or set(value) != required | {"dataTime"} or
                    any(not isinstance(text, str) or not 1 <= len(text) <= 160 for text in value.values())):
                raise ValueError("Each manual item needs its source fields, time and display values.")
            timestamp = datetime.fromisoformat(value["dataTime"])
            if timestamp.tzinfo is None:
                raise ValueError("Manual data requires a time zone.")
    if not isinstance(config.get("assistant", False), bool):
        raise ValueError("Assistant configuration is a boolean.")
    feeds = config.get("feeds", {})
    if not isinstance(feeds, dict) or set(feeds) - set(livefeeds.SOURCES) or any(
        type(value) is not bool for value in feeds.values()
    ):
        raise ValueError("Use boolean activation for the supported feeds.")


def _xml_time(element):
    if element is None:
        return None
    raw = element.findtext("timeStamp")
    if raw is None:
        return None
    try:
        return datetime.strptime(raw, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
    except ValueError:
        return None


class Providers:
    def __init__(self):
        self.client = httpx.AsyncClient(follow_redirects=False, trust_env=False, timeout=1.5)
        self.desk = InformationDesk(self.client)
        self.flights = flights.Flights(self.client)
        self.weather_cache = {}
        self.weather_refresh = asyncio.Lock()
        self.regional = Regional() if os.getenv("ADSI_REGIONAL_ENABLE") == "1" else None

    def regional_enabled(self, config):
        return self.regional is not None and config.get("regional", True)

    async def _weather(self, site):
        now = datetime.now(UTC)
        key = (site["province"], site["code"])
        cached = self.weather_cache.get(key)
        if cached and now - cached[0] < timedelta(minutes=10):
            return cached[1]
        async with self.weather_refresh:
            cached = self.weather_cache.get(key)
            if cached and now - cached[0] < timedelta(minutes=10):
                return cached[1]
            try:
                for hour in (now.hour, (now.hour - 1) % 24):
                    folder = f"{DATAMART}/{site['province']}/{hour:02d}/"
                    index = await self.client.get(folder)
                    if index.status_code != 200 or len(index.content) > 2_000_000:
                        continue
                    pattern = rf'\b\d{{8}}T\d{{6}}\.\d{{3}}Z_MSC_CitypageWeather_{site["code"]}_en\.xml\b'
                    names = re.findall(pattern, index.text)
                    if names:
                        response = await self.client.get(folder + max(names))
                        response.raise_for_status()
                        if len(response.content) > 300_000:
                            break
                        document = ElementTree.fromstring(response.content)
                        self.weather_cache[key] = (now, document)
                        return document
            except (httpx.HTTPError, ValueError, ElementTree.ParseError):
                pass
            return cached[1] if cached else None

    async def lookup(self, config, operation, args, province=None):
        required, _ = graph.ARGUMENTS[operation]
        key = args[next(iter(required))]
        if operation.startswith("airport."):
            return await self.flights.lookup(operation, key, config.get("flights", False))
        if operation == "directory.lookup":
            return directory.lookup(config, key)
        if operation.startswith("weather.") and key in config.get("sites", {}):
            return await self._weather_result(operation, config["sites"][key])
        if operation == "assistant.answer":
            return await self.desk.answer(key) if config.get("assistant") else None
        if self.regional_enabled(config):
            try:
                if operation.startswith("weather.") and "|" in key:
                    return await self.regional.weather(operation, key)
                if operation == "news.headlines":
                    if key == "local":
                        key = f"local:{province}" if province else "canada"
                    if key == "atlantic":
                        key = "local:NL"
                    record = await self.regional.news(key)
                elif operation == "market.quote":
                    record = await self.regional.quote(key)
                elif operation == "lottery.draw":
                    record = await self.regional.lottery(key, province, args.get("draw_date"))
                else:
                    record = None
                if record:
                    return self._public_record(operation, record, "LIVE")
            except (KeyError, ValueError, TypeError, IndexError, AttributeError, OverflowError):
                pass
            if operation not in config.get("manual", {}) and not config.get("feeds", {}).get(operation):
                return None
        entries = config.get("manual", {}).get(operation, {})
        if operation == "lottery.draw" and "draw_date" in args:
            key += "/" + args["draw_date"]
        if config.get("feeds", {}).get(operation):
            fetched = await livefeeds.fetch(self.client, operation, key)
            if fetched is not None:
                return self._public_record(operation, fetched, "LIVE")
        if key in entries:
            return self._public_record(operation, entries[key], "MANUAL")
        if config.get("feeds", {}).get(operation):
            return None
        if operation in config.get("manual", {}):
            return None
        return fixture(operation, args)

    @staticmethod
    def _public_record(operation, value, mode):
        needed = (graph.OUTPUTS[operation] - {"displayTitle"}) | {"dataTime"}
        if (not isinstance(value, dict) or set(value) != needed or
                any(not isinstance(text, str) or not 1 <= len(text) <= 160 for text in value.values())):
            return None
        try:
            record = value.copy()
            age = datetime.now(UTC) - datetime.fromisoformat(record.pop("dataTime"))
        except (TypeError, ValueError):
            return None
        if age < timedelta(0):
            return None
        policy = {"news.headlines": (6, 24), "market.quote": (0.5, 24)}
        if operation in policy:
            fresh, maximum = policy[operation]
            if operation == "market.quote" and record["delay"] == "End of day":
                fresh, maximum = 24, 168
            if age > timedelta(hours=maximum):
                return None
            record["displayTitle"] = mode if age <= timedelta(hours=fresh) else f"STALE {mode}"
        else:
            record["displayTitle"] = f"{mode} DRAW"
        return record

    async def _weather_result(self, operation, site):
        document = await self._weather(site)
        if document is None:
            return None
        now = datetime.now(UTC)
        if operation == "weather.current":
            current = document.find("currentConditions")
            if current is None:
                return None
            observed = _xml_time(current.find("dateTime[@name='observation'][@zone='UTC']"))
            temp = current.findtext("temperature")
            if observed is None or not temp or not re.fullmatch(r"-?\d{1,3}(\.\d{1,2})?", temp):
                return None
            age = now - observed
            if not timedelta(0) <= age <= timedelta(hours=6):
                return None
            title = "ECCC WEATHER" if age <= timedelta(hours=2) else "STALE ECCC WEATHER"
            return {"place": site["place"], "temperatureText": f"{temp} C", "displayTitle": title,
                    "localTime": observed.astimezone(ZoneInfo(site["zone"])).strftime("%H:%M %Z"), "source": "ECCC"}
        group = document.find("forecastGroup")
        if group is None:
            return None
        issued = _xml_time(group.find("dateTime[@name='forecastIssue'][@zone='UTC']"))
        summary = group.findtext("forecast/textSummary")
        if issued is None or not summary or not timedelta(0) <= now - issued <= timedelta(hours=24):
            return None
        return {"place": site["place"], "forecast": summary[:160], "source": "ECCC",
                "displayTitle": "ECCC FORECAST" if now - issued <= timedelta(hours=6) else "STALE ECCC FORECAST"}

    async def refresh(self, config_source):
        while True:
            try:
                config = await config_source()
                if self.regional_enabled(config["value"]):
                    await self.regional.numbering()
                for site in config["value"].get("sites", {}).values():
                    try:
                        async with asyncio.timeout(5):
                            await self._weather(site)
                    except TimeoutError:
                        pass
            except (TimeoutError, RuntimeError):
                pass
            await asyncio.sleep(60)


async def choose_site(config, caller: str | None, link: Link, say) -> str:
    sites = config.get("sites", {})
    if not sites:
        return "demo-harbour"
    suggested = config.get("prefixes", {}).get(prefix(caller))

    async def choose(title, entries):
        lines = [graph.handset_text(title)[:20]] + [graph.handset_text(f"{index} {name}")[:20]
                                                   for index, name in enumerate(entries, 1)]
        if link.display_active:
            await link.transfer(wire.screen(lines, [(graph.handset_text(label)[:7], str(index))
                                                     for index, label in enumerate(entries, 1)]), open_input=True)
        else:
            await say(title + ". " + ". ".join(f"Press {index} for {name}" for index, name in enumerate(entries, 1)))
            link.open_voice_input()
        return await link.selection()

    if suggested in sites:
        if await choose(f"Weather for {sites[suggested]['place']}?", ["Yes", "Other city"]) == "1":
            return suggested
    names = sorted(sites, key=lambda key: sites[key]["place"])
    for start in range(0, len(names), 2):
        batch = names[start:start + 2]
        entries = [sites[key]["place"] for key in batch]
        if start + 2 < len(names):
            entries.append("More")
        digit = await choose("Choose weather city", entries)
        if any(digit == str(index) for index in range(1, len(batch) + 1)):
            return batch[int(digit) - 1]
        if digit != "3":
            break
    return ""
