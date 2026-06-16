import pytest
from fastapi.testclient import TestClient
from uuid import UUID

from app.core.database import Base, engine
from app.core.queue import job_queue
from app.main import app as fastapi_app
from app.core.database import SessionLocal
from app.services.job_service import job_service
from app.models.job import JobStatus


@pytest.fixture
def client():
    import app.models  # noqa: F401 — register models; do not bind as `app` (shadows FastAPI app)

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    job_queue.clear()

    return TestClient(fastapi_app)


def test_create_job_returns_pending(client):
    response = client.post(
        "/jobs",
        json={"job_type": "summarization", "input": {"text": "hello world"}},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "pending"
    assert data["job_type"] == "summarization"


def test_create_job_validation_error(client):
    response = client.post(
        "/jobs",
        json={"input": {"text": "missing job_type"}},
    )

    assert response.status_code == 422


def test_get_job_success(client):
    create = client.post(
        "/jobs",
        json={"job_type": "summarization", "input": {"text": "hello"}},
    )
    job_id = create.json()["id"]

    response = client.get(f"/jobs/{job_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == job_id
    assert data["job_type"] == "summarization"


def test_create_job_enqueues(client):
    before = job_queue.size()
    response = client.post(
        "/jobs",
        json={"job_type": "ocr", "input": {"image_url": "http://example.com/a.png"}},
    )
    assert response.status_code == 201
    assert job_queue.size() == before + 1


def test_create_job_enqueues_correct_id(client):
    before = job_queue.size()

    response = client.post(
        "/jobs",
        json={"job_type": "ocr", "input": {"image_url": "http://example.com/a.png"}},
    )

    job_id = response.json()["id"]

    assert job_queue.size() == before + 1
    assert UUID(job_id) in job_queue._queue  # assumes internal list storage


def test_get_job_not_found(client):
    response = client.get("/jobs/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


def test_get_job_invalid_uuid(client):
    response = client.get("/jobs/123")
    assert response.status_code == 422


def test_list_jobs_empty(client):
    response = client.get("/jobs")

    assert response.status_code == 200
    data = response.json()

    assert data["total"] == 0
    assert data["jobs"] == []


def test_list_jobs(client):
    client.post(
        "/jobs",
        json={"job_type": "summarization", "input": {"text": "first job"}},
    )
    client.post(
        "/jobs",
        json={"job_type": "ocr", "input": {"image_url": "http://example.com/b.png"}},
    )

    response = client.get("/jobs")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert len(data["jobs"]) == 2
    assert {job["job_type"] for job in data["jobs"]} == {"summarization", "ocr"}


def test_update_job_status_persists(client):
    create = client.post(
        "/jobs",
        json={"job_type": "summarization", "input": {"text": "hello"}},
    )
    job_id = create.json()["id"]

    db = SessionLocal()
    try:
        job_service.update_job_status(
            db,
            job_id=job_id,
            status=JobStatus.COMPLETED,
            result_payload={"result": "done"},
        )
    finally:
        db.close()

    response = client.get(f"/jobs/{job_id}")
    data = response.json()

    assert data["status"] == "completed"
    assert data["result_payload"]["result"] == "done"