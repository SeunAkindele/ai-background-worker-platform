from unittest.mock import MagicMock, patch

import pytest

from app.models.job import JobStatus
from app.workers.tasks import process_job


@pytest.fixture
def mock_handler():
    return MagicMock(
        return_value={
            "summary": "A mocked summary.",
            "chunks_processed": 1,
            "original_word_count": 2,
            "summary_word_count": 3,
        }
    )


@patch("app.workers.tasks.get_handler")
def test_process_job_completes_summarization(mock_get_handler, mock_handler, client):
    mock_get_handler.return_value = mock_handler

    response = client.post(
        "/jobs",
        json={"job_type": "summarization", "input": {"text": "long article"}},
    )
    assert response.status_code == 201
    job_id = response.json()["id"]

    process_job.run(job_id)

    data = client.get(f"/jobs/{job_id}").json()
    assert data["status"] == "completed"
    assert data["result_payload"]["summary"] == "A mocked summary."
    mock_handler.assert_called_once()


@patch("app.workers.tasks.get_handler")
def test_process_job_marks_failed_after_retries(mock_get_handler, client):
    failing = MagicMock(side_effect=RuntimeError("boom"))
    mock_get_handler.return_value = failing

    response = client.post(
        "/jobs",
        json={"job_type": "summarization", "input": {"text": "will fail"}},
    )
    job_id = response.json()["id"]

    task = process_job._get_current_object()
    task.push_request(retries=task.max_retries)
    try:
        with patch.object(
            task,
            "retry",
            side_effect=task.MaxRetriesExceededError("max retries"),
        ):
            task.run(job_id)
    finally:
        task.pop_request()

    data = client.get(f"/jobs/{job_id}").json()
    assert data["status"] == JobStatus.FAILED.value
    assert "boom" in data["error_message"]


@patch("app.workers.tasks.get_handler")
def test_process_job_skips_missing_job(mock_get_handler, client):
    process_job.run("00000000-0000-0000-0000-000000000000")
    mock_get_handler.assert_not_called()
