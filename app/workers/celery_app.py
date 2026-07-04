from celery import Celery
from kombu import Queue

from app.config import settings

celery_app = Celery(
    "ai_worker",
    broker=settings.redis_url,
    backend=settings.redis_url,   # optional: see note below
    include=["app.workers.tasks"],  # worker imports this module to find tasks
)

celery_app.conf.update(
    # --- serialization (Python internals focus) ---
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],      # refuse pickle: safer, forces JSON-clean args

    # --- time ---
    timezone="UTC",
    enable_utc=True,

    # --- delivery semantics (DSA focus) ---
    task_acks_late=True,            # ack AFTER the task finishes, not before
    worker_prefetch_multiplier=1,   # don't hoard messages; one at a time
    task_track_started=True,        # expose a STARTED state

    # --- visibility timeout (DSA focus) ---
    broker_transport_options={"visibility_timeout": 3600},  # 1h; > your slowest job

    # Priority queues — workers drain "high" before "normal" before "low"
    task_queues=(
        Queue("high", routing_key="high"),
        Queue("normal", routing_key="normal"),
        Queue("low", routing_key="low"),
    ),
    task_default_queue="normal",
    task_default_routing_key="normal",
    # Workers consume in this order (leftmost first when messages are available)
    worker_consumer_prefetch=True,
)