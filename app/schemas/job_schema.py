from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.models.job import JobPriority, JobStatus, JobType


class JobCreate(BaseModel):
    job_type: JobType
    input: dict[str, Any] = Field(..., description="Job-specific input payload")
    priority: JobPriority = JobPriority.NORMAL

    @model_validator(mode="after")
    def validate_input_for_job_type(self):
        """Validate that the input payload matches the job type."""
        validators = {
            JobType.SUMMARIZATION: self._validate_summarization,
            JobType.EMBEDDINGS: self._validate_embeddings,
            JobType.OCR: self._validate_ocr,
            JobType.TRANSCRIPTION: self._validate_transcription,
            JobType.RECOMMENDATIONS: self._validate_recommendations,
        }

        validator = validators.get(self.job_type)
        if validator:
            validator()

        return self

    def _validate_summarization(self):
        text = self.input.get("text")
        if not text or not isinstance(text, str) or not text.strip():
            raise ValueError("Summarization requires a non-empty 'text' field")

    def _validate_embeddings(self):
        text = self.input.get("text")
        texts = self.input.get("texts")
        if text is None and texts is None:
            raise ValueError(
                "Embeddings require either 'text' (string) or 'texts' (list of strings)"
            )
        if texts is not None:
            if not isinstance(texts, list) or not all(isinstance(t, str) for t in texts):
                raise ValueError("'texts' must be a list of strings")
            if len(texts) == 0:
                raise ValueError("'texts' must not be empty")

    def _validate_ocr(self):
        image = self.input.get("image")
        images = self.input.get("images")
        file_path = self.input.get("file_path")
        if image is None and images is None and file_path is None:
            raise ValueError(
                "OCR requires 'image', 'images', or 'file_path'"
            )

    def _validate_transcription(self):
        file_path = self.input.get("file_path")
        audio_url = self.input.get("audio_url")
        text = self.input.get("text")
        if file_path is None and audio_url is None and text is None:
            raise ValueError(
                "Transcription requires 'file_path', 'audio_url', or 'text'"
            )

    def _validate_recommendations(self):
        user_id = self.input.get("user_id")
        interactions = self.input.get("interactions")
        if user_id is None:
            raise ValueError("Recommendations require a 'user_id'")
        if interactions is None or not isinstance(interactions, list):
            raise ValueError("Recommendations require 'interactions' (list)")


class JobResponse(BaseModel):
    id: UUID
    job_type: JobType
    status: JobStatus
    priority: JobPriority
    input_payload: dict[str, Any]
    result_payload: dict[str, Any] | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class JobListResponse(BaseModel):
    jobs: list[JobResponse]
    total: int