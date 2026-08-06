# AI Background Worker Platform

A backend platform for submitting, queuing, and processing AI background jobs. Deploy with Kubernetes (Kustomize) — API, five per-type Celery workers, Postgres, Redis, shared uploads PVC, probes, and HPAs — or use Docker Compose locally.

## Architecture

```
kubectl apply -k infra/kubernetes/
  │
  ├── namespace: ai-worker-platform
  ├── postgres / redis
  ├── api  (Deployment + Service NodePort 30080)
  │      readiness/liveness → GET /ready
  │      uploads PVC → /app/uploads ──┐
  ├── worker-summarization            │
  ├── worker-embeddings               │
  ├── worker-ocr  (+ uploads PVC)     │ shared image
  ├── worker-transcription (+ PVC)    │ WORKER_TYPE + --queues=<type>
  └── worker-recommendations          │
         HPAs: OCR (CPU), sum/trans (memory)
```

## Features

- **Kubernetes manifests** — Kustomize bundle under `infra/kubernetes/` (Deployments, Services, ConfigMap, Secret, PVCs)
- **Per-type worker Deployments** — one Deployment per job type; scale OCR without scaling summarization
- **Probes** — API readiness/liveness on `GET /ready`; worker liveness via process check
- **HPAs** — OCR scales on CPU; summarization and transcription scale on memory
- **Shared uploads PVC** — mounted on API, OCR, and transcription workers
- **Job API** — async FastAPI, rate limiting, file uploads, admin observability (unchanged from prior releases)

## Quick start

**Prerequisites:** Docker (to build the image) and a local cluster (Docker Desktop Kubernetes, Kind, or Minikube) with `kubectl`

```bash
cd ai-background-worker-platform
docker build -t ai-worker-platform:latest .
kubectl apply -k infra/kubernetes/
kubectl -n ai-worker-platform get pods
```

- API: `http://localhost:30080` (NodePort) or `kubectl -n ai-worker-platform port-forward svc/api 8000:8000`
- Ready: `GET /ready` · Health: `GET /health` · Docs: `/docs`
- Examples: [`API_COLLECTION.md`](API_COLLECTION.md)

```bash
curl -X POST http://localhost:30080/jobs \
  -H "Content-Type: application/json" \
  -d '{"job_type": "summarization", "input": {"text": "Artificial intelligence has transformed industries..."}, "priority": "high"}'
```

```bash
kubectl -n ai-worker-platform delete -k infra/kubernetes/
pytest
```

For local Compose (no cluster): `docker compose up --build`.

## Evolution

Per-type workers on Compose already isolated queues by job type. This release **moves the same topology to Kubernetes** — Deployments, a shared uploads PVC, `/ready` probes, and HPAs — so each worker type can scale independently in a cluster.
