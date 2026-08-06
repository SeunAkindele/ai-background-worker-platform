import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

# Ensure Settings binds to the test database before app imports.
load_dotenv(ROOT / ".env.test", override=True)

if not os.environ.get("DATABASE_URL"):
    raise RuntimeError(
        "DATABASE_URL is required for tests. "
        "Copy .env.test.example to .env.test and create the test database."
    )

os.environ["APP_ENV"] = "test"

import pytest
from fastapi.testclient import TestClient

import app.models  # noqa: F401
from app.core.database import Base, SessionLocal, engine
from app.core.queue import job_queue
from app.main import app as fastapi_app
from app.workers.local_worker import local_worker


@pytest.fixture
def client():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    job_queue.clear()

    local_worker.stop()
    local_worker.start()

    yield TestClient(fastapi_app)

    local_worker.stop()


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def reset_queue(client):
    job_queue.clear()
    yield
    job_queue.clear()