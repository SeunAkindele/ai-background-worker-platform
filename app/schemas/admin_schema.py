from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.models.job_log import LogLevel
from app.models.worker_heartbeat import WorkerStatus


class JobLogResponse(BaseModel):
    id: UUID
    job_id: UUID
    message: str
    level: LogLevel
    created_at: datetime

    model_config = {"from_attributes": True}


class JobLogListResponse(BaseModel):
    logs: list[JobLogResponse]
    total: int


class WorkerHeartbeatResponse(BaseModel):
    id: UUID
    worker_name: str
    worker_type: str
    status: WorkerStatus
    last_seen_at: datetime
    current_job_id: UUID | None
    jobs_completed: int
    jobs_failed: int

    model_config = {"from_attributes": True}


class WorkerHealthResponse(BaseModel):
    workers: list[WorkerHeartbeatResponse]
    total_online: int
    total_busy: int
    total_offline: int


class JobTypeStats(BaseModel):
    job_type: str
    total: int
    avg_duration_seconds: float | None


class DashboardResponse(BaseModel):
    total_jobs: int
    pending_jobs: int
    processing_jobs: int
    completed_jobs: int
    failed_jobs: int
    avg_processing_seconds: float | None
    slowest_job_types: list[JobTypeStats]
    queue_size: int
    workers: WorkerHealthResponse


class TopKJobResponse(BaseModel):
    job_id: UUID
    job_type: str
    duration_seconds: float