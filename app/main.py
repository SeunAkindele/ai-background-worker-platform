from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.admin import router as admin_router
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
app.include_router(admin_router)

@app.get("/health")
def health():
    from app.core.redis_client import redis_client
    return {
        "status": "ok",
        "queued_jobs": redis_client.llen("celery"),
    }
