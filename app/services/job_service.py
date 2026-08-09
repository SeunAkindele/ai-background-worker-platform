from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.job import Job, JobPriority, JobStatus
from app.models.job_file import FilePurpose
from app.schemas.job_schema import JobCreate, JobListResponse, JobResponse
from app.services.file_service import file_service


# JobPriority → Celery integer priority (lower = higher priority).
# Matches priority_steps in celery_app.py: [0, 5, 9].
PRIORITY_TO_CELERY = {
    JobPriority.HIGH: 0,
    JobPriority.NORMAL: 5,
    JobPriority.LOW: 9,
}


class JobService:

    async def async_create_job(
        self, db: AsyncSession, payload: JobCreate
    ) -> JobResponse:
        """Create a job; resolve file_id to an on-disk path when present."""
        input_payload = dict(payload.input)
        file_id_raw = input_payload.get("file_id")

        if file_id_raw is not None:
            input_payload = await self._resolve_file_input(
                db, payload.job_type.value, input_payload
            )

        job = Job(
            job_type=payload.job_type,
            input_payload=input_payload,
            status=JobStatus.PENDING,
            priority=payload.priority,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)

        if file_id_raw is not None:
            await file_service.link_file_to_job(
                db, UUID(str(file_id_raw)), job.id
            )

        from app.workers.celery_app import celery_app

        queue_name = job.job_type.value
        task_priority = PRIORITY_TO_CELERY.get(job.priority, 5)
        celery_app.send_task(
            "process_job", 
            args=[str(job.id)], 
            queue=queue_name, 
            priority=task_priority
        )

        return JobResponse.model_validate(job)

    async def _resolve_file_input(
        self,
        db: AsyncSession,
        job_type: str,
        input_payload: dict,
    ) -> dict:
        file_id = UUID(str(input_payload["file_id"]))
        job_file = await file_service.get_file(db, file_id)

        if job_file is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Uploaded file {file_id} not found",
            )

        expected_purpose = {
            "ocr": FilePurpose.OCR,
            "transcription": FilePurpose.TRANSCRIPTION,
        }.get(job_type)

        if expected_purpose and job_file.purpose != expected_purpose:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"File purpose '{job_file.purpose.value}' does not match "
                    f"job type '{job_type}'"
                ),
            )

        resolved = dict(input_payload)
        resolved["file_path"] = file_service.resolve_absolute_path(job_file)
        resolved["original_filename"] = job_file.original_filename
        resolved["file_type"] = job_file.file_type
        resolved["file_size"] = job_file.file_size
        return resolved

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