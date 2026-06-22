import time
from uuid import UUID

import pytest

from app.core.queue import job_queue
from app.workers.local_worker import local_worker


def test_worker_completes_summarization_job(client):
    response = client.post(
        "/jobs",
        json={
            "job_type": "summarization",
            "input": {"text": "long article here"},
        },
    )
    assert response.status_code == 201
    job_id = response.json()["id"]
    assert response.json()["status"] == "pending"

    # Poll until worker finishes (fake work is instant)
    deadline = time.time() + 5
    status = "pending"
    while time.time() < deadline and status != "completed":
        data = client.get(f"/jobs/{job_id}").json()
        status = data["status"]
        if status == "failed":
            pytest.fail(f"Job failed: {data.get('error_message')}")
        time.sleep(0.2)

    assert status == "completed"
    data = client.get(f"/jobs/{job_id}").json()
    assert data["result_payload"]["summary"] == "summary generated"


def _wait_until_completed(client, job_id: str, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = client.get(f"/jobs/{job_id}").json()
        if data["status"] == "completed":
            return data
        if data["status"] == "failed":
            pytest.fail(f"Job {job_id} failed: {data.get('error_message')}")
        time.sleep(0.1)
    pytest.fail(f"Job {job_id} did not complete within {timeout}s")


def test_high_priority_processed_before_low(client):
    # Stop worker so jobs pile up in the queue (no race)
    local_worker.stop()
    low = client.post(
        "/jobs",
        json={
            "job_type": "summarization",
            "input": {"text": "low priority job"},
            "priority": "low",
        },
    ).json()
    high = client.post(
        "/jobs",
        json={
            "job_type": "summarization",
            "input": {"text": "high priority job"},
            "priority": "high",
        },
    ).json()

    assert job_queue.size() == 2
    # HIGH should be at front of priority queue even though LOW was posted first
    assert job_queue.peek() == UUID(high["id"])

    local_worker.start()

    high_data = _wait_until_completed(client, high["id"])
    low_data = _wait_until_completed(client, low["id"])

    # HIGH finished first → earlier updated_at
    assert high_data["updated_at"] <= low_data["updated_at"]