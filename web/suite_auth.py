"""Replay-safe FastOffice suite ticket redemption."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sqlite3
import time
from pathlib import Path


def _database():
    path = Path(os.getenv("FASTSME_AUTH_DB", "data/fastsme-accounts.sqlite"))
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE IF NOT EXISTS suite_ticket_redemptions(
        jti_hash TEXT PRIMARY KEY, expires_at INTEGER NOT NULL, redeemed_at INTEGER NOT NULL
    )""")
    return con


def redeem(token: str, audience: str) -> dict | None:
    secret = os.getenv("FASTOFFICE_SSO_SECRET", "")
    if not secret:
        return None
    try:
        encoded, supplied = token.split(".", 1)
        expected = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, supplied):
            return None
        body = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        now = int(time.time())
        required = {"sub", "email", "name", "org_id", "org_name", "role", "jti", "exp", "aud"}
        if not required.issubset(body) or body["aud"] != audience or body["exp"] < now:
            return None
        digest = hashlib.sha256(body["jti"].encode()).hexdigest()
        with _database() as con:
            con.execute("DELETE FROM suite_ticket_redemptions WHERE expires_at<?", (now,))
            if con.execute("SELECT 1 FROM suite_ticket_redemptions WHERE jti_hash=?", (digest,)).fetchone():
                return None
            con.execute(
                "INSERT INTO suite_ticket_redemptions(jti_hash,expires_at,redeemed_at) VALUES(?,?,?)",
                (digest, body["exp"], now),
            )
        return body
    except (ValueError, TypeError, KeyError, json.JSONDecodeError, sqlite3.Error):
        return None
