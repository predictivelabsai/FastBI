"""FastBI AI — grounded chat, slash-commands, and text-to-SQL.

Right-rail chat answers metric questions, grounded with a live data summary.
The SQL Lab's "Ask the data" box calls ``text_to_sql()`` which asks the LLM for
a single read-only SELECT against the warehouse schema; the query is then run
through ``db.run_sql`` (which enforces read-only) and rendered as a chart+table.
"""
from __future__ import annotations

import json
import os
import re

import db

PROVIDER = os.getenv("MODEL_PROVIDER", "xai")
MODEL = os.getenv("MODEL_NAME", "grok-4.5")


def _money(v):
    v = v or 0
    return f"£{v/1_000_000:.2f}M" if v >= 1_000_000 else (f"£{v/1_000:.0f}k" if v >= 1_000 else f"£{v:,.0f}")


def snapshot() -> str:
    total = db.scalar("SELECT SUM(revenue) FROM wh_orders") or 0
    margin = db.scalar("SELECT SUM(revenue-cost) FROM wh_orders") or 0
    orders = db.scalar("SELECT COUNT(*) FROM wh_orders") or 0
    by_region = db.rows("""SELECT r.region, ROUND(SUM(o.revenue)) v FROM wh_orders o
        JOIN wh_customers c ON c.customer_id=o.customer_id JOIN wh_regions r ON r.region_id=c.region_id
        GROUP BY r.region ORDER BY v DESC""")
    by_cat = db.rows("""SELECT p.category, ROUND(SUM(o.revenue)) v FROM wh_orders o
        JOIN wh_products p ON p.product_id=o.product_id GROUP BY p.category ORDER BY v DESC""")
    return "\n".join([
        "CURRENT DATA SUMMARY (synthetic retail warehouse):",
        f"- Total revenue {_money(total)} across {orders:,} orders; gross margin {_money(margin)}.",
        "Revenue by region: " + ", ".join(f"{r['region']} {_money(r['v'])}" for r in by_region),
        "Revenue by category: " + ", ".join(f"{r['category']} {_money(r['v'])}" for r in by_cat),
        "Date range: 2024-01 to 2026-05.",
    ])


SYSTEM_PROMPT = """You are the FastBI assistant, embedded in an open-source BI tool.
Help analysts understand a synthetic retail sales warehouse. Be concise; use Markdown
(short tables, bold figures). All data is synthetic — never claim it's real. Base answers on
the DATA SUMMARY below; for anything not in it, suggest using the SQL Lab's "Ask the data" box."""

SQL_SYSTEM = """You write SQLite SQL for a retail data warehouse. Output ONLY one read-only
SELECT statement (no prose, no markdown fences, no semicolon). Use only these tables/columns:

{schema}

Rules: SELECT or WITH only; never modify data; alias aggregates with readable names; for
time series group by substr(order_date,1,7) AS month; keep results to a sensible size."""


def _table(headers, rows_):
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for r in rows_:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def route_mode(question: str, requested: str = "auto") -> str:
    """Choose the conversational execution path; explicit modes always win."""
    requested = (requested or "auto").strip().lower()
    if requested in {"sql", "graph"}:
        return requested
    text = (question or "").lower()
    graph_terms = (
        "ontology", "relationship", "related", "connected", "connection", "path between",
        "depends on", "class", "node", "graph", "upstream", "downstream", "measures",
    )
    if any(term in text for term in graph_terms):
        try:
            import graph_db
            if graph_db.configured():
                return "graph"
        except Exception:
            pass
    sql_terms = (
        "revenue", "margin", "orders", "customers", "monthly", "trend", "average",
        "total", "top", "sales", "channel", "region", "category", "product",
    )
    return "sql" if any(term in text for term in sql_terms) else "assistant"


def _sql_markdown(question: str) -> str:
    sql, _note = text_to_sql(question)
    cols, rows_ = db.run_sql(sql, limit=50)
    lines = ["**SQL answer** — generated and executed against the read-only warehouse.", ""]
    if cols and rows_:
        lines.append(_table(cols, [[str(value) for value in row] for row in rows_[:12]]))
    else:
        lines.append("No matching rows were found.")
    lines.extend(["", "```sql", sql, "```", "Open **SQL Lab + Ask AI** for the chart and full result."])
    return "\n".join(lines)


def _graph_markdown(question: str) -> str:
    import graph_db
    from web import graph_ai

    cypher, params, explanation = graph_ai.text_to_cypher(question)
    result = graph_db.run_cypher(cypher, params)
    return graph_ai.markdown_answer(question, result, explanation)


def handle_command(text):
    if not text.startswith("/"):
        return None
    parts = text[1:].split()
    cmd = parts[0].lower() if parts else ""
    arg = " ".join(parts[1:])
    if cmd in ("help", "?"):
        return ("**FastBI shortcuts**\n\n"
                "- `/metrics` — headline numbers\n- `/tables` — warehouse schema\n"
                "- `/top [region|category|customer]` — top breakdown\n\n"
                "For SQL generation use the **SQL Lab → Ask the data** box.")
    if cmd == "metrics":
        total = db.scalar("SELECT SUM(revenue) FROM wh_orders") or 0
        margin = db.scalar("SELECT SUM(revenue-cost) FROM wh_orders") or 0
        orders = db.scalar("SELECT COUNT(*) FROM wh_orders") or 0
        return _table(["Metric", "Value"], [
            ["Total revenue", _money(total)], ["Gross margin", _money(margin)],
            ["Orders", f"{orders:,}"], ["Avg order value", _money(total/orders if orders else 0)]])
    if cmd == "tables":
        return "**Warehouse schema**\n\n```\n" + db.schema_prompt() + "\n```"
    if cmd == "top":
        dim = (arg or "region").lower()
        if dim.startswith("cat"):
            r = db.rows("SELECT p.category k, ROUND(SUM(o.revenue)) v FROM wh_orders o JOIN wh_products p ON p.product_id=o.product_id GROUP BY k ORDER BY v DESC")
        elif dim.startswith("cust"):
            r = db.rows("SELECT c.customer k, ROUND(SUM(o.revenue)) v FROM wh_orders o JOIN wh_customers c ON c.customer_id=o.customer_id GROUP BY k ORDER BY v DESC LIMIT 10")
        else:
            r = db.rows("SELECT rg.region k, ROUND(SUM(o.revenue)) v FROM wh_orders o JOIN wh_customers c ON c.customer_id=o.customer_id JOIN wh_regions rg ON rg.region_id=c.region_id GROUP BY k ORDER BY v DESC")
        return _table(["Name", "Revenue"], [[x["k"], _money(x["v"])] for x in r])
    return f"Unknown command `/{cmd}`. Try `/help`."


# --- streaming chat ---------------------------------------------------------

async def stream_chat(message, query_mode: str = "auto"):
    cmd = handle_command(message)
    if cmd is not None:
        yield f"data: {json.dumps({'token': cmd})}\n\n"
        yield f"data: {json.dumps({'done': True})}\n\n"
        return
    mode = route_mode(message, query_mode)
    if mode in {"sql", "graph"}:
        try:
            answer = _sql_markdown(message) if mode == "sql" else _graph_markdown(message)
            yield f"data: {json.dumps({'token': answer, 'mode': mode})}\n\n"
        except Exception as exc:  # noqa: BLE001
            yield f"data: {json.dumps({'error': f'{mode.title()} query failed: {exc}'})}\n\n"
        yield f"data: {json.dumps({'done': True, 'mode': mode})}\n\n"
        return
    system = SYSTEM_PROMPT + "\n\n" + snapshot()
    try:
        async for tok in _provider_stream(system, message):
            yield f"data: {json.dumps({'token': tok})}\n\n"
    except Exception as e:  # noqa: BLE001
        yield f"data: {json.dumps({'error': str(e)})}\n\n"
    yield f"data: {json.dumps({'done': True})}\n\n"


# --- text-to-SQL (non-streaming) -------------------------------------------

def text_to_sql(question: str) -> tuple[str, str]:
    """Return (sql, note). Raises RuntimeError with a friendly message on failure."""
    key_env = {"xai": "XAI_API_KEY", "openai": "OPENAI_API_KEY",
               "anthropic": "ANTHROPIC_API_KEY", "google": "GOOGLE_API_KEY"}.get(PROVIDER)
    if not key_env or not os.getenv(key_env):
        raise RuntimeError(f"No {key_env or 'LLM'} configured — set it in .env to use AI SQL generation.")
    system = SQL_SYSTEM.format(schema=db.schema_prompt())
    raw = _complete(system, question)
    sql = _extract_sql(raw)
    if not sql:
        raise RuntimeError("The model did not return a SQL query. Try rephrasing.")
    return sql, f"Generated from: <em>{question}</em>"


def _extract_sql(text: str) -> str:
    text = text.strip()
    m = re.search(r"```(?:sql)?\s*(.+?)```", text, re.IGNORECASE | re.DOTALL)
    if m:
        text = m.group(1).strip()
    m = re.search(r"((?:select|with)\b.+)", text, re.IGNORECASE | re.DOTALL)
    return (m.group(1).strip().rstrip(";") if m else "")


def _complete(system: str, user: str) -> str:
    import httpx
    provider, model = PROVIDER, MODEL
    if provider in ("xai", "openai"):
        url = "https://api.x.ai/v1/chat/completions" if provider == "xai" else "https://api.openai.com/v1/chat/completions"
        key = os.getenv("XAI_API_KEY" if provider == "xai" else "OPENAI_API_KEY", "")
        r = httpx.post(url, headers={"Authorization": f"Bearer {key}"},
                       json={"model": model, "messages": [{"role": "system", "content": system},
                                                          {"role": "user", "content": user}]}, timeout=60)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    if provider == "anthropic":
        key = os.getenv("ANTHROPIC_API_KEY", "")
        r = httpx.post("https://api.anthropic.com/v1/messages",
                       headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                       json={"model": model, "max_tokens": 600, "system": system,
                             "messages": [{"role": "user", "content": user}]}, timeout=60)
        r.raise_for_status()
        return r.json()["content"][0]["text"]
    if provider == "google":
        key = os.getenv("GOOGLE_API_KEY", "")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
        r = httpx.post(url, json={"system_instruction": {"parts": [{"text": system}]},
                                  "contents": [{"role": "user", "parts": [{"text": user}]}]}, timeout=60)
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    raise RuntimeError(f"Unsupported provider '{provider}'.")


async def _provider_stream(system, message):
    import httpx
    provider, model = PROVIDER, MODEL
    if provider in ("xai", "openai"):
        url = "https://api.x.ai/v1/chat/completions" if provider == "xai" else "https://api.openai.com/v1/chat/completions"
        key = os.getenv("XAI_API_KEY" if provider == "xai" else "OPENAI_API_KEY", "")
        if not key:
            yield _no_key(provider); return
        async with httpx.AsyncClient(timeout=90) as client:
            async with client.stream("POST", url, headers={"Authorization": f"Bearer {key}"},
                                     json={"model": model, "stream": True,
                                           "messages": [{"role": "system", "content": system},
                                                        {"role": "user", "content": message}]}) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data: ") and line != "data: [DONE]":
                        try:
                            tok = json.loads(line[6:])["choices"][0]["delta"].get("content", "")
                            if tok: yield tok
                        except (json.JSONDecodeError, KeyError, IndexError):
                            pass
    elif provider == "anthropic":
        key = os.getenv("ANTHROPIC_API_KEY", "")
        if not key:
            yield _no_key(provider); return
        async with httpx.AsyncClient(timeout=90) as client:
            async with client.stream("POST", "https://api.anthropic.com/v1/messages",
                                     headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                                     json={"model": model, "max_tokens": 1500, "stream": True, "system": system,
                                           "messages": [{"role": "user", "content": message}]}) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        try:
                            ev = json.loads(line[6:])
                            if ev.get("type") == "content_block_delta":
                                tok = ev.get("delta", {}).get("text", "")
                                if tok: yield tok
                        except json.JSONDecodeError:
                            pass
    elif provider == "google":
        key = os.getenv("GOOGLE_API_KEY", "")
        if not key:
            yield _no_key(provider); return
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?alt=sse&key={key}"
        async with httpx.AsyncClient(timeout=90) as client:
            async with client.stream("POST", url, json={"system_instruction": {"parts": [{"text": system}]},
                                                        "contents": [{"role": "user", "parts": [{"text": message}]}]}) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        try:
                            tok = json.loads(line[6:])["candidates"][0]["content"]["parts"][0].get("text", "")
                            if tok: yield tok
                        except (json.JSONDecodeError, KeyError, IndexError):
                            pass
    else:
        yield (f"No LLM provider configured (MODEL_PROVIDER='{provider}'). Slash-commands like /metrics work without a key.")


def _no_key(provider):
    env = {"xai": "XAI_API_KEY", "openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "google": "GOOGLE_API_KEY"}[provider]
    return (f"⚠ No **{env}** set, so free-form chat is disabled. Add it to `.env` and restart. "
            "Slash-commands (`/metrics`, `/tables`, `/top` …) work without any key.")
