# AI Background Worker Platform

A backend platform for submitting, queuing, and processing AI background jobs. Jobs persist in PostgreSQL, queue in Redis by priority, and run in a separate worker process. Summarization uses a Hugging Face model with sliding-window chunking for long text.

## Architecture

```
Client
  │
  ▼
FastAPI  ──►  PostgreSQL  (job records)
  │
  └──►  Redis  (pending · processing · retry · failed)
            │
            ▼
       RedisWorker
            │
            └── summarization → chunk → HF model → merge
```

## Features

- **Jobs** — create, fetch, and list jobs with typed payloads, status, and `high` / `normal` / `low` priority
- **Redis queue** — durable priority scheduling with processing, retry, and failed tracking
- **Workers** — standalone Redis worker process
- **Summarization** — Hugging Face `facebook/bart-large-cnn` with overlapping chunking and recursive merge for long documents
- **Validation** — summarization jobs require non-empty `input.text`
- **Queue stats** — `/health` and `/admin/queues`

## Quick start

**Prerequisites:** Python 3.11+, Docker (PostgreSQL + Redis). First summarization job downloads the model (~1.6GB).

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
python -m app.workers.redis_worker
```

- Health: `GET http://localhost:8000/health`
- Docs: `http://localhost:8000/docs`

```bash
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"job_type": "summarization", "input": {"text": "Artificial intelligence has transformed industries..."}, "priority": "high"}'
```

```bash
pytest
```

## Evolution

The Redis queue and separate worker process handled job dispatch with stub handlers. This release adds a **real summarization worker**: long text is chunked with overlap, each chunk is summarized with Hugging Face, and results are merged (recursively if still too long).
