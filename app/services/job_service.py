from uuid import UUID

from sqlalchemy.orm import Session

from app.models.job import Job, JobStatus
from app.schemas.job_schema import JobCreate, JobResponse, JobListResponse


class JobService:
    def create_job(self, db: Session, payload: JobCreate) -> JobResponse:
        """Persist a pending job and dispatch it to Celery."""
        job = Job(
            job_type=payload.job_type,
            input_payload=payload.input,
            status=JobStatus.PENDING,
            priority=payload.priority,
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        from app.workers.celery_app import celery_app

        celery_app.send_task("process_job", args=[str(job.id)])

        return JobResponse.model_validate(job)

    def get_job(self, db: Session, job_id: UUID) -> JobResponse | None:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return None
        return JobResponse.model_validate(job)

    def list_jobs(self, db: Session, skip: int = 0, limit: int = 50) -> JobListResponse:
        """Return a page of jobs and the total count."""
        jobs = db.query(Job).offset(skip).limit(limit).all()
        total = db.query(Job).count()
        return JobListResponse(
            jobs=[JobResponse.model_validate(job) for job in jobs],
            total=total,
        )

    def update_job_status(
        self,
        db: Session,
        job_id: UUID,
        status: JobStatus,
        result_payload: dict | None = None,
        error_message: str | None = None,
    ) -> JobResponse | None:
        """Update job status and optional result or error fields."""
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return None
        job.status = status
        job.result_payload = result_payload
        job.error_message = error_message
        db.commit()
        db.refresh(job)
        return JobResponse.model_validate(job)


job_service = JobService()
