(function () {
  try {
    var pref = localStorage.getItem("zent_theme") || "system";
    var dark =
      pref === "dark" ||
      (pref === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
    document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
  } catch {
    document.documentElement.setAttribute("data-theme", "dark");
  }
})();