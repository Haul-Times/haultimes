"""
Pull freight and trucking headlines from RSS feeds and have Claude write an
original title, summary and "why it matters" line for each new story.
Results go to data/news.json. Needs the ANTHROPIC_API_KEY environment variable.
"""

import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from common import CATEGORIES, IMAGES, load_config, load_json, save_json, slugify

SYSTEM_PROMPT = """You write for HaulTimes, a freight and trucking news site for
carriers, owner-operators, brokers, dispatchers and shippers in the US and Canada.

For each story you get a headline, source and short feed snippet. Return JSON only:
{
  "relevant": true or false,
  "title": "clear headline, max 14 words, your own wording",
  "summary": "1-2 sentences, max 40 words, in your own words",
  "why_it_matters": "1 sentence, max 25 words: the practical impact on carriers, brokers or shippers",
  "category": one of %s,
  "region": "US" | "Canada" | "Cross-border" | "Other",
  "importance": 1-100
}

relevant = true ONLY if the story matters to the US or Canadian road freight market:
trucking companies, truck drivers, freight brokers, shippers, truckload/LTL rates
and capacity, diesel prices, US/Canada border crossings and trade affecting trucks,
FMCSA/DOT/Transport Canada/provincial rules, truck equipment sold in North America.
relevant = false for: news centred on other countries (India, Pakistan, UK, Europe,
Australia, Asia, Africa, etc.) unless it directly affects US/Canada trucking;
ocean shipping, tankers, rail or air cargo unless trucking is central; stock quote
pages and stock tips; consumer car news; viral or celebrity stories; gift guides;
company press releases with no news value.

importance: 90+ = major industry news (big regulation changes, border disruptions,
large rate swings, major carrier closures or strikes). 50 = routine industry news.
Under 30 = minor or very local.

Rules:
- Write everything in your own words. Never copy sentences or more than 4 words in a row from the snippet.
- Only state facts that are in the headline or snippet. Never invent numbers, names or quotes.
- If the snippet is thin, keep the summary short and general.
- Plain, direct language a truck driver would respect. No hype, no clickbait.""" % list(CATEGORIES)


def clean(text):
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    return re.sub(r"\s+", " ", text).strip()


def fetch_feed(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; HaulTimesBot/1.0)"})
    with urllib.request.urlopen(req, timeout=25) as r:
        root = ET.fromstring(r.read())
    items = []
    for it in root.iter("item"):
        title = clean(it.findtext("title"))
        link = (it.findtext("link") or "").strip()
        if not title or not link:
            continue
        src_el = it.find("source")
        source = clean(src_el.text) if src_el is not None and src_el.text else ""
        if source and title.endswith(" - " + source):
            title = title[: -len(" - " + source)].strip()
        try:
            published = parsedate_to_datetime(it.findtext("pubDate")).astimezone(timezone.utc)
        except Exception:
            published = datetime.now(timezone.utc)
        items.append({
            "headline": title,
            "link": link,
            "source": source or "News source",
            "snippet": clean(it.findtext("description"))[:600],
            "published": published.isoformat(),
        })
    return items


def story_id(headline):
    key = re.sub(r"[^a-z0-9]", "", headline.lower())[:80]
    return hashlib.sha1(key.encode()).hexdigest()[:10]


def pick_image(sid, category):
    """Use your own or stock photos from images/<category>/ if you add some."""
    folder = os.path.join(IMAGES, category)
    if os.path.isdir(folder):
        files = sorted(f for f in os.listdir(folder)
                       if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp")))
        if files:
            return "images/%s/%s" % (category, files[int(sid, 16) % len(files)])
    return ""  # the site falls back to a topic graphic


def summarize(client, model, item):
    msg = client.messages.create(
        model=model,
        max_tokens=400,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content":
                   "Headline: %s\nSource: %s\nSnippet: %s\n\nReturn the JSON."
                   % (item["headline"], item["source"], item["snippet"] or "(none)")}],
    )
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    data = json.loads(match.group(0))
    if data.get("category") not in CATEGORIES:
        data["category"] = "other"
    try:
        data["importance"] = max(1, min(100, int(data.get("importance", 50))))
    except (TypeError, ValueError):
        data["importance"] = 50
    return data


# Headlines-only mode (no API key): simple keyword sorting.
KEYWORDS = {
    "border": ["border", "cbsa", "cbp", "customs", "cross-border", "crossing", "tariff", "usmca", "cusma", "bridge"],
    "regs": ["fmcsa", "regulation", "rule", "eld", "hours-of-service", "hours of service", "dot ", "transport canada",
             "mandate", "inspection", "law", "bill", "ministry", "safety"],
    "fuel": ["diesel", "fuel", "gas price", "oil price", "renewable diesel", "carbon tax"],
    "rates": ["rate", "spot", "contract", "capacity", "volume", "demand", "market", "load-to-truck", "tender", "freight index"],
    "equip": ["truck sales", "class 8", "trailer", "tractor", "engine", "electric truck", "ev truck", "dealer", "equipment"],
    "drivers": ["driver", "trucker", "parking", "pay", "wage", "hiring", "jobs", "strike", "union", "cdl", "training"],
}
TRUCKING = ["truck", "freight", "trucking", "carrier", "logistics", "shipping", "shipper", "broker", "fleet", "haul",
            "cargo", "diesel", "fmcsa", "border", "supply chain", "warehouse", "ltl", "reefer", "flatbed", "port"]
BIG = ["strike", "shutdown", "closed", "closure", "bankrupt", "bankruptcy", "tariff", "ban", "new rule", "record",
       "surge", "plunge", "crash", "recall", "emergency"]


# Headlines that are clearly not US/Canada trucking news.
FOREIGN = ["india", "indian", "pakistan", "bangladesh", "sri lanka", "nepal", "philippine", "manila",
           "malaysia", "singapore", "indonesia", "vietnam", "thailand", "china", "chinese", "japan",
           "korea", "taiwan", "australia", "aussie", "new zealand", "kiwi", "nigeria", "kenya", "ghana",
           "south africa", "uganda", "tanzania", "ukraine", "russia", "dnipro", "uk ", "u.k.", "britain",
           "british", "england", "scotland", "wales", "ireland", "yorkshire", "london", "europe", "eu ",
           "germany", "france", "spain", "italy", "poland", "netherlands", "dubai", "saudi", "uae",
           "iran", "israel", "turkey", "egypt", "brazil", "argentina", "chile", "peru", "colombia",
           "hgv", "lorry", "haulage", "sebi", "nse", "bse", "tse:", ".ns)", "railways", " ioc ",
           "berjaya", "tasco", "mnre", "arai", "fy27", "fy28", "crore", "lakh", "rupee"]
JUNK = ["stock price", "stock forecast", "analyst ratings", "seasonal returns", "price target",
        "shares of", "stock quote", "harbor freight", "christmas gift", "gifts for", "deal of the day",
        "ho gauge", "model train", "toy ", "lego", "the finger", "viral", "celebrity", "recipe",
        "horoscope", "tanker", "lpg carrier", "crude carrier", "ship capsizes", "freight ship",
        "reiterates", "equalweight", "overweight rating", "export stocks", "stocks tied", "stocks investors",
        "dividend", "earnings call transcript"]
# Must mention road freight (plain "freight" alone also matches ocean/rail news).
ROAD = ["truck", "trucking", "trucker", "truckload", "ltl", "less-than-truckload", "fmcsa", "freight broker",
        "brokerage", "carrier", "fleet", "semi", "18-wheeler", "big rig", "cdl", "diesel", "owner-operator",
        "dispatcher", "logistics", "shipper", "drayage", "reefer", "flatbed", "dry van", "border crossing",
        "cbsa", "cbp", "usmca", "cusma", "transport canada", "dot ", "teamsters", "highway", "interstate",
        "warehouse", "supply chain", "freight rates", "freight market", "freight recession", "spot rate",
        "fedex freight", "ups freight", "tforce", "old dominion", "j.b. hunt", "knight-swift", "werner",
        "schneider", "xpo", "saia", "estes", "landstar", "c.h. robinson", "rxo", "uber freight", "ryder",
        "penske", "kenworth", "peterbilt", "freightliner", "volvo trucks", "mack trucks", "navistar"]


def is_relevant(headline, source=""):
    t = " %s " % headline.lower()
    if any(w in t for w in FOREIGN) or any(w in t for w in JUNK):
        return False
    return any(w in t for w in ROAD)


def keyword_story(sid, item):
    text = item["headline"].lower()
    if not is_relevant(item["headline"], item.get("source", "")):
        return None
    category = "other"
    for cat, words in KEYWORDS.items():
        if any(w in text for w in words):
            category = cat
            break
    importance = 50 + (25 if any(w in text for w in BIG) else 0)
    return {
        "id": sid, "slug": "%s-%s" % (slugify(item["headline"]), sid), "title": item["headline"],
        "summary": "", "why": "", "category": category, "region": "", "importance": importance,
        "source": item["source"], "link": item["link"], "published": item["published"],
        "image": pick_image(sid, category), "ai": False,
    }


def main():
    cfg = load_config()
    use_ai = bool(os.environ.get("ANTHROPIC_API_KEY"))
    client = None
    if use_ai:
        import anthropic
        client = anthropic.Anthropic()
    else:
        print("No ANTHROPIC_API_KEY: adding headlines only (no AI summaries).")

    stories = {s["id"]: s for s in load_json("news.json", [])}
    # Clean out headline-only stories that fail the current filter.
    for sid in [k for k, v in stories.items() if v.get("ai") is False and not is_relevant(v["title"], v.get("source", ""))]:
        del stories[sid]
    seen = set(load_json("seen.json", []))
    cutoff = datetime.now(timezone.utc) - timedelta(days=cfg.get("keep_days", 30))

    fresh = {}
    for url in cfg["news_feeds"]:
        try:
            for item in fetch_feed(url):
                sid = story_id(item["headline"])
                if sid in seen or sid in fresh:
                    continue
                if sid in stories and (stories[sid].get("ai", True) or not use_ai):
                    continue
                if datetime.fromisoformat(item["published"]) < cutoff:
                    continue
                if not is_relevant(item["headline"], item["source"]):
                    seen.add(sid)
                    continue
                fresh[sid] = item
        except Exception as e:
            print("Feed failed:", url[:80], "-", e)

    # Once the key is added, also upgrade recent headline-only stories to AI summaries.
    if use_ai:
        two_days = datetime.now(timezone.utc) - timedelta(days=2)
        for sid, s in stories.items():
            if s.get("ai") is False and sid not in fresh and datetime.fromisoformat(s["published"]) >= two_days:
                fresh[sid] = {"headline": s["title"], "link": s["link"], "source": s["source"],
                              "snippet": "", "published": s["published"]}

    queue = sorted(fresh.items(), key=lambda kv: kv[1]["published"], reverse=True)
    added = skipped = 0
    if not use_ai:
        for sid, item in queue[:150]:
            story = keyword_story(sid, item)
            if story:
                stories[sid] = story
                added += 1
            else:
                skipped += 1
    for sid, item in (queue[: cfg.get("max_new_stories_per_run", 25)] if use_ai else []):
        try:
            ai = summarize(client, cfg["ai_model"], item)
        except Exception as e:
            print("AI failed:", item["headline"][:60], "-", e)
            continue
        seen.add(sid)
        if not ai or not ai.get("relevant", True):
            stories.pop(sid, None)
            skipped += 1
            continue
        title = (ai.get("title") or item["headline"]).strip()
        stories[sid] = {
            "id": sid,
            "slug": "%s-%s" % (slugify(title), sid),
            "title": title,
            "summary": (ai.get("summary") or "").strip(),
            "why": (ai.get("why_it_matters") or "").strip(),
            "category": ai["category"],
            "region": ai.get("region", "Other"),
            "importance": ai["importance"],
            "source": item["source"],
            "link": item["link"],
            "published": item["published"],
            "image": pick_image(sid, ai["category"]),
        }
        added += 1
        time.sleep(0.2)

    kept = [s for s in stories.values() if datetime.fromisoformat(s["published"]) >= cutoff]
    kept.sort(key=lambda s: s["published"], reverse=True)
    save_json("news.json", kept)
    save_json("seen.json", sorted(seen)[-20000:])
    print("News: added %d, skipped %d off-topic, %d stories on site (%s)." % (
        added, skipped, len(kept), "AI summaries" if use_ai else "headlines only"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
