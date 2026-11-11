"""Rate limit and mybritain-style AI access gate for FastBI chat/SQL/Cypher/GraphRAG."""
from __future__ import annotations

import os
import time

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from web import byok, quota

FREE_QUERIES = int(os.getenv("FREE_QUERIES", "3"))
RATE_LIMIT_ANON = int(os.getenv("RATE_LIMIT_ANON", "20"))
RATE_LIMIT_AUTH = int(os.getenv("RATE_LIMIT_AUTH", "60"))
RATE_LIMIT_WINDOW = 60
_RATE_LIMIT_REQUESTS: dict[str, list[float]] = {}

LOGIN_MESSAGE = (
    f"You've used your {FREE_QUERIES} free questions. "
    "Sign in and add your own xAI API key to keep asking FastBI."
)


def client_ip(request: Request | None) -> str:
    if request is None:
        return ""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    client = request.client
    return client.host if client else ""


def _prune_rate_limit_cache(cutoff: float) -> None:
    if len(_RATE_LIMIT_REQUESTS) <= 10_000:
        return
    for key, stamps in list(_RATE_LIMIT_REQUESTS.items()):
        if not stamps or stamps[-1] <= cutoff:
            _RATE_LIMIT_REQUESTS.pop(key, None)
    if len(_RATE_LIMIT_REQUESTS) > 10_000:
        oldest = sorted(_RATE_LIMIT_REQUESTS, key=lambda key: _RATE_LIMIT_REQUESTS[key][-1])
        for key in oldest[: len(_RATE_LIMIT_REQUESTS) - 10_000]:
            _RATE_LIMIT_REQUESTS.pop(key, None)


def rate_limited(request: Request | None, authenticated: bool) -> bool:
    now = time.monotonic()
    cutoff = now - RATE_LIMIT_WINDOW
    ip = client_ip(request)
    recent = [stamp for stamp in _RATE_LIMIT_REQUESTS.get(ip, []) if stamp > cutoff]
    if recent:
        _RATE_LIMIT_REQUESTS[ip] = recent
    else:
        _RATE_LIMIT_REQUESTS.pop(ip, None)
    _prune_rate_limit_cache(cutoff)
    limit = RATE_LIMIT_AUTH if authenticated else RATE_LIMIT_ANON
    if len(recent) >= limit:
        return True
    _RATE_LIMIT_REQUESTS.setdefault(ip, []).append(now)
    _prune_rate_limit_cache(cutoff)
    return False


def evaluate(request: Request | None, session: dict, consume: bool = True) -> dict | None:
    """Return an error payload if the request must be blocked, else None.

    On success, a guest slot is reserved (when consume=True) and a signed-in
    user's BYOK credential is installed on the context var for the LLM callers.
    """
    sess = session if session is not None else {}
    email = (sess.get("user") or "").strip()
    if rate_limited(request, bool(email)):
        return {
            "error": "rate_limited",
            "message": "Too many questions too quickly. Please wait a moment and try again.",
            "status": 429,
        }

    if not email:
        if not consume:
            return None
        used = int(sess.get("free_q", 0) or 0)
        ip = client_ip(request)
        if used >= FREE_QUERIES or not quota.reserve_guest(ip):
            sess["free_q"] = max(used, FREE_QUERIES)
            return {
                "error": "login_required",
                "message": LOGIN_MESSAGE,
                "free_used": max(used, FREE_QUERIES),
                "free_limit": FREE_QUERIES,
                "status": 402,
            }
        sess["free_q"] = used + 1
        return None

    cred = byok.get_user_cred(sess)
    if cred[1]:
        byok.use_cred(cred)
        return None
    if byok.server_key_allowed(email):
        return None
    return {
        "error": "api_key_required",
        "message": byok.key_required_message(),
        "status": 402,
    }


def json_reject(payload: dict) -> JSONResponse:
    status = int(payload.pop("status", 400))
    return JSONResponse(payload, status_code=status)


def html_reject(payload: dict) -> Response:
    status = int(payload.get("status", 400))
    message = payload.get("message") or payload.get("error") or "Request blocked"
    return Response(message, status_code=status, media_type="text/plain")


def refund_if_guest(request: Request | None, session: dict, consumed: bool) -> None:
    if not consumed:
        return
    if (session or {}).get("user"):
        return
    quota.refund_guest(client_ip(request))
    used = int((session or {}).get("free_q", 0) or 0)
    if used:
        session["free_q"] = used - 1
