# AI Background Worker Platform

A backend platform for submitting, queuing, and processing AI background jobs. Jobs persist in PostgreSQL, run through Celery with Redis, and expose admin APIs for job logs, worker heartbeats, dashboards, and performance views.

## Architecture

```
Client
  │
  ▼
FastAPI  ──►  PostgreSQL  (jobs · job_logs · worker_heartbeats)
  │
  ├──►  /admin/dashboard · logs · errors · slowest-jobs · workers
  │
  └──►  Celery  (Redis broker · high / normal / low)
            │
            ▼
       Celery worker
            ├── heartbeat thread (liveness)
            ├── job audit logs
            └── handlers (summarization · embeddings · OCR · transcription · recommendations)
```

## Features

- **Jobs** — create, fetch, and list jobs with typed payloads, status, and priority queues
- **Celery** — Redis-brokered dispatch with retry backoff and idempotent execution
- **AI handlers** — summarization, embeddings, OCR, transcription, and recommendations under a shared contract
- **Job logs** — structured per-job audit trail (info / warning / error / debug)
- **Worker heartbeats** — online / busy / offline status with stale detection and completion counters
- **Admin API** — dashboard, job logs, recent errors, slowest jobs, and worker health

## Quick start

**Prerequisites:** Python 3.11+, Docker (PostgreSQL + Redis). First ML jobs download models on demand.

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

AI job handlers delivered typed workers under a shared contract. This release adds **observability and admin controls**: per-job audit logs, worker heartbeats with stale detection, and admin endpoints for dashboard metrics, errors, slowest jobs, and worker health.
