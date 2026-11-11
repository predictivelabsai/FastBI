# FastBI changelog

## 0.2.1 — 2026-11-11

- Gate AI chat, SQL Ask, Cypher Ask, and GraphRAG like mybritain.chat: 3 free guest questions on the server key, persistent IP quota, rate limits, then sign-in plus a bring-your-own xAI key. Allowlisted admin emails may keep using the server key.
- Show a small API-key panel on the AI Assistant page and a version chip in the top bar. Anonymous visitors can use `/ai` for the free allowance.


## 0.2.0 — 2026-08-19

- Add GraphRAG Chat with Neo4j-enriched, PostgreSQL vector, FAISS, and comparison modes.
- Add isolated `fastbi_rag` storage, repository/database ingestion, OpenAI embeddings, and persisted FAISS indexes.
- Add synthetic three-approach evaluation datasets, runs, accuracy metrics, citations, and latency reporting.
- Add Docker and Coolify configuration for the RAG database, embedding model, and FAISS persistence.
- Report RAG configuration and index health from `/healthz`.
