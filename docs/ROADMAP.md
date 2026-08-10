# FastBI Roadmap — Frappe Insights feature comparison

FastBI ports the **core** of [Frappe Insights](https://github.com/frappe/insights)
(~38 doctypes) to a FastHTML demonstrator.

## Implemented ✅

| Capability | Upstream doctype(s) | FastBI |
|---|---|---|
| Data source | `Insights Data Source v3` | local synthetic SQLite warehouse (`wh_*`) |
| Tables browser | `Insights Table v3` | `/sources` with schema + samples |
| Queries | `Insights Query v3` | `queries` (saved SQL) + SQL lab |
| Charts | `Insights Chart v3` | `charts` + Plotly (bar/line/pie/row) |
| Dashboards | `Insights Dashboard v3`/`Item` | `dashboards` + responsive grid |
| **Dashboard editor** | `Insights Dashboard Item` | create board, add/remove/reorder/resize tiles (HTMX) |
| **No-SQL query builder** | `is_builder_query` | pick a measure + dimension → safe SQL, auto-joins |
| Read-only execution | query engine | `db.run_sql()` guard (single SELECT only) |
| **AI text-to-SQL** | *(not upstream)* | natural language → SQL → chart |
| Metric chat | *(not upstream)* | grounded multi-provider assistant |

## Near-term roadmap 🔜

1. ✅ **Save ad-hoc queries** (done) — the SQL lab / AI result saves as a new
   `query` + `chart` (currently the 7 saved queries are seeded).
2. ✅ **Query builder** (done) — a metadata-driven no-SQL builder: pick a
   **measure** (Revenue / Margin / Quantity / Order count / AOV) and a
   **dimension** (Month / Channel / Category / Product / Segment / Region /
   Country); only the joins each side declares are added, in dependency order,
   and the generated SQL still passes the read-only guard. Result is chartable
   and savable like any other query.
3. ✅ **Dashboard editor** (done) — create a dashboard, add an existing chart
   (half/full width), reorder tiles up/down, toggle a tile's width and remove
   it — all HTMX, swapping just the grid. Dashboard-level filters still to come.
4. **Workbooks & folders** — `Insights Workbook`, `Folder` (organise queries
   and charts into projects).
5. **Variables / parameters** — `Insights Query Variable` (parameterised
   queries, e.g. a date-range or region selector).
6. **Alerts** — `Insights Alert` (threshold alerts on a metric).

## Later / out-of-scope 🗓️

- **Live external connections** — `Insights Data Source v3` connects to MySQL,
  Postgres, BigQuery, the site DB, etc. FastBI uses a bundled SQLite
  warehouse; a read-only external-DB connector is the natural next step.
- **Query transforms / pivot / joins UI** — `Insights Query Transform`,
  multi-query references (`Insights Query Reference`).
- **Notebooks** — `Insights Notebook`/`Page` (Python/markdown analysis notebooks).
- **Team permissions & sharing** — `Insights Team`, `Resource Permission`,
  public share links.
- **Stored-procedure execution**, caching, scheduled refresh.

## Design notes

The headline is **AI text-to-SQL with a hard read-only guard**: `db.run_sql()`
rejects anything that isn't a single `SELECT`/`WITH`, blocks DML/DDL keywords,
and auto-applies a `LIMIT`. This lets the LLM (or a curious analyst) write
arbitrary queries safely against the warehouse. Charts are server-rendered
Plotly specs (`web/charts.py`), and the **dashboard composer** now lets users
assemble those into boards (add/remove/reorder/resize, all HTMX). The **no-SQL
builder** generalises the safe path to non-technical users: it never accepts raw
SQL — it assembles a known-safe query from a curated measure/dimension catalogue,
so the read-only guard and the builder are belt-and-braces.
