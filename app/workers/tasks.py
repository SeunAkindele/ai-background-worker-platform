from uuid import UUID

from app.core.database import db_session
from app.models.job import JobStatus
from app.models.job_log import LogLevel
from app.models.worker_heartbeat import WorkerStatus
from app.services.heartbeat_service import heartbeat_service
from app.services.job_service import job_service
from app.services.log_service import log_service
from app.workers.celery_app import celery_app
from app.workers.decorators import timed_block
from app.workers.handlers import get_handler
from app.workers.worker_identity import get_process_worker_name

RETRY_BACKOFF = {0: 10, 1: 60}
DEFAULT_BACKOFF = 60
MAX_RETRIES = 2


def _backoff_seconds(retries: int) -> int:
    return RETRY_BACKOFF.get(retries, DEFAULT_BACKOFF)


def _worker_name() -> str:
    """Process-level worker identity — matches the periodic heartbeat thread."""
    return get_process_worker_name()


@celery_app.task(
    bind=True, name="process_job", max_retries=MAX_RETRIES, acks_late=True
)
def process_job(self, job_id: str) -> None:
    job_uuid = UUID(job_id)
    worker = _worker_name()

    # --- Phase 1: Pick up the job ---
    with db_session() as db:
        job = job_service.get_job(db, job_uuid)
        if job is None:
            return

        if job.status in (JobStatus.COMPLETED, JobStatus.FAILED):
            return

        job_service.update_job_status(db, job_uuid, JobStatus.PROCESSING)
        log_service.add_log(
            db, job_uuid,
            f"Job picked up by worker {worker}",
            LogLevel.INFO,
        )
        heartbeat_service.beat(
            db, worker, job.job_type.value,
            status=WorkerStatus.BUSY, current_job_id=job_uuid,
        )
        handler = get_handler(job.job_type)
        input_payload = job.input_payload

    # --- Phase 2: Process ---
    try:
        with timed_block(f"process:{job.job_type.value}") as timer:
            result = handler(input_payload)
    except Exception as exc:
        # --- Phase 3a: Handle failure ---
        countdown = _backoff_seconds(self.request.retries)
        with db_session() as db:
            log_service.add_log(
                db, job_uuid,
                f"Attempt {self.request.retries + 1} failed: {exc}",
                LogLevel.ERROR,
            )
        try:
            raise self.retry(exc=exc, countdown=countdown)
        except self.MaxRetriesExceededError:
            with db_session() as db:
                job_service.update_job_status(
                    db, job_uuid, JobStatus.FAILED, error_message=str(exc),
                )
                log_service.add_log(
                    db, job_uuid,
                    f"Job permanently failed after {MAX_RETRIES + 1} attempts: {exc}",
                    LogLevel.ERROR,
                )
                heartbeat_service.record_completion(db, worker, success=False)
            return

    # --- Phase 3b: Handle success ---
    with db_session() as db:
        job_service.update_job_status(
            db, job_uuid, JobStatus.COMPLETED, result_payload=result,
        )
        log_service.add_log(
            db, job_uuid,
            f"Job completed successfully in {timer.elapsed:.3f}s",
            LogLevel.INFO,
        )
        heartbeat_service.record_completion(db, worker, success=True)