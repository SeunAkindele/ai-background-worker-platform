# API Testing Guide — All Workers

Base URL: `http://localhost:8000`

---

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/jobs` | Create a job |
| `GET` | `/jobs/{job_id}` | Get job by ID (check status/result) |
| `GET` | `/jobs` | List all jobs (query: `skip`, `limit`) |
| `GET` | `/health` | Health check |
| `GET` | `/admin/dashboard` | Full system overview (jobs, workers, queues) |
| `GET` | `/admin/jobs/{job_id}/logs` | Audit trail / logs for a specific job |
| `GET` | `/admin/errors` | Recent error logs across all jobs |
| `GET` | `/admin/slowest-jobs` | Top-K slowest completed jobs |
| `GET` | `/admin/workers` | Worker health and status |

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

### 3c. File Path (for local files)

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

---

## 4. Transcription Worker

### 4a. Simulated Transcription (with source text)

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

## 6. Check Job Status

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

## 7. List All Jobs

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

## 8. Health & Admin

### Health Check

```
GET /health
```

**Response:**

```json
{"status": "ok", "queued_jobs": 0}
```

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
        "worker_name": "celery@myhost.12345",
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

**Response:**

```json
{
  "workers": [
    {
      "id": "...",
      "worker_name": "celery@myhost.12345",
      "worker_type": "general",
      "status": "online",
      "last_seen_at": "2026-07-07T15:35:00Z",
      "current_job_id": null,
      "jobs_completed": 20,
      "jobs_failed": 1
    }
  ],
  "total_online": 1,
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

**OCR — missing image/images/file_path:**
```json
{"job_type": "ocr", "input": {}}
```

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

---

## Priority Values

All `POST /jobs` requests accept an optional `priority` field:

| Value | Description |
|-------|-------------|
| `"high"` | Processed first |
| `"normal"` | Default |
| `"low"` | Processed last |

---

## 9. Rate Limiting (Stage 8)

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

When `POST /jobs` is called and there are already too many pending jobs (default: 50):

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

- **Summarization** and **Embeddings** workers download ML models on first use (~1.6GB and ~80MB respectively). First job will be slow.
- **OCR** requires Tesseract installed on the system (`brew install tesseract`). Without it, returns simulated output.
- **Transcription** is currently simulated — distributes provided `text` across time chunks. Real Whisper integration comes in Stage 9.
- **Recommendations** is purely algorithmic — no ML model, processes instantly.
- **Rate limiting** applies to all endpoints (20 req/min per client IP by default). Configure via `RATE_LIMIT_REQUESTS` and `RATE_LIMIT_WINDOW_SECONDS` env vars.
- **Backpressure** — `POST /jobs` rejects with 429 when pending job count exceeds `MAX_PENDING_JOBS_PER_USER` (default 50).
