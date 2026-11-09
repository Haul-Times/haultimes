"""
Simulate a day of Facebook/X queue behaviour with the real rules, in dry run.

  python scripts/simulate_social.py quiet|busy  [--json out.json]

Headlines in the scenarios are made up for testing. Every 15 minutes: stories that
have "arrived" are run through the editorial rules (scoring, duplicates), then the
social queue runs for both platforms exactly as in production, with a simulated clock.
"""

import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import editorial  # noqa: E402
import fetch_news  # noqa: E402
import social  # noqa: E402

# (arrival "HH:MM" Eastern, minutes since publication, source, headline). "+1 " prefix = next day.
QUIET = [
    ("05:50", 30, "FreightWaves", "Truckload spot rates slip for second week as freight demand softens"),
    ("08:10", 25, "Truck News", "Ontario adds weekend enforcement blitz for trucks on Highway 401"),
    ("09:30", 40, "Daily Herald", "Trucker honored for helping stranded family on I-80"),
    ("10:15", 5, "TheTrucker.com", "CDL Truck Driving Job near Dayton, OH | Class-A CDL Regional Driver"),
    ("11:40", 20, "Transport Topics", "Diesel prices fall 4 cents, first drop in a month, EIA says"),
    ("13:05", 35, "Commercial Carrier Journal", "Werner Enterprises to acquire Texas flatbed carrier"),
    ("14:20", 15, "WKBN", "Truck crash slows traffic on Route 9 near Canfield"),
    ("15:00", 30, "CDLLife", "FMCSA extends comment period on heavy truck speed limiter proposal"),
    ("16:45", 300, "Yahoo", "Truckload spot rates slip for second week as freight demand softens"),
    ("19:30", 20, "Truck News", "CBSA reports shorter commercial waits at Windsor after new truck lanes open"),
    ("22:30", 25, "FreightWaves", "Trailer orders drop 12% in October as fleets delay purchases"),
]

BUSY = [
    # overnight ingestion: a batch arrives at once
    ("06:00", 240, "FreightWaves", "Truckload tender rejections jump to 9-month high as capacity tightens"),
    ("06:00", 200, "Transport Topics", "Diesel prices surge 11 cents, biggest weekly jump since 2022, EIA says"),
    ("06:00", 180, "Truck News", "Canada and U.S. reach deal to reopen talks on steel tariffs affecting truck parts"),
    ("06:00", 220, "Commercial Carrier Journal", "Knight-Swift to cut 400 jobs at LTL unit as volumes fall"),
    ("06:00", 260, "Heavy Duty Trucking", "Class 8 orders slump 18% in October, ACT Research says"),
    ("06:00", 190, "CDLLife", "FMCSA approves English proficiency out-of-service enforcement for Canadian drivers"),
    ("06:00", 210, "Overdrive", "Owner-operators report detention pay disputes rising at grocery warehouses"),
    ("06:00", 230, "Truck News", "Ontario trucking association warns of insurance premium spike for small fleets"),
    ("06:00", 170, "FreightWaves", "Freight brokers face new FMCSA transparency rule audits starting January"),
    ("06:00", 250, "Kalkine Media", "Why Did Old Dominion (NASDAQ:ODFL) Shares Jump Today?"),
    ("06:00", 240, "SA Trucker", "Truck strike blocks N3 highway near Durban"),
    ("06:00", 200, "Transport Topics", "California delays clean truck fleet rule enforcement for one year"),
    # a local first report, then the stronger trade-press report of the same event
    ("09:00", 20, "Windsor Star", "Ambassador Bridge truck lanes closed after crash, police say"),
    ("09:30", 15, "Transport Topics", "Ambassador Bridge truck lanes closed after crash, police say; trucks diverted to Blue Water Bridge"),
    ("10:05", 25, "FreightWaves", "FMCSA proposes stricter broker bond rule for freight brokers"),
    ("10:40", 30, "Journal of Commerce", "LTL carriers raise general rates 5.9% as costs climb"),
    ("11:15", 20, "Truck News", "Quebec truckers protest new carbon fuel charge at border crossings"),
    ("12:00", 30, "Transport Topics", "Teamsters reach tentative deal with grocery distributor, ending strike"),
    # breaking: trade publication, then another outlet confirms
    ("13:40", 10, "FreightWaves", "FMCSA orders immediate shutdown of 340 carriers in nationwide ELD fraud crackdown"),
    ("13:55", 20, "CBC", "FMCSA orders immediate shutdown of 340 carriers in nationwide ELD fraud crackdown"),
    ("14:30", 35, "Overdrive", "Truck parking shortage worsens along I-95 corridor, survey finds"),
    ("15:10", 25, "Heavy Duty Trucking", "Daimler Truck recalls 12,000 Freightliner Cascadias over brake issue"),
    ("16:00", 30, "FreightWaves", "Spot rates climb in Midwest as produce season peaks"),
    ("17:20", 20, "Truck News", "Alberta announces truck driver training grant for new Canadians"),
    ("18:45", 25, "Transport Topics", "Cargo theft rises 27% in third quarter, CargoNet says"),
    ("20:30", 20, "CDLLife", "FMCSA delays hours-of-service pilot program to spring"),
    ("21:50", 15, "FreightWaves", "Port of Long Beach drayage wait times climb as import surge hits"),
    # next morning: a follow-up with a real development (>18h after the original)
    ("+1 06:30", 20, "FreightWaves", "FMCSA broker bond rule for freight brokers now final"),
]


def build(scenario, day):
    """Turn the scenario into stored-story records with arrival times."""
    out = []
    for when, lag, source, title in scenario:
        plus = when.startswith("+1 ")
        hh, mm = map(int, when.replace("+1 ", "").split(":"))
        arrive = (day + timedelta(days=1 if plus else 0)).replace(hour=hh, minute=mm)
        arrive_utc = arrive.astimezone(timezone.utc)
        sid = fetch_news.story_id(title + source)
        item = {"headline": title, "link": "https://example.com/%s" % sid, "source": source, "snippet": "",
                "published": (arrive_utc - timedelta(minutes=lag)).isoformat()}
        rec = fetch_news.new_record(sid, item, arrive_utc)
        out.append((arrive_utc, rec))
    return out


def fake_pages(records, site_dir):
    for _, s in records:
        d = os.path.join(site_dir, "story", s["slug"])
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "index.html"), "w") as f:
            f.write('<meta property="og:title" content="%s | HaulTimes"><strong>%s</strong> <a href="/out/%s/">Read</a>'
                    % (s["title"], s["source"], s["id"]))


def simulate(name):
    day = datetime(2026, 11, 10 if name == "quiet" else 11, 0, 0, tzinfo=social.EASTERN)
    scenario = QUIET if name == "quiet" else BUSY
    records = build(scenario, day)
    site = tempfile.mkdtemp()
    fake_pages(records, site)
    settings = social.load_settings()
    for p in social.PLATFORMS:
        settings[p]["mode"] = "dry_run"
    states = {p: social.new_state() for p in social.PLATFORMS}
    t = day.astimezone(timezone.utc)
    end = (day + timedelta(days=1, hours=8)).astimezone(timezone.utc)
    editorial_log = []
    try:
        while t <= end:
            visible = [dict(r) for a, r in records if a <= t]
            editorial.reprocess(visible, t)
            for s in visible:
                if s["id"] not in {e["id"] for e in editorial_log}:
                    editorial_log.append({"id": s["id"], "title": s["title"], "source": s["source"], "status": s["status"],
                                          "importance": s["importance"], "kind": s.get("kind"), "category": s["category"],
                                          "reasons": s.get("reasons", [])})
            for p in social.PLATFORMS:
                social.run_platform(p, visible, settings[p], states[p], t, site, None, [])
            t += timedelta(minutes=15)
    finally:
        shutil.rmtree(site)
    arrivals = {r["id"]: a for a, r in records}
    result = {"scenario": name, "date": day.date().isoformat(), "settings": {p: {k: settings[p][k] for k in social.DEFAULTS[p] if k != "mode"} for p in social.PLATFORMS},
              "stories": len(records), "editorial": editorial_log, "platforms": {}}
    for p in social.PLATFORMS:
        st = states[p]
        posts = sorted([r for r in st["items"].values() if r["status"] == "dry_run"], key=lambda r: r["posted_at"])
        result["platforms"][p] = {
            "posts": [{"time": datetime.fromisoformat(r["posted_at"]).astimezone(social.EASTERN).strftime("%a %-I:%M %p"),
                       "arrived": arrivals[r["story_id"]].astimezone(social.EASTERN).strftime("%-I:%M %p"),
                       "wait_min": int((datetime.fromisoformat(r["posted_at"]) - arrivals[r["story_id"]]).total_seconds() // 60),
                       "title": r["title"], "source": r["source"], "score": r["score"], "breaking": bool(r.get("breaking")),
                       "text": r["caption"]} for r in posts],
            "decisions": [dict(d, time=datetime.fromisoformat(d["at"]).astimezone(social.EASTERN).strftime("%a %-I:%M %p"))
                          for d in st["decisions"]],
            "left_in_queue": [r["title"] for r in st["items"].values() if r["status"] == "queued"],
        }
    return result


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "quiet"
    res = simulate(name)
    if "--json" in sys.argv:
        with open(sys.argv[sys.argv.index("--json") + 1], "w") as f:
            json.dump(res, f, indent=1, ensure_ascii=False)
    for p in social.PLATFORMS:
        print("\n== %s: %d posts" % (p, len(res["platforms"][p]["posts"])))
        for x in res["platforms"][p]["posts"]:
            print("  %-12s (arrived %s, waited %3d min) %s%s [%s, %d]" % (x["time"], x["arrived"], x["wait_min"],
                  "BREAKING " if x["breaking"] else "", x["title"][:70], x["source"], x["score"]))
        for d in res["platforms"][p]["decisions"]:
            if d["action"] not in ("queued", "would post"):
                print("     - %s %-8s %s | %s" % (d["time"], d["action"], d["title"][:55], d["reason"][:90]))
