"""Pydantic schemas for document ingestion and RAG query endpoints."""
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class DocumentIngestRequest(BaseModel):
    """Request body for document ingestion."""

    title: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Human-readable name for this document",
    )
    content: str = Field(
        ...,
        min_length=1,
        description="The full text content to ingest",
    )
    source: str = Field(
        default="text",
        description="Where this document came from: 'text', 'upload', 'url'",
    )
    metadata: dict[str, Any] | None = Field(
        default=None,
        description="Optional metadata (author, department, tags, etc.)",
    )
    chunk_size: int = Field(default=512, ge=50, le=2000)
    chunk_overlap: int = Field(default=50, ge=0, le=500)


class DocumentResponse(BaseModel):
    id: UUID
    title: str
    source: str
    status: str
    metadata: dict[str, Any] | None = Field(None, alias="metadata_")
    chunk_size: int
    chunk_overlap: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True, "populate_by_name": True}


class DocumentIngestResponse(BaseModel):
    """Response after submitting a document for ingestion."""

    document: DocumentResponse
    job_id: UUID
    message: str = "Document submitted for ingestion"


class RAGQueryRequest(BaseModel):
    question: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="The question to answer",
    )
    top_k: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Number of chunks to retrieve",
    )
    document_ids: list[UUID] | None = Field(
        default=None,
        description="Limit retrieval to these documents only",
    )


class RAGQueryResponse(BaseModel):
    """Returned immediately with a job ID for status polling."""

    job_id: UUID
    message: str = "RAG query submitted"


class RAGSourceResponse(BaseModel):
    chunk_id: str
    document_id: str
    document_title: str
    chunk_index: int
    similarity: float
    text_preview: str


class RAGQuerySyncResponse(BaseModel):
    question: str
    answer: str
    sources: list[RAGSourceResponse]
    chunks_retrieved: int
    top_k_requested: int | None = None
    model: str | None = None


class ChunkResponse(BaseModel):
    id: UUID
    document_id: UUID
    content: str
    chunk_index: int
    token_count: int
    metadata: dict[str, Any] | None = Field(None, alias="metadata_")
    created_at: datetime

    model_config = {"from_attributes": True, "populate_by_name": True}


class ChunkListResponse(BaseModel):
    chunks: list[ChunkResponse]
    total: int
    document_id: UUID
