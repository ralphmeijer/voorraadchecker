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

// Handmatig bijwerken via de pijltjes in de bovenbalk: draaien tot de ophaalronde klaar is, dan herladen.
(function () {
  var form = document.querySelector("[data-sync]");
  if (!form || !window.fetch) return;
  var knop = form.querySelector("button");
  var tekst = knop.querySelector("span");
  var kanaal = form.querySelector("[name=kanaal]").value;
  var begin = 0;

  function bezig() {
    knop.classList.add("busy");
    knop.classList.remove("fail");
    knop.disabled = true;
    tekst.textContent = "Bijwerken…";
    knop.title = "Bezig met bijwerken";
  }
  function mislukt(msg) {
    knop.classList.remove("busy");
    knop.classList.add("fail");
    knop.disabled = false;
    tekst.textContent = "Bijwerken mislukt";
    knop.title = msg || "Bijwerken mislukt";
  }
  function volgen() {
    if (Date.now() - begin > 20 * 60 * 1000) return mislukt("Het bijwerken duurt ongewoon lang; herlaad de pagina later");
    fetch("/bijwerken/status?kanaal=" + encodeURIComponent(kanaal), { credentials: "same-origin", cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (s) {
        if (s.running) return setTimeout(volgen, 3000);
        if (s.ok === false) return mislukt(s.message);
        location.reload();
      })
      .catch(function () { setTimeout(volgen, 5000); });
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    if (knop.classList.contains("busy")) return;
    bezig();
    begin = Date.now();
    fetch(form.action, { method: "POST", body: new FormData(form), credentials: "same-origin",
                         headers: { "X-Requested-With": "fetch" } })
      .then(function (r) { return r.json(); })
      .then(function (s) {
        if (!s.started) return mislukt(s.message);
        setTimeout(volgen, 2000);
      })
      .catch(function () { mislukt("Geen verbinding met de server"); });
  });

  // Loopt er al een ronde (bijvoorbeeld de geplande van 06:10), dan meteen meedraaien.
  if (knop.classList.contains("busy")) { bezig(); begin = Date.now(); setTimeout(volgen, 3000); }
})();
