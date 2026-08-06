from uuid import UUID

from sqlalchemy.orm import Session

from app.core.queue import job_queue
from app.models.job import Job, JobStatus
from app.schemas.job_schema import JobCreate, JobResponse, JobListResponse


class JobService:
    def create_job(self, db: Session, payload: JobCreate) -> JobResponse:
        """
        1. Create Job row with status=pending
        2. Commit to DB
        3. Enqueue job.id
        4. Return job
        """
        
        job = Job(
            job_type=payload.job_type,
            input_payload=payload.input,
            status=JobStatus.PENDING,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        job_queue.enqueue(job.id)
        return JobResponse.model_validate(job)

    def get_job(self, db: Session, job_id: UUID) -> JobResponse | None:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return None
        return JobResponse.model_validate(job)

    def list_jobs(self, db: Session, skip: int = 0, limit: int = 50) -> JobListResponse:
        """
        Return (jobs, total_count) for pagination.
        """
        jobs = db.query(Job).offset(skip).limit(limit).all()
        total = db.query(Job).count()
        return JobListResponse(jobs=[JobResponse.model_validate(job) for job in jobs], total=total)

    def update_job_status(
        self,
        db: Session,
        job_id: UUID,
        status: JobStatus,
        result_payload: dict | None = None,
        error_message: str | None = None,
    ) -> Job | None:
        """Update job status and optional result or error payload."""

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
