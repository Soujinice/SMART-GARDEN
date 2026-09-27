/* Shared: mobile menu. Landing page: live stats with count-up. */
(function () {
  "use strict";

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

  function render(data, first) {
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
