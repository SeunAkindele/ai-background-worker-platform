from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.jobs import router as jobs_router
from app.core.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield
    print("Server shutting down")  # shutdown


app = FastAPI(
    title="AI Background Worker Platform",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(jobs_router)


@app.get("/health")
def health():
    from app.core.queue import job_queue
    return {
        "status": "ok",
        "pending_jobs": job_queue.size(),
        "processing_jobs": job_queue.processing_size(),
    }

@app.get("/admin/queues")
def queue_stats():
    from app.core.redis_client import redis_client
    from app.core.queue import FAILED_KEY, PENDING_KEY, PROCESSING_KEY, RETRY_KEY
    return {
        "pending": redis_client.zcard(PENDING_KEY),
        "processing": redis_client.llen(PROCESSING_KEY),
        "retry": redis_client.llen(RETRY_KEY),
        "failed": redis_client.llen(FAILED_KEY),
    }