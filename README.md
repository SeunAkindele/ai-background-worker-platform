# AI Background Worker Platform

A backend platform for submitting, queuing, and processing AI background jobs. Supports multipart file uploads for OCR and transcription (with Whisper), async rate-limited APIs, Celery workers, and admin observability.

## Architecture

```
Client
  │
  ├──► POST /uploads          → stream · hash · dedupe → file_id
  ├──► POST /uploads/job      → upload + create OCR/transcription job
  ├──► POST /jobs             → JSON or file_id
  │
  ▼
FastAPI (async)  ──►  PostgreSQL  (jobs · job_files · logs · heartbeats)
  │
  └──►  Celery  (Redis broker)
            │
            ▼
       Workers
            ├── OCR ← uploaded images/PDFs
            └── Transcription ← Whisper on audio/video
```

## Features

- **File uploads** — multipart upload with MIME validation, 50 MB max, SHA-256 hashing, and content-hash deduplication
- **OCR / transcription jobs** — accept `file_id` (or one-shot `POST /uploads/job`); Whisper for real audio/video
- **Async API** — FastAPI + asyncpg with Redis rate limiting and pending-job backpressure
- **Celery workers** — priority queues, retry backoff, AI handlers for all job types
- **Observability** — job logs, worker heartbeats, admin dashboard

## Quick start

**Prerequisites:** Python 3.11+, Docker (PostgreSQL + Redis), ffmpeg (for Whisper)

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
# Upload then create a job
curl -X POST http://localhost:8000/uploads \
  -F "file=@sample.png" -F "purpose=ocr"

curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"job_type": "ocr", "input": {"file_id": "<FILE_ID>"}}'
```

```bash
pytest
```

## Evolution

Async APIs with rate limiting and backpressure protected the HTTP layer. This release adds a **file upload pipeline** — streaming storage, hash-based deduplication, and `file_id` wiring so OCR and transcription workers process real uploaded media (including Whisper for audio/video).
