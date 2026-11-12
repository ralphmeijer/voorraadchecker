"""Wekelijks bevroren advies: momentopname in de database plus e-mail met Excel-bijlage."""
from __future__ import annotations

import json
import smtplib
import ssl
from email.message import EmailMessage
from html import escape as esc

from . import calc, config, db, excel
from .views import nl, nl_date


def weekly(conn, send: bool = True) -> bool:
    ok = True
    for ch in db.channels(conn):
        result = calc.compute(conn, ch)
        if not result["ref_date"]:
            print("%s: nog geen gegevens, weekadvies overgeslagen" % ch["name"])
            continue
        todo = calc.logistics_rows(result)
        frozen = [{k: r[k] for k in ("ean", "article_code", "name", "unit", "units", "deliver", "status", "stock", "cover")}
                  for r in todo]
        conn.execute("INSERT INTO snapshots(channel, date, created_at, data) VALUES(?,?,datetime('now','localtime'),?)",
                     (ch["code"], result["ref_date"], json.dumps({"params": result["params"], "rows": frozen})))
        conn.commit()
        print("%s: weekadvies vastgelegd (%d artikelen)" % (ch["name"], len(todo)))
        if send:
            ok = _send(ch, result, todo) and ok
    return ok


def _send(ch, result, todo) -> bool:
    host, to = config.get("SMTP_HOST"), config.get("MAIL_TO")
    if not host or not to:
        print("Weekmail niet verstuurd: SMTP_HOST of MAIL_TO ontbreekt in config.env")
        return False
    rows = result["rows"]
    crit = [r for r in todo if r["status"] == "Kritiek"]
    signals = [(r, s) for r in rows for s in r["signals"] if s[0] in ("up", "down", "warn")]
    base = config.get("VC_BASE_URL")

    lines = ["Weekadvies %s, voorraadstand van %s" % (ch["name"], nl_date(result["ref_date"])), ""]
    if todo:
        lines.append("Aan te melden: %d artikelen, %s stuks (%d kritiek)." % (len(todo), nl(sum(r["deliver"] for r in todo)), len(crit)))
        for r in todo:
            amount = "%s x %s = %s st" % (r["units"], r["unit"], r["deliver"]) if r["units"] else "%s st (besteleenheid ontbreekt)" % r["need"]
            lines.append("- [%s] %s (%s): %s, dekking %s dgn" % (r["status"], r["name"], r["ean"], amount, nl(r["cover"], 0)))
    else:
        lines.append("Er hoeft deze week niets aangemeld te worden.")
    if signals:
        lines += ["", "Signalen:"] + ["- %s: %s" % (r["name"], s[1]) for r, s in signals[:25]]
    if base:
        lines += ["", "Dashboard: " + base]

    trs = "".join("<tr><td>%s</td><td>%s<br><small>%s %s</small></td><td align='right'>%s</td><td align='right'>%s</td></tr>" % (
        esc(r["status"]), esc(r["name"]), esc(r["ean"]), esc(r["article_code"]),
        ("%s &times; %s = <b>%s</b>" % (r["units"], r["unit"], r["deliver"])) if r["units"] else "<b>%s</b> (eenheid ontbreekt)" % r["need"],
        nl(r["cover"], 0)) for r in todo)
    html = "<h2>Weekadvies %s</h2><p>Voorraadstand van %s.</p>" % (esc(ch["name"]), nl_date(result["ref_date"]))
    html += ("<table cellpadding='6' border='1' style='border-collapse:collapse'><tr><th>Prioriteit</th><th>Artikel</th><th>Aanleveren (st)</th><th>Dekking (dgn)</th></tr>%s</table>" % trs
             ) if todo else "<p>Er hoeft deze week niets aangemeld te worden.</p>"
    if signals:
        html += "<h3>Signalen</h3><ul>%s</ul>" % "".join("<li>%s: %s</li>" % (esc(r["name"]), esc(s[1])) for r, s in signals[:25])
    if base:
        html += "<p><a href='%s'>Open het dashboard</a></p>" % esc(base)

    msg = EmailMessage()
    msg["Subject"] = "Weekadvies %s: %d aan te melden%s" % (ch["name"], len(todo), ", %d kritiek" % len(crit) if crit else "")
    msg["From"] = config.get("MAIL_FROM") or config.get("SMTP_USER")
    msg["To"] = to
    msg.set_content("\n".join(lines))
    msg.add_alternative(html, subtype="html")
    msg.add_attachment(excel.build(result, ch["name"]), maintype="application",
                       subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       filename="LvB_aanvuladvies_%s.xlsx" % result["ref_date"])
    try:
        port = int(config.get("SMTP_PORT", "587"))
        ctx = ssl.create_default_context()
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=30, context=ctx)
        else:
            server = smtplib.SMTP(host, port, timeout=30)
            server.starttls(context=ctx)
        with server:
            if config.get("SMTP_USER"):
                server.login(config.get("SMTP_USER"), config.get("SMTP_PASSWORD"))
            server.send_message(msg)
    except Exception as e:
        print("Weekmail versturen mislukt: %s" % e)
        return False
    print("Weekmail verstuurd naar %s" % to)
    return True
