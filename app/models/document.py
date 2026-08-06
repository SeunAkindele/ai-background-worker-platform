"""
Stage 13a — RAG data models: Document → Chunk → ChunkEmbedding.

DSA Focus:
----------
- The three-table design mirrors how production RAG systems work:
  1. Document: the original source (a file, a web page, pasted text)
  2. Chunk: a slice of the document (paragraph, 512-token window, etc.)
  3. ChunkEmbedding: the vector representation of that chunk

  Why not store the vector on the Chunk row directly?
  - Separation of concerns: you might re-embed with a different model
    without touching the chunk text
  - Different embedding models produce different dimensions (384 vs 768
    vs 1536) — a separate table lets you store multiple embeddings per chunk
  - In Stage 14, you'll add metadata filtering on chunks WITHOUT loading
    the (large) vector column

Python Internals Focus:
-----------------------
- pgvector's Vector type maps to PostgreSQL's vector(n) column.
  In Python, it appears as a plain list[float]. The pgvector library
  handles serialization/deserialization transparently.
- relationship() with back_populates creates a bidirectional link.
  Accessing document.chunks triggers a lazy SQL query. In workers
  (sync sessions), this Just Works. In async routes, you'd need
  selectinload() to avoid lazy-load errors.
"""
import enum
import uuid
from datetime import datetime
from typing import Any, Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class DocumentStatus(str, enum.Enum):
    """
    Tracks the lifecycle of a document through the ingestion pipeline.
    
    PENDING   → just created, ingestion job not started yet
    INGESTING → worker picked it up, chunking/embedding in progress
    READY     → all chunks embedded, available for RAG queries
    FAILED    → something went wrong during ingestion
    """
    PENDING = "pending"
    INGESTING = "ingesting"
    READY = "ready"
    FAILED = "failed"


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # The human-readable name — could be a filename, URL, or user-provided title
    title: Mapped[str] = mapped_column(Text, nullable=False)
    # Where this document came from: "upload", "text", "url"
    source: Mapped[str] = mapped_column(Text, nullable=False, default="text")
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus), nullable=False, default=DocumentStatus.PENDING
    )

    # The FULL original text. We keep this so you can re-chunk later
    # (Stage 14 small-to-big indexing needs the original).
    # For very large documents (>10MB), you'd store this in S3/file system
    # and keep only a reference here. For Stage 13, inline is fine.
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Flexible metadata bag — source URL, author, department, upload date.
    # JSONB is indexed and queryable in Postgres (Stage 14 metadata filtering).
    metadata_: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata",  # Column name in DB is "metadata" (without underscore).
        # We use metadata_ as the Python attribute because metadata is
        # a reserved name in SQLAlchemy's DeclarativeBase (it refers to
        # the MetaData registry that tracks all tables). Using "metadata"
        # as an attribute would shadow Base.metadata and break table creation.
        JSONB,
        nullable=True,
    )

    chunk_size: Mapped[int] = mapped_column(Integer, default=512)
    chunk_overlap: Mapped[int] = mapped_column(Integer, default=50)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # ORM relationship — access chunks via document.chunks (lazy load).
    # cascade="all, delete-orphan" means deleting a Document automatically
    # deletes all its Chunks (and transitively, their embeddings).
    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    # The actual text slice
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Position tracking — which chunk is this in the document?
    # Essential for reassembling context in order (Stage 14 small-to-big).
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)

    # Token count for this chunk — useful for prompt budget calculations.
    # When building a RAG prompt, you need to know: "do my top-K chunks
    # fit within the LLM's context window?"
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Per-chunk metadata (page number, section header, etc.)
    # Separate from document-level metadata — Stage 14 will filter on this.
    metadata_: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSONB, nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    document: Mapped["Document"] = relationship(back_populates="chunks")
    embedding: Mapped[Optional["ChunkEmbedding"]] = relationship(
        back_populates="chunk", cascade="all, delete-orphan", uselist=False
    )

    # Composite index: quickly find all chunks for a document, in order.
    # Without this, SELECT ... WHERE document_id = ? ORDER BY chunk_index
    # would do a sequential scan on large tables.
    __table_args__ = (
        Index("ix_chunks_document_id_chunk_index", "document_id", "chunk_index"),
    )


# ─── WHY 384 DIMENSIONS? ────────────────────────────────────────────
# all-MiniLM-L6-v2 (your existing EmbeddingHandler model) produces
# 384-dimensional vectors. If you switch to a larger model later
# (e.g., text-embedding-3-small = 1536 dims), you'd change this
# constant and re-embed all documents.
EMBEDDING_DIMENSIONS = 384


class ChunkEmbedding(Base):
    __tablename__ = "chunk_embeddings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chunks.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,  # One embedding per chunk (for now)
    )
    # The vector column. Vector(384) stores a fixed-size float array.
    # pgvector validates that every inserted vector has exactly 384 dims.
    # In Python, you read/write this as a plain list[float].
    embedding: Mapped[list] = mapped_column(
        Vector(EMBEDDING_DIMENSIONS), nullable=False
    )
    # Which model produced this embedding — for reproducibility and
    # to detect stale embeddings after a model upgrade.
    model_name: Mapped[str] = mapped_column(
        Text, nullable=False, default="all-MiniLM-L6-v2"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    chunk: Mapped["Chunk"] = relationship(back_populates="embedding")

    # ─── HNSW INDEX ──────────────────────────────────────────────────
    # This is the key to fast top-K retrieval. Without an index,
    # pgvector does an exact (brute-force) scan — O(n) per query,
    # comparing your query vector against EVERY stored vector.
    #
    # HNSW (Hierarchical Navigable Small World) is an approximate
    # nearest neighbor (ANN) algorithm. Think of it as a skip-list
    # for vectors: it builds a multi-layer graph where:
    #   - Top layers: few nodes, long jumps (coarse search)
    #   - Bottom layers: many nodes, short jumps (fine search)
    #
    # vector_cosine_ops: tells pgvector to use cosine distance (<=>)
    # for this index. Must match the operator you use in queries.
    #
    # Without this index: 100K vectors → ~200ms per query
    # With this index:    100K vectors → ~5ms per query
    #
    # Trade-off: HNSW uses more memory and INSERT is slower (~2x).
    # For Stage 13, this is fine. At millions of vectors, you'd tune
    # m (connections per node) and ef_construction (build quality).
    __table_args__ = (
        Index(
            "ix_chunk_embeddings_vector",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )