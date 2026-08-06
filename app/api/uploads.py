from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import enforce_pending_limit, enforce_rate_limit
from app.core.file_storage import FileValidationError
from app.models.job import JobPriority, JobType
from app.models.job_file import FilePurpose
from app.schemas.file_schema import FileUploadResponse, JobFileResponse
from app.schemas.job_schema import JobCreate, JobResponse
from app.services.file_service import file_service
from app.services.job_service import job_service

router = APIRouter(prefix="/uploads", tags=["uploads"])

JOB_TYPE_TO_PURPOSE = {
    JobType.OCR: FilePurpose.OCR,
    JobType.TRANSCRIPTION: FilePurpose.TRANSCRIPTION,
}


@router.post("", response_model=FileUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_file(
    file: UploadFile = File(...),
    purpose: FilePurpose = Form(...),
    db: AsyncSession = Depends(get_async_db),
    _client: str = Depends(enforce_rate_limit),
):
    """Upload a file for later use in a job."""
    try:
        return await file_service.save_upload(db, file, purpose)
    except FileValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post("/job", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def create_job_with_upload(
    job_type: JobType = Form(...),
    file: UploadFile = File(...),
    priority: JobPriority = Form(JobPriority.NORMAL),
    db: AsyncSession = Depends(get_async_db),
    _client: str = Depends(enforce_rate_limit),
    _pending: None = Depends(enforce_pending_limit),
):
    """Upload a file and create an OCR or transcription job in one request."""
    if job_type not in JOB_TYPE_TO_PURPOSE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Job type '{job_type.value}' does not accept file uploads",
        )

    purpose = JOB_TYPE_TO_PURPOSE[job_type]

    try:
        upload_result = await file_service.save_upload(db, file, purpose)
    except FileValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    payload = JobCreate(
        job_type=job_type,
        priority=priority,
        input={"file_id": str(upload_result.id)},
    )
    return await job_service.async_create_job(db, payload)


@router.get("/{file_id}", response_model=JobFileResponse)
async def get_upload_metadata(
    file_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    _client: str = Depends(enforce_rate_limit),
):
    job_file = await file_service.get_file(db, file_id)
    if job_file is None:
        raise HTTPException(status_code=404, detail="File not found")
    return JobFileResponse.model_validate(job_file)