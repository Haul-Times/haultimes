"""
Build the HaulTimes website into the site/ folder from data/news.json and
data/border.json. Pages are plain HTML so Google can read them, with a little
JavaScript for filters and live times.
"""

import html
import re
import json
import os
import shutil
import sys
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

from common import CATEGORIES, IMAGES, SITE, STATIC, load_config, load_json

try:
    from zoneinfo import ZoneInfo
    EASTERN = ZoneInfo("America/Toronto")
except Exception:  # pragma: no cover
    EASTERN = timezone(timedelta(hours=-5))

E = html.escape
NOW = datetime.now(timezone.utc)
CFG = load_config()
BASE = CFG["site_url"].rstrip("/")
FONTS = ("https://fonts.googleapis.com/css2?family=Playfair+Display:wght@900&family=Archivo:wdth,wght@62..125,400..900"
         "&family=Newsreader:ital,opsz,wght@0,6..72,400..600;1,6..72,500..700"
         "&family=Barlow:wght@400;500;600;700&display=swap")
MARK = ('<svg viewBox="0 0 64 64" aria-hidden="true"><rect width="64" height="64" rx="12" fill="#FFB800"/>'
        '<path d="M8 56 L29 12 L35 12 L56 56 Z" fill="#101826"/><rect x="30.5" y="18" width="3" height="6" fill="#FFB800"/>'
        '<rect x="30" y="29" width="4" height="8" fill="#FFB800"/><rect x="29.4" y="42" width="5.2" height="10" fill="#FFB800"/></svg>')


# ---------------------------------------------------------------- helpers

def when(s):
    return datetime.fromisoformat(s["published"])


def hours_old(s):
    return (NOW - when(s)).total_seconds() / 3600


def ago(dt):
    m = max(0, int((NOW - dt).total_seconds() // 60))
    if m < 1:
        return "Just now"
    if m < 60:
        return "%d min ago" % m
    h = round(m / 60)
    if h < 24:
        return "%dh ago" % h
    d = round(h / 24)
    return "Yesterday" if d == 1 else "%d days ago" % d


def time_tag(s):
    dt = when(s)
    return '<time datetime="%s" data-ago>%s</time>' % (dt.isoformat(), ago(dt))


def clock(s):
    return when(s).astimezone(EASTERN).strftime("%-I:%M %p") if os.name != "nt" else when(s).astimezone(EASTERN).strftime("%I:%M %p")


def cat_label(c):
    return CATEGORIES.get(c, CATEGORIES["other"])[0]


def cat_url(c):
    return "/topic/%s/" % CATEGORIES.get(c, CATEGORIES["other"])[1]


def has_page(s):
    """Headline-only stories (no AI summary yet) link straight to the source."""
    return s.get("ai", True) is not False


def story_url(s):
    return "/story/%s/" % s["slug"] if has_page(s) else s["link"]


def topic_art(cat):
    """Our own topic graphic, used when a story has no photo."""
    label = E(cat_label(cat).upper())
    return ('<svg viewBox="0 0 480 270" role="img" aria-label="%s" preserveAspectRatio="xMinYMid slice">'
            '<rect width="480" height="270" fill="#101826"/>'
            '<path d="M150 270 L232 60 L248 60 L330 270 Z" fill="#1C2A40"/>'
            '<path d="M236 80 h8 v22 h-8z M234 125 h12 v30 h-12z M231 185 h18 v45 h-18z" fill="#FFB800" opacity=".8"/>'
            '<path d="M0 60 H480" stroke="#22324A" stroke-width="2"/>'
            '<text x="24" y="46" fill="#FFB800" font-family="Archivo, Arial Narrow, sans-serif" font-weight="800" '
            'font-size="22" letter-spacing="2">%s</text></svg>') % (label, label)


def pic(s):
    if s.get("image"):
        return '<div class="pic"><img src="/%s" alt="" loading="lazy"></div>' % E(s["image"])
    return ""  # no real photo: clean text-only layout, like a newspaper


def write(path, content):
    full = os.path.join(SITE, path.lstrip("/"))
    if full.endswith("/"):
        full = os.path.join(full, "index.html")
    os.makedirs(os.path.dirname(full), exist_ok=True)
    if full.endswith(".html"):
        content = re.sub(r'<a href="(https?://[^"]+)">', r'<a href="\1" rel="nofollow noopener" target="_blank">', content)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)


# ---------------------------------------------------------------- page shell

def head(title, desc, path, image=None, extra=""):
    full_title = title if title.startswith(CFG["site_name"]) else "%s | %s" % (title, CFG["site_name"])
    analytics = ""
    if CFG.get("cloudflare_analytics_token"):
        analytics = ("<script defer src=\"https://static.cloudflareinsights.com/beacon.min.js\" "
                     "data-cf-beacon='{\"token\": \"%s\"}'></script>" % E(CFG["cloudflare_analytics_token"]))
    verify = ('<meta name="google-site-verification" content="%s">' % E(CFG["google_site_verification"])
              if CFG.get("google_site_verification") else "")
    og_img = image or BASE + "/static/og.png"
    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{t}</title>
<meta name="description" content="{d}">
<link rel="canonical" href="{u}">
<meta property="og:site_name" content="{n}">
<meta property="og:title" content="{t}">
<meta property="og:description" content="{d}">
<meta property="og:url" content="{u}">
<meta property="og:type" content="website">
<meta property="og:image" content="{img}">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
<link rel="alternate" type="application/rss+xml" title="{n}" href="/rss.xml">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{fonts}">
<link rel="stylesheet" href="/static/style.css">
{verify}{analytics}{extra}
</head>
<body>
""".format(t=E(full_title), d=E(desc), u=E(BASE + path), n=E(CFG["site_name"]), img=E(og_img),
           fonts=E(FONTS), verify=verify, analytics=analytics, extra=extra)


def header(active, stories):
    today = NOW.astimezone(EASTERN).strftime("%A, %B %-d, %Y")
    links = ['<a href="/"%s>Top news</a>' % (' class="on"' if active == "home" else ""),
             '<a href="/border-wait-times/"%s>Border wait times</a>' % (' class="on"' if active == "border-waits" else "")]
    for key, (label, slug) in CATEGORIES.items():
        links.append('<a href="/topic/%s/"%s>%s</a>' % (slug, ' class="on"' if active == key else "", E(label)))
    latest = sorted(stories, key=when, reverse=True)[:12]
    items = "".join('<a href="%s"><time>%s</time>%s</a>' % (story_url(s), clock(s), E(s["title"])) for s in latest)
    ticker = ""
    if latest:
        ticker = ('<div class="ticker"><div class="wrap"><span class="label">Latest</span>'
                  '<div class="lane"><div class="track">%s%s</div></div></div></div>') % (items, items.replace("<a ", '<a tabindex="-1" aria-hidden="true" '))
    return """<div class="topbar"><div class="wrap"><span>{today} · Updated every 15 minutes</span>
<nav aria-label="Site"><a href="/rss.xml">RSS</a><a href="/contact/">Advertise</a><a href="/about/">About</a></nav></div></div>
<header class="masthead"><div class="wrap">
<a class="logo" href="/" aria-label="{name} home">HaulTimes</a>
</div></header>
<nav class="sections" aria-label="Sections"><div class="wrap">{links}</div></nav>
{ticker}
""".format(today=E(today), name=E(CFG["site_name"]), mark=MARK, tag=E(CFG["tagline"]), links="".join(links), ticker=ticker)


def footer(scripts=""):
    return """<footer class="site"><div class="wrap">
<span><strong style="color:#111418">{n}</strong> · Freight and trucking news for the US and Canada</span>
<nav aria-label="Footer"><a href="/about/">About</a><a href="/contact/">Contact</a><a href="/privacy/">Privacy</a><a href="/rss.xml">RSS</a></nav>
</div></footer>
<script src="/static/site.js" defer></script>{scripts}
</body></html>""".format(n=E(CFG["site_name"]), scripts=scripts)


def ad(box=False):
    if not CFG.get("show_ad_slots"):
        return ""
    return '<div class="ad%s">Advertisement</div>' % (" box" if box else "")


def signup():
    action = CFG.get("newsletter_form_action")
    if not action:
        return ""
    return """<section class="signup" aria-label="Newsletter"><h2>The 6 AM Haul</h2>
<p>The day's top freight stories in your inbox before the first load. Free, every weekday.</p>
<form action="{a}" method="post" target="_blank" class="signup">
<label for="nl-email" style="font-size:13px;font-weight:600">Email address</label>
<input id="nl-email" name="email" type="email" required placeholder="you@company.com">
<button class="btn" type="submit">Subscribe</button></form></section>""".format(a=E(action))


# ---------------------------------------------------------------- pages

def build_home(stories, border):
    recent = [s for s in stories if hours_old(s) <= 48] or stories[:20]
    by_score = sorted(recent, key=lambda s: (s["importance"], s["published"]), reverse=True)
    used = set()

    def take(pool, n, cond=lambda s: True):
        out = []
        for s in pool:
            if s["id"] not in used and cond(s):
                out.append(s)
                used.add(s["id"])
                if len(out) == n:
                    break
        return out

    lead = take(by_score, 1)
    lead = lead[0] if lead else None
    left = take(by_score, 4)
    related = take(sorted(stories, key=when, reverse=True), 2, lambda s: lead and s["category"] == lead["category"]) if lead else []
    more_latest = take(sorted(stories, key=when, reverse=True), 6) if lead else []
    week = sorted([s for s in stories if hours_old(s) <= 168], key=lambda s: s["importance"], reverse=True)
    top_week = take(week, 5)

    out = [head(CFG["site_name"] + " | " + CFG["tagline"],
                "Freight and trucking news for the US and Canada, updated every 15 minutes: rates, border crossings, regulations, fuel, equipment and drivers.", "/"),
           header("home", stories), '<main class="wrap">']

    if not lead:
        out.append('<p class="empty">The first stories arrive within 15 minutes of launch. Meanwhile, check the <a href="/border-wait-times/">live border wait times</a>.</p>')
    else:
        lc = ['<div class="col-left">']
        for i, s in enumerate(left):
            lc.append('<article class="stack-item">%s<a class="kicker" href="%s">%s</a><h3 class="h-md"><a href="%s">%s</a></h3>'
                      '<span class="meta">%s · %s</span></article>' % (
                          pic(s) if i == 0 else "", cat_url(s["category"]), E(cat_label(s["category"])),
                          story_url(s), E(s["title"]), time_tag(s), E(s["source"])))
        lc.append("</div>")
        rel = "".join('<div><h3 class="h-sm"><a href="%s">%s</a></h3><span class="meta">%s · %s</span></div>' % (
            story_url(s), E(s["title"]), time_tag(s), E(s["source"])) for s in related)
        why = '<p class="why"><strong>Why it matters:</strong> %s</p>' % E(lead["why"]) if lead.get("why") else ""
        lead_html = """<section class="col-lead" aria-label="Top story">{pic}
<a class="kicker hot" href="{cu}">{cl}</a>
<h1 class="h-xl"><a href="{su}">{t}</a></h1>
{sm}{why}
<span class="meta">{tm} · via {src}{cm} · <a href="{link}" rel="nofollow noopener" target="_blank">Read full story</a></span>
{rel}{more}</section>""".format(more=('<section class="lead-more" aria-label="More headlines"><h2 class="sec-title">More headlines</h2>%s</section>' % "".join(
                          '<article class="lm"><a class="kicker" href="%s">%s</a><h3 class="h-sm"><a href="%s">%s</a></h3><span class="meta">%s · %s</span></article>' % (
                              cat_url(x["category"]), E(cat_label(x["category"])), story_url(x), E(x["title"]), time_tag(x), E(x["source"])) for x in more_latest)) if more_latest else "",
                          pic=pic(lead), cu=cat_url(lead["category"]), cl=E(cat_label(lead["category"])), su=story_url(lead),
                          t=E(lead["title"]), sm=('<p class="dek">%s</p>' % E(lead["summary"])) if lead.get("summary") else "", why=why,
                          cm=(' · <a href="%s">Comments</a>' % story_url(lead)) if has_page(lead) and CFG.get("cusdis_app_id") else "", tm=time_tag(lead), src=E(lead["source"]),
                          link=E(lead["link"]), rel=('<div class="related">%s</div>' % rel) if rel else "")
        right = ['<aside class="col-right">']
        if top_week:
            right.append('<section aria-label="Top stories this week"><h2 class="sec-title">Top this week</h2><ol class="ranked">%s</ol></section>' %
                         "".join('<li><a href="%s">%s</a></li>' % (story_url(s), E(s["title"])) for s in top_week))
        bw = [c for c in (border or {}).get("crossings", []) if c.get("south") and c["south"].get("wait") is not None]
        if bw:
            bw.sort(key=lambda c: c["south"]["wait"], reverse=True)
            right.append('<section aria-label="Border waits"><h2 class="sec-title"><a href="/border-wait-times/">Truck border waits ›</a></h2>'
                         '<ul class="mini-border">%s</ul><p class="note">Into the US, commercial lanes.</p></section>' %
                         "".join('<li><a href="/border-wait-times/">%s</a><strong>%s</strong></li>' % (E(c["name"]), fmt_wait(c["south"]["wait"])) for c in bw[:5]))
        else:
            right.append('<section><h2 class="sec-title"><a href="/border-wait-times/">Truck border waits ›</a></h2>'
                         '<p>Live commercial wait times at every major US–Canada crossing.</p></section>')
        right.append(ad(True))
        right.append(signup())
        right.append("</aside>")
        out.append('<div class="front">%s%s%s</div>' % ("".join(lc), lead_html, "".join(right)))
        out.append(ad())

        blocks = []
        for key, (label, slug) in CATEGORIES.items():
            pool = sorted([s for s in stories if s["category"] == key and s["id"] not in used and hours_old(s) <= 96],
                          key=lambda s: (s["importance"], s["published"]), reverse=True)
            if not pool:
                continue
            first, more = pool[0], pool[1:4]
            used.update(s["id"] for s in pool[:4])
            blocks.append('<section class="block"><h2 class="sec-title"><a href="/topic/%s/">%s ›</a></h2>%s'
                          '<h3 class="h-md"><a href="%s">%s</a></h3><span class="meta">%s · %s</span><div class="more">%s</div></section>' % (
                              slug, E(label), pic(first), story_url(first), E(first["title"]), time_tag(first), E(first["source"]),
                              "".join('<a href="%s">%s</a>' % (story_url(s), E(s["title"])) for s in more)))
        if blocks:
            out.append('<div class="blocks">%s</div>' % "".join(blocks))
    out.append("</main>")
    out.append(footer())
    write("/", "".join(out))


def fmt_wait(w):
    if w is None:
        return "—"
    return "%d min" % w if w < 60 else "%d h %d min" % (w // 60, w % 60)


def story_row(s):
    return ('<article class="row" data-time="%s" data-score="%d">%s<div class="txt"><a class="kicker" href="%s">%s</a>'
            '<h2 class="h-md"><a href="%s">%s</a></h2>%s<span class="meta">%s · %s</span></div></article>') % (
        when(s).isoformat(), s["importance"], pic(s), cat_url(s["category"]), E(cat_label(s["category"])),
        story_url(s), E(s["title"]), ("<p>%s</p>" % E(s["summary"])) if s.get("summary") else "", time_tag(s), E(s["source"]))


def build_topic(key, stories, all_stories):
    label, slug = CATEGORIES[key]
    items = sorted([s for s in stories if s["category"] == key], key=when, reverse=True)
    top = sorted(items, key=lambda s: s["importance"], reverse=True)[:5]
    desc = "Latest %s news for truckers, carriers, brokers and shippers in the US and Canada." % label.lower()
    filters = """<div class="filters"><div class="group"><span class="lbl">Show</span>
<button class="chip" data-range="today" aria-pressed="false">Today</button><button class="chip" data-range="week" aria-pressed="false">This week</button>
<button class="chip" data-range="month" aria-pressed="false">This month</button><button class="chip" data-range="all" aria-pressed="true">All</button></div>
<div class="group"><span class="lbl">Sort</span><button class="chip" data-sort="new" aria-pressed="true">Newest</button>
<button class="chip" data-sort="top" aria-pressed="false">Most important</button></div></div>"""
    side = ""
    if top:
        side = '<section><h2 class="sec-title">Most important</h2><ol class="ranked">%s</ol></section>' % "".join(
            '<li><a href="%s">%s</a></li>' % (story_url(s), E(s["title"])) for s in top)
    page = [head("%s News" % label, desc, "/topic/%s/" % slug), header(key, all_stories),
            '<main class="wrap"><div class="page-head"><h1>%s</h1><p>%s</p></div>%s' % (E(label), E(desc), filters),
            '<div class="list"><div class="list-main"><div id="story-list">%s</div><p id="no-stories" class="empty" %s>No stories in this time range yet. Try “All”.</p></div>'
            % ("".join(story_row(s) for s in items), "hidden" if items else ""),
            '<aside class="list-side">%s%s%s</aside></div></main>' % (side, ad(True), signup()), footer()]
    write("/topic/%s/" % slug, "".join(page))


def build_story(s, stories):
    related = sorted([x for x in stories if x["category"] == s["category"] and x["id"] != s["id"]], key=when, reverse=True)[:5]
    comments = ""
    if CFG.get("cusdis_app_id"):
        comments = """<section class="comments" aria-label="Comments"><h2 class="sec-title" style="border:0">Talk about this story</h2>
<p class="note">Comments appear after a quick review.</p>
<div id="cusdis_thread" data-host="https://cusdis.com" data-app-id="{a}" data-page-id="{i}" data-page-url="{u}" data-page-title="{t}" data-theme="light"></div>
<script async defer src="https://cusdis.com/js/cusdis.es.js"></script>
</section>""".format(a=E(CFG["cusdis_app_id"]), i=E(s["id"]), u=E(BASE + story_url(s)), t=E(s["title"]))
    why = '<p class="why"><strong>Why it matters:</strong> %s</p>' % E(s["why"]) if s.get("why") else ""
    img = BASE + "/" + s["image"] if s.get("image") else None
    body = """<main class="wrap"><div class="story"><article>
<a class="kicker" href="{cu}">{cl}</a>
<h1 class="h-xl">{t}</h1>
<span class="meta">{tm} · {region} · via {src}</span>
{pic}
<p class="dek">{sm}</p>{why}
<div class="source-box"><span>This is a short summary. The full story is published by <strong>{src}</strong>.</span>
<a class="btn amber" href="{link}" rel="nofollow noopener" target="_blank">Read the full story ›</a></div>
{comments}</article>
<aside>{rel}{ad}{signup}</aside></div></main>""".format(
        cu=cat_url(s["category"]), cl=E(cat_label(s["category"])), t=E(s["title"]), tm=time_tag(s),
        region=E(s.get("region", "")), src=E(s["source"]), pic=pic(s), sm=E(s["summary"]), why=why, link=E(s["link"]),
        comments=comments, ad=ad(True), signup=signup(),
        rel=('<section><h2 class="sec-title">More %s</h2><ol class="ranked">%s</ol></section>' % (
            E(cat_label(s["category"])), "".join('<li><a href="%s">%s</a></li>' % (story_url(x), E(x["title"])) for x in related))) if related else "")
    write(story_url(s), head(s["title"], s["summary"] or s["title"], story_url(s), img) + header(s["category"], stories) + body + footer())


REGIONS = [("all", "All"), ("on-mi", "Ontario–Michigan"), ("on-ny", "Ontario–New York"), ("on-mn", "Ontario–Minnesota"),
           ("qc", "Quebec"), ("atl", "Atlantic"), ("pra", "Prairies"), ("bc", "British Columbia")]


def build_border(border, stories):
    data = border or {"crossings": [], "hour_now": 0}
    crossings = data.get("crossings", [])
    rows = []
    for c in sorted(crossings, key=lambda c: c["name"]):
        w = c["south"]["wait"] if c.get("south") else None
        rows.append('<tr><td><span class="n">%s</span><div class="p">%s</div></td><td>%s</td><td>%s</td><td></td></tr>' % (
            E(c["name"]), E(c["ports"]), fmt_wait(w), E(c.get("best_south", ""))))
    updated = ""
    if data.get("updated"):
        updated = datetime.fromisoformat(data["updated"]).astimezone(EASTERN).strftime("%-I:%M %p ET, %b %-d")
    regions = "".join('<button class="chip" data-region="%s" aria-pressed="%s">%s</button>' % (k, "true" if k == "all" else "false", E(v)) for k, v in REGIONS)
    note = ""
    if data and not data.get("have_us", True):
        note += "<p class=\"note\">US wait times are temporarily unavailable.</p>"
    if data and not data.get("have_ca", True):
        note += "<p class=\"note\">Canadian wait times are temporarily unavailable.</p>"
    blob = json.dumps({"crossings": crossings, "hour_now": data.get("hour_now", 0)}, ensure_ascii=False).replace("</", "<\\/")
    body = """<main class="wrap">
<div class="page-head"><h1>Truck border wait times, US ↔ Canada</h1>
<p>Commercial lane waits at major crossings, refreshed every 15 minutes from official US and Canadian border data. Tap a crossing to see its usual wait by hour.</p>
<span class="meta">Last updated {upd}</span>{note}</div>
<div class="filters"><div class="group"><span class="lbl">Direction</span>
<button class="chip" data-dir="south" aria-pressed="true">Into the US (southbound)</button>
<button class="chip" data-dir="north" aria-pressed="false">Into Canada (northbound)</button></div>
<div class="group"><span class="lbl">Region</span>{regions}</div></div>
<div class="stats">
<div><span class="k">Fastest right now</span><span class="v" id="stat-fast">—</span><span id="stat-fast-w" style="color:var(--ok);font-weight:600"></span></div>
<div><span class="k">Longest wait</span><span class="v" id="stat-slow">—</span><span id="stat-slow-w" style="color:var(--bad);font-weight:600"></span></div>
<div><span class="k">Crossings shown</span><span class="v" id="stat-count">{n}</span><span id="stat-dir" style="color:var(--muted)">Trucks entering the US</span></div>
</div>
<div class="bw"><div class="table-box"><table class="waits"><thead><tr><th scope="col">Crossing</th><th scope="col">Truck wait</th>
<th scope="col">Usually fastest</th><th scope="col">Last report</th></tr></thead><tbody id="waits-body">{rows}</tbody></table></div>
<aside id="detail" aria-label="Crossing detail"><span class="k" style="font-size:13px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.05em">Usual truck wait by hour, <span id="d-dir">into the US</span></span>
<h2 class="h-xl" id="d-name" style="font-size:28px"></h2><span class="meta" id="d-ports"></span>
<div class="chart" role="img" aria-label="Usual commercial wait for each hour of today"><div class="y"><span>90m</span><span>60m</span><span>30m</span><span>0</span></div>
<div class="plot"><div class="bars" id="d-bars"></div><div class="x"><span>12 AM</span><span>6 AM</span><span>12 PM</span><span>6 PM</span><span>11 PM</span></div></div></div>
<p class="note" id="d-empty">History is still building. The chart fills in over the first few weeks.</p>
<p class="why"><strong>Best window:</strong> <span id="d-best"></span>. The darker bar is the current hour.</p>
<div class="legend"><span><i style="background:var(--ok)"></i>Light, under 30 min</span><span><i style="background:var(--mid)"></i>Moderate, 30–60</span><span><i style="background:var(--bad)"></i>Heavy, over 60</span></div>
{ad}</aside></div>
<p class="note" style="margin-top:18px">Wait times come from U.S. Customs and Border Protection and the Canada Border Services Agency (Open Government Licence – Canada). They are estimates; FAST lanes and booth openings can change waits quickly.</p>
</main>
<script id="border-data" type="application/json">{blob}</script>""".format(
        upd=E(updated or "soon"), note=note, regions=regions, n=len(crossings), rows="".join(rows), ad=ad(True), blob=blob)
    write("/border-wait-times/", head("Truck Border Wait Times US–Canada",
                                      "Live commercial truck wait times at US–Canada border crossings, updated every 15 minutes, with the usual fastest times to cross.",
                                      "/border-wait-times/") + header("border-waits", stories) + body +
          footer('<script src="/static/border.js" defer></script>'))


def build_static_pages(stories):
    about = """<main class="wrap prose"><h1>About {n}</h1>
<p>{n} brings freight and trucking news from across the US and Canada into one place, updated every 15 minutes, with live truck border wait times.</p>
<p>Every story links to its original publisher.</p>
<p>For advertising, corrections or anything else, use our <a href="/contact/">contact form</a>.</p></main>""".format(n=E(CFG["site_name"]))
    write("/about/", head("About", "About HaulTimes, freight and trucking news for the US and Canada.", "/about/") + header("", stories) + about + footer())

    key = CFG.get("contact_form_key", "")
    if key:
        form = """<form class="contact" action="https://api.web3forms.com/submit" method="POST">
<input type="hidden" name="access_key" value="{k}">
<input type="hidden" name="subject" value="New message from HaulTimes">
<input type="hidden" name="from_name" value="HaulTimes website">
<input type="hidden" name="redirect" value="{base}/contact/thanks/">
<input type="checkbox" name="botcheck" class="hp" tabindex="-1" autocomplete="off" aria-hidden="true">
<label for="c-name">Name</label><input id="c-name" name="name" type="text" required autocomplete="name">
<label for="c-email">Email</label><input id="c-email" name="email" type="email" required autocomplete="email">
<label for="c-topic">Topic</label><select id="c-topic" name="topic">
<option>Advertising</option><option>Correction or removal</option><option>News tip</option><option>Other</option></select>
<label for="c-msg">Message</label><textarea id="c-msg" name="message" rows="6" required></textarea>
<button class="btn" type="submit">Send message</button>
</form>""".format(k=E(key), base=E(BASE))
    else:
        form = '<p class="note">The contact form is being set up. Please check back soon.</p>'
    contact = """<main class="wrap prose"><h1>Contact</h1>
<p>Advertising, corrections, news tips or questions. Send us a message and we'll get back to you.</p>
{f}</main>""".format(f=form)
    write("/contact/", head("Contact", "Contact HaulTimes about advertising, corrections or news tips.", "/contact/") + header("", stories) + contact + footer())
    write("/contact/thanks/", head("Message sent", "Thanks for contacting HaulTimes.", "/contact/thanks/") + header("", stories) +
          '<main class="wrap prose"><h1>Thanks, your message was sent</h1><p>We\'ll reply as soon as we can. Back to the <a href="/">latest news</a>.</p></main>' + footer())

    privacy = """<main class="wrap prose"><h1>Privacy</h1>
<p>{n} does not ask for your name or an account to read the site.</p>
<p>We use privacy-friendly analytics to count visits and popular pages. It does not use cookies or track you across other websites.</p>
<p>Messages sent through the contact form are used only to reply to you.</p>
<p>Questions: use our <a href="/contact/">contact form</a>.</p></main>""".format(n=E(CFG["site_name"]))
    write("/privacy/", head("Privacy", "HaulTimes privacy policy.", "/privacy/") + header("", stories) + privacy + footer())
    write("/404.html", head("Page not found", "Page not found.", "/404.html") + header("", stories) +
          '<main class="wrap prose"><h1>Page not found</h1><p>That story may have expired. Head back to the <a href="/">latest news</a>.</p></main>' + footer())


def abs_url(s):
    u = story_url(s)
    return u if u.startswith("http") else BASE + u


HASHTAGS = {
    "rates": "#FreightRates #Trucking #Freight",
    "border": "#CrossBorder #Trucking #CanadaUS",
    "regs": "#FMCSA #TruckingNews #Trucking",
    "fuel": "#DieselPrices #Trucking #Fuel",
    "equip": "#Trucks #Trucking #Fleet",
    "drivers": "#TruckDrivers #Trucking #Truckers",
    "other": "#Trucking #Freight #Logistics",
}


def social_text(s):
    """Ready-to-post text for Facebook: summary, why it matters, hashtags."""
    parts = [s["summary"]] if s.get("summary") else []
    if s.get("why"):
        parts.append("Why it matters: " + s["why"])
    parts.append(HASHTAGS.get(s["category"], HASHTAGS["other"]) + " #HaulTimes")
    return "\n\n".join(parts)


def rss(stories, name, title, social=False):
    items = []
    for s in stories[:60]:
        if social:
            desc = social_text(s)
        else:
            desc = (s["summary"] + (" Why it matters: " + s["why"] if s.get("why") else "")).strip() or s["source"]
        items.append("<item><title>%s</title><link>%s</link><guid isPermaLink=\"true\">%s</guid><pubDate>%s</pubDate>"
                     "<category>%s</category><description>%s</description></item>" % (
                         E(s["title"]), E(abs_url(s)), E(abs_url(s)), format_datetime(when(s)),
                         E(cat_label(s["category"])), E(desc)))
    xml = ('<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>%s</title><link>%s</link>'
           '<description>%s</description><language>en</language><lastBuildDate>%s</lastBuildDate>%s</channel></rss>') % (
        E(title), E(BASE + "/"), E(CFG["tagline"]), format_datetime(NOW), "".join(items))
    write("/" + name, xml)


def build_feeds(stories):
    newest = sorted(stories, key=when, reverse=True)
    rss(newest, "rss.xml", CFG["site_name"])
    top = [s for s in newest if s["importance"] >= CFG.get("top_story_score", 80)]
    rss(top, "top.xml", CFG["site_name"] + " Top Stories")

    # facebook.xml: the few biggest stories of each day, for automatic Facebook posts.
    # A story enters once and stays, so the auto-poster never posts it twice.
    per_day = CFG.get("facebook_posts_per_day", 6)
    min_score = CFG.get("facebook_min_score", 70)
    by_day = {}
    for s in newest:
        if s["importance"] >= min_score and hours_old(s) <= 72:
            by_day.setdefault(when(s).astimezone(EASTERN).date(), []).append(s)
    fb = []
    for day, items in by_day.items():
        fb += sorted(items, key=lambda x: x["importance"], reverse=True)[:per_day]
    rss(sorted(fb, key=when, reverse=True), "facebook.xml", CFG["site_name"], social=True)
    urls = ["/", "/border-wait-times/", "/about/", "/contact/"] + ["/topic/%s/" % v[1] for v in CATEGORIES.values()] + [story_url(s) for s in newest if has_page(s)]
    sm = '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">%s</urlset>' % "".join(
        "<url><loc>%s</loc></url>" % E(BASE + u) for u in urls)
    write("/sitemap.xml", sm)
    write("/robots.txt", "User-agent: *\nAllow: /\nSitemap: %s/sitemap.xml\n" % BASE)


def main():
    stories = [s for s in load_json("news.json", []) if s.get("title")]
    stories.sort(key=when, reverse=True)
    border = load_json("border.json", None)

    if os.path.isdir(SITE):
        shutil.rmtree(SITE)
    os.makedirs(SITE)
    shutil.copytree(STATIC, os.path.join(SITE, "static"))
    if os.path.isdir(IMAGES):
        shutil.copytree(IMAGES, os.path.join(SITE, "images"))

    build_home(stories, border)
    for key in CATEGORIES:
        build_topic(key, stories, stories)
    for s in stories:
        if has_page(s):
            build_story(s, stories)
    build_border(border, stories)
    build_static_pages(stories)
    build_feeds(stories)
    print("Site built: %d stories, %d border crossings." % (len(stories), len((border or {}).get("crossings", []))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
