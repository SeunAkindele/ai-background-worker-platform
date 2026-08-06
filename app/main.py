from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.jobs import router as jobs_router
from app.core.database import init_db
from app.workers.local_worker import local_worker


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    local_worker.start()
    yield
    local_worker.stop()


app = FastAPI(
    title="AI Background Worker Platform",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(jobs_router)


@app.get("/health")
def health():
    return {"status": "ok"}
