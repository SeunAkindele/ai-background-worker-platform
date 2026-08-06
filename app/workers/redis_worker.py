import logging
import signal
import threading
import time
from uuid import UUID

from app.core.database import db_session, init_db
from app.core import queue as queue_module
from app.models.job import JobStatus
from app.services.job_service import job_service
from app.workers.decorators import log_execution_time
from app.workers.handlers import get_handler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class RedisWorker:
    """Polls Redis for jobs and runs the matching handler."""

    def __init__(self, poll_interval: float = 0.5) -> None:
        self._poll_interval = poll_interval
        self._running = True

    def stop(self, *_args) -> None:
        self._running = False
        logger.info("Shutdown signal received")

    def _iter_jobs(self):
        while self._running:
            job_id = queue_module.job_queue.dequeue()
            if job_id is None:
                time.sleep(self._poll_interval)
                continue
            yield job_id

    def run(self) -> None:
        init_db()
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGINT, self.stop)
            signal.signal(signal.SIGTERM, self.stop)
        logger.info("Initializing Redis worker")

        for job_id in self._iter_jobs():
            try:
                self._process_job(job_id)
            except Exception:
                logger.exception("Unexpected error processing job %s", job_id)

    @log_execution_time
    def _process_job(self, job_id: UUID) -> None:
        with db_session() as db:
            job = job_service.get_job(db, job_id)
            if not job:
                logger.warning("Job %s not found", job_id)
                queue_module.job_queue.acknowledge(job_id)
                return

            if job.status != JobStatus.PENDING:
                logger.warning("Job %s skipped — status %s", job_id, job.status)
                queue_module.job_queue.acknowledge(job_id)
                return

            job_service.update_job_status(db, job_id, JobStatus.PROCESSING)

            try:
                result = get_handler(job.job_type)(job.input_payload)
            except Exception as exc:
                logger.exception("Job %s failed", job_id)
                job_service.update_job_status(
                    db, job_id, JobStatus.FAILED, error_message=str(exc),
                )
                queue_module.job_queue.move_to_failed(job_id)
                return

            job_service.update_job_status(
                db, job_id, JobStatus.COMPLETED, result_payload=result,
            )
            queue_module.job_queue.acknowledge(job_id)


def main() -> None:
    RedisWorker().run()


if __name__ == "__main__":
    main()
