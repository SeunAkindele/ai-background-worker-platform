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
    version="0.9.0",
    lifespan=lifespan,
)

app.include_router(jobs_router)
app.include_router(uploads_router)
app.include_router(admin_router)


@app.get("/health")
async def health():
    """
    Lightweight health check.

    Note: redis_client is still the sync client. For a simple LLEN command
    (microseconds), running it in an async route is acceptable. The call
    completes so fast that blocking is negligible.

    If you needed to do heavy Redis work in an async context, you'd use:
        from redis.asyncio import Redis as AsyncRedis

    But for health checks, keep it simple.
    """
    from app.core.redis_client import redis_client

    return {
        "status": "ok",
        "queued_jobs": redis_client.llen("celery"),
    }