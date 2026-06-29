import threading
import time
from unittest.mock import patch

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


@patch("app.workers.summarization_worker.get_summarization_pipeline")
def test_worker_completes_summarization_job(mock_get_pipeline, client, redis_worker):
    mock_pipe = mock_get_pipeline.return_value
    mock_pipe.return_value = [{"summary_text": "A mocked summary."}]

    response = client.post(
        "/jobs",
        json={"job_type": "summarization", "input": {"text": "long article"}},
    )
    assert response.status_code == 201
    job_id = response.json()["id"]

    deadline = time.time() + 10
    while time.time() < deadline:
        data = client.get(f"/jobs/{job_id}").json()
        if data["status"] == "completed":
            summary = data["result_payload"]["summary"]
            assert isinstance(summary, str)
            assert len(summary) > 0
            return
        if data["status"] == "failed":
            pytest.fail(data.get("error_message"))
        time.sleep(0.1)

    pytest.fail("Job did not complete")