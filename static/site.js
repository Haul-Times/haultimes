// HaulTimes: live relative times and the date/sort filters on topic pages.
(function () {
  function ago(iso) {
    var t = Date.parse(iso);
    if (isNaN(t)) return "";
    var m = Math.max(0, Math.round((Date.now() - t) / 60000));
    if (m < 1) return "Just now";
    if (m < 60) return m + " min ago";
    var h = Math.round(m / 60);
    if (h < 24) return h + "h ago";
    var d = Math.round(h / 24);
    return d === 1 ? "Yesterday" : d + " days ago";
  }
  function refreshTimes() {
    document.querySelectorAll("time[data-ago]").forEach(function (el) {
      var txt = ago(el.getAttribute("datetime"));
      if (txt) el.textContent = txt;
    });
  }
  refreshTimes();
  setInterval(refreshTimes, 60000);

  // Topic page filters
  var list = document.getElementById("story-list");
  if (!list) return;
  var state = { range: "all", sort: "new" };
  var LIMIT = { today: 24, week: 168, month: 720, all: 1e9 };

  function apply() {
    var rows = Array.prototype.slice.call(list.querySelectorAll(".row"));
    var now = Date.now(), shown = 0;
    rows.forEach(function (r) {
      var hrs = (now - Date.parse(r.getAttribute("data-time"))) / 3600000;
      var ok = hrs <= LIMIT[state.range];
      r.hidden = !ok;
      if (ok) shown++;
    });
    rows.sort(function (a, b) {
      if (state.sort === "top") return b.getAttribute("data-score") - a.getAttribute("data-score");
      return Date.parse(b.getAttribute("data-time")) - Date.parse(a.getAttribute("data-time"));
    }).forEach(function (r) { list.appendChild(r); });
    var empty = document.getElementById("no-stories");
    if (empty) empty.hidden = shown > 0;
  }

  document.querySelectorAll("[data-range],[data-sort]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var key = btn.hasAttribute("data-range") ? "range" : "sort";
      state[key] = btn.getAttribute(key === "range" ? "data-range" : "data-sort");
      document.querySelectorAll(key === "range" ? "[data-range]" : "[data-sort]").forEach(function (b) {
        b.setAttribute("aria-pressed", b === btn ? "true" : "false");
      });
      apply();
    });
  });
  apply();
})();

// Privacy-friendly visit counter: page and referring site only. No cookies, nothing stored on the device.
(function () {
  try {
    if (location.hostname !== "haultimes.com" && location.hostname !== "www.haultimes.com" && location.hostname !== "localhost") return;
    try { if (localStorage.getItem("ht_owner") === "1") return; } catch (e) {}   // the site owner's own browser
    var body = JSON.stringify({ p: location.pathname, r: document.referrer || "" });
    if (navigator.sendBeacon) navigator.sendBeacon("/api/hit", body);
    else fetch("/api/hit", { method: "POST", body: body, keepalive: true });
  } catch (e) {}
})();

// A refresh on a news page should show the newest stories, so start back at the top instead of
// where the reader was (browsers otherwise restore the old scroll position, which can leave the
// logo half hidden under the address bar on phones). Back/forward still keep their position.
(function () {
  try {
    var nav = performance.getEntriesByType && performance.getEntriesByType("navigation")[0];
    if (nav && nav.type === "reload") {
      if ("scrollRestoration" in history) history.scrollRestoration = "manual";
      window.scrollTo(0, 0);
      var top = function () { window.scrollTo(0, 0); };
      window.addEventListener("load", function () { top(); setTimeout(top, 60); });
      window.addEventListener("pagehide", function () { history.scrollRestoration = "auto"; });
    }
  } catch (e) {}
})();

// Share buttons: the phone's own share sheet (Messages, WhatsApp, Facebook...) when available,
// otherwise a small row of icons. Shares are counted (network only) so the admin panel can show them.
(function () {
  var canNative = !!navigator.share && /Mobi|Android|iPhone|iPad/i.test(navigator.userAgent);
  function count(net) {
    try { if (localStorage.getItem("ht_owner") === "1") return; } catch (e) {}
    try { navigator.sendBeacon && navigator.sendBeacon("/api/hit", JSON.stringify({ p: "/~share/" + net, r: "" })); } catch (e) {}
  }
  var ICONS = {"facebook": "<svg viewBox=\"0 0 24 24\" width=\"18\" height=\"18\" aria-hidden=\"true\" fill=\"currentColor\"><path d=\"M14 8h3V4h-3c-2.8 0-4.5 1.8-4.5 4.6V11H7v4h2.5v7h4v-7h3l.5-4h-3.5V8.8c0-.5.3-.8.5-.8z\"/></svg>", "x": "<svg viewBox=\"0 0 24 24\" width=\"18\" height=\"18\" aria-hidden=\"true\" fill=\"currentColor\"><path d=\"M17.7 3h3.1l-6.8 7.8L22 21h-6.3l-4.9-6.4L5.2 21H2.1l7.3-8.3L1.8 3h6.4l4.4 5.9zm-1.1 16.2h1.7L7.4 4.7H5.6z\"/></svg>", "email": "<svg viewBox=\"0 0 24 24\" width=\"18\" height=\"18\" aria-hidden=\"true\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linejoin=\"round\"><rect x=\"3\" y=\"5\" width=\"18\" height=\"14\" rx=\"1\"/><path d=\"M3 6l9 7 9-7\"/></svg>", "copy": "<svg viewBox=\"0 0 24 24\" width=\"18\" height=\"18\" aria-hidden=\"true\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\"><path d=\"M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1\"/></svg>"};
  function links(u, t) {
    var e = encodeURIComponent;
    return [["facebook", "Share on Facebook", "https://www.facebook.com/sharer/sharer.php?u=" + e(u)],
      ["x", "Share on X", "https://x.com/intent/post?text=" + e(t) + "&url=" + e(u)],
      ["email", "Share by email", "mailto:?subject=" + e(t) + "&body=" + e("Saw this on HaulTimes:\n\n" + t + "\n" + u)]];
  }
  function flash(el, msg) {
    var tip = document.createElement("span");
    tip.className = "sh-tip"; tip.textContent = msg;
    el.appendChild(tip); setTimeout(function () { tip.remove(); }, 1600);
  }
  function copy(u, el) {
    var done = function () { flash(el, "Link copied"); };
    if (navigator.clipboard) navigator.clipboard.writeText(u).then(done, function () { prompt("Copy this link:", u); });
    else prompt("Copy this link:", u);
    count("copy");
  }
  var menu;
  function close() { if (menu) { menu.remove(); menu = null; } }
  function openMenu(btn) {
    close();
    var u = btn.dataset.u, t = btn.dataset.t;
    menu = document.createElement("div");
    menu.className = "sh-pop";
    menu.setAttribute("role", "menu");
    menu.innerHTML = links(u, t).map(function (l) {
      var ext = l[0] === "email" ? "" : ' target="_blank" rel="noopener"';
      return '<a role="menuitem" class="sh-' + l[0] + '" data-net="' + l[0] + '" href="' + l[2].replace(/"/g, "&quot;") + '"' + ext +
        ' aria-label="' + l[1] + '" title="' + l[1] + '">' + ICONS[l[0]] + "</a>";
    }).join("") + '<button type="button" role="menuitem" class="cp" aria-label="Copy link" title="Copy link">' + ICONS.copy + "</button>";
    document.body.appendChild(menu);
    var r = btn.getBoundingClientRect();
    menu.style.top = (window.scrollY + r.top + r.height / 2 - menu.offsetHeight / 2) + "px";
    menu.style.left = Math.max(8, Math.min(window.scrollX + r.right + 6, window.scrollX + document.documentElement.clientWidth - menu.offsetWidth - 8)) + "px";
    menu.querySelector(".cp").addEventListener("click", function (e) { copy(u, e.currentTarget); setTimeout(close, 1200); });
    menu.querySelector("a,button").focus();
  }
  document.addEventListener("click", function (ev) {
    var b = ev.target.closest && ev.target.closest(".sh, .sh-native");
    var a = ev.target.closest && ev.target.closest("[data-net]");
    if (a) { count(a.dataset.net); setTimeout(close, 100); return; }
    if (b) {
      ev.preventDefault();
      if (canNative) {
        navigator.share({ title: b.dataset.t, url: b.dataset.u }).then(function () { count("native"); }, function () {});
      } else if (b.classList.contains("sh")) {
        menu ? close() : openMenu(b);
      }
      return;
    }
    var c = ev.target.closest && ev.target.closest(".sh-copy");
    if (c) { copy(c.dataset.u, c); return; }
    if (menu && !menu.contains(ev.target)) close();
  });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") close(); });
  if (canNative) document.querySelectorAll(".sh-native").forEach(function (b) { b.hidden = false; });
})();

// Masthead status: words + colour from /api/status (server-judged). Never green from the page alone.
(function () {
  var box = document.getElementById("htStatus");
  if (!box) return;
  var label = box.querySelector(".st-label"), line = box.querySelector(".st-line"),
      btn = box.querySelector(".st-row"), panel = box.querySelector(".st-panel"), misses = 0;
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function show(d) {
    box.dataset.state = d.state;
    label.textContent = d.label;
    if (d.every) line.textContent = "Headlines checked every " + d.every + " minutes" + (d.last_checked_et ? " · Last checked " + d.last_checked_et : "");
    var x = d.detail || {};
    panel.innerHTML = d.state === "unavailable" ? "<p>Status information can't be reached right now. This doesn't mean news has stopped.</p>" :
      "<ul><li>" + esc(x.news) + "</li>" + (x.sources ? "<li>" + esc(x.sources) + "</li>" : "") +
      (x.last_new_story_et ? "<li>Last new story: " + esc(x.last_new_story_et) + "</li>" : "") +
      (x.failing && x.failing.length ? "<li>Not answering: " + esc(x.failing.join(", ")) + "</li>" : "") +
      "<li>" + esc(x.summaries) + "</li><li>" + esc(x.social) + "</li></ul>" +
      "<p>Fuel, market and border data keep their own update times on their pages.</p>";
  }
  function poll() {
    fetch("/api/status?t=" + Date.now(), { cache: "no-store" }).then(function (r) { if (!r.ok) throw 0; return r.json(); })
      .then(function (d) { misses = 0; show(d); })
      .catch(function () { if (++misses >= 2) show({ state: "unavailable", label: "STATUS UNAVAILABLE" }); });
  }
  btn.addEventListener("click", function () {
    var open = panel.hidden; panel.hidden = !open; btn.setAttribute("aria-expanded", String(open));
  });
  poll(); setInterval(poll, 60000);
  setTimeout(function () { if (!box.dataset.state) { misses = 2; show({ state: "unavailable", label: "STATUS UNAVAILABLE" }); } }, 12000);
})();
