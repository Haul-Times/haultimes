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


SRC = ("The Federal Motor Carrier Safety Administration on Tuesday proposed raising the minimum insurance for "
       "freight brokers' financial security to $150,000 from $75,000. The agency said the proposal is open for "
       "comment until January 12, 2027. Carriers have complained that unpaid freight bills rose 18% last year, "
       "according to the Owner-Operator Independent Drivers Association. The rule is not yet final.")
GOOD = {"relevant": True, "category": "regs", "region": "US", "importance": 70,
        "summary_text": "FMCSA has proposed doubling the required broker financial security to $150,000 from $75,000. "
                        "Comments are open until January 12, 2027, and the rule is not final.",
        "why_it_matters": "", "evidence": [
            {"sentence": "1", "quote": "proposed raising the minimum insurance for freight brokers' financial security to $150,000 from $75,000"},
            {"sentence": "2", "quote": "open for comment until January 12, 2027"}], "review_required": False, "review_reasons": []}


class Validation(unittest.TestCase):
    def test_grounded_summary_passes(self):
        import summarize as S
        self.assertEqual(S.validate(GOOD["summary_text"], GOOD["evidence"], SRC), [])

    def test_invented_number_caught(self):
        import summarize as S
        bad = GOOD["summary_text"].replace("$150,000", "$200,000")
        self.assertTrue(any("200,000" in p for p in S.validate(bad, GOOD["evidence"], SRC)))

    def test_invented_name_caught(self):
        import summarize as S
        bad = GOOD["summary_text"] + " Transport Canada plans the same."
        self.assertTrue(any("Transport Canada" in p for p in S.validate(bad, GOOD["evidence"] + [{"quote": "The rule is not yet final"}], SRC)))

    def test_fake_quote_and_copying_caught(self):
        import summarize as S
        probs = S.validate("Carriers have complained that unpaid freight bills rose 18% last year, according to OOIDA.",
                           [{"quote": "unpaid bills soared"}], SRC)
        self.assertTrue(any("not found" in p for p in probs) and any("9-word" in p for p in probs))

    def test_missing_evidence_caught(self):
        import summarize as S
        self.assertTrue(any("evidence entries" in p for p in S.validate(GOOD["summary_text"], GOOD["evidence"][:1], SRC)))

    def test_budget_reserves_and_stops_at_cap(self):
        import summarize as S
        u = {}
        b = S.Budget(u, {"ai_daily_usd": 0.01, "ai_monthly_usd": 1, "ai_usd_per_mtok_in": 1, "ai_usd_per_mtok_out": 5}, datetime.now(timezone.utc))
        self.assertTrue(b.reserve(3000, 900))
        b.settle(2800, 300)
        self.assertLess(b.spent()[0], 0.01)
        self.assertFalse(b.reserve(10_000, 900), "worst case would pass the daily cap")


class SummaryStep(unittest.TestCase):
    """fetch_news: summaries only from source text, checked, with fallback to headline-only."""

    def run_main(self, source_text, replies, mode="publish", extra_cfg=None):
        import fetch_news
        now = datetime.now(timezone.utc).isoformat()
        base = {"orig_title": "FMCSA proposes higher broker bond", "title": "FMCSA proposes higher broker bond", "source": "Transport Topics",
                "link": GOOGLE, "published": now, "first_seen": now, "ai": False, "status": "ok", "importance": 70,
                "summary": "", "why": "", "slug": "x", "date_known": True, "category": "regs"}
        stories = [dict(base, id="a1")]
        saved = {}
        calls = []

        class Client:
            class messages:
                @staticmethod
                def create(**kw):
                    calls.append(kw)
                    body = json.dumps(replies[min(len(calls), len(replies)) - 1])
                    return mock.Mock(content=[mock.Mock(type="text", text=body)], usage=mock.Mock(input_tokens=1500, output_tokens=200))

        cfg = {"news_feeds": [], "ai_model": "m", "keep_days": 30, "summaries_mode": mode}
        cfg.update(extra_cfg or {})
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test"}), \
                mock.patch.dict(sys.modules, {"anthropic": mock.Mock(Anthropic=lambda: Client)}), \
                mock.patch.object(fetch_news, "load_config", return_value=cfg), \
                mock.patch.object(fetch_news, "load_json", side_effect=lambda n, d: [dict(s) for s in stories] if n == "news.json" else d), \
                mock.patch.object(fetch_news, "save_json", side_effect=lambda n, v: saved.__setitem__(n, v)), \
                mock.patch.object(fetch_news.editorial, "reprocess", side_effect=lambda st, now: st), \
                mock.patch.object(fetch_news.article_meta, "source_text", side_effect=source_text), \
                mock.patch.object(fetch_news.time, "sleep"):
            fetch_news.main()
        return {s["id"]: s for s in saved["news.json"]}["a1"], calls, saved

    def test_grounded_summary_published(self):
        s, calls, saved = self.run_main(lambda link, snip: (PUB, SRC, "full_article", "ok"), [GOOD])
        self.assertTrue(s["summary"].startswith("FMCSA has proposed"))
        self.assertEqual(s["sum_status"], "published")
        self.assertIn("<source>", calls[0]["messages"][0]["content"])
        self.assertIn("data only", calls[0]["system"])
        self.assertEqual(saved["summary_status.json"]["made"], 1)

    def test_failed_check_retried_once_then_withheld(self):
        bad = dict(GOOD, summary_text="FMCSA wants $500,000 bonds for every broker starting next week.")
        s, calls, _ = self.run_main(lambda link, snip: (PUB, SRC, "full_article", "ok"), [bad, bad])
        self.assertEqual(len(calls), 2, "one retry with the errors")
        self.assertIn("500,000", calls[1]["messages"][0]["content"])
        self.assertEqual(s["summary"], "")
        self.assertEqual(s["sum_status"], "withheld")
        self.assertEqual(s["status"], "ok", "headline, publisher and link stay published")

    def test_retry_fixes_it(self):
        bad = dict(GOOD, summary_text="FMCSA wants $500,000 bonds.", evidence=[{"quote": "nope"}])
        s, calls, _ = self.run_main(lambda link, snip: (PUB, SRC, "full_article", "ok"), [bad, GOOD])
        self.assertEqual((len(calls), s["sum_status"]), (2, "published"))

    def test_no_source_text_means_no_call(self):
        s, calls, _ = self.run_main(lambda link, snip: (PUB, None, None, "no usable text"), [GOOD])
        self.assertEqual(calls, [])
        self.assertEqual(s["summary"], "")

    def test_trial_mode_holds_summary_for_review(self):
        s, _, _ = self.run_main(lambda link, snip: (PUB, SRC, "full_article", "ok"), [GOOD], mode="trial")
        self.assertEqual(s["summary"], "")
        self.assertTrue(s["pending_summary"].startswith("FMCSA has proposed"))

    def test_spending_cap_pauses_summaries_not_headlines(self):
        s, calls, saved = self.run_main(lambda link, snip: (PUB, SRC, "full_article", "ok"), [GOOD], extra_cfg={"ai_daily_usd": 0.0001})
        self.assertEqual(calls, [])
        self.assertEqual(saved["summary_status.json"]["state"], "limit")
        self.assertEqual(s["status"], "ok")

    def test_service_error_keeps_headlines(self):
        def boom(**kw):
            raise RuntimeError("overloaded")
        import fetch_news
        with mock.patch("summarize.ask", side_effect=RuntimeError("overloaded")):
            s, calls, saved = self.run_main(lambda link, snip: (PUB, SRC, "full_article", "ok"), [GOOD])
        self.assertEqual(saved["summary_status.json"]["state"], "error")
        self.assertEqual(s["status"], "ok")

    def test_excerpt_scope_recorded(self):
        s, _, _ = self.run_main(lambda link, snip: (PUB, SRC, "excerpt", "excerpt only"), [GOOD])
        self.assertEqual(s["source_scope"], "excerpt")


if __name__ == "__main__":
    unittest.main()
