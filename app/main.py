from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.admin import router as admin_router
from app.api.jobs import router as jobs_router
from app.api.uploads import router as uploads_router
from app.core.database import async_engine, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Python Internals Focus:
    -----------------------
    asynccontextmanager converts an async generator into an async context manager.
    FastAPI uses this to run startup code (before yield) and shutdown code (after yield).

    The event loop is already running when this executes — that's why we can
    use `await` here for async cleanup like disposing the engine's connection pool.

    Why dispose the async engine on shutdown?
    - Gracefully closes all pooled connections to PostgreSQL
    - Without this, connections may linger as TIME_WAIT on the OS
    - Important in containerized environments where restarts are frequent
    """
    init_db()
    yield
    await async_engine.dispose()


app = FastAPI(
    title="AI Background Worker Platform",
    version="0.12.0",
    lifespan=lifespan,
)

app.include_router(jobs_router)
app.include_router(uploads_router)
app.include_router(admin_router)


@app.get("/health")
async def health():
    """
    Health check showing per-queue job counts.
    Stage 11 change:
    With split workers, the old redis_client.llen("celery") returns 0
    because there's no longer a single "celery" queue. Each job type
    has its own queue. This endpoint now shows the size of each queue
    so you can see which worker types have backlogs.
    DSA Focus:
    This is essentially a hash map of queue_name → size. Iterating
    over all queue names is O(k) where k = number of job types (5).
    Each llen call is O(1) in Redis (Redis stores list length as metadata).
    Note: redis_client is the sync client. For a handful of llen calls
    (each taking microseconds), blocking an async route is acceptable.
    """
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
    """
    Stage 12: Kubernetes readiness probe target.
    Liveness = "process is alive" (don't kill if Redis is briefly slow).
    Readiness = "safe to send traffic" (fail if we can't serve requests).
    Start simple: always ok once the app started.
    Stretch: ping Postgres/Redis and return 503 if down.
    """
    return {"status": "ready"}