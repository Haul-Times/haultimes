"""
Fetch commercial (truck) border wait times from the official US and Canadian
sources and save them to data/border.json, plus a running history used for the
"usual wait by hour" charts.

  US side (trucks entering the US):    U.S. Customs and Border Protection
  Canada side (trucks entering Canada): Canada Border Services Agency open data
"""

import csv
import io
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone

from common import load_json, save_json

try:
    from zoneinfo import ZoneInfo
    EASTERN = ZoneInfo("America/Toronto")
except Exception:  # pragma: no cover
    EASTERN = None

CBP_URL = "https://bwt.cbp.gov/api/bwtnew"
CBSA_URL = "https://www.cbsa-asfc.gc.ca/bwt-taf/bwt-eng.csv"

# Major truck crossings. us = (CBP port name, words in the CBP crossing name or "")
# ca = words found in the CBSA office or location name.
CROSSINGS = [
    {"id": "ambassador", "name": "Ambassador Bridge", "ports": "Detroit, MI ↔ Windsor, ON", "region": "on-mi", "us": ("Detroit", "ambassador"), "ca": ["ambassador bridge"]},
    {"id": "blue-water", "name": "Blue Water Bridge", "ports": "Port Huron, MI ↔ Sarnia, ON", "region": "on-mi", "us": ("Port Huron", ""), "ca": ["blue water"]},
    {"id": "sault", "name": "Sault Ste. Marie Bridge", "ports": "Sault Ste. Marie, MI ↔ Sault Ste. Marie, ON", "region": "on-mi", "us": ("Sault Ste. Marie", ""), "ca": ["sault ste"]},
    {"id": "peace", "name": "Peace Bridge", "ports": "Buffalo, NY ↔ Fort Erie, ON", "region": "on-ny", "us": ("Buffalo/Niagara Falls", "peace"), "ca": ["peace bridge"]},
    {"id": "lewiston", "name": "Lewiston–Queenston Bridge", "ports": "Lewiston, NY ↔ Queenston, ON", "region": "on-ny", "us": ("Buffalo/Niagara Falls", "lewiston"), "ca": ["queenston"]},
    {"id": "thousand-islands", "name": "Thousand Islands Bridge", "ports": "Alexandria Bay, NY ↔ Lansdowne, ON", "region": "on-ny", "us": ("Alexandria Bay", ""), "ca": ["lansdowne"]},
    {"id": "ogdensburg", "name": "Ogdensburg–Prescott Bridge", "ports": "Ogdensburg, NY ↔ Prescott, ON", "region": "on-ny", "us": ("Ogdensburg", ""), "ca": ["prescott"]},
    {"id": "massena", "name": "Massena–Cornwall", "ports": "Massena, NY ↔ Cornwall, ON", "region": "on-ny", "us": ("Massena", ""), "ca": ["cornwall"]},
    {"id": "fort-frances", "name": "International Falls–Fort Frances", "ports": "International Falls, MN ↔ Fort Frances, ON", "region": "on-mn", "us": ("International Falls", ""), "ca": ["fort frances"]},
    {"id": "champlain", "name": "Champlain–Lacolle", "ports": "Champlain, NY ↔ Lacolle, QC", "region": "qc", "us": ("Champlain", ""), "ca": ["lacolle"]},
    {"id": "highgate", "name": "Highgate Springs–Saint-Armand", "ports": "Highgate Springs, VT ↔ Saint-Armand, QC", "region": "qc", "us": ("Highgate Springs", ""), "ca": ["armand", "philipsburg"]},
    {"id": "derby-line", "name": "Derby Line–Stanstead", "ports": "Derby Line, VT ↔ Stanstead, QC", "region": "qc", "us": ("Derby Line", ""), "ca": ["stanstead"]},
    {"id": "houlton", "name": "Houlton–Woodstock", "ports": "Houlton, ME ↔ Woodstock, NB", "region": "atl", "us": ("Houlton", ""), "ca": ["woodstock"]},
    {"id": "calais", "name": "Calais–St. Stephen", "ports": "Calais, ME ↔ St. Stephen, NB", "region": "atl", "us": ("Calais", ""), "ca": ["st. stephen", "st stephen", "saint stephen"]},
    {"id": "pembina", "name": "Pembina–Emerson", "ports": "Pembina, ND ↔ Emerson, MB", "region": "pra", "us": ("Pembina", ""), "ca": ["emerson"]},
    {"id": "portal", "name": "Portal–North Portal", "ports": "Portal, ND ↔ North Portal, SK", "region": "pra", "us": ("Portal", ""), "ca": ["north portal"]},
    {"id": "sweetgrass", "name": "Sweetgrass–Coutts", "ports": "Sweetgrass, MT ↔ Coutts, AB", "region": "pra", "us": ("Sweetgrass", ""), "ca": ["coutts"]},
    {"id": "pacific-highway", "name": "Pacific Highway", "ports": "Blaine, WA ↔ Surrey, BC", "region": "bc", "us": ("Blaine", "pacific"), "ca": ["pacific highway"]},
    {"id": "sumas", "name": "Sumas–Abbotsford", "ports": "Sumas, WA ↔ Abbotsford, BC", "region": "bc", "us": ("Sumas", ""), "ca": ["huntingdon", "abbotsford"]},
]


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; HaulTimesBot/1.0)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def minutes(text):
    """'No delay' -> 0, '25 min' -> 25, '1 hr 10 min' -> 70, closed/unknown -> None."""
    if text is None:
        return None
    t = str(text).strip().lower()
    if t == "" or "not applicable" in t or "n/a" in t or "closed" in t or "update pending" in t:
        return None
    if "no delay" in t:
        return 0
    if t.isdigit():
        return int(t)
    hours = re.search(r"(\d+)\s*(h|hr|hour)", t)
    mins = re.search(r"(\d+)\s*(m|min)", t)
    if hours or mins:
        return (int(hours.group(1)) * 60 if hours else 0) + (int(mins.group(1)) if mins else 0)
    return None


def fetch_us():
    """Trucks entering the US. Returns {(port_name, crossing_name): {...}}."""
    out = {}
    try:
        data = json.loads(get(CBP_URL))
    except Exception as e:
        print("CBP feed failed:", e)
        return out
    if isinstance(data, list) and data:
        sample = next((p for p in data if "canad" in str(p.get("border", "")).lower()), data[0])
        print("CBP sample:", json.dumps({k: sample.get(k) for k in ("port_name", "crossing_name", "border", "commercial_vehicle_lanes")})[:400])
    for p in data if isinstance(data, list) else []:
        if "canad" not in str(p.get("border", "")).lower():
            continue
        cv = p.get("commercial_vehicle_lanes") or {}
        std = cv.get("standard_lanes") or {}
        fast = cv.get("FAST_lanes") or {}
        status = str(std.get("operational_status", "")).strip()
        wait = None
        if status.lower() in ("no delay", "delay"):
            wait = minutes(std.get("delay_minutes"))
            if status.lower() == "no delay":
                wait = 0
        fast_wait = minutes(fast.get("delay_minutes")) if str(fast.get("operational_status", "")).lower() in ("no delay", "delay") else None
        out[(str(p.get("port_name", "")).strip(), str(p.get("crossing_name", "")).strip())] = {
            "wait": wait,
            "fast_wait": fast_wait,
            "lanes": std.get("lanes_open"),
            "status": status or "Unknown",
            "updated": str(std.get("update_time") or p.get("time") or "").strip(),
            "hours": str(p.get("hours", "")).strip(),
        }
    return out


def fetch_ca():
    """Trucks entering Canada. Returns list of rows with office, location, wait, updated."""
    rows = []
    try:
        raw = get(CBSA_URL).decode("utf-8-sig", errors="replace")
    except Exception as e:
        print("CBSA feed failed:", e)
        return rows
    lines = [l for l in raw.splitlines() if l.strip()]
    if not lines:
        return rows
    first = lines[0]
    delim = ";" if first.count(";") > first.count(",") else ("\t" if first.count("\t") > first.count(",") else ",")
    print("CBSA header:", first[:200], "| delimiter:", repr(delim))
    if len(lines) > 1:
        print("CBSA sample row:", lines[1][:200])
    reader = csv.reader(io.StringIO("\n".join(lines)), delimiter=delim)
    header = None
    for r in reader:
        if not r:
            continue
        if header is None:
            header = [h.strip().lower() for h in r]
            continue
        rec = dict(zip(header, [c.strip() for c in r]))
        office = next((v for k, v in rec.items() if "office" in k or "bureau" in k), "")
        location = next((v for k, v in rec.items() if "location" in k), "")
        comm = next((v for k, v in rec.items() if "commercial" in k), None)
        updated = next((v for k, v in rec.items() if "updated" in k or "date" in k), "")
        rows.append({"office": office, "location": location, "raw": comm or "",
                     "wait": minutes(comm), "updated": updated})
    return rows


def now_eastern():
    now = datetime.now(timezone.utc)
    return now.astimezone(EASTERN) if EASTERN else now


def best_window(hist_row, weekday):
    """Lowest-average hour for this weekday, if we have enough readings."""
    hours = []
    for h in range(24):
        s, c = hist_row[weekday * 24 + h]
        if c >= 2:
            hours.append((s / c, h))
    if len(hours) < 12:
        return "Building history"
    avg, hour = min(hours)
    label = "%d %s" % ((hour % 12) or 12, "AM" if hour < 12 else "PM")
    return "Usually fastest around %s" % label


def main():
    us = fetch_us()
    ca = fetch_ca()
    hist = load_json("border_history.json", {})
    local = now_eastern()
    slot = local.weekday() * 24 + local.hour

    used_us, used_ca = set(), set()
    crossings = []
    for c in CROSSINGS:
        port, words = c["us"]
        south = None
        for key, val in us.items():
            if key[0].lower() == port.lower() and (not words or words in key[1].lower()):
                south = val
                used_us.add(key)
                break
        north = None
        for i, row in enumerate(ca):
            hay = (row["office"] + " " + row["location"]).lower()
            if any(w in hay for w in c["ca"]):
                north = {"wait": row["wait"], "status": row["raw"] or "Unknown", "updated": row["updated"]}
                used_ca.add(i)
                break

        h = hist.setdefault(c["id"], {"south": [[0, 0] for _ in range(168)], "north": [[0, 0] for _ in range(168)]})
        for d, val in (("south", south), ("north", north)):
            if val and val.get("wait") is not None:
                cell = h[d][slot]
                # light decay so old readings fade over a few months
                cell[0] = round(cell[0] * 0.97 + val["wait"], 2)
                cell[1] = round(cell[1] * 0.97 + 1, 3)

        usual = {}
        for d in ("south", "north"):
            day = local.weekday()
            usual[d] = [round(h[d][day * 24 + i][0] / h[d][day * 24 + i][1]) if h[d][day * 24 + i][1] >= 1 else None
                        for i in range(24)]
        crossings.append({
            "id": c["id"], "name": c["name"], "ports": c["ports"], "region": c["region"],
            "south": south, "north": north, "usual": usual,
            "best_south": best_window(h["south"], local.weekday()),
            "best_north": best_window(h["north"], local.weekday()),
        })

    others = {
        "south": [{"name": "%s %s" % k if k[1] else k[0], "wait": v["wait"], "status": v["status"]}
                  for k, v in us.items() if k not in used_us],
        "north": [{"name": r["office"] or r["location"], "wait": r["wait"], "status": r["raw"]}
                  for i, r in enumerate(ca) if i not in used_ca and r["raw"]],
    }

    save_json("border.json", {
        "updated": datetime.now(timezone.utc).isoformat(),
        "hour_now": local.hour,
        "have_us": bool(us), "have_ca": bool(ca),
        "crossings": crossings, "others": others,
    })
    save_json("border_history.json", hist)
    print("Border: %d US ports, %d Canadian offices read." % (len(us), len(ca)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
