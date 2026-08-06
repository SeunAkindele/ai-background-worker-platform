# AI Background Worker Platform

A backend platform for submitting, queuing, and processing AI background jobs. The API is async (FastAPI + asyncpg), protected by Redis sliding-window rate limits and pending-job backpressure. Workers run on Celery with observability via job logs and heartbeats.

## Architecture

```
Client
  │
  │  rate limit (Redis sliding window)
  │  backpressure (max pending jobs)
  ▼
FastAPI (async)  ──►  PostgreSQL (asyncpg)
  │
  ├──►  /jobs · /admin/*  (rate-limited)
  │
  └──►  Celery  (Redis broker)
            │
            ▼
       Celery worker  (sync handlers · logs · heartbeats)
```

## Features

- **Async API** — non-blocking routes with async SQLAlchemy (`asyncpg`)
- **Rate limiting** — Redis sliding-window limiter per client IP (default 20 req / 60s)
- **Backpressure** — reject new jobs when pending count hits the configured max
- **Jobs** — create, fetch, and list jobs with typed payloads and priority queues
- **Celery workers** — retry backoff, AI handlers, job logs, and worker heartbeats
- **Admin API** — dashboard, logs, errors, slowest jobs, and worker health

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
celery -A app.workers.celery_app worker --loglevel=info -Q high,normal,low
```

- Health: `GET http://localhost:8000/health`
- Dashboard: `GET http://localhost:8000/admin/dashboard`
- Docs: `http://localhost:8000/docs`
- Examples: [`API_COLLECTION.md`](API_COLLECTION.md)

```bash
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"job_type": "summarization", "input": {"text": "Artificial intelligence has transformed industries..."}, "priority": "high"}'
```

```bash
pytest
```

## Evolution

Observability and admin controls added job logs, heartbeats, and dashboards. This release makes the API **async** with **Redis rate limiting** and **pending-job backpressure**, so the HTTP layer scales under concurrent load without flooding the queue.
