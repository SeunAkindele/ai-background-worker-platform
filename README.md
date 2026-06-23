# AI Background Worker Platform

A staged backend platform for submitting, queuing, and processing AI background jobs (summarization, OCR, embeddings, transcription, recommendations).

**Current branch:** `feat/stage-1`  
**Current stage:** Stage 1 — Job API, persistence, and in-memory queue

## Stage 1 scope (this branch)

Stage 1 establishes the core job lifecycle without a background worker or external queue infrastructure.

| Area | Status |
|------|--------|
| FastAPI HTTP API | Done |
| PostgreSQL job persistence (SQLAlchemy) | Done |
| In-memory FIFO job queue (job IDs only) | Done |
| Job create / get / list endpoints | Done |
| `update_job_status` service (for workers in Stage 2) | Done |
| Automated tests (isolated test database) | Done |
| Background worker | Not in this stage |
| Redis / Docker Compose | Not in this stage |

### Architecture (Stage 1)

```
Client
  │
  ▼
FastAPI  ──►  PostgreSQL  (full job records: status, payloads, timestamps)
  │
  └──►  InMemoryJobQueue  (FIFO of job UUIDs — scheduling order only)
```

On job creation, the API:

1. Inserts a `pending` job row in PostgreSQL
2. Enqueues the job ID in the in-process queue
3. Returns the job to the caller

No worker consumes the queue yet; jobs remain `pending` until Stage 2.

### Job model

**Statuses:** `pending` → `processing` → `completed` | `failed`

**Types:** `summarization`, `ocr`, `embeddings`, `transcription`, `recommendations`

## Project structure

```
app/
├── api/jobs.py           # REST endpoints
├── core/
│   ├── database.py       # SQLAlchemy engine, sessions, init_db
│   └── queue.py          # In-memory FIFO queue
├── models/job.py         # Job ORM model and enums
├── schemas/job_schema.py # Pydantic request/response models
├── services/job_service.py
├── config.py
└── main.py
tests/
├── conftest.py           # Test client, DB reset, queue clear
└── test_jobs.py
```

## Prerequisites

- Python 3.11+
- PostgreSQL (local instance; Docker is not required for Stage 1)

## Setup

```bash
# Clone and enter the repo
cd ai-background-worker-platform

# Create a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# App database
cp .env.example .env
# Edit DATABASE_URL in .env for your local PostgreSQL

# Create the database (example)
createdb ai_worker_platform

# Test database (separate from app DB)
cp .env.test.example .env.test
createdb ai_worker_platform_test
```

## Running the API

```bash
uvicorn app.main:app --reload
```

- Health: `GET http://localhost:8000/health`
- Interactive docs: `http://localhost:8000/docs`

Tables are created automatically on startup via `init_db()`.

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness check |
| `POST` | `/jobs` | Create a job (`job_type`, `input`) |
| `GET` | `/jobs/{job_id}` | Fetch a job by UUID |
| `GET` | `/jobs` | List jobs (`skip`, `limit`; returns `jobs` + `total`) |

**Example — create a job:**

```bash
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"job_type": "summarization", "input": {"text": "hello world"}}'
```

## Tests

Tests use `.env.test` and a dedicated database so they never touch the development DB.

```bash
pytest
```

Coverage includes job creation, validation, retrieval, listing, enqueue behavior, and status updates via `job_service.update_job_status`.

## Environment variables

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection string |
| `APP_ENV` | `development` or `test` |

See `.env.example` and `.env.test.example` for templates.
