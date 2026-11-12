"""Webserver van het dashboard. Draait achter Caddy op 127.0.0.1."""
from __future__ import annotations

import email
import email.policy
import io
import json
import mimetypes
import re
import threading
from datetime import date, timedelta
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

from . import auth, calc, config, db, drafts, excel, photos, report_import, shipments, sync, views
from .channels import ChannelError, get_adapter
from .masterdata import norm_ean

STATIC = config.ROOT / "static"
MAX_BODY = 6 * 1024 * 1024
_sync_lock = threading.Lock()


def _background_sync(code):
    if not _sync_lock.acquire(blocking=False):
        return
    try:
        conn = db.connect()
        try:
            sync.run(conn, only=code)
        finally:
            conn.close()
    finally:
        _sync_lock.release()


class Handler(BaseHTTPRequestHandler):
    server_version = "Voorraadchecker"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    # --- antwoorden -----------------------------------------------------------
    def send(self, status, body, ctype="text/html; charset=utf-8", headers=None):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'; form-action 'self'")
        if not ctype.startswith(("text/css", "text/javascript", "image/")):
            self.send_header("Cache-Control", "no-store")
        for k, v in (headers or []):
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def redirect(self, location, headers=None):
        self.send(303, "", headers=[("Location", location)] + (headers or []))

    def back(self, path, code=None, ok=None, bad=None):
        parts = []
        if code:
            parts.append("kanaal=" + quote(code))
        if ok:
            parts.append("ok=" + quote(ok))
        if bad:
            parts.append("fout=" + quote(bad))
        self.redirect(path + ("?" + "&".join(parts) if parts else ""))

    def page(self, title, body, active=""):
        flash = None
        if self.q.get("ok"):
            flash = ("good", self.q["ok"][0][:300])
        elif self.q.get("fout"):
            flash = ("bad", self.q["fout"][0][:300])
        # Wachtpagina's verversen ook zonder script: de browser volgt de Refresh-kop.
        headers = [("Refresh", "4; url=%s?kanaal=%s" % (urlparse(self.path).path, quote(self.ch["code"])))] if 'data-refresh="' in body and self.ch else None
        self.send(200, views.layout(title, body, self.user, self.chans, self.ch["code"] if self.ch else None, active, flash), headers=headers)

    def cookie(self, token, max_age):
        secure = "; Secure" if config.get("VC_COOKIE_SECURE", "0") == "1" else ""
        return ("Set-Cookie", "vc_session=%s; Path=/; HttpOnly; SameSite=Lax; Max-Age=%d%s" % (token, max_age, secure))

    # --- aanvraag -------------------------------------------------------------
    def read_form(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ValueError("Het bestand is te groot (maximaal 6 MB)")
        raw = self.rfile.read(length)
        ctype = self.headers.get("Content-Type", "")
        fields, files = {}, {}
        if ctype.startswith("multipart/form-data"):
            msg = email.message_from_bytes(b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + raw, policy=email.policy.HTTP)
            for part in msg.iter_parts():
                name = part.get_param("name", header="content-disposition")
                if part.get_filename():
                    files[name] = (part.get_filename(), part.get_payload(decode=True))
                else:
                    fields[name] = (part.get_payload(decode=True) or b"").decode("utf-8", "replace").strip()
        else:
            for k, v in parse_qs(raw.decode("utf-8", "replace"), keep_blank_values=True).items():
                fields[k] = v[0].strip()
        return fields, files

    def handle_request(self, method):
        url = urlparse(self.path)
        self.q = parse_qs(url.query)
        path = url.path
        self.user = self.ch = None
        self.chans = []
        if method == "GET" and path.startswith("/static/"):
            return self.static(path[8:])
        self.conn = db.connect()
        try:
            jar = SimpleCookie(self.headers.get("Cookie", ""))
            token = jar["vc_session"].value if "vc_session" in jar else ""
            self.user = auth.session_user(self.conn, token)
            form, files = ({}, {})
            if method == "POST":
                try:
                    form, files = self.read_form()
                except ValueError as e:
                    return self.send(413, views.layout("Fout", "<h1>%s</h1>" % e))
            if path == "/inloggen" and method == "POST":
                new, err = auth.login(self.conn, form.get("username", ""), form.get("password", ""))
                if err:
                    return self.send(401, views.login_page(err))
                return self.redirect("/", [self.cookie(new, auth.SESSION_DAYS * 86400)])
            if not self.user:
                if method == "GET" and path == "/inloggen":
                    return self.send(200, views.login_page())
                return self.redirect("/inloggen")
            if method == "POST" and form.get("csrf") != self.user["csrf"]:
                return self.send(403, views.layout("Fout", "<h1>De sessie is verlopen</h1><p><a href='/'>Ga terug</a> en probeer het opnieuw.</p>"))
            self.chans = db.channels(self.conn)
            code = form.get("kanaal") or (self.q.get("kanaal") or [""])[0]
            self.ch = db.channel(self.conn, code) or (self.chans[0] if self.chans else None)
            if method == "GET":
                return self.get(path)
            return self.post(path, form, files)
        finally:
            self.conn.close()

    def do_GET(self):
        self.handle_request("GET")

    def do_POST(self):
        self.handle_request("POST")

    def static(self, name):
        target = (STATIC / name).resolve()
        if STATIC.resolve() not in target.parents or not target.is_file():
            return self.send(404, "Niet gevonden", "text/plain; charset=utf-8")
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if ctype in ("text/css", "application/javascript", "text/javascript"):
            ctype = ("text/css" if ctype == "text/css" else "text/javascript") + "; charset=utf-8"
        self.send(200, target.read_bytes(), ctype, [("Cache-Control", "max-age=300")])

    def admin(self):
        if self.user["role"] != "beheer":
            self.send(403, views.layout("Geen toegang", "<h1>Geen toegang</h1><p>Deze pagina is alleen voor beheerders.</p>",
                                        self.user, self.chans, self.ch["code"] if self.ch else None))
            return False
        return True

    # --- pagina's -------------------------------------------------------------
    def get(self, path):
        conn, ch = self.conn, self.ch
        if path == "/inloggen":
            return self.redirect("/")
        if path == "/account":
            return self.page("Mijn account", views.account(self.user))
        if path.startswith("/foto/"):
            m = re.fullmatch(r"/foto/(\d{13})(-s)?\.jpg", path)
            target = photos.path(m.group(1), bool(m.group(2))) if m else None
            if not target or not target.is_file():
                return self.send(404, "Niet gevonden", "text/plain; charset=utf-8")
            return self.send(200, target.read_bytes(), "image/jpeg", [("Cache-Control", "private, max-age=86400")])
        if ch is None:
            return self.page("Voorraadchecker", "<h1>Er is nog geen kanaal ingesteld</h1>")
        code = ch["code"]
        if path == "/":
            result = calc.compute(conn, ch)
            handoffs = conn.execute(
                """SELECT h.*, l.title FROM handoffs h LEFT JOIN listings l ON l.channel=h.channel AND l.ean=h.ean
                   WHERE h.channel=? AND h.undone=0 AND h.created_at>=? ORDER BY h.created_at DESC LIMIT 30""",
                (code, (date.today() - timedelta(days=14)).isoformat())).fetchall()
            last = conn.execute("SELECT * FROM sync_runs WHERE channel=? AND finished IS NOT NULL ORDER BY id DESC LIMIT 1", (code,)).fetchone()
            stale = (date.today() - date.fromisoformat(result["ref_date"])).days if result["ref_date"] else None
            week = None
            snap = conn.execute("SELECT id, date, created_at, data FROM snapshots WHERE channel=? ORDER BY id DESC LIMIT 1", (code,)).fetchone()
            if snap:
                seen = conn.execute("SELECT 1 FROM snapshot_seen WHERE user_id=? AND snapshot_id=?", (self.user["id"], snap["id"])).fetchone()
                week = {"id": snap["id"], "date": snap["date"], "created_at": snap["created_at"], "seen": bool(seen),
                        "count": len(json.loads(snap["data"]).get("rows", []))}
            return self.page("Aanvullen", views.dashboard(result, ch, self.user, handoffs, last, stale,
                                                            shipments.open_deviations(conn, code), shipments.running(conn, code), week,
                                                            drafts.can_create(get_adapter(ch)), drafts.open_drafts(conn, code)), "aanvullen")
        if path == "/zendingen":
            return self.page("Zendingen", views.shipment_list(ch, shipments.all_shipments(conn, code)), "aanvullen")
        m = re.fullmatch(r"/zendingen/([A-Za-z0-9_-]{1,60})", path)
        if m:
            ship, lines, devs = shipments.one(conn, code, m.group(1))
            if not ship:
                return self.back("/zendingen", code, bad="Deze zending is niet bekend")
            return self.page("Zending %s" % (ship["reference"] or ship["ship_id"]), views.shipment_detail(ch, ship, lines, devs), "aanvullen")
        if path == "/zending/nieuw":
            if not drafts.can_create(get_adapter(ch)):
                return self.back("/", code, bad="Voor dit kanaal kunnen nog geen zendingen worden aangemaakt")
            return self.page("Zending voorbereiden", views.new_shipment(calc.compute(conn, ch), ch, self.user), "aanvullen")
        m = re.fullmatch(r"/zending/(\d+)", path)
        if m:
            draft = drafts.get(conn, code, int(m.group(1)))
            if not draft:
                return self.back("/", code, bad="Deze voorbereiding bestaat niet")
            adapter = get_adapter(ch)
            note = None
            try:
                drafts.refresh(conn, ch, adapter, draft)
            except ChannelError as e:
                note = str(e)
            draft = drafts.get(conn, code, draft["id"])
            groups, unassigned, all_lines = drafts.detail(conn, draft)
            dates, refs = [], {}
            if draft["status"] == "klaar":
                dates = drafts.delivery_dates(adapter)
                taken = []
                for item in groups:
                    if item["g"]["state"] in ("open", "mislukt") and not item["g"]["reference"]:
                        refs[item["g"]["group_no"]] = drafts.next_reference(conn, code, taken)
                        taken.append(refs[item["g"]["group_no"]])
            body = views.shipment_page(ch, self.user, draft, groups, unassigned, all_lines, dates, refs,
                                       drafts.TRANSPORTERS, getattr(adapter, "demo", False), drafts.has_remote(conn, draft["id"]))
            if note:
                body = '<div class="flash bad" role="alert">%s</div>' % views.esc(note) + body
            return self.page("Zending voorbereiden", body, "aanvullen")
        if path == "/weekadvies":
            wanted = (self.q.get("id") or [""])[0]
            snap = conn.execute("SELECT * FROM snapshots WHERE channel=? AND (id=? OR ?='') ORDER BY id DESC LIMIT 1",
                                (code, wanted if wanted.isdigit() else -1, "" if wanted.isdigit() else "")).fetchone()
            if not snap:
                return self.back("/", code, bad="Er is nog geen weekadvies vastgelegd")
            conn.execute("INSERT OR IGNORE INTO snapshot_seen(user_id, snapshot_id) VALUES(?,?)", (self.user["id"], snap["id"]))
            conn.commit()
            others = conn.execute("SELECT id, date, created_at FROM snapshots WHERE channel=? AND id<>? ORDER BY id DESC LIMIT 8",
                                  (code, snap["id"])).fetchall()
            return self.page("Weekadvies", views.weekadvies(ch, snap, json.loads(snap["data"]), others), "aanvullen")
        if path == "/artikelen":
            result = calc.compute(conn, ch)
            status = (self.q.get("status") or [""])[0]
            return self.page("Alle artikelen", views.articles(result, ch, status if status in calc.STATUS_ORDER else "",
                                                               bool(self.q.get("zonder"))), "artikelen")
        if path.startswith("/artikel/"):
            ean = norm_ean(path[9:])
            result = calc.compute(conn, ch)
            row = next((r for r in result["rows"] if r["ean"] == ean), None)
            if not row:
                return self.send(404, views.layout("Niet gevonden", "<h1>Artikel niet gevonden</h1>", self.user, self.chans, code))
            refd = date.fromisoformat(result["ref_date"])
            per_day = {r["date"]: r["ordered"] or 0 for r in conn.execute(
                "SELECT date, ordered FROM daily_sales WHERE channel=? AND ean=? AND date>=?",
                (code, ean, (refd - timedelta(days=28)).isoformat()))}
            first = conn.execute("SELECT MIN(date) FROM daily_sales WHERE channel=?", (code,)).fetchone()[0] or result["ref_date"]
            history = []
            for i in range(28, 0, -1):
                d = (refd - timedelta(days=i)).isoformat()
                if d >= first:
                    history.append((d, per_day.get(d, 0)))
            product = conn.execute("SELECT * FROM products WHERE ean=?", (ean,)).fetchone()
            return self.page(row["name"] or ean, views.article(row, ch, self.user, history, product, result["params"]), "artikelen")
        if path == "/export.xlsx":
            result = calc.compute(conn, ch)
            if not result["ref_date"]:
                return self.back("/", code, bad="Er zijn nog geen gegevens om te exporteren")
            data = excel.build(result, ch["name"])
            name = "%s_aanvuladvies_%s.xlsx" % ("LvB" if ch["adapter"] == "bol" else ch["code"].capitalize(), result["ref_date"])
            return self.send(200, data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             [("Content-Disposition", 'attachment; filename="%s"' % name)])
        if path == "/instellingen":
            if not self.admin():
                return
            runs = conn.execute("SELECT * FROM sync_runs WHERE channel=? ORDER BY id DESC LIMIT 8", (code,)).fetchall()
            users = conn.execute("SELECT id, username, role FROM users ORDER BY username").fetchall()
            mail_ready = bool(config.get("SMTP_HOST") and config.get("MAIL_TO"))
            return self.page("Instellingen", views.settings(ch, self.user, runs, users, get_adapter(ch).configured(), mail_ready), "instellingen")
        self.send(404, views.layout("Niet gevonden", "<h1>Pagina niet gevonden</h1>", self.user, self.chans, code))

    # --- acties ---------------------------------------------------------------
    def post(self, path, form, files):
        conn, ch, user = self.conn, self.ch, self.user
        code = ch["code"] if ch else None
        if path == "/uitloggen":
            auth.logout(conn, user["token"])
            return self.redirect("/inloggen", [self.cookie("", 0)])
        if path == "/account":
            row = conn.execute("SELECT pw FROM users WHERE id=?", (user["id"],)).fetchone()
            if not auth.check_password(form.get("current", ""), row["pw"]):
                return self.back("/account", bad="Het huidige wachtwoord klopt niet")
            try:
                auth.set_user(conn, user["username"], form.get("new", ""), user["role"])
            except ValueError as e:
                return self.back("/account", bad=str(e))
            return self.back("/account", ok="Wachtwoord gewijzigd")
        if path == "/afvinken":
            ean = norm_ean(form.get("ean"))
            try:
                pieces = int(form.get("pieces") or 0)
                units = int(form["units"]) if form.get("units") else None
            except ValueError:
                pieces, units = 0, None
            if not ean or pieces <= 0 or pieces > 100000:
                return self.back("/", code, bad="Ongeldige regel")
            conn.execute("INSERT INTO handoffs(channel, ean, units, pieces, username, created_at) VALUES(?,?,?,?,?,datetime('now','localtime'))",
                         (code, ean, units, pieces, user["username"]))
            conn.commit()
            return self.back("/", code, ok="Afgevinkt als aangemeld: %d stuks" % pieces)
        if path == "/zending/nieuw":
            adapter = get_adapter(ch)
            if not drafts.can_create(adapter):
                return self.back("/", code, bad="Voor dit kanaal kunnen nog geen zendingen worden aangemaakt")
            known = {r[0] for r in conn.execute("SELECT ean FROM listings WHERE channel=?", (code,))}
            lines = []
            for key, value in form.items():
                ean = norm_ean(key[2:]) if key.startswith("p_") else None
                if not ean or ean not in known or not value:
                    continue
                if not value.isdigit() or int(value) > 9999:
                    return self.back("/zending/nieuw", code, bad="Vul per artikel een heel aantal van 0 tot 9999 in")
                lines.append((ean, int(value)))
            try:
                draft_id = drafts.create(conn, ch, adapter, user["username"], lines)
            except (ValueError, ChannelError) as e:
                conn.rollback()
                return self.back("/zending/nieuw", code, bad=str(e))
            return self.back("/zending/%d" % draft_id, code)
        m = re.fullmatch(r"/zending/(\d+)/(aanmaken|annuleren|sluiten|groep-verwijderen|regel-verwijderen)", path)
        if m:
            draft = drafts.get(conn, code, int(m.group(1)))
            if not draft:
                return self.back("/", code, bad="Deze voorbereiding bestaat niet")
            target = "/zending/%d" % draft["id"]
            group_no = int(form["groep"]) if (form.get("groep") or "").isdigit() else -1
            try:
                if m.group(2) == "sluiten":
                    drafts.close(conn, draft["id"])
                    return self.back("/", code, ok="Voorbereiding afgesloten" if drafts.has_remote(conn, draft["id"]) else "Voorbereiding verwijderd")
                if m.group(2) == "annuleren":
                    if form.get("zeker") != "ja":
                        raise ValueError("Vink aan dat je de zending wilt annuleren")
                    drafts.cancel_remote(conn, ch, get_adapter(ch), draft, group_no)
                    return self.back(target, code, ok="De annulering is naar bol gestuurd.")
                if draft["status"] != "klaar":
                    raise ValueError("Deze voorbereiding is niet meer open")
                if m.group(2) == "groep-verwijderen":
                    drafts.remove_group(conn, draft, group_no)
                    return self.back(target, code, ok="Deelzending verwijderd")
                if m.group(2) == "regel-verwijderen":
                    drafts.remove_line(conn, draft, norm_ean(form.get("ean")) or "")
                    return self.back(target, code, ok="Artikel uit de zending gehaald")
                if m.group(2) == "aanmaken":
                    drafts.submit_group(conn, ch, get_adapter(ch), draft, group_no, form, user["username"])
                    return self.back(target, code, ok="De zending is naar bol gestuurd. Bol bevestigt binnen enkele ogenblikken.")
            except (ValueError, ChannelError) as e:
                conn.rollback()
                return self.back(target, code, bad=str(e))
        if path == "/afwijking/afhandelen":
            if (form.get("id") or "").isdigit():
                shipments.handle(conn, code, int(form["id"]), user["username"])
            return self.back("/", code, ok="Afwijking afgehandeld")
        if path == "/afvinken/ongedaan":
            conn.execute("UPDATE handoffs SET undone=1 WHERE id=? AND channel=?", (form.get("id"), code))
            conn.commit()
            return self.back("/", code, ok="Aanmelding ongedaan gemaakt")

        # Vanaf hier alleen beheer.
        if not self.admin():
            return
        if path.startswith("/artikel/"):
            ean = norm_ean(path[9:])
            if not ean or not conn.execute("SELECT 1 FROM products WHERE ean=?", (ean,)).fetchone():
                return self.back("/artikelen", code, bad="Artikel niet gevonden")
            mode = form.get("mode") if form.get("mode") in ("normaal", "eol", "uit") else "normaal"
            unit = None
            if form.get("order_unit"):
                try:
                    unit = int(form["order_unit"])
                    if not 1 <= unit <= 10000:
                        raise ValueError
                except ValueError:
                    return self.back("/artikel/" + ean, code, bad="De besteleenheid moet een geheel getal tussen 1 en 10.000 zijn")
            conn.execute(
                """UPDATE products SET article_code=?, order_unit=?, unit_source=?, mode=?, note=?, updated_at=datetime('now') WHERE ean=?""",
                (form.get("article_code", "")[:60] or None, unit, "handmatig", mode, form.get("note", "")[:200] or None, ean))
            conn.commit()
            return self.back("/artikel/" + ean, code, ok="Artikel opgeslagen")
        if path == "/instellingen":
            try:
                vals = [int(form[k]) for k in ("target_days", "lead_days", "buffer_days", "trigger_days", "velocity_days")]
                if not all(1 <= v <= 365 for v in vals):
                    raise ValueError
            except (KeyError, ValueError):
                return self.back("/instellingen", code, bad="Vul voor elke parameter een getal tussen 1 en 365 in")
            conn.execute("UPDATE channels SET target_days=?, lead_days=?, buffer_days=?, trigger_days=?, velocity_days=? WHERE code=?",
                         vals + [code])
            conn.commit()
            return self.back("/instellingen", code, ok="Parameters opgeslagen")
        if path == "/verversen":
            if not get_adapter(ch).configured():
                return self.back("/instellingen", code, bad="De API-gegevens ontbreken in config.env")
            threading.Thread(target=_background_sync, args=(code,), daemon=True).start()
            return self.back("/instellingen", code, ok="Verversen is gestart. Dit duurt een paar minuten; herlaad daarna deze pagina.")
        if path == "/rapport":
            if "bestand" not in files:
                return self.back("/instellingen", code, bad="Kies eerst een bestand")
            name, data = files["bestand"]
            try:
                res = report_import.import_report(conn, io.BytesIO(data), code, filename=name)
            except Exception as e:
                conn.rollback()
                return self.back("/instellingen", code, bad="Importeren mislukt: %s" % e)
            return self.back("/instellingen", code, ok="Rapport geimporteerd: %(artikelen)d artikelen, %(voorraad)d stuks voorraad, %(besteld)d besteld" % res)
        if path == "/gebruiker":
            try:
                auth.set_user(conn, form.get("username", ""), form.get("password", ""), form.get("role", ""))
            except ValueError as e:
                return self.back("/instellingen", code, bad=str(e))
            return self.back("/instellingen", code, ok="Gebruiker opgeslagen")
        if path == "/gebruiker/verwijderen":
            if str(user["id"]) != form.get("id"):
                conn.execute("DELETE FROM sessions WHERE user_id=?", (form.get("id"),))
                conn.execute("DELETE FROM users WHERE id=?", (form.get("id"),))
                conn.commit()
            return self.back("/instellingen", code, ok="Gebruiker verwijderd")
        self.send(404, views.layout("Niet gevonden", "<h1>Pagina niet gevonden</h1>", user, self.chans, code))


def serve(host: str, port: int):
    conn = db.connect()
    db.init(conn)
    conn.close()
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    print("Voorraadchecker draait op http://%s:%d" % (host, port))
    httpd.serve_forever()
