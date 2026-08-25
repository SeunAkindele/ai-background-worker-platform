from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import enforce_rate_limit
from app.schemas.admin_schema import (
    DashboardResponse,
    JobLogListResponse,
    JobLogResponse,
    RagDashboardResponse,
    TopKJobResponse,
    WorkerHealthResponse,
)
from app.services.admin_service import admin_service
from app.services.log_service import log_service

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/dashboard", response_model=DashboardResponse)
async def dashboard(
    db: AsyncSession = Depends(get_async_db),
    _client: str = Depends(enforce_rate_limit),
):
    return await admin_service.async_get_dashboard(db)


@router.get("/jobs/{job_id}/logs", response_model=JobLogListResponse)
async def get_job_logs(
    job_id: UUID,
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(100, ge=1, le=500, description="Max records to return"),
    db: AsyncSession = Depends(get_async_db),
    _client: str = Depends(enforce_rate_limit),
):
    logs, total = await log_service.async_get_logs_for_job(
        db, job_id, skip=skip, limit=limit
    )
    return JobLogListResponse(
        logs=[JobLogResponse.model_validate(log) for log in logs],
        total=total,
    )


@router.get("/errors", response_model=list[JobLogResponse])
async def recent_errors(
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(50, ge=1, le=500, description="Max records to return"),
    db: AsyncSession = Depends(get_async_db),
    _client: str = Depends(enforce_rate_limit),
):
    errors = await log_service.async_get_recent_errors(db, skip=skip, limit=limit)
    return [JobLogResponse.model_validate(e) for e in errors]


@router.get("/slowest-jobs", response_model=list[TopKJobResponse])
async def slowest_jobs(
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(10, ge=1, le=100, description="Max records to return"),
    db: AsyncSession = Depends(get_async_db),
    _client: str = Depends(enforce_rate_limit),
):
    return await admin_service.async_get_top_k_slowest_jobs(
        db, skip=skip, limit=limit
    )


@router.get("/workers", response_model=WorkerHealthResponse)
async def worker_health(
    db: AsyncSession = Depends(get_async_db),
    _client: str = Depends(enforce_rate_limit),
):
    return await admin_service.async_get_worker_health(db)


@router.get("/rag/dashboard", response_model=RagDashboardResponse)
async def rag_dashboard(
    window_hours: int = Query(24, ge=1, le=24 * 30),
    grounding_threshold: float = Query(0.25, ge=0.0, le=1.0),
    slow_k: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_async_db),
    _client: str = Depends(enforce_rate_limit),
):
    return await admin_service.async_get_rag_dashboard(
        db,
        window_hours=window_hours,
        grounding_threshold=grounding_threshold,
        slow_k=slow_k,
    )
    