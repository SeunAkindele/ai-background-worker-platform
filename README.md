# AI Background Worker Platform

A backend platform for submitting, queuing, and processing AI background jobs. Docker Compose runs the API plus one Celery worker service per job type — same image, different queues — with Postgres, Redis, file uploads, and admin observability.

## Architecture

```
docker compose up
  │
  ├── postgres / redis
  ├── api                         uvicorn :8000
  │      send_task(..., queue=job_type, priority=0|5|9)
  │      UPLOAD_DIR → /app/uploads ──┐
  │                                  │ shared volume
  ├── worker-summarization           │
  ├── worker-embeddings              │
  ├── worker-ocr                     │
  ├── worker-transcription           │
  └── worker-recommendations         │
         same image, --queues=<type> │
         WORKER_TYPE=<type>          │
         UPLOAD_DIR → /app/uploads ←─┘
```

## Features

- **Per-type workers** — five Compose services (summarization, embeddings, OCR, transcription, recommendations), independently scalable
- **Shared image** — one Docker image; each worker sets `WORKER_TYPE` and consumes its own queue
- **Job-type routing** — Celery queue = `job_type`; priority via Celery integers inside each queue
- **File uploads** — OCR and transcription via multipart upload + Whisper
- **Async API** — FastAPI + asyncpg with Redis rate limiting and backpressure
- **Observability** — job logs, typed worker heartbeats, admin dashboard, per-queue health

## Quick start

**Prerequisites:** Docker Desktop (or Docker Engine + Compose)

```bash
cd ai-background-worker-platform
docker compose up --build
```

- API: `http://localhost:8000`
- Health (per-queue depths): `GET http://localhost:8000/health`
- Docs: `http://localhost:8000/docs`
- Examples: [`API_COLLECTION.md`](API_COLLECTION.md)

```bash
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"job_type": "summarization", "input": {"text": "Artificial intelligence has transformed industries..."}, "priority": "high"}'
```

Stop with `docker compose down` (add `-v` to remove volumes).

```bash
pytest
```

## Evolution

Dockerizing the platform packaged API and a single all-purpose worker. This release **splits workers by job type** — one Compose service and Redis queue per type, same image — so OCR backlog no longer blocks summarization and each worker type can scale independently.
