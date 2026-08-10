# Skills

Capability reference for FastBI + the shared **Frappe → FastHTML migration
playbook** (same recipe across `fasthtml-oss-migrations`; see also
`FastCRM/SKILLS.md`).

---

## Part 1 — FastBI capabilities

**Entry:** `python web_app.py` → http://localhost:5008. Configure local admin
credentials in the ignored `.env`, or use Google SSO.

### Pages

| View | Route | What it shows |
|---|---|---|
| Home | `/` | KPIs + flagship Plotly charts + dashboard links |
| Dashboards | `/dashboards`, `/dashboards/{id}` | boards of charts in a responsive grid |
| Queries & Charts | `/queries`, `/queries/{id}` | saved SQL + chart + result table |
| SQL Lab + Ask AI | `/sql` | run read-only SQL, or AI text-to-SQL |
| Data Source | `/sources` | warehouse tables, row counts, samples |
| Integrations | `/integrations` | guarded HTTP(S) schema/catalogue import |
| Migrations | `/migrations` | report artefact upload → editable dashboard |
| AI Assistant | `/ai` | metric chat (right rail) |

### Warehouse & safe SQL (`db.py`)

A bundled SQLite **retail star schema**: `wh_orders` (fact) + `wh_customers`,
`wh_products`, `wh_regions` (dims). `run_sql(sql)` enforces a single read-only
`SELECT`/`WITH` (blocks DML/DDL and multiple statements, auto-`LIMIT`) so both
the SQL lab and AI generation are safe.

### Charts (`web/charts.py`)

`plotly(div_id, cols, data, chart_type, x_col, y_col)` emits a Plotly spec +
tiny init script (bar / line / pie / row). `result_table()` renders a typed
result grid. Charts re-init after HTMX swaps via a `data-plot` re-eval hook in
`layout.py`.

### AI (`web/ai.py`)

- **text_to_sql(question)** — sends the question + live schema to the LLM, parses
  one SELECT out, returns it for `run_sql`. Used by `/sql/ask`.
- **Grounded chat** — streamed, with a live data summary in the system prompt.
- **Slash-commands** (no key): `/metrics`, `/tables`, `/top region|category|customer`.

### Integrations and migrations (`web/integrations.py`)

- **Schema import** follows only validated public HTTP(S) URLs, rejects
  credential-bearing/private-network targets, and caps responses at 2 MB.
- **Report migration** accepts Power BI, Tableau, Looker, text, PDF, and image
  artefacts up to 8 MB, combines them with a selected schema and migration
  instructions, then creates a governed editable dashboard immediately.

---

## Part 2 — Frappe → FastHTML migration playbook

1. **Mine the schema** — `python scripts/frappe_doctype_to_schema.py
   /tmp/frappe-insights` → starting SQLite DDL.
2. **Collapse, don't replicate** — Insights' Query/Chart/Dashboard *v3* doctypes
   become three small tables; the data-source plumbing becomes one bundled DB.
3. **FastHTML shell** — `fast_app(pico=False, hdrs=[Style(CSS)])`; `page()`
   wrapper; `_guard()` auth; **add Plotly + marked CDNs in `page()`**.
4. **HTMX over JS** — the SQL lab posts to `/sql/run` and `/sql/ask` with
   `hx_post`/`hx_target`; results (incl. charts) swap in. Re-run chart scripts in
   the `htmx:afterSwap` hook.
5. **Synthetic data** — fixed RNG seed; self-seed on first boot.
6. **LLM, key-optional** — reuse `_provider_stream` (chat) and `_complete`
   (text-to-SQL). Everything non-AI works with no key.
7. **Capture the demo** — Playwright MCP → frames → `bash scripts/build_demo_gif.sh`.
8. **Ship deploy paths** — `.env.sample`, `Dockerfile`, `docker-compose.yml`.

### Reusable assets

| File | Reuse |
|---|---|
| `scripts/frappe_doctype_to_schema.py` | DocType JSON → SQLite DDL |
| `scripts/build_demo_gif.sh` | frames → demo GIF |
| `web/charts.py` | Plotly chart + typed result-table rendering (any data app) |
| `db.run_sql()` | read-only SQL guard for AI/user-supplied SQL |
| `web/ai.py` `_complete()` / `text_to_sql()` | non-streaming LLM call + NL→SQL |
| `web/layout.py` | 3-pane shell + CSS tokens + SSE chat JS |
