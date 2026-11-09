"""
Freight-market indicators for haultimes.com/freight-market/.

Only sources whose terms allow commercial reuse with credit:

  1. USDA AMS Specialty Crops Market News, via USDA AgTransport (Socrata API, no key):
     weekly refrigerated (reefer) truck availability at produce shipping districts
     (1 = surplus ... 5 = shortage) and reported spot rates to 10 destination cities.
     USDA: "public domain information may be freely distributed or copied" (credit requested).
  2. Ontario Fuels Price Survey (Open Government Licence – Ontario): weekly retail diesel,
     cents per litre, 10 Ontario markets.
  3. U.S. EIA weekly retail on-highway diesel (public domain), only if EIA_API_KEY is set.

Each source is fetched at most every few hours (they update weekly). If a fetch fails,
the previous good data is kept with its original dates and the failure is recorded,
so the page can say "last retrieved ... (update failed ...)".
"""

import csv
import io
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from common import load_json, save_json

UA = {"User-Agent": "HaulTimes/1.0 (haultimes.com freight market page)"}
NOW = datetime.now(timezone.utc)

USDA_URL = "https://agtransport.usda.gov/resource/25pi-t6xr.json?$limit=5000"
USDA_PAGE = "https://agtransport.usda.gov/d/acar-e3r8"
ONTARIO_URL = "https://ontario.ca/v1/files/fuel-prices/fueltypesall.csv"
ONTARIO_PAGE = "https://data.ontario.ca/dataset/fuels-price-survey-information"
EIA_URL = ("https://api.eia.gov/v2/petroleum/pri/gnd/data/?frequency=weekly&data[0]=value"
           "&facets[product][]=EPD2D&sort[0][column]=period&sort[0][direction]=desc&length=60&api_key=")
EIA_PAGE = "https://www.eia.gov/petroleum/gasdiesel/"

AVAILABILITY = {1: "Surplus", 2: "Slight surplus", 3: "Adequate", 4: "Slight shortage", 5: "Shortage"}

STATES = {
    "ALABAMA": "AL", "ARIZONA": "AZ", "ARKANSAS": "AR", "CALIFORNIA": "CA", "COLORADO": "CO", "CONNECTICUT": "CT",
    "DELAWARE": "DE", "FLORIDA": "FL", "GEORGIA": "GA", "IDAHO": "ID", "ILLINOIS": "IL", "INDIANA": "IN", "IOWA": "IA",
    "KANSAS": "KS", "KENTUCKY": "KY", "LOUISIANA": "LA", "MAINE": "ME", "MARYLAND": "MD", "MASSACHUSETTS": "MA",
    "MICHIGAN": "MI", "MINNESOTA": "MN", "MISSISSIPPI": "MS", "MISSOURI": "MO", "MONTANA": "MT", "NEBRASKA": "NE",
    "NEVADA": "NV", "NEW HAMPSHIRE": "NH", "NEW JERSEY": "NJ", "NEW MEXICO": "NM", "NEW YORK": "NY",
    "NORTH CAROLINA": "NC", "NORTH DAKOTA": "ND", "OHIO": "OH", "OKLAHOMA": "OK", "OREGON": "OR",
    "PENNSYLVANIA": "PA", "RHODE ISLAND": "RI", "SOUTH CAROLINA": "SC", "SOUTH DAKOTA": "SD", "TENNESSEE": "TN",
    "TEXAS": "TX", "UTAH": "UT", "VERMONT": "VT", "VIRGINIA": "VA", "WASHINGTON": "WA", "WEST VIRGINIA": "WV",
    "WISCONSIN": "WI", "WYOMING": "WY",
}
CODES = set(STATES.values())
# Regional names USDA uses for shipping districts
REGIONS = {"DELMARVA": ["DE", "MD", "VA"], "RIO GRANDE VALLEY": ["TX"], "LOWER RIO GRANDE": ["TX"],
           "SAN JOAQUIN": ["CA"], "SALINAS": ["CA"], "SANTA MARIA": ["CA"], "OXNARD": ["CA"], "COACHELLA": ["CA"],
           "IMPERIAL": ["CA"], "YAKIMA": ["WA"], "WENATCHEE": ["WA"], "COLUMBIA BASIN": ["WA", "OR"],
           "RED RIVER VALLEY": ["MN", "ND"], "UPPER VALLEY": ["ID"], "SAN LUIS VALLEY": ["CO"],
           "PEACE RIVER": ["FL"], "PALM BEACH": ["FL"], "EVERGLADES": ["FL"], "SOUTH DISTRICT": ["TX"]}


def states_in(origin):
    """US states named in a USDA shipping-district name. Never guesses: unknown -> []."""
    o = " %s " % origin.upper().replace(".", "")
    found = []
    for name in sorted(STATES, key=len, reverse=True):
        if re.search(r"(?<![A-Z])%s(?![A-Z])" % name, o):
            if name == "VIRGINIA" and "WEST VIRGINIA" in o and o.count("VIRGINIA") == 1:
                continue
            if name == "KANSAS" and "ARKANSAS" in o and o.count("KANSAS") == 1:
                continue
            found.append(STATES[name])
    # Two-letter codes only where USDA writes them as codes: before a comma, "AND" or the end
    for code in re.findall(r"(?<=\s)([A-Z]{2})(?=\s*(?:,|$|\s+AND\s|\s+-))", o.strip() + " "):
        if code in CODES and code not in found:
            found.append(code)
    if not found:
        for key, codes in REGIONS.items():
            if key in o:
                found += [c for c in codes if c not in found]
    return found


def http_get(url, timeout=40):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def due(store, hours):
    """Fetch again after `hours` since the last success; after a failure, retry hourly."""
    ok, tried = store.get("retrieved_at"), store.get("last_attempt_at")
    if tried and store.get("last_error") and NOW - datetime.fromisoformat(tried) < timedelta(hours=1):
        return False
    return not ok or NOW - datetime.fromisoformat(ok) >= timedelta(hours=hours)


def keep_old(store, err):
    store["last_attempt_at"] = NOW.isoformat()
    store["last_error"] = err[:300]
    return store


# ------------------------------------------------------------------ USDA reefer

def parse_usda(rows):
    """Turn USDA rows into one entry per origin district (+ commodity group)."""
    if not isinstance(rows, list) or not rows:
        raise ValueError("no rows")
    weeks = {r.get("date", "")[:10] for r in rows}
    if len(weeks) != 1:
        raise ValueError("expected one week, got %d" % len(weeks))
    week = weeks.pop()
    datetime.fromisoformat(week)
    origins = {}
    for r in rows:
        try:
            avail = int(float(r["availability"]))
        except (KeyError, TypeError, ValueError):
            avail = None
        if avail is not None and avail not in AVAILABILITY:
            avail = None
        key = (r.get("origin", "").strip(), r.get("commodity", "").strip())
        o = origins.setdefault(key, {
            "origin": key[0], "commodity": key[1], "region": (r.get("region") or "").strip(),
            "states": states_in(key[0]), "mexico": "MEXICO" in key[0].upper(),
            "availability": avail, "rates": []})
        if avail is not None and (o["availability"] is None or avail > o["availability"]):
            o["availability"] = avail

        def num(k):
            try:
                v = float(r[k])
                return v if v > 0 else None
            except (KeyError, TypeError, ValueError):
                return None
        rate = {"destination": (r.get("destination") or "").strip().title(), "distance": num("distance"),
                "low": num("weeklow"), "high": num("weekhigh"), "mid": num("midpoint")}
        if rate["mid"] and rate["distance"]:
            rate["rpm"] = round(rate["mid"] / rate["distance"], 2)
        if rate["destination"] and (rate["low"] or rate["high"] or rate["mid"]):
            o["rates"].append(rate)
    out = sorted(origins.values(), key=lambda o: (-(o["availability"] or 0), o["origin"]))
    return week, out


def update_usda(store):
    if not due(store, 6):
        return store
    try:
        rows = json.loads(http_get(USDA_URL))
        week, origins = parse_usda(rows)
    except Exception as e:  # keep last good data
        return keep_old(store, "USDA AgTransport: %s: %s" % (type(e).__name__, e))
    prev = store.get("week_ending")
    if prev and week < prev:
        return keep_old(store, "USDA returned an older week (%s) than stored (%s)" % (week, prev))
    history = store.get("history", {})
    if prev and prev != week and store.get("origins"):
        history[prev] = {"%s|%s" % (o["origin"], o["commodity"]): {"availability": o["availability"],
                                                                     "mid": {x["destination"]: x["mid"] for x in o["rates"]}}
                         for o in store["origins"]}
        history = dict(sorted(history.items())[-12:])
    store.update(week_ending=week, origins=origins, retrieved_at=NOW.isoformat(), history=history,
                 last_attempt_at=NOW.isoformat(), last_error=None, source_url=USDA_PAGE)
    return store


# ------------------------------------------------------------------ Ontario diesel

def parse_ontario(text):
    """Return (date, {market: cents_per_litre}) for diesel, latest week.

    Accepts the two layouts such files usually have and refuses anything else:
      wide:  Date, Fuel Type, <market 1>, <market 2>, ...
      long:  Date, Fuel Type, Market, Price
    """
    rows = list(csv.reader(io.StringIO(text)))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if len(rows) < 2:
        raise ValueError("empty file")
    head = [h.strip().lower() for h in rows[0]]
    di = next((i for i, h in enumerate(head) if "date" in h), None)
    fi = next((i for i, h in enumerate(head) if "fuel" in h or "type" in h or "product" in h), None)
    if di is None or fi is None:
        raise ValueError("unrecognized columns: %s" % rows[0][:6])

    def pdate(s):
        s = s.strip()
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d", "%d-%b-%y", "%b %d, %Y"):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                pass
        return None

    def pnum(s):
        try:
            v = float(s.replace(",", "").strip())
            return v if 40 <= v <= 400 else None  # plausible cents/litre
        except (ValueError, AttributeError):
            return None

    by_date = {}
    mi = next((i for i, h in enumerate(head) if h in ("market", "city", "location", "region")), None)
    pi = next((i for i, h in enumerate(head) if "price" in h), None)
    for r in rows[1:]:
        if len(r) <= max(di, fi) or "diesel" not in r[fi].lower():
            continue
        d = pdate(r[di])
        if not d:
            continue
        if mi is not None and pi is not None:  # long layout
            v = pnum(r[pi]) if len(r) > pi else None
            if v and len(r) > mi:
                by_date.setdefault(d, {})[r[mi].strip()] = v
        else:  # wide layout
            for i, h in enumerate(rows[0]):
                if i in (di, fi) or i >= len(r):
                    continue
                v = pnum(r[i])
                if v:
                    by_date.setdefault(d, {})[h.strip()] = v
    if not by_date:
        raise ValueError("no diesel rows recognized")
    latest = max(by_date)
    prev = max((d for d in by_date if d < latest), default=None)
    return latest.isoformat(), by_date[latest], (prev.isoformat() if prev else None), (by_date.get(prev) or {})


def update_ontario(store):
    if not due(store, 12):
        return store
    try:
        raw = http_get(ONTARIO_URL).decode("utf-8-sig", "replace")
        store["sample_head"] = raw.splitlines()[:3]  # kept so the layout can be checked
        week, prices, prev_week, prev_prices = parse_ontario(raw)
    except Exception as e:
        return keep_old(store, "Ontario fuel survey: %s: %s" % (type(e).__name__, e))
    store.update(week=week, prices=prices, prev_week=prev_week, prev_prices=prev_prices,
                 retrieved_at=NOW.isoformat(), last_attempt_at=NOW.isoformat(), last_error=None,
                 source_url=ONTARIO_PAGE)
    return store


# ------------------------------------------------------------------ EIA diesel by region (public domain)
# With a free EIA_API_KEY the official API is used; without one, the same weekly table is read from
# EIA's Gasoline and Diesel Fuel Update page. Both give retail on-highway diesel, US$/gallon, by region.

EIA_REGIONS = [  # (key, label, words that identify it in EIA's names), most specific first
    ("5XCA", "West Coast except California", ("less california", "except california", "padd 5 ex", "padd 5xca")),
    ("CA", "California", ("california",)),
    ("1A", "New England", ("new england", "padd 1a")),
    ("1B", "Central Atlantic", ("central atlantic", "padd 1b")),
    ("1C", "Lower Atlantic", ("lower atlantic", "padd 1c")),
    ("1", "East Coast", ("east coast", "padd 1")),
    ("2", "Midwest", ("midwest", "padd 2")),
    ("3", "Gulf Coast", ("gulf coast", "padd 3")),
    ("4", "Rocky Mountain", ("rocky mountain", "padd 4")),
    ("5", "West Coast", ("west coast", "padd 5")),
    ("US", "US average", ("u.s.", "united states", "us average", "national")),
]
# Which EIA region each state is priced in (EIA's own regional definitions)
EIA_STATE_REGION = {}
for _r, _states in {"1A": "ME NH VT MA RI CT", "1B": "NY NJ PA DE MD", "1C": "VA WV NC SC GA FL",
                    "2": "ND SD NE KS OK MN IA MO WI IL IN MI OH KY TN", "3": "TX LA MS AL AR NM",
                    "4": "MT ID WY UT CO", "5XCA": "WA OR NV AZ AK HI", "CA": "CA"}.items():
    for _s in _states.split():
        EIA_STATE_REGION[_s] = _r


def eia_region(name):
    n = " %s " % name.lower().replace("(", " ").replace(")", " ")
    for key, _, words in EIA_REGIONS:
        if any(w in n for w in words):
            return key
    return None


class _Tables(__import__("html.parser").parser.HTMLParser):
    """Collects every <table> as rows of cell texts, plus the text that came just before it."""
    def __init__(self):
        super().__init__()
        self.tables, self.before, self.cell, self.row, self.depth = [], "", None, None, 0
    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.depth += 1
            self.tables.append({"before": self.before[-300:], "rows": []})
        elif tag == "tr" and self.depth:
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = ""
    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.row is not None and self.cell is not None:
            self.row.append(" ".join(self.cell.split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if self.row and self.tables:
                self.tables[-1]["rows"].append(self.row)
            self.row = None
        elif tag == "table":
            self.depth = max(0, self.depth - 1)
    def handle_data(self, data):
        if self.cell is not None:
            self.cell += data
        else:
            self.before += " " + data.strip()


def parse_eia_page(html_text):
    """Diesel table from EIA's Gasoline and Diesel Fuel Update page -> (week, {region: price}, prev_week, {region: price})."""
    p = _Tables()
    p.feed(html_text)
    for t in p.tables:
        # The table's own heading is whichever fuel word appears LAST in the text just before it
        # (the page title "Gasoline and Diesel Fuel Update" mentions both, so "contains diesel" is not enough).
        before = t["before"].lower()
        own = " ".join(" ".join(r) for r in t["rows"][:1]).lower()
        if "diesel" in own and "gasoline" not in own:
            pass
        elif before.rfind("diesel") <= before.rfind("gasoline"):
            continue
        dates = None
        for r in t["rows"]:
            ds = [c for c in r if re.match(r"^\d{1,2}/\d{1,2}/\d{2,4}$", c)]
            if len(ds) >= 2:
                dates = ds
                break
        if not dates:
            continue
        cur, prev = {}, {}
        for r in t["rows"]:
            if not r:
                continue
            key = eia_region(r[0])
            nums = []
            for c in r[1:]:
                try:
                    nums.append(float(c.replace("$", "")))
                except ValueError:
                    pass
            if key and len(nums) >= len(dates) and 1 < nums[len(dates) - 1] < 15:
                cur[key] = nums[len(dates) - 1]
                prev[key] = nums[len(dates) - 2]
        if len(cur) >= 5 and cur.get("US", 0) > 0:
            iso = lambda d: datetime.strptime(d, "%m/%d/%y" if len(d.split("/")[2]) == 2 else "%m/%d/%Y").date().isoformat()
            return iso(dates[-1]), cur, iso(dates[-2]), prev
    raise ValueError("diesel table not found on EIA page")


EIA_PARSER = 2   # bump to force a fresh fetch when the way the page is read changes


def update_eia(store, key):
    if store.get("parser") == EIA_PARSER and not due(store, 6):
        return store
    try:
        if key:
            body = json.loads(http_get(EIA_URL + urllib.parse.quote(key)))
            data = body["response"]["data"]
            weeks = sorted({d["period"] for d in data}, reverse=True)
            if len(weeks) < 2:
                raise ValueError("not enough weeks")
            def pick(wk):
                out = {}
                for d in data:
                    r = eia_region(d.get("area-name", "") + " " + d.get("duoarea", ""))
                    if d["period"] == wk and r and d.get("value") not in (None, ""):
                        out.setdefault(r, float(d["value"]))
                return out
            latest, prices, prev_week, prev_prices = weeks[0], pick(weeks[0]), weeks[1], pick(weeks[1])
        else:
            latest, prices, prev_week, prev_prices = parse_eia_page(http_get(EIA_PAGE).decode("utf-8", "replace"))
    except Exception as e:
        msg = re.sub(r"api_key=[^&\s]+", "api_key=***", "%s: %s" % (type(e).__name__, e))
        return keep_old(store, "EIA: " + msg)
    store.update(status="ok", week=latest, prices=prices, prev_week=prev_week, prev_prices=prev_prices, parser=EIA_PARSER,
                 units="US$ per gallon", retrieved_at=NOW.isoformat(), last_attempt_at=NOW.isoformat(),
                 last_error=None, source_url=EIA_PAGE)
    return store


# ------------------------------------------------------------------ Canada diesel by city (Statistics Canada, Open Government Licence)

STATCAN_FUEL_URL = "https://www150.statcan.gc.ca/n1/tbl/csv/18100001-eng.zip"
STATCAN_FUEL_PAGE = "https://doi.org/10.25318/1810000101-eng"
PROVINCES = {"newfoundland and labrador": "NL", "prince edward island": "PE", "nova scotia": "NS", "new brunswick": "NB",
             "quebec": "QC", "ontario": "ON", "manitoba": "MB", "saskatchewan": "SK", "alberta": "AB",
             "british columbia": "BC", "yukon": "YT", "northwest territories": "NT", "nunavut": "NU"}


def city_province(geo):
    g = geo.lower()
    if "ontario part" in g:
        return "ON"
    if "quebec part" in g:
        return "QC"
    last = g.split(",")[-1].strip()
    for name, code in PROVINCES.items():
        if name in last:
            return code
    return None


def parse_statcan_fuel(csv_text):
    """Monthly diesel (self-serve) by city -> (month, {province: {"avg": ¢/L, "cities": {...}}}, prev_month, {...})."""
    rows = list(csv.DictReader(io.StringIO(csv_text)))
    if not rows or "REF_DATE" not in rows[0]:
        raise ValueError("unexpected StatCan layout")
    fuel_col = next((c for c in rows[0] if "fuel" in c.lower()), None)
    if not fuel_col:
        raise ValueError("no fuel column")
    by_month = {}
    for r in rows:
        if "diesel" not in r[fuel_col].lower() or not r.get("VALUE"):
            continue
        prov = city_province(r["GEO"])
        if not prov:
            continue
        try:
            v = float(r["VALUE"])
        except ValueError:
            continue
        if not 40 <= v <= 400:
            continue
        city = r["GEO"].split(",")[0].strip()
        by_month.setdefault(r["REF_DATE"][:7], {}).setdefault(prov, {})[city] = v
    if not by_month:
        raise ValueError("no diesel rows")
    months = sorted(by_month)
    def summarise(m):
        return {p: {"avg": round(sum(c.values()) / len(c), 1), "cities": c} for p, c in by_month.get(m, {}).items()}
    latest = months[-1]
    prev = months[-2] if len(months) > 1 else None
    return latest, summarise(latest), prev, summarise(prev) if prev else {}


def update_statcan_fuel(market):
    st = market.get("statcan_diesel", {})
    if due(st, 12):
        try:
            import zipfile
            z = zipfile.ZipFile(io.BytesIO(http_get(STATCAN_FUEL_URL, timeout=90)))
            name = next(n for n in z.namelist() if n.endswith(".csv") and "MetaData" not in n)
            month, provs, prev_month, prev_provs = parse_statcan_fuel(z.read(name).decode("utf-8-sig", "replace"))
            st.update(month=month, provinces=provs, prev_month=prev_month, prev_provinces=prev_provs,
                      retrieved_at=NOW.isoformat(), last_attempt_at=NOW.isoformat(), last_error=None, source_url=STATCAN_FUEL_PAGE)
        except Exception as e:
            st = keep_old(st, "Statistics Canada fuel: %s: %s" % (type(e).__name__, e))
    market["statcan_diesel"] = st


# ------------------------------------------------------------------ official indicators (public domain / open licence)

BLS_SERIES = {
    "bls_truckload": ("PCU484121484121", "https://fred.stlouisfed.org/series/PCU484121484121"),
    "bls_specialized": ("PCU484230484230", "https://fred.stlouisfed.org/series/PCU484230484230"),
}
BLS_URL = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
STATCAN_URL = "https://www150.statcan.gc.ca/n1/tbl/csv/18100281-eng.zip"
STATCAN_PAGE = "https://doi.org/10.25318/1810028101-eng"
BTS_URL = ("https://data.bts.gov/resource/keg4-3bc2.json?$select=date,sum(value)%20as%20trucks"
           "&$where=border=%27US-Canada%20Border%27%20AND%20measure=%27Trucks%27&$group=date&$order=date%20DESC&$limit=14")
BTS_PAGE = "https://www.bts.gov/browse-statistical-products-and-data/border-crossing-data/border-crossingentry-data"


def series_store(store, points, source_url, label=None):
    """points: list of (period 'YYYY-MM', value) newest last. Keeps 13 months."""
    points = sorted(points)[-13:]
    if len(points) < 2:
        raise ValueError("fewer than 2 data points")
    store.update(points=points, period=points[-1][0], value=points[-1][1], prev=points[-2][1],
                 retrieved_at=NOW.isoformat(), last_attempt_at=NOW.isoformat(), last_error=None, source_url=source_url)
    if label:
        store["label"] = label
    return store


def parse_bls(body, series_id):
    if body.get("status") != "REQUEST_SUCCEEDED":
        raise ValueError("BLS status %s" % body.get("status"))
    for s in body["Results"]["series"]:
        if s.get("seriesID") == series_id:
            pts = []
            for d in s["data"]:
                if not d.get("period", "").startswith("M") or d["period"] == "M13":
                    continue
                try:
                    pts.append(("%s-%s" % (d["year"], d["period"][1:]), float(d["value"])))
                except ValueError:
                    continue
            return pts
    raise ValueError("series %s missing" % series_id)


def update_bls(market):
    for key, (sid, page) in BLS_SERIES.items():
        st = market.get(key, {})
        if due(st, 12):
            try:
                st = series_store(st, parse_bls(json.loads(http_get(BLS_URL + sid)), sid), page)
            except Exception as e:
                st = keep_old(st, "BLS %s: %s: %s" % (sid, type(e).__name__, e))
        market[key] = st


def parse_statcan(csv_text):
    """Canada-level monthly index. Picks the all-services total when the table has several series."""
    rows = list(csv.DictReader(io.StringIO(csv_text)))
    if not rows or "REF_DATE" not in rows[0] or "VALUE" not in rows[0]:
        raise ValueError("unexpected StatCan layout")
    cols = list(rows[0].keys())
    dims = [c for c in cols[cols.index("GEO") + 1:cols.index("UOM")] if c not in ("DGUID",)] if "GEO" in cols and "UOM" in cols else []
    series = {}
    for r in rows:
        if r.get("GEO", "Canada") != "Canada" or not r.get("VALUE"):
            continue
        key = tuple(r[c] for c in dims)
        try:
            series.setdefault(key, []).append((r["REF_DATE"][:7], float(r["VALUE"])))
        except ValueError:
            continue
    if not series:
        raise ValueError("no Canada rows")
    def rank(item):
        key, pts = item
        text = " ".join(key).lower()
        return (("total" in text or "all" in text), -len(text), max(pts)[0])
    key, pts = max(series.items(), key=rank)
    return pts, "; ".join(k for k in key if k)


def update_statcan(market):
    st = market.get("statcan_trucking", {})
    if due(st, 12):
        try:
            import zipfile
            z = zipfile.ZipFile(io.BytesIO(http_get(STATCAN_URL, timeout=90)))
            name = next(n for n in z.namelist() if n.endswith(".csv") and "MetaData" not in n)
            pts, label = parse_statcan(z.read(name).decode("utf-8-sig", "replace"))
            st = series_store(st, pts, STATCAN_PAGE, label)
        except Exception as e:
            st = keep_old(st, "Statistics Canada: %s: %s" % (type(e).__name__, e))
    market["statcan_trucking"] = st


def parse_bts(rows):
    pts = []
    for r in rows:
        try:
            pts.append((r["date"][:7], float(r["trucks"])))
        except (KeyError, TypeError, ValueError):
            continue
    return pts


def update_bts(market):
    st = market.get("bts_trucks_canada", {})
    if due(st, 12):
        try:
            st = series_store(st, parse_bts(json.loads(http_get(BTS_URL))), BTS_PAGE)
        except Exception as e:
            st = keep_old(st, "BTS: %s: %s" % (type(e).__name__, e))
    market["bts_trucks_canada"] = st


def main():
    market = load_json("market.json", {})
    market["usda_reefer"] = update_usda(market.get("usda_reefer", {}))
    market["ontario_diesel"] = update_ontario(market.get("ontario_diesel", {}))
    market["eia_diesel"] = update_eia(market.get("eia_diesel", {}), os.environ.get("EIA_API_KEY"))
    for fn in (update_bls, update_statcan, update_bts, update_statcan_fuel):
        fn(market)
    save_json("market.json", market)
    u = market["usda_reefer"]
    print("Market: USDA reefer week %s (%d origins)%s | Ontario diesel %s%s | EIA %s%s" % (
        u.get("week_ending"), len(u.get("origins", [])), " [error: %s]" % u["last_error"] if u.get("last_error") else "",
        market["ontario_diesel"].get("week"), " [error: %s]" % market["ontario_diesel"]["last_error"] if market["ontario_diesel"].get("last_error") else "",
        market["eia_diesel"].get("week") or market["eia_diesel"].get("status"),
        " [error: %s]" % market["eia_diesel"]["last_error"] if market["eia_diesel"].get("last_error") else ""))
    sd = market.get("statcan_diesel", {})
    print("  statcan_diesel: %s %s provinces%s" % (sd.get("month"), len(sd.get("provinces", {})), " [error: %s]" % sd["last_error"] if sd.get("last_error") else ""))
    for k in ("bls_truckload", "bls_specialized", "statcan_trucking", "bts_trucks_canada"):
        st = market.get(k, {})
        print("  %s: %s %s%s" % (k, st.get("period"), st.get("value"), " [error: %s]" % st["last_error"] if st.get("last_error") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
