# API Testing Guide — All Workers

Base URL: `http://localhost:8000` (Compose / local) or `http://localhost:30080` (Kubernetes NodePort) or `http://localhost:8000` after `kubectl port-forward svc/api 8000:8000`

> **Advanced RAG (Compose):** Multi-query expand, metadata filters, cross-encoder rerank, small-to-big parent/child chunks, and optional Celery chain mode (`use_chain: true` on `POST /rag/query`). Chain step job types: `query_expand`, `rerank`, `rag_retrieve`, `rag_generate`. Chunk list responses include `level` / `parent_chunk_id`. Compose runs dedicated workers per primary job type (including `ingestion` and `rag_query`) against Postgres with **pgvector**.
>
> **Modular RAG — Stage 15 (Compose):** Enable on `POST /rag/query` or `POST /rag/query/sync` with flags: `use_router` (cache | vector | sql | web), `use_critic` + `max_critic_attempts` (self-correction loop), `use_eval` (persist RAG triad to `rag_query_metrics`). Web route calls the Compose `mcp-web` service (`MCP_WEB_URL=http://mcp-web:8080/mcp`) which exposes JSON-RPC `web_search` (Wikipedia). Inspect quality with `GET /admin/rag/dashboard`. Apply `init-db/04-stage15-modular-rag.sql` on existing DB volumes.
>
> **Deployments:** With `docker compose up`, workers share the **same image**; jobs route to a Redis queue named after `job_type`, with `priority` ordering inside that queue (Celery integers 0 / 5 / 9). Kubernetes (`kubectl apply -k infra/kubernetes/`) exposes the API on NodePort `30080` with readiness via `GET /ready`. Manifests deploy the same seven worker types as Compose, pgvector Postgres, `mcp-web`, and RAG queues on `worker-rag-query`.

---

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/jobs` | Create a job |
| `GET` | `/jobs/{job_id}` | Get job by ID (check status/result) |
| `GET` | `/jobs/{job_id}/file` | File metadata linked to a job |
| `GET` | `/jobs` | List all jobs (query: `skip`, `limit`) |
| `POST` | `/uploads` | Upload a file (`multipart`: `file`, `purpose`) |
| `POST` | `/uploads/job` | Upload + create OCR/transcription job (one-shot) |
| `GET` | `/uploads/{file_id}` | Upload metadata by file UUID |
| `POST` | `/documents/ingest` | Ingest a document into the RAG knowledge base |
| `GET` | `/documents/{document_id}` | Get document metadata/status |
| `GET` | `/documents/{document_id}/chunks` | List chunks (`level`, `parent_chunk_id` for small-to-big) |
| `POST` | `/rag/query` | Async RAG — inline or Celery chain (`use_chain`) |
| `POST` | `/rag/query/sync` | Sync advanced RAG — answer in one response (no chain) |
| `GET` | `/health` | Health check (per-type queue sizes) |
| `GET` | `/ready` | Readiness probe (Kubernetes) |
| `GET` | `/admin/dashboard` | Full system overview (jobs, workers, queues) |
| `GET` | `/admin/jobs/{job_id}/logs` | Audit trail / logs for a specific job |
| `GET` | `/admin/errors` | Recent error logs across all jobs |
| `GET` | `/admin/slowest-jobs` | Top-K slowest completed jobs |
| `GET` | `/admin/workers` | Worker health and status |
| `GET` | `/admin/rag/dashboard` | Stage 15 RAG metrics (triad, routes, critic, slow queries) |

---

## 1. Summarization Worker

### Create Job

```
POST /jobs
Content-Type: application/json
```

**Body:**

```json
{
  "job_type": "summarization",
  "priority": "high",
  "input": {
    "text": "Artificial intelligence has transformed industries ranging from healthcare to finance. In healthcare, AI systems can now detect diseases from medical images with accuracy rivaling human doctors. In finance, AI powers fraud detection systems that monitor millions of transactions in real time. The education sector has also seen significant changes, with AI tutors providing personalized learning experiences for students. Meanwhile, in transportation, autonomous vehicles are becoming increasingly common on roads around the world. These developments raise important questions about privacy, employment, and the ethical use of technology."
  }
}
```

**Expected result (after completed):**

```json
{
  "summary": "...",
  "chunks_processed": 1,
  "original_word_count": 93,
  "summary_word_count": 30
}
```

---

## 2. Embeddings Worker

### 2a. Single Text Embedding

```
POST /jobs
Content-Type: application/json
```

**Body:**

```json
{
  "job_type": "embeddings",
  "priority": "normal",
  "input": {
    "text": "Machine learning is fascinating"
  }
}
```

**Expected result:**

```json
{
  "embedding": [0.012345, -0.067890, ...],
  "dimensions": 384
}
```

### 2b. Single Text with Similarity Comparison

```
POST /jobs
Content-Type: application/json
```

**Body:**

```json
{
  "job_type": "embeddings",
  "priority": "normal",
  "input": {
    "text": "Machine learning is fascinating",
    "compare_to": "Deep learning is a subset of ML"
  }
}
```

**Expected result:**

```json
{
  "embedding": [0.012345, ...],
  "dimensions": 384,
  "similarity": 0.78,
  "compare_to_embedding": [0.034567, ...]
}
```

### 2c. Batch Embeddings with Nearest Neighbor

```
POST /jobs
Content-Type: application/json
```

**Body:**

```json
{
  "job_type": "embeddings",
  "priority": "normal",
  "input": {
    "texts": ["cat", "dog", "car", "bicycle", "fish", "airplane", "hamster"],
    "compare_to": "puppy"
  }
}
```

**Expected result:**

```json
{
  "embeddings": [[...], [...], ...],
  "count": 7,
  "dimensions": 384,
  "nearest": {
    "index": 1,
    "text": "dog",
    "similarity": 0.85
  }
}
```

---

## 3. OCR Worker

### 3a. Single Image (base64)

```
POST /jobs
Content-Type: application/json
```

**Body:**

```json
{
  "job_type": "ocr",
  "priority": "normal",
  "input": {
    "image": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
  }
}
```

> Note: The base64 above is a 1x1 transparent PNG (for testing). Use a real image with text for meaningful OCR output.

**Expected result:**

```json
{
  "text": "[extracted text or simulated output]",
  "pages": [
    {
      "page": 1,
      "text": "...",
      "confidence": 0.85,
      "width": 1,
      "height": 1
    }
  ],
  "total_pages": 1
}
```

### 3b. Batch Images

```
POST /jobs
Content-Type: application/json
```

**Body:**

```json
{
  "job_type": "ocr",
  "priority": "normal",
  "input": {
    "images": [
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    ]
  }
}
```

### 3c. File Upload (recommended)

**Step 1 — Upload the file:**

```
POST /uploads
Content-Type: multipart/form-data
```

| Field | Value |
|-------|-------|
| `purpose` | `ocr` |
| `file` | your image or PDF file |

```bash
curl -X POST http://localhost:8000/uploads \
  -F "purpose=ocr" \
  -F "file=@/path/to/invoice.png"
```

**Response (201):**

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "original_filename": "invoice.png",
  "file_type": "image/png",
  "file_size": 12345,
  "content_hash": "abc123...",
  "purpose": "ocr",
  "deduplicated": false,
  "created_at": "2026-07-10T12:00:00Z"
}
```

**Step 2 — Create OCR job with `file_id`:**

```
POST /jobs
Content-Type: application/json
```

```json
{
  "job_type": "ocr",
  "priority": "normal",
  "input": {
    "file_id": "550e8400-e29b-41d4-a716-446655440000"
  }
}
```

The API resolves `file_id` → absolute `file_path` and links the file to the job.

### 3d. One-Shot Upload + Job

```
POST /uploads/job
Content-Type: multipart/form-data
```

| Field | Value |
|-------|-------|
| `job_type` | `ocr` |
| `priority` | `normal` (optional) |
| `file` | your image or PDF file |

```bash
curl -X POST http://localhost:8000/uploads/job \
  -F "job_type=ocr" \
  -F "priority=normal" \
  -F "file=@/path/to/scan.pdf"
```

### 3e. File Path (local dev only)

```
POST /jobs
Content-Type: application/json
```

**Body:**

```json
{
  "job_type": "ocr",
  "priority": "normal",
  "input": {
    "file_path": "/path/to/your/image.png"
  }
}
```

> Use `file_id` from `/uploads` in production — `file_path` is for local testing when API and worker share the same filesystem.

---

## 4. Transcription Worker

### 4a. Simulated Transcription (text-only — no Whisper)

Use this path when you pass `text` + `duration` without a file. For real audio/video, use **4d** (Whisper).

```
POST /jobs
Content-Type: application/json
```
**Body:**

```json
{
  "job_type": "transcription",
  "priority": "normal",
  "input": {
    "text": "Welcome to this presentation on artificial intelligence. Today we will cover the basics of machine learning, deep learning, and natural language processing. These technologies are transforming how we interact with computers and how businesses operate in the modern world.",
    "duration": 120
  }
}
```

**Expected result:**

```json
{
  "transcript": "Welcome to this presentation on artificial intelligence...",
  "segments": [
    {"start": 0.0, "end": 30.0, "text": "Welcome to this presentation..."},
    {"start": 30.0, "end": 58.0, "text": "Today we will cover..."},
    {"start": 58.0, "end": 86.0, "text": "deep learning and..."},
    {"start": 86.0, "end": 114.0, "text": "transforming how..."},
    {"start": 114.0, "end": 120.0, "text": "modern world."}
  ],
  "duration": 120,
  "chunk_count": 5,
  "segment_count": 5
}
```

### 4b. Short Duration (single chunk)

```
POST /jobs
Content-Type: application/json
```

**Body:**

```json
{
  "job_type": "transcription",
  "priority": "high",
  "input": {
    "text": "This is a short audio clip for testing purposes.",
    "duration": 10
  }
}
```

### 4c. Long Duration (many chunks, tests merge intervals)

```
POST /jobs
Content-Type: application/json
```

**Body:**

```json
{
  "job_type": "transcription",
  "priority": "low",
  "input": {
    "text": "This is a longer transcription test that will generate many overlapping chunks which the merge intervals algorithm must combine into a clean non-overlapping timeline of transcript segments with aligned timestamps from start to finish without any gaps or duplicates in the final output",
    "duration": 300
  }
}
```

### 4d. File Upload + Whisper

**Step 1 — Upload audio/video:**

```
POST /uploads
Content-Type: multipart/form-data
```

| Field | Value |
|-------|-------|
| `purpose` | `transcription` |
| `file` | your audio or video file (binary — not a path string) |

```bash
curl -X POST http://localhost:8000/uploads \
  -F "purpose=transcription" \
  -F "file=@/path/to/meeting.mp3"
```

**Step 2 — Create transcription job:**

```json
{
  "job_type": "transcription",
  "priority": "normal",
  "input": {
    "file_id": "550e8400-e29b-41d4-a716-446655440000"
  }
}
```

The worker reads the file from disk, detects duration via mutagen, and runs **OpenAI Whisper** (`base` model). Segments are merged and timestamps aligned. Requires **ffmpeg** on the host.

**Expected result (shape):**

```json
{
  "transcript": "Welcome everyone to today's meeting...",
  "segments": [
    {"start": 0.0, "end": 4.2, "text": "Welcome everyone to today's meeting"},
    {"start": 4.2, "end": 9.8, "text": "We'll start with the quarterly update"}
  ],
  "duration": 62.5,
  "chunk_count": 2,
  "segment_count": 2,
  "source": {
    "type": "file",
    "path": "...",
    "original_filename": "meeting.mp3",
    "file_type": "audio/mpeg",
    "file_size": 1234567,
    "detected_duration": 62.5,
    "engine": "whisper"
  }
}
```

**One-shot:**

```bash
curl -X POST http://localhost:8000/uploads/job \
  -F "job_type=transcription" \
  -F "priority=normal" \
  -F "file=@/path/to/podcast.wav"
```

> First Whisper job downloads `base.pt` (~139MB) to `~/.cache/whisper/`. Later jobs on the same worker reuse the in-memory model.
---

## 5. Recommendations Worker

### 5a. Basic Recommendation

```
POST /jobs
Content-Type: application/json
```

**Body:**

```json
{
  "job_type": "recommendations",
  "priority": "normal",
  "input": {
    "user_id": "user_1",
    "top_k": 5,
    "interactions": [
      {"user_id": "user_1", "item_id": "movie_a", "rating": 5.0},
      {"user_id": "user_1", "item_id": "movie_b", "rating": 4.0},
      {"user_id": "user_1", "item_id": "movie_c", "rating": 3.0},
      {"user_id": "user_2", "item_id": "movie_a", "rating": 4.5},
      {"user_id": "user_2", "item_id": "movie_c", "rating": 5.0},
      {"user_id": "user_2", "item_id": "movie_d", "rating": 4.0},
      {"user_id": "user_2", "item_id": "movie_e", "rating": 3.5},
      {"user_id": "user_3", "item_id": "movie_b", "rating": 4.0},
      {"user_id": "user_3", "item_id": "movie_d", "rating": 4.5},
      {"user_id": "user_3", "item_id": "movie_e", "rating": 5.0},
      {"user_id": "user_3", "item_id": "movie_f", "rating": 3.0}
    ]
  }
}
```

**Expected result:**

```json
{
  "recommendations": [
    {"item_id": "movie_d", "score": 2.1234},
    {"item_id": "movie_e", "score": 1.8765},
    {"item_id": "movie_f", "score": 0.5432}
  ],
  "user_id": "user_1",
  "user_item_count": 3,
  "similar_users_found": 2
}
```

### 5b. Many Users (larger graph)

```
POST /jobs
Content-Type: application/json
```

**Body:**

```json
{
  "job_type": "recommendations",
  "priority": "high",
  "input": {
    "user_id": "alice",
    "top_k": 3,
    "interactions": [
      {"user_id": "alice", "item_id": "python_book", "rating": 5.0},
      {"user_id": "alice", "item_id": "js_book", "rating": 4.0},
      {"user_id": "bob", "item_id": "python_book", "rating": 4.5},
      {"user_id": "bob", "item_id": "go_book", "rating": 5.0},
      {"user_id": "bob", "item_id": "rust_book", "rating": 4.0},
      {"user_id": "carol", "item_id": "js_book", "rating": 5.0},
      {"user_id": "carol", "item_id": "ts_book", "rating": 4.5},
      {"user_id": "carol", "item_id": "react_book", "rating": 4.0},
      {"user_id": "dave", "item_id": "python_book", "rating": 3.5},
      {"user_id": "dave", "item_id": "js_book", "rating": 4.0},
      {"user_id": "dave", "item_id": "docker_book", "rating": 5.0},
      {"user_id": "dave", "item_id": "k8s_book", "rating": 4.5}
    ]
  }
}
```

### 5c. User with No History (edge case)

```
POST /jobs
Content-Type: application/json
```

**Body:**

```json
{
  "job_type": "recommendations",
  "priority": "normal",
  "input": {
    "user_id": "new_user",
    "top_k": 5,
    "interactions": [
      {"user_id": "user_1", "item_id": "item_a", "rating": 5.0},
      {"user_id": "user_2", "item_id": "item_b", "rating": 4.0}
    ]
  }
}
```

**Expected result:**

```json
{
  "recommendations": [],
  "reason": "user has no interaction history"
}
```

---

## 6. Document Ingestion & Advanced RAG

Flow: **ingest documents** → store parent/child chunks + child embeddings in Postgres/pgvector → **ask questions** with expand → retrieve → rerank → small-to-big → generate.

### 6a. Ingest a document

```
POST /documents/ingest
Content-Type: application/json
```

**Body:**

```json
{
  "title": "Python Asyncio Guide",
  "content": "Asyncio is a library to write concurrent code using the async/await syntax. An event loop runs coroutines, schedules callbacks, and handles I/O. Transfer learning is unrelated to asyncio, but both appear in modern AI stacks. Coroutines pause at await points so other tasks can run.",
  "source": "text",
  "metadata": {
    "author": "docs team",
    "department": "engineering",
    "category": "python"
  },
  "chunk_size": 512,
  "chunk_overlap": 50
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `title` | yes | Human-readable name (1–500 chars) |
| `content` | yes | Full document text to chunk + embed |
| `source` | no | Default `"text"` (`text`, `upload`, `url`, …) |
| `metadata` | no | Optional JSON object (author, tags, etc.) |
| `chunk_size` | no | Words per chunk (default `512`, range 50–2000) |
| `chunk_overlap` | no | Overlap between chunks (default `50`, range 0–500) |

**Response (201):**

```json
{
  "document": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "title": "Python Asyncio Guide",
    "source": "text",
    "status": "pending",
    "metadata": {"author": "docs team", "department": "engineering", "category": "python"},
    "chunk_size": 512,
    "chunk_overlap": 50,
    "created_at": "2026-08-04T12:00:00Z",
    "updated_at": "2026-08-04T12:00:00Z"
  },
  "job_id": "660e8400-e29b-41d4-a716-446655440001",
  "message": "Document submitted for ingestion"
}
```

Poll `GET /jobs/{job_id}` until `status` is `completed`. Document status becomes `ready` when chunks + embeddings are stored. Ingestion writes **parent** and **child** chunks; only children are embedded for ANN search.

**Expected `result_payload` (ingestion job):**

```json
{
  "document_id": "550e8400-e29b-41d4-a716-446655440000",
  "title": "Python Asyncio Guide",
  "chunks_created": 4,
  "embedding_dimensions": 384,
  "model": "all-MiniLM-L6-v2",
  "status": "ready"
}
```

```bash
curl -X POST http://localhost:8000/documents/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Python Asyncio Guide",
    "content": "Asyncio is a library to write concurrent code using async/await...",
    "source": "text",
    "metadata": {"department": "engineering"},
    "chunk_size": 512,
    "chunk_overlap": 50
  }'
```

### 6b. Get document metadata

```
GET /documents/{document_id}
```

**Response (200):** same shape as `document` in the ingest response. Status progresses `pending` → `ingesting` → `ready` (or `failed`).

### 6c. List document chunks

```
GET /documents/{document_id}/chunks?skip=0&limit=50
```

**Response (200)** — includes `level` and `parent_chunk_id` for small-to-big inspection:

```json
{
  "chunks": [
    {
      "id": "...",
      "document_id": "550e8400-e29b-41d4-a716-446655440000",
      "content": "Asyncio is a library to write concurrent code...",
      "chunk_index": 0,
      "token_count": 42,
      "level": "child",
      "parent_chunk_id": "880e8400-e29b-41d4-a716-446655440099",
      "metadata": {"start_word": 0, "end_word": 30},
      "created_at": "2026-08-04T12:00:05Z"
    }
  ],
  "total": 4,
  "document_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

### 6d. Async RAG query — inline (default)

```
POST /rag/query
Content-Type: application/json
```

**Body:**

```json
{
  "question": "How does Python asyncio work?",
  "retrieve_k": 50,
  "keep_top_n": 3,
  "document_ids": ["550e8400-e29b-41d4-a716-446655440000"],
  "metadata_filter": {"department": "engineering"},
  "use_multi_query": true,
  "use_rerank": true,
  "use_small_to_big": true,
  "use_chain": false
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `question` | yes | Question to answer (1–2000 chars) |
| `retrieve_k` | no | Candidate pool size before rerank (default `50`, range 1–100) |
| `keep_top_n` | no | Chunks kept after rerank / for generation (default `3`, range 1–10) |
| `top_k` | no | **Deprecated** alias; if set, overrides `retrieve_k` |
| `document_ids` | no | Limit search to these document UUIDs |
| `metadata_filter` | no | JSONB filter on chunk/document metadata, e.g. `{"department":"legal"}` |
| `use_multi_query` | no | Expand question into variants (default `true`) |
| `use_rerank` | no | Cross-encoder rerank of the candidate pool (default `true`) |
| `use_small_to_big` | no | Expand selected children to parent text (default `true`) |
| `use_chain` | no | `false` (default) = one `rag_query` job; `true` = Celery chain (async only) |
| `use_router` | no | Stage 15a: classify route — `cache`, `vector`, `sql`, `web` (default `false`) |
| `force_route` | no | Override router, e.g. `"sql"` or `"cache"` (demo/testing) |
| `use_critic` | no | Stage 15b: critic loop + retrieval retries (default `false`) |
| `max_critic_attempts` | no | Max critic iterations including first try (default `2`, range 1–3) |
| `use_eval` | no | Stage 15c: write RAG triad to `rag_query_metrics` (default `false`) |

**Response (202 Accepted) — inline:**

```json
{
  "job_id": "770e8400-e29b-41d4-a716-446655440002",
  "message": "RAG query submitted (inline)",
  "mode": "inline",
  "step_job_ids": null
}
```

Poll `GET /jobs/{job_id}` for the answer.

**Expected `result_payload` (inline `rag_query` job):**

```json
{
  "question": "How does Python asyncio work?",
  "answer": "...",
  "sources": [
    {
      "chunk_id": "...",
      "document_id": "550e8400-e29b-41d4-a716-446655440000",
      "document_title": "Python Asyncio Guide",
      "chunk_index": 0,
      "similarity": 0.82,
      "rerank_score": 0.91,
      "text_preview": "Asyncio is a library to write concurrent code...",
      "expanded_from_child": true
    }
  ],
  "chunks_retrieved": 3,
  "retrieve_k": 50,
  "keep_top_n": 3,
  "queries_used": ["How does Python asyncio work?", "...", "..."],
  "route": "vector",
  "model": "all-MiniLM-L6-v2",
  "observability": {
    "route": "vector",
    "route_confidence": 0.58,
    "critic_passed": true,
    "critic_attempts": 1,
    "triad": {
      "context_relevance": 0.42,
      "answer_relevance": 0.31,
      "groundedness": 0.55
    },
    "stages": []
  }
}
```

```bash
curl -X POST http://localhost:8000/rag/query \
  -H "Content-Type: application/json" \
  -d '{
    "question": "How does Python asyncio work?",
    "retrieve_k": 50,
    "keep_top_n": 3,
    "use_multi_query": true,
    "use_rerank": true
  }'
```

### 6e. Async RAG query — Celery chain (`use_chain: true`)

Creates a parent `rag_query` job plus step jobs: `query_expand` → `rag_retrieve` → `rerank` → `rag_generate`. Poll the **parent** `job_id` for the final answer; use `step_job_ids` to debug individual stages.

```json
{
  "question": "How does Python asyncio work?",
  "retrieve_k": 50,
  "keep_top_n": 3,
  "use_chain": true
}
```

**Response (202 Accepted) — chain:**

```json
{
  "job_id": "770e8400-e29b-41d4-a716-446655440002",
  "message": "RAG query submitted (Celery chain)",
  "mode": "chain",
  "step_job_ids": {
    "expand": "880e8400-e29b-41d4-a716-446655440010",
    "retrieve": "880e8400-e29b-41d4-a716-446655440011",
    "rerank": "880e8400-e29b-41d4-a716-446655440012",
    "generate": "880e8400-e29b-41d4-a716-446655440013"
  }
}
```

```bash
curl -X POST http://localhost:8000/rag/query \
  -H "Content-Type: application/json" \
  -d '{"question":"How does Python asyncio work?","use_chain":true}'
```

> Chain mode requires workers listening on `query_expand`, `rag_retrieve`, `rerank`, and `rag_generate` (or a local worker that includes those queues). Compose `worker-rag-query` handles inline `rag_query`; for chain demos locally, broaden that worker’s `--queues` list.

### 6f. Sync RAG query (answer in one response)

```
POST /rag/query/sync
Content-Type: application/json
```

Same request body as `6d`, **except** `use_chain` must be `false` / omitted. Returns **200** with the answer directly (no `job_id`). Blocks until the advanced pipeline finishes (often 2–10s+). Uses the same `RAGQueryHandler` as inline async.

**Error (400)** if `use_chain: true`:

```json
{
  "detail": "use_chain is only supported on POST /rag/query (async)"
}
```

**Response (200):**

```json
{
  "question": "How does Python asyncio work?",
  "answer": "...",
  "sources": [
    {
      "chunk_id": "...",
      "document_id": "...",
      "document_title": "Python Asyncio Guide",
      "chunk_index": 0,
      "similarity": 0.82,
      "text_preview": "Asyncio is a library..."
    }
  ],
  "chunks_retrieved": 3,
  "top_k_requested": null,
  "model": "all-MiniLM-L6-v2"
}
```

```bash
curl -X POST http://localhost:8000/rag/query/sync \
  -H "Content-Type: application/json" \
  -d '{
    "question": "How does Python asyncio work?",
    "retrieve_k": 50,
    "keep_top_n": 3,
    "metadata_filter": {"department": "engineering"}
  }'
```

### 6g. Create ingestion / rag_query jobs via `POST /jobs`

You can also enqueue these job types through the generic jobs API:

```json
{
  "job_type": "ingestion",
  "priority": "normal",
  "input": {
    "document_id": "550e8400-e29b-41d4-a716-446655440000",
    "chunk_size": 512,
    "chunk_overlap": 50
  }
}
```

```json
{
  "job_type": "rag_query",
  "priority": "normal",
  "input": {
    "question": "How does Python asyncio work?",
    "retrieve_k": 50,
    "keep_top_n": 3,
    "use_multi_query": true,
    "use_rerank": true,
    "use_small_to_big": true
  }
}
```

Chain steps use job types `query_expand`, `rerank`, `rag_retrieve`, and `rag_generate`. Prefer `POST /documents/ingest` and `POST /rag/query` — they create the document row, validate input, and wire the chain.

### 6h. Stage 15 — Modular RAG (router, critic, eval, MCP)

Stage 15 runs **inside** the same `rag_query` worker when you pass flags on `POST /rag/query` or `POST /rag/query/sync`. It does **not** replace Stage 14 — it wraps it.

**Prerequisites (existing Postgres volume):**

```bash
docker compose exec -T postgres psql -U postgres -d ai_worker_platform \
  < init-db/04-stage15-modular-rag.sql
```

Compose starts `mcp-web` at `http://localhost:8080/mcp` (JSON-RPC `tools/list` and `tools/call` for `web_search`). Inside the stack, API and workers use:

```bash
MCP_WEB_URL=http://mcp-web:8080/mcp
```

#### 6h.1 Full modular pipeline (sync demo)

```
POST /rag/query/sync
Content-Type: application/json
```

```json
{
  "question": "How does Python asyncio work?",
  "retrieve_k": 50,
  "keep_top_n": 3,
  "use_router": true,
  "use_critic": true,
  "max_critic_attempts": 2,
  "use_eval": true
}
```

```bash
curl -X POST http://localhost:8000/rag/query/sync \
  -H "Content-Type: application/json" \
  -d '{
    "question": "How does Python asyncio work?",
    "use_router": true,
    "use_critic": true,
    "use_eval": true
  }'
```

Check `result_payload.observability` (async) or the sync response fields for `route`, `critic_passed`, `critic_attempts`, `triad`, and per-stage `stages[]`.

#### 6h.2 Router — force each route

| `force_route` | Example question | Expected behavior |
|---------------|------------------|-------------------|
| `"vector"` | `"How does asyncio work?"` | Stage 14 pipeline (expand → retrieve → …) |
| `"sql"` | `"How many failed jobs?"` | Whitelist `COUNT(*)` on `jobs` table |
| `"cache"` | repeat exact question | Hit `rag_answer_cache` after first successful vector answer |
| `"web"` | `"What is the latest news?"` | MCP tool call via `McpToolCallHandler` |

```bash
# SQL route
curl -X POST http://localhost:8000/rag/query/sync \
  -H "Content-Type: application/json" \
  -d '{"question":"How many pending jobs?","use_router":true,"force_route":"sql"}'

# Web route (mcp-web → Wikipedia)
curl -X POST http://localhost:8000/rag/query/sync \
  -H "Content-Type: application/json" \
  -d '{"question":"What is the latest news about AI?","use_router":true,"force_route":"web"}'

# Cache route (run same question twice; second should be instant)
curl -X POST http://localhost:8000/rag/query/sync \
  -H "Content-Type: application/json" \
  -d '{"question":"What is asyncio?","use_router":true,"use_eval":true}'
# ... wait for completion, then run identical request again
```

#### 6h.3 Critic self-correction

Enable retries when the first answer is weak (empty context, refusal phrases, low groundedness):

```json
{
  "question": "Explain quantum entanglement in our handbook",
  "use_router": false,
  "use_critic": true,
  "max_critic_attempts": 2,
  "retrieve_k": 50
}
```

On failure, observability shows `critic_attempt_1`, `retrieve_retry_1`, and updated strategy (`retrieve_k_boost`, `drop_metadata_filter`, etc.).

#### 6h.4 Evaluation (RAG triad)

With `"use_eval": true`, each completed vector-path query inserts a row into `rag_query_metrics`:

| Metric | Meaning |
|--------|---------|
| `context_relevance` | Retrieved chunks relate to the question |
| `answer_relevance` | Answer addresses the question |
| `groundedness` | Answer tokens supported by context |

Async: enable eval, poll job, then inspect admin dashboard:

```bash
curl -X POST http://localhost:8000/rag/query \
  -H "Content-Type: application/json" \
  -d '{"question":"What is asyncio?","use_eval":true,"use_router":true}'

# after job completes
curl "http://localhost:8000/admin/rag/dashboard?window_hours=24&slow_k=5"
```

#### 6h.5 RAG admin dashboard

```
GET /admin/rag/dashboard?window_hours=24&grounding_threshold=0.25&slow_k=10
```

**Response (200):**

```json
{
  "window_hours": 24,
  "total_queries": 12,
  "retrieve_hit_rate": 0.9167,
  "rerank_lift_rate": 0.3333,
  "failed_grounding_rate": 0.0833,
  "avg_context_relevance": 0.2841,
  "avg_answer_relevance": 0.1923,
  "avg_groundedness": 0.4102,
  "avg_latency_ms": 8421.5,
  "route_counts": {"vector": 9, "sql": 2, "cache": 1},
  "critic_pass_rate": 0.875,
  "slowest_queries": [
    {
      "id": "...",
      "job_id": "...",
      "question": "How does asyncio work?",
      "route": "vector",
      "total_latency_ms": 12450.2,
      "groundedness": 0.55,
      "created_at": "2026-08-25T10:00:00Z"
    }
  ]
}
```

#### 6h.6 Stage 15 job types (internal)

These run inside `rag_query` or as standalone handlers; queues appear in `GET /health`:

| Job type | Stage | Role |
|----------|-------|------|
| `route_query` | 15a | Router handler (usually inline in `rag_query`) |
| `critic` | 15b | Answer quality gate |
| `rag_eval` | 15c | Triad metrics (inline when `use_eval`) |
| `mcp_tool_call` | 15d | External MCP web search |

You can also enqueue modular RAG via generic jobs:

```json
{
  "job_type": "rag_query",
  "priority": "normal",
  "input": {
    "question": "How many failed jobs?",
    "use_router": true,
    "force_route": "sql",
    "use_eval": true,
    "mode": "inline"
  }
}
```

---

## 7. File Upload Endpoints

### Upload a file

```
POST /uploads
Content-Type: multipart/form-data
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file` | binary file | yes | The file to upload (multipart binary — not a path string) |
| `purpose` | string | yes | `ocr` or `transcription` |

**Allowed MIME types:**

| `purpose` | Types |
|-----------|-------|
| `ocr` | PNG, JPEG, WebP, TIFF, BMP, PDF |
| `transcription` | MP3, WAV (`audio/wav`, `audio/wave`, `audio/x-wav`), OGG, FLAC, AAC, MP4, WebM, etc. |

**Max size:** 50 MB (configurable via `MAX_UPLOAD_SIZE_BYTES`)

**Deduplication:** Uploading the same file twice returns the existing record with `"deduplicated": true`.

### Get upload metadata

```
GET /uploads/{file_id}
```

### Get file linked to a job

```
GET /jobs/{job_id}/file
```

---

## 8. Check Job Status

After creating any job, use the returned `id` to poll status:

```
GET /jobs/{job_id}
```

**Response progression:**

```json
{"status": "pending", "result_payload": null}
```
→
```json
{"status": "processing", "result_payload": null}
```
→
```json
{"status": "completed", "result_payload": {"summary": "..."}}
```

Or on failure:

```json
{"status": "failed", "error_message": "...", "result_payload": null}
```

---

## 9. List All Jobs

```
GET /jobs?skip=0&limit=10
```

**Response:**

```json
{
  "jobs": [...],
  "total": 25
}
```

---

## 10. Health & Admin

### Readiness Check

```
GET /ready
```

Used by Kubernetes readiness and liveness probes on the API Deployment. Returns once the app process has started.

**Response:**

```json
{
  "status": "ready"
}
```

**Kubernetes access:**

```bash
# NodePort (default in api.yaml)
curl http://localhost:30080/ready

# Or port-forward
kubectl -n ai-worker-platform port-forward svc/api 8000:8000
curl http://localhost:8000/ready
```

### Health Check

```
GET /health
```

**Response:**

```json
{
  "status": "ok",
  "queues": {
    "summarization": 0,
    "ocr": 0,
    "embeddings": 0,
    "transcription": 0,
    "recommendations": 0,
    "ingestion": 0,
    "rag_query": 0,
    "query_expand": 0,
    "rerank": 0,
    "rag_retrieve": 0,
    "rag_generate": 0,
    "route_query": 0,
    "critic": 0,
    "rag_eval": 0,
    "mcp_tool_call": 0
  },
  "total_queued": 0
}
```

### RAG Dashboard (Stage 15 observability)

```
GET /admin/rag/dashboard?window_hours=24&grounding_threshold=0.25&slow_k=10
```

Sliding-window aggregates over `rag_query_metrics`: retrieval hit rate, rerank lift, failed grounding, route mix, critic pass rate, and slowest queries. Requires at least one query with `"use_eval": true`.

**Response:** see section **6h.5**.

`queues` = waiting Celery messages per job-type Redis list (not Postgres job counts). Completed jobs stay in PostgreSQL; they leave the Redis queue when a worker consumes the task.

> Note: with Redis priority sub-lists (`summarization:0`, etc.), plain `LLEN summarization` may under-count. Prefer job status polling for correctness.

### Dashboard (full system overview)

```
GET /admin/dashboard
```

**Response:**

```json
{
  "total_jobs": 42,
  "pending_jobs": 3,
  "processing_jobs": 1,
  "completed_jobs": 35,
  "failed_jobs": 3,
  "avg_processing_seconds": 12.345,
  "slowest_job_types": [
    {"job_type": "summarization", "total": 10, "avg_duration_seconds": 18.432},
    {"job_type": "ocr", "total": 8, "avg_duration_seconds": 14.221}
  ],
  "queue_size": 4,
  "workers": {
    "workers": [
      {
        "id": "...",
        "worker_name": "celery@myhost.12345.summarization",
        "worker_type": "summarization",
        "status": "busy",
        "last_seen_at": "2026-07-07T15:30:00Z",
        "current_job_id": "...",
        "jobs_completed": 20,
        "jobs_failed": 1
      }
    ],
    "total_online": 1,
    "total_busy": 1,
    "total_offline": 0
  }
}
```

### Job Logs (audit trail for one job)

```
GET /admin/jobs/{job_id}/logs?limit=100
```

**Response:**

```json
{
  "logs": [
    {
      "id": "...",
      "job_id": "...",
      "message": "Job picked up by worker celery@myhost.12345",
      "level": "info",
      "created_at": "2026-07-07T15:30:01Z"
    },
    {
      "id": "...",
      "job_id": "...",
      "message": "Job completed successfully in 4.231s",
      "level": "info",
      "created_at": "2026-07-07T15:30:05Z"
    }
  ],
  "total": 2
}
```

### Recent Errors (across all jobs)

```
GET /admin/errors?limit=50
```

**Response:**

```json
[
  {
    "id": "...",
    "job_id": "...",
    "message": "Attempt 1 failed: model loading error",
    "level": "error",
    "created_at": "2026-07-07T15:28:00Z"
  }
]
```

### Slowest Jobs (Top-K)

```
GET /admin/slowest-jobs?k=10
```

**Response:**

```json
[
  {
    "job_id": "...",
    "job_type": "summarization",
    "duration_seconds": 45.678
  },
  {
    "job_id": "...",
    "job_type": "ocr",
    "duration_seconds": 32.101
  }
]
```

### Worker Health

```
GET /admin/workers
```

Compose typically runs **seven** workers (one per primary type), each with `worker_type` from `WORKER_TYPE`. Kubernetes deploys the same set. The RAG worker also consumes chain and modular queues (`query_expand`, `rerank`, `rag_retrieve`, `rag_generate`, `route_query`, `critic`, `rag_eval`, `mcp_tool_call`).

**Response:**

```json
{
  "workers": [
    {
      "id": "...",
      "worker_name": "celery@3ec3b1a9670a.1.summarization",
      "worker_type": "summarization",
      "status": "online",
      "last_seen_at": "2026-07-16T15:35:00Z",
      "current_job_id": null,
      "jobs_completed": 1,
      "jobs_failed": 0
    },
    {
      "id": "...",
      "worker_name": "celery@f1ef18dae3e4.1.embeddings",
      "worker_type": "embeddings",
      "status": "online",
      "last_seen_at": "2026-07-16T15:35:00Z",
      "current_job_id": null,
      "jobs_completed": 1,
      "jobs_failed": 0
    }
  ],
  "total_online": 7,
  "total_busy": 0,
  "total_offline": 0
}
```

---

## Validation Error Examples (422)

These should all return `422 Unprocessable Entity`:

**Summarization — empty text:**
```json
{"job_type": "summarization", "input": {"text": ""}}
```

**Embeddings — missing both text and texts:**
```json
{"job_type": "embeddings", "input": {}}
```

**OCR — missing image/images/file_path/file_id:**
```json
{"job_type": "ocr", "input": {}}
```

**OCR — wrong MIME for purpose (400 on upload):**
Upload an MP3 with `purpose=ocr` → `400 Bad Request`

**Transcription — file purpose mismatch (400):**
Use an OCR-uploaded `file_id` on a transcription job → `400 Bad Request`

**Transcription — missing all input options:**
```json
{"job_type": "transcription", "input": {}}
```

**Recommendations — missing user_id:**
```json
{"job_type": "recommendations", "input": {"interactions": []}}
```

**Recommendations — missing interactions:**
```json
{"job_type": "recommendations", "input": {"user_id": "user_1"}}
```

**Ingestion — missing document_id:**
```json
{"job_type": "ingestion", "input": {}}
```

**RAG query — empty question:**
```json
{"job_type": "rag_query", "input": {"question": ""}}
```

**Document ingest — empty content (422):**
```json
{"title": "Doc", "content": ""}
```

**RAG sync — empty question (422):**
```json
{"question": ""}
```

---

## Priority Values

All `POST /jobs` requests accept an optional `priority` field:

| Value | Celery priority | Description |
|-------|-----------------|-------------|
| `"high"` | `0` | Processed first within that job-type queue |
| `"normal"` | `5` | Default |
| `"low"` | `9` | Processed last within that job-type queue |

**Routing:** queue name = `job_type` (e.g. `ocr`). Priority orders within that queue; it does not select a separate `high`/`normal`/`low` queue.

---

## 11. Rate Limiting

All endpoints are protected by a sliding window rate limiter. Default: **20 requests per 60 seconds** per client IP.

### Rate limit exceeded (429)

When you exceed the limit, any endpoint returns:

```
HTTP/1.1 429 Too Many Requests
```

**Response:**

```json
{
  "detail": {
    "error": "Rate limit exceeded",
    "limit": 20,
    "window_seconds": 60,
    "current_count": 21
  }
}
```

### Backpressure — too many pending jobs (429)

When `POST /jobs`, `POST /uploads/job`, `POST /documents/ingest`, or `POST /rag/query` is called and there are already too many pending jobs (default: 50):

```
HTTP/1.1 429 Too Many Requests
```

**Response:**

```json
{
  "detail": {
    "error": "Too many pending jobs",
    "pending_count": 50,
    "limit": 50
  }
}
```

### Testing rate limits

To trigger the rate limit, send rapid requests:

```bash
for i in $(seq 1 25); do
  curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/jobs
done
```

Requests 1-20 return `200`, requests 21+ return `429`.

---

## Notes

- **Advanced RAG:** Ingest/query via `POST /documents/ingest` and `POST /rag/query` (or `/sync`) with `retrieve_k` / `keep_top_n`, `metadata_filter`, `use_multi_query`, `use_rerank`, `use_small_to_big`, and optional `use_chain` on async query.
- **Modular RAG (Stage 15):** Add `use_router`, `force_route`, `use_critic`, `max_critic_attempts`, `use_eval` on RAG endpoints. Monitor with `GET /admin/rag/dashboard`. DB migrations for existing volumes: `init-db/02-stage14-jobtype-enum.sql`, `init-db/03-stage15-chunk-hierarchy.sql`, `init-db/04-stage15-modular-rag.sql`.
- **Compose:** `docker compose up -d`. Postgres is `pgvector/pgvector:pg16` with `CREATE EXTENSION vector`. Workers include `worker-ingestion` and `worker-rag-query`. First ingestion/RAG jobs download embedding (~80MB) and BART (~1.6GB) models.
- **Kubernetes:** `kubectl apply -k infra/kubernetes/` after loading `ai-worker-platform:latest` into the cluster. API at NodePort `30080` or via port-forward. Workers match Compose, including `worker-ingestion` and `worker-rag-query`. Postgres uses `pgvector/pgvector:pg16`. `mcp-web` serves `POST /mcp` at `http://mcp-web:8080/mcp`. Scale: `kubectl -n ai-worker-platform scale deployment worker-ocr --replicas=2`.
- **Workers:** OCR jobs are only consumed by `worker-ocr`, summarization by `worker-summarization`, ingestion by `worker-ingestion`, etc. Check `docker compose logs worker-<type>` or `kubectl logs -l worker-type=<type>` if a job stays `pending`.
- **Summarization** and **Embeddings** download ML models on first use (~1.6GB and ~80MB). First job on that worker container is slow.
- **OCR** requires Tesseract (installed in the Docker runtime image). Without it locally, returns simulated output. Supports file uploads via `POST /uploads` with `purpose=ocr`.
- **Transcription (file uploads)** uses **OpenAI Whisper** (`base`). Requires `ffmpeg` (in Docker image) and `openai-whisper`. Model caches per container. Duration via mutagen; result includes `source.engine: "whisper"`.
- **Transcription (text-only)** with `input.text` + `duration` still uses the simulated sliding-window path (no Whisper).
- **Recommendations** is purely algorithmic — no ML model, processes instantly.
- **RAG** uses `all-MiniLM-L6-v2` for embeddings and BART for answer generation, plus expand/rerank/small-to-big. Stage 15 adds router (cache/sql/web/vector), critic loop, eval triad, and MCP web client (`MCP_WEB_URL`). Prefer sync for demos; async inline for agents; `use_chain: true` for per-step jobs.
- **File uploads** are stored under `uploads/` (hash-sharded; Docker volume `upload_data`). Same file uploaded twice is deduplicated by SHA-256.
- **Rate limiting** applies to all endpoints (20 req/min per client IP by default). Configure via `RATE_LIMIT_REQUESTS` and `RATE_LIMIT_WINDOW_SECONDS` env vars.
- **Backpressure** — `POST /jobs`, `POST /uploads/job`, `POST /documents/ingest`, and `POST /rag/query` reject with 429 when pending job count exceeds `MAX_PENDING_JOBS_PER_USER` (default 50).
