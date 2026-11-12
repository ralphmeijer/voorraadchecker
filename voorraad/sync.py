"""Dagelijkse ophaalronde: haalt per kanaal de gegevens op en legt ze vast in de database."""
from __future__ import annotations

import traceback
from datetime import date, timedelta

from . import db, photos, shipments
from .channels import ChannelError, get_adapter


def sync_channel(conn, ch, backfill_days: int = 0) -> str:
    code = ch["code"]
    adapter = get_adapter(ch)
    if not adapter.configured():
        raise ChannelError("De API-gegevens voor %s ontbreken in config.env" % ch["name"])
    today = date.today()

    stock = adapter.fetch_stock()
    orders = adapter.fetch_order_lines(backfill_days)
    returns = adapter.fetch_returns((today - timedelta(days=45)).isoformat())
    known_done = [r[0] for r in conn.execute(
        "SELECT ship_id FROM shipments WHERE channel=? AND state='DONE'", (code,))]
    ships = adapter.fetch_shipments((today - timedelta(days=shipments.HISTORY_DAYS)).isoformat(), known_done)

    # Alles is opgehaald; nu pas schrijven, zodat een mislukte ronde niets half achterlaat.
    for s in stock:
        db.ensure_product(conn, s.ean, s.title)
        conn.execute("INSERT OR REPLACE INTO listings(channel, ean, sku, title) VALUES(?,?,?,?)",
                     (code, s.ean, s.sku, s.title))
        conn.execute(
            """INSERT INTO stock(channel, ean, date, stock, graded) VALUES(?,?,?,?,?)
               ON CONFLICT(channel, ean, date) DO UPDATE SET stock=excluded.stock, graded=excluded.graded""",
            (code, s.ean, today.isoformat(), s.stock, s.graded))
    for o in orders:
        conn.execute("INSERT OR REPLACE INTO order_items(channel, item_id, order_id, ean, placed_date, quantity, cancelled) VALUES(?,?,?,?,?,?,?)",
                     (code, o.item_id, o.order_id, o.ean, o.placed_date, o.quantity, o.cancelled))
    for r in returns:
        conn.execute("INSERT OR REPLACE INTO return_items(channel, rma_id, ean, reg_date, quantity) VALUES(?,?,?,?,?)",
                     (code, r.rma_id, r.ean, r.reg_date, r.quantity))

    # Vanaf api_since is de API de bron; oudere dagen houden de waarden uit het LvB-rapport.
    # De standaardronde ziet 48 uur terug, dus gisteren is op de eerste dag al volledig.
    wanted = (today - timedelta(days=max(1, backfill_days))).isoformat()
    api_since = ch["api_since"]
    if not api_since or wanted < api_since:
        api_since = wanted
        conn.execute("UPDATE channels SET api_since=? WHERE code=?", (api_since, code))
    conn.execute("DELETE FROM daily_sales WHERE channel=? AND date>=?", (code, api_since))
    conn.execute(
        """INSERT INTO daily_sales(channel, ean, date, ordered, revenue, source)
           SELECT channel, ean, placed_date, SUM(quantity - cancelled), NULL, 'api' FROM order_items
           WHERE channel=? AND placed_date>=? GROUP BY ean, placed_date""", (code, api_since))
    conn.execute("DELETE FROM daily_returns WHERE channel=? AND date>=?", (code, api_since))
    conn.execute(
        """INSERT INTO daily_returns(channel, ean, date, received, source)
           SELECT channel, ean, reg_date, SUM(quantity), 'api' FROM return_items
           WHERE channel=? AND reg_date>=? GROUP BY ean, reg_date""", (code, api_since))
    shipments.store(conn, code, ships)
    n_inbound = shipments.rebuild_inbound(conn, ch, today)
    n_dev = shipments.evaluate(conn, ch, today)
    conn.commit()
    note = shipments.notify(conn, ch, today)
    try:
        photos.update(conn, ch, adapter)
    except Exception as e:  # foto's zijn bijzaak: een fout hier mag de ophaalronde niet laten mislukken
        print("Foto's ophalen mislukt: %s" % e)
    return "%d artikelen, %d orderregels, %d retouren, %d zendingen bijgewerkt, %d regels onderweg, %d afwijkingen%s" % (
        len(stock), len(orders), len(returns), len(ships), n_inbound, n_dev, " (" + note + ")" if note else "")


def run(conn, only: str = None, backfill_days: int = 0) -> bool:
    all_ok = True
    for ch in db.channels(conn):
        if only and ch["code"] != only:
            continue
        if not get_adapter(ch).configured():
            print("[--] %s: nog niet gekoppeld, overgeslagen" % ch["name"])
            continue
        cur = conn.execute("INSERT INTO sync_runs(channel, started) VALUES(?, datetime('now','localtime'))",
                           (ch["code"],))
        conn.commit()
        try:
            message, ok = sync_channel(conn, ch, backfill_days), 1
        except ChannelError as e:
            conn.rollback()
            message, ok = str(e), 0
        except Exception as e:  # onverwachte fout: vastleggen en doorgaan met het volgende kanaal
            conn.rollback()
            traceback.print_exc()
            message, ok = "Onverwachte fout: %s" % e, 0
        conn.execute("UPDATE sync_runs SET finished=datetime('now','localtime'), ok=?, message=? WHERE id=?",
                     (ok, message, cur.lastrowid))
        conn.commit()
        print("[%s] %s: %s" % ("ok" if ok else "FOUT", ch["name"], message))
        all_ok = all_ok and bool(ok)
    return all_ok
