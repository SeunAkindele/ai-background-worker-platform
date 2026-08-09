from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.admin import router as admin_router
from app.api.documents import documents_router, rag_router
from app.api.jobs import router as jobs_router
from app.api.uploads import router as uploads_router
from app.core.database import async_engine, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create tables on startup; dispose the async engine on shutdown."""
    init_db()
    yield
    await async_engine.dispose()


app = FastAPI(
    title="AI Background Worker Platform",
    version="0.14.0",
    lifespan=lifespan,
)

app.include_router(jobs_router)
app.include_router(uploads_router)
app.include_router(admin_router)
app.include_router(documents_router)
app.include_router(rag_router)


@app.get("/health")
async def health():
    """Return per-queue Redis depths and total queued count."""
    from app.core.redis_client import redis_client
    from app.models.job import JobType

    queue_sizes = {}
    for jt in JobType:
        queue_sizes[jt.value] = redis_client.llen(jt.value)

    return {
        "status": "ok",
        "queues": queue_sizes,
        "total_queued": sum(queue_sizes.values()),
    }


@app.get("/ready")
async def ready():
    """Kubernetes readiness/liveness probe target."""
    return {"status": "ready"}
