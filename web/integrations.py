"""Schema integrations and report-to-dashboard migration workflows."""
from __future__ import annotations

import ipaddress
import base64
import json
import os
import socket
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx
from fasthtml.common import *

import db
from web.layout import generation_progress

MAX_SCHEMA_BYTES = 2 * 1024 * 1024
MAX_REPORT_BYTES = 8 * 1024 * 1024
REPORT_SUFFIXES = {
    ".json", ".csv", ".txt", ".sql", ".yaml", ".yml", ".lkml",
    ".twb", ".twbx", ".pbix", ".pdf", ".png", ".jpg", ".jpeg", ".webp",
}
PROVIDERS = (
    "Microsoft Fabric / OneLake", "Google BigQuery", "Amazon Redshift",
    "Snowflake", "Databricks", "PostgreSQL", "MySQL", "SQL Server", "Other",
)
SOURCE_TOOLS = ("Power BI", "Tableau", "Looker", "Other")


class IntegrationError(ValueError):
    """A user-correctable integration or migration error."""


def _validate_public_url(url: str) -> str:
    parsed = urlsplit((url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise IntegrationError("Enter an HTTP(S) schema or catalogue URL.")
    if parsed.username or parsed.password:
        raise IntegrationError("Do not put credentials in the URL. Use a short-lived public catalogue export.")
    try:
        addresses = {row[4][0] for row in socket.getaddrinfo(parsed.hostname, parsed.port or 443)}
    except socket.gaierror as exc:
        raise IntegrationError("The schema host could not be resolved.") from exc
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise IntegrationError("Private, local, and reserved network addresses are not allowed.")
    return parsed.geturl()


def _schema_summary(raw: bytes, content_type: str) -> str:
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        raise IntegrationError("The schema endpoint returned an empty response.")
    if "json" not in content_type.lower() and not text.startswith(("{", "[")):
        return text[:60000]
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text[:60000]

    if isinstance(payload, dict) and payload.get("openapi"):
        schemas = payload.get("components", {}).get("schemas", {})
        lines = [f"OpenAPI {payload.get('openapi')} · {payload.get('info', {}).get('title', 'Schema catalogue')}"]
        for name, definition in list(schemas.items())[:120]:
            props = definition.get("properties", {}) if isinstance(definition, dict) else {}
            fields = ", ".join(
                f"{field} {details.get('type', 'object') if isinstance(details, dict) else 'object'}"
                for field, details in list(props.items())[:80]
            )
            lines.append(f"{name}({fields})")
        if len(lines) > 1:
            return "\n".join(lines)[:60000]

    tables = payload.get("tables") if isinstance(payload, dict) else None
    if isinstance(tables, list):
        lines = ["Warehouse catalogue:"]
        for table in tables[:200]:
            if isinstance(table, str):
                lines.append(f"- {table}")
                continue
            if not isinstance(table, dict):
                continue
            columns = table.get("columns", [])
            rendered = []
            for column in columns[:100] if isinstance(columns, list) else []:
                rendered.append(
                    column if isinstance(column, str)
                    else f"{column.get('name', 'field')} {column.get('type', '')}".strip()
                )
            lines.append(f"- {table.get('name', table.get('table', 'table'))}({', '.join(rendered)})")
        return "\n".join(lines)[:60000]
    return json.dumps(payload, indent=2, ensure_ascii=False)[:60000]


def pull_schema(url: str) -> str:
    """Fetch a bounded public schema document, validating every redirect."""
    current = _validate_public_url(url)
    headers = {"Accept": "application/schema+json, application/json, text/plain, application/sql;q=0.9"}
    with httpx.Client(timeout=httpx.Timeout(15.0), follow_redirects=False, headers=headers) as client:
        for _ in range(4):
            with client.stream("GET", current) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise IntegrationError("The schema endpoint returned an invalid redirect.")
                    current = _validate_public_url(urljoin(current, location))
                    continue
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise IntegrationError(f"The schema endpoint returned HTTP {response.status_code}.") from exc
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > MAX_SCHEMA_BYTES:
                        raise IntegrationError("The schema response is larger than 2 MB.")
                    chunks.append(chunk)
                return _schema_summary(b"".join(chunks), response.headers.get("content-type", ""))
    raise IntegrationError("The schema endpoint redirected too many times.")


def _options(values, selected=""):
    return NotStr("".join(
        f'<option value="{value}"{" selected" if value == selected else ""}>{value}</option>'
        for value in values
    ))


def _flash(message: str, error: bool = False):
    if not message:
        return None
    colour = "#b42318" if error else "var(--accent-hover)"
    background = "#fef3f2" if error else "var(--accent-light)"
    return Div(message, cls="callout", style=f"background:{background};border-left:4px solid {colour};color:{colour};padding:12px 16px;border-radius:8px;margin-bottom:16px;font-size:13px;")


def integrations_workspace(message="", error=False):
    items = db.integrations()
    form = Form(
        Div(Label("Connection name"), Input(name="name", placeholder="Finance warehouse", required=True, cls="askbox")),
        Div(Label("Platform"), Select(_options(PROVIDERS), name="provider", style="width:100%;padding:10px;border:1px solid var(--border);border-radius:8px;background:white;")),
        Div(Label("Schema or catalogue URL"), Input(name="url", type="url", placeholder="https://example.com/catalogue/schema.json", required=True, cls="askbox")),
        P("Use a public, short-lived metadata export. FastBI blocks credentials, private hosts, and responses over 2 MB.", cls="sub"),
        Button("Pull schema", type="submit", cls="btn primary"),
        method="post", action="/integrations/import", style="display:grid;gap:12px;",
    )
    cards = []
    for item in items:
        host = urlsplit(item["source_url"]).hostname or "catalogue"
        preview = "\n".join(item["schema_text"].splitlines()[:7])
        cards.append(Div(
            Div(H3(item["name"]), Span(item["provider"], cls="pill"), cls="card-header"),
            P(f"{host} · imported {item['created']}", cls="sub"),
            Pre(Code(preview), style="white-space:pre-wrap;max-height:180px;overflow:auto;background:#0f172a;color:#e2e8f0;padding:12px;border-radius:8px;font-size:12px;"),
            cls="card",
        ))
    return (
        Div(Div(H1("Integrations"), P("Pull governed schema metadata from a warehouse or database catalogue URL.", cls="sub")),
            Div(A("Migration workspace →", href="/migrations", cls="btn")), cls="page-title"),
        _flash(message, error),
        Div(Div(H3("Connect a catalogue"), cls="card-header"), form, cls="card"),
        Div(*cards, cls="grid-2") if cards else Div(P("No external schemas yet. Connect one above, then use it to ground a migration.", cls="sub"), cls="card"),
    )


def _rank_charts(text: str) -> list[dict]:
    words = set(text.lower().replace("_", " ").replace("-", " ").split())
    rows = db.rows("""SELECT ch.id, ch.title, q.description FROM charts ch
                      LEFT JOIN queries q ON q.id=ch.query_id ORDER BY ch.id""")
    scored = []
    for row in rows:
        haystack = f"{row['title']} {row.get('description') or ''}".lower()
        score = sum(1 for word in words if len(word) > 3 and word in haystack)
        scored.append((score, row))
    scored.sort(key=lambda pair: (-pair[0], pair[1]["id"]))
    return [row for _score, row in scored[:4]]


def _visual_blueprint(content: bytes, suffix: str, instructions: str, schema: str) -> str:
    """Ask the configured multimodal model to interpret a report screenshot."""
    key = os.getenv("XAI_API_KEY", "")
    if not key or suffix not in {".png", ".jpg", ".jpeg"}:
        return ""
    media_type = "image/png" if suffix == ".png" else "image/jpeg"
    image_url = f"data:{media_type};base64,{base64.b64encode(content).decode('ascii')}"
    prompt = (
        "Read this existing BI report screenshot. Return a concise dashboard blueprint: "
        "business questions, visible KPIs, chart types, dimensions, measures, filters, and layout. "
        "Use only fields supported by the schema context and flag uncertain interpretations.\n\n"
        f"Migration instructions:\n{instructions or 'Preserve the report intent and hierarchy.'}\n\n"
        f"Schema context:\n{schema[:12000] or db.schema_prompt()}"
    )
    try:
        response = httpx.post(
            "https://api.x.ai/v1/responses",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": os.getenv("XAI_VISION_MODEL", "grok-4.5"),
                "store": False,
                "input": [{
                    "role": "user",
                    "content": [
                        {"type": "input_image", "image_url": image_url, "detail": "high"},
                        {"type": "input_text", "text": prompt},
                    ],
                }],
            },
            timeout=90,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("output_text"):
            return str(payload["output_text"])[:30000]
        parts = []
        for item in payload.get("output", []):
            for part in item.get("content", []):
                if isinstance(part, dict) and part.get("text"):
                    parts.append(str(part["text"]))
        return "\n".join(parts)[:30000]
    except (httpx.HTTPError, ValueError, KeyError):
        # The deterministic schema-aware migration remains available if the
        # optional model is unavailable, rate-limited, or rejects the image.
        return ""


async def generate_migration(form) -> int:
    upload = form.get("report")
    filename = Path(getattr(upload, "filename", "") or "").name
    suffix = Path(filename).suffix.lower()
    if not filename or suffix not in REPORT_SUFFIXES:
        raise IntegrationError("Upload a Power BI, Tableau, Looker, JSON, text, PDF, or screenshot artefact.")
    content = await upload.read(MAX_REPORT_BYTES + 1)
    if not content:
        raise IntegrationError("The uploaded report artefact is empty.")
    if len(content) > MAX_REPORT_BYTES:
        raise IntegrationError("The report artefact is larger than 8 MB.")
    source_tool = str(form.get("source_tool") or "Other")
    instructions = str(form.get("instructions") or "").strip()
    integration_raw = str(form.get("integration_id") or "").strip()
    integration_id = int(integration_raw) if integration_raw.isdigit() else None
    if integration_id and not db.one("SELECT id FROM data_integrations WHERE id=?", (integration_id,)):
        raise IntegrationError("Choose an existing schema integration.")

    if suffix in {".json", ".csv", ".txt", ".sql", ".yaml", ".yml", ".lkml", ".twb"}:
        report_text = content.decode("utf-8", errors="replace")[:60000]
    else:
        report_text = f"{source_tool} visual report artefact {filename}"
    grounding = ""
    if integration_id:
        grounding = db.one("SELECT schema_text FROM data_integrations WHERE id=?", (integration_id,))["schema_text"][:12000]
    blueprint = _visual_blueprint(content, suffix, instructions, grounding)
    candidates = _rank_charts(f"{filename} {source_tool} {instructions} {report_text} {grounding} {blueprint}")
    if not candidates:
        raise IntegrationError("No governed charts are available for dashboard generation.")

    title = f"Migrated {source_tool}: {Path(filename).stem[:60]}"
    description = "Generated from the uploaded report artefact"
    if integration_id:
        description += " and connected schema"
    description += ". Review measures and filters before production use."
    dashboard_id = db.create_dashboard(title, description)
    for index, chart in enumerate(candidates):
        db.add_chart_to_dashboard(dashboard_id, chart["id"], "full" if index == 0 else "half")
    interpretation = " with multimodal report interpretation" if blueprint else " with deterministic schema-aware mapping"
    summary = f"Created an editable {len(candidates)}-chart dashboard from {filename}{interpretation}."
    db.save_migration(source_tool, filename, integration_id, instructions, summary, dashboard_id)
    return dashboard_id


def migrations_workspace(message="", error=False):
    integrations = db.integrations()
    history = db.migrations()
    integration_options = '<option value="">Use local warehouse schema</option>' + "".join(
        f'<option value="{item["id"]}">{item["name"]} · {item["provider"]}</option>' for item in integrations
    )
    form = Form(
        Div(Label("Source BI tool"), Select(_options(SOURCE_TOOLS), name="source_tool", style="width:100%;padding:10px;border:1px solid var(--border);border-radius:8px;background:white;")),
        Div(Label("Grounding schema"), Select(NotStr(integration_options), name="integration_id", style="width:100%;padding:10px;border:1px solid var(--border);border-radius:8px;background:white;")),
        Div(Label("Existing report or screenshot"), Input(type="file", name="report", required=True,
            accept=".pbix,.twb,.twbx,.lkml,.json,.csv,.txt,.sql,.yaml,.yml,.pdf,.png,.jpg,.jpeg,.webp")),
        Div(Label("Migration instructions"), Textarea(name="instructions", placeholder="Preserve the executive KPI row, monthly trend, regional split, and customer drill-down.", cls="sqlbox", style="min-height:100px;")),
        P("FastBI reads available report text, filenames, visual artefacts, migration instructions, and the selected schema to generate an editable governed dashboard.", cls="sub"),
        Button("Generate dashboard", type="submit", cls="btn primary"),
        method="post", action="/migrations/run", enctype="multipart/form-data", style="display:grid;gap:12px;",
        onsubmit="document.getElementById('migration-generation-progress').classList.add('htmx-request')",
    )
    rows = [Tr(Td(item["source_tool"]), Td(item["file_name"]), Td(item.get("integration_name") or "Local warehouse"),
               Td(A("Open dashboard →", href=f"/dashboards/{item['dashboard_id']}"))) for item in history]
    return (
        Div(Div(H1("Migrations"), P("Turn Power BI, Tableau, Looker, and visual report artefacts into editable FastBI dashboards.", cls="sub")),
            Div(A("Manage integrations →", href="/integrations", cls="btn")), cls="page-title"),
        _flash(message, error),
        Div(Div(H3("Generate a migrated dashboard"), cls="card-header"), form,
            generation_progress("migration-generation-progress", "Reading the report and generating dashboard structure…",
                                "FastBI is matching visuals, measures, and schema."), cls="card"),
        Div(Div(H3("Migration history"), cls="card-header"),
            Table(Thead(Tr(Th("Source"), Th("Artefact"), Th("Schema"), Th("Result"))), Tbody(*rows), cls="tbl") if rows else P("No reports migrated yet.", cls="sub"), cls="card"),
    )
