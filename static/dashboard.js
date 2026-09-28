/* Dashboard: live gauges, remote watering, automation summary, recent activity. */
(function () {
  "use strict";

  var SG = window.SG;
  var $ = function (id) { return document.getElementById(id); };

  var ARC = 2 * Math.PI * 50 * 0.75;       // visible length of the 270° gauge arc
  var CIRC = 2 * Math.PI * 50;
  var seconds = 5;
  var last = null;
  var failures = 0;
  var lastLevel = null;
  var wasWatering = false;
  var progressTimer = null;

  // -- gauges -------------------------------------------------------------
  var gauges = {};
  document.querySelectorAll("[data-gauge]").forEach(function (card) {
    var g = { card: card, num: card.querySelector(".gauge-num"), hint: card.querySelector(".gauge-hint"),
              value: card.querySelector(".g-value"), band: card.querySelector(".g-band"),
              mark: card.querySelector(".g-mark"),
              min: +card.dataset.min || 0, max: +card.dataset.max || 100 };
    [g.value, g.band, card.querySelector(".g-track")].forEach(function (c) {
      if (c) c.style.strokeDasharray = ARC + " " + CIRC;
    });
    if (g.value) g.value.style.strokeDashoffset = ARC;
    gauges[card.dataset.gauge] = g;
  });

  function frac(g, v) { return Math.max(0, Math.min(1, (v - g.min) / (g.max - g.min))); }

  function setGauge(key, v, state, hint) {
    var g = gauges[key];
    if (!g) return;
    g.card.dataset.state = v === null ? "none" : state;
    g.hint.textContent = hint;
    if (v === null) { g.num.textContent = "--"; delete g.num.dataset.current; return; }
    SG.tween(g.num, Math.round(v));
    if (g.value) g.value.style.strokeDashoffset = ARC * (1 - frac(g, v));
  }

  // Comfort band drawn as a faint arc segment behind the value.
  function setBand(key, lo, hi) {
    var g = gauges[key];
    if (!g || !g.band) return;
    var a = frac(g, lo), b = frac(g, hi);
    g.band.style.strokeDasharray = "0 " + (ARC * a) + " " + (ARC * (b - a)) + " " + CIRC;
  }

  function setMark(key, v) {
    var g = gauges[key];
    if (!g || !g.mark) return;
    g.mark.style.transform = "rotate(" + (-135 + 270 * frac(g, v)) + "deg)";
  }

  function rangeState(v, lo, hi) {
    if (v === null) return ["none", "No reading yet"];
    if (v < lo) return ["warn", "Low · ideal " + lo + "–" + hi];
    if (v > hi) return ["warn", "High · ideal " + lo + "–" + hi];
    return ["ok", "Ideal " + lo + "–" + hi];
  }

  // -- render -------------------------------------------------------------
  function render(d) {
    last = d;
    var s = d.settings;

    $("status").dataset.level = d.status;
    $("status-text").textContent = d.message;
    $("status-meta").textContent = (d.simulated ? "Simulated data · " : "") + "Updated " + SG.ago(d.updated);
    if (lastLevel && lastLevel !== d.status && d.status !== "ok") SG.toast(d.message, d.status === "alert" ? "error" : "info");
    lastLevel = d.status;
    document.title = (d.status === "ok" ? "" : "⚠ ") + "Dashboard · Smart Indoor Garden";

    // Moisture
    if (!d.has_moisture) {
      setGauge("moisture", null, "none", "No sensor connected");
    } else {
      var m = d.moisture;
      var dry = m !== null && m < s.moisture_threshold;
      setGauge("moisture", m, dry ? "warn" : "ok",
        m === null ? "No reading yet" : dry ? "Dry · waters below " + s.moisture_threshold + "%" : "Waters below " + s.moisture_threshold + "%");
      setMark("moisture", s.moisture_threshold);
    }

    var t = rangeState(d.temperature, s.temp_min, s.temp_max);
    setGauge("temperature", d.temperature, t[0], t[1]);
    setBand("temperature", s.temp_min, s.temp_max);

    var h = rangeState(d.humidity, s.humidity_min, s.humidity_max);
    setGauge("humidity", d.humidity, h[0], h[1]);
    setBand("humidity", s.humidity_min, s.humidity_max);

    var w = d.water_level;
    var low = w !== null && w < s.low_water_percent;
    setGauge("water_level", w, low ? "alert" : "ok",
      w === null ? "No reading yet" : low ? "Refill now" : w < 35 ? "Getting low" : "Tank OK");
    $("tank-fill").style.transform = "translateY(" + (100 - (w || 0)) + "%)";

    // Water card
    $("water-meta").textContent = "Last " + SG.ago(d.last_watered) + " · " + d.waterings_today +
      " today · ~" + d.water_used_today_ml + " ml";
    renderWatering(d);

    // Automation summary
    var toggle = $("auto-toggle");
    toggle.checked = s.auto_enabled && d.has_moisture;
    toggle.disabled = !d.has_moisture;
    $("auto-line").innerHTML = !d.has_moisture
      ? '<i class="fa-solid fa-seedling"></i> Needs a soil moisture sensor'
      : s.auto_enabled
        ? '<i class="fa-solid fa-seedling"></i> Waters ' + s.auto_seconds + " s when soil drops below <b>" + s.moisture_threshold + "%</b>"
        : '<i class="fa-solid fa-seedling"></i> Off - only schedules and manual watering';
    $("schedule-line").innerHTML = '<i class="fa-solid fa-clock"></i> ' + (d.next_schedule
      ? "Next schedule: <b>" + SG.day(d.next_schedule) + " " + SG.time(d.next_schedule) + "</b>"
      : "No daily schedule set");

    renderRecent(d.recent);
  }

  function renderRecent(list) {
    var ul = $("recent");
    var key = JSON.stringify(list.map(function (e) { return e.id; }));
    if (ul.dataset.key === key) return;       // unchanged: don't touch the DOM
    ul.dataset.key = key;
    if (!list.length) { ul.innerHTML = '<li class="events-empty">No waterings yet</li>'; return; }
    ul.innerHTML = "";
    list.forEach(function (e, i) {
      var tr = SG.triggers[e.trigger] || SG.triggers.manual;
      var li = document.createElement("li");
      li.className = "event" + (e.completed ? "" : " is-skipped");
      li.style.setProperty("--i", i);
      li.innerHTML =
        '<span class="event-icon t-' + e.trigger + '"><i class="fa-solid ' + tr.icon + '"></i></span>' +
        '<span class="event-main"><b></b><small></small></span>' +
        '<span class="event-side"></span>';
      li.querySelector("b").textContent = e.completed ? tr.label + " · " + Math.round(e.seconds) + " s" : tr.label + " skipped";
      li.querySelector("small").textContent = SG.day(e.ts) + ", " + SG.time(e.ts) + (e.note ? " · " + e.note : "");
      li.querySelector(".event-side").textContent = e.moisture_before !== null ? "Soil " + Math.round(e.moisture_before) + "%" : "";
      ul.appendChild(li);
    });
  }

  // -- watering button -----------------------------------------------------
  function renderWatering(d) {
    var btn = $("water-btn");
    var running = !!d.watering;
    $("stop-btn").hidden = !running;
    btn.classList.toggle("is-watering", running);

    if (running && !progressTimer) startProgress(d.watering);
    if (!running && wasWatering) {
      stopProgress();
      SG.toast("Plants watered", "ok");
    }
    wasWatering = running;

    var reason = "";
    if (running) reason = "";
    else if (!d.output_connected) reason = "No LED/buzzer connected";
    else if (d.water_level !== null && d.water_level < d.settings.low_water_percent) reason = "Refill the tank first";
    btn.disabled = running || !!reason;
    $("water-msg").textContent = reason;
  }

  function startProgress(w) {
    var fill = $("water-fill");
    var total = w.seconds, remaining = w.remaining;
    fill.style.transition = "none";
    fill.style.transform = "scaleX(" + (1 - remaining / total) + ")";
    void fill.offsetWidth;
    fill.style.transition = "transform " + remaining + "s linear";
    fill.style.transform = "scaleX(1)";
    var end = performance.now() + remaining * 1000;
    var label = SG.triggers[w.trigger] ? SG.triggers[w.trigger].label : "";
    progressTimer = setInterval(function tick() {
      var left = Math.max(0, Math.ceil((end - performance.now()) / 1000));
      $("water-label").innerHTML = '<i class="fa-solid fa-droplet"></i> Watering… ' + left + " s";
      $("water-label").title = label + " watering";
      return tick;
    }(), 250);
  }

  function stopProgress() {
    clearInterval(progressTimer);
    progressTimer = null;
    var fill = $("water-fill");
    fill.style.transition = "transform .4s ease";
    fill.style.transform = "scaleX(0)";
    $("water-label").innerHTML = '<i class="fa-solid fa-droplet"></i> Water Now';
  }

  document.querySelectorAll(".chip").forEach(function (chip, _, all) {
    chip.addEventListener("click", function () {
      all.forEach(function (c) { c.setAttribute("aria-checked", String(c === chip)); });
      seconds = +chip.dataset.seconds;
    });
  });

  $("water-btn").addEventListener("click", function () {
    var btn = this;
    if (btn.disabled) return;
    btn.disabled = true;
    SG.post("/api/water", { seconds: seconds })
      .then(poll)
      .catch(function (err) {
        btn.disabled = false;
        SG.toast(err.message, "error");
      });
  });

  $("stop-btn").addEventListener("click", function () {
    SG.post("/api/stop").then(function () { SG.toast("Watering stopped", "info"); poll(); });
  });

  $("auto-toggle").addEventListener("change", function () {
    var on = this.checked;
    SG.post("/api/settings", { auto_enabled: on })
      .then(function () { SG.toast("Automatic watering " + (on ? "on" : "off"), "ok"); poll(); })
      .catch(function (err) { SG.toast(err.message, "error"); });
  });

  // -- polling --------------------------------------------------------------
  function offline() {
    $("status").dataset.level = "alert";
    $("status-text").textContent = "Garden offline";
    $("status-meta").textContent = "Check that app.py is running on the Pi";
  }

  function poll() {
    return SG.json("/api/status")
      .then(function (d) { failures = 0; render(d); })
      .catch(function () { if (++failures >= 2) offline(); });
  }

  poll();
  setInterval(function () { if (!document.hidden) poll(); }, 2500);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) poll(); });
})();
