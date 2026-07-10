from uuid import UUID

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.file_storage import FileStorage, file_storage
from app.models.job_file import FilePurpose, JobFile
from app.schemas.file_schema import FileUploadResponse, JobFileResponse


class FileService:
    def __init__(self, storage: FileStorage | None = None):
        self.storage = storage or file_storage

    async def save_upload(
        self,
        db: AsyncSession,
        upload_file: UploadFile,
        purpose: FilePurpose,
    ) -> FileUploadResponse:
        stored_path, content_hash, file_size, file_type = (
            await self.storage.save_upload(upload_file, purpose)
        )

        existing = await self._find_by_hash(db, content_hash)
        if existing is not None:
            return FileUploadResponse(
                id=existing.id,
                original_filename=upload_file.filename or existing.original_filename,
                file_type=existing.file_type,
                file_size=existing.file_size,
                content_hash=existing.content_hash,
                purpose=existing.purpose,
                deduplicated=True,
                created_at=existing.created_at,
            )

        job_file = JobFile(
            original_filename=upload_file.filename or "unnamed",
            stored_path=stored_path,
            content_hash=content_hash,
            file_type=file_type,
            file_size=file_size,
            purpose=purpose,
        )
        db.add(job_file)
        await db.commit()
        await db.refresh(job_file)

        return FileUploadResponse(
            id=job_file.id,
            original_filename=job_file.original_filename,
            file_type=job_file.file_type,
            file_size=job_file.file_size,
            content_hash=job_file.content_hash,
            purpose=job_file.purpose,
            deduplicated=False,
            created_at=job_file.created_at,
        )

    async def get_file(
        self, db: AsyncSession, file_id: UUID
    ) -> JobFile | None:
        stmt = select(JobFile).where(JobFile.id == file_id)
        result = await db.execute(stmt)
        return result.scalars().first()

    async def get_file_for_job(
        self, db: AsyncSession, job_id: UUID
    ) -> JobFile | None:
        stmt = select(JobFile).where(JobFile.job_id == job_id)
        result = await db.execute(stmt)
        return result.scalars().first()

    async def link_file_to_job(
        self,
        db: AsyncSession,
        file_id: UUID,
        job_id: UUID,
    ) -> JobFileResponse:
        job_file = await self.get_file(db, file_id)
        if job_file is None:
            raise ValueError(f"File {file_id} not found")

        job_file.job_id = job_id
        await db.commit()
        await db.refresh(job_file)
        return JobFileResponse.model_validate(job_file)

    def resolve_absolute_path(self, job_file: JobFile) -> str:
        return str(self.storage.resolve_absolute_path(job_file.stored_path))

    async def _find_by_hash(
        self, db: AsyncSession, content_hash: str
    ) -> JobFile | None:
        stmt = select(JobFile).where(JobFile.content_hash == content_hash)
        result = await db.execute(stmt)
        return result.scalars().first()


file_service = FileService()