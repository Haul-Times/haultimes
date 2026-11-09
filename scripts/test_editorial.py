"""
Tests for the HaulTimes editorial rules. Run:  python scripts/test_editorial.py

Covers the problems seen on the live site (Nov 8, 2026) and real trucking
stories that must still get through, plus the full pipeline: feed parsing,
dates, duplicates, editor overrides, and that every page uses the same list.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import editorial as ed  # noqa: E402
import fetch_news as fn  # noqa: E402

NOW = datetime(2026, 11, 8, 22, 0, tzinfo=timezone.utc)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def verdict(title, source="Local News"):
    return ed.assess(title, source)


def rec(i, title, source, hours=1, link=None, cat=None):
    return {"id": "t%02d" % i, "slug": "s%d" % i, "title": title, "orig_title": title, "source": source,
            "link": link or "https://example.com/story-%d" % i, "summary": "", "why": "", "ai": False,
            "published": (NOW - timedelta(hours=hours)).isoformat(), "image": "", "category": cat or "other",
            "importance": 50}


class ObservedFailures(unittest.TestCase):
    """Every item here was on haultimes.com and should not have been."""

    def test_drive_by_truckers(self):
        for t, s in [("Drive By Truckers", "Knoxville News Sentinel"),
                     ("Drive-By Truckers Homecoming Hits Portland's Revolution Hall", "Hoodline")]:
            v = verdict(t, s)
            self.assertEqual(v["status"], "rejected", t)
            self.assertIn("music", v["reasons"][0])

    def test_nfi_recruitment_listings(self):
        for code in ("LPNB", "HPNB", "LPB", "HPB"):
            v = verdict("NFI %s - Truck Driving Jobs" % code, "TheTrucker.com")
            self.assertEqual(v["status"], "rejected")
            self.assertIn("job", v["reasons"][0])

    def test_other_job_ads(self):
        for t in ["CDL Truck Driving Job near El Paso, TX | LOCAL CDL-A DRIVERS WANTED | HOME DAILY | FLEXIBLE SHIFTS",
                  "CDL Truck Driving Job near Columbus, GA | Class-A CDL Over The Road Owner Operator"]:
            self.assertEqual(verdict(t, "TheTrucker.com")["status"], "rejected", t)

    def test_publisher_only_titles(self):
        for t, s in [("- TheTrucker.com", "TheTrucker.com"), ("- Truck News", "Truck News"),
                     ("trucking defence Archives", "Truck News"), ("Logistics & Brokerage Archives", "FreightWaves"),
                     ("Truckload Freight News", "FreightWaves"), ("", "Truck News")]:
            v = verdict(t, s)
            self.assertEqual(v["status"], "rejected", repr(t))
            self.assertIn("headline", v["reasons"][0])

    def test_range_extender_is_equipment(self):
        v = verdict("This New All-In-One Range Extender Is Ready To Go Into Any Electric Truck", "InsideEVs")
        self.assertEqual(v["status"], "ok")
        self.assertEqual(v["category"], "equip")

    def test_ocean_rates_without_trucking_link(self):
        for t, s in [("Freight rates scale new highs despite West Asia lull", "The Financial Express"),
                     ("Soaring Freight Rates Give US Refiners Edge As Crude Discounts Widen", "gCaptain"),
                     ("Ocean freight rates rebound as indicative prices for imported bauxite fall", "AL Circle"),
                     # same kind of story from a neutral-looking source: the mode rule must catch it
                     ("Ocean freight rates will come down eventually, says port operator", "Business Daily"),
                     ("Container shipping rates jump as carriers cut sailings", "Local News"),
                     ("Venezuela's Oil Exports Unchanged Amid High Freight Rates", "Wire Report")]:
            self.assertEqual(verdict(t, s)["status"], "rejected", t)

    def test_other_junk_seen_on_site(self):
        for t, s in [("Why Did Saia (NASDAQ:SAIA) Surge Despite Flat Revenue Growth?", "Kalkine Media"),
                     ("What Comes Next For RXO After A 121% Gain", "Simply Wall St"),
                     ("Why Old Dominion and J.B. Hunt Stock Could Gain From Trucking Rule Changes", "Yahoo Finance"),
                     ("Retread Tires Market Forecast to Expand Through 2035, Driven by Fleet Cost Pressures", "IndexBox"),
                     ("Crazy offer for Arda Güler! Fenerbahçe will make a truckload of money", "Haberler.com"),
                     ("Fareway, Iowa Farm Bureau deliver truckload of protein to Food Bank of Iowa", "Globe Gazette"),
                     ("Hungry Truckers And Tourists Both Swear By Missouri Hick BBQ In Cuba Along Route 66", "Fast Food Club"),
                     ("A Truck Hit His Sedan in Parking Lot. Insurance Claims Both Drivers Are Both At Fault", "Yahoo"),
                     ("Truck Test 2026: 20 Trucks Prepare For N3 Challenge", "SA Trucker"),
                     ("Can FLEETLEAP take the guesswork out of electric truck fleets?", "Australasian Transport"),
                     ("Trucking industry at breaking point: NatRoad", "Prime Mover"),
                     ("Ex-BJD MP faces EOW raids over fund collection from truckers to pay Naxals", "The New Indian Express"),
                     ("Plane clips truck during emergency landing on busy Florida road", "Al Jazeera"),
                     ("2026 Ford F-150 Lightning review: still the pickup to beat", "Car and Driver")]:
            self.assertEqual(verdict(t, s)["status"], "rejected", t)


class LegitimateStories(unittest.TestCase):
    """Real trucking news must still get through, in the right topic."""

    CASES = [
        ("Brake Safety Week puts 2,369 trucks out of service across North America", "Truck News", "regs"),
        ("FMCSA expands complaint system to cover driver training, broker and registration violations", "Truck News", "regs"),
        ("Borderlands Mexico: US foreign-trade zones push to fix USMCA tariff obstacles", "FreightWaves", "border"),
        ("Survey collecting data on tariff impact on Alberta trucking workforce", "Truck News", "border"),
        ("Trucking bankruptcies rise by 38% as high diesel prices squeeze firms", "The Arkansas Democrat-Gazette", "other"),
        ("High diesel prices put brakes on growth for DC-area waste hauling company", "WTOP News", "fuel"),
        ("Diesel tax breaks make limited impact as prices remain high", "The Mighty 790 KFGO", "fuel"),
        ("What would a federal gas tax holiday mean for trucking?", "Transport Topics", "fuel"),
        ("Trucking recovery takes shape, but headwinds temper carrier optimism", "Journal of Commerce", "rates"),
        ("Spot truckload rates climb as capacity tightens ahead of Thanksgiving", "DAT", "rates"),
        ("Third-party axle, engine supply issues dent DTNA truck output", "Transport Topics", "equip"),
        ("The Tesla Semi Had This Reviewer Skeptical. Now He Thinks It's A Game Changer", "InsideEVs", "equip"),
        ("Truckers, warehouse workers for Associated Grocers Northeast go on strike", "WMUR", "drivers"),
        ("Optimal Dynamics says cutting empty truck miles can shrink driver pay", "MarketScale", "drivers"),
        ("PS Logistics acquires Tennessee-based Roane Transportation", "Truck News", "other"),
        ("Navistar Reports Worse-Than-Expected Results, Makes Management Changes", "Heavy Duty Trucking", "other"),
        ("Union Pacific & Norfolk Southern Merger: Trucking Impacts & Benefits", "Commercial Carrier Journal", "other"),
        ("CBP seizes 1,000-plus pounds of meth in produce truck at Texas border", "FreightWaves", "border"),
        ("Operation Highway Shield Removes Nearly 400 Truckers, Vehicles From US Roads", "NTD News", "regs"),
        ("Rolling returns: Fleets exploring benefits of LRR tires", "Transport Topics", "equip"),
        # mentions stocks / another mode / another country, but matters to our readers
        ("Port of Long Beach container surge strains drayage truck capacity", "Journal of Commerce", None),
        ("Canada-U.S. tariff talks stall, cross-border truckers brace for delays", "CBC", "border"),
        ("Minnesota trucking company teams with Semper Forward to hire veterans", "Truckers News", "drivers"),
    ]

    def test_accepted_and_categorized(self):
        for title, source, cat in self.CASES:
            v = verdict(title, source)
            self.assertEqual(v["status"], "ok", "%s -> %s" % (title, v["reasons"]))
            if cat:
                self.assertEqual(v["category"], cat, title)

    def test_rail_crossing_is_not_cross_border(self):
        v = verdict("Train crashes into transport truck at Ontario rail crossing", "insauga.com")
        self.assertNotEqual(v["category"], "border")
        self.assertEqual(v["kind"], "incident")

    def test_labels(self):
        self.assertIn("Company announcement",
                      verdict("Lockdown Security launches dashcam kit for B.C. trucking requirements", "Truck News")["labels"])
        self.assertIn("Press release",
                      verdict("Fleet software maker adds fuel-tax reporting for trucking fleets", "PR Newswire")["labels"])
        # government action is not a company announcement
        self.assertEqual(verdict("FMCSA launches revised Complaint Center for trucking violations", "Truckers News")["labels"], [])


class Ranking(unittest.TestCase):

    def test_minor_crash_and_stock_commentary_never_lead(self):
        crash = dict(rec(1, "Freight truck runs off road in Camden, prompting traffic advisory", "newscentermaine.com"),
                     **verdict("Freight truck runs off road in Camden, prompting traffic advisory", "newscentermaine.com"))
        self.assertFalse(ed.lead_eligible(crash))
        big = dict(rec(2, "Brake Safety Week puts 2,369 trucks out of service across North America", "Truck News", hours=30),
                   **verdict("Brake Safety Week puts 2,369 trucks out of service across North America", "Truck News"))
        self.assertGreater(ed.rank_score(big, NOW), ed.rank_score(crash, NOW))

    def test_major_route_closure_kept_as_disruption(self):
        v = verdict("Fiery truck crash shuts down Interstate 81 for hours, freight traffic diverted", "WHSV")
        self.assertEqual(v["status"], "ok")
        self.assertEqual(v["kind"], "disruption")

    def test_age_counts_by_publication_time(self):
        fresh = dict(rec(1, "A", "Truck News", hours=1), importance=60)
        old = dict(rec(2, "B", "Truck News", hours=48), importance=60)
        self.assertGreater(ed.rank_score(fresh, NOW), ed.rank_score(old, NOW))


class Pipeline(unittest.TestCase):

    def test_feed_dates_are_never_invented(self):
        rss = """<?xml version="1.0"?><rss><channel>
<item><title>FMCSA proposes new hours-of-service pilot for truck drivers - Truck News</title><link>https://www.trucknews.com/a/?utm_source=rss</link>
<source url="https://trucknews.com">Truck News</source><pubDate>Fri, 06 Nov 2026 19:16:35 +0000</pubDate></item>
<item><title>Truckload spot rates firm up in November market update</title><link>https://example.com/b</link></item>
<item><title>Diesel prices climb for third week, truckers say</title><link>https://example.com/c</link><pubDate>Sat, 01 Jan 2050 00:00:00 +0000</pubDate></item>
</channel></rss>"""
        tmp = tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False)
        tmp.write(rss)
        tmp.close()
        items = fn.fetch_feed({"url": "file://" + tmp.name, "source": "Feed"})
        os.unlink(tmp.name)
        self.assertEqual(items[0]["headline"], "FMCSA proposes new hours-of-service pilot for truck drivers")
        self.assertEqual(items[0]["source"], "Truck News")
        self.assertTrue(items[0]["published"].startswith("2026-11-06T19:16"))
        self.assertIsNone(items[1]["published"])   # no date in the feed
        self.assertIsNone(items[2]["published"])   # date in the future
        r = fn.new_record("x1", items[1], NOW)
        ed.reprocess([r], NOW)
        self.assertEqual(r["status"], "review")
        self.assertIn("no publication date", r["reasons"][0])

    def test_duplicates(self):
        stories = [
            rec(1, "FMCSA expands complaint system to cover driver training, broker and registration violations", "Truck News", 3),
            rec(2, "FMCSA launches 'enhanced' online system for reporting violations of federal trucking regulations", "CDLLife", 3.1),
            rec(3, "Army veteran Kearney wins Kenworth W990 in Pilot contest", "Truck News", 5),
            rec(4, "Army vet wins custom Kenworth W990 as Pilot Road Warrior", "eTrucker", 6),
            rec(5, "Spot truckload rates climb ahead of Thanksgiving", "FreightWaves", 2, link="https://www.freightwaves.com/news/spot?utm_source=x"),
            rec(6, "Spot rates climb before Thanksgiving holiday", "Yahoo", 1, link="https://freightwaves.com/news/spot/amp/"),
            rec(7, "Trucking bankruptcies rise by 38% as high diesel prices squeeze firms", "The Arkansas Democrat-Gazette", 4),
            rec(8, "Trucking bankruptcies rise by 38% as high diesel prices squeeze firms", "Yahoo", 2),
            rec(9, "Trucking industry at a crossroads as safety, compliance concerns grow", "MidlandToday.ca", 4),
            rec(10, "Carriers must look beyond compliance to manage growing legal risks: Traffix lawyer", "Truck News", 4),
        ]
        ed.reprocess(stories, NOW)
        st = {s["id"]: s for s in stories}
        self.assertEqual(st["t02"]["status"], "duplicate")   # same event, weaker source
        self.assertEqual(st["t01"]["status"], "ok")
        self.assertEqual(st["t04"]["status"], "duplicate")
        self.assertEqual(st["t06"]["status"], "duplicate")   # same article, tracking/AMP link
        self.assertEqual(st["t08"]["status"], "duplicate")   # syndicated copy
        self.assertEqual(st["t07"]["status"], "ok")          # original kept
        self.assertEqual(st["t09"]["status"], "ok")          # different stories that share a word
        self.assertEqual(st["t10"]["status"], "ok")

    def test_followup_with_new_development_is_kept(self):
        stories = [rec(1, "FMCSA proposes English proficiency rule for truck drivers", "FreightWaves", 40),
                   rec(2, "FMCSA English proficiency rule for truck drivers now final", "FreightWaves", 2)]
        ed.reprocess(stories, NOW)
        self.assertEqual([s["status"] for s in stories], ["ok", "ok"])

    def test_reprocess_never_deletes_and_overrides_work(self):
        stories = [rec(1, "Drive By Truckers", "Knoxville News Sentinel"),
                   rec(2, "Brake Safety Week puts 2,369 trucks out of service across North America", "Truck News"),
                   rec(3, "Spot truckload rates climb ahead of Thanksgiving", "FreightWaves"),
                   rec(4, "Trucking bankruptcies rise by 38% as high diesel prices squeeze firms", "Arkansas Democrat-Gazette")]
        backup = ed.OVERRIDES_FILE
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump({"pin": ["t03"], "exclude": ["Brake Safety Week puts"], "category": {"t04": "fuel"}}, tmp)
        tmp.close()
        ed.OVERRIDES_FILE = tmp.name
        try:
            ed.reprocess(stories, NOW)
        finally:
            ed.OVERRIDES_FILE = backup
            os.unlink(tmp.name)
        self.assertEqual(len(stories), 4)
        st = {s["id"]: s for s in stories}
        self.assertEqual(st["t01"]["status"], "rejected")
        self.assertEqual(st["t02"]["status"], "rejected")
        self.assertEqual(st["t02"]["reasons"], ["hidden by editor"])
        self.assertTrue(st["t03"]["pinned"])
        self.assertTrue(ed.lead_eligible(st["t03"]))
        self.assertEqual(st["t04"]["category"], "fuel")
        self.assertEqual([s["id"] for s in ed.eligible(stories)], ["t03", "t04"] if st["t03"]["published"] >= st["t04"]["published"] else ["t04", "t03"])

    def test_every_page_uses_the_same_list(self):
        """Build the real site from a test copy of the live data and check no hidden story appears anywhere."""
        live = os.environ.get("HAULTIMES_TEST_NEWS")
        if not live or not os.path.exists(live):
            self.skipTest("set HAULTIMES_TEST_NEWS to a news.json to run the full build test")
        work = tempfile.mkdtemp()
        try:
            data, site = os.path.join(work, "data"), os.path.join(work, "site")
            os.makedirs(data)
            stories = json.loads(read(live))
            for s in stories:
                s.pop("status", None)
            with open(os.path.join(data, "news.json"), "w") as f:
                json.dump(stories, f)
            env = dict(os.environ, HAULTIMES_DATA=data, HAULTIMES_SITE=site)
            subprocess.run([sys.executable, os.path.join(HERE, "build_site.py")], check=True, env=env,
                           capture_output=True)
            checked = json.loads(read(os.path.join(data, "news.json")))
            ed.reprocess(checked)
            hidden = [s for s in checked if s["status"] != "ok"]
            shown = ed.eligible(checked)
            pages = []
            for root, _, files in os.walk(site):
                if "/editor" in root:
                    continue
                for f in files:
                    if f.endswith((".html", ".xml")):
                        pages.append(read(os.path.join(root, f)))
            html_all = "\n".join(pages)
            import html as h
            for s in hidden:
                self.assertNotIn(h.escape(s["link"], quote=True), html_all, "hidden story on a page: " + s["title"])
            topics = "\n".join(read(os.path.join(site, "topic", d, "index.html"))
                               for d in os.listdir(os.path.join(site, "topic")))
            home = read(os.path.join(site, "index.html"))
            for s in shown:
                self.assertIn(h.escape(s["link"], quote=True), topics, "shown story missing from its topic page: " + s["title"])
            self.assertTrue(any(h.escape(s["link"], quote=True) in home for s in shown))
        finally:
            shutil.rmtree(work)


if __name__ == "__main__":
    unittest.main(verbosity=1)
