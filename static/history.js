/* History: trend chart (SVG), waterings-per-day bars and the watering log. */
(function () {
  "use strict";

  var SG = window.SG;
  var $ = function (id) { return document.getElementById(id); };
  var NS = "http://www.w3.org/2000/svg";

  var METRICS = {
    moisture: { label: "Soil moisture", unit: "%", fixed: [0, 100] },
    temperature: { label: "Temperature", unit: "°C" },
    humidity: { label: "Humidity", unit: "%", fixed: [0, 100] },
    water_level: { label: "Water tank", unit: "%", fixed: [0, 100] }
  };

  var metric = "moisture", range = "24h", filter = "all", days = 7;
  var data = null, settings = null, logEvents = [];

  function el(tag, attrs, parent) {
    var n = document.createElementNS(NS, tag);
    for (var k in attrs) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }

  function fmt(v) { return v === null || v === undefined ? "--" : (Math.round(v * 10) / 10) + METRICS[metric].unit; }

  // -- segmented controls --------------------------------------------------
  function seg(id, attr, onChange) {
    var buttons = document.querySelectorAll("#" + id + " button");
    buttons.forEach(function (b) {
      b.addEventListener("click", function () {
        buttons.forEach(function (x) { x.setAttribute("aria-selected", String(x === b)); });
        onChange(b.dataset[attr]);
      });
    });
  }

  seg("metric-tabs", "metric", function (v) { metric = v; drawChart(true); });
  seg("range-tabs", "range", function (v) { range = v; loadHistory(); });
  seg("filter-tabs", "filter", function (v) { filter = v; renderLog(); });
  seg("days-tabs", "days", function (v) { days = +v; loadLog(); });

  // -- trend chart ----------------------------------------------------------
  var chartBox = $("chart"), svg = $("chart-svg"), tip = $("chart-tip");
  var geom = null;

  function drawChart(animate) {
    if (!data) return;
    var m = METRICS[metric];
    var pts = data.points.filter(function (p) { return p[metric] !== null; });
    $("legend-metric").textContent = m.label;
    $("legend-threshold").hidden = metric !== "moisture";

    // summary tiles
    var vals = pts.map(function (p) { return p[metric]; });
    var tileVals = vals.length ? [vals[vals.length - 1], Math.min.apply(null, vals), Math.max.apply(null, vals),
      vals.reduce(function (a, b) { return a + b; }, 0) / vals.length] : [null, null, null, null];
    ["t-now", "t-min", "t-max", "t-avg"].forEach(function (id, i) { $(id).textContent = fmt(tileVals[i]); });

    while (svg.lastChild && svg.lastChild.tagName !== "desc") svg.removeChild(svg.lastChild);
    $("chart-empty").hidden = pts.length > 1;
    if (pts.length < 2) { geom = null; return; }

    var W = chartBox.clientWidth, H = W < 560 ? 210 : 270;
    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    svg.setAttribute("height", H);
    var P = { l: 38, r: 12, t: 12, b: 28 };
    var x0 = data.since, x1 = Date.now() / 1000;

    var lo, hi;
    if (m.fixed) { lo = m.fixed[0]; hi = m.fixed[1]; }
    else {
      lo = Math.floor((Math.min.apply(null, vals) - 2) / 5) * 5;
      hi = Math.ceil((Math.max.apply(null, vals) + 2) / 5) * 5;
    }
    var X = function (t) { return P.l + (t - x0) / (x1 - x0) * (W - P.l - P.r); };
    var Y = function (v) { return P.t + (1 - (v - lo) / (hi - lo)) * (H - P.t - P.b); };

    // grid + y labels
    var g = el("g", { class: "c-grid" }, svg);
    for (var i = 0; i <= 4; i++) {
      var v = lo + (hi - lo) * i / 4, y = Y(v);
      el("line", { x1: P.l, x2: W - P.r, y1: y, y2: y }, g);
      el("text", { x: P.l - 8, y: y + 4, "text-anchor": "end" }, g).textContent = Math.round(v);
    }
    // x labels
    var step = range === "7d" ? 86400 : 6 * 3600;
    var first;
    if (range === "7d") { var d0 = new Date(x0 * 1000); d0.setHours(24, 0, 0, 0); first = d0 / 1000; }
    else { var d1 = new Date(x0 * 1000); d1.setMinutes(0, 0, 0); d1.setHours(Math.ceil((d1.getHours() + 1) / 6) * 6); first = d1 / 1000; }
    for (var t = first; t < x1; t += step) {
      var lbl = range === "7d"
        ? new Date(t * 1000).toLocaleDateString([], { weekday: "short" })
        : SG.time(t);
      el("text", { x: X(t), y: H - 8, "text-anchor": "middle" }, g).textContent = lbl;
    }

    // moisture threshold
    if (metric === "moisture" && settings) {
      var ty = Y(settings.moisture_threshold);
      el("line", { class: "c-threshold", x1: P.l, x2: W - P.r, y1: ty, y2: ty }, svg);
    }

    // watering markers
    var marks = el("g", { class: "c-marks" }, svg);
    data.waterings.forEach(function (w) {
      var wx = X(w.ts);
      if (wx < P.l) return;
      el("line", { class: "c-mark-line", x1: wx, x2: wx, y1: P.t, y2: H - P.b }, marks);
      el("circle", { class: "c-mark t-" + w.trigger, cx: wx, cy: H - P.b, r: 4 }, marks);
    });

    // line + area (break the line where readings are missing for > 3 buckets)
    var gap = (range === "7d" ? 1800 : 300) * 3;
    var segs = [], cur = [];
    pts.forEach(function (p, i) {
      if (i && p.t - pts[i - 1].t > gap) { segs.push(cur); cur = []; }
      cur.push(p);
    });
    segs.push(cur);

    var defs = el("defs", {}, svg);
    var grad = el("linearGradient", { id: "area-grad", x1: 0, x2: 0, y1: 0, y2: 1 }, defs);
    el("stop", { offset: "0%", "stop-color": "#8fd9b6", "stop-opacity": 0.28 }, grad);
    el("stop", { offset: "100%", "stop-color": "#8fd9b6", "stop-opacity": 0 }, grad);

    segs.forEach(function (s) {
      if (s.length < 2) return;
      var d = s.map(function (p, i) { return (i ? "L" : "M") + X(p.t).toFixed(1) + " " + Y(p[metric]).toFixed(1); }).join("");
      var area = el("path", { class: "c-area", d: d + "L" + X(s[s.length - 1].t).toFixed(1) + " " + Y(lo) + "L" + X(s[0].t).toFixed(1) + " " + Y(lo) + "Z" }, svg);
      var line = el("path", { class: "c-line", d: d }, svg);
      if (animate && !SG.reduceMotion) {
        var len = line.getTotalLength();
        line.style.strokeDasharray = len;
        line.style.strokeDashoffset = len;
        area.style.opacity = 0;
        requestAnimationFrame(function () {
          line.style.transition = "stroke-dashoffset 1s cubic-bezier(0.22,1,0.36,1)";
          line.style.strokeDashoffset = 0;
          area.style.transition = "opacity .8s ease .3s";
          area.style.opacity = 1;
        });
      }
    });

    // hover layer
    var cross = el("line", { class: "c-cross", y1: P.t, y2: H - P.b, x1: 0, x2: 0, visibility: "hidden" }, svg);
    var dot = el("circle", { class: "c-dot", r: 5, visibility: "hidden" }, svg);
    geom = { pts: pts, X: X, Y: Y, P: P, W: W, H: H, cross: cross, dot: dot };
    $("chart-desc").textContent = m.label + " over the last " + (range === "7d" ? "7 days" : "24 hours");
  }

  function hover(clientX) {
    if (!geom) return;
    var r = svg.getBoundingClientRect();
    var mx = clientX - r.left;
    var best = null, bd = Infinity;
    geom.pts.forEach(function (p) {
      var dx = Math.abs(geom.X(p.t) - mx);
      if (dx < bd) { bd = dx; best = p; }
    });
    if (!best) return;
    var px = geom.X(best.t), py = geom.Y(best[metric]);
    geom.cross.setAttribute("x1", px); geom.cross.setAttribute("x2", px);
    geom.cross.setAttribute("visibility", "visible");
    geom.dot.setAttribute("cx", px); geom.dot.setAttribute("cy", py);
    geom.dot.setAttribute("visibility", "visible");

    var bucket = range === "7d" ? 1800 : 300;
    var near = data.waterings.filter(function (w) { return Math.abs(w.ts - best.t - bucket / 2) <= bucket; });
    var when = (range === "7d" ? SG.day(best.t) + ", " : "") + SG.time(best.t);
    tip.innerHTML = "<small></small><b></b>" + (near.length ? "<em></em>" : "");
    tip.querySelector("small").textContent = when;
    tip.querySelector("b").textContent = fmt(best[metric]);
    if (near.length) tip.querySelector("em").textContent = "Watered · " + near.map(function (w) { return (SG.triggers[w.trigger] || {}).label; }).join(", ");
    tip.hidden = false;
    var tw = tip.offsetWidth;
    tip.style.transform = "translate(" + Math.min(Math.max(px - tw / 2, 0), geom.W - tw) + "px," + Math.max(py - 70, 0) + "px)";
  }

  function unhover() {
    tip.hidden = true;
    if (geom) { geom.cross.setAttribute("visibility", "hidden"); geom.dot.setAttribute("visibility", "hidden"); }
  }

  svg.addEventListener("pointermove", function (e) { hover(e.clientX); });
  svg.addEventListener("pointerdown", function (e) { hover(e.clientX); });
  svg.addEventListener("pointerleave", unhover);

  var resizeTimer;
  window.addEventListener("resize", function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () { drawChart(false); drawBars(); }, 150);
  }, { passive: true });

  function loadHistory() {
    return SG.json("/api/history?range=" + range).then(function (d) {
      data = d;
      // No moisture sensor: start on humidity instead of an empty chart.
      if (metric === "moisture" && !d.points.some(function (p) { return p.moisture !== null; })) {
        var btn = document.querySelector('#metric-tabs [data-metric="humidity"]');
        if (btn) btn.click();
        return;
      }
      drawChart(true);
    }).catch(function (e) { SG.toast(e.message, "error"); });
  }

  // -- waterings per day ----------------------------------------------------
  function drawBars() {
    var box = $("bars");
    var n = days === 30 ? 14 : 7;
    var today = new Date(); today.setHours(0, 0, 0, 0);
    var buckets = [];
    for (var i = n - 1; i >= 0; i--) {
      var start = new Date(today); start.setDate(today.getDate() - i);
      buckets.push({ start: start / 1000, end: start / 1000 + 86400, list: [] });
    }
    logEvents.forEach(function (e) {
      if (!e.completed) return;
      buckets.forEach(function (b) { if (e.ts >= b.start && e.ts < b.end) b.list.push(e); });
    });
    var max = Math.max(3, Math.max.apply(null, buckets.map(function (b) { return b.list.length; })));
    var total = buckets.reduce(function (a, b) { return a + b.list.length; }, 0);
    $("bars-total").textContent = total + " in " + n + " days";

    box.innerHTML = "";
    buckets.forEach(function (b, i) {
      var col = document.createElement("div");
      col.className = "bar-col";
      var count = b.list.length;
      var by = {};
      b.list.forEach(function (e) { by[e.trigger] = (by[e.trigger] || 0) + 1; });
      var ml = Math.round(b.list.reduce(function (a, e) { return a + e.seconds; }, 0) * mlPerSecond);
      var d = new Date(b.start * 1000);
      col.innerHTML = '<span class="bar-num"></span><span class="bar-track"><span class="bar-fill"></span></span><span class="bar-day"></span>';
      col.querySelector(".bar-num").textContent = count || "";
      col.querySelector(".bar-day").textContent = i === n - 1 ? "Today" : d.toLocaleDateString([], n > 7 ? { day: "numeric" } : { weekday: "short" });
      col.title = SG.day(b.start) + ": " + count + (count === 1 ? " watering" : " waterings") +
        (count ? " (" + Object.keys(by).map(function (k) { return by[k] + " " + SG.triggers[k].label.toLowerCase(); }).join(", ") + ") · ~" + ml + " ml" : "");
      col.tabIndex = 0;
      var fill = col.querySelector(".bar-fill");
      fill.style.transitionDelay = (i * 0.04) + "s";
      box.appendChild(col);
      requestAnimationFrame(function () { requestAnimationFrame(function () {
        fill.style.transform = "scaleY(" + (count / max) + ")";
      }); });
    });
  }

  // -- log ------------------------------------------------------------------
  var mlPerSecond = 25;

  function renderLog() {
    var list = $("log-list");
    var items = logEvents.filter(function (e) { return filter === "all" || e.trigger === filter; });
    list.innerHTML = "";
    if (!items.length) {
      list.innerHTML = '<p class="events-empty">No waterings in this period.</p>';
      return;
    }
    var groups = [];
    items.forEach(function (e) {
      var day = SG.day(e.ts);
      if (!groups.length || groups[groups.length - 1].day !== day) groups.push({ day: day, items: [] });
      groups[groups.length - 1].items.push(e);
    });
    groups.forEach(function (g, gi) {
      var done = g.items.filter(function (e) { return e.completed; });
      var ml = Math.round(done.reduce(function (a, e) { return a + e.seconds; }, 0) * mlPerSecond);
      var sec = document.createElement("div");
      sec.className = "log-day";
      sec.style.setProperty("--i", Math.min(gi, 8));
      sec.innerHTML = '<div class="log-day-head"><b></b><span></span></div><ul class="events"></ul>';
      sec.querySelector("b").textContent = g.day;
      sec.querySelector("span").textContent = done.length + (done.length === 1 ? " watering" : " waterings") + " · ~" + ml + " ml";
      var ul = sec.querySelector("ul");
      g.items.forEach(function (e) {
        var tr = SG.triggers[e.trigger] || SG.triggers.manual;
        var li = document.createElement("li");
        li.className = "event" + (e.completed ? "" : " is-skipped");
        li.innerHTML =
          '<span class="event-time"></span>' +
          '<span class="event-icon t-' + e.trigger + '"><i class="fa-solid ' + tr.icon + '"></i></span>' +
          '<span class="event-main"><b></b><small></small></span>' +
          '<span class="event-side"></span>';
        li.querySelector(".event-time").textContent = SG.time(e.ts);
        li.querySelector("b").textContent = e.completed ? tr.label + " · " + Math.round(e.seconds) + " s" : tr.label + " skipped";
        li.querySelector("small").textContent = e.note || (e.completed ? "~" + Math.round(e.seconds * mlPerSecond) + " ml" : "");
        li.querySelector(".event-side").textContent = e.moisture_before !== null ? "Soil " + Math.round(e.moisture_before) + "%" : "";
        ul.appendChild(li);
      });
      list.appendChild(sec);
    });
  }

  function loadLog() {
    return SG.json("/api/log?days=" + days).then(function (d) {
      logEvents = d.events;
      mlPerSecond = d.ml_per_second;
      renderLog();
      drawBars();
    }).catch(function (e) { SG.toast(e.message, "error"); });
  }

  SG.json("/api/settings").then(function (s) { settings = s; }).finally(function () {
    loadHistory();
    loadLog();
  });

  // keep it fresh without redrawing constantly
  setInterval(function () {
    if (document.hidden) return;
    SG.json("/api/history?range=" + range).then(function (d) { data = d; if (tip.hidden) drawChart(false); });
    loadLog();
  }, 60000);
})();
