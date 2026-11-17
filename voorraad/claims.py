"""Bezwaar bij bol over een manco in een afgeronde LvB-zending.

De tool verstuurt zelf geen mail: zij stelt de tekst op, de gebruiker verstuurt hem vanuit het eigen
mailprogramma (of Outlook op het web) en bevestigt daarna in de tool. Per zending kan dat één keer.
"""
from __future__ import annotations

import sqlite3
from urllib.parse import quote

TO = "zakelijkverkopen@bol.com"


def _nl(n):
    return "{:,}".format(n).replace(",", ".")


def _date(iso):
    if not iso:
        return "onbekend"
    months = ["januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus",
              "september", "oktober", "november", "december"]
    y, m, d = iso[:10].split("-")
    return "%d %s %s" % (int(d), months[int(m) - 1], y)


def booked(line) -> int:
    return (line["regular"] or 0) + (line["graded"] or 0)


def shortfall(lines) -> int:
    """Totaal aantal stuks dat minder is opgeboekt dan aangemeld (overschotten tellen niet mee)."""
    return sum(max(0, (l["announced"] or 0) - booked(l)) for l in lines)


def state(ch, ship, lines, claim):
    """'gemaakt', 'kan', 'wachten' of None (geen bezwaar mogelijk of nodig)."""
    if ch["adapter"] != "bol" or not lines:
        return None
    if claim:
        return "gemaakt"
    if ship["state"] == "DONE":
        return "kan" if shortfall(lines) else None
    # Nog niet afgerond: alleen melden als er nu al minder binnen of opgeboekt lijkt dan aangemeld.
    if ship["arrived"] and any(booked(l) < (l["announced"] or 0) for l in lines):
        return "wachten"
    return None


def compose(ship, lines):
    """(onderwerp, tekst) van de bezwaarmail."""
    ref = ship["reference"] or ""
    subject = "Bezwaar manco LvB-zending %s%s" % (ship["ship_id"], " (%s)" % ref if ref else "")
    short = [l for l in lines if booked(l) < (l["announced"] or 0)]
    extra = [l for l in lines if booked(l) > (l["announced"] or 0)]
    total = shortfall(lines)

    def row(l):
        name = (l["title"] or "").strip()
        return ("- %s\n  EAN %s: aangemeld %s, ontvangen %s, opgeboekt %s" % (
            name or "Artikel", l["ean"], _nl(l["announced"] or 0), _nl(l["received"] or 0), _nl(booked(l))))

    parts = [
        "Beste partnerservice,",
        "",
        "Graag maken wij bezwaar tegen het verschil bij onderstaande LvB-zending. "
        "Er is minder op voorraad gelegd dan wij hebben aangemeld en aangeleverd.",
        "",
        "Zendingnummer bol: %s" % ship["ship_id"],
    ]
    if ref:
        parts.append("Ons kenmerk: %s" % ref)
    parts += [
        "Aangekomen: %s" % _date(ship["arrived"]),
        "Afgerond: %s" % _date(ship["done_at"]),
    ]
    if ship["carrier"] or ship["boxes"]:
        parts.append("Vervoer: %s" % ", ".join(x for x in (ship["carrier"] or "", "%d dozen" % ship["boxes"] if ship["boxes"] else "") if x))
    parts += ["", "Manco per artikel:"]
    for l in short:
        parts.append(row(l) + " -> manco %s" % _nl((l["announced"] or 0) - booked(l)))
    parts += ["", "Totaal manco: %s stuks (aangemeld %s, opgeboekt %s)." % (
        _nl(total), _nl(sum(l["announced"] or 0 for l in lines)), _nl(sum(booked(l) for l in lines)))]
    if extra:
        parts += ["", "Ter volledigheid: van deze artikelen is meer opgeboekt dan aangemeld:"]
        for l in extra:
            parts.append(row(l) + " -> %s meer" % _nl(booked(l) - (l["announced"] or 0)))
    parts += ["", "Willen jullie dit onderzoeken en de ontbrekende stuks alsnog op voorraad leggen of vergoeden?",
              "", "Met vriendelijke groet,", "", "Dexxon"]
    return subject, "\n".join(parts)


def mailto(subject, body) -> str:
    return "mailto:%s?subject=%s&body=%s" % (TO, quote(subject, safe=""), quote(body.replace("\n", "\r\n"), safe=""))


def outlook_web(subject, body) -> str:
    return "https://outlook.office.com/mail/deeplink/compose?to=%s&subject=%s&body=%s" % (
        quote(TO, safe=""), quote(subject, safe=""), quote(body, safe=""))


def get(conn, code, ship_id):
    return conn.execute("SELECT * FROM claims WHERE channel=? AND ship_id=?", (code, ship_id)).fetchone()


def for_channel(conn, code) -> dict:
    return {r["ship_id"]: r for r in conn.execute("SELECT * FROM claims WHERE channel=?", (code,))}


def record(conn, code, ship_id, username, units) -> bool:
    """Legt vast dat het bezwaar is verstuurd. False als dat voor deze zending al eerder is gedaan."""
    try:
        conn.execute("INSERT INTO claims(channel, ship_id, created_at, username, units) VALUES(?,?,datetime('now','localtime'),?,?)",
                     (code, ship_id, username, units))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def undo(conn, code, ship_id) -> None:
    conn.execute("DELETE FROM claims WHERE channel=? AND ship_id=?", (code, ship_id))
    conn.commit()
