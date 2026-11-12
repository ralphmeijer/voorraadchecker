"""SQLite-database: schema en kleine hulpfuncties."""
from __future__ import annotations

import sqlite3

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS channels(
  code TEXT PRIMARY KEY, name TEXT NOT NULL, adapter TEXT NOT NULL, active INTEGER DEFAULT 1,
  target_days INTEGER DEFAULT 60, lead_days INTEGER DEFAULT 7, buffer_days INTEGER DEFAULT 7,
  trigger_days INTEGER DEFAULT 16, velocity_days INTEGER DEFAULT 14, api_since TEXT);
CREATE TABLE IF NOT EXISTS products(
  ean TEXT PRIMARY KEY, article_code TEXT, name TEXT, brand TEXT, order_unit INTEGER,
  unit_source TEXT, mode TEXT DEFAULT 'normaal', note TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS listings(
  channel TEXT, ean TEXT, sku TEXT, title TEXT, PRIMARY KEY(channel, ean));
CREATE TABLE IF NOT EXISTS stock(
  channel TEXT, ean TEXT, date TEXT, stock INTEGER, graded INTEGER, unsellable_14d INTEGER,
  PRIMARY KEY(channel, ean, date));
CREATE TABLE IF NOT EXISTS daily_sales(
  channel TEXT, ean TEXT, date TEXT, ordered INTEGER, revenue REAL, source TEXT,
  PRIMARY KEY(channel, ean, date));
CREATE TABLE IF NOT EXISTS daily_returns(
  channel TEXT, ean TEXT, date TEXT, received INTEGER, source TEXT,
  PRIMARY KEY(channel, ean, date));
CREATE TABLE IF NOT EXISTS order_items(
  channel TEXT, item_id TEXT, order_id TEXT, ean TEXT, placed_date TEXT,
  quantity INTEGER, cancelled INTEGER, PRIMARY KEY(channel, item_id));
CREATE TABLE IF NOT EXISTS return_items(
  channel TEXT, rma_id TEXT, ean TEXT, reg_date TEXT, quantity INTEGER,
  PRIMARY KEY(channel, rma_id));
CREATE TABLE IF NOT EXISTS inbound(
  channel TEXT, ref TEXT, ean TEXT, quantity INTEGER, state TEXT, created TEXT,
  PRIMARY KEY(channel, ref, ean));
CREATE TABLE IF NOT EXISTS shipments(
  channel TEXT, ship_id TEXT, reference TEXT, state TEXT, created TEXT, expected TEXT, arrived TEXT,
  done_at TEXT, PRIMARY KEY(channel, ship_id));
CREATE TABLE IF NOT EXISTS shipment_lines(
  channel TEXT, ship_id TEXT, ean TEXT, announced INTEGER, received INTEGER, in_progress INTEGER,
  regular INTEGER, graded INTEGER, PRIMARY KEY(channel, ship_id, ean));
CREATE TABLE IF NOT EXISTS deviations(
  id INTEGER PRIMARY KEY AUTOINCREMENT, channel TEXT, ship_id TEXT, ean TEXT, kind TEXT, detail TEXT,
  first_seen TEXT, last_seen TEXT, resolved_at TEXT, handled_at TEXT, handled_by TEXT, mailed_at TEXT,
  UNIQUE(channel, ship_id, ean, kind));
CREATE TABLE IF NOT EXISTS handoffs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, channel TEXT, ean TEXT, units INTEGER, pieces INTEGER,
  username TEXT, created_at TEXT, undone INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS sync_runs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, channel TEXT, started TEXT, finished TEXT,
  ok INTEGER, message TEXT);
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, pw TEXT, role TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS sessions(
  token TEXT PRIMARY KEY, user_id INTEGER, csrf TEXT, expires TEXT);
CREATE TABLE IF NOT EXISTS snapshots(
  id INTEGER PRIMARY KEY AUTOINCREMENT, channel TEXT, date TEXT, created_at TEXT, data TEXT);
"""


def connect() -> sqlite3.Connection:
    config.DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(config.DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    # Het eerste kanaal. Nieuwe marketplaces komen hier als extra rij bij.
    conn.execute(
        "INSERT OR IGNORE INTO channels(code, name, adapter) VALUES('bol', 'Bol.com LvB', 'bol')")
    conn.execute(
        "INSERT OR IGNORE INTO channels(code, name, adapter) VALUES('amazon', 'Amazon FBA', 'amazon')")
    conn.commit()


def channel(conn, code: str):
    return conn.execute("SELECT * FROM channels WHERE code=?", (code,)).fetchone()


def channels(conn):
    return conn.execute("SELECT * FROM channels WHERE active=1 ORDER BY CASE code WHEN 'bol' THEN 0 ELSE 1 END, name").fetchall()


def ensure_product(conn, ean: str, title: str = "") -> None:
    """Maak een artikel aan als het nog niet bestaat. De besteleenheid blijft leeg: niet gokken."""
    brand = None
    low = (title or "").lower()
    if "grixx" in low:
        brand = "Grixx"
    elif "philips" in low:
        brand = "Philips"
    conn.execute(
        "INSERT OR IGNORE INTO products(ean, name, brand, updated_at) VALUES(?,?,?,datetime('now'))",
        (ean, title, brand))
    conn.execute(
        "UPDATE products SET name=? WHERE ean=? AND (name IS NULL OR name='')", (title, ean))
    if brand:
        conn.execute("UPDATE products SET brand=? WHERE ean=? AND brand IS NULL", (brand, ean))
