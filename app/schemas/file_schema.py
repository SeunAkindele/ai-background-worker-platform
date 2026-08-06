from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.job_file import FilePurpose


class FileUploadResponse(BaseModel):
    id: UUID
    original_filename: str
    file_type: str
    file_size: int
    content_hash: str
    purpose: FilePurpose
    deduplicated: bool = Field(
        description="True if this upload matched an existing file by hash"
    )
    created_at: datetime

    model_config = {"from_attributes": True}


class JobFileResponse(BaseModel):
    id: UUID
    job_id: UUID | None
    original_filename: str
    file_type: str
    file_size: int
    content_hash: str
    purpose: FilePurpose
    created_at: datetime

    model_config = {"from_attributes": True}