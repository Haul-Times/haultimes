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
