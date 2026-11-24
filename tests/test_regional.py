"""Deterministic Canadian provider and free-tier budget checks."""

import asyncio
import io
import tempfile
import unittest
import zipfile
from datetime import UTC, date, datetime
from unittest.mock import patch

import httpx

from coinline_adsi import livefeeds
from coinline_adsi.provider_cache import ProviderCache
from coinline_adsi.regional import Regional, city_coordinates, dated_draw, load_catalog, parse_numbering, weather_record


class RegionalTests(unittest.TestCase):
    def test_numbering_shared_area_code_and_invalid_entries(self):
        rows = ["NPA,CO Code (NXX),Status,Exchange Area,Province",
                "902,200,In Service,Example Harbour,NS", "902,201,In Service,Example Island,PE",
                "902,202,Reserved,Example Town,NS"]
        rows += [f"{npa},{nxx},In Service,Test City,ON" for npa in (289, 416) for nxx in range(200, 900)]
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as archive:
            archive.writestr("COCodeStatus_ALL.csv", "\n".join(rows))
        result = parse_numbering(data.getvalue())
        self.assertEqual(result["902200"], ["NS", "Example Harbour"])
        self.assertEqual(result["902201"], ["PE", "Example Island"])
        self.assertNotIn("902202", result)

    def test_location_exact_match_and_rounding(self):
        rows = [{"display_name": "Example, QC", "lat": "47.12355", "lon": "-72.4563"},
                {"display_name": "Example, ON", "lat": "43.65485714", "lon": "-79.38321697"}]
        self.assertEqual(city_coordinates(rows, "ON", "Example"), "43.655,-79.383")
        self.assertIsNone(city_coordinates(rows, "NL", "Example"))

    def test_weather_source_observation_and_forecast_freshness(self):
        now = datetime(2026, 2, 7, 12, tzinfo=UTC)
        data = [{"displayName": "Nearby Town", "observation": {"provinceCode": "nl", "observedAt": "Test Airport",
                 "timeStamp": "2026-02-07T11:00:00Z", "temperature": {"metric": "-7"}},
                 "dailyFcst": {"dailyIssuedTimeEpoch": str(int(now.timestamp()) - 600), "daily": [{"titleText": "Cloudy"}]}}]
        record = weather_record(data, "weather.current", "NL", now)
        self.assertEqual(record["place"], "Test Airport")
        self.assertEqual(record["temperatureText"], "-7 C")
        self.assertEqual(weather_record(data, "weather.forecast", "NL", now)["forecast"], "Cloudy")
        self.assertIsNone(weather_record(data, "weather.current", "ON", now))

    def test_draw_date_and_regional_extra(self):
        spec = load_catalog()["lottery"]["max"]
        day = date(2026, 11, 17)
        stamp = int(datetime(2026, 11, 18, 3, tzinfo=UTC).timestamp()) * 1000
        data = {"game": "LottoMax30", "draw_date": f"/Date({stamp}-0400)/", "draw": {"winning_numbers": ["01", "02", "03", "04", "05", "06", "52"],
                "bonus_number": "07", "tag": "012345"}}
        self.assertIn("TAG 012345", dated_draw(spec, data, day, "NL")["bonus"])
        self.assertNotIn("TAG", dated_draw(spec, data, day, "ON")["bonus"])
        self.assertIsNone(dated_draw(spec, data, date(2026, 11, 18), "NL"))
        data["game"] = "DifferentGame"
        self.assertIsNone(dated_draw(spec, data, day, "NL"))
        data["game"] = "LottoMax30"
        data["draw"]["winning_numbers"][0] = "03"
        self.assertIsNone(dated_draw(spec, data, day, "NL"))

    def test_quebec_regional_date_and_balls(self):
        spec = load_catalog()["lottery"]["quebec49"]
        html = '<div class="date">November 21, 2026</div><div class="numeros">' + ''.join(f'<span class="num">{n}</span>' for n in range(1, 7)) + '<span class="num complementaire">07</span></div>'
        record = dated_draw(spec, [{"noProduit": "214", "html": html}], date(2026, 11, 21), "QC")
        self.assertEqual(record["numbers"], "01 02 03 04 05 06")

    def test_wclc_uses_the_requested_draw_block(self):
        spec = load_catalog()["lottery"]["western649"]
        def row(stamp, extra, balls):
            return (f'<div class="pastWinNum"><div class="pastWinNumExtra">{extra}</div>'
                    f'<div class="pastWinNumDate"><h4>{stamp}</h4></div><ul class="pastWinNumbers">'
                    + ''.join(f'<li class="pastWinNumber">{n}</li>' for n in balls)
                    + '<li class="pastWinNumberBonus"><span class="pastWinNumberBonusText">Bonus</span>9</li></ul></div>')
        html = row("Saturday, November 21, 2026", "1234567", range(1, 7)) + row("Wednesday, November 18, 2026", "7654321", range(2, 8))
        record = dated_draw(spec, html, date(2026, 11, 18), "SK")
        self.assertEqual(record["numbers"], "02 03 04 05 06 07")
        self.assertIn("Extra 7654321", record["bonus"])
        self.assertIsNone(dated_draw(spec, html, date(2026, 11, 17), "SK"))

    def test_rss_configured_publisher_for_untitled_feed(self):
        data = b'<rss><channel><title></title><item><title>Fixture headline</title><pubDate>Sat, 07 Feb 2026 10:00:00 GMT</pubDate></item></channel></rss>'
        self.assertIsNone(livefeeds.rss(data))
        self.assertEqual(livefeeds.rss(data, "Fixture Publisher")["source"], "Fixture Publisher")

    def test_bc_subdraw_requires_date_and_valid_card_codes(self):
        spec = load_catalog()["lottery"]["bc-poker"]
        row = {"drawNbr": 100, "drawDate": "Nov 24, 2026", "drawTime": "01:37:00 PM",
               "CC": ["FOUR_HEARTS", "TEN_CLUBS", "ACE_SPADES", "SEVEN_CLUBS", "KING_CLUBS"]}
        result = dated_draw(spec, [row], date(2026, 11, 24), "BC")
        self.assertEqual(result["numbers"], "CC 4H TC AS 7C KC")
        self.assertIsNone(dated_draw(spec, [row], date(2026, 11, 23), "BC"))
        row["CC"][0] = "ACE_SPADES"
        self.assertIsNone(dated_draw(spec, [row], date(2026, 11, 24), "BC"))


class CacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_cache_coalesces_and_persists_quota(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = ProviderCache(directory)
            calls = 0

            async def fetch():
                nonlocal calls
                calls += 1
                await asyncio.sleep(0)
                return {"value": 1}

            with patch("coinline_adsi.provider_cache.time.time", return_value=600):
                self.assertEqual(await asyncio.gather(*(cache.get("sample", 3600, fetch) for _ in range(5))), [{"value": 1}] * 5)
                self.assertEqual(calls, 1)
                self.assertTrue(cache.quota("test", 3, 2, 2))
                self.assertFalse(cache.quota("test", 3, 2))
                cache.close()
                cache = ProviderCache(directory)
                self.assertEqual(await cache.get("sample", 3600, fetch), {"value": 1})
                self.assertFalse(cache.quota("test", 3, 2))
            with patch("coinline_adsi.provider_cache.time.time", return_value=660):
                self.assertTrue(cache.quota("test", 3, 2))
                self.assertFalse(cache.quota("test", 3, 2))
            cache.close()

    async def test_stock_request_is_shared_and_has_explicit_currency(self):
        requests = []
        now = datetime.now(UTC)

        def respond(request):
            requests.append(request.url.path)
            self.assertEqual(request.headers["Authorization"], "apikey synthetic")
            return httpx.Response(200, json={"symbol": "AAPL", "close": "102.34", "currency": "USD", "timestamp": int(now.timestamp())})

        with patch.dict("os.environ", {"ADSI_TWELVE_DATA_KEY": "synthetic", "ADSI_PROVIDER_CACHE_DIR": ""}):
            provider = Regional()
            await provider.client.aclose()
            provider.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
            try:
                results = await asyncio.gather(provider.quote("AAPL"), provider.quote("AAPL"))
                self.assertEqual(results[0]["priceText"], "USD 102.34")
                self.assertEqual(results[0], results[1])
                self.assertEqual(requests, ["/quote"])
                self.assertIsNone(await provider.quote("INVALID"))
            finally:
                await provider.close()

    async def test_financial_news_query_and_fallback_quote(self):
        seen = []
        now = datetime.now(UTC)

        def respond(request):
            if request.url.host == "api.headlinefeed.dev":
                self.assertEqual(request.headers["Authorization"], "Bearer synthetic")
                self.assertIn(b'"title":"biotech"', request.content)
                seen.append("biotech")
                return httpx.Response(200, json={"headlines": [{"title": "Fixture biotech headline", "source": "Fixture Publisher", "publishedAt": now.isoformat()}]})
            self.assertEqual(request.url.host, "www.alphavantage.co")
            self.assertEqual(request.url.params["symbol"], "MSFT")
            seen.append("alpha")
            return httpx.Response(200, json={"Global Quote": {"01. symbol": "MSFT", "05. price": "99.42", "07. latest trading day": now.date().isoformat()}})

        with patch.dict("os.environ", {"ADSI_HEADLINEFEED_KEY": "synthetic", "ADSI_ALPHA_VANTAGE_KEY": "synthetic",
                                       "ADSI_TWELVE_DATA_KEY": "", "ADSI_PROVIDER_CACHE_DIR": ""}):
            provider = Regional()
            await provider.client.aclose()
            provider.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
            try:
                self.assertEqual((await provider.news("biotech"))["headline"], "Fixture biotech headline")
                await provider.news("biotech")
                quote = await provider.quote("MSFT")
                self.assertEqual(quote["priceText"], "USD 99.42")
                self.assertEqual(quote["delay"], "End of day")
                await provider.quote("MSFT")
                self.assertEqual(seen, ["biotech", "alpha"])
            finally:
                await provider.close()

    async def test_failed_fetch_uses_bounded_cache_and_retry_window(self):
        cache = ProviderCache(None)
        calls = 0
        async def fetch():
            nonlocal calls
            calls += 1
            return {"value": 1} if calls == 1 else None
        try:
            with patch("coinline_adsi.provider_cache.time.time", return_value=600):
                self.assertEqual(await cache.get("key", 30, fetch, max_age=180), {"value": 1})
            with patch("coinline_adsi.provider_cache.time.time", return_value=640):
                self.assertEqual(await cache.get("key", 30, fetch, max_age=180), {"value": 1})
                self.assertEqual(await cache.get("key", 30, fetch, max_age=180), {"value": 1})
                self.assertEqual(calls, 2)
            with patch("coinline_adsi.provider_cache.time.time", return_value=900):
                self.assertIsNone(await cache.get("key", 30, fetch, max_age=180))
        finally:
            cache.close()
