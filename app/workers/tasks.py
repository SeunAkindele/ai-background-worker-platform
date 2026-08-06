from uuid import UUID

from app.core.database import db_session
from app.models.job import JobStatus
from app.services.job_service import job_service
from app.workers.celery_app import celery_app
from app.workers.handlers import get_handler

RETRY_BACKOFF = {0: 10, 1: 60}
DEFAULT_BACKOFF = 60
MAX_RETRIES = 2


def _backoff_seconds(retries: int) -> int:
    return RETRY_BACKOFF.get(retries, DEFAULT_BACKOFF)


@celery_app.task(bind=True, name="process_job", max_retries=MAX_RETRIES, acks_late=True)
def process_job(self, job_id: str) -> None:
    """Process a job by ID; retry with backoff on handler failure."""
    job_uuid = UUID(job_id)

    with db_session() as db:
        job = job_service.get_job(db, job_uuid)
        if job is None:
            return

        if job.status in (JobStatus.COMPLETED, JobStatus.FAILED):
            return

        job_service.update_job_status(db, job_uuid, JobStatus.PROCESSING)
        handler = get_handler(job.job_type)
        input_payload = job.input_payload

    try:
        result = handler(input_payload)
    except Exception as exc:
        countdown = _backoff_seconds(self.request.retries)
        try:
            raise self.retry(exc=exc, countdown=countdown)
        except self.MaxRetriesExceededError:
            with db_session() as db:
                job_service.update_job_status(
                    db, job_uuid, JobStatus.FAILED, error_message=str(exc),
                )
            return

    with db_session() as db:
        job_service.update_job_status(
            db, job_uuid, JobStatus.COMPLETED, result_payload=result,
        )
