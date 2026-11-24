import json
import unittest
from unittest.mock import patch

import httpx

from coinline_adsi import fdm, livefeeds
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


class PublicProviderTests(unittest.IsolatedAsyncioTestCase):
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
