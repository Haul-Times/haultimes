/* HaulTimes Freight Market: reader reports (rate checker, weekly map, lane rates, one-tap poll, rate form). */
(function () {
  var API = "/api/";
  var CA = ["AB","BC","MB","NB","NL","NS","NT","NU","ON","PE","QC","SK","YT"];
  var EQ = { all: "All equipment", van: "Dry van", reefer: "Reefer", flatbed: "Flatbed", stepdeck: "Step deck" };
  var COL = { hot: "#C4262E", normal: "#E6DFC8", slow: "#2F6690" };
  var NAMES = {};
  var store = {
    get: function (k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set: function (k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
  };
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var esc = function (s) { return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); };
  $$("#chk select[name=o] option").forEach(function (o) { if (o.value) NAMES[o.value] = o.textContent; });

  var country = function (r) { return CA.indexOf(r) >= 0 ? "CA" : "US"; };
  var mkt = function (o, d) { var a = country(o), b = country(d); return a === b ? a : "XB"; };
  var cur = function (m) { return m === "CA" ? "C$" : "US$"; };
  var money = function (m, v) { return cur(m) + Number(v).toFixed(2) + "/mi"; };
  var off = false;

  function setOff() {
    off = true;
    $("#mk-off").hidden = false;
    $$("#chk button, #rep button, #poll button").forEach(function (b) { b.disabled = true; });
    $("#lanes-body").innerHTML = '<tr><td colspan="5" class="note">Lane rates will appear here once readers start reporting.</td></tr>';
  }

  // ---------------------------------------------------------------- weekly map + lanes
  var eq = store.get("ht_eq") || "all";
  var mFilter = "all";
  var last = null;

  function paintLanes() {
    var body = $("#lanes-body");
    if (!last) return;
    var rows = last.lanes.filter(function (l) { return mFilter === "all" || l.market === mFilter; });
    if (!rows.length) {
      body.innerHTML = '<tr><td colspan="5" class="note">No lane has enough reports yet' + (last.lanes_waiting ? " (" + last.lanes_waiting + " lanes are filling up)" : "") +
        '. <a href="#rep">Report a rate</a> to help.</td></tr>';
      return;
    }
    body.innerHTML = rows.map(function (l) {
      var ch = l.change == null ? '<span class="note">—</span>' :
        '<span class="mk-chg ' + (l.change > 0 ? "up" : l.change < 0 ? "down" : "") + '">' + (l.change > 0 ? "▲ " : l.change < 0 ? "▼ " : "– ") + Math.abs(l.change).toFixed(2) + "</span>";
      var where = { US: "US", CA: "Canada", XB: "Cross-border" }[l.market];
      return '<tr><td><span class="n">' + esc(NAMES[l.o] || l.o) + " → " + esc(NAMES[l.d] || l.d) + '</span><div class="p">' + where + "</div></td>" +
        '<td data-l="Equipment">' + EQ[l.equipment] + '</td><td data-l="Typical rate"><b>' + money(l.market, l.median) + '</b> <span class="note">middle half ' +
        Number(l.p25).toFixed(2) + "–" + Number(l.p75).toFixed(2) + '</span></td><td data-l="Reports">' + l.n + '</td><td data-l="vs last week">' + ch + "</td></tr>";
    }).join("");
  }

  function paintMap() {
    $$("[id^='r-'] rect").forEach(function (r) { r.setAttribute("fill", "#F1F2F4"); });
    $$("[id^='r-'] text").forEach(function (t) { t.removeAttribute("fill"); });
    var hot = 0, shown = 0;
    Object.keys(last.regions).forEach(function (k) {
      var g = document.getElementById("r-" + k), v = last.regions[k];
      if (!g) return;
      var tip = g.querySelector("title");
      if (!v.level) { tip.textContent = (NAMES[k] || k) + ": not enough reports yet (" + v.n + " of 5)"; return; }
      shown++; if (v.level === "hot") hot++;
      g.querySelector("rect").setAttribute("fill", COL[v.level]);
      if (v.level !== "normal") g.querySelector("text").setAttribute("fill", "#fff");
      tip.textContent = (NAMES[k] || k) + ": " + v.level + " (" + v.hot + " hot, " + v.normal + " normal, " + v.slow + " slow)";
    });
    $("#map-title").textContent = (eq === "all" ? "All loads" : EQ[eq] + " loads") + ", week of " + new Date(last.week + "T12:00:00Z").toLocaleDateString("en-US", { month: "short", day: "numeric" });
    $("#map-count").textContent = last.reports + " reports this week. " + (shown ? shown + " areas shown, " + hot + " hot." : "No area has 5 reports yet.");
  }

  function load() {
    $$("#eq .chip").forEach(function (b) { b.setAttribute("aria-pressed", b.dataset.eq === eq ? "true" : "false"); });
    fetch(API + "summary?eq=" + eq).then(function (r) {
      if (r.status === 503 || r.status === 404) { setOff(); throw 0; }
      return r.json();
    }).then(function (j) { last = j; paintMap(); paintLanes(); }).catch(function (e) {
      if (e !== 0 && !off) $("#lanes-body").innerHTML = '<tr><td colspan="5" class="note">Couldn\'t load reader reports. Try again in a minute.</td></tr>';
    });
  }
  $$("#eq .chip").forEach(function (b) {
    b.addEventListener("click", function () {
      eq = b.dataset.eq; store.set("ht_eq", eq); load();
      if (eq !== "all" && !store.get("ht_poll_eq") && typeof showWhere === "function") { pEq = eq; showWhere(); }
    });
  });
  $$("#mkt .chip").forEach(function (b) {
    b.addEventListener("click", function () {
      mFilter = b.dataset.m;
      $$("#mkt .chip").forEach(function (x) { x.setAttribute("aria-pressed", x === b ? "true" : "false"); });
      paintLanes();
    });
  });

  // ---------------------------------------------------------------- shared form helpers
  function vals(form) {
    var o = {};
    $$("input, select", form).forEach(function (el) { if (el.name) o[el.name] = el.value.trim(); });
    return o;
  }
  function say(el, cls, html) { el.className = "mk-out " + cls; el.innerHTML = html; }
  function post(path, body) {
    return fetch(API + path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) })
      .then(function (r) { if (r.status === 503) setOff(); return r.json(); });
  }
  // Remember lane and equipment between the two rate forms
  ["o", "d", "equipment", "unit", "currency"].forEach(function (n) {
    var saved = store.get("ht_" + n);
    $$("form select[name=" + n + "]").forEach(function (s) {
      if (saved && s.querySelector('option[value="' + saved + '"]')) s.value = saved;
      s.addEventListener("change", function () { store.set("ht_" + n, s.value); });
    });
  });

  // ---------------------------------------------------------------- rate checker
  $("#chk").addEventListener("submit", function (ev) {
    ev.preventDefault();
    var v = vals(this), out = $("#chk-out");
    var amount = Number(v.amount.replace(/[$,\s]/g, "")), dist = Number(v.distance.replace(/[,\s]/g, ""));
    if (!v.o || !v.d) return say(out, "err", "Pick the pickup and delivery state or province.");
    if (!(amount > 0) || !(dist > 0)) return say(out, "err", "Enter the rate offered and the loaded distance.");
    var miles = v.unit === "km" ? dist / 1.609344 : dist;
    say(out, "", "Checking…");
    fetch(API + "check?o=" + v.o + "&d=" + v.d + "&equipment=" + v.equipment).then(function (r) {
      if (r.status === 503) { setOff(); throw 0; }
      return r.json();
    }).then(function (j) {
      if (!j.ok) return say(out, "err", esc(j.error));
      var lane = esc(NAMES[v.o]) + " → " + esc(NAMES[v.d]) + ", " + EQ[v.equipment];
      if (!j.enough) {
        return say(out, "", "<b>Not enough reports on " + lane + " yet</b> (" + j.n + " in the last 30 days; we need 5 from 3 different people). " +
          'If you\'ve hauled this lane, <a href="#rep">report your rate</a> so the next driver can check.');
      }
      var rpm = amount / miles, laneCur = j.currency, offerCur = v.currency;
      if (offerCur !== laneCur) {
        if (!j.usdcad) return say(out, "err", "Enter the offer in " + (laneCur === "USD" ? "US$" : "C$") + " for this lane.");
        rpm = offerCur === "CAD" ? rpm / j.usdcad : rpm * j.usdcad;
      }
      var m = j.market, verdict = rpm < j.p25 ? "low" : rpm > j.p75 ? "high" : "usual";
      var head = { low: "Below what most carriers got", usual: "In the usual range", high: "Above most reports" }[verdict];
      say(out, "v-" + verdict, "<b class=\"vh\">" + head + "</b>Your offer works out to <b>" + money(m, rpm) + "</b>" +
        (offerCur !== laneCur ? " (converted at the Bank of Canada rate)" : "") + ". On " + lane + ", carriers reported a typical <b>" + money(m, j.median) +
        "</b>; the middle half got " + money(m, j.p25) + " to " + money(m, j.p75) + ". Based on " + j.n + " reports from the last " + j.days + " days.");
    }).catch(function (e) { if (e !== 0) say(out, "err", "Couldn't check right now. Try again in a minute."); });
  });

  // ---------------------------------------------------------------- one-tap poll
  var poll = $("#poll"), pick = $("#poll-pick"), pCity, pRegion, pEq;
  pCity = null; pRegion = store.get("ht_poll_region"); pEq = store.get("ht_poll_eq") || (eq !== "all" ? eq : "van");
  function showWhere() {
    $("#poll-where").textContent = (EQ[pEq] || "Dry van") + " · " + (pRegion ? "near " + (pCity ? pCity + ", " : "") + (NAMES[pRegion] || pRegion) : "pick your area");
    $("#poll-eq-line").hidden = true;
    pick.querySelector("[name=region]").value = pRegion || "";
    pick.querySelector("[name=equipment]").value = pEq;
  }
  if (!pRegion) {
    fetch(API + "where").then(function (r) { return r.json(); }).then(function (j) {
      if (j.region) { pRegion = j.region; pCity = j.city; showWhere(); } else { pick.hidden = false; }
    }).catch(function () { pick.hidden = false; });
  }
  showWhere();
  $("#poll-change").addEventListener("click", function () { pick.hidden = !pick.hidden; });
  pick.querySelector("[name=region]").addEventListener("change", function () { pRegion = this.value; pCity = null; store.set("ht_poll_region", pRegion); showWhere(); });
  pick.querySelector("[name=equipment]").addEventListener("change", function () { pEq = this.value; store.set("ht_poll_eq", pEq); showWhere(); });
  $$(".pollbtn", poll).forEach(function (b) {
    b.addEventListener("click", function () {
      var out = $("#poll-out");
      if (!pRegion) { pick.hidden = false; return say(out, "err", "Pick your state or province first."); }
      $$(".pollbtn", poll).forEach(function (x) { x.classList.toggle("on", x === b); });
      post("poll", { region: pRegion, equipment: pEq, answer: Number(b.dataset.a) }).then(function (j) {
        if (!j.ok) return say(out, "err", esc(j.error || "Couldn't save. Try again."));
        store.set("ht_poll_region", pRegion); store.set("ht_poll_eq", pEq);
        say(out, "ok", "Thanks! Counted for " + esc(NAMES[pRegion] || pRegion) + ", " + EQ[pEq] + ", this week.");
        load();
      }).catch(function () { say(out, "err", "Couldn't save right now. Try again in a minute."); });
    });
  });

  // ---------------------------------------------------------------- report a rate
  var rep = $("#rep");
  rep.querySelector("[name=date]").value = new Date(Date.now() - new Date().getTimezoneOffset() * 6e4).toISOString().slice(0, 10);
  rep.addEventListener("submit", function (ev) {
    ev.preventDefault();
    var out = $("#rep-out"), body = vals(rep);
    post("rate", body).then(function (j) {
      if (!j.ok) return say(out, "err", esc(j.error || "Couldn't save. Try again."));
      say(out, "ok", "Thanks! Recorded at " + (j.currency === "CAD" ? "C$" : "US$") + j.rpm.toFixed(2) + "/mi. It counts toward the lane once enough people report.");
      rep.querySelector("[name=amount]").value = ""; rep.querySelector("[name=distance]").value = "";
      load();
    }).catch(function () { say(out, "err", "Couldn't save right now. Try again in a minute."); });
  });

  // ---------------------------------------------------------------- USDA table destination filter
  var dest = document.getElementById("mk-dest");
  if (dest) dest.addEventListener("change", function () {
    var v = dest.value;
    $$("#mk-body tr").forEach(function (tr) {
      tr.hidden = !(!v || tr.dataset.dests.split("|").indexOf(v) >= 0);
      $$("li[data-dest]", tr).forEach(function (li) { li.hidden = !!v && li.dataset.dest !== v; });
    });
  });

  load();
})();

// Arriving from the homepage "Is your rate fair?" box: fill in the lane and jump to the checker.
(function () {
  try {
    var q = new URLSearchParams(location.search), f = document.getElementById("chk");
    if (!f || !q.get("o")) return;
    ["o", "d", "equipment"].forEach(function (k) {
      var v = (q.get(k) || "").toUpperCase(), el = f.querySelector("[name=" + k + "]");
      if (k === "equipment") v = v.toLowerCase();
      if (el && el.querySelector('option[value="' + v + '"]')) el.value = v;
    });
    f.scrollIntoView({ block: "start" });
    var amt = f.querySelector("[name=amount]");
    if (amt) amt.focus({ preventScroll: true });
  } catch (e) {}
})();
