"""Gebruikers, wachtwoorden en sessies."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from datetime import datetime, timedelta

ROLES = ("beheer", "logistiek")
ITER = 240000
SESSION_DAYS = 14
_failures = {}  # gebruikersnaam -> (aantal, geblokkeerd tot)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITER)
    return "pbkdf2$%d$%s$%s" % (ITER, salt.hex(), dk.hex())


def check_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt, dk = stored.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iters))
        return hmac.compare_digest(calc.hex(), dk)
    except Exception:
        return False


def set_user(conn, username: str, password: str, role: str) -> None:
    if role not in ROLES:
        raise ValueError("Rol moet beheer of logistiek zijn")
    if len(password) < 10:
        raise ValueError("Het wachtwoord moet minstens 10 tekens hebben")
    conn.execute(
        """INSERT INTO users(username, pw, role, created_at) VALUES(?,?,?,datetime('now'))
           ON CONFLICT(username) DO UPDATE SET pw=excluded.pw, role=excluded.role""",
        (username.strip().lower(), hash_password(password), role))
    conn.commit()


def login(conn, username: str, password: str):
    """Geeft (token, fout). Na vijf mislukte pogingen vijf minuten geblokkeerd."""
    username = username.strip().lower()
    count, until = _failures.get(username, (0, 0))
    if time.time() < until:
        return None, "Te veel mislukte pogingen. Probeer het over een paar minuten opnieuw."
    user = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    stored = user["pw"] if user else "pbkdf2$1$00$00"
    if not check_password(password, stored) or not user:
        count += 1
        _failures[username] = (0, time.time() + 300) if count >= 5 else (count, 0)
        return None, "Onjuiste gebruikersnaam of wachtwoord."
    _failures.pop(username, None)
    token = secrets.token_urlsafe(32)
    expires = (datetime.utcnow() + timedelta(days=SESSION_DAYS)).isoformat()
    conn.execute("DELETE FROM sessions WHERE expires < ?", (datetime.utcnow().isoformat(),))
    conn.execute("INSERT INTO sessions(token, user_id, csrf, expires) VALUES(?,?,?,?)",
                 (token, user["id"], secrets.token_urlsafe(24), expires))
    conn.commit()
    return token, None


def session_user(conn, token: str):
    if not token:
        return None
    return conn.execute(
        """SELECT u.id, u.username, u.role, s.csrf, s.token FROM sessions s JOIN users u ON u.id=s.user_id
           WHERE s.token=? AND s.expires>?""", (token, datetime.utcnow().isoformat())).fetchone()


def logout(conn, token: str) -> None:
    conn.execute("DELETE FROM sessions WHERE token=?", (token,))
    conn.commit()
