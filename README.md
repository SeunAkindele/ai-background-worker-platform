# AI Background Worker Platform

HTTP API for submitting and tracking AI background jobs. Jobs are persisted in PostgreSQL and scheduled through an in-process FIFO queue, ready for worker consumption.

## Architecture

```
Client
  │
  ▼
FastAPI  ──►  PostgreSQL  (job records: type, status, payloads, timestamps)
  │
  └──►  InMemoryJobQueue  (FIFO of job UUIDs — scheduling order)
```

On create, the API inserts a `pending` job, enqueues its ID, and returns the record. Status transitions (`pending` → `processing` → `completed` | `failed`) are available via the job service for workers.

## Features

- **Job API** — create, fetch, and list jobs with pagination
- **Persistence** — SQLAlchemy models on PostgreSQL
- **In-memory FIFO queue** — schedules job IDs for processing
- **Job types** — summarization, OCR, embeddings, transcription, recommendations
- **Status updates** — service method for workers to set status, result, or error
- **Isolated tests** — dedicated test database via `.env.test`

## Quick start

**Prerequisites:** Python 3.11+, local PostgreSQL

```bash
cd ai-background-worker-platform
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Set DATABASE_URL in .env
createdb ai_worker_platform

cp .env.test.example .env.test
createdb ai_worker_platform_test

uvicorn app.main:app --reload
```

- Health: `GET http://localhost:8000/health`
- Docs: `http://localhost:8000/docs`

```bash
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"job_type": "summarization", "input": {"text": "hello world"}}'
```

```bash
pytest
```

## API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness check |
| `POST` | `/jobs` | Create a job (`job_type`, `input`) |
| `GET` | `/jobs/{job_id}` | Fetch a job by UUID |
| `GET` | `/jobs` | List jobs (`skip`, `limit`; returns `jobs` + `total`) |

## Project layout

```
app/
├── api/jobs.py
├── core/
│   ├── database.py
│   └── queue.py
├── models/job.py
├── schemas/job_schema.py
├── services/job_service.py
├── config.py
└── main.py
tests/
├── conftest.py
└── test_jobs.py
```

## Environment

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection string |
| `APP_ENV` | `development` or `test` |

See `.env.example` and `.env.test.example` for templates.
