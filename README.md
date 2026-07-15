# AI Background Worker Platform

A staged backend platform for submitting, queuing, and processing AI background jobs (summarization, OCR, embeddings, transcription, recommendations).

**Current stage:** Stage 10 — Dockerize the Platform

## Stage 10 scope (latest)

Stage 10 packages the **whole platform** into Docker Compose: API, Celery worker, PostgreSQL, and Redis start with one command. Same image for API and worker (different `command`); shared volume for uploads.

| Area | Status |
|------|--------|
| **Multi-stage `Dockerfile` (builder + runtime)** | **Done** |
| **CPU PyTorch install (avoid huge CUDA wheels)** | **Done** |
| **`.dockerignore` for lean build context** | **Done** |
| **Compose services: `api` + `worker` (+ postgres/redis)** | **Done** |
| **Health-gated `depends_on`** | **Done** |
| **Shared `upload_data` volume (API write / worker read)** | **Done** |
| **Service DNS (`postgres`, `redis`) instead of localhost inside containers** | **Done** |
| **Separate worker images / gunicorn / K8s** | Stage 11–12 |

### What changed from Stage 9

| Stage 9 | Stage 10 |
|---------|----------|
| Compose only ran Postgres + Redis | Compose also runs **api** and **worker** |
| Local `uvicorn` + local `celery` required | **`docker compose up`** starts everything |
| Host OS needed tesseract/ffmpeg for workers | Runtime image installs **tesseract** + **ffmpeg** |
| `torch` from default PyPI (CUDA-heavy) | **CPU torch** from `download.pytorch.org/whl/cpu` |
| Uploads only on host `uploads/` | Shared Docker volume **`upload_data:/app/uploads`** |

### Architecture (Stage 10)

```
docker compose up
  │
  ├── postgres          (healthy → others start)
  ├── redis             (healthy → others start)
  ├── api               uvicorn on 0.0.0.0:8000
  │      DATABASE_URL → postgres:5432
  │      REDIS_URL    → redis:6379
  │      UPLOAD_DIR   → /app/uploads  ──┐
  │                                     │ shared volume
  └── worker            celery solo     │
         same image, different command  │
         queues: high,normal,low        │
         UPLOAD_DIR → /app/uploads  ←───┘
```

### System design / Python focus (Stage 10)

| Concept | Where |
|---------|--------|
| Service boundaries | API vs worker vs infra in Compose |
| Container networking | Hostnames `postgres` / `redis` |
| Multi-stage builds | Builder compiles deps; runtime stays lean |
| Layer caching | `COPY requirements.txt` before `COPY . .` |
| Module paths | `WORKDIR /app` → imports like `app.main` |

## Stage 9 scope

Stage 9 adds a **file upload pipeline** so OCR and transcription jobs can work with real files (images, PDFs, audio, video) instead of only JSON payloads.

| Area | Status |
|------|--------|
| **Multipart file upload (`POST /uploads`)** | **Done** |
| **One-shot upload + job (`POST /uploads/job`)** | **Done** |
| **`job_files` table (metadata + SHA-256 hash)** | **Done** |
| **Streaming upload (8 KB chunks, O(chunk_size) memory)** | **Done** |
| **SHA-256 hashing during upload** | **Done** |
| **Deduplication by content hash** | **Done** |
| **MIME type validation per purpose (OCR vs transcription)** | **Done** |
| **Max upload size (default 50 MB)** | **Done** |
| **Jobs accept `file_id` in input → resolve to `file_path`** | **Done** |
| **`GET /jobs/{job_id}/file` — linked file metadata** | **Done** |
| **`GET /uploads/{file_id}` — upload metadata** | **Done** |
| **OCR worker reads uploaded files from disk** | **Done** |
| **Transcription worker reads file duration via mutagen** | **Done** |
| **Real Whisper transcription for uploaded audio/video** | **Done** (`openai-whisper`, `base` model) |
| **Simulated transcription path kept for text-only jobs** | **Done** (`input.text` + `duration`) |

### What changed from Stage 8

| Stage 8 | Stage 9 |
|---------|---------|
| JSON-only job input | **File uploads** for OCR and transcription |
| No file storage | **Local disk storage** under `uploads/` (hash-sharded paths) |
| OCR: base64 / local path only | OCR: **`file_id`** from upload API |
| Transcription: simulated text only | Transcription: **Whisper** on real audio/video; simulated path for text-only jobs |
| Single `jobs` table | Added **`job_files`** table linked to jobs |
| No deduplication | **Content-hash dedup** — same bytes uploaded twice → one stored file |

### File upload flow

```
Client
  │
  ├──► POST /uploads (multipart: file + purpose)
  │         │
  │         ├── stream to disk in 8 KB chunks
  │         ├── SHA-256 hash while streaming
  │         ├── dedup if hash already exists
  │         └── return file_id + metadata
  │
  ├──► POST /jobs  {"job_type":"ocr","input":{"file_id":"..."}}
  │         │
  │         ├── resolve file_id → absolute file_path
  │         ├── link job_files.job_id
  │         └── dispatch Celery task
  │
  └──► POST /uploads/job (one-shot: upload + create job)
            │
            └── same as above, single request
```

### Allowed file types

| Purpose | MIME types |
|---------|-----------|
| **OCR** | `image/png`, `image/jpeg`, `image/webp`, `image/tiff`, `image/bmp`, `application/pdf` |
| **Transcription** | `audio/mpeg`, `audio/wav`, `audio/wave`, `audio/x-wav`, `audio/ogg`, `audio/flac`, `audio/aac`, `video/mp4`, `video/webm`, etc. |

### DSA concepts in Stage 9

| Concept | Where Used |
|---------|-----------|
| Streaming | `save_upload()` — read/write in fixed-size chunks |
| Buffering | 8 KB `upload_chunk_size` — balances syscalls vs memory |
| SHA-256 hashing | Incremental hash during upload — O(n) time, O(1) extra space |
| Deduplication | Hash → DB lookup → skip storing duplicate bytes |
| Hash-sharded directories | `uploads/ab/<hash>.ext` — avoids flat directory bloat |

### Python internals in Stage 9

| Concept | Where Used |
|---------|-----------|
| File objects + context managers | `with path.open("rb")` in chunk readers |
| Generators | `iter_file_chunks()` — lazy byte streaming |
| `UploadFile` (SpooledTemporaryFile) | FastAPI multipart — small files in RAM, large spill to disk |
| Immutable bytes | Each chunk from `read()` is safe to hash without copy issues |

## Stage 8 scope

Stage 8 makes the API layer **non-blocking and protected**. All routes are now `async def` backed by an async SQLAlchemy engine (`asyncpg`), allowing hundreds of concurrent connections without thread exhaustion. A Redis-based sliding window rate limiter protects every endpoint, and a backpressure mechanism prevents any single client from flooding the queue.

| Area | Status |
|------|--------|
| **Async FastAPI routes (`async def` + `await`)** | **Done** |
| **Async SQLAlchemy engine (`asyncpg` driver)** | **Done** |
| **Async DB dependency (`get_async_db`)** | **Done** |
| **Async service methods (`async_create_job`, `async_get_job`, etc.)** | **Done** |
| **Sliding window rate limiter (Redis-based, per-client IP)** | **Done** |
| **Backpressure: max pending jobs limit (global)** | **Done** |
| **429 Too Many Requests responses** | **Done** |
| **Async engine disposal on shutdown** | **Done** |
| Workers remain synchronous (CPU-bound, separate processes) | Intentional |

| Stage 7 | Stage 8 |
|---------|---------|
| Sync routes (`def`) block a thread per request | **Async routes (`async def`)** — event loop handles hundreds concurrently |
| `psycopg2` only (sync driver) | Added **`asyncpg`** (async driver) for API; workers still use `psycopg2` |
| Single `get_db` dependency | Added **`get_async_db`** (async session) for routes |
| No request throttling | **Sliding window rate limiter** — 20 req/min per client (configurable) |
| No queue backpressure | **Max pending jobs limit** — rejects new submissions when global pending count is full |
| No 429 responses | All endpoints return **429 Too Many Requests** when limits exceeded |
| Services only had sync methods | Services now have **dual interface** (async for API, sync for workers) |
| `SQLAlchemy .query()` in routes | Routes use **SQLAlchemy 2.0 `select()` API** (required for async) |

> Stage 8 makes the **API layer efficient** without touching the workers. Workers remain synchronous (CPU-bound AI work doesn't benefit from async). The worker handlers, task flow, heartbeat system, and observability are unchanged.

### Architecture (Stage 8)

```
Client
  │
  │  (rate limit: sliding window counter in Redis)
  │  (backpressure: max pending jobs check)
  │
  ▼
FastAPI (async)  ──►  PostgreSQL (via asyncpg — non-blocking)
  │                     ├── jobs
  │                     ├── job_logs
  │                     └── worker_heartbeats
  │
  ├──►  /jobs (POST)          → rate limit → backpressure check → async create
  ├──►  /jobs/{id} (GET)      → rate limit → async fetch
  ├──►  /admin/dashboard      → rate limit → async aggregation
  ├──►  /admin/workers        → rate limit → async staleness check + fetch
  │
  └──►  celery_app.send_task("process_job", [job_id], queue=priority)
            │                              ↑ still sync (< 1ms Redis LPUSH)
            ▼
       Redis (Celery broker)    Redis (rate limit keys: rate:{client}:{window})
            │
            ▼
       Celery worker (SYNC — separate process, CPU-bound AI work)
            ├── uses psycopg2 (sync driver)
            ├── uses db_session() (sync context manager)
            └── unchanged from Stage 7
```

### Rate limiting (DSA: sliding window counter)

```
Algorithm:
1. Time divided into fixed windows (default 60s)
2. Each window has a Redis key: rate:{client_ip}:{window_number}
3. Estimated rate = prev_window_count × overlap_fraction + curr_window_count
4. If estimated_rate >= limit → reject with 429

Why sliding window (not fixed window)?
- Fixed window allows burst at boundaries: 20 req at second 59 + 20 at second 61 = 40 in 2s
- Sliding window smooths this by weighting the previous window's count
```

### Backpressure

```
On POST /jobs:
1. Count all pending jobs in PostgreSQL (global, not per-client yet)
2. If count >= MAX_PENDING_JOBS_PER_USER (default 50) → reject with 429
3. Otherwise → create the job

Note: the env var name says "per_user" but the current implementation
counts total pending jobs system-wide. Per-client backpressure would
require a submitted_by column on the Job model.

This prevents:
- Queue starvation (flooding the queue with too many pending jobs)
- Unbounded memory growth in Redis
- Worker overload
```

### Python internals learned in Stage 8

| Concept | Where Used |
|---------|-----------|
| `async def` / `await` | All API routes — coroutines that suspend on I/O |
| Event loop | Uvicorn's asyncio loop handles hundreds of concurrent requests on one thread |
| Async generators (`async def` + `yield`) | `get_async_db` — FastAPI uses it as async context manager dependency |
| `@property` descriptor | `config.py` — `async_database_url` derived from `database_url` |
| Coroutine cost (~200 bytes) vs thread cost (~8MB) | Why async scales for I/O-bound API work |
| GIL irrelevance for async | Async is single-threaded by design; GIL only matters for threads |
| When NOT to use async | CPU-bound worker code — async adds overhead with zero benefit |
| SQLAlchemy 2.0 `select()` API | Required for async sessions (`.query()` triggers sync I/O internally) |

### DSA concepts in Stage 8

| Concept | Where Used | Complexity |
|---------|-----------|-----------|
| Sliding window counter | `rate_limiter.py` — per-client rate limiting | O(1) per check |
| Token bucket (alternative) | Discussed in rate_limiter.py comments | O(1) per check |
| Backpressure / bounded buffer | `dependencies.py` — max pending jobs | O(1) query (indexed) |
| DAG resolution | FastAPI dependency graph (Depends chain) | Framework-level |
| Atomic increment | Redis `INCR` — no race conditions | O(1) |

## Previous stages

| Stage | Theme | Key Additions |
|-------|-------|---------------|
| 1 | FastAPI + PostgreSQL | Job CRUD, in-memory FIFO queue, clean structure |
| 2 | Local worker | Priority queue (`heapq`), fake worker, decorators |
| 3 | Redis queue | `RedisJobQueue`, producer-consumer, Docker Compose |
| 4 | Real summarization | HF BART model, sliding window chunking, lazy loading |
| 5 | Celery | Task dispatch, retry backoff, named queues, idempotency |
| 6 | Multi-worker platform | `BaseJobHandler` ABC, all 5 AI handlers, lazy registry |
| 7 | Observability | `job_logs`, `worker_heartbeats`, admin API, timing decorators |
| 8 | Async FastAPI | Async routes, asyncpg, rate limiting, backpressure |
| 9 | File uploads | Multipart uploads, `job_files`, streaming, SHA-256 dedup |
| 10 | Dockerize | Multi-stage image, Compose api/worker, CPU torch, shared uploads |

### Architecture (Stage 7)

```
Client
  │
  ▼
FastAPI  ──►  PostgreSQL
  │             ├── jobs           (status, priority, payloads, timestamps)
  │             ├── job_logs       (per-job audit trail: message, level, timestamp)
  │             └── worker_heartbeats (worker liveness: status, current_job, counters)
  │
  ├──►  /admin/dashboard        → aggregated metrics (job counts, queue size, workers)
  ├──►  /admin/jobs/{id}/logs   → audit trail for one job
  ├──►  /admin/errors           → recent failures across all jobs
  ├──►  /admin/slowest-jobs     → Top-K slowest jobs (heapq)
  ├──►  /admin/workers          → worker health (online/busy/offline)
  │
  └──►  celery_app.send_task("process_job", [job_id], queue=priority)
            │
            ▼
       Redis (Celery broker — named queues: high, normal, low)
            │
            ▼
       Celery worker  (celery -A app.workers.celery_app worker)
            │
            ├── heartbeat thread (pulse every 60s — keeps idle workers ONLINE)
            ├── on startup: start heartbeat thread
            ├── on shutdown: mark OFFLINE immediately
            │
            ├── load job from PostgreSQL
            ├── idempotency check (skip if already completed / failed)
            ├── mark processing + log "picked up by worker X"
            ├── beat(status=BUSY, current_job_id=...)
            ├── get_handler(job_type) → returns handler.run (bound method)
            │     │
            │     ▼
            │   BaseJobHandler.run()  ← wrapped in timed_block()
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
            ├── on success: mark completed + log duration + record_completion
            └── on failure: log error + retry with backoff (10s → 60s)
                  └── after max retries: mark failed + log + record_completion
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
| **Transcription** | `transcription_worker.py` | Merge intervals (O(n log n)), timestamp alignment; Whisper for real files | OpenAI Whisper (`base`) + simulated text-only path |
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

The task lives in `app/workers/tasks.py` (updated in Stage 7 to emit logs and heartbeats):

| Concept | Detail |
|---------|--------|
| **Dispatch** | `job_service.create_job()` commits the job to PostgreSQL, then calls `celery_app.send_task("process_job", [str(job.id)], queue=priority)`. |
| **Idempotency** | If the job is missing or in a terminal state, the task returns immediately. |
| **Retry backoff** | 10 s after 1st failure, 60 s after 2nd. After 3 total attempts → `failed`. |
| **Late ack** | `task_acks_late=True` + `worker_prefetch_multiplier=1`. |
| **Handler call** | `handler = get_handler(job.job_type)` returns `handler.run`, then `result = handler(input_payload)` triggers validate → process → format. |
| **Job logs** | Every lifecycle transition (picked up, failed attempt, permanently failed, completed) writes a `job_logs` row. |
| **Heartbeat** | On pickup: `beat(status=BUSY, current_job_id=...)`. On completion/failure: `record_completion()`. |
| **Timing** | Processing wrapped in `timed_block()` — exact duration logged on success. |
| **Worker identity** | `get_process_worker_name()` returns `celery@{hostname}.{pid}` — stable per process, matches the heartbeat thread. |

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

### Observability (Stage 7)

#### Job logs

Every job gets a structured audit trail in the `job_logs` table. Each row has `job_id`, `message`, `level` (info/warning/error/debug), and `created_at`. Logs are written during task execution — not via Python's `logging` module — so they survive in PostgreSQL and are queryable per job via `GET /admin/jobs/{job_id}/logs`.

#### Worker heartbeats

Workers maintain liveness via two mechanisms:

| Mechanism | When | What it does |
|-----------|------|-------------|
| `beat()` | Job pickup | Sets `status=BUSY`, `current_job_id`, `worker_type` |
| `pulse()` | Every 60s (background thread) | Refreshes `last_seen_at` only — preserves BUSY state mid-job |
| `record_completion()` | Job success/failure | Increments counters, clears `current_job_id`, sets `status=ONLINE` |
| `mark_offline()` | Graceful shutdown | Immediately marks worker OFFLINE |

Both `beat()` and `pulse()` share a private `_upsert()` method — no duplicated logic.

The heartbeat thread uses `threading.Event` for clean shutdown and exponential backoff (capped at 5 minutes) when the database is unreachable.

**Staleness detection:** `mark_stale_workers_offline()` marks any worker whose `last_seen_at` is older than 2 minutes as OFFLINE. With the periodic pulse, only truly dead workers (crashed processes) hit this — idle workers stay ONLINE.

#### Worker lifecycle signals

| Signal | Pool | Action |
|--------|------|--------|
| `worker_process_init` | Prefork | Start heartbeat thread in each child |
| `worker_process_shutdown` | Prefork | Stop thread, mark OFFLINE |
| `worker_ready` | Solo | Start heartbeat thread in main process |
| `worker_shutdown` | Solo | Stop thread, mark OFFLINE |

#### Admin dashboard

`GET /admin/dashboard` aggregates across all tables:

| Metric | How it's computed |
|--------|------------------|
| Job counts by status | `GROUP BY status` — hash map aggregation, O(n) |
| Average processing time | `AVG(updated_at - created_at)` for completed jobs |
| Slowest job types | `GROUP BY job_type` + `heapq.nlargest(k)` — O(n log k) |
| Queue size | Sum of `LLEN` across Redis priority queues |
| Worker health | From `worker_heartbeats` table after marking stale workers |

#### Decorators and context managers

| Tool | File | Purpose |
|------|------|---------|
| `timed_block(label)` | `decorators.py` | Context manager — times a code block, exposes `timer.elapsed` after `with` block |
| `log_execution_time` | `decorators.py` | Decorator — logs function duration |
| `monitor_task` | `decorators.py` | Decorator — logs start/success/failure with timing |
| `TimerResult` | `decorators.py` | Mutable container with `__slots__` — holds elapsed time |

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
| File uploads | `file_id` from `POST /uploads` with `purpose=transcription` |
| Real transcription | **OpenAI Whisper** (`base` model) on uploaded audio/video |
| Model loading | Lazy singleton — download once to `~/.cache/whisper/`, load once per Celery worker process |
| Duration | Detected via mutagen (with size-based fallback) |
| Post-processing | Merge overlapping segments + timestamp alignment |
| Text-only jobs | Still supported via `input.text` + `duration` (simulated sliding-window path) |
| System dependency | **ffmpeg** required by Whisper for audio decoding (`brew install ffmpeg`) |

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

### DSA concepts in Stage 7

| Concept | Where Used | Complexity |
|---------|-----------|-----------|
| Hash map aggregation | `admin_service.get_dashboard()` — GROUP BY status | O(n) scan, O(1) lookup |
| Top-K via heap | `admin_service.get_top_k_slowest_jobs()` — `heapq.nlargest` | O(n log k) |
| Sliding window (time) | `heartbeat_service.mark_stale_workers_offline()` — time-based cutoff | O(n) scan |
| B-tree index lookup | `job_logs.job_id` index, `worker_heartbeats.worker_name` index | O(log n) |
| Append-only log | `job_logs` table — write once, read many, ordered by time | O(1) write |

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

### Python internals learned in Stage 7

| Concept | Where Used |
|---------|-----------|
| Context manager (`@contextmanager`) | `decorators.py` — `timed_block` with mutable result via yield |
| `__slots__` | `decorators.py` — `TimerResult` uses fixed-layout struct, no `__dict__` |
| Mutable reference via yield | `TimerResult` is mutated after yield, caller sees updated `elapsed` |
| Decorator stacking | `monitor_task` designed to layer on top of `@celery_app.task` |
| `threading.Event` | `worker_signals.py` — clean shutdown of heartbeat loop |
| Exponential backoff | `worker_signals.py` — `interval * 2^failures`, capped at 5 min |
| Celery signals | `worker_signals.py` — `worker_process_init`, `worker_ready`, `worker_shutdown` |
| Upsert pattern | `heartbeat_service._upsert()` — SELECT then UPDATE or INSERT |

## Project structure

```
app/
├── api/
│   ├── jobs.py                        # Async job CRUD + file metadata (Stage 9)
│   ├── uploads.py                     # Multipart file upload endpoints (Stage 9)
│   └── admin.py                       # Async admin endpoints + rate limiting (Stage 8)
├── core/
│   ├── database.py                    # Sync + async engines, sessions, dependencies (Stage 8)
│   ├── file_storage.py                # Streaming upload, hashing, dedup (Stage 9)
│   ├── rate_limiter.py                # Sliding window counter rate limiter (Stage 8)
│   ├── dependencies.py                # Rate limit + backpressure FastAPI deps (Stage 8)
│   └── redis_client.py                # Shared Redis connection
├── models/
│   ├── __init__.py                    # Imports all models for create_all
│   ├── job.py                         # Job ORM model, enums
│   ├── job_file.py                    # JobFile ORM model (Stage 9)
│   ├── job_log.py                     # JobLog ORM model (Stage 7)
│   └── worker_heartbeat.py            # WorkerHeartbeat ORM model (Stage 7)
├── schemas/
│   ├── job_schema.py                  # Pydantic request/response + per-type input validation
│   ├── file_schema.py                 # Upload response schemas (Stage 9)
│   └── admin_schema.py                # Admin response schemas (Stage 7)
├── services/
│   ├── job_service.py                 # Async API + sync worker methods + Celery dispatch
│   ├── file_service.py                # Upload save, dedup lookup, job linking (Stage 9)
│   ├── log_service.py                 # Async reads + sync add_log for workers (Stage 8)
│   ├── heartbeat_service.py           # Async staleness check + sync worker heartbeats (Stage 8)
│   └── admin_service.py               # Async dashboard aggregation (Stage 8)
├── workers/
│   ├── base.py                        # BaseJobHandler ABC (Stage 6)
│   ├── celery_app.py                  # Celery configuration + signal registration (Stage 5/7)
│   ├── tasks.py                       # process_job task with logging + heartbeats (Stage 5/7)
│   ├── handlers.py                    # Lazy handler registry → handler.run (Stage 6)
│   ├── worker_identity.py             # Stable per-process worker name (Stage 7)
│   ├── worker_signals.py              # Celery signals: heartbeat thread + shutdown (Stage 7)
│   ├── decorators.py                  # timed_block, log_execution_time, monitor_task (Stage 7)
│   ├── summarization_worker.py        # SummarizationHandler: chunking + HF model
│   ├── embedding_worker.py            # EmbeddingHandler: vectors + cosine similarity (Stage 6)
│   ├── ocr_worker.py                  # OCRHandler: batch pipeline + Pillow (Stage 6)
│   ├── transcription_worker.py        # TranscriptionHandler: merge intervals (Stage 6)
│   └── recommendation_worker.py       # RecommendationHandler: graph + heap (Stage 6)
├── config.py                          # Settings + upload config (Stage 9)
└── main.py                            # Async lifespan, routers, v0.10.0
tests/
├── conftest.py                        # Fake Redis, mock Celery, temp upload dir
├── test_jobs.py
├── test_uploads.py                    # File upload + file_id job flow (Stage 9)
├── test_file_storage.py               # Chunking + hashing helpers (Stage 9)
├── test_celery_dispatch.py            # Priority queue → Celery queue names
├── test_worker.py                     # process_job task (handler mocked)
└── test_summarization.py              # SummarizationHandler (model mocked)
Dockerfile                             # Multi-stage API/worker image (Stage 10)
.dockerignore                          # Excludes .venv, uploads, etc. from build context
docker-compose.yml                     # PostgreSQL + Redis + api + worker (Stage 10)
uploads/                               # Local file storage (gitignored; volume in Docker)
```

## Prerequisites

- Docker Desktop (or Docker Engine + Compose)
- For **local (non-Docker) runs** only: Python 3.11+, Tesseract, ffmpeg, and pip deps
- ~2GB+ free disk for Docker images and AI models (downloaded once, then cached):
  - Summarization: `facebook/bart-large-cnn` (~1.6GB)
  - Embeddings: `all-MiniLM-L6-v2` (~80MB)
  - Transcription: Whisper `base` (~139MB)
- Inside Docker, **tesseract** and **ffmpeg** are installed in the runtime image — no Homebrew required for Compose runs

> **Note on `torch`:** Stage 10 installs **CPU torch** in the Dockerfile (`--index-url https://download.pytorch.org/whl/cpu`). `torch` is commented out in `requirements.txt` so pip does not pull multi‑GB CUDA wheels. Local venv installs should install CPU torch the same way if needed.

> **Note on `openai-whisper` / `llvmlite` (local installs):** If `pip install` tries to build `llvmlite` from source and fails (missing `cmake`), prefer binary wheels:
> ```bash
> pip install --only-binary=llvmlite,numba -r requirements.txt
> ```

## Setup

### Option A — Full Docker (Stage 10, recommended)

```bash
cd ai-background-worker-platform

# Build images and start postgres, redis, api, worker
docker compose up --build

# Detached:
# docker compose up -d --build
```

Compose injects `DATABASE_URL` / `REDIS_URL` / `UPLOAD_DIR` for containers. Host `.env` is for local runs outside Docker.

- API: `http://localhost:8000`
- Health: `GET http://localhost:8000/health`
- Docs: `http://localhost:8000/docs`

Stop with `docker compose down` (add `-v` to wipe volumes).

### Option B — Local API/worker + Docker infra only

```bash
cd ai-background-worker-platform

python -m venv .venv
source .venv/bin/activate

# CPU torch first (same as Dockerfile), then the rest
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt

# Infra only (comment out or leave api/worker unused — or use docker compose up postgres redis)
docker compose up -d postgres redis

cp .env.example .env
# DATABASE_URL=postgresql://postgres:postgres@localhost:5432/ai_worker_platform
# REDIS_URL=redis://localhost:6379/0

cp .env.test.example .env.test
createdb ai_worker_platform_test   # for pytest
```

## Running the platform

### Docker (one command)

```bash
docker compose up
# or: docker compose up --build   # after Dockerfile / requirements changes
```

### Local processes (two terminals)

**Terminal 1 — API:**

```bash
uvicorn app.main:app --reload
```

**Terminal 2 — Celery worker:**

```bash
celery -A app.workers.celery_app worker --loglevel=info --pool=solo --queues=high,normal,low
```

- Health: `GET http://localhost:8000/health`
- Dashboard: `GET http://localhost:8000/admin/dashboard`
- Interactive docs: `http://localhost:8000/docs`

Tables are created automatically on startup via `init_db()`.

> **First ML jobs are slow.** Summarization downloads ~1.6GB; Whisper transcription downloads ~139MB. In Docker these caches live inside the worker container unless you mount a cache volume. Models load once per worker process and stay in RAM for later jobs.
## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness + number of queued Celery tasks |
| `POST` | `/jobs` | Create a job (`job_type`, `input`, optional `priority`) |
| `GET` | `/jobs/{job_id}` | Fetch a job by UUID |
| `GET` | `/jobs/{job_id}/file` | File metadata linked to a job (Stage 9) |
| `GET` | `/jobs` | List jobs (`skip`, `limit`; returns `jobs` + `total`) |
| `POST` | `/uploads` | Upload a file (`multipart`: `file`, `purpose`) (Stage 9) |
| `POST` | `/uploads/job` | Upload + create OCR/transcription job in one request (Stage 9) |
| `GET` | `/uploads/{file_id}` | Upload metadata by file UUID (Stage 9) |
| `GET` | `/admin/dashboard` | Full system overview (job counts, queue size, workers) |
| `GET` | `/admin/jobs/{job_id}/logs` | Audit trail for a specific job (`skip`, `limit`) |
| `GET` | `/admin/errors` | Recent error logs across all jobs (`skip`, `limit`) |
| `GET` | `/admin/slowest-jobs` | Slowest completed jobs (`skip`, `limit`) |
| `GET` | `/admin/workers` | Worker health and status |

**Quick example — summarization job:**

```bash
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "job_type": "summarization",
    "input": {"text": "Artificial intelligence has transformed industries..."},
    "priority": "high"
  }'
```

**Quick example — OCR with file upload (Stage 9):**

```bash
# Step 1: upload
curl -X POST http://localhost:8000/uploads \
  -F "purpose=ocr" \
  -F "file=@/path/to/invoice.png"

# Step 2: create job with returned file_id
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"job_type":"ocr","input":{"file_id":"YOUR-FILE-UUID"}}'

# Or one-shot:
curl -X POST http://localhost:8000/uploads/job \
  -F "job_type=ocr" \
  -F "priority=normal" \
  -F "file=@/path/to/invoice.png"
```

**Quick example — Whisper transcription with file upload (Stage 9):**

```bash
# One-shot upload + job (requires ffmpeg + Whisper model)
curl -X POST http://localhost:8000/uploads/job \
  -F "job_type=transcription" \
  -F "priority=normal" \
  -F "file=@/path/to/meeting.mp3"
```

Poll `GET /jobs/{job_id}` to watch status move from `pending` → `processing` → `completed`. Completed file jobs include `source.engine: "whisper"` in `result_payload`.

> For full request examples for all 5 worker types (including batch, edge cases, and validation errors), see [`API_COLLECTION.md`](API_COLLECTION.md).

## Tests

Tests use `.env.test`, a dedicated PostgreSQL database, and **fakeredis** (no real Redis required for `pytest`).

```bash
pytest
```

Coverage includes job CRUD, file uploads (Stage 9), Celery dispatch, summarization logic (HF pipeline mocked), and rate-limit/backpressure behaviour. Tests use **fakeredis** and mock Celery `send_task` — no running worker required for `pytest`.

## Environment variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | — |
| `REDIS_URL` | Redis connection string (Celery broker + rate limiter) | — |
| `APP_ENV` | `development` or `test` | `development` |
| `RATE_LIMIT_REQUESTS` | Max requests per client per window | `20` |
| `RATE_LIMIT_WINDOW_SECONDS` | Rate limit window duration | `60` |
| `MAX_PENDING_JOBS_PER_USER` | Max total pending jobs before rejecting new submissions (global count) | `50` |
| `UPLOAD_DIR` | Directory for uploaded files | `uploads` (Compose sets `/app/uploads`) |
| `MAX_UPLOAD_SIZE_BYTES` | Max file upload size in bytes | `52428800` (50 MB) |
| `UPLOAD_CHUNK_SIZE` | Chunk size for streaming reads/writes | `8192` (8 KB) |

See `.env.example` and `.env.test.example` for templates.
