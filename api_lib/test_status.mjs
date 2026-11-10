// Tests for the masthead status: node api_lib/test_status.mjs
import { judge, etTime, delayAfterMinutes, statusResponse } from "./status.js";
let failed = 0;
const check = (n, c) => { console.log((c ? "ok   " : "FAIL ") + n); if (!c) failed++; };
const now = new Date("2026-11-10T14:52:00Z"); // 9:52 AM EST
const base = (min, extra = {}) => ({ interval_minutes: 15, news: { last_success: new Date(now - min * 60000).toISOString(), result: "ok", sources_ok: 20, sources_total: 24, ...extra }, summaries: { state: "off" }, social: { state: "ok" } });
check("fresh check -> UPDATING", judge(base(12), now).label === "UPDATING");
check("31 min on a 15-min schedule -> UPDATES DELAYED", judge(base(31), now).label === "UPDATES DELAYED");
check("delay keeps the last successful time, not the failed attempt", judge(base(45, { result: "failed" }), now).last_checked_et === "9:07 AM ET");
check("no data -> STATUS UNAVAILABLE", judge(null, now).label === "STATUS UNAVAILABLE" && judge({}, now).label === "STATUS UNAVAILABLE");
check("never succeeded -> delayed, not green", judge({ interval_minutes: 10, news: {} }, now).state === "delayed");
check("thresholds documented: 15->30, 10->25, 30->75", delayAfterMinutes(15) === 30 && delayAfterMinutes(10) === 25 && delayAfterMinutes(30) === 75);
check("Eastern time, standard time (EST)", etTime("2026-11-10T14:52:00Z", now) === "9:52 AM ET");
check("Eastern time, daylight time (EDT)", etTime("2026-07-01T14:52:00Z", new Date("2026-07-01T15:00:00Z")) === "10:52 AM ET");
check("earlier day includes the date", etTime("2026-11-10T03:10:00Z", now) === "Nov 9, 10:10 PM ET");
check("partial source failure shown separately", /did not answer/.test(judge(base(5, { result: "partial" }), now).detail.news) && judge(base(5, { result: "partial" }), now).label === "UPDATING");
check("AI problem does not turn news red", judge({ ...base(5), summaries: { state: "limit" } }, now).label === "UPDATING");
const res = await statusResponse({ ASSETS: { fetch: async () => new Response(JSON.stringify(base(5))) } }, now);
check("endpoint: no-store cache header", res.headers.get("cache-control").includes("no-store"));
check("endpoint: server judged UPDATING", (await res.json()).label === "UPDATING");
check("endpoint: missing file -> unavailable", (await (await statusResponse({ ASSETS: { fetch: async () => new Response("", { status: 404 }) } }, now)).json()).label === "STATUS UNAVAILABLE");
console.log(failed ? `\n${failed} failed` : "\nAll status tests passed.");
process.exit(failed ? 1 : 0);
