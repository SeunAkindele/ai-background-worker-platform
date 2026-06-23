import threading
import time

import pytest

from app.workers.redis_worker import RedisWorker


@pytest.fixture
def redis_worker(job_queue):
    worker = RedisWorker(poll_interval=0.05)
    thread = threading.Thread(target=worker.run, daemon=True)
    thread.start()
    yield worker
    worker.stop()
    thread.join(timeout=2)


def test_worker_completes_summarization_job(client, redis_worker):
    response = client.post(
        "/jobs",
        json={"job_type": "summarization", "input": {"text": "long article"}},
    )
    assert response.status_code == 201
    job_id = response.json()["id"]

    deadline = time.time() + 5
    while time.time() < deadline:
        data = client.get(f"/jobs/{job_id}").json()
        if data["status"] == "completed":
            assert data["result_payload"]["summary"] == "summary generated"
            return
        if data["status"] == "failed":
            pytest.fail(data.get("error_message"))
        time.sleep(0.1)

    pytest.fail("Job did not complete")