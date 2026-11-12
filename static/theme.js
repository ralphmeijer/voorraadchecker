// Zet de gekozen dag- of nachtmodus voordat de pagina wordt getekend (voorkomt een lichtflits).
(function () {
  try {
    var t = localStorage.getItem("thema");
    if (t === "dark" || t === "light") document.documentElement.setAttribute("data-theme", t);
  } catch (e) {}
})();
