"""
Stage 13d — Pydantic schemas for RAG endpoints.

These schemas define the API contract:
- What the client sends (request bodies)
- What the server returns (response bodies)
- Validation rules enforced at the API boundary

Python Internals Focus:
-----------------------
- model_config = {"from_attributes": True} tells Pydantic v2 to read
  values from SQLAlchemy model attributes (e.g., document.title) instead
  of requiring a dict. This is what makes JobResponse.model_validate(job)
  work — it reads job.id, job.title, etc. from the ORM object.
"""
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


# ─── INGESTION (POST /documents/ingest) ─────────────────────────────

class DocumentIngestRequest(BaseModel):
    """
    Request body for document ingestion.
    
    The client sends the document text + metadata.
    The API creates a Document row and dispatches an INGESTION job.
    """
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
    # Let the user override chunking params per document.
    # Different document types benefit from different chunk sizes:
    # - Legal contracts: larger chunks (1024 words) for full clause context
    # - FAQ pages: smaller chunks (256 words) for precise answers
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
    """
    Response after submitting a document for ingestion.
    Includes both the document record and the job ID for polling.
    """
    document: DocumentResponse
    job_id: UUID
    message: str = "Document submitted for ingestion"


# ─── RAG QUERY (POST /rag/query) ────────────────────────────────────

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
    # Optional: restrict search to specific documents
    document_ids: list[UUID] | None = Field(
        default=None,
        description="Limit retrieval to these documents only",
    )


class RAGQueryResponse(BaseModel):
    """Returned immediately — contains the job ID for status polling."""
    job_id: UUID
    message: str = "RAG query submitted"


# Sync path — returns answer directly (ChatGPT-style)
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


# ─── CHUNKS (GET /documents/{id}/chunks) ────────────────────────────

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