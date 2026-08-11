"""Optional Neo4j graph engine for FastBI.

SQLite remains FastBI's primary analytical and application store.  This module
owns the secondary graph connection, the small JSON/YAML ontology contract,
idempotent ontology replacement, graph visualisation payloads, and the guarded
read-only Cypher executor used by both the Cypher Lab and conversational AI.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from typing import Any

import yaml


MAX_ONTOLOGY_BYTES = int(os.getenv("FASTBI_GRAPH_MAX_IMPORT_BYTES", str(2 * 1024 * 1024)))
MAX_ONTOLOGY_NODES = int(os.getenv("FASTBI_GRAPH_MAX_IMPORT_NODES", "5000"))
MAX_ONTOLOGY_EDGES = int(os.getenv("FASTBI_GRAPH_MAX_IMPORT_EDGES", "10000"))
MAX_QUERY_ROWS = int(os.getenv("FASTBI_GRAPH_MAX_QUERY_ROWS", "200"))
MAX_VIS_NODES = int(os.getenv("FASTBI_GRAPH_MAX_VIS_NODES", "400"))
QUERY_TIMEOUT = float(os.getenv("FASTBI_GRAPH_QUERY_TIMEOUT", "5"))

_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_ONTOLOGY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_FORBIDDEN_CYPHER = re.compile(
    r"\b(create|merge|delete|detach|set|remove|drop|alter|rename|load\s+csv|"
    r"call|yield|union|show|terminate|start\s+database|stop\s+database|grant|deny|revoke|"
    r"foreach|use)\b",
    re.IGNORECASE,
)


class GraphError(RuntimeError):
    """Base graph error safe to show to an authenticated user."""


class GraphUnavailable(GraphError):
    """The optional graph engine is disabled or unreachable."""


class OntologyError(ValueError):
    """An ontology failed validation."""


class CypherError(ValueError):
    """A Cypher query failed the read-only guard or execution."""


@dataclass(frozen=True)
class GraphResult:
    columns: list[str]
    rows: list[list[Any]]
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    cypher: str


_driver = None


def enabled() -> bool:
    return os.getenv("FASTBI_GRAPH_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}


def configured() -> bool:
    return enabled() and bool(os.getenv("NEO4J_URI")) and bool(os.getenv("NEO4J_PASSWORD"))


def _get_driver():
    global _driver
    if not configured():
        raise GraphUnavailable("Neo4j is not configured for this FastBI deployment.")
    if _driver is None:
        from neo4j import GraphDatabase

        _driver = GraphDatabase.driver(
            os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687"),
            auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "")),
            max_connection_lifetime=300,
            connection_timeout=5,
        )
    return _driver


def close() -> None:
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None


def health() -> dict[str, Any]:
    state = {"enabled": enabled(), "configured": configured(), "connected": False}
    if not configured():
        return state
    try:
        driver = _get_driver()
        driver.verify_connectivity()
        with driver.session(database=os.getenv("NEO4J_DATABASE", "neo4j")) as session:
            record = session.run(
                "MATCH (n:OntologyNode) RETURN count(n) AS nodes"
            ).single()
        state.update({"connected": True, "nodes": int(record["nodes"] if record else 0)})
    except Exception as exc:  # connection messages can contain hostnames; return only the class
        state["error"] = type(exc).__name__
    return state


def ensure_schema() -> None:
    try:
        driver = _get_driver()
        statements = (
            "CREATE CONSTRAINT fastbi_ontology_id IF NOT EXISTS "
            "FOR (o:Ontology) REQUIRE o.ontology_id IS UNIQUE",
            "CREATE CONSTRAINT fastbi_ontology_node_key IF NOT EXISTS "
            "FOR (n:OntologyNode) REQUIRE n.key IS UNIQUE",
        )
        with driver.session(database=os.getenv("NEO4J_DATABASE", "neo4j")) as session:
            for statement in statements:
                session.run(statement).consume()
    except GraphError:
        raise
    except Exception as exc:
        raise GraphUnavailable(f"Neo4j schema setup failed ({type(exc).__name__}).") from exc


def _clean_property(value: Any, path: str) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list) and all(v is None or isinstance(v, (str, int, float, bool)) for v in value):
        return value
    raise OntologyError(f"{path} must be a scalar or a list of scalars.")


def _properties(raw: Any, path: str) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise OntologyError(f"{path} must be an object.")
    clean = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not _IDENTIFIER.fullmatch(key):
            raise OntologyError(f"{path} contains an invalid property name: {key!r}.")
        if key in {"key", "ontology_id", "external_id", "kind", "label"}:
            raise OntologyError(f"{path}.{key} is reserved by FastBI.")
        clean[key] = _clean_property(value, f"{path}.{key}")
    return clean


def parse_ontology(raw: bytes, filename: str = "ontology.yaml") -> dict[str, Any]:
    """Parse and validate the FastBI JSON/YAML property-graph contract."""
    if len(raw) > MAX_ONTOLOGY_BYTES:
        raise OntologyError(f"Ontology files are limited to {MAX_ONTOLOGY_BYTES // (1024 * 1024)} MB.")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise OntologyError("Ontology files must be UTF-8 JSON or YAML.") from exc
    try:
        data = json.loads(text) if filename.lower().endswith(".json") else yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise OntologyError("The ontology is not valid JSON/YAML.") from exc
    if not isinstance(data, dict):
        raise OntologyError("The ontology root must be an object.")

    meta = data.get("ontology")
    if not isinstance(meta, dict):
        raise OntologyError("Add an ontology object with id, name, and version.")
    ontology_id = str(meta.get("id") or "").strip()
    if not _ONTOLOGY_ID.fullmatch(ontology_id):
        raise OntologyError("ontology.id must contain only letters, numbers, dots, dashes, or underscores.")
    name = str(meta.get("name") or ontology_id).strip()[:200]
    version = str(meta.get("version") or "1.0").strip()[:80]
    description = str(meta.get("description") or "").strip()[:2000]

    raw_nodes, raw_edges = data.get("nodes"), data.get("edges")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise OntologyError("nodes must be a non-empty list.")
    if not isinstance(raw_edges, list):
        raise OntologyError("edges must be a list.")
    if len(raw_nodes) > MAX_ONTOLOGY_NODES or len(raw_edges) > MAX_ONTOLOGY_EDGES:
        raise OntologyError(
            f"Ontology limit: {MAX_ONTOLOGY_NODES} nodes and {MAX_ONTOLOGY_EDGES} edges."
        )

    nodes, node_ids = [], set()
    for index, item in enumerate(raw_nodes):
        if not isinstance(item, dict):
            raise OntologyError(f"nodes[{index}] must be an object.")
        external_id = str(item.get("id") or "").strip()
        kind = str(item.get("type") or "Entity").strip()
        if not external_id or len(external_id) > 200:
            raise OntologyError(f"nodes[{index}].id is required and limited to 200 characters.")
        if external_id in node_ids:
            raise OntologyError(f"Duplicate node id: {external_id}.")
        if not _IDENTIFIER.fullmatch(kind):
            raise OntologyError(f"nodes[{index}].type is not a safe graph label.")
        node_ids.add(external_id)
        nodes.append({
            "id": external_id,
            "type": kind,
            "label": str(item.get("label") or external_id).strip()[:300],
            "properties": _properties(item.get("properties"), f"nodes[{index}].properties"),
        })

    edges, edge_ids = [], set()
    for index, item in enumerate(raw_edges):
        if not isinstance(item, dict):
            raise OntologyError(f"edges[{index}] must be an object.")
        source, target = str(item.get("from") or "").strip(), str(item.get("to") or "").strip()
        rel_type = str(item.get("type") or "RELATED_TO").strip().upper()
        external_id = str(item.get("id") or f"{source}:{rel_type}:{target}:{index}").strip()
        if source not in node_ids or target not in node_ids:
            raise OntologyError(f"edges[{index}] references an unknown node.")
        if not _IDENTIFIER.fullmatch(rel_type):
            raise OntologyError(f"edges[{index}].type is not a safe relationship type.")
        if not external_id or len(external_id) > 300 or external_id in edge_ids:
            raise OntologyError(f"edges[{index}].id is invalid or duplicated.")
        edge_ids.add(external_id)
        edges.append({
            "id": external_id,
            "from": source,
            "to": target,
            "type": rel_type,
            "properties": _properties(item.get("properties"), f"edges[{index}].properties"),
        })

    return {
        "ontology": {"id": ontology_id, "name": name, "version": version, "description": description},
        "nodes": nodes,
        "edges": edges,
    }


def ontology_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def ontology_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(ontology_json(payload).encode()).hexdigest()


def import_ontology(payload: dict[str, Any]) -> dict[str, Any]:
    """Atomically replace one ontology's active graph using validated data."""
    # Revalidate canonical JSON so callers cannot bypass the public parser.
    payload = parse_ontology(ontology_json(payload).encode(), "ontology.json")
    ensure_schema()
    ontology = payload["ontology"]
    oid = ontology["id"]
    grouped_nodes: dict[str, list[dict[str, Any]]] = {}
    for node in payload["nodes"]:
        grouped_nodes.setdefault(node["type"], []).append({
            "key": f"{oid}::{node['id']}", "external_id": node["id"],
            "label": node["label"], "kind": node["type"], "properties": node["properties"],
        })
    grouped_edges: dict[str, list[dict[str, Any]]] = {}
    for edge in payload["edges"]:
        grouped_edges.setdefault(edge["type"], []).append({
            "key": f"{oid}::{edge['id']}", "source": f"{oid}::{edge['from']}",
            "target": f"{oid}::{edge['to']}", "external_id": edge["id"],
            "properties": edge["properties"],
        })

    def write(tx):
        tx.run("MATCH (n:OntologyNode {ontology_id:$oid}) DETACH DELETE n", oid=oid).consume()
        tx.run(
            "MERGE (o:Ontology {ontology_id:$oid}) "
            "SET o.name=$name,o.version=$version,o.description=$description,"
            "o.content_hash=$hash,o.imported_at=datetime()",
            oid=oid, name=ontology["name"], version=ontology["version"],
            description=ontology["description"], hash=ontology_hash(payload),
        ).consume()
        for kind, rows in grouped_nodes.items():
            tx.run(
                f"UNWIND $rows AS row MERGE (n:OntologyNode:`{kind}` {{key:row.key}}) "
                "SET n.ontology_id=$oid,n.external_id=row.external_id,n.label=row.label,n.kind=row.kind "
                "SET n += row.properties WITH n "
                "MATCH (o:Ontology {ontology_id:$oid}) MERGE (o)-[:CONTAINS]->(n)",
                rows=rows, oid=oid,
            ).consume()
        for rel_type, rows in grouped_edges.items():
            tx.run(
                f"UNWIND $rows AS row MATCH (a:OntologyNode {{key:row.source}}) "
                f"MATCH (b:OntologyNode {{key:row.target}}) "
                f"MERGE (a)-[r:`{rel_type}` {{key:row.key}}]->(b) "
                "SET r.ontology_id=$oid,r.external_id=row.external_id SET r += row.properties",
                rows=rows, oid=oid,
            ).consume()

    try:
        driver = _get_driver()
        with driver.session(database=os.getenv("NEO4J_DATABASE", "neo4j")) as session:
            session.execute_write(write)
    except GraphError:
        raise
    except Exception as exc:
        raise GraphError(f"Neo4j ontology import failed ({type(exc).__name__}).") from exc
    return {"ontology_id": oid, "nodes": len(payload["nodes"]), "edges": len(payload["edges"])}


def list_ontologies() -> list[dict[str, Any]]:
    if not configured():
        return []
    try:
        with _get_driver().session(database=os.getenv("NEO4J_DATABASE", "neo4j")) as session:
            return session.run(
                "MATCH (o:Ontology) OPTIONAL MATCH (o)-[:CONTAINS]->(n:OntologyNode) "
                "RETURN o.ontology_id AS id,o.name AS name,o.version AS version,"
                "o.content_hash AS content_hash,count(n) AS nodes ORDER BY o.name"
            ).data()
    except GraphError:
        raise
    except Exception as exc:
        raise GraphUnavailable(f"Neo4j ontology listing failed ({type(exc).__name__}).") from exc


def schema() -> dict[str, Any]:
    if not configured():
        raise GraphUnavailable("Neo4j is not configured for this FastBI deployment.")
    try:
        with _get_driver().session(database=os.getenv("NEO4J_DATABASE", "neo4j")) as session:
            node_rows = session.run(
                "MATCH (n:OntologyNode) UNWIND labels(n) AS label "
                "WITH label,n WHERE label <> 'OntologyNode' "
                "UNWIND keys(n) AS property "
                "WITH label,collect(DISTINCT property) AS properties,count(DISTINCT n) AS count "
                "RETURN label,properties,count ORDER BY label"
            ).data()
            rel_rows = session.run(
                "MATCH (a:OntologyNode)-[r]->(b:OntologyNode) "
                "RETURN type(r) AS type,collect(DISTINCT a.kind) AS from_labels,"
                "collect(DISTINCT b.kind) AS to_labels,count(r) AS count ORDER BY type"
            ).data()
    except GraphError:
        raise
    except Exception as exc:
        raise GraphUnavailable(f"Neo4j schema read failed ({type(exc).__name__}).") from exc
    internal = {"key", "ontology_id", "external_id", "kind"}
    for row in node_rows:
        row["properties"] = sorted(p for p in row["properties"] if p not in internal)
    return {"nodes": node_rows, "relationships": rel_rows}


def schema_prompt() -> str:
    graph_schema = schema()
    lines = ["Neo4j ontology graph schema:"]
    for item in graph_schema["nodes"]:
        props = ", ".join(item["properties"])
        lines.append(f"  (:{item['label']}) properties [{props}]")
    for item in graph_schema["relationships"]:
        lines.append(
            f"  ({'|'.join(item['from_labels'])})-[:{item['type']}]->"
            f"({'|'.join(item['to_labels'])})"
        )
    lines.append("Every imported node also has :OntologyNode and ontology_id, external_id, label, and kind.")
    return "\n".join(lines)


def validate_cypher(cypher: str, max_rows: int = MAX_QUERY_ROWS) -> str:
    query = (cypher or "").strip().rstrip(";").strip()
    if not query:
        raise CypherError("Empty Cypher query.")
    if ";" in query or "//" in query or "/*" in query or "*/" in query:
        raise CypherError("Only one comment-free Cypher statement is allowed.")
    if not re.match(r"^(optional\s+match|match)\b", query, re.IGNORECASE):
        raise CypherError("Read-only Cypher must start with MATCH or OPTIONAL MATCH.")
    if _FORBIDDEN_CYPHER.search(query) or re.search(r"\b(apoc|dbms|n10s|db)\s*\.", query, re.I):
        raise CypherError("Only read-only graph matching is allowed.")
    if not re.search(r"\breturn\b", query, re.IGNORECASE):
        raise CypherError("Cypher must return a bounded result.")
    limits = re.findall(r"\blimit\s+(\d+)\b", query, re.IGNORECASE)
    if limits and any(int(value) > max_rows for value in limits):
        raise CypherError(f"Cypher LIMIT cannot exceed {max_rows}.")
    if not limits:
        query += f"\nLIMIT {max_rows}"
    return query


def _element_id(value: Any) -> str:
    return str(getattr(value, "element_id", None) or getattr(value, "id", ""))


def _json_value(value: Any) -> Any:
    from neo4j.graph import Node, Path, Relationship

    if isinstance(value, Node):
        return {"id": _element_id(value), "labels": sorted(value.labels), "properties": dict(value)}
    if isinstance(value, Relationship):
        return {"id": _element_id(value), "type": value.type, "properties": dict(value)}
    if isinstance(value, Path):
        return {"nodes": [_json_value(n) for n in value.nodes], "relationships": [_json_value(r) for r in value.relationships]}
    if isinstance(value, (list, tuple)):
        return [_json_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _json_value(v) for k, v in value.items()}
    if hasattr(value, "iso_format"):
        return value.iso_format()
    return value


def _collect_graph(value: Any, nodes: dict[str, dict], edges: dict[str, dict]) -> None:
    from neo4j.graph import Node, Path, Relationship

    if isinstance(value, Node):
        nid = _element_id(value)
        props = dict(value)
        groups = sorted(label for label in value.labels if label != "OntologyNode")
        nodes[nid] = {
            "id": nid, "label": str(props.get("label") or props.get("name") or props.get("external_id") or nid),
            "group": groups[0] if groups else "OntologyNode", "properties": _json_value(props),
        }
    elif isinstance(value, Relationship):
        rid = _element_id(value)
        _collect_graph(value.start_node, nodes, edges)
        _collect_graph(value.end_node, nodes, edges)
        edges[rid] = {
            "id": rid, "from": _element_id(value.start_node), "to": _element_id(value.end_node),
            "label": value.type, "arrows": "to", "properties": _json_value(dict(value)),
        }
    elif isinstance(value, Path):
        for node in value.nodes:
            _collect_graph(node, nodes, edges)
        for relationship in value.relationships:
            _collect_graph(relationship, nodes, edges)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _collect_graph(item, nodes, edges)
    elif isinstance(value, dict):
        for item in value.values():
            _collect_graph(item, nodes, edges)


def run_cypher(cypher: str, params: dict[str, Any] | None = None) -> GraphResult:
    query = validate_cypher(cypher)
    params = params or {}
    driver = _get_driver()

    def read(tx, statement, parameters):
        tx.run("EXPLAIN " + statement, parameters).consume()
        result = tx.run(statement, parameters)
        columns = list(result.keys())
        records = [record for record in result]
        return columns, records

    try:
        from neo4j import unit_of_work

        read_work = unit_of_work(timeout=QUERY_TIMEOUT, metadata={"app": "FastBI", "mode": "text-to-cypher"})(read)
        with driver.session(database=os.getenv("NEO4J_DATABASE", "neo4j")) as session:
            columns, records = session.execute_read(read_work, query, params)
    except CypherError:
        raise
    except Exception as exc:
        raise CypherError(f"Neo4j rejected the read-only query ({type(exc).__name__}).") from exc

    graph_nodes: dict[str, dict] = {}
    graph_edges: dict[str, dict] = {}
    rows = []
    for record in records[:MAX_QUERY_ROWS]:
        values = [record[column] for column in columns]
        for value in values:
            _collect_graph(value, graph_nodes, graph_edges)
        rows.append([_json_value(value) for value in values])
    return GraphResult(columns, rows, list(graph_nodes.values()), list(graph_edges.values()), query)


def explorer_payload(ontology_id: str | None = None, limit: int = MAX_VIS_NODES) -> dict[str, Any]:
    where = " WHERE n.ontology_id=$oid" if ontology_id else ""
    query = (
        f"MATCH (n:OntologyNode){where} WITH n LIMIT $limit "
        "OPTIONAL MATCH (n)-[r]->(m:OntologyNode) "
        "WHERE m IS NULL OR m.ontology_id=n.ontology_id RETURN n,r,m"
    )
    result = run_cypher(query, {"oid": ontology_id, "limit": min(limit, MAX_VIS_NODES)})
    # Isolated or destination-only nodes can be missed by the source-limited query.
    return {
        "nodes": result.nodes,
        "edges": result.edges,
        "stats": f"{len(result.nodes)} nodes · {len(result.edges)} relationships",
        "ontology_id": ontology_id or "",
    }
