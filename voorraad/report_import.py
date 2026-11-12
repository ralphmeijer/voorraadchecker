"""Import van het LvB-dagrapport van bol (bolcom_<id>_<start>_<eind>.xlsx).

Dient als startvulling van de historie en als terugvaloptie wanneer de API niet beschikbaar is.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

import openpyxl

from . import db
from .masterdata import norm_ean


def _int(value):
    return int(round(value)) if isinstance(value, (int, float)) else 0


def import_report(conn, path, channel: str = "bol", filename: str = None):
    name = filename or str(path)
    m = re.search(r"(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})", name)
    if not m:
        raise ValueError("De bestandsnaam moet de periode bevatten, zoals bolcom_123_2026-10-29_2026-11-12.xlsx")
    end = date.fromisoformat(m.group(2))  # datum van de voorraadstand
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    if "Gisteren & 14 dagen" not in wb.sheetnames or "Details per dag" not in wb.sheetnames:
        raise ValueError("Dit lijkt geen LvB-dagrapport: de verwachte tabbladen ontbreken")

    n = stock_total = ordered_total = 0
    for r in wb["Gisteren & 14 dagen"].iter_rows(min_row=5, values_only=True):
        ean = norm_ean(r[0])
        if not ean:
            continue
        title = str(r[2] or "").strip()
        db.ensure_product(conn, ean, title)
        conn.execute("INSERT OR REPLACE INTO listings(channel, ean, sku, title) VALUES(?,?,?,?)",
                     (channel, ean, str(r[1] or ""), title))
        conn.execute(
            """INSERT INTO stock(channel, ean, date, stock, graded, unsellable_14d) VALUES(?,?,?,?,NULL,?)
               ON CONFLICT(channel, ean, date) DO UPDATE SET stock=excluded.stock,
                 unsellable_14d=excluded.unsellable_14d""",
            (channel, ean, end.isoformat(), _int(r[6]), _int(r[11])))
        n += 1
        stock_total += _int(r[6])
        ordered_total += _int(r[8])

    ch = db.channel(conn, channel)
    api_since = ch["api_since"] if ch else None
    days = 14
    for r in wb["Details per dag"].iter_rows(min_row=5, values_only=True):
        ean = norm_ean(r[0])
        if not ean:
            continue
        for i in range(days):  # nieuwste dag staat links
            d = (end - timedelta(days=i + 1)).isoformat()
            if api_since and d >= api_since:
                continue  # voor deze dagen is de API de bron
            conn.execute(
                "INSERT OR REPLACE INTO daily_sales(channel, ean, date, ordered, revenue, source) VALUES(?,?,?,?,?,'rapport')",
                (channel, ean, d, _int(r[3 + i]), float(r[3 + days + i] or 0)))
            if len(r) > 3 + 2 * days + i:
                conn.execute(
                    "INSERT OR REPLACE INTO daily_returns(channel, ean, date, received, source) VALUES(?,?,?,?,'rapport')",
                    (channel, ean, d, _int(r[3 + 2 * days + i])))
    conn.execute(
        "INSERT INTO sync_runs(channel, started, finished, ok, message) VALUES(?,datetime('now','localtime'),datetime('now','localtime'),1,?)",
        (channel, "LvB-rapport geimporteerd (stand %s): %d artikelen, %d stuks voorraad, %d besteld"
         % (end.isoformat(), n, stock_total, ordered_total)))
    conn.commit()
    return {"artikelen": n, "voorraad": stock_total, "besteld": ordered_total, "stand": end.isoformat()}
