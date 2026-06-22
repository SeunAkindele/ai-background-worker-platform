import logging
import threading
import time
from uuid import UUID

from app.core.database import db_session
from app.core.queue import job_queue
from app.models.job import Job, JobStatus
from app.services.job_service import job_service
from app.workers.decorators import log_execution_time
from app.workers.handlers import get_handler

logger = logging.getLogger(__name__)


class LocalWorker:
    """
    Background thread that:
    1. dequeues job_id
    2. marks processing
    3. runs fake handler
    4. marks completed or failed
    """

    def __init__(self, poll_interval: float = 0.5) -> None:
        self._poll_interval = poll_interval
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="local-worker", daemon=True)
        self._thread.start()
        logger.info("Local worker started")

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=timeout)
        logger.info("Local worker stopped")

    def _iter_jobs(self):
        """Generator: yields one job_id at a time; sleeps when queue is empty."""
        while not self._stop_event.is_set():   # stop when app shuts down
            job_id = job_queue.dequeue()
            if job_id is None:
                time.sleep(self._poll_interval)
                continue
            yield job_id

    def _run(self) -> None:
        """Main loop — runs in background thread."""
        for job_id in self._iter_jobs():
            try:
                self._process_job(job_id)
            except Exception:
                logger.exception("Unexpected error processing job %s", job_id)

    @log_execution_time
    def _process_job(self, job_id: UUID) -> None:
        with db_session() as db:
            # get job from DB
            job = job_service.get_job(db, job_id)
            if not job:
                logger.warning("Job %s not found in DB", job_id)
                return
            if job.status != JobStatus.PENDING:  # TODO: handle other statuses
                logger.warning("Job %s skipped — status is %s", job_id, job.status)
                return
            # update status → PROCESSING
            job_service.update_job_status(db, job_id, JobStatus.PROCESSING)
            try:
                # handler = get_handler(job.job_type)(job.input_payload)
                result = get_handler(job.job_type)(job.input_payload)
            except Exception as exc:
                # On handler error: status → FAILED with error_message
                logger.exception("Job %s failed", job_id)
                job_service.update_job_status(
                    db,
                    job_id,
                    JobStatus.FAILED,
                    error_message=str(exc),
                )
                return
            # update status → COMPLETED with result_payload
            job_service.update_job_status(
                db,
                job_id,
                JobStatus.COMPLETED,
                result_payload=result,
            )
            
# Singleton — started from main.py lifespan
local_worker = LocalWorker()