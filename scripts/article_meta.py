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


GOOGLE_MAX_BYTES = 4_000_000  # Google's article page puts the address data late in a large page


def _get(url, data=None, headers=None):
    h = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.8"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    limit = GOOGLE_MAX_BYTES if "news.google.com" in url else MAX_BYTES
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.geturl(), r.read(limit).decode(r.headers.get_content_charset() or "utf-8", "replace")


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


LAST_STEP = {"note": ""}


def google_to_publisher(link, get=_get):
    """Publisher URL for a news.google.com article link, or the link itself if it isn't one.
    LAST_STEP["note"] says which step failed, for diagnostics."""
    aid = _article_id(link)
    if not aid:
        return link
    url = _offline_decode(aid)
    if url:
        return url
    # Newer ids: ask Google for the address, the same way its own page does.
    sig = ts = None
    for page_url in ("https://news.google.com/rss/articles/%s" % aid, "https://news.google.com/articles/%s" % aid):
        try:
            final, page = get(page_url)
        except Exception as e:
            LAST_STEP["note"] = "google page %s" % type(e).__name__
            continue
        sig = re.search(r'data-n-a-sg="([^"]+)"', page)
        ts = re.search(r'data-n-a-ts="([^"]+)"', page)
        if sig and ts:
            break
        LAST_STEP["note"] = "google page without signature (%s, %d bytes)" % (final[:40], len(page))
    if not sig or not ts:
        return None
    inner = json.dumps(["garturlreq", [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1, None, None, None, None, None, 0, 1],
                                       "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0],
                        aid, int(ts.group(1)), sig.group(1)])
    body = "f.req=" + urllib.parse.quote(json.dumps([[["Fbv4je", inner, None, "generic"]]]))
    try:
        _, resp = get("https://news.google.com/_/DotsSplashUi/data/batchexecute",
                      data=body.encode(), headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                                                   "Referer": "https://news.google.com/"})
    except Exception as e:
        LAST_STEP["note"] = "google decode request %s" % type(e).__name__
        return None
    for chunk in resp.split("\n"):
        if "garturlres" in chunk:
            try:
                outer = json.loads(chunk)
                return json.loads(outer[0][2])[1]
            except Exception:
                m = re.search(r'garturlres\\",\\"(https?://[^\\"]+)', chunk)
                if m:
                    return m.group(1)
    LAST_STEP["note"] = "google decode answer without address (%d bytes)" % len(resp)
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


class _Body(HTMLParser):
    """Paragraph text from the article (inside <article> or <main> when present). Skips nav, ads, comments."""
    SKIP = {"nav", "aside", "footer", "header", "script", "style", "noscript", "form", "figure", "button"}
    VOID = {"br", "img", "hr", "input", "meta", "link", "source", "wbr"}
    JUNK = re.compile(r"comment|related|newsletter|promo|advert|share|social|subscribe|recommend", re.I)

    def __init__(self):
        super().__init__()
        self.paras, self.cur, self.in_p, self.scope, self.scoped = [], [], 0, 0, False
        self.skip_tag, self.skip_depth = None, 0

    def handle_starttag(self, tag, attrs):
        if tag in self.VOID:
            return
        if self.skip_tag:
            if tag == self.skip_tag:
                self.skip_depth += 1
            return
        a = dict(attrs)
        if tag in self.SKIP or self.JUNK.search((a.get("class") or "") + " " + (a.get("id") or "")):
            self.skip_tag, self.skip_depth = tag, 1
            return
        if tag in ("article", "main"):
            if not self.scoped:
                self.paras = []
            self.scoped = True
            self.scope += 1
        if tag == "p":
            self.in_p, self.cur = 1, []

    def handle_endtag(self, tag):
        if self.skip_tag:
            if tag == self.skip_tag:
                self.skip_depth -= 1
                if not self.skip_depth:
                    self.skip_tag = None
            return
        if tag in ("article", "main") and self.scope:
            self.scope -= 1
        if tag == "p" and self.in_p:
            self.in_p = 0
            txt = _clean(" ".join(self.cur))
            if txt and (self.scope or not self.scoped) and len(txt.split()) >= 6:
                self.paras.append(txt)

    def handle_data(self, data):
        if self.in_p and not self.skip_tag:
            self.cur.append(data)


def jsonld_body(page):
    """Article text from the page's structured data (schema.org articleBody), which many news sites publish
    for search engines. Used only as source text for the summary; never republished."""
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', page, re.S | re.I):
        try:
            data = json.loads(block.strip())
        except ValueError:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            d = stack.pop()
            if isinstance(d, list):
                stack.extend(d)
            elif isinstance(d, dict):
                if d.get("isAccessibleForFree") in (False, "False", "false"):
                    return None  # the publisher marks it as paid content: excerpt only
                body = d.get("articleBody")
                if isinstance(body, str) and len(body.split()) >= 150:
                    return _clean(body)[:20000]
                stack.extend(v for v in d.values() if isinstance(v, (dict, list)))
    return None


def body_from_html(page):
    p = _Body()
    try:
        p.feed(page)
    except Exception:
        pass
    text = "\n\n".join(p.paras)
    return text if len(text.split()) >= 150 else None


def source_text(link, feed_snippet="", get=_get):
    """(publisher_url, text, scope, note). scope: full_article | excerpt | None (nothing usable)."""
    LAST_STEP["note"] = ""
    url = google_to_publisher(link, get)
    if not url:
        return None, None, None, "no publisher address: " + LAST_STEP["note"]
    if not allowed(url, get):
        return url, None, None, "robots.txt disallows"
    final, page = get(url)
    if re.search(r'paywall|subscriber-only|"isAccessibleForFree"\s*:\s*"?false', page, re.I):
        d = description_from_html(page)
        return final or url, d, ("excerpt" if d else None), "paywalled: excerpt only"
    body = jsonld_body(page) or body_from_html(page)
    if body:
        return final or url, body, "full_article", "ok"
    d = description_from_html(page) or (feed_snippet if len((feed_snippet or "").split()) >= 15 else None)
    return final or url, d, ("excerpt" if d else None), "excerpt only" if d else "no usable text"


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
