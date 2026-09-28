/* Shared: helpers, toasts, mobile menu. Landing page: live stats with count-up. */
(function () {
  "use strict";

  // ---------------------------------------------------------------------
  // Shared helpers (used by dashboard.js, history.js, automation.js)
  // ---------------------------------------------------------------------
  var SG = (window.SG = {});

  SG.reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  SG.ago = function (ts) {
    if (!ts) return "never";
    var s = Math.max(0, Math.round(Date.now() / 1000 - ts));
    if (s < 60) return s + " s ago";
    if (s < 3600) return Math.round(s / 60) + " min ago";
    if (s < 86400) return Math.round(s / 3600) + " h ago";
    return Math.round(s / 86400) + " d ago";
  };

  SG.time = function (ts) {
    return new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  };

  SG.day = function (ts) {
    var d = new Date(ts * 1000);
    var today = new Date(); today.setHours(0, 0, 0, 0);
    var diff = Math.round((today - new Date(d.getFullYear(), d.getMonth(), d.getDate())) / 86400000);
    if (diff === 0) return "Today";
    if (diff === 1) return "Yesterday";
    return d.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
  };

  SG.triggers = {
    manual: { label: "Manual", icon: "fa-hand-pointer" },
    auto: { label: "Auto", icon: "fa-seedling" },
    schedule: { label: "Schedule", icon: "fa-clock" }
  };

  SG.json = function (url, opts) {
    return fetch(url, Object.assign({ cache: "no-store" }, opts || {})).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!r.ok) throw new Error(j.error || "Request failed (" + r.status + ")");
        return j;
      });
    });
  };

  SG.post = function (url, body) {
    return SG.json(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {})
    });
  };

  // Smoothly animates a number inside an element.
  SG.tween = function (el, to, opts) {
    opts = opts || {};
    var dec = opts.decimals || 0;
    var from = parseFloat(el.dataset.current);
    el.dataset.current = to;
    if (isNaN(from) || SG.reduceMotion) { el.textContent = to.toFixed(dec); return; }
    if (from === to) return;
    var start = performance.now(), dur = opts.duration || 700;
    requestAnimationFrame(function frame(now) {
      var t = Math.min(1, (now - start) / dur);
      var e = 1 - Math.pow(1 - t, 3);
      el.textContent = (from + (to - from) * e).toFixed(dec);
      if (t < 1) requestAnimationFrame(frame);
    });
  };

  SG.toast = function (msg, type) {
    var box = document.getElementById("toasts");
    if (!box) return;
    var el = document.createElement("div");
    el.className = "toast toast-" + (type || "info");
    var icon = type === "error" ? "fa-circle-exclamation" : type === "ok" ? "fa-circle-check" : "fa-circle-info";
    el.innerHTML = '<i class="fa-solid ' + icon + '" aria-hidden="true"></i><span></span>';
    el.querySelector("span").textContent = msg;
    box.appendChild(el);
    setTimeout(function () {
      el.classList.add("is-leaving");
      setTimeout(function () { el.remove(); }, 350);
    }, 3600);
  };

  // ---------------------------------------------------------------------
  // Mobile menu
  // ---------------------------------------------------------------------
  var burger = document.querySelector(".burger");
  var menu = document.getElementById("mobile-menu");
  var overlay = document.querySelector(".menu-overlay");

  function setMenu(open) {
    if (!burger || !menu || !overlay) return;
    burger.setAttribute("aria-expanded", String(open));
    burger.setAttribute("aria-label", open ? "Close menu" : "Open menu");
    menu.hidden = !open;
    overlay.hidden = !open;
    document.body.classList.toggle("menu-open", open);
  }

  if (burger) {
    burger.addEventListener("click", function () {
      setMenu(burger.getAttribute("aria-expanded") !== "true");
    });
    overlay.addEventListener("click", function () { setMenu(false); });
    menu.addEventListener("click", function (e) {
      if (e.target.closest("a")) setMenu(false);
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") setMenu(false);
    });
    window.addEventListener("resize", function () {
      if (window.innerWidth > 720) setMenu(false);
    }, { passive: true });
  }

  // ---------------------------------------------------------------------
  // Live stats (landing page only)
  // ---------------------------------------------------------------------
  var values = Array.prototype.slice.call(document.querySelectorAll(".stat-value[data-key]"));
  if (!values.length) return;

  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var counted = false;
  var latest = null;

  function format(el, n) {
    var dec = +el.dataset.decimals || 0;
    return n.toFixed(dec) + (el.dataset.suffix || "");
  }

  function easeOutCubic(t) { return 1 - Math.pow(1 - t, 3); }

  function tween(el, to, duration, delay) {
    var from = parseFloat(el.dataset.current) || 0;
    el.dataset.current = to;
    if (reduceMotion || duration <= 0) { el.textContent = format(el, to); return; }
    setTimeout(function () {
      var start = performance.now();
      function frame(now) {
        var t = Math.min(1, (now - start) / duration);
        el.textContent = format(el, from + (to - from) * easeOutCubic(t));
        if (t < 1) requestAnimationFrame(frame);
      }
      requestAnimationFrame(frame);
    }, delay);
  }

  function applyFallback(data) {
    if (data.moisture_simulated) {
      var lbl = document.querySelector('.stat-value[data-key="moisture"] ~ .stat-label');
      if (lbl) lbl.textContent = "Soil Moisture (sim)";
    }
    if (data.has_moisture) return;
    document.querySelectorAll(".stat[data-fallback]").forEach(function (stat) {
      var v = stat.querySelector(".stat-value");
      if (v.dataset.key === stat.dataset.fallback) return;
      v.dataset.key = stat.dataset.fallback;
      v.dataset.suffix = "";
      stat.querySelector(".stat-label").textContent = stat.dataset.fallbackLabel;
      stat.querySelector(".stat-icon").textContent = stat.dataset.fallbackIcon;
    });
  }

  function render(data, first) {
    applyFallback(data);
    values.forEach(function (el, i) {
      var v = data[el.dataset.key];
      if (v === null || v === undefined) { el.textContent = "--"; return; }
      if (first) tween(el, +v, 1500 + i * 80, 480 + i * 90);
      else if (+v !== +el.dataset.current) tween(el, +v, 500, 0);
    });
  }

  function load() {
    return fetch("/api/status", { cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data) return;
        var first = !latest;
        latest = data;
        if (counted) render(data, first);
      })
      .catch(function () {});
  }

  function startCount() {
    if (counted) return;
    counted = true;
    if (latest) render(latest, true);
  }

  if ("IntersectionObserver" in window) {
    var io = new IntersectionObserver(function (entries) {
      if (entries.some(function (e) { return e.isIntersecting; })) {
        startCount();
        io.disconnect();
      }
    }, { threshold: 0.25 });
    io.observe(document.querySelector(".stats"));
  } else {
    startCount();
  }

  load();
  // Refresh every 5 s, but only while the tab is visible (no wasted work).
  setInterval(function () { if (!document.hidden) load(); }, 5000);
})();
