from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import enforce_pending_limit, enforce_rate_limit
from app.schemas.job_schema import JobCreate, JobListResponse, JobResponse
from app.services.job_service import job_service

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def create_job(
    payload: JobCreate,
    db: AsyncSession = Depends(get_async_db),
    _client: str = Depends(enforce_rate_limit),
    _pending: None = Depends(enforce_pending_limit),
):
    """Submit a new job."""
    job = await job_service.async_create_job(db, payload)
    return job


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    _client: str = Depends(enforce_rate_limit),
):
    """Fetch a job by ID."""
    job = await job_service.async_get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("", response_model=JobListResponse)
async def list_jobs(
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(50, ge=1, le=100, description="Max records to return"),
    db: AsyncSession = Depends(get_async_db),
    _client: str = Depends(enforce_rate_limit),
):
    return await job_service.async_list_jobs(db, skip=skip, limit=limit)
