// HaulTimes border wait times: direction and region filters, crossing detail chart.
(function () {
  var el = document.getElementById("border-data");
  if (!el) return;
  var data = JSON.parse(el.textContent);
  var state = { dir: "south", region: "all", sel: null };
  var tbody = document.getElementById("waits-body");

  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function level(w) {
    if (w == null) return ["No data", "na"];
    return w < 30 ? ["Light", "ok"] : (w <= 60 ? ["Moderate", "mid"] : ["Heavy", "bad"]);
  }
  function fmt(w) { if (w == null) return ""; return w < 60 ? w + " min" : Math.floor(w / 60) + " h " + (w % 60) + " min"; }
  function side(c) { return c[state.dir] || null; }
  function wait(c) { var s = side(c); return s ? s.wait : null; }

  function rows() {
    return data.crossings.filter(function (c) { return state.region === "all" || c.region === state.region; })
      .sort(function (a, b) {
        var wa = wait(a), wb = wait(b);
        if (wa == null && wb == null) return a.name.localeCompare(b.name);
        if (wa == null) return 1; if (wb == null) return -1;
        return wb - wa;
      });
  }

  function render() {
    var list = rows();
    if (!state.sel || !list.some(function (c) { return c.id === state.sel; })) state.sel = list.length ? list[0].id : null;
    tbody.innerHTML = list.map(function (c) {
      var s = side(c), w = wait(c), l = level(w);
      var extra = s && s.fast_wait != null && state.dir === "south" ? '<div class="p">FAST lane: ' + fmt(s.fast_wait) + "</div>" : "";
      var best = state.dir === "south" ? c.best_south : c.best_north;
      return '<tr class="' + (c.id === state.sel ? "sel" : "") + '">' +
        '<td><button type="button" class="name" data-id="' + esc(c.id) + '"><span class="n">' + esc(c.name) + '</span><span class="p">' + esc(c.ports) + "</span></button></td>" +
        '<td style="white-space:nowrap"><span class="badge ' + l[1] + '">' + l[0] + '</span><span class="wait">' + esc(fmt(w)) + "</span>" + extra + "</td>" +
        "<td>" + esc(best) + "</td>" +
        '<td class="p">' + esc(s && s.updated ? s.updated : (s ? s.status : "Not reported")) + "</td></tr>";
    }).join("") || '<tr><td colspan="4" class="empty">No crossings in this region.</td></tr>';

    var waits = list.filter(function (c) { return wait(c) != null; });
    var fast = waits.slice().sort(function (a, b) { return wait(a) - wait(b); })[0];
    var slow = waits.slice().sort(function (a, b) { return wait(b) - wait(a); })[0];
    document.getElementById("stat-fast").textContent = fast ? fast.name : "—";
    document.getElementById("stat-fast-w").textContent = fast ? fmt(wait(fast)) : "";
    document.getElementById("stat-slow").textContent = slow ? slow.name : "—";
    document.getElementById("stat-slow-w").textContent = slow ? fmt(wait(slow)) : "";
    document.getElementById("stat-count").textContent = list.length;
    document.getElementById("stat-dir").textContent = state.dir === "south" ? "Trucks entering the US" : "Trucks entering Canada";
    detail();
  }

  function detail() {
    var c = data.crossings.filter(function (x) { return x.id === state.sel; })[0];
    var box = document.getElementById("detail");
    if (!c) { box.hidden = true; return; }
    box.hidden = false;
    document.getElementById("d-name").textContent = c.name;
    document.getElementById("d-ports").textContent = c.ports;
    document.getElementById("d-dir").textContent = state.dir === "south" ? "into the US" : "into Canada";
    var usual = (c.usual && c.usual[state.dir]) || [];
    var has = usual.some(function (v) { return v != null; });
    document.getElementById("d-bars").innerHTML = usual.map(function (v, h) {
      var val = v == null ? 0 : Math.min(v, 90);
      var col = v == null ? "transparent" : (v < 30 ? "var(--ok)" : (v <= 60 ? "var(--mid)" : "var(--bad)"));
      return '<span class="' + (h === data.hour_now ? "now" : "") + '" title="' + (h % 12 || 12) + (h < 12 ? " AM" : " PM") + ": " + (v == null ? "no data yet" : v + " min") + '" style="height:' + Math.round(val / 90 * 150) + "px;background:" + col + '"></span>';
    }).join("");
    document.getElementById("d-best").textContent = state.dir === "south" ? c.best_south : c.best_north;
    document.getElementById("d-empty").hidden = has;
  }

  document.addEventListener("click", function (e) {
    var b = e.target.closest("button");
    if (!b) return;
    if (b.hasAttribute("data-dir")) { state.dir = b.getAttribute("data-dir"); press("[data-dir]", b); render(); }
    else if (b.hasAttribute("data-region")) { state.region = b.getAttribute("data-region"); press("[data-region]", b); render(); }
    else if (b.classList.contains("name")) { state.sel = b.getAttribute("data-id"); render(); }
  });
  function press(sel, on) { document.querySelectorAll(sel).forEach(function (x) { x.setAttribute("aria-pressed", x === on ? "true" : "false"); }); }
  render();
})();
