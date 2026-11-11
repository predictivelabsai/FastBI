"""Bring-your-own-key (BYOK) for signed-in FastBI users.

Guests get FREE_QUERIES questions on the server XAI_API_KEY. After that they
must sign in, and signed-in users must add their own xAI key (unless their
email is on the admin allowlist, which may keep using the server key). The key
is Fernet-encrypted in SQLite and never sent back to the browser or logged.
LLM callers read it through a context variable set per request.
"""
from __future__ import annotations

import contextvars
import logging
import os
import time

log = logging.getLogger(__name__)

SESSION_EMAIL = "user"
SESSION_KEY = "user_xai_key"
_current_key: contextvars.ContextVar[tuple] = contextvars.ContextVar("byok_key", default=("", "", ""))

FREE_QUERIES = int(os.getenv("FREE_QUERIES", "3"))

_key_cache: dict[str, tuple[float, tuple]] = {}
_table_ready = False


def _fernet():
    import base64
    import hashlib
    from cryptography.fernet import Fernet

    raw = (os.getenv("BYOK_ENCRYPTION_KEY") or "").strip()
    if raw:
        return Fernet(raw.encode())
    secret = (
        os.getenv("FASTBI_SECRET")
        or os.getenv("FASTINSIGHTS_SECRET")
        or os.getenv("FASTOFFICE_SSO_SECRET")
        or os.getenv("APP_SECRET")
        or "fastbi-dev-only"
    )
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(("byok|" + secret).encode()).digest()))


def _db_conn():
    try:
        import db
        return db.connect()
    except Exception:  # noqa: BLE001
        return None


def _ensure_table(conn) -> None:
    global _table_ready
    if _table_ready:
        return
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_api_keys (
            email TEXT PRIMARY KEY,
            provider TEXT NOT NULL DEFAULT 'xai',
            encrypted_key TEXT NOT NULL,
            model TEXT,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    _table_ready = True


def _email(sess) -> str:
    return ((sess or {}).get(SESSION_EMAIL) or "").strip().lower()


def server_key_allowed(email: str) -> bool:
    """Admins / allowlisted emails may keep using the shared server key."""
    email = (email or "").strip().lower()
    if not email:
        return False
    allowed: set[str] = set()
    for raw in (
        os.getenv("FASTBI_ADMIN_EMAIL", ""),
        os.getenv("FASTINSIGHTS_ADMIN_EMAIL", ""),
        os.getenv("FASTBI_GRAPH_ADMIN_EMAILS", ""),
        os.getenv("GOOGLE_ALLOWED_EMAILS", ""),
    ):
        for part in raw.split(","):
            if part.strip():
                allowed.add(part.strip().lower())
    return email in allowed


def load_cred_for_email(email: str) -> tuple[str, str, str]:
    email = (email or "").strip().lower()
    if not email:
        return ("", "", "")
    hit = _key_cache.get(email)
    if hit and hit[0] > time.time():
        return hit[1]
    conn = _db_conn()
    cred = ("", "", "")
    if conn is not None:
        try:
            _ensure_table(conn)
            row = conn.execute(
                "SELECT encrypted_key, provider, model FROM user_api_keys WHERE email = ?",
                (email,),
            ).fetchone()
            if row:
                cred = (row[1] or "xai", _fernet().decrypt(row[0].encode()).decode(), row[2] or "")
            conn.commit()
        except Exception:  # noqa: BLE001
            log.exception("failed to load BYOK credential")
            cred = ("", "", "")
        finally:
            conn.close()
    _key_cache[email] = (time.time() + 60, cred)
    return cred


def _save_key_for_email(email: str, key: str, provider: str = "xai", model: str = "") -> bool:
    conn = _db_conn()
    if conn is None or not email:
        return False
    try:
        _ensure_table(conn)
        if key:
            conn.execute(
                """
                INSERT INTO user_api_keys (email, provider, encrypted_key, model, updated_at)
                VALUES (?, ?, ?, ?, datetime('now'))
                ON CONFLICT(email) DO UPDATE SET
                    encrypted_key = excluded.encrypted_key,
                    provider = excluded.provider,
                    model = excluded.model,
                    updated_at = datetime('now')
                """,
                (email, provider, _fernet().encrypt(key.encode()).decode(), model or None),
            )
        else:
            conn.execute("DELETE FROM user_api_keys WHERE email = ?", (email,))
        conn.commit()
    finally:
        conn.close()
    _key_cache[email] = (time.time() + 60, (provider, key, model) if key else ("", "", ""))
    return True


def get_user_cred(sess) -> tuple[str, str, str]:
    """(provider, key, model) for the signed-in user.

    A key left in an old session cookie is moved into the database and removed
    from the cookie on first use. Without a database the session is the store.
    """
    sess = sess if sess is not None else {}
    email = _email(sess)
    legacy = (sess.get(SESSION_KEY) or "").strip()
    conn = _db_conn()
    if conn is None:
        if not legacy:
            return ("", "", "")
        return (sess.get(SESSION_KEY + "_provider") or "xai", legacy, sess.get(SESSION_KEY + "_model") or "")
    conn.close()
    if legacy and email:
        try:
            _save_key_for_email(
                email, legacy,
                sess.get(SESSION_KEY + "_provider") or "xai",
                sess.get(SESSION_KEY + "_model") or "",
            )
            for k in (SESSION_KEY, SESSION_KEY + "_provider", SESSION_KEY + "_model"):
                sess.pop(k, None)
        except Exception:  # noqa: BLE001
            return ("xai", legacy, "")
    return load_cred_for_email(email)


def get_user_key(sess) -> str:
    return get_user_cred(sess)[1]


def set_user_key(sess, key: str, provider: str = "xai", model: str = "") -> None:
    key = (key or "").strip()
    email = _email(sess)
    if email:
        if _save_key_for_email(email, key, provider, model):
            for k in (SESSION_KEY, SESSION_KEY + "_provider", SESSION_KEY + "_model"):
                sess.pop(k, None)
            return
    if key:
        sess[SESSION_KEY] = key
        sess[SESSION_KEY + "_provider"] = provider
        sess[SESSION_KEY + "_model"] = model
    else:
        for k in (SESSION_KEY, SESSION_KEY + "_provider", SESSION_KEY + "_model"):
            sess.pop(k, None)


def verify_key_live(key: str) -> bool | None:
    """Check the key with xAI before saving. None when xAI could not be reached."""
    try:
        import httpx
        r = httpx.get(
            "https://api.x.ai/v1/api-key",
            headers={"Authorization": f"Bearer {key.strip()}"},
            timeout=10,
        )
    except Exception:  # noqa: BLE001
        return None
    if r.status_code == 200:
        try:
            d = r.json()
            return not (d.get("api_key_blocked") or d.get("api_key_disabled"))
        except Exception:  # noqa: BLE001
            return True
    if r.status_code in (400, 401, 403):
        return False
    return None


def valid_key_shape(key: str) -> bool:
    key = (key or "").strip()
    return key.startswith("xai-") and 20 <= len(key) <= 200 and " " not in key


def use_key(key: str, provider: str = "xai", model: str = ""):
    key = (key or "").strip()
    return _current_key.set(((provider or "xai") if key else "", key, model or ""))


def use_cred(cred: tuple):
    provider, key, model = (tuple(cred) + ("", "", ""))[:3]
    return use_key(key, provider, model)


def current_key() -> str:
    return _current_key.get()[1]


def current_cred() -> tuple[str, str, str]:
    return _current_key.get()


def key_required_message() -> str:
    return (
        "Add your own xAI API key to keep chatting on FastBI. "
        "It is checked with xAI, stored encrypted, and never shown again."
    )
