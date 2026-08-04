from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.dependencies import enforce_pending_limit, enforce_rate_limit
from app.schemas.document_schema import (
    ChunkListResponse,
    DocumentIngestRequest,
    DocumentIngestResponse,
    DocumentResponse,
    RAGQueryRequest,
    RAGQueryResponse,
    RAGQuerySyncResponse,
)
from app.services.document_service import document_service

documents_router = APIRouter(prefix="/documents", tags=["documents"])
rag_router = APIRouter(prefix="/rag", tags=["rag"])


@documents_router.post(
    "/ingest",
    response_model=DocumentIngestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def ingest_document(
    payload: DocumentIngestRequest,
    db: AsyncSession = Depends(get_async_db),
    _client: str = Depends(enforce_rate_limit),
    _pending: None = Depends(enforce_pending_limit),
):
    return await document_service.ingest_document(db, payload)


@documents_router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    _client: str = Depends(enforce_rate_limit),
):
    document = await document_service.get_document(db, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@documents_router.get("/{document_id}/chunks", response_model=ChunkListResponse)
async def get_document_chunks(
    document_id: UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_async_db),
    _client: str = Depends(enforce_rate_limit),
):
    return await document_service.get_document_chunks(
        db, document_id, skip=skip, limit=limit
    )


# ─── ASYNC: returns job_id, poll GET /jobs/{id} ───────────────────────

@rag_router.post(
    "/query",
    response_model=RAGQueryResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def rag_query_async(
    payload: RAGQueryRequest,
    db: AsyncSession = Depends(get_async_db),
    _client: str = Depends(enforce_rate_limit),
    _pending: None = Depends(enforce_pending_limit),
):
    return await document_service.submit_rag_query(db, payload)


# ─── SYNC: returns answer immediately ────────────────────────────────

@rag_router.post(
    "/query/sync",
    response_model=RAGQuerySyncResponse,
    status_code=status.HTTP_200_OK,
)
async def rag_query_sync(
    payload: RAGQueryRequest,
    _client: str = Depends(enforce_rate_limit),
):
    """
    ChatGPT-style: ask a question, get the answer in the same response.

    No job_id. No polling. Blocks until RAG finishes (typically 2-10s).
    """
    return await document_service.run_rag_query_sync(payload)