"""Small, shared Server-Sent Events contract for FastBI generations."""
from __future__ import annotations

import json
from typing import Any


def event(name: str, data: dict[str, Any] | None = None) -> str:
    """Encode one named SSE event with a JSON payload."""
    return f"event: {name}\ndata: {json.dumps(data or {}, ensure_ascii=False, default=str)}\n\n"


def parse(chunk: str) -> tuple[str, dict[str, Any]]:
    """Parse an event emitted by :func:`event` for server-side persistence/tests."""
    name = "message"
    payload_lines: list[str] = []
    for line in chunk.splitlines():
        if line.startswith("event:"):
            name = line[6:].strip()
        elif line.startswith("data:"):
            payload_lines.append(line[5:].lstrip())
    try:
        payload = json.loads("\n".join(payload_lines) or "{}")
    except json.JSONDecodeError:
        payload = {}
    return name, payload if isinstance(payload, dict) else {}
