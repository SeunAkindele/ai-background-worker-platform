"""Document and RAG query business logic for API routes."""
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
        """Create a document row and dispatch an ingestion job."""
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

    
    def _build_rag_input(self, payload: RAGQueryRequest) -> dict:
        """
        Shared payload for inline + chain.

        Never send top_k=null into the handler — resolve a concrete
        retrieve_k here and omit top_k entirely.
        """
        retrieve_k = payload.retrieve_k
        if payload.top_k is not None:
            retrieve_k = payload.top_k
        data = {
            "question": payload.question,
            "retrieve_k": retrieve_k,
            "keep_top_n": payload.keep_top_n,
            "use_multi_query": payload.use_multi_query,
            "use_rerank": payload.use_rerank,
            "use_small_to_big": payload.use_small_to_big,
            "use_router": payload.use_router,
            "use_critic": payload.use_critic,
            "max_critic_attempts": payload.max_critic_attempts,
            "use_eval": payload.use_eval,
        }
        if payload.force_route:
            data["force_route"] = payload.force_route
        if payload.document_ids:
            data["document_ids"] = [str(d) for d in payload.document_ids]
        if payload.metadata_filter:
            data["metadata_filter"] = payload.metadata_filter
        return data
    
    async def submit_rag_query(
        self, db: AsyncSession, payload: RAGQueryRequest
    ) -> RAGQueryResponse:
        """Submit a RAG query as an async job (inline or chain)."""
        input_payload = self._build_rag_input(payload)

        if payload.use_chain:
            return await self.submit_rag_query_chain(db, input_payload)


        job = Job(
            job_type=JobType.RAG_QUERY,
            input_payload={**input_payload, "mode": "inline"},
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

        return RAGQueryResponse(
            job_id=job.id,
            message="RAG query submitted (inline)",
            mode="inline",
        )


    async def submit_rag_query_chain(
        self, db: AsyncSession, input_payload: dict
    ) -> RAGQueryResponse:
        """
        Create parent + 4 step jobs, then start Celery chain.
        Parent is completed by the FINAL chain task (not process_job).
        """
        parent = Job(
            job_type=JobType.RAG_QUERY,
            input_payload={**input_payload, "mode": "chain"},
            status=JobStatus.PENDING,
            priority=JobPriority.NORMAL,
        )
        db.add(parent)
        await db.flush()  # need parent.id
        expand = Job(
            job_type=JobType.QUERY_EXPAND,
            input_payload={
                "question": input_payload["question"],
                "num_queries": 3 if input_payload.get("use_multi_query", True) else 1,
                "parent_job_id": str(parent.id),
            },
            status=JobStatus.PENDING,
            priority=JobPriority.NORMAL,
        )
        retrieve = Job(
            job_type=JobType.RAG_RETRIEVE,
            input_payload={
                **input_payload,
                "parent_job_id": str(parent.id),
            },
            status=JobStatus.PENDING,
            priority=JobPriority.NORMAL,
        )
        rerank = Job(
            job_type=JobType.RERANK,
            input_payload={
                "question": input_payload["question"],
                "keep_top_n": input_payload.get("keep_top_n", 3),
                "parent_job_id": str(parent.id),
                # candidates filled by previous chain step into this job at runtime
            },
            status=JobStatus.PENDING,
            priority=JobPriority.NORMAL,
        )
        generate = Job(
            job_type=JobType.RAG_GENERATE,
            input_payload={
                **input_payload,
                "parent_job_id": str(parent.id),
            },
            status=JobStatus.PENDING,
            priority=JobPriority.NORMAL,
        )
        db.add_all([expand, retrieve, rerank, generate])
        await db.commit()
        for j in (parent, expand, retrieve, rerank, generate):
            await db.refresh(j)
        step_ids = {
            "expand": expand.id,
            "retrieve": retrieve.id,
            "rerank": rerank.id,
            "generate": generate.id,
        }
        # Persist step ids on parent for debugging
        parent.input_payload = {
            **parent.input_payload,
            "step_job_ids": {k: str(v) for k, v in step_ids.items()},
        }
        await db.commit()
        from app.workers.rag_chain_tasks import dispatch_rag_chain
        dispatch_rag_chain(
            parent_job_id=str(parent.id),
            expand_job_id=str(expand.id),
            retrieve_job_id=str(retrieve.id),
            rerank_job_id=str(rerank.id),
            generate_job_id=str(generate.id),
        )
        return RAGQueryResponse(
            job_id=parent.id,
            message="RAG query submitted (Celery chain)",
            mode="chain",
            step_job_ids=step_ids,
        )


    async def run_rag_query_sync(
        self, payload: RAGQueryRequest
    ) -> RAGQuerySyncResponse:
        """
        Runs RAG inline and returns the answer in the same HTTP response.
        Uses asyncio.to_thread() so CPU-heavy model work does not block
        the FastAPI event loop while other requests are handled.
        """
        if payload.use_chain:
            raise HTTPException(
                status_code=400,
                detail="use_chain is only supported on POST /rag/query (async)",
            )
        input_payload = self._build_rag_input(payload)
        handler = get_handler(JobType.RAG_QUERY)
        result = await asyncio.to_thread(handler, input_payload)
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
        

    async def submit_modular_rag(
        self, db: AsyncSession, payload: RAGQueryRequest
    ) -> RAGQueryResponse:
        """Submit a modular RAG job with router, critic, eval, and MCP enabled."""
        input_payload = {
            **self._build_rag_input(payload),
            "mode": "modular",
            "use_router": True,
            "use_critic": getattr(payload, "use_critic", True),
            "use_eval": getattr(payload, "use_eval", True),
            "use_mcp": getattr(payload, "use_mcp", True),
        }
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
        return RAGQueryResponse(
            job_id=job.id,
            message="Modular RAG query submitted",
            mode="modular",
        )

document_service = DocumentService()