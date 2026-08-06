import os
from pathlib import Path

import fakeredis
import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent

load_dotenv(ROOT / ".env.test", override=True)

if not os.environ.get("DATABASE_URL"):
    raise RuntimeError(
        "DATABASE_URL is required for tests. "
        "Copy .env.test.example to .env.test and create the test database."
    )

os.environ["APP_ENV"] = "test"

import app.models  # noqa: F401
from app.core.database import Base, SessionLocal, engine
from app.core import queue as queue_module
from app.main import app as fastapi_app


@pytest.fixture
def fake_redis():
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def job_queue(fake_redis):
    q = queue_module.RedisJobQueue(client=fake_redis)
    queue_module.job_queue = q
    yield q
    q.clear()


@pytest.fixture
def client(job_queue):
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    job_queue.clear()
    yield TestClient(fastapi_app)


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
