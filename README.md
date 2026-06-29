# AI Background Worker Platform

A staged backend platform for submitting, queuing, and processing AI background jobs (summarization, OCR, embeddings, transcription, recommendations).

**Current branch:** `feat/stage-4`  
**Current stage:** Stage 4 — Real summarization worker (Hugging Face + chunking)

## Stage 4 scope (this branch)

Stage 4 replaces the fake summarization stub with a **real AI summarizer**. Long text is split into overlapping chunks (sliding window), each chunk is summarized with a Hugging Face model, and the chunk summaries are merged — recursively re-summarizing if the merged result is still too long. All Stage 1–3 infrastructure (API, PostgreSQL, Redis queue, separate worker process) is unchanged.

| Area | Status |
|------|--------|
| FastAPI HTTP API | Done |
| PostgreSQL job persistence (SQLAlchemy) | Done |
| Redis job queue (priority + FIFO via ZSET) | Done |
| Separate worker process (`redis_worker`) | Done |
| Job priority (`high`, `normal`, `low`) | Done |
| Processing / retry / failed queue tracking | Done (retry scheduling stubbed for Stage 5) |
| Queue observability (`/health`, `/admin/queues`) | Done |
| **Real summarization** (Hugging Face `facebook/bart-large-cnn`) | **Done** |
| **Text chunking** (sliding window + recursive merge) | **Done** |
| **Summarization input validation** (API + handler) | **Done** |
| Stub handlers for `ocr` / `embeddings` / `transcription` / `recommendations` | Done (real impls in Stage 6) |
| Job lifecycle: `pending` → `processing` → `completed` \| `failed` | Done |
| Automated tests (API, Redis queue, worker, chunking/summarize) | Done |
| Celery / RabbitMQ / Kafka | Not in this stage |

### Architecture (Stage 4)

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
            ├── run handler
            │     └── summarization → chunk_text() → summarize_chunk() (HF model) → merge
            └── mark completed / failed + acknowledge / move_to_failed
```

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

`app/workers/handlers.py` maps each job type to a handler. As of Stage 4, `summarization` is a **real** handler that calls `summarize()` and validates that `input.text` is a non-empty string. The other types (`ocr`, `embeddings`, `transcription`, `recommendations`) are still stubs returning fake results — real implementations come in Stage 6.

Summarization input is validated in two places:

1. **API level** — `JobCreate.validate_input_for_job_type` (a Pydantic `model_validator` in `app/schemas/job_schema.py`) rejects a summarization job with empty/missing `text` with a `422` before it is ever queued.
2. **Handler level** — `_summarize` re-checks and raises `ValueError` (defence in depth for jobs created by other paths).

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
│   ├── redis_worker.py             # Standalone worker process
│   ├── handlers.py                 # Job-type → handler map (summarization is real)
│   ├── summarization_worker.py     # Real summarizer: chunking + HF pipeline + merge
│   └── decorators.py               # Execution-time logging
├── config.py
└── main.py                         # API only — worker is started separately
tests/
├── conftest.py                     # Test client, DB reset, fakeredis queue fixture
├── test_jobs.py
├── test_redis_queue.py             # Priority ordering, FIFO, cross-client dequeue
├── test_worker.py
└── test_summarization.py           # chunk_text() + summarize() (model mocked)
docker-compose.yml                  # PostgreSQL + Redis
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

The platform requires **two processes**: the API and the worker.

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

> **The worker does not auto-reload.** Unlike `uvicorn --reload`, the worker loads your code (and the model) into memory once at startup. After editing any worker code — `summarization_worker.py`, `handlers.py`, `redis_worker.py` — stop the worker (`Ctrl+C`) and start it again, or it will keep running the old code.

> **First summarization job is slow.** On the first job the worker downloads the model (~1.6GB) and loads it into memory. Subsequent jobs reuse the cached, in-memory pipeline and are much faster.

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness + pending/processing queue sizes |
| `GET` | `/admin/queues` | Full queue stats (`pending`, `processing`, `retry`, `failed`) |
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
# {"pending": 0, "processing": 0, "retry": 0, "failed": 0}
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
| `REDIS_URL` | Redis connection string (e.g. `redis://localhost:6379/0`) |
| `APP_ENV` | `development` or `test` |

See `.env.example` and `.env.test.example` for templates.

## What changed from Stage 3

| Stage 3 | Stage 4 |
|---------|---------|
| `summarization` handler returned a fake `"summary generated"` string | `summarization` runs a real Hugging Face model (`facebook/bart-large-cnn`) |
| No chunking | Long text split via sliding-window `chunk_text()` generator + recursive merge |
| No ML dependencies | Adds `transformers`, `torch`, `safetensors`, `sentencepiece` |
| No input validation per job type | `JobCreate` rejects empty summarization `text` (`422`); handler re-validates |
| Tests covered CRUD / queue / worker | Adds `test_summarization.py` (chunking + summarize, model mocked) |

> Stage 4 changes **only** the summarization handler and adds the summarizer module. The API, PostgreSQL layer, Redis queue, and worker loop are unchanged from Stage 3.
