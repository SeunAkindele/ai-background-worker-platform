# AI Background Worker Platform

A backend platform for submitting, queuing, and processing AI background jobs (summarization, OCR, embeddings, transcription, recommendations). Jobs are persisted in PostgreSQL, scheduled by priority, and executed by a local background worker.

## Architecture

```
Client
  │
  ▼
FastAPI  ──►  PostgreSQL  (job records: status, priority, payloads, timestamps)
  │
  └──►  PriorityJobQueue  (min-heap — HIGH before NORMAL before LOW)
            │
            ▼
       LocalWorker  (background thread)
            │
            ├── mark processing
            ├── run handler
            └── mark completed or failed
```

On create, the API inserts a `pending` job, enqueues its ID by priority, and returns the record. The worker polls the queue, runs the matching handler, and updates status through `pending` → `processing` → `completed` | `failed`.

## Features

- **Jobs** — REST API to create, fetch, and list jobs with typed payloads, lifecycle status, and `high` / `normal` / `low` priority
- **Priority queue** — Thread-safe min-heap that schedules HIGH before NORMAL before LOW (FIFO within the same priority)
- **Workers** — Local background worker that consumes the queue and runs stub handlers per job type
- **Persistence** — SQLAlchemy models on PostgreSQL, with a dedicated test database
- **Job types** — summarization, OCR, embeddings, transcription, recommendations

## Quick start

**Prerequisites:** Python 3.11+, PostgreSQL (local or Docker Compose)

```bash
cd ai-background-worker-platform
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Set DATABASE_URL in .env

# Option A — local PostgreSQL
createdb ai_worker_platform

# Option B — PostgreSQL via Docker
docker compose up -d

cp .env.test.example .env.test
createdb ai_worker_platform_test

uvicorn app.main:app --reload
```

The local worker starts with the API and stops on shutdown.

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

The **job API foundation** established FastAPI job CRUD, PostgreSQL persistence, and an in-memory FIFO queue. This stage adds a **local background worker** and a **priority queue** so jobs process end-to-end with HIGH before NORMAL before LOW (FIFO within the same priority).
