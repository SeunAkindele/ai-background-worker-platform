from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.job import Job, JobStatus
from app.schemas.job_schema import JobCreate, JobListResponse, JobResponse


class JobService:

    async def async_create_job(
        self, db: AsyncSession, payload: JobCreate
    ) -> JobResponse:
        """Persist a pending job and dispatch it to Celery by priority queue."""
        job = Job(
            job_type=payload.job_type,
            input_payload=payload.input,
            status=JobStatus.PENDING,
            priority=payload.priority,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)

        from app.workers.celery_app import celery_app

        queue_name = job.priority.value
        celery_app.send_task("process_job", args=[str(job.id)], queue=queue_name)

        return JobResponse.model_validate(job)

    async def async_get_job(
        self, db: AsyncSession, job_id: UUID
    ) -> JobResponse | None:
        stmt = select(Job).where(Job.id == job_id)
        result = await db.execute(stmt)
        job = result.scalars().first()
        if not job:
            return None
        return JobResponse.model_validate(job)

    async def async_list_jobs(
        self, db: AsyncSession, skip: int = 0, limit: int = 50
    ) -> JobListResponse:
        stmt = select(Job).offset(skip).limit(limit)
        result = await db.execute(stmt)
        jobs = result.scalars().all()

        count_stmt = select(func.count()).select_from(Job)
        count_result = await db.execute(count_stmt)
        total = count_result.scalar_one()

        return JobListResponse(
            jobs=[JobResponse.model_validate(job) for job in jobs],
            total=total,
        )

    def get_job(self, db: Session, job_id: UUID) -> JobResponse | None:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return None
        return JobResponse.model_validate(job)

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
