"""Zendingen naar de marketplace: opslaan, afwijkingen beoordelen en erover mailen.

Afwijkingen:
  aantal  - de zending is afgerond, maar er is een ander aantal opgeboekt dan aangemeld;
            of er is nu al meer ontvangen dan aangemeld.
  hangt   - de zending is aangekomen, maar na de lead time (in dagen) nog niet volledig opgeboekt.

Een afwijking verdwijnt vanzelf als de oorzaak weg is, of als iemand haar afhandelt in het dashboard.
Staat ze er een dag na de eerste melding nog, dan gaat er een mail uit (een keer per afwijking).
"""
from __future__ import annotations

import json
from datetime import date, timedelta

OPEN_STATES = ("ANNOUNCED", "IN_TRANSIT", "ARRIVED_AT_WH", "IN_PROGRESS_AT_WH")
ARRIVED_STATES = ("ARRIVED_AT_WH", "IN_PROGRESS_AT_WH")
STATE_LABEL = {"ANNOUNCED": "Aangemeld", "IN_TRANSIT": "Onderweg", "ARRIVED_AT_WH": "Aangekomen",
               "IN_PROGRESS_AT_WH": "Wordt opgeboekt", "DONE": "Opgeboekt", "CANCELLED": "Geannuleerd"}
HISTORY_DAYS = 60


def store(conn, code, shipments) -> None:
    for s in shipments:
        conn.execute(
            """INSERT INTO shipments(channel, ship_id, reference, state, created, expected, arrived, done_at,
                                     carrier, tracking, boxes, window_start)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(channel, ship_id) DO UPDATE SET reference=excluded.reference, state=excluded.state,
                 expected=excluded.expected, arrived=COALESCE(shipments.arrived, excluded.arrived),
                 done_at=COALESCE(shipments.done_at, excluded.done_at),
                 carrier=COALESCE(excluded.carrier, shipments.carrier), tracking=COALESCE(excluded.tracking, shipments.tracking),
                 boxes=COALESCE(excluded.boxes, shipments.boxes), window_start=COALESCE(excluded.window_start, shipments.window_start)""",
            (code, s.ship_id, s.reference, s.state, s.created, s.expected, s.arrived, s.done_at,
             s.carrier, json.dumps(s.tracking) if s.tracking else None, s.boxes, s.window_start))
        conn.execute("DELETE FROM shipment_lines WHERE channel=? AND ship_id=?", (code, s.ship_id))
        for l in s.lines:
            conn.execute(
                """INSERT INTO shipment_lines(channel, ship_id, ean, announced, received, in_progress, regular, graded)
                   VALUES(?,?,?,?,?,?,?,?)
                   ON CONFLICT(channel, ship_id, ean) DO UPDATE SET announced=announced+excluded.announced,
                     received=received+excluded.received, in_progress=in_progress+excluded.in_progress,
                     regular=regular+excluded.regular, graded=graded+excluded.graded""",
                (code, s.ship_id, l.ean, l.announced, l.received, l.in_progress, l.regular, l.graded))


def rebuild_inbound(conn, ch, today: date) -> int:
    """Wat telt als onderweg: aangemeld en nog niet opgeboekt, zolang de zending redelijkerwijs nog loopt."""
    code = ch["code"]
    grace = (today - timedelta(days=ch["lead_days"] + ch["buffer_days"])).isoformat()
    lost = (today - timedelta(days=30)).isoformat()
    conn.execute("DELETE FROM inbound WHERE channel=?", (code,))
    n = 0
    q = """SELECT s.ship_id, s.reference, s.state, s.created, s.expected, s.arrived, l.ean,
                  l.announced - l.regular - l.graded AS open_qty
           FROM shipments s JOIN shipment_lines l ON l.channel=s.channel AND l.ship_id=s.ship_id
           WHERE s.channel=? AND s.state IN (%s)""" % ",".join("?" * len(OPEN_STATES))
    for r in conn.execute(q, (code,) + OPEN_STATES).fetchall():
        if r["open_qty"] <= 0:
            continue
        if r["arrived"]:
            if r["arrived"] < grace:
                continue  # al lang binnen: wat nog openstaat is een telverschil, geen voorraad die nog komt
        elif (r["expected"] or r["created"] or "") < lost:
            continue      # ruim over de verwachte datum en nooit aangekomen
        conn.execute(
            """INSERT INTO inbound(channel, ref, ean, quantity, state, created) VALUES(?,?,?,?,?,?)
               ON CONFLICT(channel, ref, ean) DO UPDATE SET quantity=quantity+excluded.quantity""",
            (code, r["reference"] or r["ship_id"], r["ean"], r["open_qty"], r["state"], r["created"]))
        n += 1
    return n


def evaluate(conn, ch, today: date) -> int:
    """Werkt de tabel met afwijkingen bij. Geeft het aantal openstaande afwijkingen."""
    code = ch["code"]
    since = (today - timedelta(days=HISTORY_DAYS)).isoformat()
    stuck_before = (today - timedelta(days=ch["lead_days"])).isoformat()
    found = {}
    for s in conn.execute("SELECT * FROM shipments WHERE channel=? AND created>=? AND state<>'CANCELLED'",
                          (code, since)).fetchall():
        lines = conn.execute("SELECT * FROM shipment_lines WHERE channel=? AND ship_id=?",
                             (code, s["ship_id"])).fetchall()
        for l in lines:
            booked = l["regular"] + l["graded"]
            if s["state"] == "DONE" and booked != l["announced"]:
                diff = booked - l["announced"]
                found[(s["ship_id"], l["ean"], "aantal")] = "Aangemeld %d, opgeboekt %d (%+d)" % (l["announced"], booked, diff)
            elif s["state"] != "DONE" and l["received"] > l["announced"]:
                found[(s["ship_id"], l["ean"], "aantal")] = "Aangemeld %d, al %d ontvangen (%+d)" % (
                    l["announced"], l["received"], l["received"] - l["announced"])
        if s["state"] in ARRIVED_STATES and s["arrived"] and s["arrived"] <= stuck_before:
            announced = sum(l["announced"] for l in lines)
            booked = sum(l["regular"] + l["graded"] for l in lines)
            days = (today - date.fromisoformat(s["arrived"])).days
            found[(s["ship_id"], "", "hangt")] = "Aangekomen op %s, na %d dagen nog niet afgerond: %d van %d stuks opgeboekt" % (
                s["arrived"], days, booked, announced)

    iso = today.isoformat()
    for (ship_id, ean, kind), detail in found.items():
        conn.execute(
            """INSERT INTO deviations(channel, ship_id, ean, kind, detail, first_seen, last_seen) VALUES(?,?,?,?,?,?,?)
               ON CONFLICT(channel, ship_id, ean, kind) DO UPDATE SET detail=excluded.detail,
                 last_seen=excluded.last_seen, resolved_at=NULL""",
            (code, ship_id, ean, kind, detail, iso, iso))
    for d in conn.execute("SELECT id, ship_id, ean, kind FROM deviations WHERE channel=? AND resolved_at IS NULL", (code,)).fetchall():
        if (d["ship_id"], d["ean"], d["kind"]) not in found:
            conn.execute("UPDATE deviations SET resolved_at=? WHERE id=?", (iso, d["id"]))
    return len(open_deviations(conn, code))


def open_deviations(conn, code):
    return conn.execute(
        """SELECT d.*, s.reference, s.state, s.created, COALESCE(l.title, p.name, '') AS title,
                  COALESCE(f.ok, 0) AS photo
           FROM deviations d JOIN shipments s ON s.channel=d.channel AND s.ship_id=d.ship_id
           LEFT JOIN photos f ON f.ean=d.ean
           LEFT JOIN listings l ON l.channel=d.channel AND l.ean=d.ean
           LEFT JOIN products p ON p.ean=d.ean
           WHERE d.channel=? AND d.resolved_at IS NULL AND d.handled_at IS NULL
           ORDER BY d.first_seen, s.reference, d.ean""", (code,)).fetchall()


def running(conn, code):
    """Lopende zendingen met totalen, nieuwste eerst."""
    q = """SELECT s.*, COUNT(l.ean) AS n_lines, COALESCE(SUM(l.announced),0) AS announced,
                  COALESCE(SUM(l.received),0) AS received, COALESCE(SUM(l.regular + l.graded),0) AS booked
           FROM shipments s LEFT JOIN shipment_lines l ON l.channel=s.channel AND l.ship_id=s.ship_id
           WHERE s.channel=? AND s.state IN (%s) GROUP BY s.ship_id ORDER BY s.created DESC""" % ",".join("?" * len(OPEN_STATES))
    return conn.execute(q, (code,) + OPEN_STATES).fetchall()


def all_shipments(conn, code, limit=60):
    """Alle zendingen met totalen, nieuwste eerst (ook afgeronde en geannuleerde)."""
    return conn.execute(
        """SELECT s.*, COUNT(l.ean) AS n_lines, COALESCE(SUM(l.announced),0) AS announced,
                  COALESCE(SUM(l.received),0) AS received, COALESCE(SUM(l.regular + l.graded),0) AS booked
           FROM shipments s LEFT JOIN shipment_lines l ON l.channel=s.channel AND l.ship_id=s.ship_id
           WHERE s.channel=? GROUP BY s.ship_id ORDER BY s.created DESC, s.reference DESC LIMIT ?""", (code, limit)).fetchall()


def one(conn, code, ship_id):
    """Een zending met haar regels en alle afwijkingen (ook afgehandelde)."""
    ship = conn.execute("SELECT * FROM shipments WHERE channel=? AND ship_id=?", (code, ship_id)).fetchone()
    if not ship:
        return None, [], []
    lines = conn.execute(
        """SELECT sl.*, COALESCE(l.title, p.name, '') AS title, p.article_code, p.order_unit, COALESCE(f.ok, 0) AS photo
           FROM shipment_lines sl LEFT JOIN listings l ON l.channel=sl.channel AND l.ean=sl.ean
           LEFT JOIN products p ON p.ean=sl.ean LEFT JOIN photos f ON f.ean=sl.ean
           WHERE sl.channel=? AND sl.ship_id=? ORDER BY title""", (code, ship_id)).fetchall()
    devs = conn.execute("SELECT * FROM deviations WHERE channel=? AND ship_id=? ORDER BY first_seen", (code, ship_id)).fetchall()
    return ship, lines, devs


def handle(conn, code, dev_id, username) -> None:
    conn.execute("UPDATE deviations SET handled_at=datetime('now','localtime'), handled_by=? WHERE id=? AND channel=?",
                 (username, dev_id, code))
    conn.commit()


def notify(conn, ch, today: date) -> str:
    """Mailt afwijkingen die er een dag na de eerste melding nog staan. Een keer per afwijking."""
    from . import mailer
    due = [d for d in open_deviations(conn, ch["code"]) if d["mailed_at"] is None and d["first_seen"] < today.isoformat()]
    if not due:
        return ""
    if not mailer.send_deviations(ch, due):
        return "%d afwijkingen wachten op een mail (mail niet ingesteld of mislukt)" % len(due)
    conn.executemany("UPDATE deviations SET mailed_at=datetime('now','localtime') WHERE id=?", [(d["id"],) for d in due])
    conn.commit()
    return "mail verstuurd over %d afwijkingen" % len(due)
