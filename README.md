# AI Background Worker Platform

A backend platform for submitting, queuing, and processing AI background jobs — including **advanced RAG**: multi-query expansion, metadata-filtered retrieval, cross-encoder reranking, and small-to-big parent context. Docker Compose runs the API with pgvector Postgres and per-type Celery workers.

## Architecture

```
docker compose up
  │
  ├── postgres (pgvector) / redis
  ├── api :8000
  │      POST /documents/ingest  → parent+child chunks + ingestion job
  │      POST /rag/query         → inline rag_query  OR  Celery chain (use_chain)
  │      POST /rag/query/sync    → inline advanced pipeline
  ├── worker-summarization … recommendations
  ├── worker-ingestion           --queues=ingestion
  └── worker-rag-query           --queues=rag_query
         expand → retrieve → rerank → generate (inline or chain on same queue)
```

## Features

- **Advanced RAG pipeline** — multi-query expand, `metadata_filter`, cross-encoder rerank, small-to-big parent expansion
- **Retrieve vs keep** — `retrieve_k` candidate pool and `keep_top_n` after rerank (defaults on for sync/async)
- **Optional Celery chain** — `use_chain: true` on `POST /rag/query` runs expand → retrieve → rerank → generate as step jobs
- **RAG observability** — per-step timings and quality signals in `result_payload.observability`
- **Document ingest** — parent/child chunking into pgvector; `GET /documents/{id}/chunks` exposes `level` / `parent_chunk_id`
- **Job platform** — async FastAPI, uploads, rate limiting, admin controls (Compose-first for RAG)

## Quick start

**Prerequisites:** Docker Desktop (or Docker Engine + Compose)

```bash
cd ai-background-worker-platform
docker compose up --build
```

- API: `http://localhost:8000` · Docs: `/docs` · Examples: [`API_COLLECTION.md`](API_COLLECTION.md)
- Existing Postgres volumes may need: `init-db/02-stage14-jobtype-enum.sql`

```bash
curl -X POST http://localhost:8000/documents/ingest \
  -H "Content-Type: application/json" \
  -d '{"title":"Demo","content":"Asyncio lets you write concurrent Python with async/await."}'

curl -X POST http://localhost:8000/rag/query/sync \
  -H "Content-Type: application/json" \
  -d '{"question":"What is asyncio?","retrieve_k":50,"keep_top_n":3}'

curl -X POST http://localhost:8000/rag/query \
  -H "Content-Type: application/json" \
  -d '{"question":"What is asyncio?","use_chain":true}'
```

Stop with `docker compose down` (add `-v` to remove volumes). Run `pytest` for tests.

## Evolution

Naive RAG added ingest, pgvector retrieval, and a single-pass query worker. This release **advances the RAG path** — expand, filter, rerank, small-to-big context, metrics, and an optional Celery chain — so answers use a larger candidate pool and better-ranked evidence.
