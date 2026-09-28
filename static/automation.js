/* Automation settings: moisture rule, daily schedules, presets, alert ranges. */
(function () {
  "use strict";

  var SG = window.SG;
  var $ = function (id) { return document.getElementById(id); };
  var root = $("auto");
  var hasMoisture = root.dataset.hasMoisture === "true";
  var minS = +root.dataset.minSeconds, maxS = +root.dataset.maxSeconds;

  var PRESETS = {
    herbs: { moisture_threshold: 40, auto_seconds: 5, temp_min: 18, temp_max: 28, humidity_min: 40, humidity_max: 65 },
    greens: { moisture_threshold: 45, auto_seconds: 6, temp_min: 15, temp_max: 24, humidity_min: 50, humidity_max: 70 },
    fruiting: { moisture_threshold: 35, auto_seconds: 8, temp_min: 20, temp_max: 30, humidity_min: 45, humidity_max: 70 },
    succulents: { moisture_threshold: 15, auto_seconds: 4, temp_min: 18, temp_max: 32, humidity_min: 20, humidity_max: 50 }
  };

  var NUMS = ["moisture_threshold", "auto_seconds", "auto_min_gap_minutes",
              "temp_min", "temp_max", "humidity_min", "humidity_max", "low_water_percent"];

  var saved = null;   // last saved settings
  var draft = null;   // what the form currently shows

  function clone(o) { return JSON.parse(JSON.stringify(o)); }

  // -- form <-> draft -------------------------------------------------------
  function fill() {
    $("auto_enabled").checked = draft.auto_enabled && hasMoisture;
    $("buzzer_enabled").checked = draft.buzzer_enabled;
    $("auto_enabled").disabled = !hasMoisture;
    NUMS.forEach(function (k) { $(k).value = draft[k]; });
    ["moisture_threshold", "auto_seconds"].forEach(function (k) { $(k).disabled = !hasMoisture; });
    $("auto_min_gap_minutes").disabled = !hasMoisture;
    outputs();
    renderSchedules();
    markPreset();
  }

  function outputs() {
    $("out-threshold").textContent = $("moisture_threshold").value + "%";
    $("out-seconds").textContent = $("auto_seconds").value + " s";
    paintRange($("moisture_threshold"));
    paintRange($("auto_seconds"));
  }

  // Filled part of the slider track
  function paintRange(input) {
    var p = (input.value - input.min) / (input.max - input.min) * 100;
    input.style.setProperty("--p", p + "%");
  }

  function readForm() {
    draft.auto_enabled = $("auto_enabled").checked;
    draft.buzzer_enabled = $("buzzer_enabled").checked;
    NUMS.forEach(function (k) { var v = parseInt($(k).value, 10); if (!isNaN(v)) draft[k] = v; });
  }

  function dirty() {
    var d = JSON.stringify(draft) !== JSON.stringify(saved);
    $("save-bar").hidden = !d;
    return d;
  }

  function markPreset() {
    document.querySelectorAll(".preset").forEach(function (b) {
      var p = PRESETS[b.dataset.preset];
      var match = Object.keys(p).every(function (k) { return draft[k] === p[k]; });
      b.classList.toggle("is-active", match);
    });
  }

  root.addEventListener("input", function (e) {
    if (!e.target.id || e.target.closest(".schedules")) return;
    readForm();
    outputs();
    markPreset();
    dirty();
  });
  root.addEventListener("change", function (e) {
    if (e.target.closest(".schedules")) return;
    readForm();
    dirty();
  });

  document.querySelectorAll(".preset").forEach(function (b) {
    b.addEventListener("click", function () {
      Object.assign(draft, PRESETS[b.dataset.preset]);
      fill();
      dirty();
      SG.toast(b.querySelector("b").textContent + " values applied - press Save", "info");
    });
  });

  // -- schedules --------------------------------------------------------------
  function renderSchedules() {
    var ul = $("schedules");
    ul.innerHTML = "";
    if (!draft.schedules.length) {
      ul.innerHTML = '<li class="events-empty">No daily waterings. Add a time to water every day.</li>';
    }
    draft.schedules.forEach(function (s, i) {
      var li = document.createElement("li");
      li.className = "schedule" + (s.enabled ? "" : " is-off");
      li.innerHTML =
        '<input type="time" aria-label="Time" required />' +
        '<label class="sched-sec"><select aria-label="Duration"></select></label>' +
        '<label class="switch switch-sm" title="On/off"><input type="checkbox" aria-label="Enabled" /><span></span></label>' +
        '<button type="button" class="icon-btn" aria-label="Remove"><i class="fa-solid fa-trash-can"></i></button>';
      var time = li.querySelector('input[type="time"]');
      var sel = li.querySelector("select");
      var on = li.querySelector('input[type="checkbox"]');
      for (var n = minS; n <= maxS; n++) {
        var o = document.createElement("option");
        o.value = n; o.textContent = n + " s";
        sel.appendChild(o);
      }
      time.value = s.time; sel.value = s.seconds; on.checked = s.enabled;
      time.addEventListener("change", function () { if (time.value) { s.time = time.value; dirty(); } });
      sel.addEventListener("change", function () { s.seconds = +sel.value; dirty(); });
      on.addEventListener("change", function () { s.enabled = on.checked; li.classList.toggle("is-off", !on.checked); dirty(); });
      li.querySelector(".icon-btn").addEventListener("click", function () {
        li.classList.add("is-leaving");
        setTimeout(function () { draft.schedules.splice(i, 1); renderSchedules(); dirty(); }, 250);
      });
      ul.appendChild(li);
    });
    $("add-schedule").disabled = draft.schedules.length >= 6;
  }

  $("add-schedule").addEventListener("click", function () {
    var used = draft.schedules.map(function (s) { return s.time; });
    var t = ["08:00", "18:00", "12:00", "06:00", "20:00", "14:00"].filter(function (x) { return used.indexOf(x) < 0; })[0] || "09:00";
    draft.schedules.push({ time: t, seconds: 5, enabled: true });
    renderSchedules();
    dirty();
  });

  // -- save / discard ---------------------------------------------------------
  $("save").addEventListener("click", function () {
    var btn = this;
    btn.disabled = true;
    SG.post("/api/settings", draft)
      .then(function (r) {
        saved = clone(r.settings);
        draft = clone(r.settings);
        fill();
        dirty();
        SG.toast("Settings saved", "ok");
      })
      .catch(function (e) { SG.toast(e.message, "error"); })
      .finally(function () { btn.disabled = false; });
  });

  $("discard").addEventListener("click", function () {
    draft = clone(saved);
    fill();
    dirty();
  });

  window.addEventListener("beforeunload", function (e) {
    if (saved && dirty()) { e.preventDefault(); e.returnValue = ""; }
  });

  // -- LED & buzzer test ------------------------------------------------------
  $("test-outputs").addEventListener("click", function () {
    var btn = this;
    btn.disabled = true;
    SG.post("/api/test-outputs")
      .then(function (r) { SG.toast(r.sound ? "LED blinking + buzzer beeping" : "LED blinking (buzzer is muted)", "ok"); })
      .catch(function (e) { SG.toast(e.message, "error"); })
      .finally(function () { setTimeout(function () { btn.disabled = false; }, 1500); });
  });

  // -- live moisture marker on the threshold slider ----------------------------
  function showMoisture() {
    if (!hasMoisture) return;
    SG.json("/api/status").then(function (d) {
      if (d.moisture === null) return;
      var el = $("moisture-now");
      var slider = $("moisture_threshold");
      var p = (d.moisture - slider.min) / (slider.max - slider.min) * 100;
      el.style.left = Math.max(0, Math.min(100, p)) + "%";
      el.hidden = false;
      $("now-label").textContent = "Now " + d.moisture + "%";
    }).catch(function () {});
  }

  SG.json("/api/settings").then(function (s) {
    saved = clone(s);
    draft = clone(s);
    fill();
    showMoisture();
    setInterval(function () { if (!document.hidden) showMoisture(); }, 10000);
  }).catch(function (e) { SG.toast(e.message, "error"); });
})();
