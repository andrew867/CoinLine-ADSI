import json
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import httpx
from defusedxml import ElementTree

from coinline_adsi import fdm, livefeeds, providers
from coinline_adsi.assistant import InformationDesk


class ResidentArtifactTests(unittest.TestCase):
    def test_order_lengths_and_checksums(self):
        frames = fdm.artifact("RESIDENT LAB", 2)
        self.assertEqual([frame[3] for frame in frames], [0x83, 0x80, 0x81, 0x82, 0x84])
        for frame in frames:
            self.assertEqual(frame[0], 0x85)
            self.assertEqual(frame[1], len(frame) - 3)
            self.assertEqual(frame[4], len(frame) - 6)
            self.assertEqual(sum(frame) % 256, 0)
        self.assertNotEqual(fdm.fingerprint("RESIDENT LAB", 2), fdm.fingerprint("RESIDENT LAB", 3))
        with self.assertRaises(ValueError):
            fdm.artifact("newline\n", 2)
        launcher = fdm.artifact("INFOLINE", 2, True)
        self.assertIn(b"\x82\x846501", launcher[1])
        self.assertNotEqual(fdm.fingerprint("INFOLINE", 2), fdm.fingerprint("INFOLINE", 2, True))


class PublicProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_location_confirms_or_overrides_numbering_suggestion(self):
        places = {
            "east": {**providers.DEMO_SITE, "place": "East Harbour"},
            "west": {**providers.DEMO_SITE, "place": "West Harbour"},
        }
        config = {"sites": places, "prefixes": {"709555": "east"}}
        for caller, digits, expected in (
            ("+17095550123", ["1"], "east"),
            ("+17095550123", ["2", "2"], "west"),
            (None, ["2"], "west"),
        ):
            with self.subTest(caller=caller is not None, digits=digits):
                link = AsyncMock()
                link.display_active = True
                link.selection.side_effect = digits
                self.assertEqual(await providers.choose_site(config, caller, link, AsyncMock()), expected)
                self.assertEqual(link.transfer.await_count, len(digits))

    async def test_live_weather_uses_source_time_and_checks_current_conditions(self):
        source_time = datetime(2026, 2, 8, 2, 30, tzinfo=UTC)
        site = {**providers.DEMO_SITE, "code": "s1234567"}
        document = ElementTree.fromstring(
            '<siteData><currentConditions><dateTime name="observation" zone="UTC">'
            '<timeStamp>20260208023000</timeStamp></dateTime>'
            '<temperature>-8</temperature></currentConditions></siteData>')
        desk = providers.Providers()
        self.addAsyncCleanup(desk.client.aclose)
        with patch.object(desk, "_weather", new_callable=AsyncMock, return_value=document) as fetch:
            with patch.object(providers, "datetime", wraps=datetime) as clock:
                clock.now.return_value = source_time + timedelta(hours=3)
                result = await desk._weather_result("weather.current", site)
                self.assertEqual(result["displayTitle"], "STALE ECCC WEATHER")
                self.assertEqual(result["localTime"], "23:00 NST")
                clock.now.return_value = source_time + timedelta(hours=7)
                self.assertIsNone(await desk._weather_result("weather.current", site))
                fetch.return_value = ElementTree.fromstring("<siteData/>")
                self.assertIsNone(await desk._weather_result("weather.current", site))

    async def test_manual_market_age_and_draw_correction(self):
        date = datetime(2026, 2, 8, 2, 30, tzinfo=UTC)
        quote = {**providers.fixture("market.quote", {}), "delay": "Delayed", "dataTime": date.isoformat()}
        quote.pop("displayTitle")
        draw = {**providers.fixture("lottery.draw", {}), "dataTime": date.isoformat()}
        draw.pop("displayTitle")
        desk = providers.Providers()
        self.addAsyncCleanup(desk.client.aclose)
        config = {"manual": {"market.quote": {"TSX-DEMO": quote}, "lottery.draw": {"atlantic-demo": draw}}}
        with patch.object(providers, "datetime", wraps=datetime) as clock:
            clock.now.return_value = date + timedelta(hours=2)
            result = await desk.lookup(config, "market.quote", {"instrument": "TSX-DEMO"})
            self.assertEqual(result["displayTitle"], "STALE MANUAL")
            self.assertEqual(result["delay"], "Delayed")
            quote["delay"] = "End of day"
            result = await desk.lookup(config, "market.quote", {"instrument": "TSX-DEMO"})
            self.assertEqual(result["displayTitle"], "MANUAL")
            self.assertEqual(result["delay"], "End of day")
            result = await desk.lookup(config, "lottery.draw", {"game": "atlantic-demo"})
            self.assertEqual(result["bonus"], "Bonus 08")
            draw["bonus"] = "Bonus 09"
            corrected = await desk.lookup(config, "lottery.draw", {"game": "atlantic-demo"})
            self.assertEqual(corrected["displayTitle"], "MANUAL DRAW")
            self.assertEqual(corrected["bonus"], "Bonus 09")
            self.assertIsNone(await desk.lookup(config, "lottery.draw", {"game": "other-game"}))

    async def test_publisher_feed_parsing(self):
        response = b"<rss><channel><title>Fixture Desk</title><item><title>Later headline</title>" \
                   b"<pubDate>Sat, 7 Feb 2026 15:00:00 +0000</pubDate></item><item><title>Earlier</title>" \
                   b"<pubDate>Sat, 7 Feb 2026 14:00:00 +0000</pubDate></item></channel></rss>"
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=response))) as client:
            with patch.dict("os.environ", {"ADSI_FEED_NEWS_URL": "https://fixture.invalid/feed"}):
                data = await livefeeds.fetch(client, "news.headlines", "atlantic")
        self.assertEqual(data["headline"], "Later headline")
        self.assertEqual(data["source"], "Fixture Desk")
        self.assertEqual(data["dataTime"], "2026-02-07T15:00:00+00:00")

    async def test_model_context_and_reject_extra_fields(self):
        recorded = []
        def route(request):
            recorded.append(json.loads(request.content))
            value = json.dumps({"answer": "An analog display service.", "tool": "unsupported"})
            return httpx.Response(200, json={"choices": [{"message": {"content": value}}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(route)) as client:
            with patch.dict("os.environ", {"ADSI_MODEL_URL": "https://fixture.invalid/chat/completions",
                                           "ADSI_MODEL_NAME": "synthetic-model"}):
                desk = InformationDesk(client)
                self.assertIsNone(await desk.answer("unapproved"))
                self.assertIsNone(await desk.answer("adsi"))
        self.assertEqual(len(recorded), 1)
        context = json.loads(recorded[0]["messages"][1]["content"])
        self.assertEqual(set(context), {"question", "public_source"})
