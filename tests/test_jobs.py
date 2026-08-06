from app.models.job import JobStatus
from app.services.job_service import job_service


def test_create_job_returns_pending(client, celery_calls):
    response = client.post(
        "/jobs",
        json={"job_type": "summarization", "input": {"text": "hello world"}},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "pending"
    assert data["job_type"] == "summarization"
    assert data["priority"] == "normal"
    assert len(celery_calls) == 1
    assert celery_calls[0]["name"] == "process_job"
    assert celery_calls[0]["queue"] == "normal"
    assert celery_calls[0]["args"] == [data["id"]]


def test_create_job_validation_error(client):
    response = client.post(
        "/jobs",
        json={"input": {"text": "missing job_type"}},
    )
    assert response.status_code == 422


def test_create_job_rejects_invalid_ocr_input(client):
    response = client.post(
        "/jobs",
        json={"job_type": "ocr", "input": {"image_url": "http://example.com/a.png"}},
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


def test_create_job_dispatches_celery_task(client, celery_calls):
    response = client.post(
        "/jobs",
        json={
            "job_type": "ocr",
            "input": {"image": "aGVsbG8="},  # base64 "hello"
        },
    )
    assert response.status_code == 201
    job_id = response.json()["id"]

    assert len(celery_calls) == 1
    assert celery_calls[0]["name"] == "process_job"
    assert celery_calls[0]["args"] == [job_id]
    assert celery_calls[0]["queue"] == "normal"


def test_create_job_high_priority_queue(client, celery_calls):
    response = client.post(
        "/jobs",
        json={
            "job_type": "summarization",
            "input": {"text": "urgent"},
            "priority": "high",
        },
    )
    assert response.status_code == 201
    assert celery_calls[-1]["queue"] == "high"


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
        json={"job_type": "ocr", "input": {"image": "aGVsbG8="}},
    )

    response = client.get("/jobs")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert len(data["jobs"]) == 2
    assert {job["job_type"] for job in data["jobs"]} == {"summarization", "ocr"}


def test_update_job_status_persists(client, db_session):
    create = client.post(
        "/jobs",
        json={"job_type": "summarization", "input": {"text": "hello"}},
    )
    job_id = create.json()["id"]

    job_service.update_job_status(
        db_session,
        job_id=job_id,
        status=JobStatus.COMPLETED,
        result_payload={"result": "done"},
    )

    response = client.get(f"/jobs/{job_id}")
    data = response.json()

    assert data["status"] == "completed"
    assert data["result_payload"]["result"] == "done"
