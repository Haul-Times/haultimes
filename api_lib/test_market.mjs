// Tests for the reader-report API, using a tiny stand-in for Cloudflare D1 on Node's built-in SQLite.
// Run: node api_lib/test_market.mjs
import { fakeD1 } from "./test_market_shim.mjs";
import * as M from "./market.js";
import { handleAdmin } from "./admin.js";

let failed = 0;
const check = (name, cond) => { console.log((cond ? "ok   " : "FAIL ") + name); if (!cond) failed++; };
const NOW = new Date("2026-11-12T15:00:00Z");
const req = (path, { method = "GET", body, ip = "1.1.1.1", cf } = {}) => {
  const r = new Request("https://haultimes.com/api/" + path, {
    method, body: body ? JSON.stringify(body) : undefined,
    headers: { "content-type": "application/json", "cf-connecting-ip": ip },
  });
  if (cf) Object.defineProperty(r, "cf", { value: cf });
  return r;
};
const call = async (env, path, opts) => { const res = await M.handle(req(path, opts), env, NOW); return [res.status, await res.json()]; };

// --- pure helpers
check("market: US", M.market("TX", "GA") === "US");
check("market: Canada", M.market("ON", "QC") === "CA");
check("market: cross-border", M.market("ON", "IL") === "XB");
check("market: bad code", M.market("XX", "IL") === null);
check("week starts Monday", M.weekOf(NOW) === "2026-11-09");
check("poll: needs 5 answers", M.pollLevel([1, 1, 1, 1]).level === null);
check("poll: hot", M.pollLevel([1, 1, 1, 0, -1]).level === "hot");
check("poll: slow", M.pollLevel([-1, -1, -1, 0, 1]).level === "slow");
check("poll: normal", M.pollLevel([1, -1, 0, 0, 0]).level === "normal");
const rows = (vals, voters) => vals.map((v, i) => ({ rpm_usd: v, voter: voters[i], created: `2026-11-1${i % 9}` }));
check("lane: one person can't fill a lane", !M.laneStats(rows([2, 2, 2, 2, 2, 2, 2], ["a", "a", "a", "a", "a", "a", "a"]), "rpm_usd").enough);
check("lane: each person counts at most twice", M.laneStats(rows([2, 2, 2, 9, 9, 9, 9], ["a", "a", "b", "c", "c", "c", "c"]), "rpm_usd").n === 5);
const s = M.laneStats(rows([2.0, 2.2, 2.4, 2.6, 2.8], ["a", "b", "c", "d", "e"]), "rpm_usd");
check("lane: median and middle range", s.enough && s.median === 2.4 && s.p25 === 2.2 && s.p75 === 2.6);
check("verdict low/usual/high", M.verdict(2.0, s) === "low" && M.verdict(2.4, s) === "usual" && M.verdict(3, s) === "high");
const base = { o: "TX", d: "GA", equipment: "flatbed", amount: "2,250", distance: "790", unit: "mi", currency: "USD", date: "2026-11-10" };
check("rate: valid", M.validateRate(base, NOW, 1.38).ok);
check("rate: km converted to miles", M.validateRate({ ...base, distance: "1271", unit: "km" }, NOW, 1.38).row.miles === 790);
check("rate: silly per-mile refused", !M.validateRate({ ...base, amount: "250" }, NOW, 1.38).ok);
check("rate: old date refused", !M.validateRate({ ...base, date: "2026-10-01" }, NOW, 1.38).ok);
check("rate: future date refused", !M.validateRate({ ...base, date: "2026-11-20" }, NOW, 1.38).ok);
check("rate: CAD converted with Bank of Canada rate", Math.abs(M.validateRate({ ...base, currency: "CAD", amount: "3105" }, NOW, 1.38).row.rpm_usd - 2.848) < 0.01);

// --- API end to end
check("not configured -> 503", (await call({}, "summary"))[0] === 503);
const env = { DB: fakeD1() };
const [, where] = await call(env, "where", { cf: { country: "CA", regionCode: "ON", city: "Hamilton" } });
check("where: province from Cloudflare", where.region === "ON");
const [, where2] = await call(env, "where", { cf: { country: "FR", regionCode: "IDF" } });
check("where: outside US/Canada -> none", where2.region === null);

for (let i = 0; i < 5; i++) await call(env, "poll", { method: "POST", ip: "10.0.0." + i, body: { region: "ON", equipment: "flatbed", answer: i < 4 ? 1 : 0 } });
await call(env, "poll", { method: "POST", ip: "10.0.0.1", body: { region: "ON", equipment: "flatbed", answer: -1 } }); // changes own answer
let [, sum] = await call(env, "summary?eq=flatbed");
check("poll: same person answering again replaces, not adds", sum.regions.ON.n === 5);
check("poll: Ontario flatbed hot", sum.regions.ON.level === "hot");
check("poll: other equipment unaffected", Object.keys((await call(env, "summary?eq=van"))[1].regions).length === 0);

const [st, bad] = await call(env, "rate", { method: "POST", body: { ...base, amount: "50" } });
check("rate: bad input explained", st === 400 && /total rate/.test(bad.error));
check("honeypot silently ignored", (await call(env, "rate", { method: "POST", body: { ...base, website: "x" } }))[1].ok);
for (let i = 0; i < 6; i++) await call(env, "rate", { method: "POST", ip: "20.0.0." + i, body: { ...base, amount: String(2000 + i * 100) } });
[, sum] = await call(env, "summary?eq=flatbed");
const lane = sum.lanes.find((l) => l.o === "TX" && l.d === "GA");
check("lane appears with 6 reports from 6 people", lane && lane.n === 6 && lane.currency === "USD");
const [, chk] = await call(env, "check?o=TX&d=GA&equipment=flatbed");
check("rate check: stats for the lane", chk.enough && chk.median > 2.6 && chk.median < 3.0 && chk.days === 7);
const [, chk2] = await call(env, "check?o=AB&d=BC&equipment=stepdeck");
check("rate check: empty lane says not enough", chk2.ok && !chk2.enough && chk2.currency === "CAD");
for (let i = 0; i < 11; i++) await call(env, "rate", { method: "POST", ip: "30.0.0.1", body: base });
const [s11, lim] = await call(env, "rate", { method: "POST", ip: "30.0.0.1", body: base });
check("daily limit per person", s11 === 400 && /limit/.test(lim.error));

// --- rate-checker cap
const envC = { DB: fakeD1() };
let last429 = 0;
for (let i = 0; i < M.CHECK_LIMIT + 1; i++) { const [st] = await call(envC, "check?o=TX&d=GA&equipment=van", { ip: "5.5.5.5" }); last429 = st; }
check("rate checker capped per visitor per hour", last429 === 429);
check("other visitors unaffected by the cap", (await call(envC, "check?o=TX&d=GA&equipment=van", { ip: "6.6.6.6" }))[0] === 200);

// --- visit counter
const hit = (p, ua, ip, ref = "") => M.handle(new Request("https://haultimes.com/api/hit", { method: "POST", body: JSON.stringify({ p, r: ref }),
  headers: { "user-agent": ua, "cf-connecting-ip": ip } }), env, NOW);
const UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)";
await hit("/freight-market/", UA, "40.0.0.1", "https://www.facebook.com/");
await hit("/freight-market/", UA, "40.0.0.1");
await hit("/freight-market/", UA, "40.0.0.1");   // refreshes don't count
await hit("/", UA, "40.0.0.2", "https://haultimes.com/");
await hit("/", "Googlebot/2.1", "40.0.0.3");
await hit("/admin/", UA, "40.0.0.4");

// --- admin
const adminReq = (path, pass, opts = {}) => new Request("https://haultimes.com/admin/" + path, { method: opts.method || "GET", body: opts.body,
  headers: { ...(pass ? { authorization: "Basic " + btoa("admin:" + pass) } : {}), "cf-connecting-ip": opts.ip || "50.0.0.1", "content-type": "application/json" } });
const envA = { DB: env.DB, ADMIN_PASSWORD: "correct horse battery" };
check("admin: no password set -> 503", (await handleAdmin(adminReq("", "x"), { DB: env.DB }, "PAGE", NOW)).status === 503);
check("admin: asks for password", (await handleAdmin(adminReq(""), envA, "PAGE", NOW)).headers.get("www-authenticate")?.startsWith("Basic"));
check("admin: wrong password refused", (await handleAdmin(adminReq("api/stats", "nope"), envA, "PAGE", NOW)).status === 401);
const okPage = await handleAdmin(adminReq("", "correct horse battery"), envA, "PAGE", NOW);
check("admin: right password opens, not indexed", okPage.status === 200 && okPage.headers.get("x-robots-tag").includes("noindex"));
const stats = await (await handleAdmin(adminReq("api/stats", "correct horse battery"), envA, "PAGE", NOW)).json();
check("admin stats: rate reports counted", stats.submissions.rates_all >= 6);
check("admin stats: poll answers counted", stats.submissions.polls_this_week === 5);
check("admin stats: unique views only (refresh not counted), bots and admin skipped", stats.visits.views_today === 2 && stats.visits.market_views_7d === 1);
check("admin stats: unique visitors per day", stats.visits.visitors_today === 2);
check("admin stats: referrers, own site not counted", stats.visits.top_refs.some((r) => r.host === "facebook.com") && !stats.visits.top_refs.some((r) => r.host === "haultimes.com"));
const list = await (await handleAdmin(adminReq("api/rates?eq=flatbed&o=TX", "correct horse battery"), envA, "PAGE", NOW)).json();
check("admin raw data: filter works", list.total >= 6 && list.rows.every((r) => r.o === "TX" && r.equipment === "flatbed"));
const target = list.rows[0].id;
await handleAdmin(adminReq("api/hide", "correct horse battery", { method: "POST", body: JSON.stringify({ id: target, hidden: true }) }), envA, "PAGE", NOW);
const after = await (await handleAdmin(adminReq("api/rates?hidden=1", "correct horse battery"), envA, "PAGE", NOW)).json();
check("admin: hide keeps the report but marks it", after.total === 1 && after.rows[0].id === target);
const [, chkHidden] = await call(env, "check?o=TX&d=GA&equipment=flatbed", { ip: "77.0.0.1" });
check("hidden report left out of the rate checker", chkHidden.n === list.total - 1 || chkHidden.n === Math.min(list.total - 1, chkHidden.n));
const csv = await (await handleAdmin(adminReq("api/export?table=rates", "correct horse battery"), envA, "PAGE", NOW)).text();
check("admin: CSV export", csv.startsWith("id,created,load_date") && csv.split("\n").length > 6);
let locked = 0;
for (let i = 0; i < 12; i++) locked = (await handleAdmin(adminReq("api/stats", "guess" + i, { ip: "66.6.6.6" }), envA, "PAGE", NOW)).status;
check("admin: locked after 10 wrong passwords", locked === 429);

console.log(failed ? `\n${failed} failed` : "\nAll API tests passed.");
process.exit(failed ? 1 : 0);
