"""FastHTML views for GraphRAG chat and comparative evaluations."""
from __future__ import annotations

import json
from fasthtml.common import Button, Code, Div, Form, H2, H3, Input, NotStr, Option, P, Pre, Select, Span, Table, Tbody, Td, Th, Thead, Tr

import rag


def workspace(message: str = "", error: bool = False):
    state = rag.health()
    status = "Connected" if state.get("connected") else ("Not initialized" if state.get("configured") else "Not configured")
    return (
        Div(Div(H2("GraphRAG Chat"), P("Compare graph-enriched, pgvector, and local FAISS retrieval over the same evidence.", cls="sub")),
            Span(status, cls="pill line" if state.get("connected") else "pill"), cls="page-title"),
        Div(message, cls="sql-result-err" if error else "callout") if message else None,
        Div(
            Div(H3("Ask indexed knowledge"), Span(f"{state.get('chunks', 0)} chunks", cls="pill"), cls="card-header"),
            Form(
                Input(name="question", cls="askbox", placeholder="Ask about the database, documentation, or ontology…", required=True, autocomplete="off"),
                Div(Select(Option("GraphRAG", value="graphrag"), Option("PostgreSQL vector", value="postgres"),
                           Option("FAISS", value="faiss"), Option("Compare all", value="compare"), name="approach", cls="chat-mode"),
                    Button("Ask", type="submit", cls="btn primary"), style="display:flex;gap:8px;margin-top:10px;"),
                hx_post="/graphrag/ask", hx_target="#rag-answer", hx_swap="innerHTML",
            ), cls="card"),
        Div(id="rag-answer"),
        Div(Div(H3("Index and evaluations"), cls="card-header"),
            P(f"Embedding: {state.get('embedding_model')} · PostgreSQL: {state.get('postgres_vector_backend', 'not initialized')} · top K {state.get('top_k')} · isolated schema fastbi_rag", cls="sub"),
            Div(Form(Button("Rebuild indexes", cls="btn", type="submit"), method="post", action="/graphrag/rebuild"),
                Form(Button("Generate synthetic benchmark", cls="btn", type="submit"), method="post", action="/graphrag/evals/generate"),
                style="display:flex;gap:8px;flex-wrap:wrap;"), cls="card"),
    )


def _one_result(result: dict):
    hits = result.get("hits", [])
    rows = [Tr(Td(hit["title"]), Td(f"{hit['score']:.3f}"), Td(Code(hit["chunk_id"][:12] + "…")),
               Td(hit["content"][:180] + ("…" if len(hit["content"]) > 180 else ""))) for hit in hits]
    return Div(
        Div(H3(result["approach"].replace("graphrag", "GraphRAG").title()), Span(f"{result['latency_ms']} ms", cls="pill"), cls="card-header"),
        Div(data_markdown=result["answer"], cls="msg-content"),
        Table(Thead(Tr(Th("Source"), Th("Score"), Th("Chunk"), Th("Evidence"))), Tbody(*rows), cls="tbl") if rows else P("No evidence retrieved."),
        cls="card")


def answer_results(results: list[dict]):
    return Div(*[_one_result(item) for item in results], ScriptMarkdown())


def ScriptMarkdown():
    from fasthtml.common import Script
    return Script("document.querySelectorAll('#rag-answer [data-markdown]').forEach(function(e){e.innerHTML=marked.parse(e.dataset.markdown||'')})")


def evaluation_result(result: dict):
    summary = result.get("summary", {})
    metrics = sorted({key for values in summary.values() for key in values})
    rows = [Tr(Td(name), *[Td(str(values.get(metric, ""))) for metric in metrics]) for name, values in summary.items()]
    return Div(Div(H3("Comparative evaluation"), Span(f"{result.get('cases', 0)} cases", cls="pill"), cls="card-header"),
               Table(Thead(Tr(Th("Approach"), *[Th(m.replace("_", " ").title()) for m in metrics])), Tbody(*rows), cls="tbl"),
               Pre(json.dumps({"run_id": result.get("run_id")}, indent=2)), cls="card")
