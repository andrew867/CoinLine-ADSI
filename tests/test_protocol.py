import asyncio
import json
import struct
import unittest
from pathlib import Path

from coinline_adsi import audio, wire
from coinline_adsi.link import Link, LinkFailure


ROOT = Path(__file__).parents[1]


class WireTests(unittest.TestCase):
    def test_golden_frames(self):
        vectors = json.loads((ROOT / "fixtures/wire/vectors.json").read_text())
        valid = {vector["id"]: bytes.fromhex(vector["hex"]) for vector in vectors["valid"]}
        self.assertEqual(wire.CONNECT, valid["sdc-connect"])
        self.assertEqual(wire.frame(wire.display_line(1, "LAB"), wire.select_line(1)), valid["sdc-lab"])
        self.assertEqual(wire.LAB, valid["sdc-lab-with-key"])
        self.assertEqual(wire.OK, valid["sdc-ok"])
        self.assertEqual(wire.RELEASE, valid["sdc-release"])
        self.assertEqual(wire.frame(wire.parameter(0x84), kind=wire.DOWNLOAD), valid["fdm-disconnect"])

    def test_boundaries(self):
        self.assertEqual(wire.frame(wire.parameter(0x82, bytes(251)))[1], 254)
        with self.assertRaises(ValueError):
            wire.frame(wire.parameter(0x82, bytes(252)))
        with self.assertRaises(ValueError):
            wire.display_line(0, "LAB")
        with self.assertRaises(ValueError):
            wire.softkey(16, "Go", "D")

    def test_pcm_durations_and_carrier(self):
        self.assertEqual(len(audio.cas()), 680 * 2)
        pcm = audio.bell202(wire.LAB)
        bits = 180 + 10 * len(wire.LAB) + 12
        self.assertEqual(len(pcm) // 2, (bits * 8000 + 1199) // 1200)
        mark = [sample for (sample,) in struct.iter_unpack("<h", pcm[:2400])]
        zero_crossings = sum(left < 0 <= right for left, right in zip(mark, mark[1:]))
        self.assertAlmostEqual(zero_crossings, 180, delta=1)


class LinkTests(unittest.IsolatedAsyncioTestCase):
    async def test_t04_failed_ack_disarms_application(self):
        clock = asyncio.get_running_loop().time
        for response in ("D0", "D2", "D", "1", ""):
            with self.subTest(response=response):
                attempts = []

                async def play(pcm):
                    attempts.append(pcm)
                    end = clock()
                    # Reordered or cached tokens timestamped before media drain cannot acknowledge.
                    for digit in "D1":
                        link.receive(digit, end - 0.005)
                    for digit in response:
                        link.receive(digit, end)
                    return end

                link = Link(play, reply_timeout=0.005)
                with self.assertRaises(LinkFailure):
                    await link.transfer(wire.LAB, open_input=True)
                self.assertEqual(len(attempts), 2)
                self.assertTrue(link.uncertain)
                with self.assertRaisesRegex(LinkFailure, "disarmed"):
                    await link.selection(0.005)

    async def test_confirmed_screen(self):
        now = asyncio.get_running_loop().time
        replies = iter(("A", "D1", "D1", "D1"))

        async def play(_):
            played = now()
            for value in next(replies):
                link.receive(value, now())
            return played

        link = Link(play)
        self.assertTrue(await link.connect())
        await link.transfer(wire.LAB, open_input=True)
        for value in "D11":
            link.receive(value, now())
        self.assertEqual(await link.selection(0.01), "1")
        await link.release()
        self.assertFalse(link.data_mode)

    async def test_t04_a_late_original_ack_cannot_confirm_next_map(self):
        now = asyncio.get_running_loop().time
        replies = iter(("", "D1"))
        played_frames = []

        async def play(pcm):
            played_frames.append(pcm)
            start = now()
            for value in next(replies):
                link.receive(value, now())
            return start

        link = Link(play, reply_timeout=0.005)
        with self.assertRaisesRegex(LinkFailure, "outstanding acknowledgment"):
            await link.transfer(wire.LAB, open_input=True)
        for value in "D1":
            link.receive(value, now())
        with self.assertRaisesRegex(LinkFailure, "unresolved"):
            await link.transfer(wire.OK, open_input=True)
        with self.assertRaisesRegex(LinkFailure, "disarmed"):
            await link.selection(0.01)
        self.assertEqual(played_frames, [audio.bell202(wire.LAB)] * 2)

    async def test_no_capability(self):
        async def play(_):
            return asyncio.get_running_loop().time()

        self.assertFalse(await Link(play, probe_timeout=0.005).connect())
