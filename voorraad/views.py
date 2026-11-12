"""HTML-opbouw van het dashboard (zonder externe bibliotheken)."""
from __future__ import annotations

from html import escape as esc
from urllib.parse import quote

STATUS_CLASS = {"Kritiek": "crit", "Aanvullen": "fill", "OK": "ok", "Overstock": "over",
                "Dood": "dead", "Niet aanvullen": "off"}
SIGNAL_ICON = {"up": "▲", "down": "▼", "warn": "!", "info": "i", "note": "✎"}


def nl(value, digits=0):
    if value is None:
        return "–"
    text = ("%." + str(digits) + "f") % value
    whole, _, frac = text.partition(".")
    sign = "-" if whole.startswith("-") else ""
    whole = whole.lstrip("-")
    groups = []
    while len(whole) > 3:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    groups.insert(0, whole)
    return sign + ".".join(groups) + ("," + frac if frac else "")


def nl_date(iso):
    if not iso:
        return "–"
    months = ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"]
    y, m, d = iso[:10].split("-")
    return "%d %s %s" % (int(d), months[int(m) - 1], y)


def pill(status):
    return '<span class="pill %s">%s</span>' % (STATUS_CLASS.get(status, "ok"), esc(status))


def spark(series, width=84, height=22):
    """Staafjes per dag, oud naar nieuw."""
    if not series:
        return ""
    top = max(max(series), 1)
    n = len(series)
    bw = width / n
    bars = []
    for i, v in enumerate(series):
        h = max(1.0, (v / top) * (height - 2)) if v else 1.0
        bars.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" class="%s"/>' % (
            i * bw + 0.5, height - h, max(1.0, bw - 1.5), h, "b" if v else "z"))
    return '<svg class="spark" viewBox="0 0 %d %d" width="%d" height="%d" role="img" aria-label="Besteld per dag: %s">%s</svg>' % (
        width, height, width, height, esc(", ".join(str(v) for v in series)), "".join(bars))


def cover_cell(r, params):
    if r["cover"] is None:
        return '<span class="muted">geen verkoop</span>'
    scale = 1.5 * params["target"]
    w = 64
    filled = min(1.0, r["cover"] / scale) * w
    tick = params["trigger"] / scale * w
    cls = STATUS_CLASS.get(r["status"], "ok")
    return ('<span class="cover"><b>%s</b> dgn<svg viewBox="0 0 %d 6" width="%d" height="6" aria-hidden="true">'
            '<rect class="track" width="%d" height="6" rx="3"/><rect class="bar %s" width="%.1f" height="6" rx="3"/>'
            '<rect class="tick" x="%.1f" width="1.5" height="6"/></svg></span>') % (
        nl(r["cover"], 0), w, w, w, cls, filled, tick)


def signals_html(r):
    if not r["signals"]:
        return ""
    return '<ul class="signals">%s</ul>' % "".join(
        '<li class="sig %s"><span class="ic" aria-hidden="true">%s</span>%s</li>' % (kind, SIGNAL_ICON.get(kind, "i"), esc(text))
        for kind, text in r["signals"])


def thumb(ean, has_photo):
    """Miniatuur van het artikel, of een leeg vakje zodat de rijen gelijk blijven."""
    if has_photo:
        return '<img class="thumb" src="/foto/%s-s.jpg" alt="" width="44" height="44" loading="lazy">' % esc(ean)
    return '<span class="thumb none" aria-hidden="true"></span>'


def ident(ean, article_code):
    """Tekst onder de artikelnaam: EAN en artikelcode, of alleen de SKU als er geen EAN bekend is."""
    if str(ean).startswith("29"):
        return "SKU %s" % esc(article_code) if article_code else "geen EAN bekend"
    return esc(ean) + (" · " + esc(article_code) if article_code else "")


def product_cell(r, code):
    return ('<a class="prod" href="/artikel/%s?kanaal=%s">%s<span class="ptext"><span class="pname">%s</span>'
            '<span class="pmeta">%s%s</span></span></a>') % (
        r["ean"], quote(code), thumb(r["ean"], r.get("photo")), esc(r["name"] or "(naam onbekend)"),
        ident(r["ean"], r["article_code"]), "")


def deliver_cell(r):
    if not r["need"]:
        return '<span class="muted">–</span>'
    if r["units"]:
        return '<b>%s</b> × %s = <b>%s</b> st' % (nl(r["units"]), nl(r["unit"]), nl(r["deliver"]))
    return '<b>%s</b> st <span class="muted">(eenheid ontbreekt)</span>' % nl(r["need"])


def logo(code, name):
    """Logo uit static/logos/<code>.png als dat bestaat, anders de eerste letter."""
    from . import config
    if (config.ROOT / "static" / "logos" / (code + ".png")).is_file():
        return '<img src="/static/logos/%s.png" alt="" width="24" height="24">' % quote(code)
    return '<span class="mono" aria-hidden="true">%s</span>' % esc((name or code)[:1].upper())


def static_version():
    """Verandert zodra stylesheet of script wijzigt, zodat browsers nooit een oude versie blijven gebruiken."""
    from . import config
    try:
        return "%d" % max((config.ROOT / "static" / f).stat().st_mtime for f in ("style.css", "app.js"))
    except OSError:
        return "0"


WAIT = '<span class="spin" role="img" aria-label="Bezig"></span>'


def layout(title, body, user=None, channels=(), current=None, active="", flash=None):
    nav = ""
    if user:
        q = "?kanaal=%s" % quote(current) if current else ""
        items = [("/", "Aanvullen", "aanvullen"), ("/artikelen", "Alle artikelen", "artikelen")]
        if user["role"] == "beheer":
            items.append(("/instellingen", "Instellingen", "instellingen"))
        links = "".join('<a href="%s%s"%s>%s</a>' % (href, q, ' class="on"' if key == active else "", label)
                        for href, label, key in items)
        chan = ""
        base = {"artikelen": "/artikelen", "instellingen": "/instellingen"}.get(active, "/")
        tabs = ""
        if active:
            tabs = '<div class="tabs" role="navigation" aria-label="Kanaal">%s</div>' % "".join(
                '<a class="tab%s" href="%s?kanaal=%s"%s>%s<span>%s</span></a>' % (
                    " on" if c["code"] == current else "", base, quote(c["code"]),
                    ' aria-current="page"' if c["code"] == current else "", logo(c["code"], c["name"]), esc(c["name"]))
                for c in channels)
        nav = ('<header class="top"><a class="brand" href="/%s">Voorraadchecker</a>%s<nav>%s</nav>'
               '<div class="who"><a href="/account">%s</a><form method="post" action="/uitloggen">'
               '<input type="hidden" name="csrf" value="%s"><button class="link">Uitloggen</button></form></div></header>%s') % (
            q, chan, links, esc(user["username"]), esc(user["csrf"]), tabs)
    note = ""
    if flash:
        note = '<div class="flash %s" role="status">%s</div>' % (esc(flash[0]), esc(flash[1]))
    return ('<!doctype html><html lang="nl"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>%s · Voorraadchecker</title><link rel="stylesheet" href="/static/style.css?v=%s">'
            '</head><body>%s<main>%s%s</main><script src="/static/app.js?v=%s" defer></script></body></html>') % (
        esc(title), static_version(), nav, note, body, static_version())


def login_page(error=None):
    err = '<p class="err" role="alert">%s</p>' % esc(error) if error else ""
    body = ('<section class="login"><h1>Voorraadchecker</h1><p class="muted">Log in om het aanvuladvies te bekijken.</p>%s'
            '<form method="post" action="/inloggen"><label>Gebruikersnaam<input name="username" autocomplete="username" required autofocus></label>'
            '<label>Wachtwoord<input name="password" type="password" autocomplete="current-password" required></label>'
            '<button class="primary">Inloggen</button></form></section>') % err
    return layout("Inloggen", body)


def freshness(result, last_run):
    bits = []
    if result["ref_date"]:
        bits.append("Voorraadstand van <b>%s</b>" % nl_date(result["ref_date"]))
    if last_run:
        state = "gelukt" if last_run["ok"] else "mislukt"
        bits.append("laatste verversing %s (%s)" % (esc((last_run["finished"] or last_run["started"] or "")[:16]), state))
    return " · ".join(bits)


def shipments_section(devs, ships, code, csrf):
    """Afwijkingen bij zendingen (met afhandelknop) en de lopende zendingen."""
    from .shipments import STATE_LABEL
    out = ""
    if devs:
        trs = []
        for d in devs:
            what = "Aantal wijkt af" if d["kind"] == "aantal" else "Blijft hangen bij opboeken"
            art = ('<span class="prod">%s<span class="ptext">%s<span class="pmeta">%s</span></span></span>' % (
                thumb(d["ean"], d["photo"]), esc(d["title"] or ""), "" if d["ean"].startswith("29") else esc(d["ean"]))) if d["ean"] else '<span class="muted">hele zending</span>'
            mailed = '<span class="pmeta">mail verstuurd %s</span>' % esc(d["mailed_at"][:10]) if d["mailed_at"] else ""
            trs.append(
                '<tr><td><b>%s</b><span class="pmeta">aangemeld %s</span></td><td>%s</td><td><span class="pill crit">%s</span></td>'
                '<td>%s</td><td>%s%s</td><td><form method="post" action="/afwijking/afhandelen">'
                '<input type="hidden" name="csrf" value="%s"><input type="hidden" name="kanaal" value="%s">'
                '<input type="hidden" name="id" value="%d"><button class="button small">Afgehandeld</button></form></td></tr>' % (
                    esc(d["reference"] or d["ship_id"]), nl_date(d["created"]), art, what, esc(d["detail"] or ""),
                    nl_date(d["first_seen"]), mailed, csrf, esc(code), d["id"]))
        out += ('<section id="afwijkingen"><h2>Afwijkingen bij zendingen</h2><p class="muted">Verdwijnt vanzelf als de marketplace het rechtzet, of als je op Afgehandeld klikt. '
                'Staat een afwijking er de volgende dag nog, dan gaat er een mail uit.</p>'
                '<div class="scroll"><table class="grid"><thead><tr><th>Zending</th><th>Artikel</th><th>Afwijking</th><th>Toelichting</th><th>Sinds</th><th></th></tr></thead>'
                '<tbody>%s</tbody></table></div></section>') % "".join(trs)
    if ships:
        trs = []
        for s in ships:
            when = "aangekomen %s" % nl_date(s["arrived"]) if s["arrived"] else ("verwacht %s" % nl_date(s["expected"]) if s["expected"] else "")
            trs.append('<tr><td><b>%s</b></td><td>%s</td><td>%s<span class="pmeta">%s</span></td><td class="num">%d</td><td class="num">%s</td><td class="num">%s</td><td class="num">%s</td></tr>' % (
                esc(s["reference"] or s["ship_id"]), nl_date(s["created"]), esc(STATE_LABEL.get(s["state"], s["state"])), esc(when),
                s["n_lines"], nl(s["announced"]), nl(s["received"]), nl(s["booked"])))
        out += ('<section><h2>Lopende zendingen</h2><div class="scroll"><table class="grid"><thead><tr><th>Zending</th><th>Aangemeld</th><th>Status</th>'
                '<th class="num">Artikelen</th><th class="num">Aangemeld (st)</th><th class="num">Ontvangen</th><th class="num">Opgeboekt</th></tr></thead>'
                '<tbody>%s</tbody></table></div></section>') % "".join(trs)
    return out


def week_banner(week, code):
    """Opvallende melding zolang deze gebruiker het nieuwste weekadvies nog niet heeft geopend."""
    if not week or week["seen"]:
        return ""
    n = week["count"]
    what = "%d %s aan te melden" % (n, "artikel" if n == 1 else "artikelen") if n else "niets aan te melden"
    return ('<div class="flash new" role="status"><b>Nieuw weekadvies beschikbaar</b> van %s: %s. '
            '<a href="/weekadvies?kanaal=%s&id=%d">Bekijk het weekadvies</a></div>') % (
        nl_date(week["created_at"]), what, quote(code), week["id"])


def weekadvies(ch, snap, data, others):
    code = ch["code"]
    rows = data.get("rows", [])
    p = data.get("params", {})
    if rows:
        trs = "".join(
            '<tr><td>%s</td><td><span class="prod">%s<span class="ptext"><span class="pname">%s</span><span class="pmeta">%s%s</span></span></span></td>'
            '<td class="num">%s</td><td class="num">%s</td><td>%s</td></tr>' % (
                pill(r["status"]), thumb(r["ean"], r.get("photo")), esc(r["name"] or ""), esc(r["ean"]),
                " · " + esc(r["article_code"]) if r.get("article_code") else "",
                nl(r.get("stock")), nl(r["cover"], 0) if r.get("cover") is not None else "–",
                ('<b>%s</b> × %s = <b>%s</b> st' % (nl(r["units"]), nl(r["unit"]), nl(r["deliver"]))) if r.get("units")
                else '<b>%s</b> st <span class="muted">(eenheid ontbreekt)</span>' % nl(r.get("need") or r.get("deliver")))
            for r in rows)
        table = ('<div class="scroll"><table class="grid"><thead><tr><th>Prioriteit</th><th>Artikel</th><th class="num">Voorraad</th>'
                 '<th class="num">Dekking (dgn)</th><th>Aanleveren</th></tr></thead><tbody>%s</tbody></table></div>') % trs
    else:
        table = '<p class="calm">In dit weekadvies hoefde niets aangemeld te worden.</p>'
    older = ""
    if others:
        older = '<section><h2>Eerdere weekadviezen</h2><ul class="plain">%s</ul></section>' % "".join(
            '<li><a href="/weekadvies?kanaal=%s&id=%d">%s</a> <span class="muted">voorraadstand %s</span></li>' % (
                quote(code), o["id"], nl_date(o["created_at"]), nl_date(o["date"])) for o in others)
    params = ""
    if p:
        params = " Parameters: doel %s, lead time %s, trigger %s dagen." % (p.get("target"), p.get("lead"), p.get("trigger"))
    return ('<p><a href="/?kanaal=%s">← Terug naar Aanvullen</a></p><h1>Weekadvies van %s</h1>'
            '<p class="muted">Momentopname van %s, op basis van de voorraadstand van %s.%s '
            'Dit overzicht verandert niet meer; de actuele stand staat op de pagina Aanvullen.</p>'
            '<section>%s</section>%s') % (
        quote(code), nl_date(snap["created_at"]), esc(snap["created_at"][:16]), nl_date(snap["date"]), params, table, older)



# --- zendingen voorbereiden en aanmaken ---------------------------------------
def approve_bar(todo, code, csrf, can_create):
    """Knoppen boven 'Nu aanmelden': het hele advies accorderen of eerst aanpassen."""
    if not can_create:
        return ""
    adjust = '<a class="button" href="/zending/nieuw?kanaal=%s">%s</a>' % (
        quote(code), "Aanpassen en zending voorbereiden" if todo else "Zelf een zending samenstellen")
    if not todo:
        return '<div class="approve">%s</div>' % adjust
    hidden = "".join('<input type="hidden" name="p_%s" value="%d">' % (r["ean"], r["deliver"]) for r in todo)
    return ('<div class="approve"><form method="post" action="/zending/nieuw"><input type="hidden" name="csrf" value="%s">'
            '<input type="hidden" name="kanaal" value="%s">%s<button class="primary">Hele advies accorderen (%d artikelen, %s stuks)</button></form>%s'
            '<span class="muted">Er wordt nog niets aangemaakt: bol geeft eerst de magazijnadressen terug.</span></div>') % (
        csrf, esc(code), hidden, len(todo), nl(sum(r["deliver"] for r in todo)), adjust)


def drafts_section(open_drafts, code, csrf=""):
    if not open_drafts:
        return ""
    label = {"adressen": "Wacht op adressen van bol", "klaar": "Klaar om aan te maken", "mislukt": "Mislukt"}
    trs = "".join(
        '<tr><td><a href="/zending/%d?kanaal=%s"><b>Voorbereiding %d</b></a><span class="pmeta">%s door %s</span></td>'
        '<td>%s</td><td class="num">%d</td><td class="num">%s</td><td class="num">%d van %d</td>'
        '<td><form method="post" action="/zending/%d/sluiten"><input type="hidden" name="csrf" value="%s">'
        '<input type="hidden" name="kanaal" value="%s"><button class="link">%s</button></form></td></tr>' % (
            d["id"], quote(code), d["id"], esc(d["created_at"][:16]), esc(d["username"] or ""),
            esc(label.get(d["status"], d["status"])), d["n_lines"], nl(d["pieces"]), d["n_done"], d["n_groups"],
            d["id"], csrf, esc(code), "Afsluiten" if d["n_done"] else "Verwijderen")
        for d in open_drafts)
    return ('<section><h2>Zendingen in voorbereiding</h2><div class="scroll"><table class="grid"><thead><tr><th>Voorbereiding</th>'
            '<th>Stand</th><th class="num">Artikelen</th><th class="num">Stuks</th><th class="num">Aangemaakt</th><th></th></tr></thead>'
            '<tbody>%s</tbody></table></div></section>') % trs


def new_shipment(result, ch, user):
    code = ch["code"]
    rows = [r for r in result["rows"] if r["mode"] == "normaal"]
    rows.sort(key=lambda r: (0 if r["need"] else 1, r["cover"] if r["cover"] is not None else 1e9))
    trs = "".join(
        '<tr><td>%s</td><td>%s</td><td class="num">%s</td><td>%s</td><td>%s</td><td class="num">%s</td>'
        '<td><input class="qty" type="number" name="p_%s" min="0" max="9999" step="1" value="%s" aria-label="Aantal stuks voor %s"></td></tr>' % (
            pill(r["status"]), product_cell(r, code), nl(r["stock"]), cover_cell(r, result["params"]), deliver_cell(r),
            nl(r["unit"]) if r["unit"] else '<span class="missing">ontbreekt</span>',
            r["ean"], r["deliver"] if r["need"] else "", esc(r["name"] or r["ean"]))
        for r in rows)
    return ('<p><a href="/?kanaal=%s">← Terug naar Aanvullen</a></p><h1>Zending voorbereiden</h1>'
            '<p class="muted">Vul per artikel het aantal stuks in dat mee moet; leeg of 0 gaat niet mee. De geadviseerde aantallen zijn al ingevuld. '
            'Na akkoord vraagt de tool bij bol op naar welk magazijn elk artikel moet. Er wordt dan nog niets aangemaakt.</p>'
            '<form method="post" action="/zending/nieuw"><input type="hidden" name="csrf" value="%s"><input type="hidden" name="kanaal" value="%s">'
            '<div class="scroll"><table class="grid"><thead><tr><th>Status</th><th>Artikel</th><th class="num">Voorraad</th><th>Dekking</th>'
            '<th>Advies</th><th class="num">Besteleenheid</th><th>Meesturen (stuks)</th></tr></thead><tbody>%s</tbody></table></div>'
            '<p class="formend"><button class="primary">Akkoord: adressen opvragen bij bol</button></p></form>') % (
        quote(code), esc(user["csrf"]), esc(code), trs)


def _address(a):
    if not a:
        return "adres onbekend"
    return "%s %s%s, %s %s%s" % (esc(str(a.get("streetName", ""))), esc(str(a.get("houseNumber", ""))),
                                 esc(str(a.get("houseNumberExtension") or "")), esc(str(a.get("zipCode", ""))),
                                 esc(str(a.get("city", ""))), " (%s)" % esc(str(a["attentionOf"])) if a.get("attentionOf") else "")


def _lines_table(lines, remove=None):
    """remove: (draft_id, csrf, kanaal) toont per regel een verwijderknop."""
    def units(l):
        u = l["order_unit"]
        if not u:
            return '<span class="missing">eenheid ontbreekt</span>'
        if l["pieces"] % u:
            return '<span class="missing">geen hele dozen van %d</span>' % u
        return "%s × %s" % (nl(l["pieces"] // u), nl(u))
    trs = "".join(
        '<tr><td><span class="prod">%s<span class="ptext"><span class="pname">%s</span><span class="pmeta">%s%s</span></span></span></td>'
        '<td class="num"><b>%s</b></td><td>%s</td>%s</tr>' % (
            thumb(l["ean"], l["photo"]), esc(l["title"] or ""), esc(l["ean"]),
            " · " + esc(l["article_code"]) if l["article_code"] else "", nl(l["pieces"]), units(l),
            ('<td><form method="post" action="/zending/%d/regel-verwijderen"><input type="hidden" name="csrf" value="%s">'
             '<input type="hidden" name="kanaal" value="%s"><input type="hidden" name="ean" value="%s">'
             '<button class="link" aria-label="Verwijder %s uit de zending">Verwijderen</button></form></td>' % (
                 remove[0], remove[1], esc(remove[2]), esc(l["ean"]), esc(l["title"] or l["ean"]))) if remove else "")
        for l in lines)
    return ('<div class="scroll"><table class="grid"><thead><tr><th>Artikel</th><th class="num">Stuks</th><th>Dozen</th>%s</tr></thead>'
            '<tbody>%s</tbody></table></div>') % ("<th></th>" if remove else "", trs)


def shipment_page(ch, user, draft, groups, unassigned, all_lines, dates, refs, transporters, demo, remote=False):
    from .shipments import STATE_LABEL
    code, csrf = ch["code"], esc(user["csrf"])
    head = ('<p><a href="/?kanaal=%s">← Terug naar Aanvullen</a></p><h1>Zending voorbereiden</h1>'
            '<p class="muted">Voorbereiding %d, gestart op %s door %s.</p>') % (quote(code), draft["id"], esc(draft["created_at"][:16]), esc(draft["username"] or ""))
    if demo:
        head += '<div class="flash warn">Testomgeving van bol: er wordt niets echt aangemaakt.</div>'
    close = ('<form method="post" action="/zending/%d/sluiten" class="formend inline"><input type="hidden" name="csrf" value="%s">'
             '<input type="hidden" name="kanaal" value="%s"><button class="button danger">%s</button> '
             '<span class="muted">%s</span></form>') % (
        draft["id"], csrf, esc(code),
        "Voorbereiding afsluiten" if remote else "Voorbereiding verwijderen",
        "Wat nog niet is aangemaakt vervalt. Zendingen die al bij bol staan blijven bestaan." if remote
        else "Er is nog niets bij bol aangemaakt; alles in deze voorbereiding vervalt.")
    if draft["status"] == "adressen":
        return head + ('<div class="calm wait" data-refresh="4">' + WAIT + '<span><b>Bol zoekt de magazijnadressen op.</b> Dit duurt meestal minder dan een minuut; '
                       'deze pagina ververst vanzelf.</span></div><section><h2>Goedgekeurde regels</h2>%s</section>%s') % (_lines_table(all_lines), close)
    if draft["status"] == "mislukt":
        return head + '<div class="flash bad" role="alert">Bol kon de adressen niet bepalen: %s</div><section>%s</section>%s' % (
            esc(draft["error"] or ""), _lines_table(all_lines), close)
    out = [head]
    if draft["status"] == "gesloten":
        out.append('<div class="flash">Deze voorbereiding is gesloten.</div>')
    if unassigned:
        out.append('<div class="flash bad" role="alert">Voor %d artikelen gaf bol geen magazijn terug. Die kunnen niet mee in deze zending.</div>%s' % (
            len(unassigned), _lines_table(unassigned)))
    waiting = False
    for n, item in enumerate(groups, 1):
        g = item["g"]
        pieces = sum(l["pieces"] for l in item["lines"])
        state = g["state"]
        editable = state in ("open", "mislukt") and draft["status"] == "klaar"
        body = _lines_table(item["lines"], (draft["id"], csrf, code) if editable else None)
        if state in ("open", "mislukt"):
            err = '<div class="flash bad" role="alert">Aanmaken is mislukt: %s</div>' % esc(g["error"] or "") if state == "mislukt" else ""
            if draft["status"] != "klaar":
                form = err
            else:
                opts_t = "".join('<option value="%s"%s>%s</option>' % (t, " selected" if t == (g["transporter"] or "DHL") else "", "Anders" if t == "OTHER" else t) for t in transporters)
                opts_d = "".join('<option value="%s"%s>%s</option>' % (d, " selected" if d == g["expected"] else "", nl_date(d)) for d in dates)
                form = err + (
                    '<form method="post" action="/zending/%d/aanmaken" class="edit"><input type="hidden" name="csrf" value="%s">'
                    '<input type="hidden" name="kanaal" value="%s"><input type="hidden" name="groep" value="%d">'
                    '<label>Kenmerk<input name="reference" value="%s" required pattern="[A-Z0-9]+" maxlength="30"></label>'
                    '<label>Vervoerder<select name="transporter">%s</select></label>'
                    '<label>Leverdatum bij bol (wanneer de zending daar aankomt)<select name="expected" required>%s</select></label>'
                    '<label>Aantal laadeenheden (pallets of dozen)<input name="carriers" type="number" min="1" max="66" value="%s" required></label>'
                    '<label>Labelservice<select name="labeling"><option value="nee">Wij labelen zelf</option><option value="ja"%s>Bol labelt de artikelen</option></select></label>'
                    '<label class="wide check"><input type="checkbox" name="gecontroleerd" value="ja" required> Ik heb de aantallen en het adres gecontroleerd</label>'
                    '<button class="primary">Zending aanmaken bij bol</button></form>'
                    '<form method="post" action="/zending/%d/groep-verwijderen" class="formend"><input type="hidden" name="csrf" value="%s">'
                    '<input type="hidden" name="kanaal" value="%s"><input type="hidden" name="groep" value="%d">'
                    '<button class="link">Deze deelzending verwijderen</button></form>') % (
                    draft["id"], csrf, esc(code), g["group_no"], esc(g["reference"] or refs.get(g["group_no"], "")), opts_t,
                    ('<option value="">Kies een datum</option>' + opts_d) if opts_d else '<option value="">geen datums beschikbaar</option>', g["carriers"] or 1, " selected" if g["labeling"] else "",
                    draft["id"], csrf, esc(code), g["group_no"])
            status = '<span class="pill fill">Nog niet aangemaakt</span>'
        elif state == "verstuurd":
            waiting = True
            status = '<span class="pill dead">Wordt aangemaakt</span>'
            form = '<div class="calm wait">' + WAIT + '<span><b>Bol verwerkt de zending %s.</b> Deze pagina ververst vanzelf.</span></div>' % esc(g["reference"] or "")
        elif state == "annuleren":
            waiting = True
            status = '<span class="pill dead">Wordt geannuleerd</span>'
            form = '<div class="calm wait">' + WAIT + '<span><b>Bol verwerkt de annulering.</b> Deze pagina ververst vanzelf.</span></div>'
        elif state == "aangemaakt":
            status = '<span class="pill ok">Aangemaakt bij bol</span>'
            err = '<div class="flash bad" role="alert">%s</div>' % esc(g["error"]) if g["error"] else ""
            form = err + ('<p>Zending <b>%s</b> staat in het bol-verkopersportaal (nummer %s): %s, leverdatum %s, %s laadeenheden, %s. '
                          'Aangemaakt door %s op %s.</p>'
                          '<form method="post" action="/zending/%d/annuleren" class="inline"><input type="hidden" name="csrf" value="%s">'
                          '<input type="hidden" name="kanaal" value="%s"><input type="hidden" name="groep" value="%d">'
                          '<label class="check"><input type="checkbox" name="zeker" value="ja" required> Ik wil deze zending bij bol annuleren</label>'
                          '<button class="button">Annuleren bij bol</button></form>'
                          '<p class="muted">Annuleren kan alleen zolang de zending bij bol nog op "Aangemeld" staat.</p>') % (
                esc(g["reference"] or ""), esc(g["ship_id"] or "onbekend"), esc(g["transporter"] or ""), nl_date(g["expected"]),
                g["carriers"], "bol labelt" if g["labeling"] else "zelf labelen", esc(g["created_by"] or ""), esc((g["created_at"] or "")[:16]),
                draft["id"], csrf, esc(code), g["group_no"])
        elif state == "geannuleerd":
            status = '<span class="pill dead">Geannuleerd bij bol</span>'
            form = '<p class="muted">Zending %s is bij bol geannuleerd.</p>' % esc(g["reference"] or "")
        else:
            status = '<span class="pill dead">Vervallen</span>'
            form = ""
        out.append('<section class="ship"><div class="headrow"><div><h2>Deelzending %d naar %s</h2><p class="muted">%d artikelen, %s stuks</p></div>%s</div>%s%s</section>' % (
            n, _address(item["address"]), len(item["lines"]), nl(pieces), status, body, form))
    if waiting:
        out.append('<span data-refresh="4"></span>')
    if draft["status"] == "klaar":
        out.append(close)
    return "".join(out)


def dashboard(result, ch, user, handoffs, last_run, stale_days, devs=(), ships=(), week=None, can_create=False, open_drafts=()):
    code = ch["code"]
    rows = result["rows"]
    if not rows:
        hint = ('Een beheerder kan bij Instellingen de bol-API koppelen of een LvB-dagrapport uploaden.' if ch["adapter"] == "bol"
                else 'De koppeling met dit kanaal is nog niet ingesteld. Zodra de API-gegevens er zijn, verschijnen hier voorraad, verkopen en zendingen.')
        return '<section class="empty"><h1>Nog geen gegevens</h1><p>Er is voor %s nog niets opgehaald. %s</p></section>' % (esc(ch["name"]), hint)
    todo = [r for r in rows if r["need"] > 0 and r["status"] in ("Kritiek", "Aanvullen")]
    crit = [r for r in rows if r["status"] == "Kritiek"]
    dead = [r for r in rows if r["status"] == "Dood"]
    over = [r for r in rows if r["status"] == "Overstock"]
    no_unit = [r for r in rows if r["unit"] is None and r["mode"] == "normaal"]
    csrf = esc(user["csrf"])

    warn = week_banner(week, code)
    if last_run and not last_run["ok"]:
        warn += '<div class="flash bad" role="alert">De laatste verversing is mislukt: %s</div>' % esc(last_run["message"] or "")
    if stale_days is not None and stale_days >= 2:
        warn += '<div class="flash bad" role="alert">De voorraadstand is %d dagen oud. Het advies kan achterlopen.</div>' % stale_days

    if devs:
        warn += '<div class="flash bad" role="alert">%d %s bij zendingen. <a href="#afwijkingen">Bekijk</a></div>' % (
            len(devs), "afwijking" if len(devs) == 1 else "afwijkingen")

    tiles = (
        '<section class="tiles">'
        '<div class="tile"><span class="k">Nu aanmelden</span><span class="v">%s</span><span class="s">%s stuks in totaal</span></div>'
        '<div class="tile %s"><span class="k">Kritiek</span><span class="v">%s</span><span class="s">dekking onder %s dagen</span></div>'
        '<a class="tile" href="/artikelen?kanaal=%s&status=Dood"><span class="k">Dode voorraad</span><span class="v">%s</span><span class="s">%s stuks zonder verkoop</span></a>'
        '<a class="tile" href="/artikelen?kanaal=%s&status=Overstock"><span class="k">Overstock</span><span class="v">%s</span><span class="s">dekking boven %s dagen</span></a>'
        '</section>') % (
        len(todo), nl(sum(r["deliver"] for r in todo)),
        "alarm" if crit else "", len(crit), result["params"]["reorder_point"],
        quote(code), len(dead), nl(sum(r["stock"] for r in dead)),
        quote(code), len(over), nl(1.5 * result["params"]["target"]))

    if todo:
        trs = []
        for r in todo:
            trs.append(
                '<tr><td>%s</td><td>%s</td><td class="num">%s</td><td>%s</td><td class="num">%s</td><td>%s</td><td>%s</td>'
                '<td><form method="post" action="/afvinken"><input type="hidden" name="csrf" value="%s">'
                '<input type="hidden" name="kanaal" value="%s"><input type="hidden" name="ean" value="%s">'
                '<input type="hidden" name="units" value="%s"><input type="hidden" name="pieces" value="%s">'
                '<button class="primary small">Aangemeld</button></form></td></tr>' % (
                    pill(r["status"]), product_cell(r, code), nl(r["stock"]), cover_cell(r, result["params"]),
                    nl(r["inbound"]) if r["inbound"] else "–", deliver_cell(r), signals_html(r),
                    csrf, esc(code), r["ean"], r["units"] or "", r["deliver"]))
        todo_html = ('<div class="scroll"><table class="grid"><thead><tr><th>Prioriteit</th><th>Artikel</th><th class="num">Voorraad</th>'
                     '<th>Dekking</th><th class="num">Onderweg</th><th>Aanleveren</th><th>Signalen</th><th></th></tr></thead>'
                     '<tbody>%s</tbody></table></div>') % "".join(trs)
    else:
        todo_html = '<p class="calm">Geen artikelen onder de besteltrigger van %s dagen. Er hoeft nu niets aangemeld te worden.</p>' % result["params"]["trigger"]

    done_html = ""
    if handoffs:
        items = []
        for h in handoffs:
            items.append(
                '<tr><td>%s</td><td>%s<span class="pmeta">%s</span></td><td class="num">%s st</td><td>%s</td>'
                '<td><form method="post" action="/afvinken/ongedaan"><input type="hidden" name="csrf" value="%s">'
                '<input type="hidden" name="kanaal" value="%s"><input type="hidden" name="id" value="%d">'
                '<button class="link">Ongedaan maken</button></form></td></tr>' % (
                    esc(h["created_at"][:16]), esc(h["title"] or ""), esc(h["ean"]), nl(h["pieces"]),
                    esc(h["username"] or ""), csrf, esc(code), h["id"]))
        done_html = ('<section><h2>Recent aangemeld</h2><p class="muted">Telt mee als onderweg tot de marketplace de zending zelf doorgeeft.</p>'
                     '<div class="scroll"><table class="grid"><thead><tr><th>Wanneer</th><th>Artikel</th><th class="num">Aantal</th><th>Door</th><th></th></tr></thead>'
                     '<tbody>%s</tbody></table></div></section>') % "".join(items)

    attention = [r for r in rows if r not in todo and any(k in ("up", "down", "warn") for k, _ in r["signals"])]
    att_html = ""
    if attention:
        att_html = '<section><h2>Aandachtspunten</h2><div class="scroll"><table class="grid"><thead><tr><th>Status</th><th>Artikel</th><th class="num">Voorraad</th><th>Dekking</th><th>Signalen</th></tr></thead><tbody>%s</tbody></table></div></section>' % "".join(
            '<tr><td>%s</td><td>%s</td><td class="num">%s</td><td>%s</td><td>%s</td></tr>' % (
                pill(r["status"]), product_cell(r, code), nl(r["stock"]), cover_cell(r, result["params"]), signals_html(r))
            for r in attention)
    unit_html = ""
    if no_unit and user["role"] == "beheer":
        unit_html = '<div class="flash warn">%d artikelen hebben nog geen besteleenheid. <a href="/artikelen?kanaal=%s&zonder=1">Bekijk en vul aan</a></div>' % (len(no_unit), quote(code))

    return ('%s<div class="headrow"><div><h1>Aanvullen</h1><p class="muted">%s</p></div>'
            '<div class="actions">%s<a class="button" href="/export.xlsx?kanaal=%s">Excel voor logistiek</a></div></div>%s%s'
            '<section><h2>Nu aanmelden</h2>%s%s</section>%s%s%s%s') % (
        warn, freshness(result, last_run),
        '<a class="button" href="/weekadvies?kanaal=%s&id=%d">Weekadvies van %s</a>' % (quote(code), week["id"], nl_date(week["created_at"])[:-5]) if week else "",
        quote(code), tiles, unit_html, approve_bar(todo, code, csrf, can_create), todo_html,
        drafts_section(open_drafts, code, csrf), shipments_section(devs, ships, code, csrf), done_html, att_html)


def articles(result, ch, status_filter, only_no_unit):
    code = ch["code"]
    rows = result["rows"]
    counts = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    chips = ['<a class="chip%s" href="/artikelen?kanaal=%s">Alle <b>%d</b></a>' % (
        "" if status_filter or only_no_unit else " on", quote(code), len(rows))]
    for status in ["Kritiek", "Aanvullen", "OK", "Overstock", "Dood", "Niet aanvullen"]:
        if counts.get(status):
            chips.append('<a class="chip%s" href="/artikelen?kanaal=%s&status=%s">%s <b>%d</b></a>' % (
                " on" if status == status_filter else "", quote(code), quote(status), esc(status), counts[status]))
    if status_filter:
        rows = [r for r in rows if r["status"] == status_filter]
    if only_no_unit:
        rows = [r for r in rows if r["unit"] is None and r["mode"] == "normaal"]
    trs = []
    for r in rows:
        v28 = ' <span class="muted">/ %s</span>' % nl(r["v28"], 2) if r["v28"] is not None else ""
        trs.append(
            '<tr data-q="%s"><td>%s</td><td>%s</td><td class="num">%s</td><td class="num">%s</td>'
            '<td><span class="sales"><b>%s</b>%s</span></td><td class="num">%s%s</td><td>%s</td><td class="num">%s</td><td>%s</td><td>%s</td></tr>' % (
                esc((r["name"] + " " + r["ean"] + " " + r["article_code"]).lower()),
                pill(r["status"]), product_cell(r, code), nl(r["stock"]), nl(r["inbound"]) if r["inbound"] else "–",
                nl(r["ordered"]), spark(r["series"]), nl(r["v"], 2), v28, cover_cell(r, result["params"]),
                nl(r["unit"]) if r["unit"] else '<span class="missing">ontbreekt</span>',
                deliver_cell(r), signals_html(r)))
    head28 = "Dagafzet <span class=\"muted\">(%d / 28 dgn)</span>" % result["params"]["velocity"] if result["has28"] else "Dagafzet"
    return ('<div class="headrow"><div><h1>Alle artikelen</h1><p class="muted">%d artikelen · voorraadstand van %s</p></div>'
            '<input type="search" id="zoek" placeholder="Zoek op naam, EAN of artikelcode" aria-label="Zoek artikel"></div>'
            '<div class="chips">%s</div>'
            '<div class="scroll"><table class="grid" id="tabel"><thead><tr><th>Status</th><th>Artikel</th><th class="num">Voorraad</th><th class="num">Onderweg</th>'
            '<th>Besteld %d dgn</th><th class="num">%s</th><th>Dekking</th><th class="num">Eenheid</th><th>Advies</th><th>Signalen</th></tr></thead>'
            '<tbody>%s</tbody></table></div><p class="muted" id="leeg" hidden>Geen artikelen gevonden.</p>') % (
        len(rows), nl_date(result["ref_date"]), "".join(chips), result["params"]["velocity"], head28, "".join(trs))


def bars28(history):
    """history: lijst (datum, aantal), oud naar nieuw."""
    if not history:
        return '<p class="muted">Nog geen verkoophistorie.</p>'
    W, H, pad = 640, 150, 18
    top = max(max(v for _, v in history), 1)
    bw = (W - 2 * pad) / len(history)
    out = ['<line class="axis" x1="%d" y1="%d" x2="%d" y2="%d"/>' % (pad, H - pad, W - pad, H - pad)]
    for i, (d, v) in enumerate(history):
        h = (v / top) * (H - 2 * pad - 12)
        x = pad + i * bw
        out.append('<rect class="b" x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="2"><title>%s: %d besteld</title></rect>' % (
            x + 1.5, H - pad - h, max(2.0, bw - 3), max(h, 0.5 if v else 0), nl_date(d), v))
        if v:
            out.append('<text class="lbl" x="%.1f" y="%.1f" text-anchor="middle">%d</text>' % (x + bw / 2, H - pad - h - 3, v))
        if i % 7 == 0 or i == len(history) - 1:
            out.append('<text class="day" x="%.1f" y="%d" text-anchor="middle">%s</text>' % (x + bw / 2, H - 4, esc(nl_date(d)[:-5])))
    return '<svg class="chart" viewBox="0 0 %d %d" role="img" aria-label="Besteld per dag">%s</svg>' % (W, H, "".join(out))


def article(r, ch, user, history, product, params):
    code = ch["code"]
    facts = [("Voorraad", nl(r["stock"]) + " st"), ("Onderweg", nl(r["inbound"]) + " st"),
             ("Besteld (%d dgn)" % params["velocity"], nl(r["ordered"])),
             ("Besteld (28 dgn)", nl(r["ordered28"]) if r["ordered28"] is not None else "nog geen 28 dagen historie"),
             ("Dagafzet", nl(r["v"], 2) + (" (28 dgn: %s)" % nl(r["v28"], 2) if r["v28"] is not None else "")),
             ("Dagen dekking", nl(r["cover"], 1) if r["cover"] is not None else "geen verkoop"),
             ("Voorraad bij aankomst", nl(max(r["arrival_stock"], 0)) + " st"),
             ("Retouren", nl(r["returns"])), ("Onverkoopbaar", nl(r["unsellable"])),
             ("Besteleenheid", nl(r["unit"]) if r["unit"] else "ontbreekt"),
             ("Advies", deliver_cell(r))]
    facts_html = "".join('<div><dt>%s</dt><dd>%s</dd></div>' % (esc(k), v) for k, v in facts)
    form = ""
    if user["role"] == "beheer":
        mode = product["mode"] or "normaal"
        opts = "".join('<option value="%s"%s>%s</option>' % (v, " selected" if v == mode else "", label) for v, label in
                       [("normaal", "Normaal aanvullen"), ("eol", "End of life: niet aanvullen"), ("uit", "Handmatig uitgezet")])
        form = ('<section><h2>Artikelgegevens</h2><form method="post" action="/artikel/%s" class="edit">'
                '<input type="hidden" name="csrf" value="%s"><input type="hidden" name="kanaal" value="%s">'
                '<label>Artikelcode<input name="article_code" value="%s"></label>'
                '<label>Besteleenheid (stuks per doos)<input name="order_unit" type="number" min="1" max="10000" value="%s" placeholder="nog niet bekend"></label>'
                '<label>Aanvullen<select name="mode">%s</select></label>'
                '<label class="wide">Notitie<input name="note" value="%s" maxlength="200"></label>'
                '<button class="primary">Opslaan</button></form>'
                '<p class="muted">Bron besteleenheid: %s. Deze gegevens gelden voor alle kanalen.</p></section>') % (
            r["ean"], esc(user["csrf"]), esc(code), esc(product["article_code"] or ""),
            product["order_unit"] or "", opts, esc(product["note"] or ""), esc(product["unit_source"] or "onbekend"))
    return ('<p><a href="/artikelen?kanaal=%s">← Alle artikelen</a></p>'
            '<div class="headrow"><div><h1>%s</h1><p class="muted">%s%s · %s</p></div>%s</div>%s%s'
            '<dl class="facts">%s</dl><section><h2>Besteld per dag</h2>%s</section>%s') % (
        quote(code), esc(r["name"] or r["ean"]), ("" if r["ean"].startswith("29") else "EAN ") + ident(r["ean"], r["article_code"]),
        "", esc(ch["name"]),
        pill(r["status"]), signals_html(r),
        '<img class="photo" src="/foto/%s.jpg" alt="Foto van %s" width="220" height="220">' % (esc(r["ean"]), esc(r["name"] or r["ean"])) if r.get("photo") else "",
        facts_html, bars28(history), form)


def settings(ch, user, runs, users, api_ready, mail_ready):
    csrf = esc(user["csrf"])
    code = esc(ch["code"])
    fields = [("target_days", "Doel-dekking (dagen)"), ("lead_days", "Lead time (dagen)"),
              ("buffer_days", "Veiligheidsbuffer (dagen)"), ("trigger_days", "Besteltrigger (dagen dekking)"),
              ("velocity_days", "Velocity-periode (dagen)")]
    inputs = "".join('<label>%s<input type="number" name="%s" min="1" max="365" value="%d" required></label>' % (label, name, ch[name])
                     for name, label in fields)
    runs_html = "".join('<tr><td>%s</td><td>%s</td><td>%s</td></tr>' % (
        esc((r["finished"] or r["started"] or "")[:16]),
        '<span class="pill ok">Gelukt</span>' if r["ok"] else ('<span class="pill crit">Mislukt</span>' if r["ok"] is not None else '<span class="pill dead">Bezig</span>'),
        esc(r["message"] or "")) for r in runs) or '<tr><td colspan="3" class="muted">Nog geen verversingen.</td></tr>'
    users_html = "".join(
        '<tr><td>%s</td><td>%s</td><td>%s</td></tr>' % (
            esc(u["username"]), esc(u["role"]),
            "" if u["id"] == user["id"] else
            '<form method="post" action="/gebruiker/verwijderen"><input type="hidden" name="csrf" value="%s"><input type="hidden" name="id" value="%d"><button class="link">Verwijderen</button></form>' % (csrf, u["id"]))
        for u in users)
    api = ('<p><span class="pill ok">Gekoppeld</span> De API-gegevens staan in config.env.</p>'
           '<form method="post" action="/verversen"><input type="hidden" name="csrf" value="%s"><input type="hidden" name="kanaal" value="%s"><button class="button">Nu verversen</button></form>' % (csrf, code)
           ) if api_ready else '<p><span class="pill fill">Niet gekoppeld</span> Vul BOL_CLIENT_ID en BOL_CLIENT_SECRET in config.env in en herstart de dienst.</p>'
    if ch["adapter"] == "bol":
        api += ('<h3>LvB-dagrapport uploaden</h3><p class="muted">Startvulling van de historie, of terugvaloptie als de API niet werkt. Gebruik de originele bestandsnaam van bol.</p>'
                '<form method="post" action="/rapport" enctype="multipart/form-data" class="inline"><input type="hidden" name="csrf" value="%s"><input type="hidden" name="kanaal" value="%s">'
                '<input type="file" name="bestand" accept=".xlsx" required aria-label="LvB-dagrapport"><button class="button">Uploaden</button></form>') % (csrf, code)
    else:
        api = ('<p><span class="pill fill">Niet gekoppeld</span> De koppeling met %s wordt gebouwd zodra de API-gegevens er zijn. '
               'De parameters hierboven kun je alvast instellen.</p>') % esc(ch["name"])
    mail = "De weekmail is ingesteld." if mail_ready else "De weekmail is nog niet ingesteld: vul de SMTP-gegevens en MAIL_TO in config.env in."
    return ('<h1>Instellingen</h1>'
            '<section><h2>Parameters voor %s</h2><form method="post" action="/instellingen" class="edit">'
            '<input type="hidden" name="csrf" value="%s"><input type="hidden" name="kanaal" value="%s">%s'
            '<button class="primary">Opslaan</button></form><p class="muted">Bestelpunt (kritiek-grens) = lead time + buffer = %d dagen.</p></section>'
            '<section><h2>Koppeling</h2>%s'
            '<h3>Laatste verversingen</h3><div class="scroll"><table class="grid"><thead><tr><th>Wanneer</th><th>Resultaat</th><th>Melding</th></tr></thead><tbody>%s</tbody></table></div>'
            '<p class="muted">%s</p></section>'
            '<section><h2>Gebruikers</h2><div class="scroll"><table class="grid"><thead><tr><th>Gebruikersnaam</th><th>Rol</th><th></th></tr></thead><tbody>%s</tbody></table></div>'
            '<h3>Gebruiker toevoegen of wachtwoord opnieuw instellen</h3><form method="post" action="/gebruiker" class="edit"><input type="hidden" name="csrf" value="%s">'
            '<label>Gebruikersnaam<input name="username" required autocomplete="off"></label>'
            '<label>Wachtwoord (minstens 10 tekens)<input name="password" type="password" minlength="10" required autocomplete="new-password"></label>'
            '<label>Rol<select name="role"><option value="logistiek">Logistiek: bekijken en afvinken</option><option value="beheer">Beheer: alles</option></select></label>'
            '<button class="primary">Opslaan</button></form></section>') % (
        esc(ch["name"]), csrf, code, inputs, ch["lead_days"] + ch["buffer_days"], api,
        runs_html, mail, users_html, csrf)


def account(user):
    return ('<h1>Mijn account</h1><p class="muted">Ingelogd als %s (%s).</p><section><h2>Wachtwoord wijzigen</h2>'
            '<form method="post" action="/account" class="edit"><input type="hidden" name="csrf" value="%s">'
            '<label>Huidig wachtwoord<input name="current" type="password" required autocomplete="current-password"></label>'
            '<label>Nieuw wachtwoord (minstens 10 tekens)<input name="new" type="password" minlength="10" required autocomplete="new-password"></label>'
            '<button class="primary">Wijzigen</button></form></section>') % (esc(user["username"]), esc(user["role"]), esc(user["csrf"]))
