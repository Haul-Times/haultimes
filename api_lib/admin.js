// Private admin panel for haultimes.com/admin/ — submissions, visitors and the raw report data.
// Protected by a password stored only in Cloudflare (Pages > Settings > Variables and Secrets > ADMIN_PASSWORD).
import { ensureSchema, voterCode, bump, summary, EQUIPMENT, weekOf } from "./market.js";

const NOINDEX = { "x-robots-tag": "noindex, nofollow", "cache-control": "no-store", "referrer-policy": "no-referrer" };
const json = (b, s = 200) => new Response(JSON.stringify(b), { status: s, headers: { "content-type": "application/json; charset=utf-8", ...NOINDEX } });
const daysAgo = (now, n) => new Date(now.getTime() - n * 864e5).toISOString().slice(0, 10);

function sameText(a, b) {          // compare without leaking length/position through timing
  const x = new TextEncoder().encode(a), y = new TextEncoder().encode(b);
  let diff = x.length ^ y.length;
  for (let i = 0; i < Math.max(x.length, y.length); i++) diff |= (x[i] || 0) ^ (y[i] || 0);
  return diff === 0;
}

/** null when the visitor may enter, otherwise the Response to send back. */
export async function guard(request, env, db, now) {
  if (!env.ADMIN_PASSWORD) {
    return new Response("Admin panel is not set up yet: add an ADMIN_PASSWORD secret in Cloudflare Pages settings.", { status: 503, headers: NOINDEX });
  }
  const ip = request.headers.get("cf-connecting-ip") || "unknown";
  const who = await voterCode(db, ip, now);
  const h = request.headers.get("authorization") || "";
  let pass = null;
  if (h.startsWith("Basic ")) {
    try { pass = atob(h.slice(6)).split(":").slice(1).join(":"); } catch (e) { pass = null; }
  }
  if (pass !== null && sameText(pass, env.ADMIN_PASSWORD)) return null;
  if (pass !== null && (await bump(db, "login:" + who, now)) > 10) {
    return new Response("Too many wrong passwords. Try again in an hour.", { status: 429, headers: NOINDEX });
  }
  return new Response("Password required.", { status: 401, headers: { "www-authenticate": 'Basic realm="HaulTimes admin", charset="UTF-8"', ...NOINDEX } });
}

const all = async (db, sql, ...a) => (await db.prepare(sql).bind(...a).all()).results;
const one = async (db, sql, ...a) => (await db.prepare(sql).bind(...a).first()) || {};

export async function stats(db, now) {
  const today = daysAgo(now, 0), d7 = daysAgo(now, 6), d30 = daysAgo(now, 29);
  const week = weekOf(now), lastWeek = weekOf(new Date(now.getTime() - 7 * 864e5));
  const rateCount = async (since) => (await one(db, "SELECT COUNT(*) AS n, COUNT(DISTINCT voter) AS p FROM rates WHERE substr(created,1,10) >= ?", since));
  const [rToday, r7, r30, rAll] = [await rateCount(today), await rateCount(d7), await rateCount(d30), await one(db, "SELECT COUNT(*) AS n, SUM(hidden) AS h FROM rates")];
  const pollCount = async (w) => await one(db, "SELECT COUNT(*) AS n, COUNT(DISTINCT voter) AS p FROM polls WHERE week = ?", w);
  const [pThis, pLast, pAll] = [await pollCount(week), await pollCount(lastWeek), await one(db, "SELECT COUNT(*) AS n FROM polls")];

  const daily = {};
  for (let i = 29; i >= 0; i--) daily[daysAgo(now, i)] = { day: daysAgo(now, i), rates: 0, polls: 0, views: 0, visitors: 0 };
  for (const r of await all(db, "SELECT substr(created,1,10) AS day, COUNT(*) AS n FROM rates WHERE substr(created,1,10) >= ? GROUP BY day", d30)) if (daily[r.day]) daily[r.day].rates = r.n;
  for (const r of await all(db, "SELECT substr(created,1,10) AS day, COUNT(*) AS n FROM polls WHERE substr(created,1,10) >= ? GROUP BY day", d30)) if (daily[r.day]) daily[r.day].polls = r.n;
  for (const r of await all(db, "SELECT day, SUM(n) AS n FROM views WHERE day >= ? GROUP BY day", d30)) if (daily[r.day]) daily[r.day].views = r.n;
  for (const r of await all(db, "SELECT day, COUNT(*) AS n FROM visitors WHERE day >= ? GROUP BY day", d30)) if (daily[r.day]) daily[r.day].visitors = r.n;
  const series = Object.values(daily);
  const sum = (k, from) => series.filter((d) => d.day >= from).reduce((s, d) => s + d[k], 0);

  const s = await summary(db, "all", now);
  const perEq = {};
  for (const eq of Object.keys(EQUIPMENT)) {
    const e = await summary(db, eq, now);
    perEq[eq] = { areas: Object.values(e.regions).filter((r) => r.level).length, lanes: e.lanes.length };
  }
  return {
    now: now.toISOString(),
    submissions: {
      rates_today: rToday.n, rates_7d: r7.n, rates_30d: r30.n, rates_all: rAll.n, rates_hidden: rAll.h || 0,
      rate_people_7d: r7.p, polls_this_week: pThis.n, polls_last_week: pLast.n, polls_all: pAll.n, poll_people_this_week: pThis.p,
    },
    visits: {
      views_today: sum("views", today), // (share clicks are stored with views but listed separately) views_7d: sum("views", d7), views_30d: sum("views", d30),
      visitors_today: daily[today].visitors, visitors_7d_daily_sum: sum("visitors", d7),
      market_views_7d: (await one(db, "SELECT SUM(n) AS n FROM views WHERE day >= ? AND path = '/freight-market/'", d7)).n || 0,
      top_pages: await all(db, "SELECT path, SUM(n) AS n FROM views WHERE day >= ? AND path NOT LIKE '/~share/%' GROUP BY path ORDER BY n DESC LIMIT 15", d7),
      shares: await all(db, "SELECT substr(path, 9) AS net, SUM(n) AS n FROM views WHERE day >= ? AND path LIKE '/~share/%' GROUP BY net ORDER BY n DESC", d7),
      top_refs: await all(db, "SELECT host, SUM(n) AS n FROM refs WHERE day >= ? GROUP BY host ORDER BY n DESC LIMIT 12", d7),
    },
    coverage: { lanes_shown: s.lanes.length, lanes_waiting: s.lanes_waiting, areas_shown: Object.values(s.regions).filter((r) => r.level).length, by_equipment: perEq },
    busiest: await all(db, "SELECT voter, COUNT(*) AS n, COUNT(DISTINCT o || d) AS lanes FROM rates WHERE substr(created,1,10) >= ? GROUP BY voter ORDER BY n DESC LIMIT 10", d7),
    series,
  };
}

const RATE_COLS = "id, created, load_date, o, d, market, equipment, amount, currency, miles, rpm, rpm_usd, rpm_cad, voter, hidden";

export async function listRates(db, q) {
  const where = ["1=1"], args = [];
  if (EQUIPMENT[q.eq]) { where.push("equipment = ?"); args.push(q.eq); }
  if (["US", "CA", "XB"].includes(q.market)) { where.push("market = ?"); args.push(q.market); }
  if (/^[A-Z]{2}$/.test(q.o || "")) { where.push("o = ?"); args.push(q.o); }
  if (/^[A-Z]{2}$/.test(q.d || "")) { where.push("d = ?"); args.push(q.d); }
  if (/^[0-9a-f]{4,24}$/.test(q.voter || "")) { where.push("voter LIKE ?"); args.push(q.voter + "%"); }
  if (q.hidden === "1") where.push("hidden = 1");
  const days = Math.min(Math.max(parseInt(q.days || "30", 10) || 30, 1), 3650);
  where.push("substr(created,1,10) >= ?"); args.push(new Date(Date.now() - days * 864e5).toISOString().slice(0, 10));
  const offset = Math.max(parseInt(q.offset || "0", 10) || 0, 0);
  const total = (await one(db, `SELECT COUNT(*) AS n FROM rates WHERE ${where.join(" AND ")}`, ...args)).n;
  const rows = await all(db, `SELECT ${RATE_COLS} FROM rates WHERE ${where.join(" AND ")} ORDER BY created DESC LIMIT 100 OFFSET ?`, ...args, offset);
  return { total, offset, rows };
}

export async function listPolls(db, week) {
  return { week, rows: await all(db, "SELECT region, equipment, SUM(answer = 1) AS hot, SUM(answer = 0) AS normal, SUM(answer = -1) AS slow, COUNT(*) AS n FROM polls WHERE week = ? GROUP BY region, equipment ORDER BY n DESC", week) };
}

function toCsv(rows) {
  if (!rows.length) return "";
  const cols = Object.keys(rows[0]);
  const cell = (v) => (v == null ? "" : /[",\n]/.test(String(v)) ? '"' + String(v).replace(/"/g, '""') + '"' : String(v));
  return cols.join(",") + "\n" + rows.map((r) => cols.map((c) => cell(r[c])).join(",")).join("\n") + "\n";
}

export async function handleAdmin(request, env, page, now = new Date()) {
  if (!env || !env.DB) return new Response("Reader reports are not switched on yet (no D1 database bound as DB).", { status: 503, headers: NOINDEX });
  const db = env.DB;
  await ensureSchema(db);
  const denied = await guard(request, env, db, now);
  if (denied) return denied;
  const url = new URL(request.url);
  const path = url.pathname.replace(/^\/admin\/?/, "").replace(/\/$/, "");
  const q = Object.fromEntries(url.searchParams);
  if (path === "" ) return new Response(page, { headers: { "content-type": "text/html; charset=utf-8", ...NOINDEX } });
  if (path === "api/stats") return json(await stats(db, now));
  if (path === "api/rates") return json(await listRates(db, q));
  if (path === "api/polls") return json(await listPolls(db, /^\d{4}-\d{2}-\d{2}$/.test(q.week || "") ? q.week : weekOf(now)));
  if (path === "api/hide" && request.method === "POST") {
    const b = await request.json().catch(() => ({}));
    const id = parseInt(b.id, 10);
    if (!id) return json({ ok: false }, 400);
    await db.prepare("UPDATE rates SET hidden = ? WHERE id = ?").bind(b.hidden ? 1 : 0, id).run();
    return json({ ok: true });
  }
  if (path === "api/export") {
    const table = q.table === "polls" ? "polls" : q.table === "views" ? "views" : "rates";
    const rows = await all(db, `SELECT * FROM ${table} ORDER BY rowid`);
    return new Response(toCsv(rows), { headers: { "content-type": "text/csv; charset=utf-8",
      "content-disposition": `attachment; filename="haultimes-${table}-${now.toISOString().slice(0, 10)}.csv"`, ...NOINDEX } });
  }
  return json({ ok: false, error: "Not found." }, 404);
}
