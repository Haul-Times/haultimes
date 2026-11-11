"""
Automatic posting of selected HaulTimes stories to the HaulTimes Facebook Page
(Meta Graph API) and X account (X API v2).

Runs after build_site.py in the GitHub Action. Controls live in social.json at the
top of the repo (mode off / dry_run / live per platform, daily cap, spacing, posting
hours, skip, publish-now and caption overrides). Queue and history are kept in
data/social_facebook.json and data/social_x.json; the editor page at
haultimes.com/editor/social/ shows previews, posts and errors.

Credentials come only from GitHub Secrets (environment variables):
  Facebook: FB_PAGE_ID, FB_PAGE_TOKEN
  X:        X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET
They are never written to files or printed.

  python scripts/social.py                 normal run (respects social.json)
  python scripts/social.py --samples 10    print sample captions, never posts
"""

import base64
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import socket
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import editorial
from common import CATEGORIES, ROOT, SITE, load_config, load_json, save_json

try:
    from zoneinfo import ZoneInfo
    EASTERN = ZoneInfo("America/Toronto")
except Exception:  # pragma: no cover
    EASTERN = timezone(timedelta(hours=-5))

PLATFORMS = ("facebook", "x")
GRAPH = "https://graph.facebook.com/v25.0"
XAPI = "https://api.x.com/2"
SETTINGS_FILE = os.path.join(ROOT, "social.json")
# No daily target or maximum: every story that passes the checks is queued and posted,
# one at a time, with minimum spacing. Spacing values are test settings, not platform limits.
DEFAULTS = {
    "facebook": {"mode": "dry_run", "min_gap_minutes": 90, "hours": [7, 21], "min_score": 70,
                 "max_age_hours": 12, "topic_gap_hours": 4, "breaking_score": 85, "breaking_max_age_hours": 3,
                 "breaking_min_gap_minutes": 10, "house_posts": True, "promo_every_days": 3,
                 "border_alert_minutes": 90, "settle_minutes": 10},
    "x": {"mode": "dry_run", "min_gap_minutes": 30, "hours": [6, 22], "min_score": 60,
          "max_age_hours": 8, "topic_gap_hours": 0, "breaking_score": 85, "breaking_max_age_hours": 3,
                 "breaking_min_gap_minutes": 10, "house_posts": False, "promo_every_days": 3,
                 "border_alert_minutes": 90, "settle_minutes": 10},
}
MAX_ATTEMPTS = 5


# ------------------------------------------------------------------ settings

def load_settings(path=None):
    try:
        with open(path or SETTINGS_FILE, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        raw = {}
    out = {}
    for p in PLATFORMS:
        cfg = dict(DEFAULTS[p])
        cfg.update({k: v for k, v in (raw.get(p) or {}).items() if k in DEFAULTS[p]})  # old "max_per_day" is ignored
        if cfg["mode"] not in ("off", "dry_run", "live"):
            cfg["mode"] = "dry_run"
        cfg["skip"] = [x for x in (raw.get("skip") or {}).get(p, []) if isinstance(x, str)]
        cfg["publish_now"] = [x for x in (raw.get("publish_now") or {}).get(p, []) if isinstance(x, str)]
        cfg["captions"] = {k: v for k, v in ((raw.get("captions") or {}).get(p) or {}).items() if isinstance(v, str)}
        out[p] = cfg
    return out


# ------------------------------------------------------------------ text helpers
CANADIAN = ["canada", "canadian", "ontario", "quebec", "alberta", "british columbia", "b.c.", "manitoba",
            "saskatchewan", "nova scotia", "new brunswick", "newfoundland", "p.e.i", "toronto", "montreal",
            "calgary", "edmonton", "winnipeg", "vancouver", "ottawa", "thunder bay", "cbsa", "transport canada",
            "cusma", "ota ", "canadian trucking alliance", "driver inc"]
CANADIAN_SOURCES = ["truck news", "today's trucking", "todays trucking", "cbc", "ctv", "global news", "insauga",
                    "globe and mail", "toronto star", "financial post", "canadian press", "midlandtoday"]


def is_canadian(s):
    """Canadian story: the headline says so, or a Canadian outlet with nothing pointing elsewhere."""
    t = " %s " % (s.get("orig_title") or s.get("title", "")).lower()
    if editorial._has(t, CANADIAN):
        return True
    elsewhere = editorial._has(t, ["north america", "u.s.", "us", "america", "american", "fmcsa", "congress",
                                   "mexico", "texas", "california", "state", "states", "nationwide"])
    return editorial._has((s.get("source") or "").lower(), CANADIAN_SOURCES) and not elsewhere


def hashtags(s, limit=2):
    """One broad tag plus one specific tag when it fits the story. #FMCSA only when FMCSA is in the story."""
    t = " %s " % ((s.get("orig_title") or s.get("title", "")) + " " + (s.get("summary") or "")).lower()
    cat = s.get("category", "other")
    broad = "#CanadianTrucking" if is_canadian(s) else "#Trucking"
    specific = {
        "fuel": "#Diesel" if "diesel" in t else None,
        "border": "#CrossBorder",
        "regs": "#FMCSA" if "fmcsa" in t else None,
        "drivers": "#TruckDrivers",
        "rates": "#Freight",
        "equip": None,
        "other": "#SupplyChain" if "supply chain" in t else ("#Freight" if editorial._has(t, ["broker", "brokerage", "freight fraud", "cargo theft"]) else None),
    }.get(cat)
    tags = [broad] + ([specific] if specific else [])
    return tags[:limit]


def publisher(s):
    """Publisher name as readers know it. Domain-style names lose their ending so X/Facebook
    don't turn them into a second link ("TheTrucker.com" -> "TheTrucker")."""
    name = (s.get("source") or "the original publisher").strip()
    name = re.split(r"\s+[|–-]\s+", name)[0].strip()
    name = re.sub(r"\.(com|ca|net|org|news|trade|tv|us|info|co|io)$", "", name, flags=re.I)
    return name or "the original publisher"


def dest_url(s, platform):
    q = urllib.parse.urlencode({"utm_source": platform, "utm_medium": "organic_social",
                                "utm_campaign": "story", "utm_content": s["id"]})
    base = load_config()["site_url"].rstrip("/")
    return "%s/story/%s/?%s" % (base, s["slug"], q)


def headline(s):
    t = re.sub(r"\s+", " ", (s.get("title") or "").strip())
    return t if t.endswith(("?", "!", ".")) else t + "."


def words(text):
    return len(re.findall(r"\S+", text))


# ---- X character counting (twitter-text v3 rules: weight 1 for common Latin ranges,
# 2 for everything else incl. emoji and CJK; any URL = 23; text is NFC-normalized)
X_LIMIT = 280
X_URL_LEN = 23
_X_LIGHT = [(0, 4351), (8192, 8205), (8208, 8223), (8242, 8247)]
_URL_RX = re.compile(r"(https?://\S+|\b(?:[a-z0-9-]+\.)+(?:com|ca|net|org|news|io|co|us|info|tv|trade|ly|gov)\b(?:/\S*)?)", re.I)


def x_weighted_length(text):
    text = unicodedata.normalize("NFC", text)
    total = 0
    pos = 0
    for m in _URL_RX.finditer(text):
        total += _x_chars(text[pos:m.start()]) + X_URL_LEN
        pos = m.end()
    return total + _x_chars(text[pos:])


def _x_chars(chunk):
    n = 0
    prev_emoji = False
    after_zwj = False
    for ch in chunk:
        cp = ord(ch)
        if cp == 0x200D:            # zero-width joiner: glues an emoji sequence, adds nothing
            after_zwj = prev_emoji
            continue
        if cp in (0xFE0E, 0xFE0F) or 0x1F3FB <= cp <= 0x1F3FF:  # variation selectors, skin tones
            continue
        is_emoji = cp >= 0x1F000 or 0x2600 <= cp <= 0x27BF
        if is_emoji and after_zwj:
            after_zwj = False
            continue
        after_zwj = False
        prev_emoji = is_emoji
        n += 1 if any(a <= cp <= b for a, b in _X_LIGHT) else 2
    return n


def shorten_headline(text, budget):
    """Shorten at a natural break (colon, dash, comma), else at a word, never mid-word."""
    if x_weighted_length(text) <= budget:
        return text
    for sep in (": ", " — ", " – ", " - ", "; ", ", "):
        if sep in text:
            head = text.split(sep)[0].strip()
            if 20 <= x_weighted_length(head) <= budget:
                return head if head.endswith((".", "?", "!")) else head + "."
    out = ""
    for w in text.split():
        if x_weighted_length((out + " " + w).strip() + "…") > budget:
            break
        out = (out + " " + w).strip()
    return out.rstrip(",;:—–-") + "…"


# ------------------------------------------------------------------ captions

def facebook_caption(s, override=None):
    """Factual opening line, one or two supported sentences, attribution, 0-2 hashtags.
    The HaulTimes link is attached as the post's link (with its preview card)."""
    tags = " ".join(hashtags(s))
    if override:
        return override.strip() + ("\n\n" + tags if tags and "#" not in override else "")
    pub = publisher(s)
    paras = [headline(s)]
    body = []
    if s.get("summary"):
        # The opening sentences of the checked website summary, whole sentences only, about 45 words at most.
        # Nothing new is written for Facebook, so the caption carries only facts already checked against the source.
        for sent in re.split(r"(?<=[.!?])\s+", s["summary"].replace("\n\n", " ").strip()):
            if body and words(" ".join(body + [sent])) > 45:
                break
            body.append(sent)
        if words(" ".join(body)) > 60:
            body = []
    attribution = "Reported by %s. The link has the details and the original article." % pub
    text_body = " ".join(body)
    if text_body:
        paras.append(text_body)
    paras.append(attribution)
    if tags:
        paras.append(tags)
    return "\n\n".join(paras)


def x_text(s, override=None):
    """Headline, optional supported explanation, attribution, the HaulTimes link, 1-2 hashtags; fits 280."""
    url = dest_url(s, "x")
    tags_all = hashtags(s)
    pub = publisher(s)
    if override:
        text = "%s %s" % (override.strip(), url)
        if x_weighted_length(text) <= X_LIMIT:
            return text
    head = headline(s)
    why = (s.get("why") or "").strip() if s.get("summary") else ""
    variants = []
    for use_why in ([True, False] if why else [False]):
        for n_tags in (len(tags_all), 1, 0):
            tags = " ".join(tags_all[:n_tags])
            parts = [head]
            if use_why:
                parts.append(why)
            parts.append(("Via %s: %s" % (pub, url)) + (("\n" + tags) if tags else ""))
            variants.append("\n\n".join(parts))
    for v in variants:
        if x_weighted_length(v) <= X_LIMIT:
            return v
    # Very long headline: shorten it naturally.
    tail = "\n\nVia %s: %s" % (pub, url) + ("\n" + tags_all[0] if tags_all else "")
    budget = X_LIMIT - x_weighted_length(tail)
    return shorten_headline(head, budget) + tail


def caption_for(platform, s, override=None):
    return facebook_caption(s, override) if platform == "facebook" else x_text(s, override)


# ------------------------------------------------------------------ selection

def hours_old(s, now):
    return (now - datetime.fromisoformat(s["published"])).total_seconds() / 3600


def similar(a, b):
    """Same event? Shares most of its distinctive words."""
    ta, tb = editorial.tokens(a), editorial.tokens(b)
    if not ta or not tb:
        return False
    inter = ta & tb
    return len(inter) / len(ta | tb) >= 0.5 or (len(inter) >= 3 and len(inter) / min(len(ta), len(tb)) >= 0.6)


def page_problem(s, site_dir):
    """The post must land on a real HaulTimes page that names the publisher and links the original."""
    path = os.path.join(site_dir, "story", s.get("slug", "-"), "index.html")
    if not os.path.exists(path):
        return "story page not built"
    with open(path, encoding="utf-8") as f:
        page = f.read()
    if html.escape(s["source"]) not in page and s["source"] not in page:
        return "story page does not name the publisher"
    if ('/out/%s/' % s["id"]) not in page:
        return "story page has no link to the original article"
    return None


def preview_meta(s, site_dir):
    """What Facebook/X will show in the link preview (from the page's Open Graph tags)."""
    path = os.path.join(site_dir, "story", s.get("slug", "-"), "index.html")
    try:
        with open(path, encoding="utf-8") as f:
            page = f.read()
    except OSError:
        return {}
    meta = {}
    for prop in ("og:title", "og:description", "og:image", "og:url"):
        m = re.search(r'<meta property="%s" content="([^"]*)"' % prop, page)
        if m:
            meta[prop] = html.unescape(m.group(1))
    return meta


def why_not(s, cfg, now):
    """Reason a story can't be posted automatically, or None."""
    if s.get("status") != editorial.SHOWN:
        return "not shown on the site"
    if not s.get("date_known", True):
        return "no publication date"
    if not editorial.lead_eligible(s) and not s.get("pinned"):
        return "minor item (%s) or low-quality source" % s.get("kind", "?")
    if set(s.get("labels", [])) & {"Press release", "Sponsored", "Company announcement"}:
        return "press release / company announcement"
    if s.get("importance", 0) < cfg["min_score"] and not s.get("pinned"):
        return "importance %d is below this platform's threshold (%d)" % (s.get("importance", 0), cfg["min_score"])
    if hours_old(s, now) > cfg["max_age_hours"]:
        return "too old to post as news (%.0fh)" % hours_old(s, now)
    return None


def new_state():
    return {"items": {}, "paused": None, "account": {}, "log": [], "decisions": [], "decided": {}}


def log(st, now, msg):
    st["log"] = (st.get("log", []) + [{"at": now.isoformat(), "msg": msg}])[-200:]


def decide(st, now, sid, title, action, reason):
    """Record why a story was queued, posted, skipped, merged or expired (once per change)."""
    decided = st.setdefault("decided", {})
    key = "%s|%s" % (action, reason.split(":")[0])
    if decided.get(sid) == key:
        return
    decided[sid] = key
    st["decisions"] = (st.get("decisions", []) + [{"at": now.isoformat(), "story_id": sid, "title": title[:140],
                                                    "action": action, "reason": reason}])[-1500:]


def strength(s):
    """Which report of an event to keep: most credible source, then most important, then the original (earliest)."""
    return (-editorial.source_tier(s.get("source")), s.get("importance", s.get("score", 0)),
            -datetime.fromisoformat(s["published"]).timestamp())


def corroboration(s, stories):
    """Other outlets reporting the same event (the editorial rules folded them in as duplicates)."""
    return len({x.get("source") for x in stories if x.get("dup_of") == s["id"] and x.get("source") != s.get("source")})


def breaking_reason(s, stories, cfg, now):
    """Verified, significant, and new: may jump ahead of routine posts and outside posting hours."""
    if s.get("importance", 0) < cfg["breaking_score"] or hours_old(s, now) > cfg["breaking_max_age_hours"]:
        return None
    if s.get("kind", "news") not in ("news", "disruption"):
        return None
    others = corroboration(s, stories)
    if editorial.source_tier(s.get("source")) == 1:
        return "breaking: importance %d, reported by a trade publication of record" % s["importance"]
    if others >= 1:
        return "breaking: importance %d, confirmed by %d other outlet%s" % (s["importance"], others, "" if others == 1 else "s")
    return None


def select_reason(s, cfg):
    tier = editorial.source_tier(s.get("source"))
    why = "importance %d (threshold %d), %s, %s" % (s.get("importance", 0), cfg["min_score"],
                                                    CATEGORIES.get(s.get("category"), ("Industry",))[0],
                                                    {1: "trade publication", 2: "established outlet", 3: "local/other outlet"}.get(tier, "source"))
    if s.get("followup_of"):
        why += ", follow-up with a new development"
    return why


def _done(r):
    return r["status"] in ("posting", "uncertain", "posted", "dry_run")


def queue_new(platform, stories, cfg, st, now, site_dir):
    items = st["items"]
    recent = lambda: [r for r in items.values() if (_done(r) or r["status"] == "queued")
                      and (now - datetime.fromisoformat(r["created_at"])).total_seconds() < 72 * 3600]
    url_keys = {r.get("url_key"): r for r in items.values() if _done(r) or r["status"] == "queued"}
    by_id = {x["id"]: x for x in stories}
    added = 0
    for s in sorted(editorial.eligible(stories), key=lambda s: editorial.rank_score(s, now), reverse=True):
        sid = s["id"]
        if sid in items:
            continue
        forced = sid in cfg["publish_now"]
        title = s.get("orig_title") or s["title"]
        reason = why_not(s, cfg, now)
        if reason and not forced:
            if hours_old(s, now) <= cfg["max_age_hours"]:
                decide(st, now, sid, title, "skipped", reason)
            continue
        key = s.get("url_key") or editorial.canonical_url(s.get("link"))
        if key and key in url_keys:
            decide(st, now, sid, title, "merged", "same article as %s" % url_keys[key]["story_id"])
            continue
        match = next((r for r in recent() if similar(title, r["title"])), None)
        if match and _done(match):
            if not s.get("followup_of"):
                decide(st, now, sid, title, "merged", "same event already posted: %s" % match["title"][:80])
                continue
        elif match:  # same event is waiting in the queue: keep the stronger report
            other = by_id.get(match["story_id"])
            if s.get("followup_of"):
                match["status"] = "merged"
                decide(st, now, match["story_id"], match["title"], "merged",
                       "replaced by a follow-up with a new development: %s" % title[:80])
            elif other and strength(s) > strength(other):
                match["status"] = "merged"
                decide(st, now, match["story_id"], match["title"], "merged",
                       "replaced by a stronger report from %s" % s["source"])
            else:
                decide(st, now, sid, title, "merged", "same event already queued from %s" % match["source"])
                continue
        problem = page_problem(s, site_dir)
        if problem:
            decide(st, now, sid, title, "skipped", problem)
            continue
        rec = {"story_id": sid, "title": title, "url_key": key, "category": s.get("category", "other"),
               "source": s["source"], "dest": dest_url(s, platform), "caption": caption_for(platform, s),
               "status": "queued", "created_at": now.isoformat(), "published": s["published"],
               "score": s.get("importance", 0), "attempts": 0, "errors": [], "post_id": None, "posted_at": None,
               "next_attempt_at": None, "preview": preview_meta(s, site_dir),
               "reason": "posted by editor request" if forced else select_reason(s, cfg)}
        items[sid] = rec
        url_keys[key] = rec
        added += 1
        decide(st, now, sid, title, "queued", rec["reason"])
    return added


# ------------------------------------------------------------------ HaulTimes' own posts
# Besides news, the Page posts three kinds of useful updates from the site's own data, through the same
# queue (same spacing, hours, duplicate and retry rules):
#   * weekly diesel prices, once per new EIA week
#   * border delays: a commercial wait of border_alert_minutes or more that is at least double the usual
#     wait for that hour, once per crossing and direction every 12 hours
#   * a Freight Market reminder every promo_every_days days, rotating through the texts below, with hashtags

PROMOS = [
    ("Is that load offer fair? Check any lane against what other carriers reported this week: dry van, reefer, "
     "flatbed and step deck, across the US and Canada. Free and anonymous on HaulTimes Freight Market.",
     "#Trucking #FreightRates #OwnerOperator #TruckDrivers", "#chk"),
    ("How's your market this week? Tell us in one tap: Hot, Normal or Slow. Every answer adds to a live "
     "load-market map for the US and Canada. No name, no email.",
     "#Trucking #CanadianTrucking #Flatbed #Reefer", "#poll"),
    ("Hauled a load this week? Share the rate, anonymously. The more carriers report, the clearer the picture "
     "of what each lane really pays, for everyone.",
     "#OwnerOperator #Freight #DryVan #TruckingLife", "#rep"),
    ("Before you book, see what your lane is paying. Typical all-in rates from real reports by carriers and "
     "brokers, for dry van, reefer, flatbed and step deck.",
     "#FreightRates #Trucking #StepDeck #Flatbed", "#chk"),
]


# Picture text for each PROMOS entry (same order): headline, one line, chips.
PROMO_CARDS = [
    ("Is that load offer fair?", "Check any lane against what carriers reported this week.",
     ["Dry van", "Reefer", "Flatbed", "Step deck"]),
    ("How's your market this week?", "Hot, normal or slow? One tap adds to the live load-market map.",
     ["Hot", "Normal", "Slow"]),
    ("Hauled a load this week?", "Share the rate anonymously. Every report makes each lane clearer.",
     ["No name", "No email", "US & Canada"]),
    ("See what your lane is paying", "Typical all-in rates from real carrier and broker reports.",
     ["Dry van", "Reefer", "Flatbed", "Step deck"]),
]


def diesel_card(e, o=None):
    from fetch_market import EIA_REGIONS
    names = {k: label for k, label, _ in EIA_REGIONS}
    p, prev = e["prices"], e.get("prev_prices") or {}
    card = {"type": "stat", "kicker": "Diesel",
            "big": _money(p["US"]), "label": "US average per gallon, week of %s (US EIA)" % datetime.fromisoformat(e["week"]).strftime("%b %-d"),
            "footer": "Weekly diesel prices · US & Canada", "details": []}
    if prev.get("US"):
        d = round((p["US"] - prev["US"]) * 100)
        if d:
            card.update(change="%d¢" % abs(d), dir="up" if d > 0 else "down")
    regional = {k: v for k, v in p.items() if k in ("1A", "1B", "1C", "2", "3", "4", "5XCA", "CA")}
    if len(regional) >= 3:
        hi, lo = max(regional, key=regional.get), min(regional, key=regional.get)
        card["details"] += [("Highest", "%s %s" % (names[hi], _money(regional[hi]))),
                            ("Lowest", "%s %s" % (names[lo], _money(regional[lo])))]
    if o and o.get("prices"):
        k = next((k for k in o["prices"] if "average" in k.lower()), None)
        if k:
            card["details"].append(("Ontario", "%.1f¢/L" % o["prices"][k]))
    return card


def _dur(m):
    h, mm = divmod(int(round(m)), 60)
    return ("%d h %d min" % (h, mm) if mm else "%d h" % h) if h else "%d min" % mm


def _site():
    return load_config()["site_url"].rstrip("/")


def _house_dest(platform, path, campaign):
    q = urllib.parse.urlencode({"utm_source": platform, "utm_medium": "organic_social", "utm_campaign": campaign})
    frag = ""
    if "#" in path:
        path, frag = path.split("#", 1)
        frag = "#" + frag
    return "%s%s?%s%s" % (_site(), path, q, frag)


def _house_share(platform, hid, target, campaign, title, desc, card, now):
    """Share page + image for a house post (so each post has its own picture). Falls back to the plain page."""
    plain = _house_dest(platform, target, campaign)
    if not card:
        return plain
    try:
        import cards
        entry = {"title": title, "desc": desc, "card": card, "target": target, "created": now.isoformat()}
        shares = load_json("share.json", {})
        shares[hid] = entry
        save_json("share.json", shares)
        cards.write_share(SITE, _site(), hid, entry)
    except Exception as e:  # never let a picture problem stop the post
        print("share card failed for %s: %s" % (hid, e))
        return plain
    q = urllib.parse.urlencode({"utm_source": platform, "utm_medium": "organic_social", "utm_campaign": campaign})
    return "%s/s/%s/?%s" % (_site(), hid, q)


def _house_item(st, now, hid, title, caption, dest, score, kind):
    st["items"][hid] = {"story_id": hid, "title": title, "url_key": hid, "category": "house:" + kind, "source": "HaulTimes",
                        "dest": dest, "caption": caption, "status": "queued", "created_at": now.isoformat(),
                        "published": now.isoformat(), "score": score, "attempts": 0, "errors": [], "post_id": None,
                        "posted_at": None, "next_attempt_at": None, "preview": {}, "house": kind,
                        "reason": "HaulTimes update: %s" % kind}
    decide(st, now, hid, title, "queued", "HaulTimes update: %s" % kind)


def _money(v):
    return "$%.2f" % v


def diesel_caption(e, o=None):
    """Weekly diesel post from EIA's US regional prices (and Ontario's weekly survey when available)."""
    from fetch_market import EIA_REGIONS
    names = {k: label for k, label, _ in EIA_REGIONS}
    p, prev = e["prices"], e.get("prev_prices") or {}
    us = p["US"]
    week = datetime.fromisoformat(e["week"]).strftime("%B %-d")
    line = "US diesel averaged %s a gallon for the week of %s" % (_money(us), week)
    if prev.get("US"):
        d = round((us - prev["US"]) * 100)
        line += ", %s" % ("unchanged from the week before" if d == 0 else "%s %d¢ from the week before" % ("up" if d > 0 else "down", abs(d)))
    parts = [line + ", according to the US Energy Information Administration."]
    regional = {k: v for k, v in p.items() if k in ("1A", "1B", "1C", "2", "3", "4", "5XCA", "CA")}
    if len(regional) >= 3:
        hi = max(regional, key=regional.get)
        lo = min(regional, key=regional.get)
        parts.append("Highest: %s at %s. Lowest: %s at %s." % (names[hi], _money(regional[hi]), names[lo], _money(regional[lo])))
    if o and o.get("prices"):
        k = next((k for k in o["prices"] if "average" in k.lower()), None)
        if k:
            parts.append("In Ontario, diesel averaged %.1f¢ a litre (week of %s)." % (
                o["prices"][k], datetime.fromisoformat(o["week"]).strftime("%B %-d")))
    parts.append("Every state and province on the HaulTimes diesel map.")
    return "\n\n".join([" ".join(parts[:2]), " ".join(parts[2:]), "#Diesel #Trucking #FuelPrices"]).replace("\n\n\n\n", "\n\n")


def border_alerts(border, minutes):
    """Crossings where trucks wait unusually long right now: (key, text)."""
    out = []
    hour = border.get("hour_now")
    for c in border.get("crossings") or []:
        for side, into, agency in (("south", "the US", "CBP"), ("north", "Canada", "CBSA")):
            w = (c.get(side) or {}).get("wait")
            if not isinstance(w, (int, float)) or w < minutes:
                continue
            usual = None
            try:
                usual = (c.get("usual") or {}).get(side)[hour]
            except (TypeError, IndexError, KeyError):
                usual = None
            if usual is not None and w < 2 * max(usual, 15):
                continue
            hrs, mins = divmod(int(w), 60)
            wait = ("%d hr %d min" % (hrs, mins) if mins else "%d hr" % hrs) if hrs else "%d min" % mins
            text = ("Long truck wait at the %s (%s): about %s for commercial vehicles entering %s, per %s%s."
                    % (c["name"], c.get("ports", "").replace("↔", "-"), wait, into, agency,
                       (", against a usual %d min at this hour" % usual) if usual is not None else ""))
            out.append(("%s-%s" % (c["id"], side), text))
            border_alerts.info[out[-1][0]] = {
                "type": "stat", "kicker": "Border delay", "big": _dur(w),
                "label": "%s (%s), trucks entering %s" % (c["name"], c.get("ports", "").replace("↔", "–"), into),
                "details": ([("Usual at this hour", _dur(usual))] if usual is not None else []) + [("Source", agency)],
                "footer": "Live truck border waits"}
            if usual is not None:
                border_alerts.info[out[-1][0]].update(change="+" + _dur(w - usual), dir="up")
    return out


border_alerts.info = {}


def queue_house(platform, cfg, st, now):
    if not cfg.get("house_posts"):
        return 0
    added = 0
    items = st["items"]
    local = now.astimezone(EASTERN)
    in_hours = cfg["hours"][0] <= local.hour < cfg["hours"][1]
    market = load_json("market.json", {})
    # weekly diesel
    e, o = market.get("eia_diesel", {}), market.get("ontario_diesel", {})
    if e.get("status") == "ok" and (e.get("prices") or {}).get("US") and e.get("parser") and in_hours and local.hour >= 10:
        hid = "diesel-%s" % e["week"]
        if hid not in items:
            cap = diesel_caption(e, o)
            _house_item(st, now, hid, "Diesel prices, week of %s" % e["week"], cap,
                        _house_share(platform, hid, "/freight-market/#fuel-h", "diesel",
                                     "US & Canada diesel prices: week of %s" % datetime.fromisoformat(e["week"]).strftime("%B %-d"),
                                     cap.split("\n\n")[0], diesel_card(e, o), now),
                        cfg["min_score"] + 10, "diesel")
            added += 1
    # border delays (any hour: a 3 a.m. delay matters to drivers too)
    border = load_json("border.json", {})
    for key, text in border_alerts(border, cfg.get("border_alert_minutes", 90)):
        recent = [r for r in items.values() if r.get("house") == "border" and r["story_id"].startswith("border-%s-" % key)
                  and now - datetime.fromisoformat(r["created_at"]) < timedelta(hours=12)]
        if recent:
            continue
        hid = "border-%s-%s" % (key, local.strftime("%Y%m%d%H"))
        _house_item(st, now, hid, text[:90], text + "\n\nLive waits at every crossing on HaulTimes.\n\n#CrossBorder #Trucking",
                    _house_share(platform, hid, "/border-wait-times/", "border", "Truck border delay", text,
                                 border_alerts.info.get(key), now),
                    cfg.get("breaking_score", 85), "border")
        items[hid]["breaking"] = "unusual border delay"
        added += 1
    # Freight Market reminder
    every = cfg.get("promo_every_days") or 0
    if every and in_hours and 10 <= local.hour < 19:
        last = max((datetime.fromisoformat(r["created_at"]) for r in items.values() if r.get("house") == "promo"), default=None)
        if last is None or now - last >= timedelta(days=every):
            i = st.get("promo_i", 0) % len(PROMOS)
            text, tags, anchor = PROMOS[i]
            st["promo_i"] = i + 1
            hid = "promo-%s" % local.strftime("%Y%m%d")
            head, sub, chips = PROMO_CARDS[i]
            _house_item(st, now, hid, "Freight Market reminder", text + "\n\n" + tags,
                        _house_share(platform, hid, "/freight-market/" + anchor, "freight_market",
                                     "HaulTimes Freight Market: " + head, text,
                                     {"type": "promo", "kicker": "Freight Market", "headline": head, "sub": sub, "chips": chips}, now),
                        cfg["min_score"], "promo")
            added += 1
    return added


def refresh_queue(platform, stories, cfg, st, now):
    """Recheck everything still waiting: skip list, stale, superseded, redundant; refresh captions and priority."""
    by_id = {s["id"]: s for s in stories}
    done = [r for r in st["items"].values() if _done(r) and r.get("posted_at")]
    for sid, r in st["items"].items():
        if r["status"] != "queued":
            continue
        if r.get("house"):   # HaulTimes' own updates: only skip-list and a 24-hour shelf life apply
            if sid in cfg["skip"]:
                r["status"] = "skipped"
                decide(st, now, sid, r["title"], "skipped", "skipped by editor")
            elif now - datetime.fromisoformat(r["created_at"]) > timedelta(hours=24 if r["house"] != "border" else 3):
                r["status"] = "expired"
                decide(st, now, sid, r["title"], "expired", "no slot opened in time")
            continue
        s = by_id.get(sid)
        if sid in cfg["skip"]:
            r["status"] = "skipped"
            r["errors"].append({"at": now.isoformat(), "msg": "skipped by editor"})
            decide(st, now, sid, r["title"], "skipped", "skipped by editor")
            continue
        if s is None or s.get("status") != editorial.SHOWN:
            if s is not None and s.get("status") == "duplicate":
                stronger = by_id.get(s.get("dup_of"), {})
                r["status"] = "merged"
                decide(st, now, sid, r["title"], "merged", "superseded by a stronger report: %s (%s)" % (
                    (stronger.get("title") or "?")[:80], stronger.get("source", "?")))
            else:
                r["status"] = "skipped"
                decide(st, now, sid, r["title"], "skipped", "no longer on the site")
            continue
        if sid not in cfg["publish_now"] and hours_old(s, now) > cfg["max_age_hours"]:
            r["status"] = "expired"
            decide(st, now, sid, r["title"], "expired", "stale before a slot opened (published %.0fh ago)" % hours_old(s, now))
            continue
        later = [d for d in done if datetime.fromisoformat(d["posted_at"]) > datetime.fromisoformat(r["created_at"])
                 and similar(r["title"], d["title"])]
        if later and not s.get("followup_of"):
            r["status"] = "skipped"
            decide(st, now, sid, r["title"], "skipped", "redundant: same event already posted (%s)" % later[0]["story_id"])
            continue
        r["score"] = s.get("importance", r["score"])
        r["breaking"] = breaking_reason(s, stories, cfg, now)
        r["caption"] = caption_for(platform, s, cfg["captions"].get(sid))
        r["edited"] = sid in cfg["captions"]
        # A summary is being written for this story: hold the post (up to 40 minutes) so the caption includes it.
        r["wait_summary"] = bool(s.get("sum_pending")) and not s.get("summary")


def slot_open(cfg, st, now, breaking=False):
    """Inside posting hours (breaking news may go any time) and far enough from the last post?"""
    local = now.astimezone(EASTERN)
    start, end = cfg["hours"]
    if not breaking and not (start <= local.hour < end):
        return False, "outside posting hours"
    done = [r for r in st["items"].values() if r.get("posted_at") and _done(r)]
    gap = cfg.get("breaking_min_gap_minutes", 10) if breaking else cfg["min_gap_minutes"]
    if done:
        last = max(datetime.fromisoformat(r["posted_at"]) for r in done)
        if now - last < timedelta(minutes=gap):
            return False, "waiting for minimum spacing (%d min)" % gap
    return True, ""


def _rank(r, now):
    return (r["score"] - min(40, (now - datetime.fromisoformat(r["published"])).total_seconds() / 3600 * 0.6), r["published"])


def next_item(cfg, st, now, open_routine=True, open_breaking=None, platform="x"):
    """Editor 'publish now' first, then verified breaking news, then routine stories by importance and freshness."""
    if open_breaking is None:
        open_breaking = open_routine
    ready = [r for r in st["items"].values() if r["status"] == "queued"
             and (not r.get("next_attempt_at") or datetime.fromisoformat(r["next_attempt_at"]) <= now)]
    forced = [r for r in ready if r["story_id"] in cfg["publish_now"]]
    # Give the site time to publish the page and its share image before Facebook reads it.
    settle = timedelta(minutes=cfg.get("settle_minutes") or 0)
    ready = [r for r in ready if now - datetime.fromisoformat(r["created_at"]) >= settle]
    ready = [r for r in ready if not r.get("wait_summary") or r.get("breaking")
             or now - datetime.fromisoformat(r["created_at"]) >= timedelta(minutes=40)]
    if forced:
        return forced[0]
    breaking = [r for r in ready if r.get("breaking")]
    if breaking and open_breaking:
        return max(breaking, key=lambda r: _rank(r, now))
    if not open_routine:
        return None
    gap = cfg.get("topic_gap_hours") or 0
    recent_cats = {r.get("category") for r in st["items"].values() if _done(r) and r.get("posted_at")
                   and now - datetime.fromisoformat(r["posted_at"]) < timedelta(hours=gap)} if gap else set()
    for r in sorted(ready, key=lambda r: _rank(r, now), reverse=True):
        if r.get("category") in recent_cats and r["score"] < cfg["min_score"] + 15:
            decide(st, now, r["story_id"], r["title"], "held",
                   "held: %s already covered %s in the last %dh" % (platform.capitalize(), CATEGORIES.get(r.get("category"), ("this topic",))[0], gap))
            continue
        return r
    return None


def post_reason(r, now):
    wait = (now - datetime.fromisoformat(r["created_at"])).total_seconds() / 60
    return "%s; waited %d min in queue" % (r.get("breaking") or r.get("reason", "selected"), wait)


def frequency(st, days=14, now=None):
    """Posts per day (UTC, matching Cloudflare's daily numbers), for comparing with traffic."""
    out = {}
    for r in st["items"].values():
        if r.get("posted_at") and r["status"] in ("posted", "dry_run"):
            d = datetime.fromisoformat(r["posted_at"]).astimezone(timezone.utc).date().isoformat()  # UTC, like Cloudflare
            out.setdefault(d, {"posted": 0, "dry_run": 0})
            out[d]["posted" if r["status"] == "posted" else "dry_run"] += 1
    return dict(sorted(out.items())[-days:])


# ------------------------------------------------------------------ API clients
class AuthError(Exception):
    """Token expired, revoked, missing permission, or billing/credits problem. Pauses the platform."""


class RateLimited(Exception):
    def __init__(self, msg, retry_at):
        super().__init__(msg)
        self.retry_at = retry_at


class Temporary(Exception):
    """Failed before or without reaching the platform; safe to retry later."""


class Uncertain(Exception):
    """The request may have gone through (timeout / server error after sending). Check before retrying."""


class Permanent(Exception):
    """The platform refused this post (e.g. content rejected). Don't retry."""


def http_request(method, url, data=None, headers=None, json_body=None, timeout=25):
    """Small HTTP helper. Returns (status, headers, parsed JSON or {})."""
    body = None
    headers = dict(headers or {})
    headers.setdefault("User-Agent", "HaulTimes/1.0")
    if json_body is not None:
        body = json.dumps(json_body).encode()
        headers["Content-Type"] = "application/json"
    elif data is not None:
        body = urllib.parse.urlencode(data).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, dict(r.headers), (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            parsed = json.loads(raw) if raw else {}
        except ValueError:
            parsed = {"raw": raw[:300].decode("utf-8", "replace")}
        return e.code, dict(e.headers or {}), parsed


class FacebookClient:
    """Posts to the Page feed with a Page access token (Graph API v25.0)."""

    def __init__(self, page_id, token, http=http_request):
        self.page_id, self.token, self.http = page_id, token, http

    def _check(self, status, headers, body, sent):
        err = body.get("error") if isinstance(body, dict) else None
        if status < 400 and not err:
            return body
        err = err or {}
        code = err.get("code")
        msg = "Facebook error %s: %s" % (code or status, err.get("message", "")[:200])
        if code in (190, 102, 10, 200, 3) or err.get("type") == "OAuthException" and code not in (1, 2, 4, 17, 32, 613):
            raise AuthError(msg)
        if code in (4, 17, 32, 613, 80001) or status == 429:
            raise RateLimited(msg, datetime.now(timezone.utc) + timedelta(hours=1))
        if err.get("is_transient") or code in (1, 2) or status >= 500:
            raise (Uncertain if sent else Temporary)(msg)
        raise Permanent(msg)

    def post(self, message, link):
        try:
            status, headers, body = self.http("POST", "%s/%s/feed" % (GRAPH, self.page_id),
                                              data={"message": message, "link": link, "access_token": self.token})
        except (socket.timeout, TimeoutError) as e:
            raise Uncertain("Facebook timed out: %s" % type(e).__name__)
        except urllib.error.URLError as e:
            raise Temporary("Facebook unreachable: %s" % e.reason)
        body = self._check(status, headers, body, sent=True)
        if not body.get("id"):
            raise Uncertain("Facebook returned no post id")
        return body["id"], "https://www.facebook.com/%s" % body["id"]

    def check(self):
        """Read-only: is this the Page's own token? (/me answers as the Page only for a Page token.)
        Returns the Page name."""
        try:
            status, headers, body = self.http("GET", "%s/me?fields=id,name" % GRAPH,
                                              headers={"Authorization": "OAuth " + self.token})
        except (socket.timeout, TimeoutError, urllib.error.URLError) as e:
            raise Temporary("Facebook check failed: %s" % type(e).__name__)
        body = self._check(status, headers, body, sent=False)
        if str(body.get("id")) != str(self.page_id):
            raise AuthError("FB_PAGE_TOKEN is a personal (user) token, not the Page token. In Graph API Explorer run "
                            "me/accounts and copy the access_token inside the HaulTimes block, then update the "
                            "FB_PAGE_TOKEN secret on GitHub.")
        return body.get("name") or body.get("id")

    def inspect(self, post_id):
        """Read-only: how Facebook sees one of our posts."""
        status, headers, body = self.http(
            "GET", "%s/%s?fields=is_published,is_hidden,privacy,permalink_url,created_time,status_type" % (GRAPH, post_id),
            headers={"Authorization": "OAuth " + self.token})
        body = self._check(status, headers, body, sent=False)
        priv = body.get("privacy") or {}
        return {"is_published": body.get("is_published"), "is_hidden": body.get("is_hidden"),
                "privacy": priv.get("value") or priv.get("description"), "permalink": body.get("permalink_url"),
                "created": body.get("created_time")}

    def find(self, message, since):
        """Look for a post we may already have made (after a timeout or crash)."""
        try:
            status, headers, body = self.http(
                "GET", "%s/%s/feed?fields=id,message,created_time&limit=25" % (GRAPH, self.page_id),
                headers={"Authorization": "OAuth " + self.token})
        except (socket.timeout, TimeoutError, urllib.error.URLError) as e:
            raise Temporary("Facebook check failed: %s" % type(e).__name__)
        body = self._check(status, headers, body, sent=False)
        norm = lambda t: re.sub(r"\s+", " ", t or "").strip()
        for p in body.get("data", []):
            if norm(p.get("message")) == norm(message):
                return p["id"], "https://www.facebook.com/%s" % p["id"]
        return None


def _pct(s):
    return urllib.parse.quote(str(s), safe="~-._")


class XClient:
    """Creates posts with OAuth 1.0a user context (POST /2/tweets)."""

    def __init__(self, api_key, api_secret, token, token_secret, http=http_request):
        self.k, self.ks, self.t, self.ts, self.http = api_key, api_secret, token, token_secret, http

    def _auth(self, method, url, params=None):
        oauth = {"oauth_consumer_key": self.k, "oauth_nonce": secrets.token_hex(16),
                 "oauth_signature_method": "HMAC-SHA1", "oauth_timestamp": str(int(time.time())),
                 "oauth_token": self.t, "oauth_version": "1.0"}
        allp = dict(oauth, **(params or {}))
        base = "&".join([method.upper(), _pct(url),
                         _pct("&".join("%s=%s" % (_pct(k), _pct(v)) for k, v in sorted(allp.items())))])
        key = "%s&%s" % (_pct(self.ks), _pct(self.ts))
        oauth["oauth_signature"] = base64.b64encode(hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()).decode()
        return "OAuth " + ", ".join('%s="%s"' % (_pct(k), _pct(v)) for k, v in sorted(oauth.items()))

    def _check(self, status, headers, body, sent):
        if status < 400:
            return body
        detail = (body.get("detail") or body.get("title") or (body.get("errors") or [{}])[0].get("message", "")
                  if isinstance(body, dict) else "")
        msg = "X error %s: %s" % (status, str(detail)[:200])
        if status in (401, 402) or (status == 403 and "duplicate" not in msg.lower() and "not permitted" not in msg.lower()):
            raise AuthError(msg)
        if status == 429:
            reset = headers.get("x-rate-limit-reset") or headers.get("X-Rate-Limit-Reset")
            when = datetime.fromtimestamp(int(reset), timezone.utc) if reset and str(reset).isdigit() \
                else datetime.now(timezone.utc) + timedelta(minutes=15)
            raise RateLimited(msg, when)
        if status >= 500:
            raise (Uncertain if sent else Temporary)(msg)
        raise Permanent(msg)

    def post(self, text, link=None):
        url = XAPI + "/tweets"
        try:
            status, headers, body = self.http("POST", url, json_body={"text": text},
                                              headers={"Authorization": self._auth("POST", url)})
        except (socket.timeout, TimeoutError) as e:
            raise Uncertain("X timed out: %s" % type(e).__name__)
        except urllib.error.URLError as e:
            raise Temporary("X unreachable: %s" % e.reason)
        body = self._check(status, headers, body, sent=True)
        pid = (body.get("data") or {}).get("id")
        if not pid:
            raise Uncertain("X returned no post id")
        return pid, "https://x.com/i/web/status/%s" % pid

    def user_id(self, st):
        if st.get("account", {}).get("x_user_id"):
            return st["account"]["x_user_id"]
        url = XAPI + "/users/me"
        status, headers, body = self.http("GET", url, headers={"Authorization": self._auth("GET", url)})
        body = self._check(status, headers, body, sent=False)
        st.setdefault("account", {})["x_user_id"] = body["data"]["id"]
        return body["data"]["id"]

    def find(self, story_id, st):
        """Our recent posts (owned reads); match the story id in the link's utm_content."""
        try:
            uid = self.user_id(st)
            base = "%s/users/%s/tweets" % (XAPI, uid)
            params = {"max_results": "10", "tweet.fields": "created_at,entities"}
            status, headers, body = self.http("GET", base + "?" + urllib.parse.urlencode(params),
                                              headers={"Authorization": self._auth("GET", base, params)})
        except (socket.timeout, TimeoutError, urllib.error.URLError) as e:
            raise Temporary("X check failed: %s" % type(e).__name__)
        body = self._check(status, headers, body, sent=False)
        for p in body.get("data", []):
            for u in ((p.get("entities") or {}).get("urls") or []):
                if "utm_content=%s" % story_id in (u.get("expanded_url") or ""):
                    return p["id"], "https://x.com/i/web/status/%s" % p["id"]
        return None


def make_client(platform, env=None):
    env = env if env is not None else os.environ
    if platform == "facebook":
        pid, tok = env.get("FB_PAGE_ID"), env.get("FB_PAGE_TOKEN")
        return (FacebookClient(pid, tok), [tok]) if pid and tok else (None, [])
    keys = [env.get(k) for k in ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET")]
    return (XClient(*keys), keys) if all(keys) else (None, [])


def scrub(text, secret_values):
    for v in secret_values:
        if v and len(v) > 6:
            text = text.replace(v, "***")
    return re.sub(r"(access_token=)[^&\s]+", r"\1***", text)


def token_fingerprint(secret_values):
    return hashlib.sha256("|".join(v or "" for v in secret_values).encode()).hexdigest()[:12] if secret_values else ""


# ------------------------------------------------------------------ one platform, one run

def find_existing(platform, client, r, st):
    return client.find(r["caption"], r["created_at"]) if platform == "facebook" else client.find(r["story_id"], st)


def run_platform(platform, stories, cfg, st, now, site_dir, client=None, secret_values=(), save=lambda: None):
    """Queue, refresh, and (in live mode) publish at most one post. Returns a short status line."""
    if cfg["mode"] == "off":
        return "off"
    refresh_queue(platform, stories, cfg, st, now)
    queue_new(platform, stories, cfg, st, now, site_dir)
    queue_house(platform, cfg, st, now)
    refresh_queue(platform, stories, cfg, st, now)

    if cfg["mode"] == "dry_run":
        ok, why = slot_open(cfg, st, now)
        okb, _ = slot_open(cfg, st, now, breaking=True)
        r = next_item(cfg, st, now, ok, okb, platform)
        if not r:
            return "dry run: nothing to post (%s)" % (why or "no worthwhile new story")
        r["status"], r["posted_at"] = "dry_run", now.isoformat()
        decide(st, now, r["story_id"], r["title"], "would post", post_reason(r, now))
        log(st, now, "dry run: would post %s" % r["story_id"])
        return "dry run: would post %s" % r["story_id"]

    # ---- live
    if client is None:
        log(st, now, "live mode but credentials are missing")
        return "live: credentials missing (see setup notes)"
    fp = token_fingerprint(secret_values)
    if st.get("paused"):
        if st["paused"].get("token") and st["paused"]["token"] != fp:
            log(st, now, "new credentials found, resuming")
            st["paused"] = None
        else:
            return "live: paused (%s)" % st["paused"]["reason"]

    # Once a day (and right after setup), confirm the credentials work, without posting.
    acct = st.setdefault("account", {})
    if hasattr(client, "check") and (acct.get("checked_fp") != fp or not acct.get("checked_at")
                                     or now - datetime.fromisoformat(acct["checked_at"]) > timedelta(hours=24)):
        try:
            acct["name"] = client.check()
            acct["checked_at"], acct["checked_fp"] = now.isoformat(), fp
            log(st, now, "credentials OK: connected to %s" % acct["name"])
        except AuthError as e:
            st["paused"] = {"reason": scrub(str(e), secret_values), "at": now.isoformat(), "token": fp}
            return "live: paused (%s)" % st["paused"]["reason"]
        except (Temporary, RateLimited, Uncertain, Permanent) as e:
            log(st, now, "credential check failed: " + scrub(str(e), secret_values))

    # Visibility check: ask Facebook how it sees our most recent posts (published? public? hidden?).
    # Read-only; results go to st["visibility"] for the admin page and for troubleshooting.
    if hasattr(client, "inspect"):
        recent = sorted((x for x in st["items"].values() if x.get("post_id") and not x.get("fb_check")),
                        key=lambda x: x.get("posted_at") or "", reverse=True)[:2]
        for r in recent:
            try:
                r["fb_check"] = dict(client.inspect(r["post_id"]), at=now.isoformat())
                st["visibility"] = {"post": r["post_id"], **r["fb_check"]}
            except Exception as e:
                st["visibility"] = {"post": r["post_id"], "error": scrub(str(e), secret_values)[:200], "at": now.isoformat()}

    # Settle anything left uncertain by an earlier run before posting anything new.
    for r in [x for x in st["items"].values() if x["status"] in ("posting", "uncertain")]:
        try:
            found = find_existing(platform, client, r, st)
        except AuthError as e:
            st["paused"] = {"reason": scrub(str(e), secret_values), "at": now.isoformat(), "token": fp}
            return "live: paused (%s)" % st["paused"]["reason"]
        except (Temporary, RateLimited, Uncertain, Permanent) as e:
            r["errors"].append({"at": now.isoformat(), "msg": "check failed: " + scrub(str(e), secret_values)})
            return "live: waiting to confirm %s" % r["story_id"]
        if found:
            r["status"], r["post_id"], r["post_url"] = "posted", found[0], found[1]
            r["posted_at"] = r.get("posted_at") or now.isoformat()
            log(st, now, "confirmed earlier post %s" % r["story_id"])
        elif now - datetime.fromisoformat(r.get("last_attempt_at") or r["created_at"]) >= timedelta(minutes=10):
            r["status"] = "queued" if r["attempts"] < MAX_ATTEMPTS else "failed"
            r["next_attempt_at"] = now.isoformat()
            log(st, now, "earlier attempt for %s did not post; will retry" % r["story_id"])
        else:
            return "live: waiting to confirm %s" % r["story_id"]

    if st.get("backoff_until") and datetime.fromisoformat(st["backoff_until"]) > now:
        return "live: rate limited until %s" % st["backoff_until"]
    st.pop("backoff_until", None)
    ok, why = slot_open(cfg, st, now)
    okb, _ = slot_open(cfg, st, now, breaking=True)
    r = next_item(cfg, st, now, ok, okb, platform)
    if not r:
        return "live: nothing to post (%s)" % (why or "no worthwhile new story")
    # Never post twice: if we've tried before, look first.
    if r["attempts"] > 0:
        try:
            found = find_existing(platform, client, r, st)
            if found:
                r["status"], r["post_id"], r["post_url"], r["posted_at"] = "posted", found[0], found[1], now.isoformat()
                return "live: confirmed earlier post %s" % r["story_id"]
        except (Temporary, RateLimited, Uncertain, Permanent, AuthError):
            pass
    r["status"], r["attempts"], r["last_attempt_at"], r["posted_at"] = "posting", r["attempts"] + 1, now.isoformat(), now.isoformat()
    save()  # record the attempt before calling the platform
    try:
        if platform == "facebook":
            pid, purl = client.post(r["caption"], r["dest"])
        else:
            pid, purl = client.post(r["caption"])
    except AuthError as e:
        r["status"], r["posted_at"] = "queued", None
        r["errors"].append({"at": now.isoformat(), "msg": scrub(str(e), secret_values)})
        st["paused"] = {"reason": scrub(str(e), secret_values), "at": now.isoformat(), "token": fp}
        return "live: paused (%s)" % st["paused"]["reason"]
    except RateLimited as e:
        r["status"], r["posted_at"] = "queued", None
        r["next_attempt_at"] = e.retry_at.isoformat()
        st["backoff_until"] = e.retry_at.isoformat()  # platform limits apply to the whole account
        r["errors"].append({"at": now.isoformat(), "msg": scrub(str(e), secret_values)})
        return "live: rate limited until %s" % e.retry_at.isoformat()
    except Uncertain as e:
        r["status"] = "uncertain"
        r["errors"].append({"at": now.isoformat(), "msg": scrub(str(e), secret_values)})
        return "live: result unclear for %s, will check before retrying" % r["story_id"]
    except Temporary as e:
        r["posted_at"] = None
        r["errors"].append({"at": now.isoformat(), "msg": scrub(str(e), secret_values)})
        if r["attempts"] >= MAX_ATTEMPTS:
            r["status"] = "failed"
        else:
            r["status"] = "queued"
            r["next_attempt_at"] = (now + timedelta(minutes=15 * 2 ** (r["attempts"] - 1))).isoformat()
        return "live: temporary failure, retry later"
    except Permanent as e:
        r["status"], r["posted_at"] = "failed", None
        r["errors"].append({"at": now.isoformat(), "msg": scrub(str(e), secret_values)})
        return "live: refused (%s)" % scrub(str(e), secret_values)
    r["status"], r["post_id"], r["post_url"] = "posted", pid, purl
    decide(st, now, r["story_id"], r["title"], "posted", post_reason(r, now))
    log(st, now, "posted %s" % r["story_id"])
    return "live: posted %s" % r["story_id"]


def prune(st, now, days=30):
    cutoff = now - timedelta(days=days)
    st["items"] = {k: v for k, v in st["items"].items()
                   if datetime.fromisoformat(v["created_at"]) >= cutoff or v["status"] in ("posting", "uncertain")}


# ------------------------------------------------------------------ editor page

def build_editor_page(settings, states, now, site_dir, traffic=None):
    import build_site as b
    E = html.escape
    names = {"facebook": "Facebook Page", "x": "X account"}
    out = [b.head("Social posts", "Editor view", "/editor/social/", extra='<meta name="robots" content="noindex, nofollow">'),
           '<main class="wrap"><div class="page-head"><h1>Social posts</h1><p>Queue, previews, posts, decisions and traffic for automatic '
           'posting. Change settings in <code>social.json</code> on GitHub. Updated %s ET.</p></div>' % now.astimezone(EASTERN).strftime("%b %-d, %-I:%M %p")]

    # Posting frequency vs traffic, per day
    freq = {p: frequency(states[p]) for p in PLATFORMS}
    traffic = traffic or {}
    days = sorted(set(freq["facebook"]) | set(freq["x"]) | set(traffic.get("days", {})))[-14:]
    out.append('<h2 class="sec-title" style="margin-top:20px">Posts and traffic by day</h2>')
    if not traffic.get("days"):
        out.append('<p class="note">Traffic columns fill in once the Cloudflare analytics token is added (see setup notes). '
                   'Dry-run counts are what would have been posted.</p>')
    out.append('<div class="table-box" style="overflow-x:auto"><table class="waits" style="min-width:640px"><thead><tr><th>Day (UTC)</th>'
               '<th>Facebook posts</th><th>X posts</th><th>Visits from Facebook</th><th>Visits from X</th>'
               '<th>Story page views</th><th>Clicks to publishers</th></tr></thead><tbody>')
    for d in reversed(days):
        t = traffic.get("days", {}).get(d, {})
        cell = lambda p: ("%d" % freq[p][d]["posted"] + (" (+%d dry run)" % freq[p][d]["dry_run"] if freq[p][d]["dry_run"] else "")) if d in freq[p] else "0"
        val = lambda k: str(t[k]) if k in t else "—"
        out.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
            d, cell("facebook"), cell("x"), val("from_facebook"), val("from_x"), val("story_views"), val("outbound")))
    out.append("</tbody></table></div>")

    order = {"posting": 0, "uncertain": 1, "queued": 2, "posted": 3, "dry_run": 4, "failed": 5, "merged": 6, "skipped": 7, "expired": 8}
    for p in PLATFORMS:
        cfg, st = settings[p], states[p]
        ok, why = slot_open(cfg, st, now)
        out.append('<h2 class="sec-title" style="margin-top:28px">%s · mode: %s%s</h2>' % (
            names[p], E(cfg["mode"]), (" · PAUSED: " + E(st["paused"]["reason"])) if st.get("paused") else ""))
        if st.get("account", {}).get("name"):
            out.append('<p class="note">Connected to <strong>%s</strong> (checked %s ET).</p>' % (
                E(st["account"]["name"]), datetime.fromisoformat(st["account"]["checked_at"]).astimezone(EASTERN).strftime("%b %-d, %-I:%M %p")))
        out.append('<p class="note">No daily limit. At least %d minutes between posts, %d:00–%d:00 ET (verified breaking news may go any time). '
                   'Minimum importance %d, posts within %dh of publication. Next slot: %s.</p>' % (
                       cfg["min_gap_minutes"], cfg["hours"][0], cfg["hours"][1], cfg["min_score"], cfg["max_age_hours"],
                       "open now" if ok else E(why)))
        out.append('<table class="waits" style="min-width:0"><thead><tr><th>Status</th><th>Post text</th><th>Links</th><th>Why</th></tr></thead><tbody>')
        rows = sorted(st["items"].values(), key=lambda r: (order.get(r["status"], 9), r["created_at"]))
        for r in rows[:60]:
            prev = r.get("preview") or {}
            out.append('<tr><td><strong>%s</strong>%s<br><code>%s</code>%s</td><td style="white-space:pre-wrap;max-width:520px">%s'
                       '<div class="note" style="margin-top:6px;border:1px solid #D5D9DE;padding:6px">Link preview: <strong>%s</strong><br>%s</div></td>'
                       '<td><a href="%s">HaulTimes page</a>%s</td><td class="note">%s</td></tr>' % (
                           E(r["status"]), " · breaking" if r.get("breaking") else "", E(r["story_id"]), " (edited)" if r.get("edited") else "",
                           E(r["caption"]), E(prev.get("og:title", "")), E(prev.get("og:description", "")), E(r["dest"]),
                           ('<br><a href="%s">View post</a>' % E(r["post_url"])) if r.get("post_url") else "",
                           E("; ".join([r.get("breaking") or r.get("reason", "")] + [e["msg"] for e in r.get("errors", [])[-2:]]))))
        out.append("</tbody></table>")
        out.append('<h3 class="sec-title" style="margin-top:18px;font-size:13px">%s decision log (latest first)</h3>' % names[p])
        out.append('<table class="waits" style="min-width:0"><thead><tr><th>Time (ET)</th><th>Story</th><th>Decision</th><th>Why</th></tr></thead><tbody>')
        for dcs in reversed(st.get("decisions", [])[-80:]):
            out.append("<tr><td>%s</td><td>%s<br><code>%s</code></td><td><strong>%s</strong></td><td class=\"note\">%s</td></tr>" % (
                datetime.fromisoformat(dcs["at"]).astimezone(EASTERN).strftime("%b %-d %-I:%M %p"), E(dcs["title"]),
                E(dcs["story_id"]), E(dcs["action"]), E(dcs["reason"])))
        out.append("</tbody></table>")
    out.append("</main>")
    out.append(b.footer())
    path = os.path.join(site_dir, "editor", "social", "index.html")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(out))


# ------------------------------------------------------------------ samples (dry run, no state change)

def samples(n=10, now=None, site_dir=SITE):
    now = now or datetime.now(timezone.utc)
    stories = load_json("news.json", [])
    if stories and "status" not in stories[0]:
        editorial.reprocess(stories, now)
    picked = []
    for s in sorted(editorial.eligible(stories), key=lambda s: editorial.rank_score(s, now), reverse=True):
        cfg = dict(DEFAULTS["facebook"], max_age_hours=10 ** 6)  # same rules as the live queue, minus freshness
        if why_not(s, cfg, now):
            continue
        if any(similar(s.get("orig_title") or s["title"], p.get("orig_title") or p["title"]) for p in picked):
            continue
        picked.append(s)
        if len(picked) == n:
            break
    out = []
    for s in picked:
        out.append({"story_id": s["id"], "title": s["title"], "source": s["source"], "category": CATEGORIES[s["category"]][0],
                    "score": s["importance"], "published": s["published"],
                    "facebook": {"caption": facebook_caption(s), "link": dest_url(s, "facebook"),
                                 "words": words(facebook_caption(s))},
                    "x": {"text": x_text(s), "length": x_weighted_length(x_text(s))},
                    "page_check": page_problem(s, site_dir) or "ok", "preview": preview_meta(s, site_dir)})
    return out


def main(argv):
    if "--samples" in argv:
        i = argv.index("--samples")
        n = int(argv[i + 1]) if len(argv) > i + 1 else 10
        print(json.dumps(samples(n), indent=1, ensure_ascii=False))
        return 0
    now = datetime.now(timezone.utc)
    settings = load_settings()
    stories = load_json("news.json", [])
    if stories and "status" not in stories[0]:
        editorial.reprocess(stories, now)
    states = {}
    for p in PLATFORMS:
        name = "social_%s.json" % p
        st = load_json(name, new_state())
        client, secret_values = (make_client(p) if settings[p]["mode"] == "live" else (None, []))
        try:
            msg = run_platform(p, stories, settings[p], st, now, SITE, client, secret_values,
                               save=lambda st=st, name=name: save_json(name, st))
        except Exception as e:  # never let one platform break the other or the site update
            msg = "error: %s" % scrub("%s: %s" % (type(e).__name__, e), secret_values)
            log(st, now, msg)
        prune(st, now)
        save_json(name, st)
        states[p] = st
        acct = st.get("account", {})
        print("%s: %s%s" % (p, msg, (" | connected to %s" % acct["name"]) if acct.get("name") and settings[p]["mode"] == "live" else ""))
    try:
        import traffic as tr
        traffic = tr.update(now)
    except Exception as e:
        traffic = load_json("traffic.json", {})
        print("traffic stats skipped:", type(e).__name__, e)
    try:
        build_editor_page(settings, states, now, SITE, traffic)
    except Exception as e:
        print("editor page failed:", type(e).__name__, e)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
