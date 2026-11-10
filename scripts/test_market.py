"""Tests for the Freight Market fetcher and page. Run: python scripts/test_market.py
Uses made-up rows shaped like real USDA AgTransport rows; nothing here is written to the live data folder."""

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

os.environ["HAULTIMES_DATA"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fetch_market as fm  # noqa: E402
import market_page as mp  # noqa: E402

ET = timezone(timedelta(hours=-5))


def row(origin, dest, avail, mid=8400, dist=2100, date="2026-11-03T00:00:00.000", commodity="MIXED VEGETABLES"):
    return {"date": date, "region": "SOUTHWEST", "origin": origin, "destination": dest, "distance": str(dist),
            "commodity": commodity, "weeklow": str(mid - 150), "weekhigh": str(mid + 150), "midpoint": str(mid),
            "rpm": "4", "availability": str(avail)}


IMPERIAL = "IMPERIAL, COACHELLA VALLEYS CA, CENTRAL AND WESTERN AZ, MEXICO CROSSINGS THROUGH CALEXICO AND SAN LUIS"
ROWS = [row(IMPERIAL, "ATLANTA", 3), row(IMPERIAL, "CHICAGO", 3, 7600, 1900),
        row("SOUTH FLORIDA", "NEW YORK", 5, 4200, 1250), row("WEST VIRGINIA APPLES", "BOSTON", 2, 3000, 700),
        row("MEXICO CROSSINGS THROUGH NOGALES", "LOS ANGELES", 4, 2600, 540),
        row("RED RIVER VALLEY", "DALLAS", 1, 3900, 1100), row("SOMEWHERE ODD", "MIAMI", "")]

failures = []


def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)


# --- district -> state mapping never guesses
check("Imperial maps to CA and AZ", set(fm.states_in(IMPERIAL)) == {"CA", "AZ"})
check("West Virginia is not Virginia", fm.states_in("WEST VIRGINIA APPLES") == ["WV"])
check("Arkansas is not Kansas", fm.states_in("ARKANSAS DELTA") == ["AR"])
check("regional name: Red River Valley", set(fm.states_in("RED RIVER VALLEY")) == {"MN", "ND"})
check("Mexico-only crossing has no US state", fm.states_in("MEXICO CROSSINGS THROUGH NOGALES") == [])
check("unknown district stays unmapped", fm.states_in("SOMEWHERE ODD") == [])
check("'IN' inside a word is not Indiana", "IN" not in fm.states_in("CENTRAL SAN JOAQUIN VALLEY CA"))

# --- parsing
week, origins = fm.parse_usda(ROWS)
check("week parsed", week == "2026-11-03")
imp = next(o for o in origins if o["origin"] == IMPERIAL)
check("one entry per district, rates grouped", len(imp["rates"]) == 2)
check("Mexico flag on Imperial", imp["mexico"])
check("rpm is midpoint / distance", imp["rates"][0]["rpm"] == 4.0)
check("tightest first", origins[0]["availability"] == 5)
odd = next(o for o in origins if o["origin"] == "SOMEWHERE ODD")
check("blank availability -> None, not a guess", odd["availability"] is None)
try:
    fm.parse_usda(ROWS + [row("X", "Y", 3, date="2026-10-27T00:00:00.000")])
    check("mixed weeks rejected", False)
except ValueError:
    check("mixed weeks rejected", True)
try:
    fm.parse_usda([])
    check("empty response rejected", False)
except ValueError:
    check("empty response rejected", True)

# --- failure keeps previous good data
good = {"week_ending": "2026-11-03", "origins": origins, "retrieved_at": "2026-11-05T12:00:00+00:00"}
orig_get = fm.http_get
fm.http_get = lambda url, timeout=40: (_ for _ in ()).throw(OSError("network down"))
kept = fm.update_usda(dict(good, retrieved_at=(fm.NOW - timedelta(hours=7)).isoformat()))
check("failed fetch keeps old origins", kept["origins"] == origins and kept["week_ending"] == "2026-11-03")
check("failed fetch records error", "network down" in kept["last_error"])

# --- an older week from the API is refused; a newer week moves the old one into history
fm.http_get = lambda url, timeout=40: json.dumps([dict(r, date="2026-10-27T00:00:00.000") for r in ROWS]).encode()
older = fm.update_usda(dict(good, retrieved_at=(fm.NOW - timedelta(hours=7)).isoformat()))
check("older week refused", older["week_ending"] == "2026-11-03" and "older week" in older["last_error"])
fm.http_get = lambda url, timeout=40: json.dumps([dict(r, date="2026-11-10T00:00:00.000", availability="5") for r in ROWS]).encode()
newer = fm.update_usda(dict(good, retrieved_at=(fm.NOW - timedelta(hours=7)).isoformat()))
check("newer week stored", newer["week_ending"] == "2026-11-10" and newer["last_error"] is None)
check("previous week kept in history", "2026-11-03" in newer["history"])
check("not re-fetched within 6 hours", fm.update_usda(dict(good, retrieved_at=fm.NOW.isoformat())) ["retrieved_at"] == fm.NOW.isoformat())
fm.http_get = orig_get

# --- EIA without a key does nothing and shows no numbers
# EIA page (no key needed): the diesel table, not the gasoline one
EIA_HTML = """<html><body><h1>Gasoline and Diesel Fuel Update</h1><h2>Retail prices for Gasoline, All Grades</h2><table><tr><th></th><th>10/20/26</th><th>10/27/26</th><th>11/03/26</th></tr>
<tr><td>U.S.</td><td>3.1</td><td>3.10</td><td>3.05</td></tr><tr><td>East Coast (PADD1)</td><td>3.1</td><td>3.1</td><td>3.1</td></tr>
<tr><td>Midwest (PADD2)</td><td>3.1</td><td>3.1</td><td>3.1</td></tr><tr><td>Gulf Coast (PADD3)</td><td>3.1</td><td>3.1</td><td>3.1</td></tr>
<tr><td>Rocky Mountain (PADD4)</td><td>3.1</td><td>3.1</td><td>3.1</td></tr><tr><td>West Coast (PADD5)</td><td>3.1</td><td>3.1</td><td>3.1</td></tr></table>
<h2>On-Highway Diesel Fuel Prices</h2><table><tr><th></th><th>10/20/26</th><th>10/27/26</th><th>11/03/26</th><th>week ago</th><th>year ago</th></tr>
<tr><td>U.S.</td><td>3.70</td><td>3.75</td><td>3.80</td><td>0.05</td><td>0.10</td></tr>
<tr><td>East Coast (PADD1)</td><td>3.8</td><td>3.85</td><td>3.9</td><td>0.05</td><td>0.1</td></tr>
<tr><td>New England (PADD1A)</td><td>3.9</td><td>3.95</td><td>4.00</td><td>0.05</td><td>0.1</td></tr>
<tr><td>Central Atlantic (PADD1B)</td><td>3.9</td><td>3.92</td><td>3.95</td><td>0.03</td><td>0.1</td></tr>
<tr><td>Lower Atlantic (PADD1C)</td><td>3.6</td><td>3.65</td><td>3.7</td><td>0.05</td><td>0.1</td></tr>
<tr><td>Midwest (PADD2)</td><td>3.6</td><td>3.62</td><td>3.66</td><td>0.04</td><td>0.1</td></tr>
<tr><td>Gulf Coast (PADD3)</td><td>3.4</td><td>3.45</td><td>3.50</td><td>0.05</td><td>0.1</td></tr>
<tr><td>Rocky Mountain (PADD4)</td><td>3.7</td><td>3.72</td><td>3.75</td><td>0.03</td><td>0.1</td></tr>
<tr><td>West Coast (PADD5)</td><td>4.3</td><td>4.35</td><td>4.40</td><td>0.05</td><td>0.1</td></tr>
<tr><td>West Coast less California</td><td>4.0</td><td>4.05</td><td>4.10</td><td>0.05</td><td>0.1</td></tr>
<tr><td>California</td><td>4.8</td><td>4.85</td><td>4.90</td><td>0.05</td><td>0.1</td></tr></table></body></html>"""
wk, cur, pwk, prv, dbg = fm.parse_eia_page(EIA_HTML)
check("EIA page: diesel table and latest week", wk == "2026-11-03" and pwk == "2026-10-27" and cur["US"] == 3.80 and prv["US"] == 3.75)
check("EIA page: regions told apart", cur["5XCA"] == 4.10 and cur["CA"] == 4.90 and cur["5"] == 4.40 and cur["1A"] == 4.00)
# headings ambiguous (both tables under the same title): the higher-priced table is diesel
amb = EIA_HTML.replace("<h2>On-Highway Diesel Fuel Prices</h2>", "").replace("<h2>Retail prices for Gasoline, All Grades</h2>", "")
_w, ac, _p, _pp, adbg = fm.parse_eia_page(amb)
check("EIA page: ambiguous headings -> higher US average (diesel)", ac["US"] == 3.80 and adbg["picked_by"] == "higher US average")
try:
    fm.parse_eia_page("<table><tr><td>U.S.</td><td>3</td></tr></table>")
    check("EIA page without diesel refused", False)
except ValueError:
    check("EIA page without diesel refused", True)
check("every lower-48 state has an EIA region", all(s in fm.EIA_STATE_REGION for s in fm.CODES))
SC = ("REF_DATE,GEO,DGUID,Type of fuel,UOM,UOM_ID,SCALAR_FACTOR,SCALAR_ID,VECTOR,COORDINATE,VALUE,STATUS\n"
      "2026-08,\"Halifax, Nova Scotia\",x,Diesel fuel at self service filling stations,Cents per litre,1,units,0,v,1,170.1,\n"
      "2026-09,\"Halifax, Nova Scotia\",x,Diesel fuel at self service filling stations,Cents per litre,1,units,0,v,1,172.3,\n"
      "2026-09,\"Toronto, Ontario\",x,Diesel fuel at self service filling stations,Cents per litre,1,units,0,v,1,160.0,\n"
      "2026-09,\"Ottawa-Gatineau, Ontario part, Ontario/Quebec\",x,Diesel fuel at self service filling stations,Cents per litre,1,units,0,v,1,162.0,\n"
      "2026-09,\"Toronto, Ontario\",x,Regular unleaded gasoline at self service filling stations,Cents per litre,1,units,0,v,1,140.0,\n")
m, provs, pm, pprovs = fm.parse_statcan_fuel(SC)
check("StatCan diesel: latest month, province averages", m == "2026-09" and provs["ON"]["avg"] == 161.0 and provs["NS"]["avg"] == 172.3 and pm == "2026-08")
check("StatCan diesel: gasoline ignored, Ottawa counted in Ontario", set(provs["ON"]["cities"]) == {"Toronto", "Ottawa-Gatineau"})
now = datetime(2026, 11, 9, 15, tzinfo=timezone.utc)
dpage = mp.diesel_section({"eia_diesel": {"status": "ok", "week": wk, "prices": cur, "prev_week": pwk, "prev_prices": prv, "retrieved_at": "2026-11-09T12:00:00+00:00"},
                           "statcan_diesel": {"month": m, "provinces": provs, "prev_month": pm, "prev_provinces": pprovs, "retrieved_at": "2026-11-09T12:00:00+00:00"}}, now, ET)
check("diesel map: states and provinces priced", 'id="f-TX"' in dpage and "$3.50" in dpage and "161¢" in dpage)
check("diesel map: change periods named", "vs Oct 27" in dpage and "vs Aug" in dpage)
check("diesel map: empty -> No data", "No data yet" in mp.diesel_section({}, now, ET))

# --- Ontario CSV: wide and long layouts, garbage refused
wide = "Date,Fuel Type,Toronto West,Ottawa,Ontario Average/Moyenne provinciale\n2026-10-26,Diesel,165.2,166.0,164.9\n2026-11-02,Diesel,167.0,166.4,165.8\n2026-11-02,Regular Unleaded Gasoline,139.1,140.2,139.9\n"
w, prices, pw, pp = fm.parse_ontario(wide)
check("Ontario wide layout", w == "2026-11-02" and prices["Toronto West"] == 167.0 and pp["Ottawa"] == 166.0)
long = "date,fuel_type,market,price\n11/02/2026,Diesel,Sudbury,170.3\n11/02/2026,Premium,Sudbury,180.0\n"
w, prices, _, _ = fm.parse_ontario(long)
check("Ontario long layout", w == "2026-11-02" and prices == {"Sudbury": 170.3})
try:
    fm.parse_ontario("a,b,c\n1,2,3\n")
    check("unknown Ontario layout refused", False)
except ValueError:
    check("unknown Ontario layout refused", True)

# --- page
now = datetime(2026, 11, 9, 15, tzinfo=timezone.utc)
check("fresh week not stale", not mp.is_stale("2026-11-03", now))
check("old week is stale", mp.is_stale("2026-10-20", now))
empty = mp.body({}, now, ET)
check("no data -> 'No data yet' on every official card", empty.count("No data yet.") >= 4)
check("reader sections present", all(x in empty for x in ('id="chk"', 'id="poll"', 'id="rep"', 'id="r-ON"', 'id="r-TX"', 'Step deck')))
full = mp.body({"usda_reefer": dict(good, last_attempt_at=good["retrieved_at"], source_url=fm.USDA_PAGE),
                "ontario_diesel": {}, "eia_diesel": {"status": "no_key"}}, now, ET)
check("USDA produce section no longer on the page", "Produce reefer trucks" not in full)
page = mp.reefer_section(dict(good, last_attempt_at=good["retrieved_at"], source_url=fm.USDA_PAGE), now, ET) + full
check("page labels produce/reefer", "Not dry van, flatbed or general freight" in page)
check("Canada says no data for USDA", "Canada: no data in this report" in page)
check("map has accessible label and table", 'role="img"' in page and "<caption" in page)
check("no confusing cross-border box", "Mexico → US" not in page)
check("unmapped district listed, not guessed", "Somewhere Odd" in page.split("Not shown on the map")[1][:200])
check("rate type and currency stated", "US dollars per load" in page and "fuel surcharge" in page)
check("'hot' explained", "Red means trucks are short" in page)
check("external sources are links only, no Truckstop link", "DAT Trendlines" in full and "truckstop" not in full.lower() and "<iframe" not in full)
stale_page = mp.reefer_section(dict(good, week_ending="2026-10-01", last_error="x", last_attempt_at=good["retrieved_at"]), now, ET)
check("stale badge and failed-update notice", "Stale:" in stale_page and "showing the last good data" in stale_page)
levels = mp.state_levels(origins)
check("state coloured by tightest district", levels["FL"][0] == 5 and levels["CA"][0] == 3)
check("Mexico-only crossing not painted on US map", all(s in fm.CODES for s in levels))

# --- official indicators
pts = fm.parse_bls({"status": "REQUEST_SUCCEEDED", "Results": {"series": [{"seriesID": "PCU484121484121", "data": [
    {"year": "2026", "period": "M09", "value": "118.4"}, {"year": "2026", "period": "M08", "value": "117.7"},
    {"year": "2025", "period": "M13", "value": "110"}, {"year": "2026", "period": "M07", "value": "-"}]}]}}, "PCU484121484121")
check("BLS parsed, annual average and blanks skipped", sorted(pts) == [("2026-08", 117.7), ("2026-09", 118.4)])
st = fm.series_store({}, pts, "x")
check("series keeps latest and previous", st["value"] == 118.4 and st["prev"] == 117.7 and st["period"] == "2026-09")
sc = 'REF_DATE,GEO,DGUID,Service,UOM,UOM_ID,SCALAR_FACTOR,VALUE,STATUS\n2026-08,Canada,x,Total for-hire trucking,Index,1,units,124.1,\n2026-09,Canada,x,Total for-hire trucking,Index,1,units,124.7,\n2026-09,Canada,x,Local trucking,Index,1,units,130.0,\n2026-09,Ontario,x,Total for-hire trucking,Index,1,units,99,\n'
spts, label = fm.parse_statcan(sc)
check("StatCan: Canada total series picked", spts == [("2026-08", 124.1), ("2026-09", 124.7)] and "Total" in label)
check("BTS parsed", fm.parse_bts([{"date": "2026-09-01T00:00:00.000", "trucks": "498210"}, {"bad": 1}]) == [("2026-09", 498210.0)])
card = mp.gov_card("T", "D", st, lambda v: "%.1f" % v, "src", now, ET)
check("gov card shows value and change from the named month", "118.4" in card and "0.6% from Aug 2026" in card)
check("gov card failure keeps old value with notice", "update failed" in mp.gov_card("T", "D", dict(st, last_error="x"), lambda v: "%.1f" % v, "src", now, ET))

print("\n%d failed" % len(failures) if failures else "\nAll market tests passed.")
sys.exit(1 if failures else 0)
