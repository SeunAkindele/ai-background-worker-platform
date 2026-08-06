from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.jobs import router as jobs_router
from app.core.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="AI Background Worker Platform",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(jobs_router)


@app.get("/health")
def health():
    from app.core.redis_client import redis_client

    return {
        "status": "ok",
        "queued_jobs": redis_client.llen("celery"),
    }


@app.get("/admin/queues")
def queue_stats():
    from app.core.redis_client import redis_client
    from app.workers.celery_app import celery_app

    inspect = celery_app.control.inspect()
    return {
        "queued": redis_client.llen("celery"),
        "active": inspect.active() or {},
        "reserved": inspect.reserved() or {},
    }
