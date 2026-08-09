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
        """Validate that input payload matches what the job type expects."""
        validators = {
            JobType.SUMMARIZATION: self._validate_summarization,
            JobType.EMBEDDINGS: self._validate_embeddings,
            JobType.OCR: self._validate_ocr,
            JobType.TRANSCRIPTION: self._validate_transcription,
            JobType.RECOMMENDATIONS: self._validate_recommendations,
            JobType.INGESTION: self._validate_ingestion,
            JobType.RAG_QUERY: self._validate_rag_query,
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
        file_id = self.input.get("file_id")

        if image is None and images is None and file_path is None and file_id is None:
            raise ValueError(
                "OCR requires 'image', 'images', 'file_path', or 'file_id'"
            )

        if file_id is not None:
            self._validate_uuid_string(file_id, "file_id")

    def _validate_transcription(self):
        file_path = self.input.get("file_path")
        audio_url = self.input.get("audio_url")
        text = self.input.get("text")
        file_id = self.input.get("file_id")

        if (
            file_path is None
            and audio_url is None
            and text is None
            and file_id is None
        ):
            raise ValueError(
                "Transcription requires 'file_path', 'audio_url', 'text', or 'file_id'"
            )

        if file_id is not None:
            self._validate_uuid_string(file_id, "file_id")

        duration = self.input.get("duration")
        if duration is not None:
            if not isinstance(duration, (int, float)) or duration <= 0:
                raise ValueError("'duration' must be a positive number (seconds)")

    def _validate_recommendations(self):
        user_id = self.input.get("user_id")
        interactions = self.input.get("interactions")
        if user_id is None:
            raise ValueError("Recommendations require a 'user_id'")
        if interactions is None or not isinstance(interactions, list):
            raise ValueError("Recommendations require 'interactions' (list)")

    @staticmethod
    def _validate_uuid_string(value: Any, field_name: str) -> None:
        if not isinstance(value, str):
            raise ValueError(f"'{field_name}' must be a UUID string")
        try:
            UUID(value)
        except ValueError as exc:
            raise ValueError(f"'{field_name}' must be a valid UUID") from exc

    
    def _validate_ingestion(self):
        doc_id = self.input.get("document_id")
        if doc_id is None:
            raise ValueError("Ingestion requires a 'document_id'")
        self._validate_uuid_string(doc_id, "document_id")
        
    def _validate_rag_query(self):
        question = self.input.get("question")
        if not question or not isinstance(question, str) or not question.strip():
            raise ValueError("RAG query requires a non-empty 'question' field")


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