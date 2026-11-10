// Public status for the masthead badge: /api/status.
// Reads /status.json (written by each build) and judges its age by the SERVER clock, never the browser's.
// Only safe facts go out: times, counts, states. No errors, keys or logs.

const ET = "America/New_York";

export function etTime(iso, now) {
  const t = new Date(iso);
  const day = (d) => new Intl.DateTimeFormat("en-US", { timeZone: ET, year: "numeric", month: "2-digit", day: "2-digit" }).format(d);
  const clock = new Intl.DateTimeFormat("en-US", { timeZone: ET, hour: "numeric", minute: "2-digit" }).format(t);
  if (day(t) === day(now)) return `${clock} ET`;
  const md = new Intl.DateTimeFormat("en-US", { timeZone: ET, month: "short", day: "numeric" }).format(t);
  return `${md}, ${clock} ET`;
}

/** Delay threshold: 30 minutes for a 15-minute schedule; otherwise 2.5 x the interval (25 min for 10), never under 20. */
export function delayAfterMinutes(interval) {
  return interval === 15 ? 30 : Math.max(20, Math.round(2.5 * interval));
}

export function judge(s, now) {
  if (!s || !s.news || !s.interval_minutes) return { state: "unavailable", label: "STATUS UNAVAILABLE" };
  const every = s.interval_minutes;
  const last = s.news.last_success ? new Date(s.news.last_success) : null;
  const age = last ? (now - last) / 60000 : Infinity;
  const state = age <= delayAfterMinutes(every) ? "updating" : "delayed";
  const parts = {
    state,
    label: state === "updating" ? "UPDATING" : "UPDATES DELAYED",
    every,
    last_checked: last ? last.toISOString() : null,
    last_checked_et: last ? etTime(last, now) : null,
    detail: {
      news: s.news.result === "partial" ? "Some sources did not answer on the last check" :
        s.news.result === "failed" ? "The last check failed; showing the last successful one" : "All checks normal",
      sources: s.news.sources_total ? `${s.news.sources_ok} of ${s.news.sources_total} sources answered` : null,
      failing: s.news.sources_failing || [],
      last_new_story_et: s.news.last_new_story ? etTime(s.news.last_new_story, now) : null,
      summaries: ({ ok: "Summaries: normal", off: "Summaries: not switched on", paused: "Summaries: paused",
        limit: "Summaries: paused at the spending limit (headlines still publishing)", error: "Summaries: service errors (headlines still publishing)" })[(s.summaries || {}).state] || "Summaries: unknown",
      social: ({ ok: "Facebook: posting", paused: "Facebook: paused", idle: "Facebook: no posts yet" })[(s.social || {}).state] || "Facebook: unknown",
    },
  };
  return parts;
}

export async function statusResponse(env, now = new Date()) {
  const headers = { "content-type": "application/json; charset=utf-8", "cache-control": "no-store, max-age=0" };
  let data = null;
  try {
    if (env && env.ASSETS) {
      const r = await env.ASSETS.fetch(new Request("https://haultimes.com/status.json", { cf: { cacheTtl: 0 } }));
      if (r.ok) data = await r.json();
    }
  } catch (e) { data = null; }
  return new Response(JSON.stringify({ ...judge(data, now), server_time: now.toISOString() }), { headers });
}
