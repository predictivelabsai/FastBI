"""FastHTML surfaces for ontologies, graph exploration, and Cypher results."""
from __future__ import annotations

import json
from typing import Any

from fasthtml.common import *

import graph_db
from web.views import _title
from web.layout import generation_progress


def _safe_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False).replace("<", "\\u003c")


def graph_status_card() -> Any:
    status = graph_db.health()
    if status.get("connected"):
        return Div(
            Span("Connected", cls="pill line"),
            Span(f"{status.get('nodes', 0)} ontology nodes", style="margin-left:8px;color:var(--text-mute);"),
            cls="card",
        )
    message = "Neo4j is disabled." if not status.get("enabled") else "Neo4j is currently unavailable."
    return Div(Div(f"⚠ {message}", cls="sql-result-err"), cls="card")


def _network(payload: dict[str, Any], element_id: str, height: str = "620px") -> tuple:
    data = _safe_json(payload)
    script = f"""
(function(){{
  var payload={data};
  var palette=['#2563eb','#7c3aed','#0f766e','#d97706','#e11d48','#475569','#0891b2'];
  var groups={{}}, names=[];
  payload.nodes.forEach(function(n){{if(names.indexOf(n.group)<0)names.push(n.group);}});
  names.sort().forEach(function(name,i){{var c=palette[i%palette.length];groups[name]={{
    shape:name==='Metric'?'diamond':'dot',color:{{background:c,border:c,highlight:{{background:c,border:'#111827'}}}},
    font:{{color:'#16203a',size:13}},borderWidth:1}};}});
  var nodes=new vis.DataSet(payload.nodes),edges=new vis.DataSet(payload.edges);
  var net=new vis.Network(document.getElementById('{element_id}'),{{nodes:nodes,edges:edges}},{{
    groups:groups,nodes:{{scaling:{{min:10,max:42}}}},
    edges:{{arrows:{{to:{{scaleFactor:.55}}}},color:{{color:'#aeb8ca'}},font:{{size:10,color:'#667085',align:'middle'}},smooth:{{type:'dynamic'}}}},
    physics:{{stabilization:{{iterations:180}},barnesHut:{{springLength:135,avoidOverlap:.25}}}},
    interaction:{{hover:true,tooltipDelay:120,navigationButtons:true,keyboard:true}}
  }});
  net.on('click',function(p){{if(!p.nodes.length)return;var n=nodes.get(p.nodes[0]);
    var box=document.getElementById('{element_id}-detail');if(box)box.textContent=JSON.stringify(n.properties||{{}},null,2);}});
}})();
"""
    return (
        Div(id=element_id, style=f"height:{height};border:1px solid var(--border);border-radius:10px;background:#fbfcff;"),
        Div(Div(H3("Selected node"), cls="card-header"),
            Pre("Click a node to inspect its properties.", id=f"{element_id}-detail",
                style="white-space:pre-wrap;margin:0;font-size:12px;overflow:auto;max-height:220px;"), cls="card"),
        Script(NotStr(script), **{"data-network": "1"}),
    )


def graph_explorer(payload: dict[str, Any] | None, ontologies: list[dict], selected: str = ""):
    options = [Option("All active ontologies", value="", selected=not selected)] + [
        Option(f"{item.get('name') or item['id']} · {item.get('version') or ''}", value=item["id"],
               selected=item["id"] == selected) for item in ontologies
    ]
    controls = Form(
        Select(*options, name="ontology", onchange="this.form.submit()",
               style="padding:8px 10px;border:1px solid var(--border);border-radius:8px;min-width:260px;"),
        method="get", action="/graph", style="display:flex;gap:10px;align-items:center;",
    )
    if payload is None:
        body = graph_status_card()
    elif not payload.get("nodes"):
        body = Div(P("No ontology nodes are available yet. Import one under Data → Ontologies."), cls="card")
    else:
        body = (Div(Span(payload.get("stats", ""), cls="pill"), cls="card"), *_network(payload, "ontology-network"))
    body_items = body if isinstance(body, tuple) else (body,)
    return (
        _title("Graph Explorer", "Explore ontology classes, metrics, and their relationships.", controls),
        *body_items,
    )


def ontology_workspace(imports: list[dict], preview: dict | None, is_admin: bool, message: str = "", error: bool = False):
    status = graph_db.health()
    blocks = [
        _title("Ontologies", "Import versioned JSON/YAML property graphs into optional Neo4j storage."),
        Div(Div(message, cls="sql-result-err" if error else "callout"), cls="card") if message else None,
        graph_status_card(),
    ]
    if is_admin:
        blocks.append(
            Div(
                Div(H3("1. Validate and stage an ontology"), cls="card-header"),
                Form(
                    Input(type="file", name="ontology", accept=".json,.yaml,.yml,application/json,text/yaml", required=True),
                    Button("Preview import", type="submit", cls="btn primary"),
                    method="post", action="/ontologies/preview", enctype="multipart/form-data",
                    style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;",
                ),
                P("Maximum 2 MB · 5,000 nodes · 10,000 relationships. Values must be scalar or scalar lists.", cls="sub"),
                cls="card",
            )
        )
    else:
        blocks.append(Div(P("Ontology imports are restricted to graph administrators."), cls="card"))

    if preview:
        payload = json.loads(preview["payload_json"])
        blocks.append(
            Div(
                Div(H3("2. Review staged import"), Span("Validated", cls="pill line"), cls="card-header"),
                P(f"{payload['ontology']['name']} · version {payload['ontology']['version']}"),
                P(f"{len(payload['nodes'])} nodes · {len(payload['edges'])} relationships · SHA-256 {preview['content_hash'][:12]}…", cls="sub"),
                Form(Button("Apply to Neo4j", type="submit", cls="btn primary"),
                     method="post", action=f"/ontologies/{preview['id']}/apply"),
                cls="card",
            )
        )

    rows = []
    for item in imports:
        actions = []
        if is_admin and item["status"] == "active":
            actions.append(Form(Button("Rollback", type="submit", cls="btn sm"), method="post",
                                action=f"/ontologies/{item['id']}/rollback", style="display:inline"))
        rows.append(Tr(
            Td(item["name"]), Td(item["ontology_id"]), Td(item["version"]),
            Td(Span(item["status"], cls="pill line" if item["status"] == "active" else "pill")),
            Td(item["created_by"]), Td(*actions),
        ))
    blocks.append(
        Div(Div(H3("Import history"), cls="card-header"),
            Table(Thead(Tr(Th("Ontology"), Th("ID"), Th("Version"), Th("Status"), Th("Imported by"), Th(""))),
                  Tbody(*rows), cls="tbl") if rows else P("No ontology imports yet.", cls="sub"), cls="card")
    )
    return tuple(block for block in blocks if block is not None)


def cypher_lab(default: str = "MATCH (a:OntologyNode)-[r]->(b:OntologyNode) RETURN a,r,b LIMIT 50"):
    try:
        schema_text = graph_db.schema_prompt()
    except graph_db.GraphError as exc:
        schema_text = str(exc)
    return (
        _title("Cypher Lab + Ask AI", "Run guarded read-only Cypher, or describe a relationship question."),
        Div(
            Div(H3("Ask the graph in plain English"), cls="card-header"),
            Form(Input(name="question", cls="askbox", placeholder="e.g. which metrics measure an order?", autocomplete="off"),
                 Button("Generate Cypher & run", cls="btn primary", type="submit", style="margin-top:8px;"),
                 hx_post="/cypher/ask", hx_target="#cypher-result", hx_swap="innerHTML",
                 **{"hx-indicator": "#cypher-generation-progress"}),
            generation_progress("cypher-generation-progress", "Reading the ontology and generating safe Cypher…",
                                "The interactive graph will appear when ready."),
            cls="card",
        ),
        Div(Div(H3("Cypher"), cls="card-header"),
            Form(Textarea(default, name="cypher", cls="sqlbox", spellcheck="false"),
                 Button("Run", cls="btn primary", type="submit", style="margin-top:8px;"),
                 hx_post="/cypher/run", hx_target="#cypher-result", hx_swap="innerHTML"), cls="card"),
        Div(Div(H3("Graph schema"), cls="card-header"), Pre(schema_text, style="white-space:pre-wrap;margin:0;font-size:12px;"), cls="card"),
        Div(id="cypher-result"),
    )


def _table_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def cypher_result(result: graph_db.GraphResult, note: str = ""):
    rows = [Tr(*[Td(_table_value(value)) for value in row]) for row in result.rows]
    blocks = []
    if note:
        blocks.append(Div(note, cls="callout",
                          style="background:var(--accent-light);border-left:4px solid var(--accent);color:var(--accent-hover);padding:10px 14px;border-radius:8px;margin-bottom:12px;"))
    blocks.append(Div(Div(H3("Read-only Cypher"), cls="card-header"),
                      Pre(Code(result.cypher), style="white-space:pre-wrap;margin:0;background:#0f172a;color:#e2e8f0;padding:12px;border-radius:8px;"), cls="card"))
    if result.nodes:
        blocks.append(Div(Div(H3("Interactive graph"), Span(f"{len(result.nodes)} nodes · {len(result.edges)} relationships", cls="pill"), cls="card-header"),
                          *_network({"nodes": result.nodes, "edges": result.edges}, "cypher-network", "480px"), cls="card"))
    blocks.append(Div(Div(H3("Result"), cls="card-header"),
                      Table(Thead(Tr(*[Th(column) for column in result.columns])), Tbody(*rows), cls="tbl")
                      if result.columns else P("No columns returned."), cls="card"))
    return Div(*blocks)


def cypher_error(message: str):
    return Div(Div(f"⚠ {message}", cls="sql-result-err"), cls="card")
