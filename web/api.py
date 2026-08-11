"""FastBI public reads and token-gated integration/graph operations."""

from typing import Any

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

import db
import graph_db

from .api_core import Resource, SQLiteBackend, create_sqlite_api, require_write_token

RESOURCES = (
    Resource("queries", "queries", "Queries", "Governed reusable SQL queries.", search_fields=("title", "description", "folder")),
    Resource("charts", "charts", "Charts", "Visualisations backed by governed queries.", search_fields=("title", "chart_type")),
    Resource("dashboards", "dashboards", "Dashboards", "Collections of business intelligence visualisations.", write_fields=("title", "description"), search_fields=("title", "description")),
    Resource("orders", "wh_orders", "Warehouse orders", "Synthetic analytical order facts.", search_fields=("order_date", "channel"), primary_key="order_id"),
)

if not db.db_exists() or not db.scalar(
    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='wh_orders'"
):
    import seed

    seed.build()

backend = SQLiteBackend(db.DB_PATH, RESOURCES, initialize=db.init_app_schema)
api = create_sqlite_api(
    product="FastBI", version="1.0.0",
    description="Open integration access to FastBI queries, charts, dashboards, and analytical facts.",
    base_url="https://fastbi.org", backend=backend, resources=RESOURCES,
)


class GraphQueryRequest(BaseModel):
    cypher: str | None = Field(default=None, description="Guarded read-only Cypher")
    question: str | None = Field(default=None, description="Natural-language graph question")
    parameters: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


@api.get("/v1/graph/health", tags=["Graph"], summary="Check the optional Neo4j engine")
def graph_health() -> dict[str, Any]:
    return graph_db.health()


@api.get(
    "/v1/graph/schema", tags=["Graph"], summary="Read the active graph schema",
    dependencies=[Depends(require_write_token)],
)
def graph_schema() -> dict[str, Any]:
    try:
        return graph_db.schema()
    except graph_db.GraphError as exc:
        raise HTTPException(status_code=503, detail={"code": "graph_unavailable", "message": str(exc), "details": {}}) from exc


@api.post(
    "/v1/graph/query", tags=["Graph"], summary="Run guarded read-only Cypher",
    dependencies=[Depends(require_write_token)],
)
def graph_query(body: GraphQueryRequest) -> dict[str, Any]:
    try:
        note = ""
        if body.question:
            from . import graph_ai

            cypher, params, note = graph_ai.text_to_cypher(body.question.strip())
        elif body.cypher:
            cypher, params = body.cypher, body.parameters
        else:
            raise graph_db.CypherError("Provide cypher or a natural-language question.")
        result = graph_db.run_cypher(cypher, params)
        return {
            "cypher": result.cypher, "explanation": note,
            "columns": result.columns, "rows": result.rows,
            "nodes": result.nodes, "edges": result.edges,
        }
    except graph_db.GraphUnavailable as exc:
        raise HTTPException(status_code=503, detail={"code": "graph_unavailable", "message": str(exc), "details": {}}) from exc
    except graph_db.CypherError as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_cypher", "message": str(exc), "details": {}}) from exc
