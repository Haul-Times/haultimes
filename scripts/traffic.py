"""
Daily traffic numbers from Cloudflare Web Analytics, so posting frequency can be
compared with visits it brings. Saved to data/traffic.json and shown on
haultimes.com/editor/social/.

Needs two GitHub Secrets (read-only):
  CF_API_TOKEN    Cloudflare API token with "Account Analytics: Read"
  CF_ACCOUNT_ID   the Cloudflare account id
Optional: CF_SITE_TAG (found automatically for haultimes.com if left out).

Per day (UTC, as Cloudflare reports it): visits arriving from Facebook, visits from X,
HaulTimes story page views, and clicks through to publishers (/out/ pages).
Cloudflare samples these numbers, so treat them as estimates.
"""

import json
import os
import urllib.request
from datetime import datetime, timedelta, timezone

from common import load_json, save_json

API = "https://api.cloudflare.com/client/v4"
FACEBOOK_HOSTS = ("facebook.com", "m.facebook.com", "l.facebook.com", "lm.facebook.com", "www.facebook.com", "fb.me")
X_HOSTS = ("t.co", "x.com", "twitter.com", "mobile.twitter.com", "www.x.com")

QUERY = """query HaulTimesTraffic($accountTag: string!, $filter: AccountRumPageloadEventsAdaptiveGroupsFilter_InputObject) {
  viewer { accounts(filter: {accountTag: $accountTag}) {
    rumPageloadEventsAdaptiveGroups(filter: $filter, limit: 10000) {
      count
      dimensions { date refererHost requestPath }
    }
  } }
}"""


def _call(method, url, token, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": "Bearer " + token, "Content-Type": "application/json", "User-Agent": "HaulTimes/1.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read())


def site_tag(token, account, host="haultimes.com"):
    res = _call("GET", "%s/accounts/%s/rum/site_info/list" % (API, account), token)
    for site in res.get("result", []):
        if host in (site.get("host") or "") or host in json.dumps(site.get("ruleset") or {}):
            return site.get("site_tag")
    return None


def summarize(rows):
    """Cloudflare rows -> {date: {from_facebook, from_x, story_views, outbound, page_views}}."""
    days = {}
    for row in rows:
        d = row["dimensions"]["date"]
        host = (row["dimensions"].get("refererHost") or "").lower()
        path = row["dimensions"].get("requestPath") or ""
        n = int(row.get("count") or 0)
        day = days.setdefault(d, {"from_facebook": 0, "from_x": 0, "story_views": 0, "outbound": 0, "page_views": 0})
        day["page_views"] += n
        if host in FACEBOOK_HOSTS or host.endswith(".facebook.com"):
            day["from_facebook"] += n
        if host in X_HOSTS:
            day["from_x"] += n
        if path.startswith("/story/"):
            day["story_views"] += n
        if path.startswith("/out/"):
            day["outbound"] += n
    return days


def update(now=None, env=None, every_minutes=60):
    """Refresh at most once an hour. Returns the saved data (possibly unchanged)."""
    env = env if env is not None else os.environ
    now = now or datetime.now(timezone.utc)
    data = load_json("traffic.json", {"days": {}})
    token, account = env.get("CF_API_TOKEN"), env.get("CF_ACCOUNT_ID")
    if not token or not account:
        data["status"] = "Cloudflare token not set up"
        return data
    if data.get("fetched_at") and now - datetime.fromisoformat(data["fetched_at"]) < timedelta(minutes=every_minutes):
        return data
    tag = env.get("CF_SITE_TAG") or data.get("site_tag") or site_tag(token, account)
    if not tag:
        data["status"] = "haultimes.com not found in Cloudflare Web Analytics"
        return data
    flt = {"AND": [{"datetime_geq": (now - timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "datetime_leq": now.strftime("%Y-%m-%dT%H:%M:%SZ")}, {"siteTag": tag}]}
    res = _call("POST", API + "/graphql", token, {"query": QUERY, "variables": {"accountTag": account, "filter": flt}})
    if res.get("errors"):
        data["status"] = "Cloudflare error: %s" % str(res["errors"][0].get("message", ""))[:200]
        save_json("traffic.json", data)
        return data
    rows = res["data"]["viewer"]["accounts"][0]["rumPageloadEventsAdaptiveGroups"]
    data.update(days=summarize(rows), fetched_at=now.isoformat(), site_tag=tag, status="ok")
    save_json("traffic.json", data)
    return data
