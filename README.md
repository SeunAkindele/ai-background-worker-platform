# AI Background Worker Platform

A staged backend platform for submitting, queuing, and processing AI background jobs (summarization, OCR, embeddings, transcription, recommendations).

**Current branch:** `feat/stage-5`  
**Current stage:** Stage 5 — Celery task queue with retry backoff

## Stage 5 scope (this branch)

Stage 5 replaces the custom Redis poll-loop worker with **Celery** for task dispatch and execution. Failed tasks are retried automatically with configurable backoff, and the task function is idempotent against duplicate delivery. The legacy `RedisJobQueue` and `redis_worker` remain in the codebase but are no longer on the active dispatch path. All Stage 1–4 infrastructure (API, PostgreSQL, summarization pipeline) is unchanged.

| Area | Status |
|------|--------|
| FastAPI HTTP API | Done |
| PostgreSQL job persistence (SQLAlchemy) | Done |
| **Celery task dispatch** (replaces custom Redis worker) | **Done** |
| **Automatic retry with backoff** (10s → 60s, max 2 retries) | **Done** |
| **Idempotent task execution** (skips terminal states on redelivery) | **Done** |
| **Late acknowledgment** (`task_acks_late`, prefetch=1) | **Done** |
| **Celery-aware observability** (`/health`, `/admin/queues`) | **Done** |
| Real summarization (Hugging Face `facebook/bart-large-cnn`) | Done |
| Text chunking (sliding window + recursive merge) | Done |
| Summarization input validation (API + handler) | Done |
| Job priority (`high`, `normal`, `low`) | Done (stored in DB; Celery dispatch is FIFO) |
| Stub handlers for `ocr` / `embeddings` / `transcription` / `recommendations` | Done (real impls in Stage 6) |
| Job lifecycle: `pending` → `processing` → `completed` \| `failed` | Done |
| Legacy Redis queue (`RedisJobQueue`, `redis_worker`) | Retained but bypassed |
| Automated tests (API, Redis queue, worker, chunking/summarize) | Done |
| Celery / RabbitMQ / Kafka | **Celery with Redis broker — done** |

### Architecture (Stage 5)

```
Client
  │
  ▼
FastAPI  ──►  PostgreSQL  (full job records: status, priority, payloads, timestamps)
  │
  └──►  celery_app.send_task("process_job", [job_id])
            │
            ▼
       Redis (Celery broker)
            │
            ▼
       Celery worker  (separate process — celery -A app.workers.celery_app worker)
            │
            ├── load job from PostgreSQL
            ├── idempotency check (skip if already completed / failed)
            ├── mark processing in PostgreSQL
            ├── run handler
            │     └── summarization → chunk_text() → summarize_chunk() (HF model) → merge
            ├── on success: mark completed + result_payload
            └── on failure: retry with backoff (10s → 60s)
                  └── after max retries: mark failed + error_message
```

### Celery task design

The task lives in `app/workers/tasks.py`:

| Concept | Detail |
|---------|--------|
| **Dispatch** | `job_service.create_job()` commits the job to PostgreSQL, then calls `celery_app.send_task("process_job", [str(job.id)])`. The job ID is sent as a JSON string. |
| **Idempotency** | On entry, the task loads the job from the DB. If the job is missing or already in a terminal state (`completed` / `failed`), it returns immediately — safe against duplicate delivery or visibility-timeout redelivery. |
| **Retry backoff** | On handler failure, Celery re-enqueues the task with a countdown: **10 s** after the 1st failure, **60 s** after the 2nd. After **3 total attempts** (original + 2 retries) the job is marked `failed` with the exception message. |
| **Late ack** | `task_acks_late=True` + `worker_prefetch_multiplier=1` — the broker message is acknowledged only after the task completes (or permanently fails), so a killed worker doesn't lose jobs. |
| **Visibility timeout** | Set to 1 hour (`broker_transport_options.visibility_timeout = 3600`), longer than any expected job runtime, to prevent the broker from redelivering in-flight tasks. |

**DSA focus:** retry backoff schedule via dict lookup, idempotent state-machine transitions.  
**Python internals focus:** `bind=True` task (access `self.request.retries`), `MaxRetriesExceededError` exception flow, lazy imports for Celery serialization.

### Celery configuration

`app/workers/celery_app.py` configures the Celery app:

| Setting | Value | Why |
|---------|-------|-----|
| `broker` / `backend` | `settings.redis_url` | Uses the same Redis instance as the legacy queue |
| `task_serializer` | `json` | Avoids pickle; forces JSON-clean arguments |
| `task_acks_late` | `True` | Ack after completion, not on receipt |
| `worker_prefetch_multiplier` | `1` | Process one task at a time; don't hoard messages |
| `task_track_started` | `True` | Exposes a `STARTED` state for monitoring |
| `visibility_timeout` | `3600` (1 h) | Longer than the slowest job to prevent false redelivery |

### Summarization pipeline

The real work lives in `app/workers/summarization_worker.py`:

| Function | Role |
|----------|------|
| `summarize()` | Entry point. Short text is summarized directly; long text is chunked, each chunk summarized, summaries merged, and re-summarized recursively (up to `_max_depth`) if still too long. Returns `summary`, `chunks_processed`, `original_word_count`, `summary_word_count`. |
| `chunk_text()` | **Generator** — yields overlapping word chunks via a sliding window. Step = `chunk_size - overlap`. Lazy, so only one chunk is held in memory at a time. |
| `summarize_chunk()` | Summarizes a single chunk with the Hugging Face pipeline. |
| `get_summarization_pipeline()` | Lazy-loading **singleton** for the model. Loads once on first use, reused after. Loads `facebook/bart-large-cnn` with `use_safetensors=True`. |

**Model:** `facebook/bart-large-cnn` (~1.6GB), loaded from **safetensors** weights. Safetensors avoids `torch.load`, so the model runs on `torch 2.2.x` (required for Intel macOS, where torch ≥ 2.6 has no wheels). Swap the model name in `get_summarization_pipeline()` to use a smaller/faster one (e.g. `Falconsai/text_summarization`, ~240MB) — it must ship safetensors weights.

**DSA focus:** sliding-window chunking, overlap/merge strategy, recursive (divide-and-conquer) reduction.  
**Python internals focus:** generators / lazy evaluation, singleton via module-global, lazy heavy imports inside the handler.

On job creation, the API:

1. Inserts a `pending` job row in PostgreSQL (with optional priority)
2. Dispatches a Celery task via `celery_app.send_task("process_job", [str(job.id)])`
3. Returns the job to the caller

The Celery worker runs in its own process, picks up tasks from the Redis broker, processes them, and updates PostgreSQL. API and worker share **only** Redis (as Celery broker) and PostgreSQL — not memory.

### Job model

**Statuses:** `pending` → `processing` → `completed` | `failed`

**Types:** `summarization`, `ocr`, `embeddings`, `transcription`, `recommendations`

**Priorities:** `high`, `normal` (default), `low`

### Handlers

`app/workers/handlers.py` maps each job type to a handler. As of Stage 4, `summarization` is a **real** handler that calls `summarize()` and validates that `input.text` is a non-empty string. The other types (`ocr`, `embeddings`, `transcription`, `recommendations`) are still stubs returning fake results — real implementations come in Stage 6.

Summarization input is validated in two places:

1. **API level** — `JobCreate.validate_input_for_job_type` (a Pydantic `model_validator` in `app/schemas/job_schema.py`) rejects a summarization job with empty/missing `text` with a `422` before it is ever queued.
2. **Handler level** — `_summarize` re-checks and raises `ValueError` (defence in depth for jobs created by other paths).

## Project structure

```
app/
├── api/jobs.py                        # REST endpoints
├── core/
│   ├── database.py                    # SQLAlchemy engine, sessions, db_session context manager
│   ├── queue.py                       # RedisJobQueue (legacy — retained, not on active path)
│   └── redis_client.py                # Shared Redis connection
├── models/job.py                      # Job ORM model, enums, priority ranks
├── schemas/job_schema.py              # Pydantic request/response models
├── services/job_service.py            # Job CRUD + Celery dispatch
├── workers/
│   ├── celery_app.py                  # Celery configuration (Stage 5)
│   ├── tasks.py                       # process_job task with retry backoff (Stage 5)
│   ├── redis_worker.py                # Standalone Redis poll worker (legacy)
│   ├── handlers.py                    # Job-type → handler map (summarization is real)
│   ├── summarization_worker.py        # Real summarizer: chunking + HF pipeline + merge
│   └── decorators.py                  # Execution-time logging
├── config.py
└── main.py                            # API only — worker is started separately
tests/
├── conftest.py                        # Test client, DB reset, fakeredis queue fixture
├── test_jobs.py
├── test_redis_queue.py                # Priority ordering, FIFO, cross-client dequeue
├── test_worker.py
└── test_summarization.py              # chunk_text() + summarize() (model mocked)
docker-compose.yml                     # PostgreSQL + Redis
```

## Prerequisites

- Python 3.11+
- Docker (recommended) or local PostgreSQL + Redis
- ~2GB free disk for the summarization model (downloaded once, cached in `~/.cache/huggingface`)

> **Note on `torch` (Intel macOS):** PyTorch ships no wheels newer than `2.2.x` for Intel macOS, and recent `transformers` refuses to load legacy `.bin` weights on `torch < 2.6`. Stage 4 sidesteps this by using a model with **safetensors** weights (`facebook/bart-large-cnn`) and `use_safetensors=True`, which works on `torch 2.2.x`.

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

The platform requires **two processes**: the API and the Celery worker.

**Terminal 1 — API:**

```bash
uvicorn app.main:app --reload
```

**Terminal 2 — Celery worker:**

```bash
celery -A app.workers.celery_app worker --loglevel=info
```

- Health: `GET http://localhost:8000/health`
- Queue stats: `GET http://localhost:8000/admin/queues`
- Interactive docs: `http://localhost:8000/docs`

Tables are created automatically on startup via `init_db()`.

> **First summarization job is slow.** On the first job the worker downloads the model (~1.6GB) and loads it into memory. Subsequent jobs reuse the cached, in-memory pipeline and are much faster.

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness + number of queued Celery tasks |
| `GET` | `/admin/queues` | Celery queue stats (`queued`, `active`, `reserved`) |
| `POST` | `/jobs` | Create a job (`job_type`, `input`, optional `priority`) |
| `GET` | `/jobs/{job_id}` | Fetch a job by UUID |
| `GET` | `/jobs` | List jobs (`skip`, `limit`; returns `jobs` + `total`) |

**Example — create a summarization job:**

```bash
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "job_type": "summarization",
    "input": {"text": "Artificial intelligence has transformed industries ranging from healthcare to finance. In healthcare, AI systems can now detect diseases from medical images with accuracy rivaling human doctors. In finance, AI powers fraud detection systems that monitor millions of transactions in real time."},
    "priority": "high"
  }'
```

Poll `GET /jobs/{job_id}` to watch status move from `pending` → `processing` → `completed`. On success, `result_payload` contains the summary:

```json
{
  "summary": "Artificial intelligence has transformed industries ranging from healthcare to finance...",
  "chunks_processed": 1,
  "original_word_count": 44,
  "summary_word_count": 30
}
```

A summarization job with empty or missing `text` is rejected with `422`:

```bash
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"job_type": "summarization", "input": {"text": ""}}'
# 422 Unprocessable Entity
```

**Example — queue stats:**

```bash
curl http://localhost:8000/admin/queues
# {"queued": 0, "active": {}, "reserved": {}}
```

## Tests

Tests use `.env.test`, a dedicated PostgreSQL database, and **fakeredis** (no real Redis required for `pytest`).

```bash
pytest
```

Coverage includes job CRUD, Redis queue ordering (HIGH before NORMAL, FIFO tie-break, separate client instances), end-to-end worker completion via a threaded test worker, and the summarization logic. The summarization tests **mock the Hugging Face pipeline**, so `pytest` stays fast and never downloads the model — they exercise `chunk_text()` (overlap, generator behaviour, edge cases) and `summarize()` (single-chunk vs. multi-chunk, recursive merge, max-depth guard).

## Environment variables

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection string |
| `REDIS_URL` | Redis connection string (used by both Celery broker and legacy queue) |
| `APP_ENV` | `development` or `test` |

See `.env.example` and `.env.test.example` for templates.

## What changed from Stage 4

| Stage 4 | Stage 5 |
|---------|---------|
| Custom Redis poll-loop worker (`redis_worker.py`) dispatches and executes jobs | **Celery** dispatches and executes jobs via `process_job` task |
| `job_service.create_job` enqueues to `RedisJobQueue` (ZSET) | `job_service.create_job` calls `celery_app.send_task("process_job")` |
| Retry was a stub (`jobs:retry` LIST, never populated) | **Automatic retry with backoff** (10 s → 60 s, max 2 retries / 3 total attempts) |
| No duplicate-delivery protection | **Idempotent task**: skips terminal states on redelivery |
| Worker acks on dequeue | **Late ack** (`task_acks_late`) — message acknowledged after task completes |
| `/health` reports Redis ZSET pending count | `/health` reports Celery broker queue length |
| `/admin/queues` returns pending/processing/retry/failed counts from Redis | `/admin/queues` returns `queued`/`active`/`reserved` from Celery broker + inspect |
| No Celery dependency | Adds `celery[redis]>=5.3.0` |
| New files: — | `app/workers/celery_app.py`, `app/workers/tasks.py` |

> Stage 5 changes **only** the dispatch and execution layer. The API, PostgreSQL layer, summarization pipeline, and handler map are unchanged from Stage 4. The legacy `RedisJobQueue` and `redis_worker` are retained in the codebase but are no longer used by `job_service`.
