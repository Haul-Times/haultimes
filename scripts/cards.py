"""
Share images (1200x630) for Facebook/X link previews, drawn with Pillow in the site's own
fonts and colours. Four kinds: news headline, diesel, border delay, Freight Market promo.
Same input -> same bytes, so unchanged cards never show up as new commits.
"""

import hashlib
import html
import json
import os

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
W, H = 1200, 630
PAD = 72

INK = (17, 20, 24)
NAVY = (16, 24, 38)
MUTED = (74, 82, 96)
RULE = (213, 217, 222)
AMBER = (255, 184, 0)
AMBER_INK = (154, 91, 0)
PAPER = (255, 255, 255)
WASH = (245, 246, 247)
GREEN = (30, 107, 69)
RED = (196, 38, 46)

_fonts = {}


def font(kind, size, weight=None, width=None):
    key = (kind, size, weight, width)
    if key not in _fonts:
        if kind == "serif":
            f = ImageFont.truetype(os.path.join(ASSETS, "fonts", "PlayfairDisplay.ttf"), size)
            f.set_variation_by_axes([weight or 900])
        else:
            f = ImageFont.truetype(os.path.join(ASSETS, "fonts", "Archivo.ttf"), size)
            f.set_variation_by_axes([weight or 700, width or 100])
        _fonts[key] = f
    return _fonts[key]


def _logo(color="navy", height=46):
    img = Image.open(os.path.join(ASSETS, "logo-%s.png" % color)).convert("RGBA")
    w = round(img.width * height / img.height)
    return img.resize((w, height), Image.LANCZOS)


def _wrap(draw, text, f, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=f) <= max_w or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _fit(draw, text, kind, sizes, max_w, max_lines, **kw):
    """Largest size at which the text fits in max_lines; the last resort shortens with an ellipsis."""
    for size in sizes:
        f = font(kind, size, **kw)
        lines = _wrap(draw, text, f, max_w)
        if len(lines) <= max_lines:
            return f, lines
    f = font(kind, sizes[-1], **kw)
    lines = _wrap(draw, text, f, max_w)[:max_lines]
    while lines and draw.textlength(lines[-1] + "…", font=f) > max_w:
        lines[-1] = lines[-1].rsplit(" ", 1)[0]
    lines[-1] = lines[-1].rstrip(",;:—–-") + "…"
    return f, lines


def _spaced(draw, xy, text, f, fill, spacing=2.5):
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=f, fill=fill)
        x += draw.textlength(ch, font=f) + spacing
    return x


def _frame(kicker, footer_left):
    """White card: logo top-left, amber kicker top-right, navy footer band."""
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    logo = _logo("navy", 44)
    img.paste(logo, (PAD, 54), logo)
    kf = font("sans", 22, 800, 100)
    kw = sum(d.textlength(c, font=kf) + 2.5 for c in kicker.upper()) - 2.5
    kx = W - PAD - kw
    d.rectangle([kx - 18, 52, W - PAD + 18, 52 + 46], fill=AMBER)
    _spaced(d, (kx, 63), kicker.upper(), kf, NAVY)
    d.line([PAD, 128, W - PAD, 128], fill=RULE, width=2)
    d.rectangle([0, H - 64, W, H], fill=NAVY)
    d.rectangle([0, H - 68, W, H - 64], fill=AMBER)
    ff = font("sans", 22, 600, 100)
    d.text((PAD, H - 44), footer_left, font=ff, fill=(220, 224, 230))
    site = "haultimes.com"
    d.text((W - PAD - d.textlength(site, font=font("sans", 22, 800)), H - 44), site, font=font("sans", 22, 800), fill=AMBER)
    return img, d


def news_card(spec):
    img, d = _frame(spec.get("kicker") or "Trucking news", "Reported by %s" % spec.get("source", ""))
    f, lines = _fit(d, spec["headline"], "serif", (70, 64, 58, 52, 46), W - 2 * PAD, 4, weight=900)
    lh = round(f.size * 1.16)
    top = 128 + (H - 68 - 128 - lh * len(lines)) // 2 - 6
    for i, line in enumerate(lines):
        d.text((PAD, top + i * lh), line, font=f, fill=INK)
    return img


def _arrow(d, x, y, size, up, fill):
    if up:
        d.polygon([(x, y + size), (x + size, y + size), (x + size / 2, y)], fill=fill)
    else:
        d.polygon([(x, y), (x + size, y), (x + size / 2, y + size)], fill=fill)


def stat_card(spec):
    """Big number + label, a change badge (dir up/down), and up to three detail lines."""
    img, d = _frame(spec.get("kicker", ""), spec.get("footer", ""))
    badge_w = 0
    cf = font("sans", 40, 800, 100)
    if spec.get("change"):
        badge_w = 34 + 26 + 12 + d.textlength(spec["change"], font=cf) + 34
    big = None
    for size in (164, 150, 136, 120, 104):
        big = font("sans", size, 900, 100)
        if d.textlength(spec["big"], font=big) + badge_w <= W - 2 * PAD:
            break
    y = 150
    asc = big.getbbox(spec["big"])
    d.text((PAD - 4, y), spec["big"], font=big, fill=INK)
    bx = PAD + d.textlength(spec["big"], font=big) + 34
    if spec.get("change"):
        up = spec.get("dir") == "up"
        col = RED if (up ^ bool(spec.get("up_is_good"))) else GREEN
        cy = y + asc[3] - 64
        cw = d.textlength(spec["change"], font=cf)
        d.rounded_rectangle([bx, cy, bx + cw + 26 + 12 + 36, cy + 64], radius=10, fill=col)
        _arrow(d, bx + 18, cy + 20, 24, up, PAPER)
        d.text((bx + 18 + 26 + 12, cy + 8), spec["change"], font=cf, fill=PAPER)
    if spec.get("label"):
        lf, ll = _fit(d, spec["label"], "sans", (34, 30, 28), W - 2 * PAD, 2, weight=600)
        for i, line in enumerate(ll):
            d.text((PAD, y + asc[3] + 22 + i * 42), line, font=lf, fill=MUTED)
    details = spec.get("details") or []
    if details:
        ty = 462
        d.line([PAD, ty - 20, W - PAD, ty - 20], fill=RULE, width=2)
        df = font("sans", 27, 600, 100)
        dfb = font("sans", 27, 800, 100)
        x = PAD
        for i, (k, v) in enumerate(details[:3]):
            if i:
                x += 40
            d.text((x, ty), k, font=df, fill=MUTED)
            x += d.textlength(k, font=df) + 10
            d.text((x, ty), v, font=dfb, fill=INK)
            x += d.textlength(v, font=dfb)
    return img


def promo_card(spec):
    img, d = _frame(spec.get("kicker", "Freight Market"), spec.get("footer", "Free · anonymous · US & Canada"))
    f, lines = _fit(d, spec["headline"], "serif", (92, 84, 76, 68, 60), W - 2 * PAD, 2, weight=900)
    lh = round(f.size * 1.14)
    sf, sl = _fit(d, spec.get("sub", ""), "sans", (32, 29, 26), W - 2 * PAD, 2, weight=500)
    block = lh * len(lines) + 22 + 42 * len(sl) + (90 if spec.get("chips") else 0)
    y = 128 + (H - 68 - 128 - block) // 2 - 10
    for i, line in enumerate(lines):
        d.text((PAD, y + i * lh), line, font=f, fill=INK)
    y += lh * len(lines) + 22
    for i, line in enumerate(sl):
        d.text((PAD, y + i * 42), line, font=sf, fill=MUTED)
    chips = spec.get("chips") or []
    cf = font("sans", 25, 700, 100)
    x, cy = PAD, y + 42 * len(sl) + 40
    for c in chips:
        cw = d.textlength(c, font=cf)
        d.rounded_rectangle([x, cy, x + cw + 36, cy + 50], radius=25, fill=WASH, outline=RULE, width=2)
        d.text((x + 18, cy + 11), c, font=cf, fill=NAVY)
        x += cw + 36 + 14
    return img


DRAW = {"news": news_card, "stat": stat_card, "promo": promo_card}


def render(spec):
    return DRAW[spec["type"]](spec)


def card_name(spec):
    return hashlib.sha1(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:10]


def save(img, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.quantize(32, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE).save(path, "PNG", optimize=True)  # ~20 KB, text stays sharp


def write_card(site_dir, rel_dir, spec):
    """Write the card once per distinct content; returns its site-relative path."""
    rel = "%s/%s.png" % (rel_dir.strip("/"), card_name(spec))
    path = os.path.join(site_dir, rel)
    if not os.path.exists(path):
        save(render(spec), path)
    return "/" + rel


def share_page(base, hid, entry, image_path):
    """A tiny page whose only job is to give Facebook the right title/description/image,
    then send people on to the real page."""
    E = lambda s: html.escape(s or "", quote=True)
    target = entry["target"]
    path, frag = (target.split("#", 1) + [""])[:2]
    return """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{t}</title><meta name="robots" content="noindex, follow">
<link rel="canonical" href="{b}{p}">
<meta property="og:type" content="website"><meta property="og:site_name" content="HaulTimes">
<meta property="og:title" content="{t}"><meta property="og:description" content="{d}">
<meta property="og:url" content="{b}/s/{h}/">
<meta property="og:image" content="{b}{img}"><meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<script>location.replace({pj} + location.search + {fj});</script>
</head><body style="font-family:system-ui,sans-serif;padding:24px">
<p><a href="{p}{fh}">Continue to HaulTimes ›</a></p></body></html>""".format(
        t=E(entry["title"]), d=E(entry.get("desc")), b=base, h=E(hid), img=image_path, p=E(path),
        fh=E("#" + frag if frag else ""), pj=json.dumps(path), fj=json.dumps("#" + frag if frag else ""))


def write_share(site_dir, base, hid, entry):
    img = write_card(site_dir, "s/%s" % hid, entry["card"])
    out = os.path.join(site_dir, "s", hid, "index.html")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(share_page(base, hid, entry, img))
    return "/s/%s/" % hid
