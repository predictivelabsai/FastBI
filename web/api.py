"""FastBI public reads and token-gated integration writes."""

import db

from .api_core import Resource, SQLiteBackend, create_sqlite_api

RESOURCES = (
    Resource("queries", "queries", "Queries", "Governed reusable SQL queries.", search_fields=("title", "description", "folder")),
    Resource("charts", "charts", "Charts", "Visualisations backed by governed queries.", search_fields=("title", "chart_type")),
    Resource("dashboards", "dashboards", "Dashboards", "Collections of business intelligence visualisations.", write_fields=("title", "description"), search_fields=("title", "description")),
    Resource("orders", "wh_orders", "Warehouse orders", "Synthetic analytical order facts.", search_fields=("order_date", "channel"), primary_key="order_id"),
)

backend = SQLiteBackend(db.DB_PATH, RESOURCES, initialize=db.init_app_schema)
api = create_sqlite_api(
    product="FastBI", version="1.0.0",
    description="Open integration access to FastBI queries, charts, dashboards, and analytical facts.",
    base_url="https://fastbi.org", backend=backend, resources=RESOURCES,
)
