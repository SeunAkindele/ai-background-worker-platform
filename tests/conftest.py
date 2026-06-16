import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

# Load test env before any app imports so Settings uses the test database.
load_dotenv(ROOT / ".env.test", override=True)

if not os.environ.get("DATABASE_URL"):
    raise RuntimeError(
        "Tests require a .env.test file with DATABASE_URL. "
        "Copy .env.test.example to .env.test and create the test database."
    )

os.environ["APP_ENV"] = "test"

import pytest
from fastapi.testclient import TestClient

import app.models  # noqa: F401 — register models; do not bind as `app`
from app.core.database import Base, SessionLocal, engine
from app.core.queue import job_queue
from app.main import app as fastapi_app


@pytest.fixture
def client():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    job_queue.clear()

    return TestClient(fastapi_app)


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
