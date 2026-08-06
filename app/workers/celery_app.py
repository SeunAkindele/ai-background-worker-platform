from celery import Celery
from kombu import Queue

from app.config import settings
from app.models.job import JobType

WORKER_QUEUES = [jt.value for jt in JobType]

celery_app = Celery(
    "ai_worker",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],

    timezone="UTC",
    enable_utc=True,

    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,

    # Redis priority sub-queues (sep=":") for each logical job-type queue.
    # priority_steps [0, 5, 9] → lower number drained first.
    broker_transport_options={
        "visibility_timeout": 3600,
        "priority_steps": [0, 5, 9],
        "sep": ":",
        "queue_order_strategy": "priority",
    },

    task_queues=tuple(Queue(name) for name in WORKER_QUEUES),
    task_default_queue="summarization",
)

# Register worker lifecycle hooks (periodic heartbeat thread).
import app.workers.worker_signals  # noqa: E402, F401
