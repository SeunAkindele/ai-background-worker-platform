# AI Background Worker Platform

A staged backend platform for submitting, queuing, and processing AI background jobs (summarization, OCR, embeddings, transcription, recommendations).

**Current branch:** `feat/stage-6`  
**Current stage:** Stage 6 — Multiple AI worker types with shared contract

## Stage 6 scope (this branch)

Stage 6 replaces the stub handlers with **real AI worker implementations**, each in its own file, all conforming to a shared `BaseJobHandler` abstract base class. The handler registry now uses lazy-instantiated class singletons instead of bare functions. Input validation for every job type is enforced at the API boundary (Pydantic) and again inside the handler (defence in depth).

| Area | Status |
|------|--------|
| FastAPI HTTP API | Done |
| PostgreSQL job persistence (SQLAlchemy) | Done |
| Celery task dispatch with retry backoff | Done |
| Idempotent task execution | Done |
| **`BaseJobHandler` ABC contract** (validate → process → format) | **Done** |
| **Embedding worker** (sentence-transformers, cosine similarity, nearest neighbor) | **Done** |
| **OCR worker** (Pillow + pytesseract, batch pipeline, generator-based) | **Done** |
| **Transcription worker** (audio chunking, merge intervals, timestamp alignment) | **Done** |
| **Recommendation worker** (graph collaborative filtering, Jaccard similarity, Top-K heap) | **Done** |
| **Summarization worker** refactored to `BaseJobHandler` subclass | **Done** |
| **Handler registry** with lazy singleton instantiation | **Done** |
| **Per-job-type input validation** at API level | **Done** |
| Job priority with Celery named queues (`high`, `normal`, `low`) | Done |
| Job lifecycle: `pending` → `processing` → `completed` \| `failed` | Done |
| Legacy Redis queue (`RedisJobQueue`, `redis_worker`) | Retained but bypassed |

### Architecture (Stage 6)

```
Client
  │
  ▼
FastAPI  ──►  PostgreSQL  (full job records: status, priority, payloads, timestamps)
  │
  └──►  celery_app.send_task("process_job", [job_id], queue=priority)
            │
            ▼
       Redis (Celery broker — named queues: high, normal, low)
            │
            ▼
       Celery worker  (celery -A app.workers.celery_app worker)
            │
            ├── load job from PostgreSQL
            ├── idempotency check (skip if already completed / failed)
            ├── mark processing
            ├── get_handler(job_type) → returns handler.run (bound method)
            │     │
            │     ▼
            │   BaseJobHandler.run()
            │     ├── validate_input()
            │     ├── process()          ← DSA logic lives here
            │     └── format_result()
            │
            │   Concrete handlers:
            │     ├── SummarizationHandler  → chunking + sliding window + HF model
            │     ├── EmbeddingHandler      → sentence-transformers + cosine similarity
            │     ├── OCRHandler            → Pillow + pytesseract batch pipeline
            │     ├── TranscriptionHandler  → audio chunking + merge intervals
            │     └── RecommendationHandler → graph + Jaccard + Top-K heap
            │
            ├── on success: mark completed + result_payload
            └── on failure: retry with backoff (10s → 60s)
                  └── after max retries: mark failed + error_message
```

### BaseJobHandler contract

`app/workers/base.py` defines the abstract contract every worker must follow:

```python
class BaseJobHandler(ABC, Generic[InputT, ResultT]):
    def validate_input(self, input_payload) -> None: ...   # raise ValueError if bad
    def process(self, input_payload) -> ResultT: ...        # DSA logic here
    def format_result(self, raw_result) -> dict: ...        # normalize for storage
    def run(self, input_payload) -> dict: ...               # template method (don't override)
```

`run()` calls validate → process → format in sequence. Subclasses override the three abstract methods, never `run()` itself. This is the **Template Method** design pattern.

**Python internals focus:** Abstract Base Classes (`ABC`), `Generic[InputT, ResultT]` type parameters, `TypeVar` with `bound`.

### Worker implementations

| Worker | File | DSA Concepts | Model/Tool |
|--------|------|-------------|------------|
| **Summarization** | `summarization_worker.py` | Sliding window chunking, recursive merge | `facebook/bart-large-cnn` (HF) |
| **Embeddings** | `embedding_worker.py` | Vectors, cosine similarity, brute-force nearest neighbor | `all-MiniLM-L6-v2` (sentence-transformers) |
| **OCR** | `ocr_worker.py` | Batch pipeline (decode → preprocess → OCR → post-process), generator-based memory efficiency | Pillow + pytesseract |
| **Transcription** | `transcription_worker.py` | Merge intervals (O(n log n)), timestamp alignment, sliding window over time | Simulated (Whisper in Stage 9) |
| **Recommendations** | `recommendation_worker.py` | Bipartite graph (adjacency list), Jaccard similarity, weighted scoring, Top-K via `heapq.nlargest` | Pure algorithm |

### Handler registry

`app/workers/handlers.py` maps each `JobType` to a lazily-instantiated handler singleton:

```python
def get_handler(job_type: JobType):
    handler = _get_or_create(job_type)
    return handler.run  # returns the bound template method
```

Each handler class (and its heavy ML dependencies) is imported only on first use. Models load into memory once per process and stay cached. This keeps Celery worker startup fast and memory low until a job of that type actually arrives.

### Celery task design

The task lives in `app/workers/tasks.py` (unchanged from Stage 5):

| Concept | Detail |
|---------|--------|
| **Dispatch** | `job_service.create_job()` commits the job to PostgreSQL, then calls `celery_app.send_task("process_job", [str(job.id)], queue=priority)`. |
| **Idempotency** | If the job is missing or in a terminal state, the task returns immediately. |
| **Retry backoff** | 10 s after 1st failure, 60 s after 2nd. After 3 total attempts → `failed`. |
| **Late ack** | `task_acks_late=True` + `worker_prefetch_multiplier=1`. |
| **Handler call** | `handler = get_handler(job.job_type)` returns `handler.run`, then `result = handler(input_payload)` triggers validate → process → format. |

### Celery configuration

`app/workers/celery_app.py`:

| Setting | Value | Why |
|---------|-------|-----|
| `broker` / `backend` | `settings.redis_url` | Redis as Celery broker |
| `task_serializer` | `json` | Avoids pickle |
| `task_acks_late` | `True` | Ack after completion |
| `worker_prefetch_multiplier` | `1` | One task at a time |
| `task_queues` | `high`, `normal`, `low` | Named priority queues |
| `visibility_timeout` | `3600` (1 h) | Prevents false redelivery |

### Input validation (two layers)

1. **API level** — `JobCreate.validate_input_for_job_type` (Pydantic `model_validator` in `app/schemas/job_schema.py`) rejects invalid input with `422` before the job is queued. Each job type has its own validation method.
2. **Handler level** — `BaseJobHandler.validate_input()` re-checks inside the worker (defence in depth for jobs created by other paths).

### Summarization pipeline

`SummarizationHandler` in `app/workers/summarization_worker.py`:

| Method | Role |
|--------|------|
| `process()` | Entry point — short text summarized directly; long text chunked, each chunk summarized, merged recursively. |
| `_chunk_text()` | Generator — sliding window with overlap. O(n) single pass. |
| `_summarize_chunk()` | Single chunk through HF pipeline. |
| `_get_pipeline()` | Lazy singleton for `facebook/bart-large-cnn` (safetensors). |

### Embeddings pipeline

`EmbeddingHandler` in `app/workers/embedding_worker.py`:

| Feature | Detail |
|---------|--------|
| Single text | Returns embedding vector (384 dimensions) |
| Batch texts | Returns list of embeddings + optional nearest neighbor search |
| `compare_to` | Computes cosine similarity between input and comparison text |
| Cosine similarity | `dot(A,B) / (‖A‖ * ‖B‖)` — O(d) per pair |
| Nearest neighbor | Brute-force O(n*d) — baseline that FAISS/HNSW optimize |

### OCR pipeline

`OCRHandler` in `app/workers/ocr_worker.py`:

| Feature | Detail |
|---------|--------|
| Single image | base64 → decode → preprocess → OCR → result |
| Batch images | Generator-based — O(1) memory regardless of batch size |
| Preprocessing | Grayscale → resize (max 4000px) → sharpen |
| Fallback | Simulated output if Tesseract binary not installed |

### Transcription pipeline

`TranscriptionHandler` in `app/workers/transcription_worker.py`:

| Feature | Detail |
|---------|--------|
| Audio chunking | Sliding window over time axis (30s chunks, 2s overlap) |
| Merge intervals | Classic O(n log n) algorithm — sort by start, single-pass merge |
| Timestamp alignment | O(n) pass to snap boundaries together |
| Current mode | Simulated (distributes source text across time chunks) |
| Future (Stage 9) | Will call Whisper on real audio file uploads |

### Recommendations pipeline

`RecommendationHandler` in `app/workers/recommendation_worker.py`:

| Feature | Detail |
|---------|--------|
| Graph building | Bipartite adjacency list (user ↔ item) — O(E) |
| Similar users | Jaccard index over shared items |
| Scoring | Weighted by similarity × rating — accumulated in hash map |
| Top-K | `heapq.nlargest(k, ...)` — O(n log k), better than full sort when k << n |

On job creation, the API:

1. Inserts a `pending` job row in PostgreSQL (with priority)
2. Dispatches a Celery task via `celery_app.send_task("process_job", [str(job.id)], queue=priority)`
3. Returns the job to the caller

The Celery worker runs in its own process, picks up tasks from the Redis broker, processes them via the appropriate handler, and updates PostgreSQL. API and worker share **only** Redis (as Celery broker) and PostgreSQL — not memory.

### Job model

**Statuses:** `pending` → `processing` → `completed` | `failed`

**Types:** `summarization`, `ocr`, `embeddings`, `transcription`, `recommendations`

**Priorities:** `high`, `normal` (default), `low`

### DSA concepts per worker

| Worker | DSA Concept | Complexity |
|--------|-------------|-----------|
| Summarization | Sliding window, divide-and-conquer recursion | O(n) chunking, O(depth) merge |
| Embeddings | Cosine similarity, brute-force nearest neighbor | O(d) per similarity, O(n*d) nearest |
| OCR | Batch pipeline, generator streaming | O(n * pixels) total, O(pixels) memory |
| Transcription | Merge intervals, timestamp alignment | O(n log n) sort + O(n) merge |
| Recommendations | Graph adjacency list, Jaccard, Top-K heap | O(E) build, O(n log k) top-K |

### Python internals learned in Stage 6

| Concept | Where Used |
|---------|-----------|
| Abstract Base Classes (`ABC`) | `base.py` — forces subclass contract |
| `Generic[InputT, ResultT]` | `base.py` — type-safe handler parameterization |
| `TypeVar` with `bound` | `base.py` — constrains generics to dict subtypes |
| Template Method pattern | `base.py` → `run()` orchestrates the steps |
| `dataclass(frozen=True, slots=True)` | `transcription_worker.py` — immutable, memory-efficient |
| `defaultdict` for graph construction | `recommendation_worker.py` |
| `heapq.nlargest` for Top-K | `recommendation_worker.py` |
| Lazy singleton pattern | `handlers.py` — one instance per job type |
| Generators for memory efficiency | `ocr_worker.py` — batch processing |

## Project structure

```
app/
├── api/jobs.py                        # REST endpoints
├── core/
│   ├── database.py                    # SQLAlchemy engine, sessions, db_session context manager
│   ├── queue.py                       # RedisJobQueue (legacy — retained, not on active path)
│   └── redis_client.py                # Shared Redis connection
├── models/job.py                      # Job ORM model, enums
├── schemas/job_schema.py              # Pydantic request/response + per-type input validation
├── services/job_service.py            # Job CRUD + Celery dispatch
├── workers/
│   ├── base.py                        # BaseJobHandler ABC (Stage 6)
│   ├── celery_app.py                  # Celery configuration (Stage 5)
│   ├── tasks.py                       # process_job task with retry backoff (Stage 5)
│   ├── handlers.py                    # Lazy handler registry → handler.run (Stage 6)
│   ├── summarization_worker.py        # SummarizationHandler: chunking + HF model
│   ├── embedding_worker.py            # EmbeddingHandler: vectors + cosine similarity (Stage 6)
│   ├── ocr_worker.py                  # OCRHandler: batch pipeline + Pillow (Stage 6)
│   ├── transcription_worker.py        # TranscriptionHandler: merge intervals (Stage 6)
│   ├── recommendation_worker.py       # RecommendationHandler: graph + heap (Stage 6)
│   ├── redis_worker.py                # Standalone Redis poll worker (legacy)
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
- ~2GB free disk for AI models (downloaded once, cached in `~/.cache/huggingface`):
  - Summarization: `facebook/bart-large-cnn` (~1.6GB)
  - Embeddings: `all-MiniLM-L6-v2` (~80MB)
- Tesseract OCR binary (optional — OCR worker falls back to simulated output without it):
  ```bash
  brew install tesseract  # macOS
  ```

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

**Example — summarization job:**

```bash
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "job_type": "summarization",
    "input": {"text": "Artificial intelligence has transformed industries ranging from healthcare to finance. In healthcare, AI systems can now detect diseases from medical images with accuracy rivaling human doctors. In finance, AI powers fraud detection systems that monitor millions of transactions in real time."},
    "priority": "high"
  }'
```

**Example — embeddings job (with similarity comparison):**

```bash
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "job_type": "embeddings",
    "input": {
      "text": "Machine learning is fascinating",
      "compare_to": "Deep learning is a subset of ML"
    }
  }'
```

**Example — embeddings batch (with nearest neighbor):**

```bash
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "job_type": "embeddings",
    "input": {
      "texts": ["cat", "dog", "car", "bicycle", "fish"],
      "compare_to": "puppy"
    }
  }'
```

**Example — transcription job (simulated):**

```bash
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "job_type": "transcription",
    "input": {
      "text": "Hello world this is a test of the transcription system with multiple words distributed across chunks",
      "duration": 120
    }
  }'
```

**Example — recommendations job:**

```bash
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "job_type": "recommendations",
    "input": {
      "user_id": "user_1",
      "top_k": 5,
      "interactions": [
        {"user_id": "user_1", "item_id": "movie_a", "rating": 5.0},
        {"user_id": "user_1", "item_id": "movie_b", "rating": 4.0},
        {"user_id": "user_2", "item_id": "movie_a", "rating": 4.5},
        {"user_id": "user_2", "item_id": "movie_c", "rating": 5.0},
        {"user_id": "user_2", "item_id": "movie_d", "rating": 3.5},
        {"user_id": "user_3", "item_id": "movie_b", "rating": 4.0},
        {"user_id": "user_3", "item_id": "movie_d", "rating": 4.5},
        {"user_id": "user_3", "item_id": "movie_e", "rating": 5.0}
      ]
    }
  }'
```

**Example — OCR job (base64 image):**

```bash
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "job_type": "ocr",
    "input": {"image": "<base64-encoded-image-string>"}
  }'
```

Poll `GET /jobs/{job_id}` to watch status move from `pending` → `processing` → `completed`.

A job with invalid input is rejected with `422`:

```bash
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"job_type": "embeddings", "input": {}}'
# 422 — "Embeddings require either 'text' (string) or 'texts' (list of strings)"
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

## What changed from Stage 5

| Stage 5 | Stage 6 |
|---------|---------|
| Stub handlers (`_ocr`, `_embeddings`, etc.) return fake results | **Real handlers** with DSA algorithms and ML models |
| Handlers are bare functions in a dict | **`BaseJobHandler` ABC** with validate → process → format contract |
| `get_handler()` returns a function directly | `get_handler()` returns `handler.run` (bound template method) |
| Only summarization validated at API level | **All 5 job types** validated at API level (`job_schema.py`) |
| Single ML model (summarization) | **Two ML models**: summarization + embeddings (`sentence-transformers`) |
| No image processing | **Pillow + pytesseract** for OCR pipeline |
| No graph algorithms | **Graph-based recommendations** with adjacency list + heap |
| No interval algorithms | **Merge intervals** for transcription segments |
| New files: — | `base.py`, `embedding_worker.py`, `ocr_worker.py`, `transcription_worker.py`, `recommendation_worker.py` |
| New dependencies: — | `sentence-transformers`, `Pillow`, `pytesseract` |

> Stage 6 changes **only** the worker layer. The API endpoints, Celery task, PostgreSQL schema, and job service are unchanged from Stage 5. `tasks.py` still calls `handler(input_payload)` — it doesn't know or care that it's now calling a class method instead of a bare function.
