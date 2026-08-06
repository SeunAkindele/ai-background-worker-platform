# AI Background Worker Platform

A backend platform for submitting, queuing, and processing AI background jobs. Jobs persist in PostgreSQL, dispatch through Celery with a Redis broker, and run in a separate worker process with automatic retry backoff. Summarization uses a Hugging Face model with sliding-window chunking.

## Architecture

```
Client
  │
  ▼
FastAPI  ──►  PostgreSQL  (job records)
  │
  └──►  Celery  (Redis broker)
            │
            ▼
       Celery worker
            ├── idempotency check
            ├── run handler (summarization → chunk → HF → merge)
            └── on failure: retry with backoff (10s → 60s)
```

## Features

- **Jobs** — create, fetch, and list jobs with typed payloads, status, and priority
- **Celery** — Redis-brokered task dispatch with late ack and prefetch=1
- **Retry backoff** — failed tasks retry at 10s then 60s (max 2 retries); then mark failed
- **Idempotency** — completed/failed jobs are skipped on redelivery
- **Summarization** — Hugging Face `facebook/bart-large-cnn` with overlapping chunking and recursive merge
- **Queue stats** — `/health` and `/admin/queues` (queued, active, reserved)

## Quick start

**Prerequisites:** Python 3.11+, Docker (PostgreSQL + Redis). First summarization job downloads the model (~1.6GB).

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
celery -A app.workers.celery_app worker --loglevel=info
```

- Health: `GET http://localhost:8000/health`
- Docs: `http://localhost:8000/docs`

```bash
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"job_type": "summarization", "input": {"text": "Artificial intelligence has transformed industries..."}, "priority": "high"}'
```

```bash
pytest
```

## Evolution

The summarization worker ran on a custom Redis poll loop. This release switches dispatch to **Celery** with a Redis broker, adding **retry with backoff**, late acknowledgment, and idempotent handling of redelivered tasks.
