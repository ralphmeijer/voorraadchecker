"""Rekenmodel voor het aanvuladvies (volgens de projectinstructie van Ralph).

Dagafzet        = besteld in de velocity-periode / aantal dagen
Dagen dekking   = voorraad / dagafzet
Advies (stuks)  = als dekking <= besteltrigger:
                    max(0, naar boven afronden((doel + lead time) x dagafzet - voorraad - onderweg))
Aanleveren      = naar boven afronden op hele besteleenheden
"""
from __future__ import annotations

import math
from datetime import date, timedelta

STATUS_ORDER = ["Kritiek", "Aanvullen", "OK", "Overstock", "Dood", "Niet aanvullen"]


def _params(ch):
    return {
        "target": ch["target_days"], "lead": ch["lead_days"], "buffer": ch["buffer_days"],
        "trigger": ch["trigger_days"], "velocity": ch["velocity_days"],
        "reorder_point": ch["lead_days"] + ch["buffer_days"],
    }


def compute(conn, ch):
    """Berekent alle artikelen van een kanaal. Geeft dict met ref_date, params en rows."""
    code = ch["code"]
    p = _params(ch)
    V = max(2, p["velocity"])
    ref = conn.execute("SELECT MAX(date) FROM stock WHERE channel=?", (code,)).fetchone()[0]
    if not ref:
        return {"ref_date": None, "params": p, "rows": [], "has28": False}
    refd = date.fromisoformat(ref)
    d28 = (refd - timedelta(days=28)).isoformat()
    first = conn.execute("SELECT MIN(date) FROM daily_sales WHERE channel=?", (code,)).fetchone()[0]
    has28 = bool(first and first <= d28)

    sales, returns = {}, {}
    for r in conn.execute("SELECT ean, date, ordered FROM daily_sales WHERE channel=? AND date>=? AND date<?",
                          (code, d28, ref)):
        sales.setdefault(r["ean"], {})[r["date"]] = r["ordered"] or 0
    since_v = (refd - timedelta(days=V)).isoformat()
    for r in conn.execute("SELECT ean, SUM(received) n FROM daily_returns WHERE channel=? AND date>=? AND date<? GROUP BY ean",
                          (code, since_v, ref)):
        returns[r["ean"]] = r["n"] or 0

    inbound = {}
    # Welke zendingen nog als onderweg tellen bepaalt shipments.rebuild_inbound (op aankomstdatum).
    for r in conn.execute("SELECT ean, SUM(quantity) n, MAX(created) c FROM inbound WHERE channel=? GROUP BY ean", (code,)):
        inbound[r["ean"]] = [r["n"] or 0, r["c"] or ""]
    # Door logistiek afgevinkte regels tellen als onderweg tot de API de zending zelf laat zien.
    horizon = (date.today() - timedelta(days=p["lead"] + p["buffer"])).isoformat()
    marked = {}
    for r in conn.execute("SELECT ean, pieces, created_at FROM handoffs WHERE channel=? AND undone=0 AND created_at>=?",
                          (code, horizon)):
        api = inbound.get(r["ean"])
        if api and api[1] >= r["created_at"][:10]:
            continue
        marked[r["ean"]] = marked.get(r["ean"], 0) + (r["pieces"] or 0)

    from .drafts import pending_inbound
    for ean, n in pending_inbound(conn, code).items():
        marked[ean] = marked.get(ean, 0) + n

    days_v = [(refd - timedelta(days=i)).isoformat() for i in range(V, 0, -1)]  # oud -> nieuw
    half = V // 2
    from .photos import available
    with_photo = available(conn)
    rows = []
    q = """SELECT s.ean, s.stock, s.graded, s.unsellable_14d, l.title, p.article_code, p.name, p.brand,
                  p.order_unit, p.mode, p.note
           FROM stock s LEFT JOIN listings l ON l.channel=s.channel AND l.ean=s.ean
           LEFT JOIN products p ON p.ean=s.ean WHERE s.channel=? AND s.date=?"""
    for s in conn.execute(q, (code, ref)):
        ean = s["ean"]
        per_day = sales.get(ean, {})
        series = [per_day.get(d, 0) for d in days_v]
        ordered = sum(series)
        ordered28 = sum(per_day.values()) if has28 else None
        stock = s["stock"] or 0
        if stock == 0 and not per_day and not inbound.get(ean) and not marked.get(ean):
            continue  # staat wel in het assortiment, maar ligt niet bij de marketplace en verkoopt niet
        v = ordered / V
        v28 = ordered28 / 28 if ordered28 is not None else None
        cover = stock / v if v > 0 else None
        onderweg = inbound.get(ean, [0])[0] + marked.get(ean, 0)
        mode = s["mode"] or "normaal"
        unit = s["order_unit"]
        need = 0
        if v > 0 and cover <= p["trigger"] and mode == "normaal":
            need = max(0, math.ceil((p["target"] + p["lead"]) * v - stock - onderweg - 1e-9))
        units = math.ceil(need / unit) if need and unit else None
        deliver = units * unit if units else (need if need and not unit else 0)

        if mode != "normaal":
            status = "Niet aanvullen"
        elif ordered == 0:
            status = "Dood"
        elif cover < p["reorder_point"]:
            status = "Kritiek"
        elif cover <= p["trigger"] and need > 0:
            status = "Aanvullen"
        elif cover > 1.5 * p["target"]:
            status = "Overstock"
        else:
            status = "OK"

        signals = []
        if need and not unit:
            signals.append(("warn", "Besteleenheid ontbreekt"))
        if status in ("Kritiek", "Aanvullen") and need == 0 and onderweg:
            signals.append(("info", "Onderweg dekt de behoefte"))
        if status == "Dood" and stock == 0:
            signals.append(("warn", "Geen voorraad: mogelijk uitverkocht in plaats van dood"))
        first_half, last_half = sum(series[:half]), sum(series[-half:])
        trend = None
        if first_half > 0 and ordered >= 10:
            trend = (last_half - first_half) / first_half
            if trend > 0.30:
                signals.append(("up", "Versnelt %+.0f%%: overweeg eerder aanvullen" % (trend * 100)))
            elif trend < -0.30:
                signals.append(("down", "Vertraagt %+.0f%%: overweeg temperen of uitstellen" % (trend * 100)))
        ret = returns.get(ean, 0)
        if ordered >= 5 and ret / ordered > 0.10:
            signals.append(("warn", "Retouren %.0f%% van besteld" % (100.0 * ret / ordered)))
        elif ret and ordered < 5:
            signals.append(("warn", "%d retour op %d besteld" % (ret, ordered)))
        unsellable = s["unsellable_14d"] if s["unsellable_14d"] is not None else (s["graded"] or 0)
        if unsellable:
            signals.append(("warn", "%d onverkoopbaar" % unsellable))
        if 0 < ordered < 5 and mode == "normaal":
            signals.append(("info", "Weinig verkopen: meting is ruisig"))
        if v28 is not None and v > 0 and v28 > 0 and abs(v - v28) / v28 > 0.5 and ordered28 >= 8:
            signals.append(("info", "Wijkt sterk af van 28-daagse afzet (%.2f/dag)" % v28))
        if s["note"]:
            signals.append(("note", s["note"]))

        rows.append({
            "ean": ean, "name": s["title"] or s["name"] or "", "article_code": s["article_code"] or "",
            "brand": s["brand"] or "", "unit": unit, "mode": mode, "stock": stock,
            "ordered": ordered, "ordered28": ordered28, "v": v, "v28": v28, "cover": cover,
            "arrival_stock": stock - p["lead"] * v, "inbound": onderweg, "need": need,
            "units": units, "deliver": deliver, "status": status, "signals": signals,
            "photo": ean in with_photo,
            "series": series, "returns": ret, "unsellable": unsellable, "trend": trend,
        })
    rows.sort(key=lambda r: (STATUS_ORDER.index(r["status"]),
                             r["cover"] if r["cover"] is not None else 1e9, r["name"]))
    return {"ref_date": ref, "params": p, "rows": rows, "has28": has28, "days": days_v}


def logistics_rows(result):
    """De hand-off: alleen artikelen die nu echt aangevuld moeten worden, kritiek eerst."""
    return [r for r in result["rows"] if r["need"] > 0 and r["status"] in ("Kritiek", "Aanvullen")]
