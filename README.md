# AI Background Worker Platform

A staged backend platform for submitting, queuing, and processing AI background jobs (summarization, OCR, embeddings, transcription, recommendations).

**Current branch:** `feat/stage-3`  
**Current stage:** Stage 3 — Redis queue and separate worker process

## Stage 3 scope (this branch)

Stage 3 externalizes the job queue to Redis and runs the worker as a **separate OS process**. Everything from Stages 1–2 is included, but the in-memory heap queue and API-embedded worker thread are replaced with a durable, shared Redis-backed queue.

| Area | Status |
|------|--------|
| FastAPI HTTP API | Done |
| PostgreSQL job persistence (SQLAlchemy) | Done |
| Redis job queue (priority + FIFO via ZSET) | Done |
| Separate worker process (`redis_worker`) | Done |
| Job priority (`high`, `normal`, `low`) | Done |
| Processing / retry / failed queue tracking | Done (retry scheduling stubbed for Stage 5) |
| Queue observability (`/health`, `/admin/queues`) | Done |
| Stub handlers per job type | Done |
| Job lifecycle: `pending` → `processing` → `completed` \| `failed` | Done |
| Automated tests (API, Redis queue, worker) | Done |
| Celery / RabbitMQ / Kafka | Not in this stage |

### Architecture (Stage 3)

```
Client
  │
  ▼
FastAPI  ──►  PostgreSQL  (full job records: status, priority, payloads, timestamps)
  │
  └──►  Redis
            │
            ├── jobs:pending     (ZSET — priority + FIFO score)
            ├── jobs:processing  (LIST — in-flight audit trail)
            ├── jobs:retry       (LIST — stub for Stage 5)
            └── jobs:failed      (LIST — dead-letter on handler error)
            │
            ▼
       RedisWorker  (separate process — python -m app.workers.redis_worker)
            │
            ├── dequeue from Redis
            ├── mark processing in PostgreSQL
            ├── run handler (stub)
            └── mark completed / failed + acknowledge / move_to_failed
```

On job creation, the API:

1. Inserts a `pending` job row in PostgreSQL (with optional priority)
2. Enqueues the job ID in the Redis pending ZSET
3. Returns the job to the caller

The worker runs in its own process, polls Redis for the next job, processes it, and updates PostgreSQL. API and worker share **only** Redis and PostgreSQL — not memory.

### Redis queue design

| Key | Type | Purpose |
|-----|------|---------|
| `jobs:pending` | ZSET | Priority queue. Score = `priority_rank × 10¹³ + created_at` so HIGH dequeues before NORMAL, and FIFO holds within the same priority. |
| `jobs:processing` | LIST | Jobs currently dequeued but not yet acknowledged. |
| `jobs:retry` | LIST | Stub list for failed jobs that will be retried (full logic in Stage 5). |
| `jobs:failed` | LIST | Jobs whose handler raised an exception. |

`RedisJobQueue` in `app/core/queue.py` is the single abstraction over these keys. External code should call methods like `enqueue()`, `dequeue()`, and `stats()` — not read Redis keys directly.

### Job model

**Statuses:** `pending` → `processing` → `completed` | `failed`

**Types:** `summarization`, `ocr`, `embeddings`, `transcription`, `recommendations`

**Priorities:** `high`, `normal` (default), `low`

### Handlers

Each job type has a stub handler in `app/workers/handlers.py` that returns fake results. Replace these with real AI integrations in later stages.

## Project structure

```
app/
├── api/jobs.py              # REST endpoints
├── core/
│   ├── database.py          # SQLAlchemy engine, sessions, db_session context manager
│   ├── queue.py             # RedisJobQueue (ZSET pending + LIST processing/retry/failed)
│   └── redis_client.py      # Shared Redis connection
├── models/job.py            # Job ORM model, enums, priority ranks
├── schemas/job_schema.py    # Pydantic request/response models
├── services/job_service.py
├── workers/
│   ├── redis_worker.py      # Standalone worker process
│   ├── handlers.py          # Per-job-type stub handlers
│   └── decorators.py        # Execution-time logging
├── config.py
└── main.py                  # API only — worker is started separately
tests/
├── conftest.py              # Test client, DB reset, fakeredis queue fixture
├── test_jobs.py
├── test_redis_queue.py      # Priority ordering, FIFO, cross-client dequeue
└── test_worker.py
docker-compose.yml           # PostgreSQL + Redis
```

## Prerequisites

- Python 3.11+
- Docker (recommended) or local PostgreSQL + Redis

## Setup

```bash
# Clone and enter the repo
cd ai-background-worker-platform

# Create a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start PostgreSQL and Redis
docker compose up -d

# App environment
cp .env.example .env
# Defaults work with docker-compose:
#   DATABASE_URL=postgresql://postgres:postgres@localhost:5432/ai_worker_platform
#   REDIS_URL=redis://localhost:6379/0

# Test database (separate from app DB)
cp .env.test.example .env.test
createdb ai_worker_platform_test
```

## Running the platform

Stage 3 requires **two processes**: the API and the worker.

**Terminal 1 — API:**

```bash
uvicorn app.main:app --reload
```

**Terminal 2 — worker:**

```bash
python -m app.workers.redis_worker
```

- Health: `GET http://localhost:8000/health`
- Queue stats: `GET http://localhost:8000/admin/queues`
- Interactive docs: `http://localhost:8000/docs`

Tables are created automatically on startup via `init_db()` (both API and worker call it).

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness + pending/processing queue sizes |
| `GET` | `/admin/queues` | Full queue stats (`pending`, `processing`, `retry`, `failed`) |
| `POST` | `/jobs` | Create a job (`job_type`, `input`, optional `priority`) |
| `GET` | `/jobs/{job_id}` | Fetch a job by UUID |
| `GET` | `/jobs` | List jobs (`skip`, `limit`; returns `jobs` + `total`) |

**Example — create a high-priority job:**

```bash
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"job_type": "summarization", "input": {"text": "hello world"}, "priority": "high"}'
```

Poll `GET /jobs/{job_id}` to watch status move from `pending` → `processing` → `completed`.

**Example — queue stats:**

```bash
curl http://localhost:8000/admin/queues
# {"pending": 0, "processing": 0, "retry": 0, "failed": 0}
```

## Tests

Tests use `.env.test`, a dedicated PostgreSQL database, and **fakeredis** (no real Redis required for `pytest`).

```bash
pytest
```

Coverage includes job CRUD, Redis queue ordering (HIGH before NORMAL, FIFO tie-break, separate client instances), and end-to-end worker completion via a threaded test worker.

## Environment variables

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection string |
| `REDIS_URL` | Redis connection string (e.g. `redis://localhost:6379/0`) |
| `APP_ENV` | `development` or `test` |

See `.env.example` and `.env.test.example` for templates.

## What changed from Stage 2

| Stage 2 | Stage 3 |
|---------|---------|
| In-memory `PriorityJobQueue` (heapq) | `RedisJobQueue` (Redis ZSET) |
| `LocalWorker` daemon thread in API process | `RedisWorker` separate process |
| Queue lost on API restart | Queue persists in Redis |
| API + worker share memory | API + worker share Redis + PostgreSQL only |
| Worker started in `main.py` lifespan | Worker started manually: `python -m app.workers.redis_worker` |
