from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import enforce_pending_limit, enforce_rate_limit
from app.schemas.file_schema import JobFileResponse
from app.schemas.job_schema import JobCreate, JobListResponse, JobResponse
from app.services.file_service import file_service
from app.services.job_service import job_service

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def create_job(
    payload: JobCreate,
    db: AsyncSession = Depends(get_async_db),
    _client: str = Depends(enforce_rate_limit),
    _pending: None = Depends(enforce_pending_limit),
):
    """
    Submit a new job.

    Python Internals Focus:
    -----------------------
    This is now `async def` — it's a coroutine function.
    When FastAPI receives a request, it calls this function which returns
    a coroutine object. The event loop schedules it and starts executing
    until the first `await` (inside async_create_job), at which point
    it suspends and can handle other requests.

    The Depends() parameters create a dependency chain:
    1. get_async_db → opens DB session
    2. enforce_rate_limit → checks sliding window counter
    3. enforce_pending_limit → checks queue backpressure

    If any dependency raises HTTPException, the route never executes.
    This is the "fail fast" principle applied to the request lifecycle.
    """
    job = await job_service.async_create_job(db, payload)
    return job


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    _client: str = Depends(enforce_rate_limit),
):
    """
    Poll job status.

    This endpoint will be called frequently by clients waiting for results.
    Being async means hundreds of polling requests can be in-flight
    simultaneously without thread exhaustion.

    Python Internals:
    UUID in the path parameter — FastAPI uses Pydantic to parse the
    string from the URL into a UUID object. If it's not a valid UUID,
    FastAPI returns 422 automatically.
    """
    job = await job_service.async_get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/{job_id}/file", response_model=JobFileResponse)
async def get_job_file(
    job_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    _client: str = Depends(enforce_rate_limit),
):
    """Return metadata for the file attached to this job, if any."""
    job = await job_service.async_get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    job_file = await file_service.get_file_for_job(db, job_id)
    if job_file is None:
        raise HTTPException(status_code=404, detail="No file linked to this job")
    return JobFileResponse.model_validate(job_file)


@router.get("", response_model=JobListResponse)
async def list_jobs(
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(50, ge=1, le=100, description="Max records to return"),
    db: AsyncSession = Depends(get_async_db),
    _client: str = Depends(enforce_rate_limit),
):
    return await job_service.async_list_jobs(db, skip=skip, limit=limit)