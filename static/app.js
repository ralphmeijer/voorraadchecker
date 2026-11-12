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

// Pagina's die op een antwoord van de marketplace wachten, verversen zichzelf.
(function () {
  var el = document.querySelector("[data-refresh]");
  if (el) setTimeout(function () { location.replace(location.pathname + "?kanaal=" + (new URLSearchParams(location.search).get("kanaal") || "")); },
    1000 * (parseInt(el.getAttribute("data-refresh"), 10) || 5));
})();
