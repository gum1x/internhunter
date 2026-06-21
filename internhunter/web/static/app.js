// InternHunter UI — tiny vanilla helpers (no framework). Theme, loading bar, toasts, hotkeys.
(function () {
  "use strict";

  // ---- theme ----
  var root = document.documentElement;
  function setTheme(mode) {
    if (mode === "dark") root.classList.add("dark");
    else root.classList.remove("dark");
    try { localStorage.setItem("ih-theme", mode); } catch (e) {}
    var btn = document.getElementById("theme-toggle");
    if (btn) {
      btn.textContent = mode === "dark" ? "☀️" : "🌙";
      btn.setAttribute("aria-label", mode === "dark" ? "Switch to light theme" : "Switch to dark theme");
    }
  }
  window.__ihToggleTheme = function () {
    setTheme(root.classList.contains("dark") ? "light" : "dark");
  };
  document.addEventListener("DOMContentLoaded", function () {
    setTheme(root.classList.contains("dark") ? "dark" : "light");
    var btn = document.getElementById("theme-toggle");
    if (btn) btn.addEventListener("click", window.__ihToggleTheme);
  });

  // ---- hotkeys: "/" focuses search, "g" then j/c/t jumps tabs ----
  document.addEventListener("keydown", function (e) {
    var tag = (e.target && e.target.tagName) || "";
    var typing = tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA";
    if (e.key === "/" && !typing) {
      var s = document.querySelector('input[type="search"]');
      if (s) { e.preventDefault(); s.focus(); s.select(); }
    }
  });

  // ---- top progress bar driven by htmx ----
  var bar;
  function ensureBar() {
    if (!bar) { bar = document.getElementById("progress"); }
    return bar;
  }
  var pending = 0;
  document.addEventListener("htmx:beforeRequest", function () {
    pending++; var b = ensureBar(); if (b) b.classList.add("active");
  });
  function done() {
    pending = Math.max(0, pending - 1);
    if (pending === 0) { var b = ensureBar(); if (b) b.classList.remove("active"); }
  }
  document.addEventListener("htmx:afterRequest", done);
  document.addEventListener("htmx:responseError", done);
  document.addEventListener("htmx:sendError", done);

  // ---- toasts ----
  function toast(msg) {
    var host = document.getElementById("toast-host");
    if (!host) return;
    var el = document.createElement("div");
    el.className = "toast";
    el.setAttribute("role", "status");
    el.innerHTML = '<span class="ok">✓</span><span></span>';
    el.lastChild.textContent = msg;
    host.appendChild(el);
    setTimeout(function () {
      el.style.opacity = "0";
      setTimeout(function () { el.remove(); }, 200);
    }, 2200);
  }
  window.__ihToast = toast;
  // Tracker inline edits + track button swap successfully -> acknowledge.
  document.addEventListener("htmx:afterOnLoad", function (e) {
    var path = (e.detail && e.detail.requestConfig && e.detail.requestConfig.path) || "";
    if (/\/tracker\/\d+\/update$/.test(path)) toast("Saved");
    else if (/\/jobs\/.+\/track$/.test(path)) toast("Added to tracker");
  });
})();
