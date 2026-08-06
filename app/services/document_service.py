"""Document and RAG query service for API routes."""
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
        """Create a document record and enqueue an ingestion job."""
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

    async def submit_rag_query(
        self, db: AsyncSession, payload: RAGQueryRequest
    ) -> RAGQueryResponse:
        """Enqueue a RAG query job and return its ID for polling."""
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
        Run RAG inline and return the answer in the same HTTP response.
        Uses asyncio.to_thread() so model work does not block the event loop.
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
        """Return paginated chunks for a document, ordered by chunk_index."""
        doc_stmt = select(Document).where(Document.id == document_id)
        doc_result = await db.execute(doc_stmt)
        document = doc_result.scalars().first()
        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document {document_id} not found",
            )

        count_stmt = (
            select(func.count())
            .select_from(Chunk)
            .where(Chunk.document_id == document_id)
        )
        count_result = await db.execute(count_stmt)
        total = count_result.scalar_one()

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
