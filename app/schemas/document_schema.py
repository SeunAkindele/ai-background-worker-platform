"""Pydantic schemas for document ingest and RAG query endpoints."""
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
    """Document record plus job ID for ingestion status polling."""
    document: DocumentResponse
    job_id: UUID
    message: str = "Document submitted for ingestion"


class RAGQueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    retrieve_k: int = Field(default=50, ge=1, le=100)
    keep_top_n: int = Field(default=3, ge=1, le=10)
    top_k: int | None = Field(
        default=None,
        description="Deprecated alias for retrieve_k",
    )
    document_ids: list[UUID] | None = None
    metadata_filter: dict[str, Any] | None = Field(
        default=None,
        description='e.g. {"department":"legal","page":3}',
    )
    use_multi_query: bool = True
    use_rerank: bool = True
    use_small_to_big: bool = True
    use_chain: bool = False
    use_router: bool = False
    force_route: str | None = Field(
        default=None,
        description='Override router: "cache", "vector", "sql", or "web"',
    )
    use_critic: bool = False
    max_critic_attempts: int = Field(default=2, ge=1, le=3)
    use_eval: bool = False


class RAGQueryResponse(BaseModel):
    """Immediate ack with job ID for status polling."""
    job_id: UUID
    message: str = "RAG query submitted"
    mode: str = "inline"  # "inline" | "chain"
    step_job_ids: dict[str, UUID] | None = None


class RAGSourceResponse(BaseModel):
    """Vector-chunk citation, or a web/SQL hit (extra fields allowed)."""
    model_config = {"extra": "allow"}
    chunk_id: str | None = None
    document_id: str | None = None
    document_title: str | None = None
    chunk_index: int | None = None
    similarity: float | None = None
    text_preview: str | None = None
    title: str | None = None
    url: str | None = None


class RAGQuerySyncResponse(BaseModel):
    question: str
    answer: str
    sources: list[RAGSourceResponse]
    chunks_retrieved: int
    top_k_requested: int | None = None
    model: str | None = None
    route: str | None = None


class ChunkResponse(BaseModel):
    id: UUID
    document_id: UUID
    content: str
    chunk_index: int
    token_count: int
    level: str = "child"
    parent_chunk_id: UUID | None = None
    metadata: dict[str, Any] | None = Field(None, alias="metadata_")
    created_at: datetime

    model_config = {"from_attributes": True, "populate_by_name": True}


class ChunkListResponse(BaseModel):
    chunks: list[ChunkResponse]
    total: int
    document_id: UUID
