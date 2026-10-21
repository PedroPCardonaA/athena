// Athena UI helpers. Everything degrades gracefully: pages work as plain forms without this file.
(function () {
  var root = document.documentElement;
  function store(fn) { try { return fn(window.localStorage); } catch (e) { return null; } }

  // Apply the saved theme immediately (this script is loaded in <head>) to avoid a flash.
  var saved = store(function (s) { return s.getItem("athena-theme"); });
  if (saved === "light" || saved === "dark") root.setAttribute("data-theme", saved);

  document.addEventListener("DOMContentLoaded", function () {
    var btn = document.getElementById("theme-toggle");
    if (btn) btn.addEventListener("click", function () {
      var dark = root.getAttribute("data-theme") === "dark" ||
        (!root.getAttribute("data-theme") && window.matchMedia("(prefers-color-scheme: dark)").matches);
      var next = dark ? "light" : "dark";
      root.setAttribute("data-theme", next);
      store(function (s) { s.setItem("athena-theme", next); });
    });

    function grow(t) { t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight, 480) + "px"; }
    document.querySelectorAll("textarea").forEach(function (t) {
      t.addEventListener("input", function () { grow(t); });
      grow(t);
    });
    // <details> panels reveal textareas after load; resize when opened.
    document.querySelectorAll("details").forEach(function (d) {
      d.addEventListener("toggle", function () { d.querySelectorAll("textarea").forEach(grow); });
    });

    document.addEventListener("keydown", function (e) {
      var mod = e.ctrlKey || e.metaKey;
      if (mod && e.key.toLowerCase() === "k") {
        var s = document.getElementById("search");
        if (s) { e.preventDefault(); s.focus(); s.select(); }
      } else if (mod && e.key === "Enter" && e.target.form) {
        e.preventDefault();
        e.target.form.requestSubmit();
      }
    });

    if (location.hash === "#new") {
      var t = document.querySelector("#new [name=title]");
      if (t) t.focus();
    }
  });
})();
