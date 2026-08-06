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
| `GET` | `/admin/queues` | Queue stats |

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

### Queue Stats

```
GET /admin/queues
```

**Response:**

```json
{
  "queued": 0,
  "active": {},
  "reserved": {}
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

## Notes

- **Summarization** and **Embeddings** workers download ML models on first use (~1.6GB and ~80MB respectively). First job will be slow.
- **OCR** requires Tesseract installed on the system (`brew install tesseract`). Without it, returns simulated output.
- **Transcription** distributes provided `text` across time chunks with merge and timestamp alignment.
- **Recommendations** is purely algorithmic — no ML model, processes instantly.
