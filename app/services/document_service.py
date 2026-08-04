"""
Stage 13d — Document service: business logic for RAG operations.

This follows the same pattern as your existing JobService:
- Async methods for API routes (FastAPI is async)
- Sync methods reused by workers (Celery is sync)
- Service singleton at module level
"""
import asyncio
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Chunk, Document, DocumentStatus
from app.models.job import JobPriority, JobStatus, JobType, Job
from app.schemas.document_schema import (
    ChunkListResponse,
    ChunkResponse,
    DocumentIngestRequest,
    DocumentIngestResponse,
    DocumentResponse,
    RAGQueryRequest,
    RAGQueryResponse,
    RAGQuerySyncResponse,
)
from app.services.job_service import PRIORITY_TO_CELERY
from app.workers.handlers import get_handler


class DocumentService:

    async def ingest_document(
        self, db: AsyncSession, payload: DocumentIngestRequest
    ) -> DocumentIngestResponse:
        """
        Two-phase operation:
        1. Create the Document row (PENDING status)
        2. Create an INGESTION job that references the document
        
        The document is NOT queryable until the ingestion worker
        finishes and sets status = READY. This prevents partial
        results from appearing in RAG queries.
        """
        # Phase 1: Create the document record
        document = Document(
            title=payload.title,
            content=payload.content,
            source=payload.source,
            metadata_=payload.metadata,
            chunk_size=payload.chunk_size,
            chunk_overlap=payload.chunk_overlap,
            status=DocumentStatus.PENDING,
        )
        db.add(document)
        await db.commit()
        await db.refresh(document)

        # Phase 2: Create a job to process this document asynchronously.
        # We reuse the existing job infrastructure: same Job table, same
        # Celery dispatch, same status polling via GET /jobs/{id}.
        job = Job(
            job_type=JobType.INGESTION,
            input_payload={
                "document_id": str(document.id),
                "chunk_size": payload.chunk_size,
                "chunk_overlap": payload.chunk_overlap,
            },
            status=JobStatus.PENDING,
            priority=JobPriority.NORMAL,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)

        # Dispatch to Celery
        from app.workers.celery_app import celery_app

        celery_app.send_task(
            "process_job",
            args=[str(job.id)],
            queue="ingestion",
            priority=PRIORITY_TO_CELERY[JobPriority.NORMAL],
        )

        return DocumentIngestResponse(
            document=DocumentResponse.model_validate(document),
            job_id=job.id,
        )
    
    # ─── ASYNC RAG (job queue) ───────────────────────────────────────

    async def submit_rag_query(
        self, db: AsyncSession, payload: RAGQueryRequest
    ) -> RAGQueryResponse:
        """
        Submit a RAG query as an async job.
        
        Why async (job queue) instead of synchronous (request-response)?
        - Embedding the question: ~100ms
        - Vector search: ~5-50ms
        - LLM generation: ~2-10 seconds
        Total: 2-10+ seconds. Too slow for a synchronous HTTP request
        that would block a FastAPI worker. The job queue lets the user
        poll for results while the API stays responsive.
        """
        input_payload = {
            "question": payload.question,
            "top_k": payload.top_k,
        }
        if payload.document_ids:
            input_payload["document_ids"] = [
                str(did) for did in payload.document_ids
            ]

        job = Job(
            job_type=JobType.RAG_QUERY,
            input_payload=input_payload,
            status=JobStatus.PENDING,
            priority=JobPriority.NORMAL,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)

        from app.workers.celery_app import celery_app

        celery_app.send_task(
            "process_job",
            args=[str(job.id)],
            queue="rag_query",
            priority=PRIORITY_TO_CELERY[JobPriority.NORMAL],
        )

        return RAGQueryResponse(job_id=job.id)


    async def run_rag_query_sync(
        self, payload: RAGQueryRequest
    ) -> RAGQuerySyncResponse:
        """
        Runs RAG inline and returns the answer in the same HTTP response.
        Uses asyncio.to_thread() so CPU-heavy model work does not block
        the FastAPI event loop while other requests are handled.
        """
        input_payload = {
            "question": payload.question,
            "top_k": payload.top_k,
        }
        if payload.document_ids:
            input_payload["document_ids"] = [
                str(did) for did in payload.document_ids
            ]
        handler = get_handler(JobType.RAG_QUERY)
        try:
            # Run sync handler in a worker thread
            result = await asyncio.to_thread(handler, input_payload)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"RAG query failed: {exc}",
            ) from exc
        return RAGQuerySyncResponse.model_validate(result)


    async def get_document(
        self, db: AsyncSession, document_id: UUID
    ) -> DocumentResponse | None:
        stmt = select(Document).where(Document.id == document_id)
        result = await db.execute(stmt)
        document = result.scalars().first()
        if not document:
            return None
        return DocumentResponse.model_validate(document)

    async def get_document_chunks(
        self, db: AsyncSession, document_id: UUID, skip: int = 0, limit: int = 50
    ) -> ChunkListResponse:
        """
        Return all chunks for a document, ordered by chunk_index.
        
        This endpoint is useful for:
        - Debugging: "what did the chunker produce?"
        - UI: showing the user how their document was split
        - Stage 14: inspecting which chunks were retrieved for a query
        """
        # First verify the document exists
        doc_stmt = select(Document).where(Document.id == document_id)
        doc_result = await db.execute(doc_stmt)
        document = doc_result.scalars().first()
        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document {document_id} not found",
            )

        # Count total chunks
        count_stmt = (
            select(func.count())
            .select_from(Chunk)
            .where(Chunk.document_id == document_id)
        )
        count_result = await db.execute(count_stmt)
        total = count_result.scalar_one()

        # Fetch paginated chunks, ordered by position in the document
        chunks_stmt = (
            select(Chunk)
            .where(Chunk.document_id == document_id)
            .order_by(Chunk.chunk_index)
            .offset(skip)
            .limit(limit)
        )
        chunks_result = await db.execute(chunks_stmt)
        chunks = chunks_result.scalars().all()

        return ChunkListResponse(
            chunks=[ChunkResponse.model_validate(c) for c in chunks],
            total=total,
            document_id=document_id,
        )


document_service = DocumentService()