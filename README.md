# AI Background Worker Platform

A backend platform for submitting, queuing, and processing AI background jobs. Runs as Docker Compose services — API, Celery worker, PostgreSQL, and Redis — with file uploads, async rate limiting, and admin observability.

## Architecture

```
docker compose up
  │
  ├── postgres
  ├── redis
  ├── api      → uvicorn :8000
  │              UPLOAD_DIR=/app/uploads ──┐
  │                                       │ shared volume
  └── worker   → celery (high,normal,low) │
                 same image, different CMD │
                 UPLOAD_DIR=/app/uploads ←─┘
```

## Features

- **Docker Compose** — one command starts API, worker, Postgres, and Redis
- **Shared image** — API and worker from the same multi-stage Dockerfile (different command)
- **File uploads** — OCR and transcription via multipart upload + Whisper
- **Async API** — FastAPI + asyncpg with Redis rate limiting and backpressure
- **Celery workers** — priority queues, retry backoff, AI handlers
- **Observability** — job logs, worker heartbeats, admin dashboard

## Quick start

**Prerequisites:** Docker Desktop (or Docker Engine + Compose)

```bash
cd ai-background-worker-platform
docker compose up --build
```

- API: `http://localhost:8000`
- Docs: `http://localhost:8000/docs`
- Examples: [`API_COLLECTION.md`](API_COLLECTION.md)

```bash
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"job_type": "summarization", "input": {"text": "Artificial intelligence has transformed industries..."}, "priority": "high"}'
```

Stop with `docker compose down` (add `-v` to remove volumes).

For local tests outside Compose:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env && cp .env.test.example .env.test
createdb ai_worker_platform_test
pytest
```

## Evolution

The file upload pipeline enabled OCR and transcription against real media on a local stack. This release **dockerizes the platform** — multi-stage image, Compose services for API and worker, health-gated Postgres/Redis, and a shared uploads volume — so the full system starts with one command.
