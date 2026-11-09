// Reader-reported freight market for haultimes.com/freight-market/.
// Runs as a Cloudflare Pages Function with a D1 database bound as DB.
//
// Privacy: no names, emails, IP addresses or exact locations are stored. Each report carries only a
// one-way code made from the visitor's IP and a secret that changes every week, so repeat answers in
// the same week can be spotted but nobody can be traced across weeks or identified.

export const EQUIPMENT = { van: "Dry van", reefer: "Reefer", flatbed: "Flatbed", stepdeck: "Step deck" };
export const US = ["AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA","KS","KY","LA","ME","MD","MA",
  "MI","MN","MS","MO","MT","NE","NV","NH","NJ","NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT",
  "VA","WA","WV","WI","WY"];
export const CA = ["AB","BC","MB","NB","NL","NS","NT","NU","ON","PE","QC","SK","YT"];
export const MIN_REPORTS = 5;      // a region or lane is shown only with at least this many reports...
export const MIN_PEOPLE = 3;       // ...from at least this many different people
export const PER_PERSON = 2;       // at most this many of one person's reports count per lane
export const BOUNDS = { USD: [0.75, 12], CAD: [1.0, 16] }; // plausible all-in rate per mile

const SCHEMA = [
  "CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)",
  "CREATE TABLE IF NOT EXISTS polls (id INTEGER PRIMARY KEY, week TEXT, region TEXT, equipment TEXT, answer INTEGER, voter TEXT, created TEXT, UNIQUE(week, equipment, region, voter))",
  "CREATE TABLE IF NOT EXISTS rates (id INTEGER PRIMARY KEY, created TEXT, load_date TEXT, o TEXT, d TEXT, market TEXT, equipment TEXT, amount REAL, currency TEXT, miles REAL, rpm REAL, rpm_usd REAL, rpm_cad REAL, voter TEXT, hidden INTEGER DEFAULT 0)",
  "CREATE INDEX IF NOT EXISTS rates_lane ON rates (equipment, o, d, load_date)",
  "CREATE INDEX IF NOT EXISTS polls_week ON polls (week, equipment)",
  // rate limits and the site's own visit counter (no cookies; visitor codes change every week)
  "CREATE TABLE IF NOT EXISTS hits (k TEXT, hour TEXT, n INTEGER, PRIMARY KEY (k, hour))",
  "CREATE TABLE IF NOT EXISTS views (day TEXT, path TEXT, n INTEGER, PRIMARY KEY (day, path))",
  "CREATE TABLE IF NOT EXISTS visitors (day TEXT, voter TEXT, PRIMARY KEY (day, voter))",
  "CREATE TABLE IF NOT EXISTS refs (day TEXT, host TEXT, n INTEGER, PRIMARY KEY (day, host))",
];
export const CHECK_LIMIT = 30;   // rate checks per visitor per hour: plenty for a driver, useless for a scraper

// ------------------------------------------------------------------ pure helpers (unit tested)

export const country = (r) => (US.includes(r) ? "US" : CA.includes(r) ? "CA" : null);
export function market(o, d) {
  const a = country(o), b = country(d);
  if (!a || !b) return null;
  return a === b ? a : "XB";
}
export const laneCurrency = (m) => (m === "CA" ? "CAD" : "USD");

export function weekOf(date) {          // Monday of the week, UTC, as YYYY-MM-DD
  const d = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()));
  d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7));
  return d.toISOString().slice(0, 10);
}
const daysAgo = (now, n) => new Date(now.getTime() - n * 864e5).toISOString().slice(0, 10);

export function quantile(sorted, q) {
  if (!sorted.length) return null;
  const pos = (sorted.length - 1) * q, lo = Math.floor(pos), hi = Math.ceil(pos);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}

/** Limit each person's influence, then require enough reports from enough people. */
export function laneStats(rows, valueKey) {
  const byVoter = {};
  for (const r of [...rows].sort((a, b) => (a.created < b.created ? 1 : -1))) {
    (byVoter[r.voter] = byVoter[r.voter] || []).push(r);
  }
  const kept = Object.values(byVoter).flatMap((list) => list.slice(0, PER_PERSON));
  const vals = kept.map((r) => r[valueKey]).filter((v) => typeof v === "number" && isFinite(v)).sort((a, b) => a - b);
  const people = Object.keys(byVoter).length;
  if (vals.length < MIN_REPORTS || people < MIN_PEOPLE) return { n: vals.length, people, enough: false };
  const r2 = (x) => Math.round(x * 100) / 100;
  return { n: vals.length, people, enough: true, median: r2(quantile(vals, 0.5)), p25: r2(quantile(vals, 0.25)), p75: r2(quantile(vals, 0.75)) };
}

/** Hot / normal / slow for a region from one-tap answers (+1 hot, 0 normal, -1 slow). */
export function pollLevel(answers) {
  const n = answers.length;
  if (n < MIN_REPORTS) return { n, level: null };
  const score = answers.reduce((s, a) => s + a, 0) / n;
  const count = (v) => answers.filter((a) => a === v).length;
  return { n, hot: count(1), normal: count(0), slow: count(-1), level: score >= 0.25 ? "hot" : score <= -0.25 ? "slow" : "normal" };
}

export function verdict(offer, s) {
  if (!s || !s.enough || !offer) return null;
  if (offer < s.p25) return "low";
  if (offer > s.p75) return "high";
  return "usual";
}

/** Check and normalise a submitted rate. Returns {ok, row} or {ok:false, error}. */
export function validateRate(b, now, fx) {
  const o = String(b.o || "").toUpperCase(), d = String(b.d || "").toUpperCase();
  const m = market(o, d);
  if (!m) return { ok: false, error: "Pick the pickup and delivery state or province." };
  if (!EQUIPMENT[b.equipment]) return { ok: false, error: "Pick the equipment." };
  const amount = Number(String(b.amount ?? "").replace(/[$,\s]/g, ""));
  let miles = Number(String(b.distance ?? "").replace(/[,\s]/g, ""));
  if (b.unit === "km") miles = miles / 1.609344;
  const currency = b.currency === "CAD" ? "CAD" : b.currency === "USD" ? "USD" : null;
  if (!currency) return { ok: false, error: "Pick the currency." };
  if (!(amount >= 100 && amount <= 30000)) return { ok: false, error: "Enter the total rate for the load, e.g. 2250." };
  if (!(miles >= 25 && miles <= 3500)) return { ok: false, error: "Enter the loaded distance (25 to 3,500 miles)." };
  const date = String(b.date || "");
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || date > daysAgo(now, -1) || date < daysAgo(now, 14))
    return { ok: false, error: "The load date must be within the last 14 days." };
  const rpm = amount / miles;
  const [lo, hi] = BOUNDS[currency];
  if (rpm < lo || rpm > hi) return { ok: false, error: `That works out to ${rpm.toFixed(2)} per mile, which looks off. Check the rate and distance.` };
  const rpm_usd = currency === "USD" ? rpm : fx ? rpm / fx : null;   // fx = CAD per 1 USD
  const rpm_cad = currency === "CAD" ? rpm : fx ? rpm * fx : null;
  return { ok: true, row: { load_date: date, o, d, market: m, equipment: b.equipment, amount, currency, miles: Math.round(miles), rpm, rpm_usd, rpm_cad } };
}

// ------------------------------------------------------------------ database

const ready = new WeakSet();
export async function ensureSchema(db) {
  if (ready.has(db)) return;
  for (const sql of SCHEMA) await db.prepare(sql).run();
  ready.add(db);
}

/** Count one use of `key` this hour; returns the new count. */
export async function bump(db, key, now) {
  const hour = now.toISOString().slice(0, 13);
  await db.prepare("INSERT INTO hits (k, hour, n) VALUES (?, ?, 1) ON CONFLICT(k, hour) DO UPDATE SET n = n + 1").bind(key, hour).run();
  if (Math.random() < 0.02) // tidy up old counters now and then
    await db.prepare("DELETE FROM hits WHERE hour < ?").bind(new Date(now.getTime() - 2 * 864e5).toISOString().slice(0, 13)).run();
  const r = await db.prepare("SELECT n FROM hits WHERE k = ? AND hour = ?").bind(key, hour).first();
  return r ? r.n : 1;
}

const BOT = /bot|crawl|spider|slurp|facebookexternalhit|preview|headless|python|curl|wget|httpclient|scrapy/i;

/** The site's own page-view counter: page, day, unique visitors per day, where they came from. */
export async function countView(db, body, voter, ua, now) {
  if (!ua || BOT.test(ua)) return;
  let path = String(body.p || "/").split("?")[0].slice(0, 160);
  if (!path.startsWith("/") || path.startsWith("/admin")) return;
  const day = now.toISOString().slice(0, 10);
  let host = "";
  try { host = body.r ? new URL(body.r).hostname.replace(/^www\./, "") : ""; } catch (e) { host = ""; }
  if (host === "haultimes.com") host = "";
  await db.prepare("INSERT INTO views (day, path, n) VALUES (?, ?, 1) ON CONFLICT(day, path) DO UPDATE SET n = n + 1").bind(day, path).run();
  await db.prepare("INSERT OR IGNORE INTO visitors (day, voter) VALUES (?, ?)").bind(day, voter).run();
  await db.prepare("INSERT INTO refs (day, host, n) VALUES (?, ?, 1) ON CONFLICT(day, host) DO UPDATE SET n = n + 1").bind(day, host || "(direct or unknown)").run();
}

async function meta(db, k) {
  const r = await db.prepare("SELECT v FROM meta WHERE k = ?").bind(k).first();
  return r ? r.v : null;
}
async function setMeta(db, k, v) {
  await db.prepare("INSERT INTO meta (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v").bind(k, v).run();
}

export async function voterCode(db, ip, now) {
  let salt = await meta(db, "salt");
  if (!salt) {
    salt = [...crypto.getRandomValues(new Uint8Array(24))].map((x) => x.toString(16).padStart(2, "0")).join("");
    await setMeta(db, "salt", salt);
  }
  const data = new TextEncoder().encode(`${ip}|${salt}|${weekOf(now)}`);
  const hash = await crypto.subtle.digest("SHA-256", data);
  return [...new Uint8Array(hash)].slice(0, 12).map((x) => x.toString(16).padStart(2, "0")).join("");
}

/** CAD per USD from the Bank of Canada, refreshed daily, last good value kept. */
export async function usdcad(db, now, fetchFn = fetch) {
  const saved = JSON.parse((await meta(db, "fx")) || "null");
  if (saved && saved.checked === now.toISOString().slice(0, 10)) return saved.rate;
  try {
    const r = await fetchFn("https://www.bankofcanada.ca/valet/observations/FXUSDCAD/json?recent=1");
    const j = await r.json();
    const rate = Number(j.observations[0].FXUSDCAD.v);
    if (rate > 0.8 && rate < 2.5) {
      await setMeta(db, "fx", JSON.stringify({ rate, date: j.observations[0].d, checked: now.toISOString().slice(0, 10) }));
      return rate;
    }
  } catch (e) { /* keep the last good rate */ }
  return saved ? saved.rate : null;
}

export async function addPoll(db, body, voter, now) {
  const region = String(body.region || "").toUpperCase();
  const answer = Number(body.answer);
  if (!country(region)) return { ok: false, error: "Pick your state or province." };
  if (!EQUIPMENT[body.equipment]) return { ok: false, error: "Pick the equipment." };
  if (![1, 0, -1].includes(answer)) return { ok: false, error: "Choose busy, normal or slow." };
  // One answer per person, equipment and region each week; answering again replaces it.
  await db.prepare(`INSERT INTO polls (week, region, equipment, answer, voter, created) VALUES (?, ?, ?, ?, ?, ?)
    ON CONFLICT(week, equipment, region, voter) DO UPDATE SET answer = excluded.answer, created = excluded.created`)
    .bind(weekOf(now), region, body.equipment, answer, voter, now.toISOString()).run();
  return { ok: true };
}

export async function addRate(db, body, voter, now, fx) {
  const v = validateRate(body, now, fx);
  if (!v.ok) return v;
  const recent = await db.prepare("SELECT COUNT(*) AS c FROM rates WHERE voter = ? AND created > ?")
    .bind(voter, new Date(now.getTime() - 864e5).toISOString()).first();
  if (recent && recent.c >= 10) return { ok: false, error: "Thanks! You've reached today's limit of 10 reports." };
  const r = v.row;
  await db.prepare(`INSERT INTO rates (created, load_date, o, d, market, equipment, amount, currency, miles, rpm, rpm_usd, rpm_cad, voter)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`)
    .bind(now.toISOString(), r.load_date, r.o, r.d, r.market, r.equipment, r.amount, r.currency, r.miles, r.rpm, r.rpm_usd, r.rpm_cad, voter).run();
  return { ok: true, rpm: Math.round(r.rpm * 100) / 100, currency: r.currency };
}

const valueKey = (m) => (laneCurrency(m) === "CAD" ? "rpm_cad" : "rpm_usd");

export async function summary(db, eq, now) {
  const week = weekOf(now);
  const eqSql = EQUIPMENT[eq] ? " AND equipment = ?" : "";
  const eqArgs = EQUIPMENT[eq] ? [eq] : [];

  const polls = (await db.prepare(`SELECT region, answer FROM polls WHERE week = ?${eqSql}`).bind(week, ...eqArgs).all()).results;
  const byRegion = {};
  for (const p of polls) (byRegion[p.region] = byRegion[p.region] || []).push(p.answer);
  const regions = {};
  for (const [k, list] of Object.entries(byRegion)) regions[k] = pollLevel(list);

  const since = daysAgo(now, 14);
  const rows = (await db.prepare(`SELECT o, d, market, equipment, rpm_usd, rpm_cad, voter, created, load_date FROM rates WHERE hidden = 0 AND load_date >= ?${eqSql}`)
    .bind(since, ...eqArgs).all()).results;
  const cut = daysAgo(now, 7);
  const groups = {};
  for (const r of rows) {
    const k = `${r.o}|${r.d}|${r.equipment}`;
    (groups[k] = groups[k] || { o: r.o, d: r.d, market: r.market, equipment: r.equipment, cur: [], prev: [] })[r.load_date >= cut ? "cur" : "prev"].push(r);
  }
  const lanes = [];
  let waiting = 0;
  for (const g of Object.values(groups)) {
    const key = valueKey(g.market);
    const s = laneStats(g.cur, key);
    if (!s.enough) { if (g.cur.length) waiting++; continue; }
    const p = laneStats(g.prev, key);
    lanes.push({ o: g.o, d: g.d, market: g.market, equipment: g.equipment, currency: laneCurrency(g.market), ...s,
      change: p.enough ? Math.round((s.median - p.median) * 100) / 100 : null });
  }
  lanes.sort((a, b) => b.n - a.n);

  const thisWeek = rows.filter((r) => r.load_date >= cut);
  const people = new Set([...thisWeek.map((r) => r.voter)]);
  const pollPeople = (await db.prepare(`SELECT COUNT(DISTINCT voter) AS c, COUNT(*) AS n FROM polls WHERE week = ?${eqSql}`).bind(week, ...eqArgs).first());
  return {
    week, equipment: EQUIPMENT[eq] ? eq : "all", regions, lanes: lanes.slice(0, 60), lanes_waiting: waiting,
    reports: thisWeek.length + (pollPeople ? pollPeople.n : 0),
    updated: now.toISOString(),
  };
}

export async function check(db, q, now) {
  const o = String(q.o || "").toUpperCase(), d = String(q.d || "").toUpperCase();
  const m = market(o, d);
  if (!m || !EQUIPMENT[q.equipment]) return { ok: false, error: "Pick pickup, delivery and equipment." };
  const key = valueKey(m);
  const out = { ok: true, market: m, currency: laneCurrency(m) };
  for (const days of [7, 30]) {
    const rows = (await db.prepare("SELECT rpm_usd, rpm_cad, voter, created FROM rates WHERE hidden = 0 AND o = ? AND d = ? AND equipment = ? AND load_date >= ?")
      .bind(o, d, q.equipment, daysAgo(now, days)).all()).results;
    const s = laneStats(rows, key);
    if (s.enough || days === 30) { Object.assign(out, s, { days }); break; }
  }
  return out;
}

// ------------------------------------------------------------------ HTTP

const json = (body, status = 200, extra = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store", ...extra } });

export async function handle(request, env, now = new Date()) {
  const url = new URL(request.url);
  const path = url.pathname.replace(/^\/api\/?/, "").replace(/\/$/, "");
  const cf = request.cf || {};

  if (path === "where") {
    const c = cf.country, r = cf.regionCode;
    const ok = (c === "US" || c === "CA") && country(r);
    return json(ok ? { region: r, city: cf.city || null } : { region: null });
  }
  if (!env || !env.DB) return json({ ok: false, error: "not_configured" }, 503);
  const db = env.DB;
  await ensureSchema(db);

  if (request.method === "POST" && path === "hit") {
    let body = {};
    try { body = JSON.parse(await request.text()); } catch (e) { /* ignore */ }
    const voter = await voterCode(db, request.headers.get("cf-connecting-ip") || "unknown", now);
    await countView(db, body, voter, request.headers.get("user-agent") || "", now);
    return new Response(null, { status: 204 });
  }
  if (request.method === "POST" && (path === "poll" || path === "rate")) {
    if (!(request.headers.get("content-type") || "").includes("application/json")) return json({ ok: false, error: "Bad request." }, 400);
    let body;
    try { body = await request.json(); } catch { return json({ ok: false, error: "Bad request." }, 400); }
    if (body.website) return json({ ok: true }); // honeypot field only bots fill in
    const ip = request.headers.get("cf-connecting-ip") || "unknown";
    const voter = await voterCode(db, ip, now);
    const res = path === "poll" ? await addPoll(db, body, voter, now) : await addRate(db, body, voter, now, await usdcad(db, now));
    return json(res, res.ok ? 200 : 400);
  }
  if (request.method === "GET" && path === "summary") {
    return json(await summary(db, url.searchParams.get("eq") || "all", now), 200, { "cache-control": "public, max-age=120" });
  }
  if (request.method === "GET" && path === "check") {
    const voter = await voterCode(db, request.headers.get("cf-connecting-ip") || "unknown", now);
    if ((await bump(db, "check:" + voter, now)) > CHECK_LIMIT)
      return json({ ok: false, error: "You've checked a lot of lanes this hour. Please try again a little later." }, 429);
    const res = await check(db, Object.fromEntries(url.searchParams), now);
    if (res.ok) res.usdcad = await usdcad(db, now); // lets the page convert an offer made in the other currency
    return json(res, res.ok ? 200 : 400);
  }
  return json({ ok: false, error: "Not found." }, 404);
}
