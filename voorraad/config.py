"""Instellingen uit config.env (geheimen staan nooit in de code)."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "voorraad.db"


def load_env() -> dict:
    env = {}
    path = ROOT / "config.env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip('"').strip("'")
    for key, value in os.environ.items():
        if key.startswith(("BOL_", "SMTP_", "MAIL_", "VC_")):
            env[key] = value
    return env


ENV = load_env()


def get(key: str, default: str = "") -> str:
    return ENV.get(key, default)
