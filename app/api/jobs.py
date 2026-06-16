from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.job_schema import JobCreate, JobListResponse, JobResponse
from app.services.job_service import job_service

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
def create_job(payload: JobCreate, db: Session = Depends(get_db)):
    job = job_service.create_job(db, payload)
    return job


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: UUID, db: Session = Depends(get_db)):
    job = job_service.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("", response_model=JobListResponse)
def list_jobs(skip: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    return job_service.list_jobs(db, skip=skip, limit=limit)
    