"""Eenmalige import van de masterdata-bestanden (besteleenheid en artikelcode per EAN)."""
from __future__ import annotations

import re

import openpyxl

# Handmatige uitzonderingen uit de projectinstructie: (artikelcode, besteleenheid, modus, notitie)
EXCEPTIONS = {
    "8721399170250": ("GRVALUEPACK03", 50, "normaal", "GRIXX Apple Oplader Bundel"),
    "4895229151253": ("PHHSTAE2146BK", 24, "normaal", "Audio; niet in masterdata"),
    "4895229154926": (None, 24, "normaal", "Audio; niet in masterdata"),
    "8720039511132": (None, None, "eol", "End of life - niet aanvullen"),
    "8721399170236": ("GRVALUEPACK01", 10, "normaal", None),
}
SSD_UNIT = 20  # SSD's gaan per omdoos van 20 (afgestemd met Ralph, 2026-11-12)


def norm_ean(value):
    if value is None:
        return None
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text if re.fullmatch(r"\d{13}", text) else None


def _num(value):
    return int(value) if isinstance(value, (int, float)) and value > 0 else None


def _find(header, predicate, start=0):
    for i in range(start, len(header)):
        cell = header[i]
        if cell is not None and predicate(str(cell).strip()):
            return i
    return None


def read_master(path: str):
    """Geeft per rij: (ean, artikelcode, naam, merk, besteleenheid, bron)."""
    out = []
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    for ws in wb.worksheets:
        rows = list(ws.iter_rows(min_row=1, max_row=600, max_col=60, values_only=True))
        if len(rows) < 5:
            continue
        groups, header = rows[1], rows[3]
        ean_i = _find(header, lambda s: s.startswith("EAN-13"))
        if ean_i is None:
            continue
        desc_i = _find(header, lambda s: s == "Description")
        type_i = _find(header, lambda s: s in ("Product Type", "Category"))
        unit_i = _find(header, lambda s: s == "# Retail Packs", ean_i + 1)
        outer_start = _find(groups, lambda s: s == "Outer Carton")
        outer_i = _find(header, lambda s: s == "# Retail Packs", outer_start) if outer_start else None
        master_start = _find(groups, lambda s: s == "Master Carton")
        master_i = _find(header, lambda s: s == "# Retail Packs", master_start) if master_start else None
        brand = "Grixx" if "grixx" in ws.title.lower() else "Philips"
        for r in rows[4:]:
            ean = norm_ean(r[ean_i])
            if not ean or not r[0]:
                continue
            ptype = str(r[type_i] or "") if type_i is not None else ""
            name = str(r[desc_i] or "").strip() if desc_i is not None else ""
            unit = _num(r[unit_i]) if unit_i is not None else None
            source = "masterdata"
            if "SSD" in ptype.upper():
                # SSD's gaan per doos van 20: de master carton als die bestaat (2,5 inch), anders de omdoos (M.2).
                unit = ((_num(r[master_i]) if master_i is not None else None)
                        or (_num(r[outer_i]) if outer_i is not None else None) or SSD_UNIT)
                source = "masterdata (omdoos)"
            out.append((ean, str(r[0]).strip(), name, brand, unit, source))
    return out


def read_bundles(path: str):
    """Bundelbestand: artikelcode en titel per bundel-EAN (geen besteleenheid)."""
    out = []
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    header = [str(c or "").strip() for c in rows[0]]
    code_i, ean_i, title_i = (header.index("Bundel productnummer"), header.index("Bundel EAN"),
                              header.index("Titel op Bol"))
    for r in rows[1:]:
        ean = norm_ean(r[ean_i])
        if ean:
            out.append((ean, str(r[code_i] or "").strip() or None, str(r[title_i] or "").strip()))
    return out


def import_files(conn, master_paths, bundle_paths=()):
    """Vult de artikeltabel. Handmatig in het dashboard gewijzigde artikelen blijven ongemoeid."""
    count = 0
    for path in master_paths:
        for ean, code, name, brand, unit, source in read_master(path):
            cur = conn.execute("SELECT unit_source FROM products WHERE ean=?", (ean,)).fetchone()
            if cur and cur["unit_source"] == "handmatig":
                continue
            conn.execute(
                """INSERT INTO products(ean, article_code, name, brand, order_unit, unit_source, updated_at)
                   VALUES(?,?,?,?,?,?,datetime('now'))
                   ON CONFLICT(ean) DO UPDATE SET article_code=excluded.article_code,
                     name=COALESCE(NULLIF(products.name,''), excluded.name), brand=excluded.brand,
                     order_unit=excluded.order_unit, unit_source=excluded.unit_source,
                     updated_at=excluded.updated_at""",
                (ean, code, name, brand, unit, source if unit else None))
            count += 1
    for path in bundle_paths:
        for ean, code, title in read_bundles(path):
            conn.execute(
                """INSERT INTO products(ean, article_code, name, brand, updated_at)
                   VALUES(?,?,?,'Grixx',datetime('now'))
                   ON CONFLICT(ean) DO UPDATE SET
                     article_code=COALESCE(products.article_code, excluded.article_code)""",
                (ean, code, title))
            count += 1
    for ean, (code, unit, mode, note) in EXCEPTIONS.items():
        cur = conn.execute("SELECT unit_source FROM products WHERE ean=?", (ean,)).fetchone()
        if cur and cur["unit_source"] == "handmatig":
            continue
        conn.execute("INSERT OR IGNORE INTO products(ean, updated_at) VALUES(?,datetime('now'))", (ean,))
        conn.execute(
            """UPDATE products SET article_code=COALESCE(?, article_code), order_unit=?,
                 unit_source=?, mode=?, note=COALESCE(?, note) WHERE ean=?""",
            (code, unit, "uitzondering" if unit else None, mode, note, ean))
    conn.commit()
    return count
