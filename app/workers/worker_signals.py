import logging
import threading

from celery.signals import (
    worker_process_init,
    worker_process_shutdown,
    worker_ready,
    worker_shutdown,
)

from app.config import settings
from app.core.database import db_session
from app.models.worker_heartbeat import WorkerStatus
from app.services.heartbeat_service import (
    HEARTBEAT_INTERVAL_SECONDS,
    heartbeat_service,
)
from app.workers.worker_identity import get_process_worker_name

logger = logging.getLogger(__name__)

_stop_event = threading.Event()

MAX_BACKOFF_SECONDS = 300


def _heartbeat_loop(worker_name: str, worker_type: str) -> None:
    """
    Periodic heartbeat that runs in a daemon thread alongside the Celery worker.
    Stage 11 change:
    The loop now receives worker_type and does an initial beat() call
    to register the correct type BEFORE entering the pulse loop.
    Previously, the first heartbeat row was created by pulse() with
    worker_type="general" (the default). It only got the correct type
    after the first job was processed (when tasks.py called beat()).
    With split workers, we know the type at startup from the WORKER_TYPE
    env var, so we register it immediately.
    """
    # Initial registration with correct worker_type and ONLINE status.
    try:
        with db_session() as db:
            heartbeat_service.beat(
                db, worker_name, worker_type, status=WorkerStatus.ONLINE,
            )
    except Exception:
        logger.exception(
            "Initial heartbeat registration failed for %s", worker_name,
        )

    consecutive_failures = 0

    while not _stop_event.is_set():
        try:
            with db_session() as db:
                heartbeat_service.pulse(db, worker_name)
            consecutive_failures = 0
        except Exception:
            consecutive_failures += 1
            backoff = min(
                HEARTBEAT_INTERVAL_SECONDS * (2 ** consecutive_failures),
                MAX_BACKOFF_SECONDS,
            )
            logger.exception(
                "Heartbeat pulse failed for %s (attempt %d, next retry in %ds)",
                worker_name, consecutive_failures, backoff,
            )
            _stop_event.wait(backoff)
            continue

        _stop_event.wait(HEARTBEAT_INTERVAL_SECONDS)


def _mark_offline(worker_name: str) -> None:
    try:
        with db_session() as db:
            heartbeat_service.mark_offline(db, worker_name)
        logger.info("Marked %s as OFFLINE", worker_name)
    except Exception:
        logger.exception("Failed to mark %s offline on shutdown", worker_name)


def _start_heartbeat_thread() -> None:
    _stop_event.clear()
    worker_name = get_process_worker_name()
    worker_type = settings.worker_type
    thread = threading.Thread(
        target=_heartbeat_loop,
        args=(worker_name, worker_type),
        name=f"heartbeat-{worker_name}",
        daemon=True,
    )
    thread.start()
    logger.info("Started heartbeat thread for %s (type=%s)", worker_name, worker_type)


def _is_solo_pool(sender) -> bool:
    pool_cls_name = getattr(sender.pool, "__class__", None)
    return pool_cls_name is not None and pool_cls_name.__name__ == "TaskPool"


@worker_process_init.connect
def on_worker_process_init(**kwargs) -> None:
    """Prefork pool: one heartbeat thread per child process."""
    _start_heartbeat_thread()


@worker_process_shutdown.connect
def on_worker_process_shutdown(**kwargs) -> None:
    """Prefork pool: mark child as OFFLINE immediately on exit."""
    _stop_event.set()
    _mark_offline(get_process_worker_name())


@worker_ready.connect
def on_worker_ready(sender, **kwargs) -> None:
    """Solo pool: tasks run in the main process; worker_process_init never fires."""
    if _is_solo_pool(sender):
        _start_heartbeat_thread()


@worker_shutdown.connect
def on_worker_shutdown(sender, **kwargs) -> None:
    """Solo pool: mark the worker OFFLINE on graceful stop."""
    _stop_event.set()
    if _is_solo_pool(sender):
        _mark_offline(get_process_worker_name())
