# AI Background Worker Platform

A backend platform for submitting, queuing, and processing AI background jobs — including **naive RAG**: ingest documents into Postgres + pgvector, retrieve top-K chunks, and generate answers from context. Docker Compose runs the API with seven per-type Celery workers.

## Architecture

```
docker compose up
  │
  ├── postgres (pgvector) / redis
  ├── api :8000
  │      POST /documents/ingest  → Document + ingestion job
  │      POST /rag/query         → rag_query job (poll GET /jobs/{id})
  │      POST /rag/query/sync    → answer inline
  ├── worker-summarization … recommendations
  ├── worker-ingestion           --queues=ingestion
  └── worker-rag-query           --queues=rag_query
         same image · WORKER_TYPE + --queues=<type>
```

## Features

- **Document ingest** — `POST /documents/ingest`; chunk, embed, store in `documents` / `chunks` / `chunk_embeddings`
- **pgvector retrieval** — cosine top-K search with HNSW; answer generation from retrieved context
- **RAG APIs** — async `POST /rag/query` (job + poll) and sync `POST /rag/query/sync` (inline answer)
- **Dedicated workers** — `worker-ingestion` and `worker-rag-query` alongside existing job-type workers
- **Shared image** — one Docker image; Postgres via `pgvector/pgvector:pg16` + `init-db/`
- **Job platform** — async FastAPI, uploads, rate limiting, admin observability (Compose-first for RAG)

## Quick start

**Prerequisites:** Docker Desktop (or Docker Engine + Compose)

```bash
cd ai-background-worker-platform
docker compose up --build
```

- API: `http://localhost:8000` · Docs: `/docs` · Examples: [`API_COLLECTION.md`](API_COLLECTION.md)

```bash
curl -X POST http://localhost:8000/documents/ingest \
  -H "Content-Type: application/json" \
  -d '{"title":"Demo","content":"Asyncio lets you write concurrent Python with async/await."}'

curl -X POST http://localhost:8000/rag/query/sync \
  -H "Content-Type: application/json" \
  -d '{"question":"What is asyncio?","top_k":5}'
```

Stop with `docker compose down` (add `-v` to remove volumes). Run `pytest` for tests.

## Evolution

Kubernetes packaged the per-type worker topology for cluster deploy. This release **adds naive RAG on Compose** — pgvector storage, ingestion and rag_query workers, and ingest/query APIs — so the platform can answer questions from a document knowledge base.
