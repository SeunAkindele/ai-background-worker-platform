# AI Background Worker Platform

A backend platform for submitting, queuing, and processing AI background jobs (summarization, OCR, embeddings, transcription, recommendations). Jobs persist in PostgreSQL, queue in Redis by priority, and run in a separate worker process.

## Architecture

```
Client
  │
  ▼
FastAPI  ──►  PostgreSQL  (job records)
  │
  └──►  Redis  (pending ZSET · processing / retry / failed lists)
            │
            ▼
       RedisWorker  (separate process)
            ├── dequeue
            ├── run handler
            └── complete or fail
```

API and worker share Redis and PostgreSQL only — not process memory.

## Features

- **Jobs** — create, fetch, and list jobs with typed payloads, status, and `high` / `normal` / `low` priority
- **Redis queue** — durable priority scheduling (FIFO within the same priority) with processing, retry, and failed tracking
- **Workers** — standalone Redis worker process that runs handlers per job type
- **Persistence** — SQLAlchemy models on PostgreSQL
- **Queue stats** — `/health` and `/admin/queues` expose pending, processing, retry, and failed counts

## Quick start

**Prerequisites:** Python 3.11+, Docker (PostgreSQL + Redis)

```bash
cd ai-background-worker-platform
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

docker compose up -d
cp .env.example .env
cp .env.test.example .env.test
createdb ai_worker_platform_test

# Terminal 1 — API
uvicorn app.main:app --reload

# Terminal 2 — worker
python -m app.workers.redis_worker
```

- Health: `GET http://localhost:8000/health`
- Docs: `http://localhost:8000/docs`

```bash
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"job_type": "summarization", "input": {"text": "hello world"}, "priority": "high"}'
```

```bash
pytest
```

## Evolution

The local worker and in-memory priority queue processed jobs inside the API process. This release moves the queue to **Redis** and the worker to a **separate process**, so the API and workers scale independently over shared Redis and PostgreSQL.
