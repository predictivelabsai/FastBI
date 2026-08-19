"""Configurable retrieval and evaluation for PostgreSQL, FAISS, and Neo4j GraphRAG."""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

SCHEMA = "fastbi_rag"
ROOT = Path(__file__).resolve().parent


class RAGError(RuntimeError):
    pass


@dataclass
class Hit:
    chunk_id: str
    document_id: str
    title: str
    content: str
    source_uri: str
    score: float
    metadata: dict[str, Any]


def config() -> dict[str, Any]:
    return {
        "embedding_provider": os.getenv("FASTBI_RAG_EMBEDDING_PROVIDER", "openai"),
        "embedding_model": os.getenv("FASTBI_RAG_EMBEDDING_MODEL", "text-embedding-3-small"),
        "embedding_dimensions": int(os.getenv("FASTBI_RAG_EMBEDDING_DIMENSIONS", "1536")),
        "chunk_size": int(os.getenv("FASTBI_RAG_CHUNK_SIZE", "1200")),
        "chunk_overlap": int(os.getenv("FASTBI_RAG_CHUNK_OVERLAP", "150")),
        "top_k": int(os.getenv("FASTBI_RAG_TOP_K", "6")),
        "faiss_path": os.getenv("FASTBI_RAG_FAISS_PATH", str(ROOT / "data" / "fastbi-rag.faiss")),
    }


def _dsn() -> str:
    value = os.getenv("DATABASE_URL_PROD") or os.getenv("DATABASE_URL") or ""
    if not value:
        raise RAGError("Set DATABASE_URL_PROD to enable RAG storage.")
    return value


def _connect():
    try:
        import psycopg
        from pgvector.psycopg import register_vector
        conn = psycopg.connect(_dsn(), connect_timeout=8)
        # A first-run connection may precede CREATE EXTENSION vector.
        try:
            register_vector(conn)
        except (psycopg.errors.UndefinedObject, psycopg.ProgrammingError) as exc:
            if "vector type not found" not in str(exc).lower() and not isinstance(exc, psycopg.errors.UndefinedObject):
                raise
            conn.rollback()
        return conn
    except Exception as exc:
        raise RAGError(f"PostgreSQL connection failed ({type(exc).__name__}).") from exc


def ensure_schema() -> None:
    dim = config()["embedding_dimensions"]
    if not 1 <= dim <= 4096:
        raise RAGError("FASTBI_RAG_EMBEDDING_DIMENSIONS must be between 1 and 4096.")
    ddl = f"""
    CREATE SCHEMA IF NOT EXISTS {SCHEMA};
    CREATE TABLE IF NOT EXISTS {SCHEMA}.documents (
      id uuid PRIMARY KEY, source_type text NOT NULL, source_uri text NOT NULL UNIQUE,
      title text NOT NULL, content_hash text NOT NULL, metadata jsonb NOT NULL DEFAULT '{{}}',
      indexed_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE TABLE IF NOT EXISTS {SCHEMA}.chunks (
      id uuid PRIMARY KEY, document_id uuid NOT NULL REFERENCES {SCHEMA}.documents(id) ON DELETE CASCADE,
      ordinal integer NOT NULL, content text NOT NULL, content_hash text NOT NULL,
      metadata jsonb NOT NULL DEFAULT '{{}}', embedding double precision[],
      UNIQUE(document_id, ordinal)
    );
    CREATE INDEX IF NOT EXISTS fastbi_rag_chunks_document ON {SCHEMA}.chunks(document_id);
    CREATE TABLE IF NOT EXISTS {SCHEMA}.conversations (
      id uuid PRIMARY KEY, created_by text NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE TABLE IF NOT EXISTS {SCHEMA}.messages (
      id uuid PRIMARY KEY, conversation_id uuid NOT NULL REFERENCES {SCHEMA}.conversations(id) ON DELETE CASCADE,
      role text NOT NULL CHECK (role IN ('user','assistant')), content text NOT NULL,
      approach text, evidence jsonb NOT NULL DEFAULT '[]', created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE TABLE IF NOT EXISTS {SCHEMA}.eval_datasets (
      id uuid PRIMARY KEY, name text NOT NULL, synthetic boolean NOT NULL DEFAULT true,
      created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE TABLE IF NOT EXISTS {SCHEMA}.eval_cases (
      id uuid PRIMARY KEY, dataset_id uuid NOT NULL REFERENCES {SCHEMA}.eval_datasets(id) ON DELETE CASCADE,
      question text NOT NULL, reference_answer text NOT NULL, expected_chunk_ids uuid[] NOT NULL DEFAULT '{{}}',
      metadata jsonb NOT NULL DEFAULT '{{}}'
    );
    CREATE TABLE IF NOT EXISTS {SCHEMA}.eval_runs (
      id uuid PRIMARY KEY, dataset_id uuid NOT NULL REFERENCES {SCHEMA}.eval_datasets(id),
      configuration jsonb NOT NULL, started_at timestamptz NOT NULL DEFAULT now(), completed_at timestamptz
    );
    CREATE TABLE IF NOT EXISTS {SCHEMA}.eval_results (
      id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES {SCHEMA}.eval_runs(id) ON DELETE CASCADE,
      case_id uuid NOT NULL REFERENCES {SCHEMA}.eval_cases(id), approach text NOT NULL,
      answer text NOT NULL, retrieved_chunk_ids uuid[] NOT NULL DEFAULT '{{}}', metrics jsonb NOT NULL,
      latency_ms integer NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
    );
    """
    with _connect() as conn:
        conn.execute(ddl)


def health() -> dict[str, Any]:
    state = {"configured": bool(os.getenv("DATABASE_URL_PROD") or os.getenv("DATABASE_URL")), **config()}
    if not state["configured"]:
        return state
    try:
        with _connect() as conn:
            exists = conn.execute("SELECT to_regclass('fastbi_rag.chunks')").fetchone()[0]
            pgvector = conn.execute("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname='vector')").fetchone()[0]
            count = conn.execute(f"SELECT count(*) FROM {SCHEMA}.chunks").fetchone()[0] if exists else 0
        state.update({"connected": True, "chunks": count, "postgres_vector_backend": "pgvector" if pgvector else "native-array-cosine"})
    except Exception as exc:
        state.update({"connected": False, "error": type(exc).__name__})
    return state


def chunk_text(text: str) -> list[str]:
    cfg = config(); size, overlap = cfg["chunk_size"], cfg["chunk_overlap"]
    text = re.sub(r"\n{3,}", "\n\n", text.strip())
    if not text: return []
    chunks, start = [], 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            boundary = max(text.rfind("\n", start, end), text.rfind(". ", start, end))
            if boundary > start + size // 2: end = boundary + 1
        chunks.append(text[start:end].strip())
        if end >= len(text): break
        start = max(start + 1, end - overlap)
    return chunks


def embed(texts: list[str]) -> np.ndarray:
    cfg = config(); provider, dim = cfg["embedding_provider"], cfg["embedding_dimensions"]
    if provider == "hash":
        vectors = np.zeros((len(texts), dim), dtype="float32")
        for row, text in enumerate(texts):
            for token in re.findall(r"[a-z0-9]+", text.lower()):
                digest = hashlib.sha256(token.encode()).digest()
                vectors[row, int.from_bytes(digest[:4], "big") % dim] += 1 if digest[4] & 1 else -1
    elif provider == "openai":
        import httpx
        key = os.getenv("OPENAI_API_KEY", "")
        if not key: raise RAGError("Set OPENAI_API_KEY to build or query the RAG indexes.")
        response = httpx.post("https://api.openai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": cfg["embedding_model"], "input": texts, "dimensions": dim}, timeout=90)
        response.raise_for_status()
        vectors = np.asarray([x["embedding"] for x in response.json()["data"]], dtype="float32")
    else:
        raise RAGError(f"Unsupported embedding provider: {provider}.")
    norms = np.linalg.norm(vectors, axis=1, keepdims=True); norms[norms == 0] = 1
    return vectors / norms


def _repo_documents() -> list[dict[str, Any]]:
    paths = [ROOT / "README.md", ROOT / "docs" / "GRAPH_DB.md", ROOT / "docs" / "ROADMAP.md",
             *sorted((ROOT / "examples").glob("*.yaml"))]
    return [{"source_type": "repository", "source_uri": f"repo:{p.relative_to(ROOT)}",
             "title": p.name, "content": p.read_text(errors="replace"), "metadata": {"path": str(p.relative_to(ROOT))}}
            for p in paths if p.is_file()]


def _database_documents(max_tables: int = 40, sample_rows: int = 20) -> list[dict[str, Any]]:
    docs = []
    with _connect() as conn:
        tables = conn.execute("""SELECT table_schema,table_name FROM information_schema.tables
          WHERE table_type='BASE TABLE' AND table_schema NOT IN ('pg_catalog','information_schema','fastbi_rag')
          ORDER BY table_schema,table_name LIMIT %s""", (max_tables,)).fetchall()
        for schema, table in tables:
            cols = conn.execute("""SELECT column_name,data_type FROM information_schema.columns
              WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position""", (schema, table)).fetchall()
            safe_schema, safe_table = '"' + schema.replace('"','""') + '"', '"' + table.replace('"','""') + '"'
            rows = conn.execute(f"SELECT * FROM {safe_schema}.{safe_table} LIMIT %s", (sample_rows,)).fetchall()
            names = [d.name for d in conn.execute(f"SELECT * FROM {safe_schema}.{safe_table} LIMIT 0").description]
            content = f"PostgreSQL table {schema}.{table}\nColumns: " + ", ".join(f"{a} {b}" for a,b in cols)
            content += "\nSample rows:\n" + "\n".join(json.dumps(dict(zip(names, row)), default=str) for row in rows)
            docs.append({"source_type":"postgresql", "source_uri":f"postgresql:{schema}.{table}",
                         "title":f"{schema}.{table}", "content":content, "metadata":{"schema":schema,"table":table}})
    return docs


def rebuild(include_database: bool = True) -> dict[str, int]:
    ensure_schema(); documents = _repo_documents() + (_database_documents() if include_database else [])
    inserted = chunks_total = 0
    with _connect() as conn:
        for doc in documents:
            digest = hashlib.sha256(doc["content"].encode()).hexdigest(); doc_id = uuid.uuid5(uuid.NAMESPACE_URL, doc["source_uri"])
            existing = conn.execute(f"SELECT content_hash FROM {SCHEMA}.documents WHERE id=%s", (doc_id,)).fetchone()
            if existing and existing[0] == digest: continue
            parts = chunk_text(doc["content"]); vectors = embed(parts) if parts else []
            conn.execute(f"""INSERT INTO {SCHEMA}.documents(id,source_type,source_uri,title,content_hash,metadata,indexed_at)
              VALUES(%s,%s,%s,%s,%s,%s,now()) ON CONFLICT(id) DO UPDATE SET title=excluded.title,
              content_hash=excluded.content_hash,metadata=excluded.metadata,indexed_at=now()""",
              (doc_id,doc["source_type"],doc["source_uri"],doc["title"],digest,json.dumps(doc["metadata"])))
            conn.execute(f"DELETE FROM {SCHEMA}.chunks WHERE document_id=%s", (doc_id,))
            for i, (part, vector) in enumerate(zip(parts, vectors)):
                chunk_id = uuid.uuid5(doc_id, str(i)); chash = hashlib.sha256(part.encode()).hexdigest()
                conn.execute(f"INSERT INTO {SCHEMA}.chunks(id,document_id,ordinal,content,content_hash,metadata,embedding) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                             (chunk_id,doc_id,i,part,chash,json.dumps(doc["metadata"]),vector.tolist()))
            inserted += 1; chunks_total += len(parts)
    build_faiss()
    return {"documents": inserted, "chunks": chunks_total}


def _row_hit(row) -> Hit:
    return Hit(str(row[0]), str(row[1]), row[2], row[3], row[4], float(row[5]), row[6] or {})


def search_postgres(question: str, k: int | None = None) -> list[Hit]:
    vector = embed([question])[0]; k = k or config()["top_k"]
    with _connect() as conn:
        rows = conn.execute(f"""SELECT c.id,c.document_id,d.title,c.content,d.source_uri,
          (SELECT sum(e*v)/NULLIF(sqrt(sum(e*e))*sqrt(sum(v*v)),0)
             FROM unnest(c.embedding) WITH ORDINALITY a(e,i)
             JOIN unnest(%s::double precision[]) WITH ORDINALITY b(v,j) ON i=j) score,
          c.metadata FROM {SCHEMA}.chunks c JOIN {SCHEMA}.documents d ON d.id=c.document_id
          WHERE c.embedding IS NOT NULL ORDER BY score DESC NULLS LAST LIMIT %s""", (vector.tolist(),k)).fetchall()
    return [_row_hit(row) for row in rows]


def build_faiss() -> int:
    import faiss
    path = Path(config()["faiss_path"]); path.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        rows = conn.execute(f"SELECT id,embedding FROM {SCHEMA}.chunks WHERE embedding IS NOT NULL ORDER BY id").fetchall()
    vectors = np.asarray([np.asarray(r[1], dtype="float32") for r in rows], dtype="float32")
    index = faiss.IndexFlatIP(config()["embedding_dimensions"])
    if len(vectors): index.add(vectors)
    faiss.write_index(index, str(path)); path.with_suffix(path.suffix + ".json").write_text(json.dumps([str(r[0]) for r in rows]))
    return len(rows)


def search_faiss(question: str, k: int | None = None) -> list[Hit]:
    import faiss
    path = Path(config()["faiss_path"]); meta = path.with_suffix(path.suffix + ".json")
    if not path.exists() or not meta.exists(): build_faiss()
    ids = json.loads(meta.read_text()); index = faiss.read_index(str(path)); k = min(k or config()["top_k"], len(ids))
    if not k: return []
    scores, positions = index.search(embed([question]), k); selected = [(ids[p], float(s)) for p,s in zip(positions[0],scores[0]) if p >= 0]
    with _connect() as conn:
        found = {str(r[0]): r for r in conn.execute(f"""SELECT c.id,c.document_id,d.title,c.content,d.source_uri,0,c.metadata
          FROM {SCHEMA}.chunks c JOIN {SCHEMA}.documents d ON d.id=c.document_id WHERE c.id=ANY(%s::uuid[])""", ([x[0] for x in selected],)).fetchall()}
    return [Hit(str(found[c][0]),str(found[c][1]),found[c][2],found[c][3],found[c][4],score,found[c][6] or {}) for c,score in selected if c in found]


def search_graphrag(question: str, k: int | None = None) -> tuple[list[Hit], str]:
    hits = search_postgres(question, k); terms = sorted(set(re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", question)))[:12]
    graph_context = ""
    try:
        import graph_db
        result = graph_db.run_cypher("MATCH (n:OntologyNode) WHERE any(term IN $terms WHERE toLower(n.label) CONTAINS toLower(term)) OPTIONAL MATCH p=(n)-[*1..2]-(m:OntologyNode) RETURN n,p,m LIMIT 40", {"terms":terms})
        graph_context = json.dumps({"rows": result.rows, "nodes": result.nodes, "edges": result.edges}, ensure_ascii=False)[:12000]
    except Exception as exc:
        graph_context = f"Graph enrichment unavailable ({type(exc).__name__})."
    return hits, graph_context


def answer(question: str, approach: str = "graphrag") -> dict[str, Any]:
    started = time.perf_counter(); approach = approach.lower()
    if approach == "postgres": hits, graph = search_postgres(question), ""
    elif approach == "faiss": hits, graph = search_faiss(question), ""
    elif approach == "graphrag": hits, graph = search_graphrag(question)
    else: raise RAGError("Approach must be graphrag, postgres, or faiss.")
    context = "\n\n".join(f"[source:{h.chunk_id}] {h.title}\n{h.content}" for h in hits)
    system = """Answer only from the supplied evidence. Cite factual claims as [source:UUID].
If evidence is insufficient, say so. Be concise and do not invent facts."""
    if graph: context += "\n\nNEO4J GRAPH CONTEXT:\n" + graph
    from web.ai import _complete
    text = _complete(system + "\n\nEVIDENCE:\n" + context, question)
    return {"answer":text, "approach":approach, "hits":[asdict(h) for h in hits],
            "latency_ms":round((time.perf_counter()-started)*1000)}


def generate_benchmark(limit: int = 12) -> dict[str, Any]:
    ensure_schema(); dataset_id = uuid.uuid4()
    with _connect() as conn:
        rows = conn.execute(f"SELECT c.id,d.title,c.content FROM {SCHEMA}.chunks c JOIN {SCHEMA}.documents d ON d.id=c.document_id ORDER BY random() LIMIT %s", (limit,)).fetchall()
        conn.execute(f"INSERT INTO {SCHEMA}.eval_datasets(id,name,synthetic) VALUES(%s,%s,true)", (dataset_id,"Synthetic benchmark"))
        for chunk_id,title,content in rows:
            sentence = next((s.strip() for s in re.split(r"(?<=[.!?])\s+",content) if len(s.strip()) > 30), content[:300])
            question = f"What does the indexed source {title} say about {sentence.split()[0:5]}?".replace("['", "").replace("']", "").replace("', '", " ")
            conn.execute(f"INSERT INTO {SCHEMA}.eval_cases(id,dataset_id,question,reference_answer,expected_chunk_ids,metadata) VALUES(%s,%s,%s,%s,%s,%s)",
                         (uuid.uuid4(),dataset_id,question,sentence,[chunk_id],json.dumps({"synthetic":True,"source_title":title})))
    return {"dataset_id":str(dataset_id),"cases":len(rows),"synthetic":True}


def run_evaluation(dataset_id: str) -> dict[str, Any]:
    run_id = uuid.uuid4(); approaches = ("graphrag","postgres","faiss")
    with _connect() as conn:
        cases = conn.execute(f"SELECT id,question,reference_answer,expected_chunk_ids FROM {SCHEMA}.eval_cases WHERE dataset_id=%s", (dataset_id,)).fetchall()
        conn.execute(f"INSERT INTO {SCHEMA}.eval_runs(id,dataset_id,configuration) VALUES(%s,%s,%s)", (run_id,dataset_id,json.dumps(config())))
    totals = {a:[] for a in approaches}
    for case_id,question,reference,expected in cases:
        for approach in approaches:
            result = answer(question, approach); retrieved = [h["chunk_id"] for h in result["hits"]]
            expected_s = {str(x) for x in expected}; recall = len(expected_s & set(retrieved))/max(1,len(expected_s))
            ref_terms = set(re.findall(r"\w+",reference.lower())); ans_terms = set(re.findall(r"\w+",result["answer"].lower()))
            similarity = len(ref_terms & ans_terms)/max(1,len(ref_terms | ans_terms))
            metrics = {"retrieval_recall_at_k":recall,"answer_token_jaccard":similarity,"citation_count":result["answer"].count("[source:")}
            totals[approach].append(metrics)
            with _connect() as conn:
                conn.execute(f"INSERT INTO {SCHEMA}.eval_results(id,run_id,case_id,approach,answer,retrieved_chunk_ids,metrics,latency_ms) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                             (uuid.uuid4(),run_id,case_id,approach,result["answer"],retrieved,json.dumps(metrics),result["latency_ms"]))
    with _connect() as conn: conn.execute(f"UPDATE {SCHEMA}.eval_runs SET completed_at=now() WHERE id=%s", (run_id,))
    summary = {a:{k:round(sum(m[k] for m in values)/len(values),3) for k in values[0]} if values else {} for a,values in totals.items()}
    return {"run_id":str(run_id),"cases":len(cases),"summary":summary}
