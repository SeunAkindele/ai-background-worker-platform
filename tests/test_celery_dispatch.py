"""
Celery dispatch tests — Stage 11 job-type queues + native priority.
"""


def test_default_routes_to_job_type_queue(client, celery_calls):
    response = client.post(
        "/jobs",
        json={"job_type": "summarization", "input": {"text": "hello"}},
    )
    assert response.status_code == 201
    assert celery_calls[-1]["queue"] == "summarization"
    assert celery_calls[-1].get("priority", 5) == 5


def test_high_priority_still_uses_job_type_queue(client, celery_calls):
    response = client.post(
        "/jobs",
        json={
            "job_type": "summarization",
            "input": {"text": "urgent"},
            "priority": "high",
        },
    )
    assert response.status_code == 201
    assert celery_calls[-1]["queue"] == "summarization"
    assert celery_calls[-1]["priority"] == 0


def test_low_priority_embeddings_queue(client, celery_calls):
    response = client.post(
        "/jobs",
        json={
            "job_type": "embeddings",
            "input": {"text": "later"},
            "priority": "low",
        },
    )
    assert response.status_code == 201
    assert celery_calls[-1]["queue"] == "embeddings"
    assert celery_calls[-1]["priority"] == 9


def test_send_task_receives_job_id(client, celery_calls):
    response = client.post(
        "/jobs",
        json={"job_type": "embeddings", "input": {"text": "vector me"}},
    )
    assert response.status_code == 201
    job_id = response.json()["id"]

    assert celery_calls[-1]["name"] == "process_job"
    assert celery_calls[-1]["args"] == [job_id]
