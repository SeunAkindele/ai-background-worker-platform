from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.job import JobStatus, JobType


class JobCreate(BaseModel):
    job_type: JobType
    input: dict[str, Any] = Field(..., description="Job-specific input payload")


class JobResponse(BaseModel):
    id: UUID
    job_type: JobType
    status: JobStatus
    input_payload: dict[str, Any]
    result_payload: dict[str, Any] | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}  # read from SQLAlchemy ORM objects


class JobListResponse(BaseModel):
    jobs: list[JobResponse]
    total: int