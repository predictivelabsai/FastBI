"""FastBI — an open-source BI tool built with FastHTML.

A server-side, HTMX-driven port of the core of Frappe Insights: a synthetic
data warehouse, saved queries that render Plotly charts, dashboards, a SQL lab,
and an AI text-to-SQL assistant — all read-only over synthetic data.

Run:
    python web_app.py            # http://localhost:5008

Set local admin credentials in ``.env`` or use Google sign-in.
"""
from __future__ import annotations

import os
import json
import secrets
import uuid
import logging

from dotenv import load_dotenv
load_dotenv()

from fasthtml.common import (
    fast_app, serve, Div, H1, P, A, Form, Input, Button, NotStr,
    RedirectResponse, Script, Style, Link, Title,
)
from starlette.responses import StreamingResponse, Response
from starlette.responses import JSONResponse

import db
from web.layout import page, LAYOUT_CSS
from web import views, ai, integrations
from web.landing import landing_page, integrations_landing_page
from web.seo import register_seo_routes
from web.developer import developer_page
from web import account_auth, google_auth, suite_auth
from web.api import api

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger("fastbi")

VALID_EMAIL = os.getenv("FASTBI_ADMIN_EMAIL", os.getenv("FASTINSIGHTS_ADMIN_EMAIL", "admin@fastbi.example"))
VALID_PASSWORD = os.getenv("FASTBI_ADMIN_PASSWORD", os.getenv("FASTINSIGHTS_ADMIN_PASSWORD", ""))
ENV_LABEL = os.getenv("FASTBI_ENV_LABEL", os.getenv("FASTINSIGHTS_ENV_LABEL", "FastBI"))
SECRET = os.getenv("FASTBI_SECRET", os.getenv("FASTINSIGHTS_SECRET", secrets.token_hex(32)))
PORT = int(os.getenv("FASTBI_PORT", os.getenv("FASTINSIGHTS_PORT", "5008")))

app, rt = fast_app(live=False, pico=False, secret_key=SECRET, hdrs=[Style(LAYOUT_CSS)])
app.mount("/api", api)


@rt("/swagger.json", methods=["GET"])
def swagger_schema():
    return JSONResponse(api.openapi())


@rt("/developers", methods=["GET"])
def developers():
    return developer_page()


@rt("/integrations", methods=["GET"])
def integrations_page(session):
    if not _user(session):
        return integrations_landing_page()
    flash = session.pop("integrations_flash", None) or {}
    return _guard(session, "integrations", lambda: integrations.integrations_workspace(
        flash.get("message", ""), flash.get("error", False)))


@rt("/integrations/import", methods=["POST"])
def integration_import(session, name: str = "", provider: str = "", url: str = ""):
    if not _user(session):
        return RedirectResponse("/login", status_code=303)
    try:
        if not name.strip():
            raise integrations.IntegrationError("Give the connection a name.")
        schema = integrations.pull_schema(url)
        db.save_integration(name, provider or "Other", url, schema)
        session["integrations_flash"] = {"message": f"Pulled and stored the schema for {name.strip()}."}
    except integrations.IntegrationError as exc:
        session["integrations_flash"] = {"message": str(exc), "error": True}
    return RedirectResponse("/integrations", status_code=303)


@rt("/migrations", methods=["GET"])
def migrations_page(session):
    if not _user(session):
        return RedirectResponse("/login", status_code=303)
    flash = session.pop("migrations_flash", None) or {}
    return _guard(session, "migrations", lambda: integrations.migrations_workspace(
        flash.get("message", ""), flash.get("error", False)))


@rt("/migrations/run", methods=["POST"])
async def migration_run(session, request):
    if not _user(session):
        return RedirectResponse("/login", status_code=303)
    try:
        dashboard_id = await integrations.generate_migration(await request.form())
    except integrations.IntegrationError as exc:
        session["migrations_flash"] = {"message": str(exc), "error": True}
        return RedirectResponse("/migrations", status_code=303)
    return RedirectResponse(f"/dashboards/{dashboard_id}", status_code=303)


account_auth.register_fasthtml_routes(rt, app_name="FastBI", session_key="user", success_path="/")


def _user(session):
    return session.get("user")


def _thread(session):
    if "thread" not in session:
        session["thread"] = uuid.uuid4().hex
    return session["thread"]


def _guard(session, active, builder):
    if not _user(session):
        return RedirectResponse("/login", status_code=303)
    content = builder() if callable(builder) else builder
    if not isinstance(content, tuple):
        content = (content,)
    return page(active, ENV_LABEL, _user(session), _thread(session), *content)


def _login_card(error="", email=""):
    return Title("FastBI — Sign in"), Link(rel="icon", type="image/svg+xml", href="/static/favicon.svg"), Style(LAYOUT_CSS), Div(
        Form(H1("FastBI"), P("Sign in to your BI workspace"),
             Input(name="email", type="email", placeholder="Email", value=email, required=True),
             Input(name="password", type="password", placeholder="Password", required=True),
             P(error, cls="error") if error else None,
             Button("Sign in", cls="btn primary", type="submit"),
             P("Configure FASTBI_ADMIN_PASSWORD for local password sign-in, or use Google from the public page.", cls="hint"),
             method="post", action="/login", cls="login-card"), cls="login-wrap")


@rt("/login")
def get(session):
    if _user(session):
        return RedirectResponse("/", status_code=303)
    return _login_card()


@rt("/login")
def post(session, email: str = "", password: str = ""):
    if VALID_PASSWORD and email.strip().lower() == VALID_EMAIL.lower() and password == VALID_PASSWORD:
        session["user"] = email.strip().lower()
        return RedirectResponse("/", status_code=303)
    return _login_card("Invalid email or password.", email)



@rt("/auth/google")
def google_start(session, request):
    if not google_auth.enabled():
        return RedirectResponse("/login?error=Google+sign-in+is+not+configured", status_code=303)
    state = google_auth.new_state()
    session["google_oauth_state"] = state
    return RedirectResponse(google_auth.authorize_url(request, state), status_code=303)

@rt("/auth/suite/callback")
def suite_callback(session, ticket: str = ""):
    identity = suite_auth.redeem(ticket, "insights")
    if not identity: return RedirectResponse("/login?error=FastOffice+session+is+invalid+or+expired", status_code=303)
    account_auth.accounts.link_google(identity["email"], identity["name"])
    session["user"], session["suite_identity"] = identity["email"], {k: identity[k] for k in ("sub","org_id","org_name","role")}
    return RedirectResponse("/", status_code=303)


@rt("/auth/google/callback")
def google_callback(session, request, code: str = "", state: str = "", error: str = ""):
    if error or not code or state != session.pop("google_oauth_state", None):
        return RedirectResponse("/login?error=Google+sign-in+failed", status_code=303)
    identity = google_auth.exchange(request, code)
    if not identity:
        return RedirectResponse("/login?error=Google+account+is+not+authorised", status_code=303)
    account_auth.accounts.link_google(identity["email"], identity["name"])
    session["user"] = identity["email"]
    return RedirectResponse("/", status_code=303)


@rt("/logout")
def get(session):
    session.pop("user", None)
    return RedirectResponse("/login", status_code=303)


@rt("/")
def get(session):
    if not _user(session):
        return landing_page()
    return _guard(session, "home", views.home)


@rt("/dashboards")
def get(session):
    return _guard(session, "dashboards", views.dashboards_list)


@rt("/dashboards/new")
def post(session, title: str = "", description: str = ""):
    if not _user(session):
        return RedirectResponse("/login", status_code=303)
    did = db.create_dashboard(title, description)
    return RedirectResponse(f"/dashboards/{did}?edit=1", status_code=303)


@rt("/dashboards/{did}")
def get(session, did: int, edit: int = 0):
    return _guard(session, "dashboards", lambda: views.dashboard_view(did, edit=bool(edit)))


def _dashfrag(session, did):
    if not _user(session):
        return Response("Unauthorized", status_code=401)
    return views.dashboard_grid(did, edit=True)


@rt("/dashboards/{did}/add")
def post(session, did: int, chart_id: int = 0, width: str = "half"):
    if not _user(session):
        return Response("Unauthorized", status_code=401)
    db.add_chart_to_dashboard(did, chart_id, width)
    return _dashfrag(session, did)


@rt("/dashboards/{did}/remove")
def post(session, did: int, chart_id: int = 0):
    if not _user(session):
        return Response("Unauthorized", status_code=401)
    db.remove_chart_from_dashboard(did, chart_id)
    return _dashfrag(session, did)


@rt("/dashboards/{did}/move")
def post(session, did: int, chart_id: int = 0, direction: str = "up"):
    if not _user(session):
        return Response("Unauthorized", status_code=401)
    db.move_chart(did, chart_id, direction)
    return _dashfrag(session, did)


@rt("/dashboards/{did}/width")
def post(session, did: int, chart_id: int = 0, width: str = "half"):
    if not _user(session):
        return Response("Unauthorized", status_code=401)
    db.set_chart_width(did, chart_id, width)
    return _dashfrag(session, did)


@rt("/build")
def get(session):
    return _guard(session, "builder", views.query_builder)


@rt("/build/run")
def post(session, dimension: str = "", measure: str = "", sort: str = "desc", limit: int = 20):
    if not _user(session):
        return Response("Unauthorized", status_code=401)
    try:
        sql = db.build_sql(dimension, measure, sort, limit)
    except db.SQLError as e:
        return Div(Div(NotStr(f"⚠ {e}"), cls="sql-result-err"), cls="card")
    return views.sql_result(sql, ai_note=f"Built from <b>{measure}</b> by <b>{dimension}</b>.")


@rt("/queries")
def get(session):
    return _guard(session, "queries", views.queries_list)


@rt("/queries/save")
def post(session, title: str = "", sql: str = "", chart_type: str = "bar", x_col: str = "", y_col: str = ""):
    if not _user(session):
        return RedirectResponse("/login", status_code=303)
    try:
        db.run_sql(sql)  # validate before saving
    except db.SQLError:
        return RedirectResponse("/sql", status_code=303)
    qid = db.save_query(title, sql, chart_type, x_col or None, y_col or None)
    return RedirectResponse(f"/queries/{qid}", status_code=303)


@rt("/queries/{qid}/delete")
def post(session, qid: int):
    if not _user(session):
        return RedirectResponse("/login", status_code=303)
    db.delete_query(qid)
    return RedirectResponse("/queries", status_code=303)


@rt("/queries/{qid}")
def get(session, qid: int):
    return _guard(session, "queries", lambda: views.query_view(qid))


@rt("/sql")
def get(session):
    return _guard(session, "sqllab", views.sql_lab)


@rt("/sql/run")
def post(session, sql: str = ""):
    if not _user(session):
        return Response("Unauthorized", status_code=401)
    return views.sql_result(sql)


@rt("/sql/ask")
def post(session, question: str = ""):
    if not _user(session):
        return Response("Unauthorized", status_code=401)
    question = (question or "").strip()
    if not question:
        return Div(P("Type a question first.", style="color:var(--text-mute);"), cls="card")
    try:
        sql, note = ai.text_to_sql(question)
    except Exception as e:  # noqa: BLE001
        return Div(Div(NotStr(f"⚠ {e}"), cls="sql-result-err"), cls="card")
    return views.sql_result(sql, ai_note=note)


@rt("/sources")
def get(session):
    return _guard(session, "sources", views.sources)


@rt("/ai")
def get(session):
    body = (views._title("AI Assistant", "Chat lives in the right rail. For SQL generation, use the SQL Lab."),
            Div(NotStr(
                "<div class='card'><h3>What you can ask</h3><ul style='line-height:1.8;'>"
                "<li>“What's our total revenue and margin?”</li>"
                "<li>“Which region and category perform best?”</li>"
                "<li>“How is revenue trending?”</li></ul>"
                "<p style='color:var(--text-mute)'>Slash-commands (no API key): "
                "<code>/metrics</code> <code>/tables</code> <code>/top region|category|customer</code></p>"
                "<p>Want a custom query? The <a href='/sql'>SQL Lab</a> turns a plain-English question "
                "into a read-only SQL query, runs it, and charts the result.</p></div>")))
    return _guard(session, "ai", body)


@rt("/guide")
def get(session):
    body = (views._title("User Guide", "How to drive FastBI"), Div(NotStr("""
<div class='card'><h3>Home</h3><p>Headline KPIs plus two flagship charts and links to your dashboards.</p></div>
<div class='card'><h3>Dashboards</h3><p>Curated boards of charts in a responsive grid.</p></div>
<div class='card'><h3>Queries & Charts</h3><p>Saved SQL queries, each bound to a chart type. Open one to see the
chart, the SQL, and the full result table.</p></div>
<div class='card'><h3>SQL Lab + Ask AI</h3><p>Run read-only SQL against the warehouse, or describe what you want and
let the AI generate the SQL, run it, and chart it. The schema is shown alongside.</p></div>
<div class='card'><h3>Data Source</h3><p>Browse the synthetic warehouse tables with row counts and samples.</p></div>
""")))
    return _guard(session, "guide", body)


@rt("/chat/new")
def get(session):
    session["thread"] = uuid.uuid4().hex
    return P("Ask about your metrics — or use /tables /metrics /help.", cls="chat-empty-hint")


@rt("/chat/stream")
async def post(session, message: str = "", thread_id: str = ""):
    if not _user(session):
        return Response("Unauthorized", status_code=401)
    message = (message or "").strip()
    if not message:
        return Response("No message", status_code=400)
    tid = thread_id or _thread(session)

    async def gen():
        with db.cursor() as conn:
            conn.execute("INSERT INTO chat_messages(thread_id,role,content,created) VALUES(?,?,?,datetime('now'))",
                         (tid, "user", message))
        full = []
        async for chunk in ai.stream_chat(message):
            if chunk.startswith("data: "):
                try:
                    tok = json.loads(chunk[6:]).get("token")
                    if tok:
                        full.append(tok)
                except Exception:
                    pass
            yield chunk
        with db.cursor() as conn:
            conn.execute("INSERT INTO chat_messages(thread_id,role,content,created) VALUES(?,?,?,datetime('now'))",
                         (tid, "assistant", "".join(full)))

    return StreamingResponse(gen(), media_type="text/event-stream")


def _ensure_db():
    if not db.db_exists():
        logger.info("No database found — seeding synthetic warehouse…")
        import seed
        seed.build()
    db.init_app_schema()


_ensure_db()


register_seo_routes(app)

if __name__ == "__main__":
    logger.info("FastBI on http://localhost:%s  (login %s)", PORT, VALID_EMAIL)
    serve(port=PORT, reload=os.getenv("FASTBI_RELOAD", os.getenv("FASTINSIGHTS_RELOAD", "0")) == "1")
