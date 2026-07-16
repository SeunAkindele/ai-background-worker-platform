from celery import Celery
from kombu import Queue

from app.config import settings
from app.models.job import JobType

WORKER_QUEUES = [jt.value for jt in JobType]

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

    # --- broker transport (Redis-specific) ---
    # priority_steps: creates sub-queues per priority level.
    # With [0, 5, 9] and sep=":", a queue named "summarization" actually
    # becomes three Redis lists: summarization:0, summarization:5, summarization:9.
    # The worker drains lower numbers first (0 = highest priority).
    #
    # queue_order_strategy="priority": tells the worker to check higher-priority
    # sub-queues before lower ones on each broker poll cycle.
    #
    # DSA Focus:
    # In Stage 5 you used SEPARATE queues (high, normal, low) for priority.
    # That's explicit but creates 3× as many queues when you multiply by
    # worker types (5 types × 3 priorities = 15 queues).
    # Celery's native priority is cleaner: one logical queue, priority handled
    # internally.
    broker_transport_options={
        "visibility_timeout": 3600,
        "priority_steps": [0, 5, 9],
        "sep": ":",
        "queue_order_strategy": "priority",
    },

    # One logical queue per job type.
    task_queues=tuple(Queue(name) for name in WORKER_QUEUES),
    task_default_queue="summarization",
)

# Register worker lifecycle hooks (periodic heartbeat thread).
import app.workers.worker_signals  # noqa: E402, F401