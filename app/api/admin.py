from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.admin_schema import (
    DashboardResponse,
    JobLogListResponse,
    JobLogResponse,
    TopKJobResponse,
    WorkerHealthResponse,
)
from app.services.admin_service import admin_service
from app.services.log_service import log_service

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/dashboard", response_model=DashboardResponse)
def dashboard(db: Session = Depends(get_db)):
    return admin_service.get_dashboard(db)


@router.get("/jobs/{job_id}/logs", response_model=JobLogListResponse)
def get_job_logs(
    job_id: UUID, limit: int = 100, db: Session = Depends(get_db)
):
    logs, total = log_service.get_logs_for_job(db, job_id, limit=limit)
    return JobLogListResponse(
        logs=[JobLogResponse.model_validate(log) for log in logs],
        total=total,
    )


@router.get("/errors", response_model=list[JobLogResponse])
def recent_errors(limit: int = 50, db: Session = Depends(get_db)):
    errors = log_service.get_recent_errors(db, limit=limit)
    return [JobLogResponse.model_validate(e) for e in errors]


@router.get(
    "/slowest-jobs", response_model=list[TopKJobResponse]
)
def slowest_jobs(k: int = 10, db: Session = Depends(get_db)):
    return admin_service.get_top_k_slowest_jobs(db, k=k)


@router.get("/workers", response_model=WorkerHealthResponse)
def worker_health(db: Session = Depends(get_db)):
    return admin_service.get_worker_health(db)