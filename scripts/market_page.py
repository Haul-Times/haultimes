"""Builds haultimes.com/freight-market/ from data/market.json (written by fetch_market.py).

Rules this page follows:
  * Only data whose terms allow republishing is shown. Everything else is a plain outbound link.
  * Every indicator states its source, equipment, coverage, period, retrieval time, meaning and limits.
  * No numbers are invented: a missing source shows "No data", never an estimate.
  * USDA covers refrigerated produce loads only, so it is labelled that way everywhere.
"""

import html
import re
import json
import os
from datetime import datetime, timezone

E = html.escape
HERE = os.path.dirname(os.path.abspath(__file__))
STALE_DAYS = 14
CODES = {"AL","AZ","AR","CA","CO","CT","DE","FL","GA","ID","IL","IN","IA","KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ","NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT","VA","WA","WV","WI","WY"} - {"IN", "OR", "ME"}

LEVELS = {  # USDA availability scale -> label, colour, plain meaning
    1: ("Surplus", "#2F6690", "Many trucks waiting for loads"),
    2: ("Slight surplus", "#8FB8D6", "More trucks than loads"),
    3: ("Adequate", "#E6DFC8", "Trucks and loads roughly balanced"),
    4: ("Slight shortage", "#F0A04B", "Shippers having some trouble finding trucks"),
    5: ("Shortage", "#C4262E", "Shippers struggling to find trucks"),
}
NO_DATA = "#F1F2F4"

FTR_URL = "https://truckstop.com/blog/freight-market-heat-map/"
DAT_URL = "https://www.dat.com/trendlines"
USDA_DOCS = "https://www.ams.usda.gov/market-news/fruits-vegetables"


def _dt(s):
    return datetime.fromisoformat(s) if s else None


def _fmt_time(s, tz):
    d = _dt(s)
    return d.astimezone(tz).strftime("%b %-d, %Y, %-I:%M %p ET") if d else "never"


def _fmt_day(s):
    try:
        return datetime.fromisoformat(s[:10]).strftime("%B %-d, %Y")
    except (TypeError, ValueError):
        return "unknown"


def tidy(name):
    """Title-case a USDA district name but keep state codes upper-case (CA, not Ca)."""
    words = name.title().split(" ")
    return " ".join(w.upper() if len(w.strip(",")) == 2 and w.strip(",").upper() in CODES else w for w in words)


def _money(v):
    return "$%s" % format(int(round(v)), ",") if v else "—"


def is_stale(period_end, now, days=STALE_DAYS):
    if not period_end:
        return True
    d = datetime.fromisoformat(period_end[:10]).replace(tzinfo=timezone.utc)
    return (now - d).days > days


def status_line(store, period_end, now, tz):
    """'Last retrieved …' plus warnings for stale data or a failed update."""
    bits = ['<span>Last retrieved %s</span>' % E(_fmt_time(store.get("retrieved_at"), tz))]
    if store.get("retrieved_at") and is_stale(period_end, now):
        bits.append('<span class="mk-badge stale">Stale: newest data is more than %d days old</span>' % STALE_DAYS)
    if store.get("last_error") and store.get("retrieved_at"):
        bits.append('<span class="mk-badge warn">Latest update attempt failed %s; showing the last good data</span>'
                    % E(_fmt_time(store.get("last_attempt_at"), tz)))
    return '<p class="mk-status">%s</p>' % " ".join(bits)


def meta_box(rows):
    return '<dl class="mk-meta">%s</dl>' % "".join("<div><dt>%s</dt><dd>%s</dd></div>" % (E(k), v) for k, v in rows)


REGION_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado", "CT": "Connecticut",
    "DE": "Delaware", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan",
    "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire",
    "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee",
    "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin",
    "WY": "Wyoming",
}
PROVINCE_NAMES = {"AB": "Alberta", "BC": "British Columbia", "MB": "Manitoba", "NB": "New Brunswick", "NL": "Newfoundland and Labrador",
                  "NS": "Nova Scotia", "NT": "Northwest Territories", "NU": "Nunavut", "ON": "Ontario", "PE": "Prince Edward Island",
                  "QC": "Quebec", "SK": "Saskatchewan", "YT": "Yukon"}
# Squares laid out roughly where each place is: (code, row, column)
TILES_CA = [("YT", 0, 1), ("NT", 0, 2), ("NU", 0, 3), ("NL", 0, 10), ("BC", 1, 1), ("AB", 1, 2), ("SK", 1, 3), ("MB", 1, 4),
            ("ON", 1, 6), ("QC", 1, 8), ("NB", 1, 9), ("PE", 1, 10), ("NS", 1, 11)]
TILES_US = [("AK", 0, 0), ("ME", 0, 10), ("VT", 1, 9), ("NH", 1, 10), ("WA", 2, 0), ("ID", 2, 1), ("MT", 2, 2), ("ND", 2, 3),
            ("MN", 2, 4), ("IL", 2, 5), ("WI", 2, 6), ("MI", 2, 7), ("NY", 2, 8), ("RI", 2, 9), ("MA", 2, 10), ("OR", 3, 0),
            ("NV", 3, 1), ("WY", 3, 2), ("SD", 3, 3), ("IA", 3, 4), ("IN", 3, 5), ("OH", 3, 6), ("PA", 3, 7), ("NJ", 3, 8),
            ("CT", 3, 9), ("CA", 4, 0), ("UT", 4, 1), ("CO", 4, 2), ("NE", 4, 3), ("MO", 4, 4), ("KY", 4, 5), ("WV", 4, 6),
            ("VA", 4, 7), ("MD", 4, 8), ("DE", 4, 9), ("AZ", 5, 1), ("NM", 5, 2), ("KS", 5, 3), ("AR", 5, 4), ("TN", 5, 5),
            ("NC", 5, 6), ("SC", 5, 7), ("OK", 6, 3), ("LA", 6, 4), ("MS", 6, 5), ("AL", 6, 6), ("GA", 6, 7), ("HI", 7, 0),
            ("TX", 7, 3), ("FL", 7, 8)]
S, G = 46, 4


def tile_map(colours, tips, idp, label, canada=True, price_labels=None):
    """Square map. colours/tips: code -> fill / tooltip. Squares without a colour are light grey."""
    def tiles(lst, oy):
        out = []
        for code, r, c in lst:
            x, y = c * (S + G), (r + oy) * (S + G)
            fill = colours.get(code, NO_DATA)
            dark = fill in ("#2F6690", "#C4262E")
            dark = dark or fill in ("#D9861C", "#A85A0A")
            pl = (price_labels or {}).get(code)
            if pl:
                txt = '<text x="%d" y="%d"%s>%s</text><text class="pl" x="%d" y="%d"%s>%s</text>' % (
                    x + S // 2, y + 17, ' fill="#fff"' if dark else "", code, x + S // 2, y + 33, ' fill="#fff"' if dark else "", E(pl))
            else:
                txt = '<text x="%d" y="%d"%s>%s</text>' % (x + S // 2, y + S // 2 + 1, ' fill="#fff"' if dark else "", code)
            out.append('<g id="%s%s"><rect x="%d" y="%d" width="%d" height="%d" rx="3" fill="%s"/>%s'
                       '<title>%s</title></g>' % (idp, code, x, y, S, S, fill, txt, E(tips.get(code, ""))))
        return "".join(out)
    oy = 2.6 if canada else 0
    w, h = 12 * (S + G), int((8 + oy) * (S + G))
    top = ""
    if canada:
        top = ('<text class="ct" x="0" y="-8">CANADA</text>%s<line x1="0" x2="%d" y1="%d" y2="%d" stroke="#101826" stroke-dasharray="3 4"/>'
               '<text class="ct" x="0" y="%d">UNITED STATES</text>') % (tiles(TILES_CA, 0), w - G, 2.3 * (S + G) - G, 2.3 * (S + G) - G, 2.3 * (S + G) + 10)
    return '<svg class="tm" viewBox="-2 %d %d %d" role="img" aria-label="%s">%s%s</svg>' % (
        -22 if canada else -2, w, h + (22 if canada else 2), E(label), top, tiles(TILES_US, oy))


def state_levels(origins):
    """State code -> (highest availability level, [district names]). Mexico-only districts are not US states."""
    out = {}
    for o in origins:
        if o.get("availability") is None:
            continue
        for st in o.get("states", []):
            lvl, names = out.get(st, (0, []))
            out[st] = (max(lvl, o["availability"]), names + [tidy(o["origin"])])
    return out


def map_svg(origins):
    levels = state_levels(origins)
    colours = {c: LEVELS[l][1] for c, (l, _) in levels.items()}
    tips = {c: "%s: %s (%s)" % (REGION_NAMES.get(c, c), LEVELS[l][0], "; ".join(sorted(set(n)))) for c, (l, n) in levels.items()}
    summary = ", ".join("%s %s" % (c, LEVELS[l][0].lower()) for c, (l, _) in sorted(levels.items())) or "no states reported"
    return tile_map(colours, tips, "u-", "USDA reefer truck availability by state: %s. Full details are in the table." % summary, canada=False)


def legend():
    items = "".join('<li><i style="background:%s"></i><b>%s</b> <span>%s</span></li>' % (c, E(n), E(d))
                    for n, c, d in LEVELS.values())
    return ('<ul class="mk-legend" aria-label="Map legend">%s<li><i style="background:%s;border:1px solid #C9CED4"></i>'
            '<b>No report</b> <span>USDA did not report a shipping district in this state this week</span></li></ul>') % (items, NO_DATA)


def change(prev, now_lvl):
    if prev is None or now_lvl is None:
        return '<span class="note">—</span>'
    d = now_lvl - prev
    if d == 0:
        return '<span class="note">No change</span>'
    word = "Tighter" if d > 0 else "Looser"
    return '<span class="mk-chg %s">%s %s (was %s)</span>' % ("up" if d > 0 else "down", "▲" if d > 0 else "▼", word, E(LEVELS[prev][0].lower()))


def reefer_section(u, now, tz):
    origins = u.get("origins") or []
    if not origins:
        return ('<section class="mk-sec" aria-labelledby="reefer-h"><h2 id="reefer-h" class="sec-title">Produce reefer trucks · USDA</h2>'
                '<p class="mk-empty">No data yet. The first USDA report will appear here after the next update.</p>%s</section>') % (
            status_line(u, u.get("week_ending"), now, tz) if u.get("last_attempt_at") else "")
    week = u["week_ending"]
    hist = u.get("history", {})
    prev_week = max(hist) if hist else None
    prev = hist.get(prev_week, {})
    dests = sorted({r["destination"] for o in origins for r in o["rates"]})
    tight = [o for o in origins if (o.get("availability") or 0) >= 4]
    loose = [o for o in origins if o.get("availability") in (1, 2)]
    mexico = [o for o in origins if o.get("mexico")]
    unmapped = [o for o in origins if not o.get("states") and not o.get("mexico")]

    rows = []
    for o in origins:
        lvl = o.get("availability")
        p = prev.get("%s|%s" % (o["origin"], o["commodity"]), {}).get("availability")
        badge = ('<span class="mk-lvl" style="--c:%s">%s</span>' % (LEVELS[lvl][1], E(LEVELS[lvl][0]))) if lvl else '<span class="note">Not reported</span>'
        rates = "".join(
            '<li data-dest="%s"><b>%s</b> %s <span class="note">(%s–%s%s)</span></li>' % (
                E(r["destination"]), E(r["destination"]), _money(r.get("mid")), _money(r.get("low")), _money(r.get("high")),
                (", ≈ $%.2f/mi" % r["rpm"]) if r.get("rpm") else "")
            for r in sorted(o["rates"], key=lambda r: r["destination"]))
        where = ", ".join(o.get("states", [])) or ("Mexico crossing" if o.get("mexico") else "Not mapped")
        if o.get("mexico") and o.get("states"):
            where += " + Mexico crossings"
        rows.append('<tr data-dests="%s"><td><span class="n">%s</span><div class="p">%s</div></td><td data-l="Produce">%s</td><td data-l="Trucks">%s</td>'
                    '<td data-l="vs. prior week">%s</td><td data-l="Spot rate per load"><ul class="mk-rates">%s</ul>%s</td></tr>' % (
                        E("|".join(r["destination"] for r in o["rates"])), E(tidy(o["origin"])), E(where),
                        E(o["commodity"].title() or "—"), badge, change(p, lvl), rates,
                        "" if rates else '<span class="note">No rates reported</span>'))

    opts = "".join('<option value="%s">%s</option>' % (E(d), E(d)) for d in dests)
    stats = ('<div class="stats"><div><span class="k">Week ending</span><span class="v">%s</span><span class="note">USDA weekly report</span></div>'
             '<div><span class="k">Shipping districts</span><span class="v">%d</span><span class="note">reporting reefer availability</span></div>'
             '<div><span class="k">Tight (shortage)</span><span class="v">%d</span><span class="note">districts short of trucks</span></div>'
             '<div><span class="k">Loose (surplus)</span><span class="v">%d</span><span class="note">districts with extra trucks</span></div></div>') % (
        E(_fmt_day(week)), len(origins), len(tight), len(loose))

    xb = ""
    if mexico:
        xb = '<p class="mk-xb"><strong>Cross-border, Mexico → US:</strong> %s.</p>' % "; ".join(
            "%s: %s" % (E(tidy(o["origin"])), E(LEVELS[o["availability"]][0].lower()) if o.get("availability") else "not reported") for o in mexico)
    um = ""
    if unmapped:
        um = '<p class="note">Not shown on the map because the district name does not identify a state: %s.</p>' % E(
            "; ".join(tidy(o["origin"]) for o in unmapped))

    meta = meta_box([
        ("Source", 'USDA Agricultural Marketing Service, Specialty Crops Market News, published on '
                   '<a href="%s" rel="noopener" target="_blank">USDA AgTransport</a> ("Refrigerated Truck Rates and Availability"). '
                   'Credit: USDA AMS Specialty Crops Market News.' % E(u.get("source_url") or "https://agtransport.usda.gov/d/acar-e3r8")),
        ("Equipment", "Refrigerated (reefer) trucks, 48–53 ft, hauling fresh fruit and vegetables. <strong>Not dry van, flatbed or general freight.</strong>"),
        ("Coverage", "US produce shipping districts and Mexican produce crossing into the US. <strong>No Canadian origins.</strong> "
                     "Outbound from each district only; inbound demand is not measured."),
        ("Reporting period", "Week ending %s (weekly; USDA updates once a week)." % E(_fmt_day(week))),
        ("Last retrieved", E(_fmt_time(u.get("retrieved_at"), tz))),
        ("What it means", "USDA market reporters rate truck availability at each district on a 5-step scale from surplus to shortage, "
                          "based on talks with shippers and brokers. A state is coloured by its tightest district."),
        ("Limitations", "A judgement by reporters, not a count of trucks or loads. Seasonal: districts appear only while they are shipping, "
                        "so a blank state means no report, not no trucks. Says nothing about freight other than produce."),
        ("Rates", "Open (spot) market rates reported by shippers and brokers, <strong>US dollars per load</strong>, including broker fees. "
                  "USDA does not say whether a fuel surcharge is included. Midpoint shown with the week's low–high range. "
                  "Per-mile figures are our arithmetic: midpoint ÷ USDA's listed distance."),
    ])

    return """<section class="mk-sec" aria-labelledby="reefer-h">
<h2 id="reefer-h" class="sec-title">Produce reefer trucks · USDA, week ending {week}</h2>
<p class="mk-lede">Official USDA report: is it hard for produce shippers to find a reefer this week? US shipping districts only.</p>
{status}
<div class="mk-mapbox"><div class="mk-mapwrap">{svg}</div>
<aside class="mk-side">{legend}
<p class="mk-hot"><strong>Red means trucks are short</strong> for produce loads leaving that area, so rates there tend to rise. It doesn't promise a load or cover other freight.</p>
<p class="note">Canada: no data in this report (USDA covers US districts and Mexico crossings only).</p>
</aside></div>
{xb}{um}
<details class="mk-more"><summary>All {n} districts with USDA rates</summary>
<div class="mk-tools"><label for="mk-dest">Show rates to</label>
<select id="mk-dest"><option value="">All destinations</option>{opts}</select></div>
<div class="table-box mk-table"><table class="waits"><caption class="sr">Reefer truck availability and spot rates by USDA shipping district, week ending {week}</caption>
<thead><tr><th scope="col">Shipping district</th><th scope="col">Produce</th><th scope="col">Trucks</th><th scope="col">vs. prior week</th>
<th scope="col">Spot rate per load (USD)</th></tr></thead><tbody id="mk-body">{rows}</tbody></table></div>
</details>
<details class="mk-about"><summary>About this data</summary>{meta}</details>
</section>""".format(status=status_line(u, week, now, tz), svg=map_svg(origins), legend=legend(), xb=xb, um=um, n=len(origins),
                     opts=opts, week=E(_fmt_day(week)), rows="".join(rows), meta=meta)


def spark(points):
    vals = [v for _, v in points]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1
    pts = " ".join("%.1f,%.1f" % (i * 160 / (len(vals) - 1), 36 - (v - lo) / span * 32) for i, v in enumerate(vals))
    x, y = pts.split()[-1].split(",")
    return ('<svg class="sp" viewBox="0 0 160 40" aria-hidden="true"><polyline points="%s" fill="none" stroke="#101826" stroke-width="2"/>'
            '<circle cx="%s" cy="%s" r="3" fill="#101826"/></svg>') % (pts, x, y)


def _month(p):
    try:
        return datetime.strptime(p[:7], "%Y-%m").strftime("%b %Y")
    except (TypeError, ValueError):
        return p or ""


def gov_card(title, desc, st, fmt, source, now, tz, period_fmt=_month, stale_days=100):
    """One official indicator: value, change, 12-month line, period, source. 'No data' when missing."""
    if st.get("value") is None:
        why = "No data yet." if not st.get("last_error") else "No data: the source could not be reached on the last try."
        return ('<div class="gc"><span class="k">%s</span><span class="d">%s</span><span class="mk-nodata">%s</span>'
                '<span class="src">%s</span></div>') % (E(title), E(desc), why, source)
    v, prev = st["value"], st.get("prev")
    chg = ""
    if prev:
        pct = (v - prev) / prev * 100
        pts = st.get("points") or []
        prev_period = st.get("prev_period") or (pts[-2][0] if len(pts) > 1 else "")
        chg = '<span class="chg %s">%s %.1f%% from %s</span>' % (
            "up" if pct > 0 else "down" if pct < 0 else "", "▲" if pct > 0 else "▼" if pct < 0 else "–", abs(pct),
            E(period_fmt(prev_period)) if prev_period else "the previous report")
    badge = ""
    if st.get("last_error"):
        badge = ' <span class="mk-badge warn">update failed, showing last good data</span>'
    elif st.get("period") and is_stale(st["period"] + ("-01" if len(st["period"]) == 7 else ""), now, stale_days):
        badge = ' <span class="mk-badge stale">stale</span>'
    return ('<div class="gc"><span class="k">%s</span><span class="d">%s</span><div class="row2"><span class="v">%s</span>%s</div>%s'
            '<span class="src">%s · %s · retrieved %s%s</span></div>') % (
        E(title), E(desc), E(fmt(v)), spark(st.get("points", [])), chg, source, E(period_fmt(st.get("period", ""))),
        E(_fmt_time(st.get("retrieved_at"), tz)), badge)


def gov_section(market, now, tz):
    a = lambda url, name: '<a href="%s" rel="noopener" target="_blank">%s</a>' % (E(url), E(name))
    cards = [
        gov_card("US truckload prices", "Dry van and general freight, long distance. Price index, monthly.",
                 market.get("bls_truckload", {}), lambda v: "%.1f" % v, a("https://fred.stlouisfed.org/series/PCU484121484121", "US BLS"), now, tz),
        gov_card("US specialized trucking prices", "Flatbed, step deck, heavy haul and other specialized freight. Price index, monthly.",
                 market.get("bls_specialized", {}), lambda v: "%.1f" % v, a("https://fred.stlouisfed.org/series/PCU484230484230", "US BLS"), now, tz),
        gov_card("Canada trucking prices", "For-hire trucking price index, Canada. Monthly.",
                 market.get("statcan_trucking", {}), lambda v: "%.1f" % v, a("https://doi.org/10.25318/1810028101-eng", "Statistics Canada"), now, tz,
                 stale_days=200),  # published with a lag of about four months
        gov_card("Trucks entering the US from Canada", "All US–Canada crossings, monthly count.",
                 market.get("bts_trucks_canada", {}), lambda v: format(int(v), ","), a("https://www.bts.gov/browse-statistical-products-and-data/border-crossing-data/border-crossingentry-data", "US BTS"), now, tz),
    ]
    return """<section class="mk-sec" aria-labelledby="gov-h"><h2 id="gov-h" class="sec-title">Official numbers · government data</h2>
<div class="gov">{cards}</div>
<p class="note">Price indexes show which way trucking prices are moving, not the rate on any load. Each change compares the latest report with the one before it (the month or week named). US figures are US-only, Canadian figures Canada-only.</p></section>""".format(cards="".join(cards))


FUEL_SCALE = ["#FBEFD5", "#F6D58E", "#EFB23F", "#D9861C", "#A85A0A"]   # cheaper -> pricier


def _buckets(values):
    """Five equal steps between the lowest and highest price in one country."""
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1
    return lambda v: FUEL_SCALE[min(4, int((v - lo) / span * 5))]


def _change(cur, prev, fmt):
    if prev is None:
        return '<span class="note">—</span>'
    d = cur - prev
    if abs(d) < 1e-9:
        return '<span class="note">no change</span>'
    return '<span class="mk-chg %s">%s %s</span>' % ("up" if d > 0 else "down", "▲" if d > 0 else "▼", fmt(abs(d)))


def diesel_section(market, now, tz):
    """Our own diesel map: US by EIA region (weekly, US$/gal) and Canada by province (monthly, ¢/L)."""
    from fetch_market import EIA_STATE_REGION, EIA_REGIONS
    e, c, o = market.get("eia_diesel", {}), market.get("statcan_diesel", {}), market.get("ontario_diesel", {})
    us = e.get("prices") or {}
    ca = {p: v["avg"] for p, v in (c.get("provinces") or {}).items()}
    if not us and not ca:
        return ('<section class="mk-sec" aria-labelledby="fuel-h"><h2 id="fuel-h" class="sec-title">Diesel prices</h2>'
                '<p class="mk-empty">No data yet. The diesel map appears after the next update.</p></section>')
    names = {k: label for k, label, _ in EIA_REGIONS}
    colours, tips, labels = {}, {}, {}
    if us:
        col = _buckets([v for k, v in us.items() if k in EIA_STATE_REGION.values()] or list(us.values()))
        for st, reg in EIA_STATE_REGION.items():
            if reg in us:
                colours[st] = col(us[reg])
                tips[st] = "%s: $%.3f/gal (%s region, week of %s)" % (REGION_NAMES.get(st, st), us[reg], names[reg], _fmt_day(e.get("week")))
                labels[st] = "$%.2f" % us[reg]
    if ca:
        colc = _buckets(list(ca.values()))
        for p, v in ca.items():
            colours[p] = colc(v)
            cities = ", ".join("%s %.1f¢" % (k, x) for k, x in sorted(c["provinces"][p]["cities"].items()))
            tips[p] = "%s: %.1f¢/L (%s; %s)" % (PROVINCE_NAMES.get(p, p), v, _month(c.get("month")), cities)
            labels[p] = "%.0f¢" % v
    svg = tile_map(colours, tips, "f-", "Diesel prices by state and province. Details are in the tables below.", price_labels=labels)

    us_rows = "".join('<tr><td>%s</td><td><b>$%.3f</b></td><td>%s</td></tr>' % (
        ("&nbsp;&nbsp;" if k in ("1A", "1B", "1C", "5XCA", "CA") else "") + E(names[k]), us[k], _change(us[k], (e.get("prev_prices") or {}).get(k), lambda d: "$%.3f" % d))
        for k in ("US", "1", "1A", "1B", "1C", "2", "3", "4", "5", "5XCA", "CA") if k in us)
    ca_rows = "".join('<tr><td>%s <span class="src-in">%s</span></td><td><b>%.1f¢</b></td><td>%s</td></tr>' % (
        E(PROVINCE_NAMES.get(p, p)), E(", ".join(sorted(c["provinces"][p]["cities"]))), ca[p],
        _change(ca[p], ((c.get("prev_provinces") or {}).get(p) or {}).get("avg"), lambda d: "%.1f¢" % d))
        for p in sorted(ca, key=lambda p: PROVINCE_NAMES.get(p, p)))
    on = ""
    if o.get("prices"):
        prev = o.get("prev_prices") or {}
        on_rows = "".join('<tr><td>%s</td><td><b>%.1f¢</b></td><td>%s</td></tr>' % (
            E(k.split("/")[0]), v, _change(v, prev.get(k), lambda d: "%.1f¢" % d)) for k, v in sorted(o["prices"].items()))
        on = ('<details class="mk-more"><summary>Ontario cities, weekly · %s (vs %s)</summary><div class="table-box">'
              '<table class="waits mk-small"><thead><tr><th>Market</th><th>¢/L</th><th>Change</th></tr></thead><tbody>%s</tbody></table></div>'
              '<p class="note">Source: Ontario Ministry of Energy fuel price survey, Open Government Licence – Ontario.</p></details>') % (
            E(_fmt_day(o.get("week"))), E(_fmt_day(o.get("prev_week"))) if o.get("prev_week") else "the week before", on_rows)

    short = lambda d: datetime.fromisoformat(d[:10]).strftime("%b %-d") if d else ""
    us_head = ("United States · week of %s" % _fmt_day(e.get("week"))) if us else "United States · no data yet"
    ca_head = ("Canada · %s" % _month(c.get("month"))) if ca else "Canada · no data yet"
    us_vs = "vs %s" % short(e.get("prev_week")) if e.get("prev_week") else "Change"
    ca_vs = "vs %s" % _month(c.get("prev_month")).split(" ")[0] if c.get("prev_month") else "Change"
    def scale(label, lo, hi):
        return ('<div class="fscale"><span class="fl">%s</span><span class="fb" style="background:linear-gradient(90deg,%s)"></span>'
                '<span class="fr"><span>%s</span><span>%s</span></span></div>') % (label, ",".join(FUEL_SCALE), lo, hi)
    scales = ""
    if us:
        vals = [v for k, v in us.items() if k in EIA_STATE_REGION.values()] or list(us.values())
        scales += scale("United States, US$/gal", "$%.2f" % min(vals), "$%.2f" % max(vals))
    if ca:
        scales += scale("Canada, ¢/L", "%.0f¢" % min(ca.values()), "%.0f¢" % max(ca.values()))
    return """<section class="mk-sec" aria-labelledby="fuel-h"><h2 id="fuel-h" class="sec-title">Diesel prices · US and Canada</h2>
<p class="mk-lede">Retail on-highway diesel, latest official survey prices.</p>
<div class="mk-mapbox fuelbox"><div class="mk-mapwrap">{svg}</div>
<aside class="mk-side">{scales}
<p class="note"><strong>US:</strong> EIA weekly survey, published Mondays. Each state shows its EIA region's average.<br>
<strong>Canada:</strong> Statistics Canada monthly survey. Each province shows the average of its surveyed cities.<br>
Pump prices including taxes; not fleet or cardlock prices. Shading is relative within each country, and prices are not comparable across the border.</p></aside></div>
<div class="two">
<div><h3 class="mk-h3">{us_head}</h3><div class="table-box"><table class="waits mk-small mk-tight"><thead><tr><th>EIA region</th><th>US$/gal</th><th>{us_vs}</th></tr></thead><tbody>{us_rows}</tbody></table></div>
<p class="note">Source: U.S. Energy Information Administration, <a href="https://www.eia.gov/petroleum/gasdiesel/" rel="noopener" target="_blank">Gasoline and Diesel Fuel Update</a> (public domain). Retrieved {us_ret}.</p></div>
<div><h3 class="mk-h3">{ca_head}</h3><div class="table-box"><table class="waits mk-small mk-tight"><thead><tr><th>Province (cities surveyed)</th><th>¢/L</th><th>{ca_vs}</th></tr></thead><tbody>{ca_rows}</tbody></table></div>
<p class="note">Source: Statistics Canada, <a href="https://doi.org/10.25318/1810000101-eng" rel="noopener" target="_blank">monthly average retail prices, diesel at self-service stations</a>, Open Government Licence – Canada. Retrieved {ca_ret}.</p>
{on}</div></div></section>""".format(svg=svg, scales=scales, us_vs=E(us_vs), ca_vs=E(ca_vs), us_head=E(us_head), ca_head=E(ca_head),
                                       us_rows=us_rows or '<tr><td colspan="3" class="note">No data yet.</td></tr>',
                                       ca_rows=ca_rows or '<tr><td colspan="3" class="note">No data yet.</td></tr>',
                                       us_ret=E(_fmt_time(e.get("retrieved_at"), tz)), ca_ret=E(_fmt_time(c.get("retrieved_at"), tz)), on=on)


def _region_options():
    us = "".join('<option value="%s">%s</option>' % (k, E(v)) for k, v in sorted(REGION_NAMES.items(), key=lambda kv: kv[1]))
    ca = "".join('<option value="%s">%s</option>' % (k, E(v)) for k, v in sorted(PROVINCE_NAMES.items(), key=lambda kv: kv[1]))
    return '<option value="">Choose…</option><optgroup label="Canada">%s</optgroup><optgroup label="United States">%s</optgroup>' % (ca, us)


EQ_OPTIONS = '<option value="van">Dry van</option><option value="reefer">Reefer</option><option value="flatbed">Flatbed</option><option value="stepdeck">Step deck</option>'


def reader_sections():
    regions = _region_options()
    def rate_fields(p):
        return """<label>Pickup<select name="o" required>{r}</select></label>
<label>Delivery<select name="d" required>{r}</select></label>
<label>Equipment<select name="equipment" required>{eq}</select></label>
<label>Rate for the load (all-in)<input name="amount" inputmode="decimal" placeholder="e.g. 2250" required></label>
<label>Loaded distance<span class="pair"><input name="distance" inputmode="numeric" placeholder="e.g. 790" required>
<select name="unit" aria-label="Distance unit"><option value="mi">miles</option><option value="km">km</option></select></span></label>
<label>Currency<select name="currency"><option value="USD">US$</option><option value="CAD">C$</option></select></label>""".format(r=regions, eq=EQ_OPTIONS)
    tiles = tile_map({}, {}, "r-", "Reader reports by state and province. Details are in the lane table and legend.")
    return """<div class="mk-off" id="mk-off" hidden>Reader reports are switching on soon. The rate checker, map and lane rates will fill in as drivers and brokers report.</div>
<section class="mk-sec" aria-labelledby="chk-h"><h2 id="chk-h" class="sec-title">Is this rate fair?</h2>
<p class="mk-lede">Enter a load you've been offered. We compare it with what other carriers reported on the same lane.</p>
<form id="chk" class="mk-form" novalidate><div class="f">{fields}</div>
<button class="btn2" type="submit">Check rate</button><div id="chk-out" class="mk-out" aria-live="polite"></div></form></section>

<section class="mk-sec" aria-labelledby="wk-h"><h2 id="wk-h" class="sec-title">This week's market · reader reports</h2>
<div class="eq" id="eq" role="group" aria-label="Equipment"><button class="chip" data-eq="all" aria-pressed="true">All</button>
<button class="chip" data-eq="van" aria-pressed="false">Dry van</button><button class="chip" data-eq="reefer" aria-pressed="false">Reefer</button>
<button class="chip" data-eq="flatbed" aria-pressed="false">Flatbed</button><button class="chip" data-eq="stepdeck" aria-pressed="false">Step deck</button></div>
<div class="mk-mapbox"><div class="mk-mapwrap">{tiles}</div>
<aside class="mk-side"><h3 id="map-title">Loads this week</h3>
<ul class="mk-legend"><li><i style="background:#C4262E"></i><b>Busy</b> <span>Plenty of loads, rates firm</span></li>
<li><i style="background:#E6DFC8"></i><b>Normal</b> <span>About usual for the season</span></li>
<li><i style="background:#2F6690"></i><b>Slow</b> <span>More trucks than loads, rates soft</span></li>
<li><i style="background:#F1F2F4;border:1px solid #C9CED4"></i><b>Insufficient reports</b> <span>Fewer than 5 this week</span></li></ul>
<p class="mk-hot" id="map-count"></p>
<p class="note">Colours come from readers' weekly one-tap answers. One person can't move the map: each counts once per week.</p></aside></div>
<h3 class="mk-h3">Lane rates, last 7 days</h3>
<div class="eq" id="mkt" role="group" aria-label="Market"><button class="chip" data-m="all" aria-pressed="true">All</button>
<button class="chip" data-m="US" aria-pressed="false">US</button><button class="chip" data-m="CA" aria-pressed="false">Canada</button>
<button class="chip" data-m="XB" aria-pressed="false">Cross-border</button></div>
<div class="table-box mk-table"><table class="waits"><caption class="sr">Reader-reported lane rates, last 7 days</caption>
<thead><tr><th scope="col">Lane</th><th scope="col">Equipment</th><th scope="col">Typical rate (median)</th><th scope="col">Reports</th><th scope="col">vs last week</th></tr></thead>
<tbody id="lanes-body"><tr><td colspan="5" class="note">Loading…</td></tr></tbody></table></div>
<p class="note">© HaulTimes. Quote with credit; bulk copying or scraping is not allowed (<a href="/terms/">Terms</a>). All-in rates (line haul plus fuel) reported by readers, not verified loads. A lane shows once at least 5 reports from 3 different people come in; one person's reports count at most twice. US and cross-border lanes in US$, Canadian lanes in C$ (converted at the Bank of Canada daily rate when reported in the other currency).</p>
</section>

<section class="mk-sec" aria-labelledby="add-h"><h2 id="add-h" class="sec-title">Add your numbers · anonymous</h2>
<div class="two">
<form class="box" id="poll" novalidate><h3>How's your market this week?</h3>
<p><span id="poll-where">Your area</span> · <button type="button" class="linkbtn" id="poll-change">change</button></p>
<div class="f" id="poll-pick" hidden><label>State or province<select name="region">{r}</select></label>
<label>Equipment<select name="equipment">{eq}</select></label></div>
<p class="note" id="poll-eq-line">Equipment: <b id="poll-eq">Dry van</b></p>
<button type="button" class="pollbtn" data-a="1"><span><b>Busy</b> · plenty of loads, rates firm</span></button>
<button type="button" class="pollbtn" data-a="0"><span><b>Normal</b> · about usual for the season</span></button>
<button type="button" class="pollbtn" data-a="-1"><span><b>Slow</b> · more trucks than loads, rates soft</span></button>
<div class="mk-out" id="poll-out" aria-live="polite"></div>
<span class="note">Anonymous. One answer per week; answering again replaces it. By answering you agree to our <a href="/terms/">Terms</a>.</span></form>
<form class="box" id="rep" novalidate><h3>Report a rate</h3><p>A load you hauled or booked in the last 14 days. No company names.</p>
<div class="f">{fields}<label>Load date<input name="date" type="date" required></label>
<input name="website" class="hp" tabindex="-1" autocomplete="off" aria-hidden="true"></div>
<button class="btn2" type="submit">Submit rate</button><p class="note">By submitting you agree to our <a href="/terms/">Terms</a>. Only combined figures are published.</p><div class="mk-out" id="rep-out" aria-live="polite"></div></form>
</div></section>""".format(fields=rate_fields("c"), tiles=tiles, r=regions, eq=EQ_OPTIONS)


def links_section():
    return """<section class="mk-sec" aria-labelledby="links-h"><h2 id="links-h" class="sec-title">More market data (other sites)</h2>
<ul class="mk-links">
<li><a href="{ftr}" rel="noopener" target="_blank"><strong>Truckstop and FTR heat map ›</strong></a>
<span>Van, reefer, flatbed and specialized by state, compared with each state's own seasonal normal.</span></li>
<li><a href="{dat}" rel="noopener" target="_blank"><strong>DAT Trendlines ›</strong></a>
<span>National weekly spot rates and load-to-truck ratios for van, reefer and flatbed.</span></li>
</ul></section>""".format(ftr=E(FTR_URL), dat=E(DAT_URL))


SCRIPT = '<script src="/static/market.js" defer></script>'


def body(market, now, tz):
    u = market.get("usda_reefer", {})
    return """<main class="wrap mk">
<div class="page-head"><h1>Freight Market</h1>
<p>What carriers are getting paid, lane by lane, for dry van, reefer, flatbed and step deck across the US and Canada. Reported anonymously by drivers and brokers, next to official government data.</p></div>
{reader}
{diesel}
{gov}
{reefer}
{links}
</main>""".format(reader=reader_sections(), diesel=diesel_section(market, now, tz), gov=gov_section(market, now, tz), reefer=reefer_section(u, now, tz), links=links_section())
