import os
from pathlib import Path

import fakeredis
import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent

load_dotenv(ROOT / ".env.test", override=True)

# Keep tests from hitting real rate limits across the suite.
os.environ["RATE_LIMIT_REQUESTS"] = "10000"
os.environ["APP_ENV"] = "test"

if not os.environ.get("DATABASE_URL"):
    raise RuntimeError(
        "Tests require a .env.test file with DATABASE_URL. "
        "Copy .env.test.example to .env.test and create the test database."
    )

import app.models  # noqa: F401 — register models
from app.config import settings
from app.core.database import Base, SessionLocal, engine
from app.core.file_storage import file_storage
from app.main import app as fastapi_app
from app.services import file_service as file_service_module


@pytest.fixture
def fake_redis(monkeypatch):
    """Isolate Redis-backed features (rate limiter, health) from a real server."""
    client = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr("app.core.redis_client.redis_client", client)
    monkeypatch.setattr("app.core.rate_limiter.redis_client", client)
    return client


@pytest.fixture
def celery_calls(monkeypatch):
    """Capture Celery send_task calls without needing a broker."""
    calls: list[dict] = []

    def fake_send_task(name, args=None, kwargs=None, queue=None, **extra):
        calls.append(
            {
                "name": name,
                "args": args or [],
                "kwargs": kwargs or {},
                "queue": queue,
            }
        )
        return None

    monkeypatch.setattr(
        "app.workers.celery_app.celery_app.send_task",
        fake_send_task,
    )
    return calls


@pytest.fixture
def client(tmp_path, fake_redis, celery_calls, monkeypatch):
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()

    monkeypatch.setattr(settings, "upload_dir", str(upload_dir))
    monkeypatch.setattr(file_storage, "upload_dir", upload_dir)
    monkeypatch.setattr(file_service_module.file_service.storage, "upload_dir", upload_dir)

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    with TestClient(fastapi_app) as test_client:
        yield test_client


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
