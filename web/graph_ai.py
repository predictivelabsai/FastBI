"""Text-to-Cypher and graph-answer helpers parallel to FastBI text-to-SQL."""
from __future__ import annotations

import json
import re
from typing import Any

import graph_db


CYPHER_SYSTEM = """You write safe read-only Cypher for a Neo4j ontology graph.
Return ONLY JSON with this exact shape:
{{"cypher":"MATCH ... RETURN ... LIMIT 50","parameters":{{}},"explanation":"one short sentence"}}

{schema}

Rules:
- Start with MATCH or OPTIONAL MATCH and always RETURN a result.
- Read only: never CREATE, MERGE, DELETE, SET, REMOVE, CALL, LOAD CSV, or administer Neo4j.
- Use parameters for user-provided values and return them in the parameters object.
- Include LIMIT 50 or less.
- When the user asks about relationships, return nodes and relationships where useful.
- Use only labels, relationship types, and properties from the schema.
"""


def _extract_json(text: str) -> dict[str, Any]:
    clean = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", clean, re.I | re.S)
    if fenced:
        clean = fenced.group(1)
    else:
        obj = re.search(r"\{.*\}", clean, re.S)
        if obj:
            clean = obj.group(0)
    try:
        value = json.loads(clean)
    except json.JSONDecodeError as exc:
        raise graph_db.CypherError("The model did not return structured Cypher JSON.") from exc
    if not isinstance(value, dict):
        raise graph_db.CypherError("The model did not return a Cypher object.")
    return value


def text_to_cypher(question: str) -> tuple[str, dict[str, Any], str]:
    from web.ai import _complete

    system = CYPHER_SYSTEM.format(schema=graph_db.schema_prompt())
    payload = _extract_json(_complete(system, question))
    cypher = graph_db.validate_cypher(str(payload.get("cypher") or ""), max_rows=50)
    params = payload.get("parameters") or {}
    if not isinstance(params, dict) or any(
        not isinstance(key, str) or not isinstance(value, (str, int, float, bool, type(None)))
        for key, value in params.items()
    ):
        raise graph_db.CypherError("Generated Cypher parameters must be scalar values.")
    explanation = str(payload.get("explanation") or "Generated a read-only graph query.")[:500]
    return cypher, params, explanation


def _cell(value: Any) -> str:
    if isinstance(value, dict):
        props = value.get("properties") if isinstance(value.get("properties"), dict) else value
        return str(props.get("label") or props.get("name") or props.get("external_id") or json.dumps(value, ensure_ascii=False))
    if isinstance(value, list):
        return ", ".join(_cell(item) for item in value[:8])
    return str(value)


def markdown_answer(question: str, result: graph_db.GraphResult, explanation: str = "") -> str:
    lines = [f"**Graph answer** — {explanation or 'read from the active ontology.'}"]
    if result.columns and result.rows:
        lines.extend([
            "",
            "| " + " | ".join(result.columns) + " |",
            "| " + " | ".join("---" for _ in result.columns) + " |",
        ])
        for row in result.rows[:12]:
            lines.append("| " + " | ".join(_cell(value).replace("|", "\\|") for value in row) + " |")
    else:
        lines.extend(["", "No matching graph records were found."])
    lines.extend([
        "",
        f"{len(result.nodes)} graph nodes and {len(result.edges)} relationships returned.",
        "",
        "```cypher",
        result.cypher,
        "```",
        "Open **Cypher Lab + Ask AI** to inspect the interactive graph.",
    ])
    return "\n".join(lines)
