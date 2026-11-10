"""Tests for the publisher-description lookup and the AI summary step (no network)."""
import json
import os
import sys
import unittest
from datetime import datetime, timezone
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
import article_meta as A  # noqa: E402

GOOGLE = "https://news.google.com/rss/articles/CBMingFBVV95cUxQR1lvWVg3QzZLYWlSUmJiSjFhRFMta3ltMlNWYnZxMjJjd2tyaUFfSENYejZWZWJTcWs?oc=5"
PUB = "https://www.freightwaves.com/news/radiant-logistics-credit-facility"
PAGE = ('<html><head><meta name="description" content="short">'
        '<meta property="og:description" content="Radiant Logistics expanded its credit facility to $300 million and says it is looking at larger acquisitions in 2027.">'
        '</head><body>ignored</body></html>')


def fake_web(robots="User-agent: *\nAllow: /\n", page=PAGE):
    calls = []

    def get(url, data=None, headers=None):
        calls.append(url)
        if url.endswith("/robots.txt"):
            return url, robots
        if "news.google.com/articles/" in url:
            return url, '<c-wiz><div jscontroller="x" data-n-a-sg="SIG123" data-n-a-ts="1762740000"></div></c-wiz>'
        if "batchexecute" in url:
            assert b"SIG123" in data and b"1762740000" in data
            inner = json.dumps(["garturlres", PUB, 1])
            return url, ")]}'\n\n" + json.dumps([["wrb.fr", "Fbv4je", inner, None, None, None, "generic"]]) + "\n"
        if url == PUB:
            return url, page
        raise AssertionError("unexpected fetch " + url)
    return get, calls


class Lookup(unittest.TestCase):
    def setUp(self):
        A._robots.clear()

    def test_google_link_to_publisher_and_description(self):
        get, calls = fake_web()
        url, desc, note = A.describe(GOOGLE, get)
        self.assertEqual(url, PUB)
        self.assertTrue(desc.startswith("Radiant Logistics expanded"))
        self.assertEqual(note, "ok")

    def test_old_style_google_id_decoded_offline(self):
        import base64
        aid = base64.urlsafe_b64encode(b"\x08\x13\x22\x2b" + PUB.encode() + b"\xd2\x01\x00").decode().rstrip("=")
        self.assertEqual(A.google_to_publisher("https://news.google.com/rss/articles/" + aid, lambda *a, **k: 1 / 0), PUB)

    def test_robots_disallow_respected(self):
        get, calls = fake_web(robots="User-agent: *\nDisallow: /news/\n")
        url, desc, note = A.describe(GOOGLE, get)
        self.assertIsNone(desc)
        self.assertIn("robots", note)
        self.assertNotIn(PUB, calls)

    def test_no_description_means_none_not_a_guess(self):
        get, _ = fake_web(page='<html><head><meta name="description" content="FreightWaves"></head></html>')
        self.assertIsNone(A.describe(GOOGLE, get)[1])

    def test_direct_publisher_link_skips_google(self):
        get, calls = fake_web()
        self.assertEqual(A.describe(PUB, get)[0], PUB)
        self.assertFalse(any("google" in c for c in calls))


class SummaryStep(unittest.TestCase):
    """fetch_news only calls the AI when a publisher description was found."""

    def run_main(self, describe):
        import fetch_news
        now = datetime.now(timezone.utc).isoformat()
        base = {"orig_title": "Radiant Logistics touts enhanced credit facility, eyes larger M&A", "source": "FreightWaves",
                "link": GOOGLE, "published": now, "first_seen": now, "ai": False, "status": "ok", "importance": 60,
                "summary": "", "why": "", "slug": "x", "date_known": True, "category": "other"}
        stories = [dict(base, id="a1"), dict(base, id="b2", orig_title="Forward Air pauses sale of intermodal unit")]
        saved = {}

        class Client:
            calls = []

            class messages:
                @staticmethod
                def create(**kw):
                    Client.calls.append(kw)
                    body = json.dumps({"relevant": True, "title": "Radiant Logistics expands credit line",
                                       "summary": "Radiant Logistics grew its credit facility and says bigger acquisitions are next.",
                                       "why_it_matters": "More consolidation among 3PLs.", "category": "other",
                                       "region": "US", "importance": 60})
                    return mock.Mock(content=[mock.Mock(type="text", text=body)])

        fake_anthropic = mock.Mock(Anthropic=lambda: Client)
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test"}), \
                mock.patch.dict(sys.modules, {"anthropic": fake_anthropic}), \
                mock.patch.object(fetch_news, "load_config", return_value={"news_feeds": [], "ai_model": "m", "keep_days": 30}), \
                mock.patch.object(fetch_news, "load_json", side_effect=lambda n, d: [dict(s) for s in stories] if n == "news.json" else d), \
                mock.patch.object(fetch_news, "save_json", side_effect=lambda n, v: saved.__setitem__(n, v)), \
                mock.patch.object(fetch_news.editorial, "reprocess", side_effect=lambda st, now: st), \
                mock.patch.object(fetch_news.article_meta, "describe", side_effect=describe), \
                mock.patch.object(fetch_news.time, "sleep"):
            fetch_news.main()
        return {s["id"]: s for s in saved["news.json"]}, Client.calls

    def test_only_described_stories_get_ai(self):
        def describe(link):
            return (PUB, "Radiant Logistics expanded its credit facility to $300 million and is eyeing larger deals.", "ok") \
                if describe.n == 0 else (None, None, "no publisher address")
        describe.n = 0

        def d(link):
            r = describe(link)
            describe.n += 1
            return r
        out, calls = self.run_main(d)
        self.assertEqual(len(calls), 1, "AI called only for the story with real preview text")
        self.assertIn("Publisher description: Radiant", calls[0]["messages"][0]["content"])
        with_sum = [s for s in out.values() if s["summary"]]
        without = [s for s in out.values() if not s["summary"]]
        self.assertEqual(len(with_sum), 1)
        self.assertEqual(len(without), 1)
        self.assertTrue(without[0]["desc_done"] and without[0].get("ai") is False)
        self.assertNotIn("ai_relevant", without[0], "headline-only story is never judged off-topic")

    def test_network_trouble_retried_later(self):
        def boom(link):
            raise OSError("timed out")
        out, calls = self.run_main(boom)
        self.assertEqual(calls, [])
        self.assertTrue(all(not s.get("desc_done") and s["desc_tries"] == 1 for s in out.values()))


if __name__ == "__main__":
    unittest.main()
