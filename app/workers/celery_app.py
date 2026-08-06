from celery import Celery
from kombu import Queue

from app.config import settings

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
    broker_transport_options={"visibility_timeout": 3600},
    task_queues=(
        Queue("high", routing_key="high"),
        Queue("normal", routing_key="normal"),
        Queue("low", routing_key="low"),
    ),
    task_default_queue="normal",
    task_default_routing_key="normal",
    worker_consumer_prefetch=True,
)
