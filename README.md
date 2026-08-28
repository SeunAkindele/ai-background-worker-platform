# AI Background Worker Platform

A backend platform for submitting, queuing, and processing AI background jobs — including **modular RAG**: routing, self-correction, evaluation metrics, and MCP web search on top of advanced retrieval (multi-query, rerank, small-to-big). Docker Compose runs the API with pgvector Postgres and per-type Celery workers.

## Architecture

```
docker compose up
  │
  ├── postgres (pgvector) / redis
  ├── mcp-web :8080                POST /mcp  (web_search via Wikipedia)
  ├── api :8000
  │      POST /documents/ingest     → parent+child chunks + ingestion job
  │      POST /rag/query            → inline rag_query OR Celery chain (use_chain)
  │      POST /rag/query/sync       → full pipeline in one response
  │      GET  /admin/rag/dashboard  → Stage 15 metrics (triad, routes, critic)
  ├── worker-summarization … recommendations
  ├── worker-ingestion              --queues=ingestion
  └── worker-rag-query              --queues=rag_query
         Stage 15 (flags on RAG request):
           router → cache | vector | sql | web(MCP)
           vector → expand → retrieve → rerank → s2b → generate
           critic loop → optional re-retrieve
           eval → rag_query_metrics
```

## Features

- **Advanced RAG (Stage 14)** — multi-query expand, `metadata_filter`, cross-encoder rerank, small-to-big parent expansion
- **Modular RAG (Stage 15)** — `use_router` (cache/vector/sql/web), `use_critic` self-correction, `use_eval` RAG triad, MCP client for web route
- **Retrieve vs keep** — `retrieve_k` candidate pool and `keep_top_n` after rerank
- **Optional Celery chain** — `use_chain: true` on `POST /rag/query` runs expand → retrieve → rerank → generate as step jobs
- **RAG observability** — per-step timings in `result_payload.observability`; admin dashboard at `/admin/rag/dashboard`
- **Document ingest** — parent/child chunking into pgvector; `GET /documents/{id}/chunks` exposes `level` / `parent_chunk_id`
- **Job platform** — async FastAPI, uploads, rate limiting, admin controls
- **Kubernetes** — Compose-parity workers (including ingestion + RAG), pgvector Postgres, `mcp-web`, NodePort `30080`

## Quick start

**Prerequisites:** Docker Desktop (or Docker Engine + Compose)

```bash
cd ai-background-worker-platform
docker compose up --build
```

- API: `http://localhost:8000` · Docs: `/docs` · OpenAPI: [`openapi.json`](openapi.json) · Examples: [`API_COLLECTION.md`](API_COLLECTION.md)
- **Existing Postgres volumes** may need (run once each):

```bash
docker compose exec -T postgres psql -U postgres -d ai_worker_platform < init-db/02-stage14-jobtype-enum.sql
docker compose exec -T postgres psql -U postgres -d ai_worker_platform < init-db/03-stage15-chunk-hierarchy.sql
docker compose exec -T postgres psql -U postgres -d ai_worker_platform < init-db/04-stage15-modular-rag.sql
```

### Stage 14 — ingest + advanced RAG

```bash
curl -X POST http://localhost:8000/documents/ingest \
  -H "Content-Type: application/json" \
  -d '{"title":"Demo","content":"Asyncio lets you write concurrent Python with async/await."}'

curl -X POST http://localhost:8000/rag/query/sync \
  -H "Content-Type: application/json" \
  -d '{"question":"What is asyncio?","retrieve_k":50,"keep_top_n":3}'
```

### Stage 15 — modular RAG

```bash
# Router + critic + eval (sync demo)
curl -X POST http://localhost:8000/rag/query/sync \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What is asyncio?",
    "use_router": true,
    "use_critic": true,
    "use_eval": true
  }'

# SQL route (ops metrics from jobs table)
curl -X POST http://localhost:8000/rag/query/sync \
  -H "Content-Type: application/json" \
  -d '{"question":"How many pending jobs?","use_router":true,"force_route":"sql"}'

# Web route (Compose mcp-web → Wikipedia; needs outbound HTTPS)
curl -X POST http://localhost:8000/rag/query/sync \
  -H "Content-Type: application/json" \
  -d '{"question":"What is the latest news about AI?","use_router":true,"force_route":"web"}'

# RAG admin dashboard (after queries with use_eval)
curl "http://localhost:8000/admin/rag/dashboard?window_hours=24&slow_k=5"
```

Compose starts `mcp-web` on port 8080 (`POST /mcp`). API and workers use `MCP_WEB_URL=http://mcp-web:8080/mcp`. For local (non-Docker) API, point `MCP_WEB_URL` at `http://localhost:8080/mcp`.

Stop with `docker compose down` (add `-v` to remove volumes). Run `pytest` for tests.

## Kubernetes

Manifests in `infra/kubernetes/` match Compose: pgvector Postgres, Redis, MCP web search, API, seven workers (summarization, embeddings, OCR, transcription, recommendations, ingestion, RAG), and HPAs.

```bash
docker build -t ai-worker-platform:latest .

# Kind
kind load docker-image ai-worker-platform:latest

# Minikube
minikube image load ai-worker-platform:latest

kubectl apply -k infra/kubernetes/
kubectl -n ai-worker-platform rollout status deploy/api
```

- API: `http://localhost:30080` (NodePort) or `kubectl -n ai-worker-platform port-forward svc/api 8000:8000`
- Fresh clusters get `CREATE EXTENSION vector` from `init-db/01-extensions.sql` plus a Postgres postStart hook
- Existing Postgres PVCs that predate RAG still need:

```bash
kubectl -n ai-worker-platform exec -i deploy/postgres -- \
  psql -U postgres -d ai_worker_platform < init-db/02-stage14-jobtype-enum.sql
kubectl -n ai-worker-platform exec -i deploy/postgres -- \
  psql -U postgres -d ai_worker_platform < init-db/03-stage15-chunk-hierarchy.sql
kubectl -n ai-worker-platform exec -i deploy/postgres -- \
  psql -U postgres -d ai_worker_platform < init-db/04-stage15-modular-rag.sql
```

Scale a worker: `kubectl -n ai-worker-platform scale deployment worker-rag-query --replicas=2`

## Evolution

| Stage | What it adds |
|-------|----------------|
| **13** | Naive RAG — ingest, pgvector, single-pass query |
| **14** | Advanced RAG — expand, filter, rerank, small-to-big, Celery chain, step metrics |
| **15** | Modular RAG — router, critic loop, eval triad, MCP client, `/admin/rag/dashboard` |
