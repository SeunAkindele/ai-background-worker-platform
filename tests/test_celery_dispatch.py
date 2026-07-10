"""
Celery dispatch tests — replaces the old RedisJobQueue priority tests.

Priority is now expressed as Celery queue names: high / normal / low.
"""


def test_normal_priority_uses_normal_queue(client, celery_calls):
    response = client.post(
        "/jobs",
        json={"job_type": "summarization", "input": {"text": "hello"}},
    )
    assert response.status_code == 201
    assert celery_calls[-1]["queue"] == "normal"


def test_high_priority_uses_high_queue(client, celery_calls):
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


def test_low_priority_uses_low_queue(client, celery_calls):
    response = client.post(
        "/jobs",
        json={
            "job_type": "summarization",
            "input": {"text": "later"},
            "priority": "low",
        },
    )
    assert response.status_code == 201
    assert celery_calls[-1]["queue"] == "low"


def test_send_task_receives_job_id(client, celery_calls):
    response = client.post(
        "/jobs",
        json={"job_type": "embeddings", "input": {"text": "vector me"}},
    )
    assert response.status_code == 201
    job_id = response.json()["id"]

    assert celery_calls[-1]["name"] == "process_job"
    assert celery_calls[-1]["args"] == [job_id]
