"""Artikelfoto's: eenmalig ophalen bij de marketplace en als kleine kopie lokaal bewaren.

Per artikel staan er twee bestanden in data/fotos: <ean>.jpg (groot) en <ean>-s.jpg (miniatuur).
Foto's horen bij het artikel, niet bij een kanaal: de eerste marketplace die een foto heeft, levert hem.
"""
from __future__ import annotations

import urllib.request
from urllib.parse import urlparse

from . import config
from .channels.base import ChannelError

DIR = config.DATA_DIR / "fotos"
ALLOWED_HOSTS = (".s-bol.com",)   # alleen downloaden van bekende mediaservers
MAX_BYTES = 2 * 1024 * 1024
RETRY_DAYS = 7                    # artikelen zonder foto proberen we na een week opnieuw
PER_RUN = 40


def path(ean: str, small: bool = False):
    return DIR / ("%s%s.jpg" % (ean, "-s" if small else ""))


def _download(url: str):
    u = urlparse(url)
    if u.scheme != "https" or not any((u.hostname or "").endswith(h) for h in ALLOWED_HOSTS):
        return None
    req = urllib.request.Request(url, headers={"User-Agent": "voorraadchecker"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES or data[:3] != b"\xff\xd8\xff":  # alleen echte JPEG-bestanden
        return None
    return data


def update(conn, ch, adapter) -> int:
    """Haalt foto's op voor artikelen van dit kanaal die er nog geen hebben. Geeft het aantal nieuwe."""
    if not hasattr(adapter, "fetch_photo_urls"):
        return 0
    DIR.mkdir(parents=True, exist_ok=True)
    rows = conn.execute(
        """SELECT DISTINCT s.ean FROM stock s LEFT JOIN photos f ON f.ean=s.ean
           WHERE s.channel=? AND s.date=(SELECT MAX(date) FROM stock WHERE channel=?) AND s.stock>0
             AND (f.ean IS NULL OR (f.ok=0 AND f.checked_at < date('now', ?)))
           LIMIT ?""", (ch["code"], ch["code"], "-%d days" % RETRY_DAYS, PER_RUN)).fetchall()
    new = 0
    for r in rows:
        ean, ok = r["ean"], 0
        try:
            urls = adapter.fetch_photo_urls(ean) or {}
            big = _download(urls["medium"]) if urls.get("medium") else None
            small = _download(urls["small"]) if urls.get("small") else None
            if big or small:
                path(ean).write_bytes(big or small)
                path(ean, small=True).write_bytes(small or big)
                ok = 1
                new += 1
        except (ChannelError, OSError, ValueError):
            ok = 0  # geen foto of tijdelijk niet bereikbaar: later opnieuw proberen
        conn.execute("INSERT OR REPLACE INTO photos(ean, ok, checked_at) VALUES(?,?,date('now'))", (ean, ok))
        conn.commit()
    return new


def available(conn) -> set:
    return {r[0] for r in conn.execute("SELECT ean FROM photos WHERE ok=1")}
