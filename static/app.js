// Zoeken in de artikeltabel en automatisch wisselen van kanaal.
(function () {
  var zoek = document.getElementById("zoek");
  var tabel = document.getElementById("tabel");
  if (zoek && tabel) {
    var rows = Array.prototype.slice.call(tabel.tBodies[0].rows);
    var leeg = document.getElementById("leeg");
    zoek.addEventListener("input", function () {
      var q = zoek.value.trim().toLowerCase();
      var shown = 0;
      rows.forEach(function (tr) {
        var hit = !q || (tr.getAttribute("data-q") || "").indexOf(q) !== -1;
        tr.hidden = !hit;
        if (hit) shown++;
      });
      if (leeg) leeg.hidden = shown > 0;
    });
  }
  var auto = document.querySelector("[data-autosubmit]");
  if (auto) auto.addEventListener("change", function () { auto.form.submit(); });
})();

// Schakelaar voor dag- en nachtmodus. Zonder eigen keuze volgt de pagina de instelling van het apparaat.
(function () {
  var knop = document.querySelector("[data-theme-toggle]");
  if (!knop) return;
  knop.addEventListener("click", function () {
    var root = document.documentElement;
    var huidig = root.getAttribute("data-theme") ||
      (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    var nieuw = huidig === "dark" ? "light" : "dark";
    root.setAttribute("data-theme", nieuw);
    try { localStorage.setItem("thema", nieuw); } catch (e) {}
  });
})();
