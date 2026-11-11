"""Persistent guest allowance, modelled on mybritain-chat / AlpaTrade.

Guests get FREE_QUERIES questions on the server key. The session cookie counts
them, but clearing cookies must not reset the allowance, so every guest question
also reserves a slot in SQLite keyed by a salted hash of the client IP. The
reservation is a single atomic UPDATE ... WHERE used < limit. A failed model
call refunds its slot. If the database is unavailable the counter falls back to
process memory (still survives cookie clearing until restart).
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
import time

log = logging.getLogger(__name__)

FREE_QUERIES = int(os.getenv("FREE_QUERIES", "3"))
GUEST_WINDOW_DAYS = int(os.getenv("GUEST_WINDOW_DAYS", "30"))
GUEST_IP_LIMIT = int(os.getenv("GUEST_IP_LIMIT", str(FREE_QUERIES)))

_lock = threading.Lock()
_mem: dict[str, list[float]] = {}
_table_ready = False


def _salt() -> str:
    return (
        os.getenv("FASTBI_SECRET")
        or os.getenv("FASTINSIGHTS_SECRET")
        or os.getenv("FASTOFFICE_SSO_SECRET")
        or os.getenv("APP_SECRET")
        or "fastbi-dev-only"
    )


def ip_hash(ip: str, scope: str = "web") -> str:
    """Hash so raw IPs are never stored."""
    return hashlib.sha256(f"{_salt()}|{scope}|{(ip or '?').strip()}".encode()).hexdigest()[:40]


def _ensure_table(conn) -> None:
    global _table_ready
    if _table_ready:
        return
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS guest_query_allowances (
            ip_hash TEXT PRIMARY KEY,
            used INTEGER NOT NULL DEFAULT 0,
            window_start TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    _table_ready = True


def _db_conn():
    try:
        import db
        return db.connect()
    except Exception:  # noqa: BLE001
        return None


def _mem_stamps(h: str) -> list[float]:
    cutoff = time.time() - GUEST_WINDOW_DAYS * 86400
    stamps = [t for t in _mem.get(h, []) if t > cutoff]
    _mem[h] = stamps
    if len(_mem) > 50_000:
        _mem.clear()
    return stamps


def guest_used(ip: str) -> int:
    h = ip_hash(ip)
    conn = _db_conn()
    if conn is not None:
        try:
            _ensure_table(conn)
            row = conn.execute(
                """
                SELECT CASE WHEN window_start < datetime('now', ?)
                            THEN 0 ELSE used END
                FROM guest_query_allowances WHERE ip_hash = ?
                """,
                (f"-{GUEST_WINDOW_DAYS} days", h),
            ).fetchone()
            conn.commit()
            return int(row[0]) if row else 0
        except Exception:  # noqa: BLE001
            log.exception("guest quota read failed; using memory")
        finally:
            conn.close()
    with _lock:
        return len(_mem_stamps(h))


def guest_remaining(ip: str) -> int:
    return max(GUEST_IP_LIMIT - guest_used(ip), 0)


def reserve_guest(ip: str) -> bool:
    """Atomically take one guest slot for this IP. False when the allowance is spent."""
    h = ip_hash(ip)
    conn = _db_conn()
    if conn is not None:
        try:
            _ensure_table(conn)
            conn.execute(
                "INSERT OR IGNORE INTO guest_query_allowances (ip_hash) VALUES (?)",
                (h,),
            )
            conn.execute(
                """
                UPDATE guest_query_allowances
                SET used = 0, window_start = datetime('now')
                WHERE ip_hash = ? AND window_start < datetime('now', ?)
                """,
                (h, f"-{GUEST_WINDOW_DAYS} days"),
            )
            row = conn.execute(
                """
                UPDATE guest_query_allowances
                SET used = used + 1, updated_at = datetime('now')
                WHERE ip_hash = ? AND used < ?
                RETURNING used
                """,
                (h, GUEST_IP_LIMIT),
            ).fetchone()
            conn.commit()
            return row is not None
        except Exception:  # noqa: BLE001
            log.exception("guest quota reserve failed; using memory")
        finally:
            conn.close()
    with _lock:
        stamps = _mem_stamps(h)
        if len(stamps) >= GUEST_IP_LIMIT:
            return False
        stamps.append(time.time())
        return True


def refund_guest(ip: str) -> None:
    """Give back a slot when the model call failed."""
    h = ip_hash(ip)
    conn = _db_conn()
    if conn is not None:
        try:
            _ensure_table(conn)
            conn.execute(
                """
                UPDATE guest_query_allowances
                SET used = MAX(used - 1, 0), updated_at = datetime('now')
                WHERE ip_hash = ?
                """,
                (h,),
            )
            conn.commit()
            return
        except Exception:  # noqa: BLE001
            log.exception("guest quota refund failed")
        finally:
            conn.close()
    with _lock:
        stamps = _mem_stamps(h)
        if stamps:
            stamps.pop()
