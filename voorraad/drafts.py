"""Zendingen voorbereiden en aanmaken bij de marketplace.

Stappen:
  1. Iemand keurt regels uit het aanvuladvies goed (eventueel met aangepaste aantallen).
  2. De tool vraagt bij de marketplace op naar welk magazijn elk artikel moet.
  3. Per magazijn ontstaat een deelzending; daar kiest de gebruiker vervoerder, labelservice,
     leverdatum en aantal laadeenheden, en bevestigt.
  4. Pas dan wordt de zending echt aangemaakt. Er gebeurt nooit iets zonder klik van een persoon.
"""
from __future__ import annotations

import json
import re
import time
from datetime import date

from .channels.base import ChannelError

TRANSPORTERS = ("DHL", "POSTNL", "DPD", "GLS", "UPS", "OTHER")
_dates_cache = {}


def can_create(adapter) -> bool:
    return bool(getattr(adapter, "supports_create", False)) and adapter.configured()


def create(conn, ch, adapter, username, lines) -> int:
    """lines: lijst (ean, stuks). Vraagt meteen de magazijnadressen op."""
    lines = [(ean, int(pieces)) for ean, pieces in lines if int(pieces) > 0]
    if not lines:
        raise ValueError("Kies minstens een artikel met een aantal groter dan nul")
    if len(lines) > 50:
        raise ValueError("Een zending kan maximaal 50 verschillende artikelen bevatten")
    process = adapter.request_destinations([ean for ean, _ in lines])
    cur = conn.execute(
        "INSERT INTO drafts(channel, username, created_at, status, dest_process) VALUES(?,?,datetime('now','localtime'),'adressen',?)",
        (ch["code"], username, process))
    for ean, pieces in lines:
        conn.execute("INSERT INTO draft_lines(draft_id, ean, pieces, group_no) VALUES(?,?,?,NULL)", (cur.lastrowid, ean, pieces))
    conn.commit()
    return cur.lastrowid


def next_reference(conn, code, taken=()) -> str:
    """Zelfde opmaak als logistiek gebruikt: DDMMJJJJ + NR + volgnummer van die dag."""
    prefix = date.today().strftime("%d%m%Y") + "NR"
    used = set(taken)
    used.update(r[0] for r in conn.execute("SELECT reference FROM shipments WHERE channel=? AND reference LIKE ?", (code, prefix + "%")))
    used.update(r[0] for r in conn.execute(
        """SELECT g.reference FROM draft_groups g JOIN drafts d ON d.id=g.draft_id
           WHERE d.channel=? AND g.reference LIKE ? AND g.state IN ('verstuurd','aangemaakt','annuleren')""", (code, prefix + "%")))
    n = 1
    while "%s%d" % (prefix, n) in used:
        n += 1
    return "%s%d" % (prefix, n)


def refresh(conn, ch, adapter, draft) -> None:
    """Werkt een voorbereide zending bij met wat de marketplace intussen heeft teruggemeld."""
    did = draft["id"]
    if draft["status"] == "adressen":
        try:
            st = adapter.process_status(draft["dest_process"])
        except ChannelError as e:
            if "(404)" not in str(e):
                raise
            # Bol bewaart een verzoek maximaal een dag: daarna is het antwoord niet meer op te halen.
            st = {"status": "FAILURE", "entity_id": None, "error": "Het adresverzoek is verlopen. Start een nieuwe voorbereiding."}
        if st["status"] == "SUCCESS":
            dests = adapter.get_destinations(st["entity_id"])
            for n, d in enumerate(dests, 1):
                conn.execute("INSERT OR REPLACE INTO draft_groups(draft_id, group_no, address, state) VALUES(?,?,?,'open')",
                             (did, n, json.dumps(d["address"])))
                for ean in d["eans"]:
                    conn.execute("UPDATE draft_lines SET group_no=? WHERE draft_id=? AND ean=?", (n, did, ean))
            conn.execute("UPDATE drafts SET status='klaar' WHERE id=?", (did,))
        elif st["status"] in ("FAILURE", "TIMEOUT"):
            conn.execute("UPDATE drafts SET status='mislukt', error=? WHERE id=?",
                         (st["error"] or "Bol kon de adressen niet bepalen (%s)" % st["status"], did))
        conn.commit()
    for g in conn.execute("SELECT * FROM draft_groups WHERE draft_id=? AND state IN ('verstuurd','annuleren')", (did,)).fetchall():
        st = adapter.process_status(g["process"])
        if st["status"] == "PENDING":
            continue
        if g["state"] == "verstuurd":
            if st["status"] == "SUCCESS":
                conn.execute("UPDATE draft_groups SET state='aangemaakt', ship_id=?, error=NULL WHERE draft_id=? AND group_no=?",
                             (st["entity_id"], did, g["group_no"]))
            else:
                conn.execute("UPDATE draft_groups SET state='mislukt', error=? WHERE draft_id=? AND group_no=?",
                             (st["error"] or "Bol heeft de zending afgewezen (%s)" % st["status"], did, g["group_no"]))
        else:
            if st["status"] == "SUCCESS":
                conn.execute("UPDATE draft_groups SET state='geannuleerd', error=NULL WHERE draft_id=? AND group_no=?", (did, g["group_no"]))
            else:
                conn.execute("UPDATE draft_groups SET state='aangemaakt', error=? WHERE draft_id=? AND group_no=?",
                             ("Annuleren is niet gelukt: %s" % (st["error"] or st["status"]), did, g["group_no"]))
        conn.commit()


def submit_group(conn, ch, adapter, draft, group_no, form, username) -> None:
    g = conn.execute("SELECT * FROM draft_groups WHERE draft_id=? AND group_no=?", (draft["id"], group_no)).fetchone()
    if not g or g["state"] not in ("open", "mislukt"):
        raise ValueError("Deze deelzending is al verstuurd of bestaat niet")
    reference = (form.get("reference") or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{1,30}", reference) or not re.search(r"\d", reference):
        raise ValueError("Het kenmerk mag alleen hoofdletters en cijfers bevatten, met minstens een cijfer")
    transporter = form.get("transporter")
    if transporter not in TRANSPORTERS:
        raise ValueError("Kies een vervoerder")
    expected = form.get("expected") or ""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", expected):
        raise ValueError("Kies een leverdatum")
    try:
        carriers = int(form.get("carriers") or 0)
    except ValueError:
        carriers = 0
    if not 1 <= carriers <= 66:
        raise ValueError("Het aantal laadeenheden moet tussen 1 en 66 liggen")
    if form.get("gecontroleerd") != "ja":
        raise ValueError("Vink aan dat je de aantallen en het adres hebt gecontroleerd")
    labeling = form.get("labeling") == "ja"
    lines = [(r["ean"], r["pieces"]) for r in conn.execute(
        "SELECT ean, pieces FROM draft_lines WHERE draft_id=? AND group_no=?", (draft["id"], group_no))]
    if not lines:
        raise ValueError("Deze deelzending bevat geen artikelen")
    process = adapter.create_replenishment(reference, lines, transporter, expected, labeling, carriers)
    conn.execute(
        """UPDATE draft_groups SET reference=?, transporter=?, labeling=?, expected=?, carriers=?, process=?,
             state='verstuurd', error=NULL, created_by=?, created_at=datetime('now','localtime')
           WHERE draft_id=? AND group_no=?""",
        (reference, transporter, 1 if labeling else 0, expected, carriers, process, username, draft["id"], group_no))
    conn.commit()


def cancel_remote(conn, ch, adapter, draft, group_no) -> None:
    g = conn.execute("SELECT * FROM draft_groups WHERE draft_id=? AND group_no=?", (draft["id"], group_no)).fetchone()
    if not g or g["state"] != "aangemaakt" or not g["ship_id"]:
        raise ValueError("Deze zending kan hier niet geannuleerd worden")
    process = adapter.cancel_replenishment(g["ship_id"])
    conn.execute("UPDATE draft_groups SET state='annuleren', process=? WHERE draft_id=? AND group_no=?",
                 (process, draft["id"], group_no))
    conn.commit()


def close(conn, draft_id) -> None:
    """Sluit een voorbereiding. Deelzendingen die nog niet verstuurd zijn, vervallen."""
    conn.execute("UPDATE draft_groups SET state='vervallen' WHERE draft_id=? AND state IN ('open','mislukt')", (draft_id,))
    conn.execute("UPDATE drafts SET status='gesloten' WHERE id=?", (draft_id,))
    conn.commit()


def delivery_dates(adapter) -> list:
    hit = _dates_cache.get("dates")
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    try:
        dates = adapter.delivery_dates()
    except ChannelError:
        return hit[1] if hit else []
    _dates_cache["dates"] = (time.time(), dates)
    return dates


def get(conn, code, draft_id):
    return conn.execute("SELECT * FROM drafts WHERE id=? AND channel=?", (draft_id, code)).fetchone()


def detail(conn, draft):
    """Groepen met hun regels, plus regels waarvoor geen magazijn is teruggekomen."""
    lines = conn.execute(
        """SELECT dl.*, COALESCE(l.title, p.name, '') AS title, p.order_unit, p.article_code, COALESCE(f.ok, 0) AS photo
           FROM draft_lines dl LEFT JOIN listings l ON l.channel=? AND l.ean=dl.ean
           LEFT JOIN products p ON p.ean=dl.ean LEFT JOIN photos f ON f.ean=dl.ean
           WHERE dl.draft_id=? ORDER BY title""", (draft["channel"], draft["id"])).fetchall()
    groups = []
    for g in conn.execute("SELECT * FROM draft_groups WHERE draft_id=? ORDER BY group_no", (draft["id"],)).fetchall():
        groups.append({"g": g, "address": json.loads(g["address"] or "{}"),
                       "lines": [l for l in lines if l["group_no"] == g["group_no"]]})
    return groups, [l for l in lines if l["group_no"] is None], lines


def open_drafts(conn, code):
    return conn.execute(
        """SELECT d.*, (SELECT COUNT(*) FROM draft_lines WHERE draft_id=d.id) AS n_lines,
                  (SELECT COALESCE(SUM(pieces),0) FROM draft_lines WHERE draft_id=d.id) AS pieces,
                  (SELECT COUNT(*) FROM draft_groups WHERE draft_id=d.id AND state IN ('aangemaakt')) AS n_done,
                  (SELECT COUNT(*) FROM draft_groups WHERE draft_id=d.id) AS n_groups
           FROM drafts d WHERE d.channel=? AND d.status IN ('adressen','klaar','mislukt')
           ORDER BY d.id DESC LIMIT 10""", (code,)).fetchall()


def pending_inbound(conn, code) -> dict:
    """Stuks uit zojuist aangemaakte zendingen die de ophaalronde nog niet als zending kent."""
    out = {}
    for r in conn.execute(
            """SELECT dl.ean, SUM(dl.pieces) n FROM draft_groups g JOIN drafts d ON d.id=g.draft_id
               JOIN draft_lines dl ON dl.draft_id=g.draft_id AND dl.group_no=g.group_no
               WHERE d.channel=? AND g.state='aangemaakt' AND g.created_at >= date('now','-21 days')
                 AND NOT EXISTS (SELECT 1 FROM shipments s WHERE s.channel=d.channel AND s.reference=g.reference)
               GROUP BY dl.ean""", (code,)):
        out[r["ean"]] = r["n"] or 0
    return out
