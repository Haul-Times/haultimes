"""
Tests for Facebook / X auto-posting. Nothing here talks to Facebook or X: a fake
platform records every call. Run:  python scripts/test_social.py
"""

import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import social as so  # noqa: E402

# 2 PM Eastern on a Monday: inside posting hours
NOW = datetime(2026, 11, 9, 19, 0, tzinfo=timezone.utc)


def story(i, title, source="Truck News", hours=1, score=75, cat="regs", **kw):
    s = {"id": "s%03d" % i, "slug": "story-%d" % i, "title": title, "orig_title": title, "source": source,
         "link": "https://example.com/a%d" % i, "url_key": "https://example.com/a%d" % i,
         "published": (NOW - timedelta(hours=hours)).isoformat(), "status": "ok", "kind": "news",
         "labels": [], "importance": score, "category": cat, "summary": "", "why": "", "date_known": True}
    s.update(kw)
    return s


def cfg(**kw):
    c = dict(so.DEFAULTS["facebook"], skip=[], publish_now=[], captions={}, min_score=60, topic_gap_hours=0)
    c.update(kw)
    return c


class FakeSite:
    """Story pages the way build_site.py writes them."""

    def __init__(self, stories):
        self.dir = tempfile.mkdtemp()
        for s in stories:
            d = os.path.join(self.dir, "story", s["slug"])
            os.makedirs(d)
            with open(os.path.join(d, "index.html"), "w") as f:
                f.write('<meta property="og:title" content="%s | HaulTimes"><strong>%s</strong> <a href="/out/%s/">Read</a>'
                        % (s["title"], s["source"], s["id"]))

    def close(self):
        shutil.rmtree(self.dir)


class FakePlatform:
    """Pretends to be Facebook. `script` lists what each post call does."""

    def __init__(self, script=None, existing=None):
        self.script = list(script or [])
        self.posts = []
        self.existing = existing or {}
        self.finds = 0

    def post(self, message, link=None):
        action = self.script.pop(0) if self.script else "ok"
        if isinstance(action, Exception):
            raise action
        if action == "ok_then_timeout":   # the platform got it, but we never heard back
            self.existing[message] = "fb_%d" % (len(self.existing) + 1)
            raise so.Uncertain("timed out")
        pid = "fb_%d" % (len(self.posts) + 1)
        self.posts.append((message, link))
        self.existing[message] = pid
        return pid, "https://www.facebook.com/" + pid

    def find(self, message, since):
        self.finds += 1
        pid = self.existing.get(message)
        return (pid, "https://www.facebook.com/" + pid) if pid else None


class Base(unittest.TestCase):
    def setUp(self):
        self.stories = [story(1, "FMCSA finalizes English proficiency rule for truck drivers", score=85),
                        story(2, "Diesel prices climb for third straight week, truckers squeezed", cat="fuel", score=70, hours=2),
                        story(3, "Spot truckload rates jump as capacity tightens before Thanksgiving", cat="rates", score=65, hours=3)]
        self.site = FakeSite(self.stories)
        self.st = so.new_state()

    def tearDown(self):
        self.site.close()

    def run_live(self, client, c=None, now=NOW, stories=None):
        return so.run_platform("facebook", stories or self.stories, c or cfg(mode="live"), self.st, now,
                               self.site.dir, client, ["SECRET_TOKEN_123"])


class Selection(Base):

    def test_queue_only_good_fresh_unique_stories(self):
        extra = [story(4, "Trucker arrested for DUI in Arizona", kind="crime", score=30),
                 story(5, "Lockdown Security launches dashcam kit", labels=["Company announcement"]),
                 story(6, "Old news: FMCSA proposes rule", hours=40),
                 story(7, "FMCSA finalizes English-proficiency rule for truck drivers nationwide", source="CDLLife"),  # same event as #1
                 story(8, "Spot rates jump", link="https://example.com/a3", url_key="https://example.com/a3", score=61, hours=6),           # same article as #3
                 story(9, "No date story about truckers", date_known=False),
                 story(10, "Hidden duplicate", status="duplicate"),
                 story(11, "Minor-source story about trucking", source="The Good Men Project")]
        allst = self.stories + extra
        site = FakeSite(allst)
        try:
            so.queue_new("facebook", allst, cfg(), self.st, NOW, site.dir)
        finally:
            site.close()
        self.assertEqual(sorted(self.st["items"]), ["s001", "s002", "s003"])

    def test_requeue_is_idempotent(self):
        so.queue_new("facebook", self.stories, cfg(), self.st, NOW, self.site.dir)
        so.queue_new("facebook", self.stories, cfg(), self.st, NOW + timedelta(minutes=15), self.site.dir)
        self.assertEqual(len(self.st["items"]), 3)

    def test_followup_with_new_development_allowed(self):
        so.queue_new("facebook", self.stories, cfg(), self.st, NOW, self.site.dir)
        f = story(12, "FMCSA English proficiency rule for truck drivers now final", followup_of="s001")
        site = FakeSite([f])
        try:
            so.queue_new("facebook", [f], cfg(), self.st, NOW, site.dir)
        finally:
            site.close()
        self.assertIn("s012", self.st["items"])

    def test_missing_page_blocks_post(self):
        s = story(13, "FMCSA announces new truck inspection blitz")
        so.queue_new("facebook", [s], cfg(), self.st, NOW, self.site.dir)  # no page built for it
        self.assertNotIn("s013", self.st["items"])


class Captions(unittest.TestCase):

    def test_headline_only_adds_nothing(self):
        s = story(1, "FMCSA finalizes English proficiency rule for truck drivers")
        c = so.facebook_caption(s)
        self.assertTrue(c.startswith("FMCSA finalizes English proficiency rule for truck drivers."))
        self.assertIn("Reported by Truck News.", c)
        self.assertLessEqual(len([w for w in c.split() if w.startswith("#")]), 2)
        self.assertIn("#FMCSA", c)
        self.assertNotIn("http", c)  # the link goes in Facebook's link field (with preview card)

    def test_summary_used_when_available_and_kept_under_80_words(self):
        s = story(1, "Diesel prices climb for third straight week", cat="fuel",
                  summary="Average on-highway diesel rose 6 cents to $4.12 a gallon, the EIA said Monday.",
                  why="Carriers without fuel surcharges absorb the full increase.")
        c = so.facebook_caption(s)
        self.assertIn("EIA said Monday", c)
        self.assertIn("#Diesel", c)
        self.assertLessEqual(so.words(c), 80)

    def test_fmcsa_tag_only_when_fmcsa(self):
        self.assertNotIn("#FMCSA", so.hashtags(story(1, "Ontario expands truck enforcement pilot")))
        self.assertIn("#CanadianTrucking", so.hashtags(story(1, "Ontario expands truck enforcement pilot")))
        self.assertEqual(so.hashtags(story(1, "Brake Safety Week puts 2,369 trucks out of service across North America")), ["#Trucking"])

    def test_publisher_domain_names_do_not_become_links(self):
        self.assertEqual(so.publisher({"source": "TheTrucker.com"}), "TheTrucker")
        self.assertEqual(so.publisher({"source": "KWBG Radio | Boone, Io"}), "KWBG Radio")

    def test_x_text_fits_and_counts_like_x(self):
        long = story(1, "Federal budget offers trucking tax breaks, border investments, Driver Inc. enforcement measures, "
                        "new rest-area funding, cross-border inspection staffing and a review of cabotage rules for "
                        "carriers operating between Canada and the United States")
        t = so.x_text(long)
        self.assertLessEqual(so.x_weighted_length(t), 280)
        self.assertNotIn("measures, new", t[:5])
        self.assertIn("utm_content=s001", t)
        self.assertIn("utm_source=x", t)
        self.assertFalse(t.split("\n")[0].endswith(" "))

    def test_weighted_length_rules(self):
        self.assertEqual(so.x_weighted_length("Hello, world! 👋"), 16)
        self.assertEqual(so.x_weighted_length("https://haultimes.com/story/" + "x" * 200), 23)
        self.assertEqual(so.x_weighted_length("日本"), 4)
        self.assertEqual(so.x_weighted_length("café"), 4)   # NFC: café = 4
        self.assertEqual(so.x_weighted_length("👨‍👩‍👧"), 2)


class Scheduling(Base):

    def test_no_daily_cap_only_spacing_and_hours(self):
        many = [story(20 + i, "Carrier news item number %d about trucking fleets and freight rates" % i, score=70,
                      hours=0.5, cat=["rates", "regs", "fuel", "equip", "drivers", "border", "other"][i % 7],
                      source=["FreightWaves", "Transport Topics", "Truck News", "CBC"][i % 4]) for i in range(10)]
        # make every headline a different event
        for i, m in enumerate(many):
            m["title"] = m["orig_title"] = ["Spot rates climb in Midwest", "FMCSA audits broker registrations",
                                            "Diesel tops $4 in Ontario", "Trailer orders slump in October",
                                            "Teamsters ratify grocery contract", "CBSA adds lanes at Lacolle",
                                            "Werner buys regional fleet", "Port drayage waits ease in Savannah",
                                            "California clean truck rule delayed", "Truck parking grant awarded in Texas"][i]
        site = FakeSite(many)
        try:
            c = cfg(mode="live", min_gap_minutes=30, hours=[6, 22], max_age_hours=99)
            fb = FakePlatform()
            t = NOW
            for _ in range(24):          # six hours of 15-minute runs
                so.run_platform("facebook", many, c, self.st, t, site.dir, fb, ["T"])
                t += timedelta(minutes=15)
        finally:
            site.close()
        self.assertEqual(len(fb.posts), 10)    # everything worthwhile went out: no daily maximum
        times = sorted(datetime.fromisoformat(r["posted_at"]) for r in self.st["items"].values() if r["status"] == "posted")
        self.assertTrue(all(b - a >= timedelta(minutes=30) for a, b in zip(times, times[1:])))  # one at a time, spaced

    def test_spacing_and_hours(self):
        c = cfg(mode="live", min_gap_minutes=90, hours=[7, 21])
        fb = FakePlatform()
        self.assertIn("posted", self.run_live(fb, c))
        self.assertIn("minimum spacing", self.run_live(fb, c, now=NOW + timedelta(minutes=30)))
        self.assertIn("posted", self.run_live(fb, c, now=NOW + timedelta(minutes=90)))
        night = datetime(2026, 11, 10, 7, 0, tzinfo=timezone.utc)  # 2 AM Eastern
        self.assertIn("outside posting hours", self.run_live(fb, c, now=night))
        self.assertEqual(len(fb.posts), 2)

    def test_breaking_news_jumps_the_queue_and_quiet_hours(self):
        routine = [story(30 + i, t, score=72, hours=1) for i, t in enumerate(
            ["Spot rates climb in Midwest", "Trailer orders slump in October", "Werner buys regional fleet"])]
        brk = story(40, "FMCSA orders immediate shutdown of 300 carriers in fraud crackdown", source="FreightWaves",
                    score=92, hours=0.3)
        site = FakeSite(routine + [brk])
        try:
            c = cfg(mode="live", min_gap_minutes=30, hours=[6, 22])
            fb = FakePlatform()
            so.run_platform("facebook", routine + [brk], c, self.st, NOW, site.dir, fb, ["T"])
            self.assertTrue(fb.posts[0][0].startswith("FMCSA orders immediate shutdown"))
            # at 2 AM a breaking story still goes; routine ones wait
            night = datetime(2026, 11, 10, 7, 0, tzinfo=timezone.utc)
            st2 = so.new_state()
            late = story(41, "Ambassador Bridge closed to trucks after structural damage", source="Transport Topics",
                         score=95, hours=0.2, published=(night - timedelta(minutes=10)).isoformat())
            site2 = FakeSite([late])
            try:
                fb2 = FakePlatform()
                so.run_platform("facebook", [late], c, st2, night, site2.dir, fb2, ["T"])
                self.assertEqual(len(fb2.posts), 1)
                self.assertIn("breaking", st2["decisions"][-1]["reason"])
            finally:
                site2.close()
        finally:
            site.close()

    def test_unverified_big_story_is_not_breaking(self):
        s = story(42, "Huge claim about trucking ban", source="Local Radio", score=95, hours=0.2)
        self.assertIsNone(so.breaking_reason(s, [s], cfg(), NOW))
        other = story(43, "Same claim", source="CBC", status="duplicate", dup_of="s042")
        self.assertIn("confirmed by 1 other outlet", so.breaking_reason(s, [s, other], cfg(), NOW))

    def test_recheck_stale_superseded_redundant(self):
        c = cfg(mode="dry_run", max_age_hours=6)
        so.queue_new("facebook", self.stories, c, self.st, NOW, self.site.dir)
        stories = [dict(x) for x in self.stories]
        stories[1]["status"], stories[1]["dup_of"] = "duplicate", "s001"     # superseded by a stronger report
        stories[2]["published"] = (NOW - timedelta(hours=9)).isoformat()      # went stale
        so.refresh_queue("facebook", stories, c, self.st, NOW)
        self.assertEqual(self.st["items"]["s002"]["status"], "merged")
        self.assertEqual(self.st["items"]["s003"]["status"], "expired")
        acts = {d["story_id"]: d["action"] for d in self.st["decisions"]}
        self.assertEqual(acts["s002"], "merged")
        self.assertEqual(acts["s003"], "expired")

    def test_redundant_after_same_event_posted(self):
        a = story(50, "FMCSA finalizes English proficiency rule for truck drivers", score=80)
        b = story(51, "FMCSA finalizes English proficiency rule for truck drivers nationwide", source="CBC", score=70)
        site = FakeSite([a, b])
        try:
            c = cfg(mode="dry_run")
            so.run_platform("facebook", [a, b], c, self.st, NOW, site.dir, None, [])
        finally:
            site.close()
        self.assertEqual(self.st["items"]["s050"]["status"], "dry_run")
        self.assertNotIn("s051", self.st["items"])
        self.assertTrue(any(d["story_id"] == "s051" and d["action"] == "merged" for d in self.st["decisions"]))

    def test_stronger_source_replaces_weaker_in_queue(self):
        weak = story(60, "Ontario closes Highway 401 to trucks near Kingston after crash", source="Kingston Radio", score=72, hours=2)
        site = FakeSite([weak])
        c = cfg(mode="dry_run", min_gap_minutes=600)
        so.queue_new("facebook", [weak], c, self.st, NOW, site.dir)
        strong = story(61, "Ontario closes Highway 401 to trucks near Kingston after crash, detours set", source="Transport Topics",
                       score=78, hours=1)
        site2 = FakeSite([strong])
        try:
            so.queue_new("facebook", [weak, strong], c, self.st, NOW, site2.dir)
        finally:
            site.close(); site2.close()
        self.assertEqual(self.st["items"]["s060"]["status"], "merged")
        self.assertEqual(self.st["items"]["s061"]["status"], "queued")

    def test_platform_specific_selection(self):
        """A story can qualify for X but not Facebook (higher bar, and no repeat topic within hours)."""
        mid = story(70, "Trailer orders slump in October", cat="equip", score=65)
        site = FakeSite([mid])
        try:
            fb_st, x_st = so.new_state(), so.new_state()
            so.queue_new("facebook", [mid], dict(cfg(), min_score=70), fb_st, NOW, site.dir)
            so.queue_new("x", [mid], dict(cfg(), min_score=60), x_st, NOW, site.dir)
        finally:
            site.close()
        self.assertNotIn("s070", fb_st["items"])
        self.assertIn("s070", x_st["items"])
        # topic gap: second Regulations story held on Facebook for a few hours
        c = cfg(mode="dry_run", min_gap_minutes=0, topic_gap_hours=4)
        r1 = story(71, "FMCSA audits broker registrations", score=72)
        r2 = story(72, "California clean truck rule delayed", score=72)
        site = FakeSite([r1, r2])
        try:
            st = so.new_state()
            so.run_platform("facebook", [r1, r2], c, st, NOW, site.dir, None, [])
            msg = so.run_platform("facebook", [r1, r2], c, st, NOW + timedelta(minutes=15), site.dir, None, [])
        finally:
            site.close()
        self.assertIn("nothing to post", msg)
        self.assertTrue(any(d["action"] == "held" for d in st["decisions"]))

    def test_empty_slot_is_skipped(self):
        fb = FakePlatform()
        self.assertIn("nothing to post", so.run_platform("facebook", [], cfg(mode="live"), self.st, NOW, self.site.dir, fb, []))
        self.assertEqual(fb.posts, [])

    def test_most_important_goes_first(self):
        fb = FakePlatform()
        self.run_live(fb)
        self.assertTrue(fb.posts[0][0].startswith("FMCSA finalizes"))
        self.assertIn("utm_source=facebook", fb.posts[0][1])
        self.assertIn("utm_medium=organic_social", fb.posts[0][1])
        self.assertIn("utm_content=s001", fb.posts[0][1])

    def test_skip_publish_now_and_caption_edit(self):
        c = cfg(mode="live", skip=["s001"], publish_now=["s003"], captions={"s003": "Spot rates are up ahead of the holiday."})
        fb = FakePlatform()
        self.run_live(fb, c)
        self.assertEqual(self.st["items"]["s001"]["status"], "skipped")
        self.assertTrue(fb.posts[0][0].startswith("Spot rates are up ahead of the holiday."))
        # publish_now ignores posting hours
        st2 = so.new_state()
        night = datetime(2026, 11, 10, 7, 0, tzinfo=timezone.utc)
        fb2 = FakePlatform()
        so.run_platform("facebook", self.stories, cfg(mode="live", publish_now=["s002"], max_age_hours=99), st2, night, self.site.dir, fb2, [])
        self.assertEqual(len(fb2.posts), 1)

    def test_dry_run_never_calls_the_platform(self):
        fb = FakePlatform()
        msg = so.run_platform("facebook", self.stories, cfg(mode="dry_run"), self.st, NOW, self.site.dir, fb, [])
        self.assertIn("would post s001", msg)
        self.assertEqual(fb.posts, [])
        self.assertEqual(fb.finds, 0)

    def test_off_does_nothing(self):
        self.assertEqual(so.run_platform("facebook", self.stories, cfg(mode="off"), self.st, NOW, self.site.dir, None, []), "off")
        self.assertEqual(self.st["items"], {})


class Failures(Base):

    def test_missing_credentials(self):
        msg = so.run_platform("facebook", self.stories, cfg(mode="live"), self.st, NOW, self.site.dir, None, [])
        self.assertIn("credentials missing", msg)
        self.assertTrue(all(r["status"] == "queued" for r in self.st["items"].values()))
        self.assertEqual(so.make_client("facebook", {})[0], None)
        self.assertEqual(so.make_client("x", {"X_API_KEY": "k"})[0], None)

    def test_token_error_pauses_until_new_token(self):
        fb = FakePlatform([so.AuthError("Facebook error 190: Error validating access token SECRET_TOKEN_123")])
        msg = self.run_live(fb)
        self.assertIn("paused", msg)
        self.assertNotIn("SECRET_TOKEN_123", msg)
        self.assertNotIn("SECRET_TOKEN_123", str(self.st))
        self.assertEqual(self.st["items"]["s001"]["status"], "queued")
        self.assertIn("paused", self.run_live(fb, now=NOW + timedelta(hours=4)))     # still paused, same token
        out = so.run_platform("facebook", self.stories, cfg(mode="live"), self.st, NOW + timedelta(hours=4),
                              self.site.dir, fb, ["NEW_TOKEN_456"])                     # new token -> resumes
        self.assertIn("posted", out)

    def test_rate_limit_backs_off(self):
        later = NOW + timedelta(hours=1)
        fb = FakePlatform([so.RateLimited("Facebook error 4: rate limit", later)])
        self.assertIn("rate limited", self.run_live(fb))
        self.assertIn("rate limited", self.run_live(fb, now=NOW + timedelta(minutes=30)))  # whole account waits
        self.assertEqual(fb.posts, [])
        self.assertIn("posted", self.run_live(fb, now=NOW + timedelta(minutes=61)))

    def test_temporary_failures_retry_with_backoff_then_stop(self):
        fb = FakePlatform([so.Temporary("unreachable")] * 10)
        c = cfg(mode="live", min_gap_minutes=0, max_per_day=99, max_age_hours=99)
        t = NOW
        for _ in range(12):
            self.run_live(fb, c, now=t)
            t += timedelta(hours=8)
            if t.astimezone(so.EASTERN).hour >= 21 or t.astimezone(so.EASTERN).hour < 7:
                t += timedelta(hours=10)
        r = self.st["items"]["s001"]
        self.assertEqual(r["status"], "failed")
        self.assertEqual(r["attempts"], so.MAX_ATTEMPTS)

    def test_timeout_is_reconciled_not_reposted(self):
        fb = FakePlatform(["ok_then_timeout"])
        self.assertIn("unclear", self.run_live(fb))
        self.assertEqual(self.st["items"]["s001"]["status"], "uncertain")
        msg = self.run_live(fb, now=NOW + timedelta(minutes=20))
        self.assertEqual(self.st["items"]["s001"]["status"], "posted")
        self.assertEqual(fb.posts, [])          # never sent a second time
        self.assertIn("nothing to post", msg)   # gap still applies after the confirmed post

    def test_timeout_that_did_not_post_is_retried(self):
        fb = FakePlatform([so.Uncertain("timed out"), "ok"])
        self.run_live(fb)
        self.run_live(fb, now=NOW + timedelta(minutes=20))
        self.assertEqual(self.st["items"]["s001"]["status"], "posted")
        self.assertEqual(len(fb.posts), 1)

    def test_crash_mid_post_is_reconciled(self):
        """The run died after marking 'posting' (and maybe after Facebook accepted it)."""
        so.queue_new("facebook", self.stories, cfg(), self.st, NOW, self.site.dir)
        r = self.st["items"]["s001"]
        r.update(status="posting", attempts=1, last_attempt_at=NOW.isoformat(), posted_at=NOW.isoformat())
        fb = FakePlatform(existing={r["caption"]: "fb_99"})
        self.run_live(fb, now=NOW + timedelta(minutes=15))
        self.assertEqual(r["status"], "posted")
        self.assertEqual(r["post_id"], "fb_99")
        self.assertEqual(fb.posts, [])

    def test_refused_post_is_not_retried(self):
        fb = FakePlatform([so.Permanent("Facebook error 368: content blocked")])
        self.run_live(fb)
        self.assertEqual(self.st["items"]["s001"]["status"], "failed")


class ApiClients(unittest.TestCase):
    """Request shape and error mapping, with a fake HTTP layer."""

    def test_facebook_request_and_errors(self):
        calls = []

        def http(method, url, data=None, headers=None, json_body=None, timeout=25):
            calls.append((method, url, data))
            return 200, {}, {"id": "123_456"}
        c = so.FacebookClient("123", "TOKEN", http)
        self.assertEqual(c.post("Hello", "https://haultimes.com/story/x/")[0], "123_456")
        self.assertEqual(calls[0][1], "https://graph.facebook.com/v25.0/123/feed")
        self.assertEqual(calls[0][2]["link"], "https://haultimes.com/story/x/")
        for body, exc in [({"error": {"code": 190, "type": "OAuthException", "message": "expired"}}, so.AuthError),
                          ({"error": {"code": 4, "message": "limit"}}, so.RateLimited),
                          ({"error": {"code": 2, "is_transient": True, "message": "temp"}}, so.Uncertain),
                          ({"error": {"code": 368, "message": "blocked"}}, so.Permanent)]:
            c = so.FacebookClient("123", "TOKEN", lambda *a, b=body, **k: (400, {}, b))
            with self.assertRaises(exc):
                c.post("Hello", "https://haultimes.com/")

    def test_x_request_signed_and_errors(self):
        seen = {}

        def http(method, url, data=None, headers=None, json_body=None, timeout=25):
            seen.update(method=method, url=url, auth=headers["Authorization"], body=json_body)
            return 201, {}, {"data": {"id": "999", "text": "x"}}
        c = so.XClient("ck", "cs", "at", "as", http)
        self.assertEqual(c.post("Hello")[0], "999")
        self.assertEqual(seen["url"], "https://api.x.com/2/tweets")
        self.assertEqual(seen["body"], {"text": "Hello"})
        self.assertTrue(seen["auth"].startswith("OAuth "))
        for k in ("oauth_consumer_key", "oauth_signature", "oauth_token", 'oauth_signature_method="HMAC-SHA1"'):
            self.assertIn(k, seen["auth"])
        for status, headers, exc in [(401, {}, so.AuthError), (402, {}, so.AuthError),
                                     (429, {"x-rate-limit-reset": str(int(NOW.timestamp()) + 900)}, so.RateLimited),
                                     (503, {}, so.Uncertain), (400, {}, so.Permanent)]:
            c = so.XClient("ck", "cs", "at", "as", lambda *a, s=status, h=headers, **k: (s, h, {"detail": "x"}))
            with self.assertRaises(exc):
                c.post("Hello")

    def test_oauth1_signature_matches_known_example(self):
        """Twitter's documented OAuth 1.0a signing example."""
        c = so.XClient("xvz1evFS4wEEPTGEFPHBog", "kAcSOqF21Fu85e7zjz7ZN2U4ZRhfV3WpwPAoE3Z7kBw",
                       "370773112-GmHxMAgYyLbNEtIKZeRNFsMKPR9EyMZeS9weJAEb", "LswwdoUaIvS8ltyTt5jkRh4J50vUPVVHtR2YPi5kE", None)
        import time as _t
        orig_time, orig_tok = _t.time, so.secrets.token_hex
        so.time.time = lambda: 1318622958
        so.secrets.token_hex = lambda n: "kYjzVBB8Y0ZFabxSWbWovY3uYSQ2pTgmZeNu2VS4cg"
        try:
            h = c._auth("POST", "https://api.twitter.com/1.1/statuses/update.json",
                        {"include_entities": "true", "status": "Hello Ladies + Gentlemen, a signed OAuth request!"})
        finally:
            so.time.time, so.secrets.token_hex = orig_time, orig_tok
        self.assertIn('oauth_signature="hCtSmYh%2BiHYCEqBWrE7C7hYmtUk%3D"', h)


class Traffic(unittest.TestCase):

    def test_summarize_counts_social_visits_and_clicks(self):
        import traffic
        rows = [{"count": 5, "dimensions": {"date": "2026-11-09", "refererHost": "l.facebook.com", "requestPath": "/story/a-1/"}},
                {"count": 3, "dimensions": {"date": "2026-11-09", "refererHost": "t.co", "requestPath": "/story/b-2/"}},
                {"count": 2, "dimensions": {"date": "2026-11-09", "refererHost": "haultimes.com", "requestPath": "/out/a1/"}},
                {"count": 7, "dimensions": {"date": "2026-11-09", "refererHost": "", "requestPath": "/"}}]
        d = traffic.summarize(rows)["2026-11-09"]
        self.assertEqual((d["from_facebook"], d["from_x"], d["story_views"], d["outbound"], d["page_views"]), (5, 3, 8, 2, 17))

    def test_no_token_means_no_calls(self):
        import traffic
        self.assertEqual(traffic.update(NOW, env={})["status"], "Cloudflare token not set up")

    def test_frequency_by_day(self):
        st = so.new_state()
        st["items"] = {"a": {"status": "posted", "posted_at": NOW.isoformat()},
                       "b": {"status": "dry_run", "posted_at": NOW.isoformat()},
                       "c": {"status": "skipped", "posted_at": None}}
        self.assertEqual(so.frequency(st), {"2026-11-09": {"posted": 1, "dry_run": 1}})


if __name__ == "__main__":
    unittest.main(verbosity=1)
