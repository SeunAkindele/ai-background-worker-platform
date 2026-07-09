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
        """
        Create a job asynchronously.

        Python Internals Focus:
        -----------------------
        `await db.commit()` suspends this coroutine and yields control back
        to the event loop. While Postgres processes our INSERT, the event loop
        can handle other incoming HTTP requests.

        Compare with the sync version below: `db.commit()` blocks the entire
        thread until Postgres responds. With 4 Uvicorn threads, only 4
        requests can be in-flight at once. With async, hundreds can be
        in-flight because they're all just suspended coroutines (very cheap).

        A coroutine costs ~200 bytes of memory. A thread costs ~8MB of stack.
        This is why async is perfect for I/O-bound API work.
        """
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
        """
        Python Internals Focus:
        -----------------------
        `select(Job).where(...)` builds a SQL expression object (lazy).
        `await db.execute(stmt)` sends it to Postgres (suspends coroutine).
        `.scalars().first()` extracts the ORM object from the result proxy.

        This is the "new style" SQLAlchemy 2.0 query API. The old
        `db.query(Job).filter(...)` style doesn't work with AsyncSession
        because .query() triggers synchronous I/O internally.
        """
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
    ) -> JobResponse:
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