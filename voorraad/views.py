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


def product_cell(r, code):
    return ('<a class="prod" href="/artikel/%s?kanaal=%s"><span class="pname">%s</span>'
            '<span class="pmeta">%s%s</span></a>') % (
        r["ean"], quote(code), esc(r["name"] or "(naam onbekend)"), esc(r["ean"]),
        " · " + esc(r["article_code"]) if r["article_code"] else "")


def deliver_cell(r):
    if not r["need"]:
        return '<span class="muted">–</span>'
    if r["units"]:
        return '<b>%s</b> × %s = <b>%s</b> st' % (nl(r["units"]), nl(r["unit"]), nl(r["deliver"]))
    return '<b>%s</b> st <span class="muted">(eenheid ontbreekt)</span>' % nl(r["need"])


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
        if len(channels) > 1:
            chan = '<form method="get" class="chan"><label class="sr" for="kanaal">Kanaal</label><select id="kanaal" name="kanaal" data-autosubmit>%s</select></form>' % "".join(
                '<option value="%s"%s>%s</option>' % (esc(c["code"]), " selected" if c["code"] == current else "", esc(c["name"]))
                for c in channels)
        elif channels:
            chan = '<span class="chan-one">%s</span>' % esc(channels[0]["name"])
        nav = ('<header class="top"><a class="brand" href="/%s">Voorraadchecker</a>%s<nav>%s</nav>'
               '<div class="who"><a href="/account">%s</a><form method="post" action="/uitloggen">'
               '<input type="hidden" name="csrf" value="%s"><button class="link">Uitloggen</button></form></div></header>') % (
            q, chan, links, esc(user["username"]), esc(user["csrf"]))
    note = ""
    if flash:
        note = '<div class="flash %s" role="status">%s</div>' % (esc(flash[0]), esc(flash[1]))
    return ('<!doctype html><html lang="nl"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>%s · Voorraadchecker</title><link rel="stylesheet" href="/static/style.css">'
            '</head><body>%s<main>%s%s</main><script src="/static/app.js" defer></script></body></html>') % (
        esc(title), nav, note, body)


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


def dashboard(result, ch, user, handoffs, last_run, stale_days):
    code = ch["code"]
    rows = result["rows"]
    if not rows:
        return ('<section class="empty"><h1>Nog geen gegevens</h1><p>Er is voor %s nog niets opgehaald. '
                'Een beheerder kan bij Instellingen de bol-API koppelen of een LvB-dagrapport uploaden.</p></section>') % esc(ch["name"])
    todo = [r for r in rows if r["need"] > 0 and r["status"] in ("Kritiek", "Aanvullen")]
    crit = [r for r in rows if r["status"] == "Kritiek"]
    dead = [r for r in rows if r["status"] == "Dood"]
    over = [r for r in rows if r["status"] == "Overstock"]
    no_unit = [r for r in rows if r["unit"] is None and r["mode"] == "normaal"]
    csrf = esc(user["csrf"])

    warn = ""
    if last_run and not last_run["ok"]:
        warn += '<div class="flash bad" role="alert">De laatste verversing is mislukt: %s</div>' % esc(last_run["message"] or "")
    if stale_days is not None and stale_days >= 2:
        warn += '<div class="flash bad" role="alert">De voorraadstand is %d dagen oud. Het advies kan achterlopen.</div>' % stale_days

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
        done_html = ('<section><h2>Recent aangemeld</h2><p class="muted">Telt mee als onderweg tot bol de zending zelf doorgeeft.</p>'
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
            '<a class="button" href="/export.xlsx?kanaal=%s">Excel voor logistiek</a></div>%s%s'
            '<section><h2>Nu aanmelden</h2>%s</section>%s%s') % (
        warn, freshness(result, last_run), quote(code), tiles, unit_html, todo_html, done_html, att_html)


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
            '<div class="headrow"><div><h1>%s</h1><p class="muted">EAN %s%s · %s</p></div>%s</div>%s'
            '<dl class="facts">%s</dl><section><h2>Besteld per dag</h2>%s</section>%s') % (
        quote(code), esc(r["name"] or r["ean"]), esc(r["ean"]),
        " · " + esc(r["article_code"]) if r["article_code"] else "", esc(ch["name"]),
        pill(r["status"]), signals_html(r), facts_html, bars28(history), form)


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
    mail = "De weekmail is ingesteld." if mail_ready else "De weekmail is nog niet ingesteld: vul de SMTP-gegevens en MAIL_TO in config.env in."
    return ('<h1>Instellingen</h1>'
            '<section><h2>Parameters voor %s</h2><form method="post" action="/instellingen" class="edit">'
            '<input type="hidden" name="csrf" value="%s"><input type="hidden" name="kanaal" value="%s">%s'
            '<button class="primary">Opslaan</button></form><p class="muted">Bestelpunt (kritiek-grens) = lead time + buffer = %d dagen.</p></section>'
            '<section><h2>Koppeling</h2>%s<h3>LvB-dagrapport uploaden</h3><p class="muted">Startvulling van de historie, of terugvaloptie als de API niet werkt. Gebruik de originele bestandsnaam van bol.</p>'
            '<form method="post" action="/rapport" enctype="multipart/form-data" class="inline"><input type="hidden" name="csrf" value="%s"><input type="hidden" name="kanaal" value="%s">'
            '<input type="file" name="bestand" accept=".xlsx" required aria-label="LvB-dagrapport"><button class="button">Uploaden</button></form>'
            '<h3>Laatste verversingen</h3><div class="scroll"><table class="grid"><thead><tr><th>Wanneer</th><th>Resultaat</th><th>Melding</th></tr></thead><tbody>%s</tbody></table></div>'
            '<p class="muted">%s</p></section>'
            '<section><h2>Gebruikers</h2><div class="scroll"><table class="grid"><thead><tr><th>Gebruikersnaam</th><th>Rol</th><th></th></tr></thead><tbody>%s</tbody></table></div>'
            '<h3>Gebruiker toevoegen of wachtwoord opnieuw instellen</h3><form method="post" action="/gebruiker" class="edit"><input type="hidden" name="csrf" value="%s">'
            '<label>Gebruikersnaam<input name="username" required autocomplete="off"></label>'
            '<label>Wachtwoord (minstens 10 tekens)<input name="password" type="password" minlength="10" required autocomplete="new-password"></label>'
            '<label>Rol<select name="role"><option value="logistiek">Logistiek: bekijken en afvinken</option><option value="beheer">Beheer: alles</option></select></label>'
            '<button class="primary">Opslaan</button></form></section>') % (
        esc(ch["name"]), csrf, code, inputs, ch["lead_days"] + ch["buffer_days"], api, csrf, code,
        runs_html, mail, users_html, csrf)


def account(user):
    return ('<h1>Mijn account</h1><p class="muted">Ingelogd als %s (%s).</p><section><h2>Wachtwoord wijzigen</h2>'
            '<form method="post" action="/account" class="edit"><input type="hidden" name="csrf" value="%s">'
            '<label>Huidig wachtwoord<input name="current" type="password" required autocomplete="current-password"></label>'
            '<label>Nieuw wachtwoord (minstens 10 tekens)<input name="new" type="password" minlength="10" required autocomplete="new-password"></label>'
            '<button class="primary">Wijzigen</button></form></section>') % (esc(user["username"]), esc(user["role"]), esc(user["csrf"]))
