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

import editorial
import market_page
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


def _asset_version():
    """Short fingerprint of the CSS and JS, so phones load new designs right away."""
    import hashlib
    h = hashlib.sha1()
    for name in ("style.css", "site.js", "logo.svg"):
        try:
            with open(os.path.join(STATIC, name), "rb") as f:
                h.update(f.read())
        except OSError:
            pass
    return h.hexdigest()[:8]


ASSET_VER = _asset_version()


def _og_version(name="og.png"):
    import hashlib
    try:
        with open(os.path.join(STATIC, name), "rb") as f:
            return hashlib.sha1(f.read()).hexdigest()[:8]
    except OSError:
        return "1"


OG_VER = _og_version()
# Small square picture for story links: Facebook shows it as a thumbnail beside the
# headline instead of a full-width banner on every post.
STORY_IMG = BASE + "/static/og-square.png?v=" + _og_version("og-square.png")
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
    """Every story on the site has its own HaulTimes page: headline, publisher and the
    link to the original article, plus our summary once the AI is switched on."""
    return bool(s.get("slug"))


def has_summary(s):
    return bool(s.get("summary"))


def story_url(s):
    return "/story/%s/" % s["slug"] if has_page(s) else s["link"]


def out_url(s):
    """Link to the original article, through a short HaulTimes hop so outbound clicks
    show up (as /out/... page views) in Cloudflare Web Analytics."""
    return "/out/%s/" % s["id"]


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


def label(s):
    """'Press release' / 'Company announcement' / 'Sponsored' tag next to the source."""
    return "".join(' · <span class="tag">%s</span>' % E(x) for x in s.get("labels", []))


def src(s):
    return E(s["source"]) + label(s)


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

def analytics_tag():
    if not CFG.get("cloudflare_analytics_token"):
        return ""
    return ("<script defer src=\"https://static.cloudflareinsights.com/beacon.min.js\" "
            "data-cf-beacon='{\"token\": \"%s\"}'></script>" % E(CFG["cloudflare_analytics_token"]))


def head(title, desc, path, image=None, extra=""):
    full_title = title if title.startswith(CFG["site_name"]) else "%s | %s" % (title, CFG["site_name"])
    analytics = analytics_tag()
    verify = ('<meta name="google-site-verification" content="%s">' % E(CFG["google_site_verification"])
              if CFG.get("google_site_verification") else "")
    og_img = image or BASE + "/static/og.png?v=" + OG_VER  # new version number whenever the picture changes, so Facebook refetches it
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
<link rel="icon" href="/static/favicon.svg?v={ver}" type="image/svg+xml">
<link rel="alternate" type="application/rss+xml" title="{n}" href="/rss.xml">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{fonts}">
<link rel="stylesheet" href="/static/style.css?v={ver}">
{verify}{analytics}{extra}
</head>
<body>
""".format(t=E(full_title), d=E(desc), u=E(BASE + path), n=E(CFG["site_name"]), img=E(og_img),
           fonts=E(FONTS), verify=verify, analytics=analytics, extra=extra, ver=ASSET_VER)


def header(active, stories):
    today = NOW.astimezone(EASTERN).strftime("%A, %B %-d, %Y")
    links = ['<a href="/"%s>Top news</a>' % (' class="on"' if active == "home" else ""),
             '<a href="/border-wait-times/"%s>Border wait times</a>' % (' class="on"' if active == "border-waits" else ""),
             '<a href="/freight-market/"%s>Freight Market%s</a>' % (' class="on"' if active == "market" else "",
                                                                      '<b class="new-dot" aria-label="new"></b>' if market_new() else "")]
    for key, (label, slug) in CATEGORIES.items():
        links.append('<a href="/topic/%s/"%s>%s</a>' % (slug, ' class="on"' if active == key else "", E(label)))
    latest = sorted(stories, key=when, reverse=True)[:12]
    items = "".join('<a href="%s"><time>%s</time>%s</a>' % (story_url(s), clock(s), E(s["title"])) for s in latest)
    ticker = ""
    if latest:
        ticker = ('<div class="ticker"><div class="wrap"><span class="label">Latest</span>'
                  '<div class="lane"><div class="track">%s%s</div></div></div></div>') % (items, items.replace("<a ", '<a tabindex="-1" aria-hidden="true" '))
    return """<div class="topbar"><div class="wrap"><span>{today} · Updated every 15 minutes</span>
<nav aria-label="Site"><a href="/about/">About</a><a href="/contact/">Contact</a></nav></div></div>
<header class="masthead"><div class="wrap">
<a class="logo" href="/" aria-label="{name} home"><img src="/static/logo.svg?v={av}" alt="{name}" width="1962" height="331"></a>
</div></header>
<nav class="sections" aria-label="Sections"><div class="wrap">{links}</div></nav>
{ticker}
""".format(today=E(today), name=E(CFG["site_name"]), mark=MARK, tag=E(CFG["tagline"]), links="".join(links), ticker=ticker, av=ASSET_VER)


def footer(scripts=""):
    return """<footer class="site"><div class="wrap">
<span><strong style="color:#111418">{n}</strong> · Freight and trucking news for the US and Canada</span>
<nav aria-label="Footer"><a href="/about/">About</a><a href="/contact/">Contact</a><a href="/privacy/">Privacy</a><a href="/terms/">Terms</a></nav>
</div></footer>
<script src="/static/site.js?v={ver}" defer></script>{scripts}
</body></html>""".format(n=E(CFG["site_name"]), scripts=scripts, ver=ASSET_VER)


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

def market_new():
    """'New' tag on the Freight Market tab until the date in config.json (market_new_until)."""
    until = CFG.get("market_new_until", "2026-12-31")
    return NOW.date().isoformat() <= until


def market_card():
    """Homepage box: pick a lane and jump straight to the rate checker. Calm, not a pop-up."""
    regions = market_page._region_options()
    return """<section class="rate-card" aria-labelledby="rc-h"><span class="kicker">Freight Market{new}</span>
<h2 id="rc-h">Is your rate fair?</h2>
<p>Compare a load offer with what other carriers reported on the same lane.</p>
<form action="/freight-market/" method="get" class="rc-form">
<label>From<select name="o" required>{r}</select></label><label>To<select name="d" required>{r}</select></label>
<label>Equipment<select name="equipment">{eq}</select></label>
<button class="btn2" type="submit">Check this lane ›</button></form>
<p class="rc-alt"><a href="/freight-market/#rep">Hauled a load this week? Report your rate ›</a></p></section>""".format(
        r=regions, eq=market_page.EQ_OPTIONS, new=' <b class="new-tag">New</b>' if market_new() else "")


def market_strip(where=""):
    """One-line pointer used on phones under the top story, and in story/topic sidebars."""
    return ('<a class="rate-strip%s" href="/freight-market/#chk"><span><b>Is your rate fair?</b> '
            'Check any lane against what carriers are reporting.</span><span class="go">Check ›</span></a>') % (" " + where if where else "")


def build_home(stories, border):
    recent = [s for s in stories if hours_old(s) <= 48 or s.get("pinned")] or stories[:20]
    by_score = sorted(recent, key=lambda s: (editorial.rank_score(s, NOW), s["published"]), reverse=True)
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

    def front(s):  # minor crashes, crime, features and roundups stay on topic pages, not the front page
        return s.get("pinned") or s.get("kind", "news") in ("news", "disruption", "announcement", "event")

    lead = take(by_score, 1, editorial.lead_eligible) or take(by_score, 1)
    lead = lead[0] if lead else None
    left = take(by_score, 4, front)
    related = take(sorted(stories, key=when, reverse=True), 2, lambda s: front(s) and lead and s["category"] == lead["category"]) if lead else []
    more_latest = take(sorted(stories, key=when, reverse=True), 6, front) if lead else []
    week = sorted([s for s in stories if hours_old(s) <= 168 and s.get("kind", "news") in ("news", "disruption")],
                  key=lambda s: s["importance"], reverse=True)
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
                      '<span class="meta">%s · %s%s</span></article>' % (
                          pic(s) if i == 0 else "", cat_url(s["category"]), E(cat_label(s["category"])),
                          story_url(s), E(s["title"]), time_tag(s), src(s), share_icon(s)))
        lc.append("</div>")
        rel = "".join('<div><h3 class="h-sm"><a href="%s">%s</a></h3><span class="meta">%s · %s</span></div>' % (
            story_url(s), E(s["title"]), time_tag(s), src(s)) for s in related)
        why = '<p class="why"><strong>Why it matters:</strong> %s</p>' % E(lead["why"]) if lead.get("why") else ""
        lead_html = """<section class="col-lead" aria-label="Top story">{pic}
<a class="kicker hot" href="{cu}">{cl}</a>
<h1 class="h-xl"><a href="{su}">{t}</a></h1>
{sm}{why}
<span class="meta">{tm} · via {src}{cm} · <a href="{link}" rel="nofollow noopener" target="_blank">Original article at {src_plain} ›</a>{share}</span>
{strip}{rel}{more}</section>""".format(strip=market_strip("phone-only"), more=('<section class="lead-more" aria-label="More headlines"><h2 class="sec-title">More headlines</h2>%s</section>' % "".join(
                          '<article class="lm"><a class="kicker" href="%s">%s</a><h3 class="h-sm"><a href="%s">%s</a></h3><span class="meta">%s · %s%s</span></article>' % (
                              cat_url(x["category"]), E(cat_label(x["category"])), story_url(x), E(x["title"]), time_tag(x), src(x), share_icon(x)) for x in more_latest)) if more_latest else "",
                          pic=pic(lead), cu=cat_url(lead["category"]), cl=E(cat_label(lead["category"])), su=story_url(lead),
                          t=E(lead["title"]), sm=('<p class="dek">%s</p>' % E(lead["summary"])) if lead.get("summary") else "", why=why,
                          cm=(' · <a href="%s">Comments</a>' % story_url(lead)) if has_page(lead) and CFG.get("cusdis_app_id") else "", tm=time_tag(lead), src=src(lead),
                          link=out_url(lead), src_plain=E(lead["source"]), share=share_icon(lead), rel=('<div class="related">%s</div>' % rel) if rel else "")
        right = ['<aside class="col-right">', market_card()]
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
                          key=lambda s: (editorial.rank_score(s, NOW), s["published"]), reverse=True)
            if not pool:
                continue
            first, more = pool[0], pool[1:4]
            used.update(s["id"] for s in pool[:4])
            blocks.append('<section class="block"><h2 class="sec-title"><a href="/topic/%s/">%s ›</a></h2>%s'
                          '<h3 class="h-md"><a href="%s">%s</a></h3><span class="meta">%s · %s</span><div class="more">%s</div></section>' % (
                              slug, E(label), pic(first), story_url(first), E(first["title"]), time_tag(first), src(first),
                              "".join('<a href="%s">%s <span class="src-in">%s</span></a>' % (story_url(s), E(s["title"]), E(s["source"])) for s in more)))
        if blocks:
            out.append('<div class="blocks">%s</div>' % "".join(blocks))
    out.append("</main>")
    out.append(footer())
    write("/", "".join(out))


def fmt_wait(w):
    if w is None:
        return "—"
    return "%d min" % w if w < 60 else "%d h %d min" % (w // 60, w % 60)


SHARE_SVG = ('<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" '
             'stroke-linecap="round" stroke-linejoin="round"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/>'
             '<circle cx="18" cy="19" r="3"/><path d="M8.6 13.5l6.8 4M15.4 6.5l-6.8 4"/></svg>')


_I = '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" %s>%s</svg>'
SHARE_ICONS = {
    "text": _I % ('fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"', '<path d="M4 5h16v11H9l-5 4z"/>'),
    "whatsapp": _I % ('fill="currentColor"', '<path d="M12 2a10 10 0 0 0-8.6 15.1L2 22l5-1.3A10 10 0 1 0 12 2zm0 2a8 8 0 1 1-4.1 14.9l-.3-.2-3 .8.8-2.9-.2-.3A8 8 0 0 1 12 4zm-3.2 3.6c-.2 0-.6.1-.9.4-.3.3-1.1 1.1-1.1 2.6s1.1 3 1.3 3.2c.2.2 2.2 3.4 5.4 4.6 2.6 1 3.2.8 3.7.8.6-.1 1.8-.7 2-1.5.3-.7.3-1.3.2-1.5-.1-.1-.3-.2-.6-.4l-2-1c-.3-.1-.5-.1-.7.1l-.9 1.1c-.2.2-.3.2-.6.1-.3-.1-1.2-.5-2.3-1.4-.9-.8-1.4-1.7-1.6-2-.2-.3 0-.4.1-.6l.5-.6.3-.5v-.5l-.9-2.2c-.2-.6-.5-.6-.7-.6z"/>'),
    "facebook": _I % ('fill="currentColor"', '<path d="M14 8h3V4h-3c-2.8 0-4.5 1.8-4.5 4.6V11H7v4h2.5v7h4v-7h3l.5-4h-3.5V8.8c0-.5.3-.8.5-.8z"/>'),
    "email": _I % ('fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"', '<rect x="3" y="5" width="18" height="14" rx="1"/><path d="M3 6l9 7 9-7"/>'),
    "x": _I % ('fill="currentColor"', '<path d="M17.7 3h3.1l-6.8 7.8L22 21h-6.3l-4.9-6.4L5.2 21H2.1l7.3-8.3L1.8 3h6.4l4.4 5.9zm-1.1 16.2h1.7L7.4 4.7H5.6z"/>'),
    "copy": _I % ('fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"', '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>'),
}


def share_icon(s):
    """Small share button next to a headline. Opens the phone's share sheet, or a menu on computers."""
    return ' <button type="button" class="sh" data-u="%s" data-t="%s" aria-label="Share: %s">%s</button>' % (
        E(BASE + story_url(s)), E(s["title"]), E(s["title"]), SHARE_SVG)


def share_bar(s):
    """Row of share links on a story page. Plain links, so they work even without JavaScript."""
    from urllib.parse import quote
    url, title = BASE + story_url(s), s["title"]
    text = "%s %s" % (title, url)
    links = [
        ("text", "Text", "sms:?&body=" + quote(text)),
        ("whatsapp", "WhatsApp", "https://wa.me/?text=" + quote(text)),
        ("facebook", "Facebook", "https://www.facebook.com/sharer/sharer.php?u=" + quote(url, safe="")),
        ("email", "Email", "mailto:?subject=%s&body=%s" % (quote(title), quote("Saw this on HaulTimes:\n\n%s\n%s" % (title, url)))),
        ("x", "X", "https://x.com/intent/post?text=%s&url=%s" % (quote(title), quote(url, safe=""))),
    ]
    out = ['<div class="share" aria-label="Share this story"><span class="lbl">Share</span>']
    out.append('<button type="button" class="sh-native" data-u="%s" data-t="%s" hidden>%s Share…</button>' % (E(url), E(title), SHARE_SVG))
    for key, name, href in links:
        ext = "" if key in ("text", "email") else ' target="_blank" rel="noopener"'
        out.append('<a class="sh-%s" data-net="%s" href="%s"%s>%s<span>%s</span></a>' % (key, key, E(href), ext, SHARE_ICONS[key], name))
    out.append('<button type="button" class="sh-copy" data-u="%s">%s<span>Copy link</span></button></div>' % (E(url), SHARE_ICONS["copy"]))
    return "".join(out)


def story_row(s):
    return ('<article class="row" data-time="%s" data-score="%d">%s<div class="txt"><a class="kicker" href="%s">%s</a>'
            '<h2 class="h-md"><a href="%s">%s</a></h2>%s<span class="meta">%s · %s%s</span></div></article>') % (
        when(s).isoformat(), s["importance"], pic(s), cat_url(s["category"]), E(cat_label(s["category"])),
        story_url(s), E(s["title"]), "", time_tag(s), src(s), share_icon(s))  # lists stay headline-only


def build_topic(key, stories, all_stories):
    label, slug = CATEGORIES[key]
    items = sorted([s for s in stories if s["category"] == key], key=when, reverse=True)
    top = sorted([s for s in items if hours_old(s) <= 168 and s.get("kind", "news") not in ("incident", "crime", "feature", "roundup")],
                 key=lambda s: editorial.rank_score(s, NOW), reverse=True)[:5]
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
            '<aside class="list-side">%s%s%s%s</aside></div></main>' % (market_strip(), side, ad(True), signup()), footer()]
    write("/topic/%s/" % slug, "".join(page))


def build_story(s, stories):
    """The story's own HaulTimes page. Publisher and the link to the original article are
    right under the headline, so a reader arriving from Facebook, X or our homepage
    sees at once who reported it and where to read it."""
    related = sorted([x for x in stories if x["category"] == s["category"] and x["id"] != s["id"]], key=when, reverse=True)[:5]
    comments = ""
    if CFG.get("cusdis_app_id"):
        comments = """<section class="comments" aria-label="Comments"><h2 class="sec-title" style="border:0">Talk about this story</h2>
<p class="note">Comments appear after a quick review.</p>
<div id="cusdis_thread" data-host="https://cusdis.com" data-app-id="{a}" data-page-id="{i}" data-page-url="{u}" data-page-title="{t}" data-theme="light"></div>
<script async defer src="https://cusdis.com/js/cusdis.es.js"></script>
</section>""".format(a=E(CFG["cusdis_app_id"]), i=E(s["id"]), u=E(BASE + story_url(s)), t=E(s["title"]))
    pub = E(s["source"])
    if has_summary(s):
        why = '<p class="why"><strong>Why it matters:</strong> %s</p>' % E(s["why"]) if s.get("why") else ""
        body_text = '<p class="note">HaulTimes summary</p><p class="dek">%s</p>%s' % (E(s["summary"]), why)
    else:
        body_text = ('<p class="note">HaulTimes lists this headline and links to the original reporting. '
                     'The story was reported by %s, not by HaulTimes.</p>' % pub)
    img = BASE + "/" + s["image"] if s.get("image") else STORY_IMG
    body = """<main class="wrap"><div class="story"><article id="story-{sid}">
<a class="kicker" href="{cu}">{cl}</a>
<h1 class="h-xl">{t}</h1>
<span class="meta">{tm}</span>
<div class="source-box"><span>Reported by <strong>{pub}</strong>{lab}</span>
<a class="btn amber" href="{out}" data-out="{link}">Read the original article at {pub} ›</a></div>
{share}
{pic}
{body_text}
{comments}</article>
<aside>{strip}{rel}{ad}{signup}</aside></div></main>""".format(strip=market_strip(),
        sid=E(s["id"]), cu=cat_url(s["category"]), cl=E(cat_label(s["category"])), t=E(s["title"]), tm=time_tag(s),
        pub=pub, lab=label(s), out=out_url(s), link=E(s["link"]), pic=pic(s), body_text=body_text,
        comments=comments, ad=ad(True), signup=signup(), share=share_bar(s),
        rel=('<section><h2 class="sec-title">More %s</h2><ol class="ranked">%s</ol></section>' % (
            E(cat_label(s["category"])), "".join('<li><a href="%s">%s</a></li>' % (story_url(x), E(x["title"])) for x in related))) if related else "")
    desc = s["summary"] if has_summary(s) else "Reported by %s. Read the original article and more US and Canada trucking news on HaulTimes." % s["source"]
    extra = ('<meta property="article:published_time" content="%s">\n'
             '<meta property="og:site_name" content="%s">' % (E(s["published"]), E(CFG["site_name"])))
    if not has_summary(s):
        extra += '\n<meta name="robots" content="noindex, follow">'  # headline-only pages: useful for readers, too thin for Google
    write(story_url(s), head(s["title"], desc, story_url(s), img, extra=extra) + header(s["category"], stories) + body + footer())
    # The hop to the original article (counted as a page view, then straight on).
    write(out_url(s), """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex, nofollow">
<title>Opening {pub}</title><meta http-equiv="refresh" content="1;url={link}">{an}
<style>body{{font:16px system-ui,sans-serif;margin:0;display:grid;place-items:center;min-height:100vh;background:#fff;color:#111418}}a{{color:#9A5B00}}</style>
</head><body><p>Opening the original article at <strong>{pub}</strong>… <a href="{link}" rel="nofollow noopener">Continue</a></p>
<script>setTimeout(function(){{location.replace({js})}},600)</script></body></html>""".format(
        pub=pub, link=E(s["link"]), js=json.dumps(s["link"]), an=analytics_tag()))


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


def build_market(stories):
    # Fetch here so no workflow change is needed. fetch_market limits itself to one try every 6-12 hours
    # per source and keeps the last good data when a source fails.
    if not os.environ.get("HAULTIMES_NO_FETCH"):
        try:
            import fetch_market
            fetch_market.main()
        except Exception as e:  # never let market data break the news site
            print("Freight market fetch failed: %s" % e)
    market = load_json("market.json", {})
    write("/freight-market/", head("Freight Market: Lane Rates, Load Market and Diesel Prices",
                                   "Check a load offer against what carriers report on the same lane, see this week's load market by state and province, and current US and Canadian diesel prices.",
                                   "/freight-market/") + header("market", stories) + market_page.body(market, NOW, EASTERN) +
          footer(market_page.SCRIPT))


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
<p>{n} does not ask for your name or an account to read the site, and does not use advertising or tracking cookies.</p>
<p><strong>Visit counts.</strong> We count page views and where visitors came from (for example, Facebook) to see which pages are useful. No cookies are used and nothing is stored on your device. To count unique visitors, your internet address is turned into a scrambled code that changes every week and cannot be turned back into the address. The address itself is not stored.</p>
<p><strong>Rate reports and market answers.</strong> When you report a rate or answer the weekly market question on the Freight Market page, we store only what you enter (lane, equipment, rate, distance, date, or your answer) and the same weekly scrambled code, used to stop spam and to make sure one person can't tilt the results. We never ask for names, company names or contact details there. We publish only combined figures, never single reports.</p>
<p><strong>Location.</strong> For the weekly market question you choose your state or province yourself; it is remembered only on your device. Only the state or province is stored with an answer.</p>
<p>Messages sent through the contact form are used only to reply to you.</p>
<p>Questions: use our <a href="/contact/">contact form</a>. See also our <a href="/terms/">Terms of Use</a>.</p></main>""".format(n=E(CFG["site_name"]))
    write("/privacy/", head("Privacy", "HaulTimes privacy policy.", "/privacy/") + header("", stories) + privacy + footer())
    terms = """<main class="wrap prose"><h1>Terms of Use</h1>
<p class="note">Last updated {upd}.</p>
<p>By using {n} you agree to these terms.</p>
<h2>News</h2>
<p>Headlines link to the original publishers, who own their articles. Summaries are for information only and may contain errors; check the original source before acting on any story.</p>
<h2>Freight Market data</h2>
<p>Rates and market conditions on the Freight Market page come from anonymous reader reports and public government sources. Reader reports are not verified loads. Use them as a guide, not as a quote, offer or advice. {n} is not responsible for decisions made using them.</p>
<h2>What you submit</h2>
<p>When you report a rate or answer the weekly market question, you confirm the information is true to the best of your knowledge, and you give {n} a permanent, worldwide, royalty-free right to store, combine, analyse, publish and license that information, including in combined reports, data products and services offered by {n}. Do not include names of people or companies.</p>
<p>We may remove or exclude any report, for example one that looks false or appears to be an attempt to push rates up or down.</p>
<h2>Using our data</h2>
<p>You're welcome to quote individual figures from {n} in news articles, social media posts and conversations, with the credit "Source: HaulTimes" and a link to haultimes.com.</p>
<p>You may not, without our written permission: copy or download our data in bulk; use automated tools (scrapers, bots or scripts) to collect it; republish it as a data set, feed, rate tool or index; or use it to build or improve a competing product, rate service or load board. Contact us through the <a href="/contact/">contact form</a> about licensing.</p>
<h2>Fair use of the site</h2>
<p>Don't attempt to overload, probe or get around the limits and protections of the site. We may block traffic that does.</p>
<h2>No warranty</h2>
<p>The site is provided as is, without warranties of any kind. To the extent the law allows, {n} is not liable for any loss arising from use of the site or its data.</p>
<h2>Changes</h2>
<p>We may update these terms. The date above shows the latest version.</p></main>""".format(n=E(CFG["site_name"]), upd=E(CFG.get("terms_updated", "November 9, 2026")))
    write("/terms/", head("Terms of Use", "HaulTimes terms of use, including use of Freight Market data.", "/terms/") + header("", stories) + terms + footer())
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
        if s["importance"] >= min_score and hours_old(s) <= 72 and editorial.lead_eligible(s):
            by_day.setdefault(when(s).astimezone(EASTERN).date(), []).append(s)
    fb = []
    for day, items in by_day.items():
        fb += sorted(items, key=lambda x: x["importance"], reverse=True)[:per_day]
    rss(sorted(fb, key=when, reverse=True), "facebook.xml", CFG["site_name"], social=True)
    urls = ["/", "/border-wait-times/", "/freight-market/", "/about/", "/contact/", "/terms/"] + ["/topic/%s/" % v[1] for v in CATEGORIES.values()] + [story_url(s) for s in newest if has_page(s) and has_summary(s)]
    sm = '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">%s</urlset>' % "".join(
        "<url><loc>%s</loc></url>" % E(BASE + u) for u in urls)
    write("/sitemap.xml", sm)
    write("/robots.txt", "User-agent: *\nAllow: /\nDisallow: /editor/\nDisallow: /out/\nDisallow: /admin\nDisallow: /api/\nSitemap: %s/sitemap.xml\n" % BASE)


def build_editor(stored):
    """Private checklist for the site owner: every stored story, what the rules decided and why.
    Not linked anywhere, hidden from search engines."""
    names = {"ok": "On the site", "review": "Waiting for review", "duplicate": "Hidden duplicates", "rejected": "Rejected"}
    rows = []
    for st in ("ok", "review", "duplicate", "rejected"):
        group = sorted([s for s in stored if s.get("status", "ok") == st],
                       key=lambda s: editorial.rank_score(s, NOW), reverse=True)
        rows.append('<h2 class="sec-title" style="margin-top:28px">%s (%d)</h2>' % (names[st], len(group)))
        rows.append('<table class="waits" style="min-width:0"><thead><tr><th>Story id</th><th>Headline</th>'
                    '<th>Topic</th><th>Score</th><th>Why</th></tr></thead><tbody>')
        for s in group:
            rows.append('<tr><td><code>%s</code>%s</td><td><a href="%s">%s</a><br><span class="note">%s · %s</span></td>'
                        '<td>%s</td><td>%d</td><td class="note">%s</td></tr>' % (
                            E(s["id"]), " 📌" if s.get("pinned") else "", E(s.get("link", "")),
                            E(s.get("orig_title") or s["title"]), E(s.get("source", "")), E(s.get("published", "")[:16].replace("T", " ")),
                            E(cat_label(s.get("category", "other"))), s.get("importance", 0),
                            E("; ".join(s.get("reasons", [])) or s.get("kind", ""))))
        rows.append("</tbody></table>")
    page = (head("Editor", "Editor view", "/editor/", extra='<meta name="robots" content="noindex, nofollow">') +
            '<main class="wrap"><div class="page-head"><h1>Editor view</h1><p>Every story the robot found in the last few days, '
            'what it decided and why. To pin, hide or move a story, copy its id into <code>overrides.json</code> on GitHub.</p></div>' +
            '<div class="table-box" style="overflow-x:auto">%s</div></main>' % "".join(rows) + footer())
    write("/editor/", page)


def main():
    stored = load_json("news.json", [])
    if stored and "status" not in stored[0]:
        editorial.reprocess(stored, NOW)  # data saved by an older version of fetch_news.py
    stories = editorial.eligible(stored)  # homepage, topic pages, story pages and feeds all use this list
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
    build_market(stories)
    build_static_pages(stories)
    build_feeds(stories)
    build_editor(stored)
    print("Site built: %d stories, %d border crossings." % (len(stories), len((border or {}).get("crossings", []))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
