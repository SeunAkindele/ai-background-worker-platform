# AI Background Worker Platform

A backend platform for submitting, queuing, and processing AI background jobs — summarization, embeddings, OCR, transcription, and recommendations. Jobs persist in PostgreSQL and run through Celery with Redis, retry backoff, and typed handlers under a shared contract.

## Architecture

```
Client
  │
  ▼
FastAPI  ──►  PostgreSQL
  │
  └──►  Celery  (Redis broker · high / normal / low queues)
            │
            ▼
       Celery worker
            ├── BaseJobHandler.run() → validate → process → format
            │     ├── SummarizationHandler
            │     ├── EmbeddingHandler
            │     ├── OCRHandler
            │     ├── TranscriptionHandler
            │     └── RecommendationHandler
            └── on failure: retry with backoff (10s → 60s)
```

## Features

- **Jobs** — create, fetch, and list jobs with typed payloads, status, and priority queues
- **Celery** — Redis-brokered dispatch with late ack, retry backoff, and idempotent execution
- **Handler contract** — shared `BaseJobHandler` (validate → process → format) with lazy registry
- **Summarization** — Hugging Face chunking + recursive merge
- **Embeddings** — sentence-transformers with cosine similarity and nearest-neighbor lookup
- **OCR** — Pillow + Tesseract batch pipeline (single or multi-image)
- **Transcription** — time-chunked segments with merge and timestamp alignment
- **Recommendations** — collaborative filtering over a user–item graph with Top-K scoring

## Quick start

**Prerequisites:** Python 3.11+, Docker (PostgreSQL + Redis). First ML jobs download models on demand.

```bash
cd ai-background-worker-platform
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

docker compose up -d
cp .env.example .env
cp .env.test.example .env.test
createdb ai_worker_platform_test

# Terminal 1 — API
uvicorn app.main:app --reload

# Terminal 2 — worker
celery -A app.workers.celery_app worker --loglevel=info -Q high,normal,low
```

- Health: `GET http://localhost:8000/health`
- Docs: `http://localhost:8000/docs`
- Examples: [`API_COLLECTION.md`](API_COLLECTION.md)

```bash
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"job_type": "summarization", "input": {"text": "Artificial intelligence has transformed industries..."}, "priority": "high"}'
```

```bash
pytest
```

## Evolution

Celery with retry backoff handled reliable dispatch for a single real summarizer. This release adds a **shared handler contract** and real workers for **embeddings, OCR, transcription, and recommendations**, each validating input and producing structured results.
