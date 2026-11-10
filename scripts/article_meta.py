"""
Find the publisher's own short description of an article (the text it publishes for
link previews: og:description / twitter:description / meta description).

Google News feeds only carry headlines, so the Google link is first turned into the
publisher's address. robots.txt is respected, only the page head is read, and nothing
is guessed: no description found -> None.
"""

import base64
import html
import json
import re
import urllib.parse
import urllib.request
import urllib.robotparser
from html.parser import HTMLParser

UA = "Mozilla/5.0 (compatible; HaulTimesBot/1.0; +https://haultimes.com/about/)"
BOT = "HaulTimesBot"
TIMEOUT = 15
MAX_BYTES = 400_000


def _get(url, data=None, headers=None):
    h = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.8"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.geturl(), r.read(MAX_BYTES).decode(r.headers.get_content_charset() or "utf-8", "replace")


# ------------------------------------------------------------------ Google News links

def _article_id(link):
    m = re.search(r"news\.google\.com/(?:rss/)?articles/([^?/#]+)", link or "")
    return m.group(1) if m else None


def _offline_decode(aid):
    """Older Google News ids carry the address inside them."""
    try:
        raw = base64.urlsafe_b64decode(aid + "=" * (-len(aid) % 4))
    except Exception:
        return None
    m = re.search(rb"https?://[\x21-\x7e]+", raw)
    if not m:
        return None
    url = m.group(0).decode("ascii", "ignore")
    return None if url.startswith("AU_yqL") else url.split("\xd2")[0]


def google_to_publisher(link, get=_get):
    """Publisher URL for a news.google.com article link, or the link itself if it isn't one."""
    aid = _article_id(link)
    if not aid:
        return link
    url = _offline_decode(aid)
    if url:
        return url
    # Newer ids: ask Google for the address, the same way its own page does.
    _, page = get("https://news.google.com/articles/%s" % aid)
    sig = re.search(r'data-n-a-sg="([^"]+)"', page)
    ts = re.search(r'data-n-a-ts="([^"]+)"', page)
    if not sig or not ts:
        return None
    inner = json.dumps(["garturlreq", [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1, None, None, None, None, None, 0, 1],
                                       "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0],
                        aid, int(ts.group(1)), sig.group(1)])
    body = "f.req=" + urllib.parse.quote(json.dumps([[["Fbv4je", inner, None, "generic"]]]))
    _, resp = get("https://news.google.com/_/DotsSplashUi/data/batchexecute",
                  data=body.encode(), headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"})
    for chunk in resp.split("\n"):
        if 'garturlres' in chunk:
            try:
                outer = json.loads(chunk)
                return json.loads(outer[0][2])[1]
            except Exception:
                m = re.search(r'garturlres\\",\\"(https?://[^\\"]+)', chunk)
                return m.group(1) if m else None
    return None


# ------------------------------------------------------------------ publisher page

class _Meta(HTMLParser):
    def __init__(self):
        super().__init__()
        self.found = {}

    def handle_starttag(self, tag, attrs):
        if tag != "meta":
            return
        a = {k.lower(): (v or "") for k, v in attrs}
        key = (a.get("property") or a.get("name") or "").lower()
        if key in ("og:description", "twitter:description", "description") and a.get("content"):
            self.found.setdefault(key, a["content"])


def _clean(text):
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    return re.sub(r"\s+", " ", text).strip()


def description_from_html(page):
    p = _Meta()
    try:
        p.feed(page)
    except Exception:
        pass
    for key in ("og:description", "twitter:description", "description"):
        d = _clean(p.found.get(key))
        if len(d) >= 60:
            return d[:600]
    return None


_robots = {}


def allowed(url, get=_get):
    parts = urllib.parse.urlsplit(url)
    root = "%s://%s" % (parts.scheme, parts.netloc)
    if root not in _robots:
        rp = urllib.robotparser.RobotFileParser()
        try:
            _, txt = get(root + "/robots.txt")
            rp.parse(txt.splitlines())
        except Exception:
            rp.parse([])  # no robots.txt reachable: nothing forbidden
        _robots[root] = rp
    return _robots[root].can_fetch(BOT, url)


def describe(link, get=_get):
    """(publisher_url, description or None, note). Raises only on network trouble worth retrying."""
    url = google_to_publisher(link, get)
    if not url:
        return None, None, "no publisher address"
    if not allowed(url, get):
        return url, None, "robots.txt disallows"
    final, page = get(url)
    d = description_from_html(page)
    return final or url, d, "ok" if d else "no description on page"
