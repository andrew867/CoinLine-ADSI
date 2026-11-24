"""Canadian public information providers. Only normalized public records are cached."""

import csv
import io
import json
import math
import os
import re
import unicodedata
import zipfile
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from . import graph, livefeeds, wire
from .provider_cache import ProviderCache


ATLANTIC = {"NL", "NS", "NB", "PE"}
CAPITALS = {"NL": "St. John's", "NS": "Halifax", "NB": "Fredericton", "PE": "Charlottetown",
            "QC": "Quebec", "ON": "Toronto", "MB": "Winnipeg", "SK": "Regina", "AB": "Edmonton",
            "BC": "Victoria", "NT": "Yellowknife", "YT": "Whitehorse", "NU": "Iqaluit"}


def load_catalog():
    path = Path(os.getenv("ADSI_REGIONAL_CONFIG") or Path(__file__).with_name("regional.json"))
    return json.loads(path.read_text(encoding="utf-8"))


def normalize(text):
    return "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if c.isalnum())


def parse_numbering(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = [item for item in archive.infolist() if item.filename.lower().endswith(".csv")]
        if len(entries) != 1 or entries[0].file_size > 20_000_000:
            return None
        raw = archive.read(entries[0])
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        content = raw.decode("cp1252")
    result = {}
    for row in csv.DictReader(io.StringIO(content)):
        npa, nxx = row.get("NPA", ""), row.get("CO Code (NXX)", "")
        province, city = row.get("Province", ""), row.get("Exchange Area", "")
        if (row.get("Status", "").casefold() == "in service" and province in CAPITALS and city
                and re.fullmatch(r"[2-9]\d{2}[2-9]\d{2}", npa + nxx)):
            result[npa + nxx] = [province, city]
    return result if len(result) > 1000 else None


def city_coordinates(rows, province, city):
    for row in rows:
        label, separator, region = row["display_name"].rpartition(",")
        if separator and region.strip() == province and normalize(label) == normalize(city):
            latitude, longitude = float(row["lat"]), float(row["lon"])
            if math.isfinite(latitude) and math.isfinite(longitude) and 41 <= latitude <= 84 and -142 <= longitude <= -50:
                return f"{latitude:.3f},{longitude:.3f}"
    return None


def weather_record(document, operation, province, now):
    item = document[0]
    observation = item["observation"]
    if observation["provinceCode"].upper() != province:
        return None
    if operation == "weather.current":
        observed = datetime.fromisoformat(observation["timeStamp"])
        age = now - observed
        temp = observation["temperature"]["metric"]
        if not timedelta(0) <= age <= timedelta(hours=6) or not re.fullmatch(r"-?\d{1,3}(\.\d{1,2})?", temp):
            return None
        return {"displayTitle": "ECCC WEATHER" if age <= timedelta(hours=2) else "STALE ECCC WEATHER",
                "place": observation["observedAt"][:80], "temperatureText": f"{temp} C",
                "localTime": observed.strftime("%d %b %H:%M UTC"), "source": "ECCC"}
    forecast = item["dailyFcst"]
    issued = datetime.fromtimestamp(int(forecast["dailyIssuedTimeEpoch"]), UTC)
    age = now - issued
    if not timedelta(0) <= age <= timedelta(hours=24):
        return None
    return {"displayTitle": "ECCC FORECAST" if age <= timedelta(hours=6) else "STALE ECCC FORECAST",
            "place": item["displayName"][:80], "forecast": forecast["daily"][0]["titleText"][:160], "source": "ECCC"}


def news_record(source, title, published):
    if not isinstance(title, str) or not title.strip() or not isinstance(source, str) or not source.strip():
        return None
    try:
        stamp = datetime.fromisoformat(published)
    except (ValueError, TypeError):
        return None
    if stamp.tzinfo is None:
        return None
    return {"source": source[:80], "headline": title[:160], "dataTime": stamp.isoformat(),
            "localTime": stamp.astimezone(UTC).strftime("%d %b %H:%M UTC")}


def quote_record(symbol, value, currency, stamp, source, delay):
    amount = Decimal(str(value))
    if not amount.is_finite() or amount <= 0 or amount > 10**9 or not re.fullmatch(r"[A-Z]{3}", currency):
        return None
    return {"symbol": symbol, "priceText": f"{currency} {amount:.2f}", "dataTime": stamp.isoformat(),
            "localTime": stamp.astimezone(UTC).strftime("%d %b %H:%M UTC"), "source": source, "delay": delay}


class QuebecResult(HTMLParser):
    def __init__(self):
        super().__init__()
        self.date = ""
        self.numbers = []
        self.bonus = ""
        self.extra = []
        self.gold = []
        self.group = 0
        self.in_numbers = False
        self.in_gold = False
        self.extra_logo = False
        self.capture = None

    def handle_starttag(self, tag, attrs):
        classes = dict(attrs).get("class", "").split()
        if tag == "div" and "numeros" in classes:
            self.group += 1
            self.in_numbers = True
        elif tag == "div" and "numeroBoule" in classes:
            self.in_gold = True
        elif tag == "img" and dict(attrs).get("alt") == "Extra":
            self.extra_logo = True
        elif "date" in classes and not self.date:
            self.capture = "date"
        elif self.in_numbers and "num" in classes:
            if self.group == 1:
                self.capture = "bonus" if "complementaire" in classes else "number"
            elif self.extra_logo:
                self.capture = "extra"
        elif self.in_gold and "num" in classes:
            self.capture = "gold"

    def handle_data(self, data):
        if self.capture == "date":
            self.date = data.strip()
        elif self.capture == "number" and re.fullmatch(r"\d{1,2}", data.strip()):
            self.numbers.append(data.strip())
        elif self.capture == "bonus":
            self.bonus = data.strip()
        elif self.capture == "extra" and re.fullmatch(r"\d", data.strip()):
            self.extra.append(data.strip())
        elif self.capture == "gold" and re.fullmatch(r"\d", data.strip()):
            self.gold.append(data.strip())

    def handle_endtag(self, tag):
        self.capture = None
        if tag == "div":
            self.in_numbers = False
            self.in_gold = False


def gold_ball(digits):
    if isinstance(digits, str) and re.fullmatch(r"\d{10}", digits):
        return f"Gold Ball {digits[:8]}-{digits[8:]}"
    return None


def wclc_results(html, day):
    for fragment in html.split('<div class="pastWinNum">')[1:]:
        stamp = re.search(r'<div class="pastWinNumDate">\s*<h4>\s*([^<]+)', fragment)
        if not stamp or datetime.strptime(stamp[1].strip(), "%A, %B %d, %Y").date() != day:
            continue
        match = re.search(r'<ul class="pastWinNumbers">(.*?)</ul>', fragment, re.S)
        if not match:
            return None
        numbers = re.findall(r'<li class="pastWinNumber">\s*(\d+)\s*</li>', match[1])
        bonus = re.search(r'<li class="pastWinNumberBonus">\s*<span[^>]*>Bonus</span>\s*(\d+)', match[1])
        extra = re.search(r'<div class="pastWinNumExtra">\s*(\d{7})\s*</div>', fragment)
        gold = re.search(r'<div class="pastWinNumGPDNumber">\s*(\d{8}-\d{2})\s*</div>', fragment)
        return numbers, bonus[1] if bonus else None, extra[1] if extra else None, gold[1].replace("-", "") if gold else None
    return None


def dated_draw(spec, payload, day, province):
    kind = spec["type"]
    extra = []
    if kind == "alc":
        if payload.get("game") != spec["product"]:
            return None
        match = re.fullmatch(r"/Date\((\d+)([+-]\d{4})\)/", payload["draw_date"])
        if not match:
            return None
        offset = match[2]
        zone = timezone(timedelta(minutes=(int(offset[1:3]) * 60 + int(offset[3:])) * (1 if offset[0] == "+" else -1)))
        actual = datetime.fromtimestamp(int(match[1]) / 1000, zone).date()
        draw = payload["draw"]
        numbers, bonus = draw["winning_numbers"], draw.get("bonus_number")
        if province in ATLANTIC:
            for field in ("tag", "twist"):
                if re.fullmatch(r"\d{5,12}", str(draw.get(field, ""))):
                    extra.append(f"{field.upper()} {draw[field]}")
        if spec["label"] == "Lotto 6/49":
            draws = payload.get("guaranteed_draws") or []
            if isinstance(draws, list) and len(draws) == 1:
                gold = gold_ball(draws[0].get("winning_number"))
                if gold:
                    extra.append(gold)
        source = "ALC"
    elif kind == "western":
        actual = datetime.strptime(payload["drawDate"], "%b %d, %Y").date()
        numbers, bonus = payload["drawNbrs"], payload.get("bonusNbr")
        source = "PlayNow"
        addon = payload.get("extraNbrs")
        if province == "BC" and isinstance(addon, list) and len(addon) == 4 and all(type(n) is int and 0 <= n <= 99 for n in addon):
            extra.append("Extra " + " ".join(f"{n:02d}" for n in addon))
        elif province in {"AB", "SK", "MB"} and isinstance(addon, list) and len(addon) == 1 and type(addon[0]) is int and 0 <= addon[0] <= 9999999:
            extra.append(f"Extra {addon[0]:07d}")
        if spec["label"] == "Lotto 6/49":
            draws = payload.get("gpNumbers") or []
            if isinstance(draws, list) and len(draws) == 1:
                gold = gold_ball("".join(map(str, draws[0].get("drawNbrs", []))))
                if gold:
                    extra.append(gold)
    elif kind == "quebec":
        item = next(row for row in payload if str(row["noProduit"]) == spec["product"])
        parser = QuebecResult()
        parser.feed(item["html"])
        actual = datetime.strptime(parser.date, "%B %d, %Y").date()
        numbers, bonus = parser.numbers, parser.bonus
        if len(parser.extra) == 7:
            extra.append("Extra " + "".join(parser.extra))
        gold = gold_ball("".join(parser.gold))
        if spec["label"] == "Lotto 6/49" and gold:
            extra.append(gold)
        source = "Loto-Quebec"
    elif kind == "wclc":
        parsed = wclc_results(payload, day)
        if not parsed:
            return None
        numbers, bonus, addon, gold_digits = parsed
        actual, source = day, "WCLC"
        if addon:
            extra.append("Extra " + addon)
        gold = gold_ball(gold_digits)
        if spec["label"] == "Lotto 6/49" and gold:
            extra.append(gold)
    elif kind in {"bc5050", "bc-poker"}:
        date_field, time_field = ("date", "time") if kind == "bc5050" else ("drawDate", "drawTime")
        rows = [row for row in payload if datetime.strptime(row[date_field], "%b %d, %Y").date() == day]
        if not rows:
            return None
        row = max(rows, key=lambda row: datetime.strptime(row[time_field], "%I:%M:%S %p"))
        if kind == "bc5050":
            digits = row["drawNumbers"]
            if len(digits) != 6 or any(type(n) is not int or not 0 <= n <= 9 for n in digits):
                return None
            numbers = "".join(map(str, digits))
        else:
            ranks = dict(zip("TWO THREE FOUR FIVE SIX SEVEN EIGHT NINE TEN JACK QUEEN KING ACE".split(), "23456789TJQKA"))
            cards = row["CC"]
            if len(cards) != 5 or len(set(cards)) != 5:
                return None
            short = []
            for card in cards:
                rank, suit = card.split("_")
                if rank not in ranks or suit not in ("CLUBS", "DIAMONDS", "HEARTS", "SPADES"):
                    return None
                short.append(ranks[rank] + suit[0])
            numbers = "CC " + " ".join(short)
        return {"game": spec["label"], "drawDate": day.strftime("%d %b %Y"), "numbers": numbers,
                "bonus": f"Draw {int(row['drawNbr'])} / {row[time_field]} PT", "source": "PlayNow",
                "dataTime": datetime.combine(day, datetime.min.time(), UTC).isoformat()}
    else:
        return None
    balls = [int(n) for n in numbers]
    if actual != day or len(balls) != spec["count"] or len(set(balls)) != len(balls) or any(not 1 <= n <= spec["maximum"] for n in balls):
        return None
    if bonus in (None, ""):
        return None
    ball = int(bonus)
    if spec["label"] == "Daily Grand":
        if not 1 <= ball <= 7:
            return None
        extra.insert(0, f"Grand {ball:02d}")
    elif 1 <= ball <= spec["maximum"] and ball not in balls:
        extra.insert(0, f"Bonus {ball:02d}")
    else:
        return None
    return {"game": spec["label"], "drawDate": day.strftime("%d %b %Y"),
            "numbers": " ".join(f"{n:02d}" for n in balls), "bonus": " / ".join(extra) or "No extra data",
            "source": source, "dataTime": datetime.combine(day, datetime.min.time(), UTC).isoformat()}


class Regional:
    def __init__(self):
        self.catalog = load_catalog()
        self.cache = ProviderCache(os.getenv("ADSI_PROVIDER_CACHE_DIR"))
        self.client = httpx.AsyncClient(timeout=8, follow_redirects=False, trust_env=False)

    async def close(self):
        await self.client.aclose()
        self.cache.close()

    async def request(self, url, *, method="GET", limit=500_000, **kwargs):
        # URLs are operator-maintained, and caller input can only enter query parameters.
        if not url.startswith("https://"):
            return None
        try:
            async with self.client.stream(method, url, **kwargs) as response:
                response.raise_for_status()
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > limit:
                        return None
                return bytes(data)
        except httpx.HTTPError:
            return None

    async def json(self, url, **kwargs):
        data = await self.request(url, **kwargs)
        return json.loads(data) if data else None

    async def numbering(self):
        async def fetch():
            data = await self.request(self.catalog["numbering_url"], limit=20_000_000)
            return parse_numbering(data) if data else None
        return await self.cached("numbering", 604800, fetch, 2592000)

    async def location(self, prefix):
        if not prefix:
            return None
        return (await self.numbering() or {}).get(prefix)

    async def cached(self, key, ttl, fetch, max_age):
        async def checked():
            try:
                return await fetch()
            except (ValueError, TypeError, KeyError, IndexError, AttributeError, OverflowError,
                    StopIteration, RuntimeError, InvalidOperation, zipfile.BadZipFile, livefeeds.ElementTree.ParseError):
                return None
        return await self.cache.get(key, ttl, checked, max_age=max_age)

    async def weather(self, operation, key):
        province, city = key.split("|", 1)
        if province not in CAPITALS or not 1 <= len(city) <= 80:
            return None
        async def resolve():
            rows = await self.json(self.catalog["city_url"], params={"query": city, "limit": 50})
            return city_coordinates(rows, province, city) if rows else None
        coords = await self.cached(f"city:{key}", 604800, resolve, 2592000)
        if coords is None:
            return None
        async def fetch():
            return await self.json(self.catalog["weather_url"] + coords, params={"type": "city"})
        data = await self.cached(f"weather:{coords}", 600, fetch, 86400)
        return weather_record(data, operation, province, datetime.now(UTC)) if data else None

    async def news(self, topic):
        if topic.startswith("local:"):
            url = self.catalog["regional_news"].get(topic[6:])
        else:
            url = self.catalog["news"].get(topic)
        if url:
            async def fetch():
                data = await self.request(url)
                return livefeeds.rss(data, self.catalog.get("news_labels", {}).get(topic)) if data else None
            return await self.cached(f"rss:{topic}", 900, fetch, 86400)
        query = self.catalog["finance_news"]["topics"].get(topic)
        if not query:
            return None
        async def finance():
            key = os.getenv("ADSI_HEADLINEFEED_KEY")
            if not key or not self.cache.quota("headlinefeed", 100):
                return None
            data = await self.json(self.catalog["finance_news"]["endpoint"], method="POST",
                                   headers={"Authorization": f"Bearer {key}"}, json=query)
            results = []
            for row in (data or {}).get("headlines", [])[:30]:
                result = news_record(row.get("source") or query.get("source") or "Headlinefeed", row.get("title"), row.get("publishedAt") or row.get("pubDate"))
                if result:
                    results.append(result)
            return max(results, key=lambda result: datetime.fromisoformat(result["dataTime"])) if results else None
        return await self.cached(f"financial:{topic}", 3600, finance, 86400)

    async def quote(self, symbol):
        if not any(symbol in symbols for symbols in self.catalog["stocks"]["categories"].values()):
            return None
        async def twelve():
            token = os.getenv("ADSI_TWELVE_DATA_KEY")
            if not token or not self.cache.quota("twelve", 800, 8):
                return None
            row = await self.json(self.catalog["stocks"]["twelve"], params={"symbol": symbol}, headers={"Authorization": f"apikey {token}"})
            if not row or row.get("symbol") != symbol:
                return None
            return quote_record(symbol, row["close"], row["currency"], datetime.fromtimestamp(int(row["timestamp"]), UTC),
                                "Twelve Data", "Provider quote")
        result = await self.cached(f"twelve:{symbol}", 3600, twelve, 86400)
        if result and timedelta(0) <= datetime.now(UTC) - datetime.fromisoformat(result["dataTime"]) <= timedelta(hours=24):
            return result
        async def alpha():
            token = os.getenv("ADSI_ALPHA_VANTAGE_KEY")
            currency = self.catalog["stocks"].get("alpha_currencies", {}).get(symbol)
            if not token or not currency or not self.cache.quota("alpha", 25):
                return None
            data = await self.json(self.catalog["stocks"]["alpha"], params={"function": "GLOBAL_QUOTE", "symbol": symbol, "apikey": token})
            row = (data or {}).get("Global Quote", {})
            if row.get("01. symbol") != symbol:
                return None
            stamp = datetime.combine(date.fromisoformat(row["07. latest trading day"]), datetime.min.time(), UTC)
            record = quote_record(symbol, row["05. price"], currency, stamp, "Alpha Vantage", "End of day")
            if record:
                record["localTime"] = stamp.strftime("%d %b %Y")
            return record
        return await self.cached(f"alpha:{symbol}", 3600, alpha, 604800)

    async def lottery(self, game, province, requested=None):
        spec = self.catalog["lottery"].get(game)
        if not spec or spec["type"] == "pending":
            return None
        today = datetime.now(ZoneInfo(spec.get("zone", "America/Toronto"))).date()
        days = [date.fromisoformat(requested)] if requested else [today - timedelta(days=n) for n in range(8)]
        for day in [d for d in days if d <= today and d.weekday() in spec["days"]][:2]:
            async def fetch_spec(selected):
                params = None
                if selected["type"] == "alc":
                    params = {"game": selected["product"], "date": day.isoformat()}
                elif selected["type"] == "quebec":
                    params = {"noProduits": selected["product"]}
                url = selected["url"].format(date=day.isoformat())
                if selected["type"] == "wclc":
                    raw = await self.request(url)
                    data = raw.decode("utf-8", errors="replace") if raw else None
                else:
                    data = await self.json(url, params=params)
                return dated_draw(selected, data, day, province) if data else None
            async def fetch():
                overrides = self.catalog.get("national_overrides", {})
                group = next((key for key, provinces in self.catalog.get("region_groups", {}).items() if province in provinces), None)
                regional = overrides.get(province, overrides.get(group, {})).get(game)
                if regional:
                    try:
                        result = await fetch_spec({**spec, **regional})
                        if result:
                            return result
                    except (KeyError, ValueError, TypeError, IndexError, StopIteration, RuntimeError):
                        pass
                return await fetch_spec(spec)
            result = await self.cached(f"draw:{game}:{province}:{day}", 1800, fetch, 604800)
            if result:
                return result
        return None


async def choose(link, say, title, entries):
    """Present a bounded paged list, preserving the active ADSI session."""
    for start in range(0, len(entries), 2):
        batch = entries[start:start + 2]
        labels = [label for _, label in batch]
        if start + 2 < len(entries):
            labels.append("More")
        lines = [graph.handset_text(title)[:20], *(graph.handset_text(f"{i} {label}")[:20] for i, label in enumerate(labels, 1))]
        if link.data_mode:
            await link.transfer(wire.screen(lines, [(graph.handset_text(label)[:7], str(i)) for i, label in enumerate(labels, 1)]), open_input=True)
        else:
            link.open_voice_input()
            await say(title + ". " + ". ".join(f"Press {i} for {label}" for i, label in enumerate(labels, 1)))
        try:
            digit = await link.selection(30)
        except TimeoutError:
            return None
        if digit in [str(i) for i in range(1, len(batch) + 1)]:
            return batch[int(digit) - 1][0]
        if digit != "3":
            return None
    return None


async def choose_weather(link, say, location):
    if location and location[1]:
        province, city = location
        choice = await choose(link, say, f"Weather: {city}?", [(f"{province}|{city}", "Yes"), ("other", "Other city")])
        if choice != "other":
            return choice
    return await choose(link, say, "Choose weather city", [(f"{province}|{city}", f"{city}, {province}") for province, city in CAPITALS.items()])
