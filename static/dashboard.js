/* Dashboard: live readings + remote watering. */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var dash = $("dash");
  var cfg = {
    tMin: +dash.dataset.tempMin, tMax: +dash.dataset.tempMax,
    hMin: +dash.dataset.humMin, hMax: +dash.dataset.humMax,
    low: +dash.dataset.lowWater
  };

  var seconds = 5;
  var busy = false;      // this page started a watering
  var last = null;       // latest /api/status payload
  var failures = 0;

  // -- helpers ------------------------------------------------------------
  function setText(el, txt) { if (el.textContent !== txt) el.textContent = txt; }

  function ago(ts) {
    if (!ts) return "never";
    var s = Math.max(0, Math.round(Date.now() / 1000 - ts));
    if (s < 60) return s + " s ago";
    if (s < 3600) return Math.round(s / 60) + " min ago";
    if (s < 86400) return Math.round(s / 3600) + " h ago";
    return new Date(ts * 1000).toLocaleDateString();
  }

  function rangeHint(el, v, min, max, unit) {
    var out = v !== null && (v < min || v > max);
    el.classList.toggle("is-warn", out);
    setText(el, v === null ? "No reading yet"
      : v > max ? "Too high · ideal " + min + "–" + max + unit
      : v < min ? "Too low · ideal " + min + "–" + max + unit
      : "Ideal " + min + "–" + max + unit);
  }

  // -- render ---------------------------------------------------------------
  function render(d) {
    last = d;
    var status = $("status");
    status.dataset.level = d.status;
    setText($("status-text"), d.message);
    setText($("status-meta"), (d.simulated ? "Simulated data · " : "") + "Updated " + ago(d.updated));

    setText($("temperature"), d.temperature === null ? "--" : String(Math.round(d.temperature)));
    setText($("humidity"), d.humidity === null ? "--" : String(Math.round(d.humidity)));
    setText($("water_level"), d.water_level === null ? "--" : String(d.water_level));
    rangeHint($("temp-hint"), d.temperature, cfg.tMin, cfg.tMax, " °C");
    rangeHint($("hum-hint"), d.humidity, cfg.hMin, cfg.hMax, " %");

    var bar = $("tank-bar");
    bar.style.transform = "scaleX(" + ((d.water_level || 0) / 100) + ")";
    bar.classList.toggle("is-low", d.water_level !== null && d.water_level < cfg.low);

    setText($("water-meta"), "Last watered " + ago(d.last_watered) +
      " · " + d.waterings_today + (d.waterings_today === 1 ? " time" : " times") + " today");

    updateButton();
  }

  function updateButton() {
    if (busy || !last) return;
    var btn = $("water-btn");
    var reason = "";
    if (last.watering) reason = "Watering in progress…";
    else if (!last.pump_connected) reason = "No pump connected";
    else if (last.water_level !== null && last.water_level < cfg.low) reason = "Refill the tank first";
    btn.disabled = !!reason;
    if (reason && !$("water-msg").dataset.sticky) setText($("water-msg"), reason);
    if (!reason && !$("water-msg").dataset.sticky) setText($("water-msg"), "");
  }

  function offline() {
    $("status").dataset.level = "alert";
    setText($("status-text"), "Garden offline");
    setText($("status-meta"), "Check that app.py is running on the Pi");
  }

  // -- polling --------------------------------------------------------------
  function poll() {
    return fetch("/api/status", { cache: "no-store" })
      .then(function (r) { if (!r.ok) throw r; return r.json(); })
      .then(function (d) { failures = 0; render(d); })
      .catch(function () { if (++failures >= 2) offline(); });
  }

  poll();
  setInterval(function () { if (!document.hidden) poll(); }, 3000);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) poll(); });

  // -- watering -------------------------------------------------------------
  var chips = document.querySelectorAll(".chip");
  chips.forEach(function (chip) {
    chip.addEventListener("click", function () {
      if (busy) return;
      chips.forEach(function (c) { c.setAttribute("aria-checked", String(c === chip)); });
      seconds = +chip.dataset.seconds;
    });
  });

  function flash(msg) {
    var el = $("water-msg");
    el.dataset.sticky = "1";
    setText(el, msg);
    clearTimeout(flash.t);
    flash.t = setTimeout(function () { delete el.dataset.sticky; updateButton(); }, 4000);
  }

  $("water-btn").addEventListener("click", function () {
    var btn = this;
    if (busy || btn.disabled) return;
    busy = true;
    btn.disabled = true;

    fetch("/api/water", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ seconds: seconds })
    })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (res) {
        if (!res.ok || !res.j.ok) throw new Error(res.j.error || "Could not start watering");
        runProgress(res.j.seconds);
      })
      .catch(function (err) {
        busy = false;
        btn.disabled = false;
        flash(err.message || "Garden offline");
        updateButton();
      });
  });

  function runProgress(total) {
    var fill = $("water-fill");
    var label = $("water-label");
    var start = performance.now();
    $("water-btn").classList.add("is-watering");
    fill.style.transition = "none";
    fill.style.transform = "scaleX(0)";
    void fill.offsetWidth; // restart the transition
    fill.style.transition = "transform " + total + "s linear";
    fill.style.transform = "scaleX(1)";

    (function tick() {
      var left = Math.max(0, Math.ceil(total - (performance.now() - start) / 1000));
      label.innerHTML = '<i class="fa-solid fa-droplet" aria-hidden="true"></i> Watering… ' + left + " s";
      if (left > 0) return void setTimeout(tick, 250);
      setTimeout(function () {
        busy = false;
        $("water-btn").classList.remove("is-watering");
        fill.style.transition = "none";
        fill.style.transform = "scaleX(0)";
        label.innerHTML = '<i class="fa-solid fa-droplet" aria-hidden="true"></i> Water Now';
        flash("Done - plants watered for " + total + " s");
        poll();
      }, 400);
    })();
  }
})();
