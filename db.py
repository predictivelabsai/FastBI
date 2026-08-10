"""FastBI data layer.

One SQLite file holds two things:
  * a synthetic **data warehouse** (a retail sales star schema, tables prefixed
    ``wh_``) — the data analysts explore;
  * the **app metadata** (saved queries, charts, dashboards) — modelled on
    Frappe Insights' Query / Chart / Dashboard doctypes.

Analyst SQL runs through ``run_sql()``, which enforces a single read-only
SELECT so neither the AI text-to-SQL nor the SQL lab can mutate anything.
"""
from __future__ import annotations

import os
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = os.getenv("FASTBI_DB") or os.getenv("FASTINSIGHTS_DB") or str(Path(__file__).parent / "fastbi.sqlite")

CHART_TYPES = ["bar", "line", "pie", "row", "number"]


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


@contextmanager
def cursor():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def db_exists() -> bool:
    p = Path(DB_PATH)
    return p.exists() and p.stat().st_size > 0


def rows(sql, params=()):
    with cursor() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def one(sql, params=()):
    with cursor() as conn:
        r = conn.execute(sql, params).fetchone()
        return dict(r) if r else None


def scalar(sql, params=()):
    with cursor() as conn:
        r = conn.execute(sql, params).fetchone()
        return r[0] if r else None


# --- safe read-only SQL runner ---------------------------------------------

class SQLError(Exception):
    pass


_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|attach|detach|pragma|vacuum|reindex)\b",
    re.IGNORECASE)


def run_sql(sql: str, limit: int = 500):
    """Execute a single read-only SELECT and return (columns, rows)."""
    s = (sql or "").strip().rstrip(";")
    if not s:
        raise SQLError("Empty query.")
    if ";" in s:
        raise SQLError("Only a single statement is allowed.")
    if not re.match(r"^\s*(select|with)\b", s, re.IGNORECASE):
        raise SQLError("Only SELECT/WITH queries are allowed.")
    if _FORBIDDEN.search(s):
        raise SQLError("Only read-only queries are allowed.")
    if re.search(r"\blimit\b", s, re.IGNORECASE) is None:
        s = f"{s}\nLIMIT {limit}"
    with cursor() as conn:
        try:
            cur = conn.execute(s)
        except sqlite3.Error as e:
            raise SQLError(str(e))
        cols = [d[0] for d in cur.description] if cur.description else []
        data = [list(r) for r in cur.fetchall()]
    return cols, data


def warehouse_schema() -> list[dict]:
    """Return [{table, columns:[(name,type)]}] for the wh_ tables."""
    tables = rows("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'wh_%' ORDER BY name")
    out = []
    for t in tables:
        cols = rows(f"PRAGMA table_info({t['name']})")
        out.append({"table": t["name"], "columns": [(c["name"], c["type"]) for c in cols]})
    return out


def schema_prompt() -> str:
    lines = ["Warehouse tables (SQLite):"]
    for t in warehouse_schema():
        lines.append(f"  {t['table']}(" + ", ".join(f"{n} {ty}" for n, ty in t["columns"]) + ")")
    return "\n".join(lines)


# --- app metadata schema ----------------------------------------------------

APP_SCHEMA = """
CREATE TABLE IF NOT EXISTS queries (
    id            INTEGER PRIMARY KEY,
    title         TEXT NOT NULL,
    description   TEXT,
    sql           TEXT NOT NULL,
    folder        TEXT
);
CREATE TABLE IF NOT EXISTS charts (
    id            INTEGER PRIMARY KEY,
    title         TEXT NOT NULL,
    query_id      INTEGER REFERENCES queries(id),
    chart_type    TEXT NOT NULL DEFAULT 'bar',
    x_col         TEXT,
    y_col         TEXT
);
CREATE TABLE IF NOT EXISTS dashboards (
    id            INTEGER PRIMARY KEY,
    title         TEXT NOT NULL,
    description   TEXT
);
CREATE TABLE IF NOT EXISTS dashboard_charts (
    dashboard_id  INTEGER REFERENCES dashboards(id),
    chart_id      INTEGER REFERENCES charts(id),
    position      INTEGER,
    width         TEXT DEFAULT 'half'   -- 'half' | 'full'
);
CREATE TABLE IF NOT EXISTS chat_messages (
    id            INTEGER PRIMARY KEY,
    thread_id     TEXT NOT NULL,
    role          TEXT NOT NULL,
    content       TEXT NOT NULL,
    created       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS data_integrations (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    provider      TEXT NOT NULL,
    source_url    TEXT NOT NULL,
    schema_text   TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'ready',
    created       TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS migration_reports (
    id            INTEGER PRIMARY KEY,
    source_tool   TEXT NOT NULL,
    file_name     TEXT NOT NULL,
    integration_id INTEGER REFERENCES data_integrations(id),
    instructions  TEXT,
    summary       TEXT NOT NULL,
    dashboard_id  INTEGER REFERENCES dashboards(id),
    status        TEXT NOT NULL DEFAULT 'generated',
    created       TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def init_app_schema():
    with cursor() as conn:
        conn.executescript(APP_SCHEMA)


# --- convenience reads ------------------------------------------------------

def query(qid: int):
    return one("SELECT * FROM queries WHERE id=?", (qid,))


def chart(cid: int):
    return one("""SELECT ch.*, q.sql, q.title query_title
                  FROM charts ch LEFT JOIN queries q ON q.id=ch.query_id WHERE ch.id=?""", (cid,))


def dashboard_charts(did: int):
    return rows("""SELECT ch.*, q.sql, dc.width, dc.position
                   FROM dashboard_charts dc
                   JOIN charts ch ON ch.id=dc.chart_id
                   LEFT JOIN queries q ON q.id=ch.query_id
                   WHERE dc.dashboard_id=? ORDER BY dc.position""", (did,))


def integrations():
    return rows("SELECT * FROM data_integrations ORDER BY id DESC")


def save_integration(name: str, provider: str, source_url: str, schema_text: str) -> int:
    with cursor() as conn:
        conn.execute(
            "INSERT INTO data_integrations(name,provider,source_url,schema_text) VALUES (?,?,?,?)",
            (name.strip(), provider.strip(), source_url.strip(), schema_text),
        )
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def migrations():
    return rows("""SELECT m.*, i.name integration_name FROM migration_reports m
                   LEFT JOIN data_integrations i ON i.id=m.integration_id
                   ORDER BY m.id DESC""")


def save_migration(source_tool: str, file_name: str, integration_id: int | None,
                   instructions: str, summary: str, dashboard_id: int) -> int:
    with cursor() as conn:
        conn.execute(
            """INSERT INTO migration_reports
               (source_tool,file_name,integration_id,instructions,summary,dashboard_id)
               VALUES (?,?,?,?,?,?)""",
            (source_tool, file_name, integration_id, instructions, summary, dashboard_id),
        )
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


# --- save / delete saved queries (transactional) ----------------------------

def save_query(title: str, sql: str, chart_type: str = "bar", x_col: str = None, y_col: str = None) -> int:
    title = (title or "Untitled query").strip() or "Untitled query"
    if chart_type not in CHART_TYPES:
        chart_type = "bar"
    with cursor() as conn:
        conn.execute("INSERT INTO queries(title,description,sql,folder) VALUES (?,?,?,'Saved')",
                     (title, "Saved from the SQL lab.", sql.strip()))
        qid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("INSERT INTO charts(title,query_id,chart_type,x_col,y_col) VALUES (?,?,?,?,?)",
                     (title, qid, chart_type, x_col, y_col))
    return qid


def delete_query(qid: int):
    with cursor() as conn:
        conn.execute("DELETE FROM charts WHERE query_id=?", (qid,))
        conn.execute("DELETE FROM queries WHERE id=?", (qid,))
        conn.execute("DELETE FROM dashboard_charts WHERE chart_id NOT IN (SELECT id FROM charts)")


# --- dashboard editor (transactional) ---------------------------------------

def create_dashboard(title: str, description: str = "") -> int:
    title = (title or "Untitled dashboard").strip() or "Untitled dashboard"
    with cursor() as conn:
        conn.execute("INSERT INTO dashboards(title,description) VALUES (?,?)", (title, description.strip()))
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def charts_not_on(did: int):
    """Charts that aren't already placed on this dashboard."""
    return rows("""SELECT id, title, chart_type FROM charts
                   WHERE id NOT IN (SELECT chart_id FROM dashboard_charts WHERE dashboard_id=?)
                   ORDER BY title""", (did,))


def add_chart_to_dashboard(did: int, chart_id: int, width: str = "half") -> bool:
    if not chart(chart_id):
        return False
    if one("SELECT 1 FROM dashboard_charts WHERE dashboard_id=? AND chart_id=?", (did, chart_id)):
        return False
    with cursor() as conn:
        nxt = (conn.execute("SELECT COALESCE(MAX(position),0) FROM dashboard_charts WHERE dashboard_id=?",
                            (did,)).fetchone()[0]) + 1
        conn.execute("INSERT INTO dashboard_charts(dashboard_id,chart_id,position,width) VALUES (?,?,?,?)",
                     (did, chart_id, nxt, width if width in ("half", "full") else "half"))
    return True


def remove_chart_from_dashboard(did: int, chart_id: int) -> bool:
    with cursor() as conn:
        conn.execute("DELETE FROM dashboard_charts WHERE dashboard_id=? AND chart_id=?", (did, chart_id))
    return True


def set_chart_width(did: int, chart_id: int, width: str) -> bool:
    if width not in ("half", "full"):
        return False
    with cursor() as conn:
        conn.execute("UPDATE dashboard_charts SET width=? WHERE dashboard_id=? AND chart_id=?",
                     (width, did, chart_id))
    return True


def move_chart(did: int, chart_id: int, direction: str) -> bool:
    """Swap this chart's position with its neighbour above/below."""
    items = rows("SELECT chart_id, position FROM dashboard_charts WHERE dashboard_id=? ORDER BY position",
                 (did,))
    idx = next((i for i, it in enumerate(items) if it["chart_id"] == chart_id), None)
    if idx is None:
        return False
    swap = idx - 1 if direction == "up" else idx + 1
    if swap < 0 or swap >= len(items):
        return False
    a, b = items[idx], items[swap]
    with cursor() as conn:
        conn.execute("UPDATE dashboard_charts SET position=? WHERE dashboard_id=? AND chart_id=?",
                     (b["position"], did, a["chart_id"]))
        conn.execute("UPDATE dashboard_charts SET position=? WHERE dashboard_id=? AND chart_id=?",
                     (a["position"], did, b["chart_id"]))
    return True


# --- no-SQL query builder ---------------------------------------------------
# A metadata-driven builder over the wh_orders star schema: pick a dimension
# (group-by) and a measure (aggregate) and we assemble safe SQL — only the joins
# each side declares are added, in dependency order.

BUILDER_BASE = "wh_orders o"
BUILDER_JOINS = {
    "products":  "JOIN wh_products p ON p.product_id = o.product_id",
    "customers": "JOIN wh_customers c ON c.customer_id = o.customer_id",
    "regions":   "JOIN wh_regions r ON r.region_id = c.region_id",
}
_JOIN_ORDER = {"products": 0, "customers": 1, "regions": 2}

BUILDER_DIMENSIONS = {
    "Month":            {"expr": "substr(o.order_date,1,7)", "joins": []},
    "Channel":          {"expr": "o.channel",               "joins": []},
    "Product category": {"expr": "p.category",              "joins": ["products"]},
    "Product":          {"expr": "p.product",               "joins": ["products"]},
    "Customer segment": {"expr": "c.segment",               "joins": ["customers"]},
    "Region":           {"expr": "r.region",                "joins": ["customers", "regions"]},
    "Country":          {"expr": "r.country",               "joins": ["customers", "regions"]},
}
BUILDER_MEASURES = {
    "Revenue":         {"expr": "SUM(o.revenue)",        "joins": []},
    "Cost":            {"expr": "SUM(o.cost)",           "joins": []},
    "Gross margin":    {"expr": "SUM(o.revenue-o.cost)", "joins": []},
    "Quantity":        {"expr": "SUM(o.quantity)",       "joins": []},
    "Order count":     {"expr": "COUNT(*)",              "joins": []},
    "Avg order value": {"expr": "ROUND(AVG(o.revenue),2)", "joins": []},
}


def build_sql(dimension: str, measure: str, sort: str = "desc", limit: int = 20) -> str:
    d = BUILDER_DIMENSIONS.get(dimension)
    m = BUILDER_MEASURES.get(measure)
    if not d or not m:
        raise SQLError("Pick a dimension and a measure.")
    joins = []
    for j in list(d["joins"]) + list(m["joins"]):
        if j not in joins:
            joins.append(j)
    joins.sort(key=lambda j: _JOIN_ORDER[j])
    join_sql = (" " + " ".join(BUILDER_JOINS[j] for j in joins)) if joins else ""
    try:
        limit = max(1, min(int(limit), 500))
    except (TypeError, ValueError):
        limit = 20
    order_dir = "ASC" if sort == "asc" else "DESC"
    # Month reads best in chronological order regardless of measure
    order_by = "1 ASC" if dimension == "Month" else f"2 {order_dir}"
    return (f'SELECT {d["expr"]} AS "{dimension}", {m["expr"]} AS "{measure}"\n'
            f"FROM {BUILDER_BASE}{join_sql}\n"
            f'GROUP BY {d["expr"]}\n'
            f"ORDER BY {order_by}\n"
            f"LIMIT {limit}")
