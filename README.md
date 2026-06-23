# AI Background Worker Platform

A staged backend platform for submitting, queuing, and processing AI background jobs (summarization, OCR, embeddings, transcription, recommendations).

**Current branch:** `feat/stage-2`  
**Current stage:** Stage 2 — Local background worker and priority queue

## Stage 2 scope (this branch)

Stage 2 adds a background worker that consumes the queue and processes jobs end-to-end. Everything from Stage 1 is included, plus priority scheduling and stub job handlers.

| Area | Status |
|------|--------|
| FastAPI HTTP API | Done |
| PostgreSQL job persistence (SQLAlchemy) | Done |
| Priority job queue (min-heap, thread-safe) | Done |
| Job priority (`high`, `normal`, `low`) | Done |
| Local background worker (daemon thread) | Done |
| Stub handlers per job type | Done |
| Job lifecycle: `pending` → `processing` → `completed` \| `failed` | Done |
| Automated tests (API, queue, worker) | Done |
| Redis / external queue | Not in this stage |

### Architecture (Stage 2)

```
Client
  │
  ▼
FastAPI  ──►  PostgreSQL  (full job records: status, priority, payloads, timestamps)
  │
  └──►  PriorityJobQueue  (min-heap of job UUIDs — HIGH before NORMAL before LOW)
            │
            ▼
       LocalWorker  (background thread)
            │
            ├── mark processing
            ├── run handler (stub)
            └── mark completed or failed
```

On job creation, the API:

1. Inserts a `pending` job row in PostgreSQL (with optional priority)
2. Enqueues the job ID in the priority queue
3. Returns the job to the caller

The worker polls the queue, picks the highest-priority job (FIFO within the same priority), runs the matching handler, and updates the job status.

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
│   └── queue.py             # Thread-safe priority queue (min-heap)
├── models/job.py            # Job ORM model, enums, priority ranks
├── schemas/job_schema.py    # Pydantic request/response models
├── services/job_service.py
├── workers/
│   ├── local_worker.py      # Background worker thread
│   ├── handlers.py          # Per-job-type stub handlers
│   └── decorators.py        # Execution-time logging
├── config.py
└── main.py                  # Starts/stops worker via lifespan
tests/
├── conftest.py              # Test client, DB reset, worker lifecycle
├── test_jobs.py
├── test_priority_queue.py
└── test_worker.py
docker-compose.yml           # Optional PostgreSQL container
```

## Prerequisites

- Python 3.11+
- PostgreSQL (local instance or via Docker Compose)

## Setup

```bash
# Clone and enter the repo
cd ai-background-worker-platform

# Create a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Option A — local PostgreSQL
cp .env.example .env
# Edit DATABASE_URL in .env for your local PostgreSQL
createdb ai_worker_platform

# Option B — PostgreSQL via Docker
docker compose up -d
# Set DATABASE_URL=postgresql://postgres:postgres@localhost:5432/ai_worker_platform in .env

# Test database (separate from app DB)
cp .env.test.example .env.test
createdb ai_worker_platform_test
```

## Running the API

```bash
uvicorn app.main:app --reload
```

The local worker starts automatically with the API and stops on shutdown.

- Health: `GET http://localhost:8000/health`
- Interactive docs: `http://localhost:8000/docs`

Tables are created automatically on startup via `init_db()`.

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness check |
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

## Tests

Tests use `.env.test` and a dedicated database so they never touch the development DB. The worker is started per test session via fixtures.

```bash
pytest
```

Coverage includes job CRUD, priority queue ordering (HIGH before NORMAL, FIFO tie-break), worker completion, and high-priority jobs finishing before low-priority ones.

## Environment variables

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection string |
| `APP_ENV` | `development` or `test` |

See `.env.example` and `.env.test.example` for templates.
