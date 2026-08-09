"""Celery chain for advanced RAG: expand → retrieve → rerank → generate."""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from celery import chain

from app.core.database import db_session
from app.models.job import JobStatus
from app.models.job_log import LogLevel
from app.services.job_service import job_service
from app.services.log_service import log_service
from app.workers.celery_app import celery_app
from app.workers.handlers import get_handler
from app.workers.query_expand_worker import QueryExpandHandler
from app.workers.rag_query_worker import RAGQueryHandler
from app.workers.rerank_worker import RerankHandler

logger = logging.getLogger(__name__)

_rag = RAGQueryHandler()
_expander = QueryExpandHandler()
_reranker = RerankHandler()


def _json_safe_chunks(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stringify UUID fields so Celery's JSON serializer can pass chunks between tasks."""
    safe = []
    for c in chunks:
        item = dict(c)
        for key in ("chunk_id", "document_id", "parent_chunk_id", "child_chunk_id"):
            if key in item and item[key] is not None:
                item[key] = str(item[key])
        safe.append(item)
    return safe


def _mark(
    job_id: str,
    *,
    status: JobStatus,
    result: dict | None = None,
    error: str | None = None,
    log_msg: str | None = None,
) -> None:
    jid = UUID(job_id)
    with db_session() as db:
        job_service.update_job_status(
            db, jid, status, result_payload=result, error_message=error
        )
        if log_msg:
            log_service.add_log(
                db,
                jid,
                log_msg,
                LogLevel.ERROR if status == JobStatus.FAILED else LogLevel.INFO,
            )


def dispatch_rag_chain(
    *,
    parent_job_id: str,
    expand_job_id: str,
    retrieve_job_id: str,
    rerank_job_id: str,
    generate_job_id: str,
) -> None:
    """Dispatch the RAG Celery chain on the rag_query queue."""
    with db_session() as db:
        job_service.update_job_status(
            db, UUID(parent_job_id), JobStatus.PROCESSING
        )
        log_service.add_log(
            db,
            UUID(parent_job_id),
            "RAG chain started",
            LogLevel.INFO,
        )

    workflow = chain(
        rag_chain_expand.s(expand_job_id).set(queue="rag_query"),
        rag_chain_retrieve.s(retrieve_job_id=retrieve_job_id).set(queue="rag_query"),
        rag_chain_rerank.s(rerank_job_id=rerank_job_id).set(queue="rag_query"),
        rag_chain_generate.s(
            generate_job_id=generate_job_id,
            parent_job_id=parent_job_id,
        ).set(queue="rag_query"),
    )
    workflow.apply_async()
    logger.info(
        "[rag.chain] dispatched parent=%s expand=%s retrieve=%s rerank=%s generate=%s",
        parent_job_id,
        expand_job_id,
        retrieve_job_id,
        rerank_job_id,
        generate_job_id,
    )


@celery_app.task(name="rag.chain.expand", bind=True, max_retries=2)
def rag_chain_expand(self, expand_job_id: str) -> dict[str, Any]:
    try:
        with db_session() as db:
            job = job_service.get_job(db, UUID(expand_job_id))
            if job is None:
                raise ValueError(f"expand job {expand_job_id} not found")
            payload = dict(job.input_payload)
            job_service.update_job_status(
                db, UUID(expand_job_id), JobStatus.PROCESSING
            )

        result = _expander.run(payload)
        _mark(
            expand_job_id,
            status=JobStatus.COMPLETED,
            result=result,
            log_msg="query_expand completed",
        )
        return {
            "question": result["question"],
            "queries": result["queries"],
        }
    except Exception as exc:
        _mark(expand_job_id, status=JobStatus.FAILED, error=str(exc), log_msg=str(exc))
        raise


@celery_app.task(name="rag.chain.retrieve", bind=True, max_retries=2)
def rag_chain_retrieve(
    self, prev: dict[str, Any], retrieve_job_id: str
) -> dict[str, Any]:
    try:
        with db_session() as db:
            job = job_service.get_job(db, UUID(retrieve_job_id))
            if job is None:
                raise ValueError(f"retrieve job {retrieve_job_id} not found")
            cfg = dict(job.input_payload)
            job_service.update_job_status(
                db, UUID(retrieve_job_id), JobStatus.PROCESSING
            )

        queries = prev["queries"]
        retrieve_k = int(cfg.get("retrieve_k", 50))
        document_ids = cfg.get("document_ids")
        metadata_filter = cfg.get("metadata_filter")

        per_query_hits: list[list[dict[str, Any]]] = []
        for q in queries:
            emb = _rag._embed_question(q)
            hits = _rag._retrieve_top_k(
                emb,
                top_k=retrieve_k,
                document_ids=document_ids,
                metadata_filter=metadata_filter,
            )
            per_query_hits.append(hits)

        merged = _rag.merge_and_dedupe(per_query_hits)
        pool = _json_safe_chunks(merged[:retrieve_k])

        result = {
            "question": prev["question"],
            "queries": queries,
            "candidates": pool,
            "retrieve_k": retrieve_k,
        }
        _mark(
            retrieve_job_id,
            status=JobStatus.COMPLETED,
            result={
                "queries": queries,
                "candidates_count": len(pool),
                "retrieve_k": retrieve_k,
            },
            log_msg=f"retrieve+merge completed pool={len(pool)}",
        )
        return result
    except Exception as exc:
        _mark(retrieve_job_id, status=JobStatus.FAILED, error=str(exc), log_msg=str(exc))
        raise


@celery_app.task(name="rag.chain.rerank", bind=True, max_retries=2)
def rag_chain_rerank(
    self, prev: dict[str, Any], rerank_job_id: str
) -> dict[str, Any]:
    try:
        with db_session() as db:
            job = job_service.get_job(db, UUID(rerank_job_id))
            if job is None:
                raise ValueError(f"rerank job {rerank_job_id} not found")
            cfg = dict(job.input_payload)
            job_service.update_job_status(
                db, UUID(rerank_job_id), JobStatus.PROCESSING
            )

        use_rerank = cfg.get("use_rerank", True)
        keep_top_n = int(cfg.get("keep_top_n", 3))
        candidates = prev.get("candidates") or []

        if not candidates:
            out = {
                "question": prev["question"],
                "queries": prev.get("queries", []),
                "selected": [],
                "rerank_observability": {"skipped": True, "reason": "empty_pool"},
            }
            _mark(rerank_job_id, status=JobStatus.COMPLETED, result=out)
            return out

        if use_rerank:
            rr = _reranker.run({
                "question": prev["question"],
                "candidates": candidates,
                "keep_top_n": keep_top_n,
            })
            selected = _json_safe_chunks(rr["reranked"])
            obs = rr["observability"]
        else:
            selected = candidates[:keep_top_n]
            obs = {"skipped": True, "kept": len(selected)}

        out = {
            "question": prev["question"],
            "queries": prev.get("queries", []),
            "selected": selected,
            "rerank_observability": obs,
            "use_small_to_big": cfg.get("use_small_to_big", True),
            "keep_top_n": keep_top_n,
        }
        _mark(
            rerank_job_id,
            status=JobStatus.COMPLETED,
            result={"selected_count": len(selected), "observability": obs},
            log_msg=f"rerank completed kept={len(selected)}",
        )
        return out
    except Exception as exc:
        _mark(rerank_job_id, status=JobStatus.FAILED, error=str(exc), log_msg=str(exc))
        raise


@celery_app.task(name="rag.chain.generate", bind=True, max_retries=2)
def rag_chain_generate(
    self,
    prev: dict[str, Any],
    generate_job_id: str,
    parent_job_id: str,
) -> dict[str, Any]:
    """Small-to-big (optional), prompt, generate; completes the parent job."""
    try:
        with db_session() as db:
            job = job_service.get_job(db, UUID(generate_job_id))
            if job is None:
                raise ValueError(f"generate job {generate_job_id} not found")
            cfg = dict(job.input_payload)
            job_service.update_job_status(
                db, UUID(generate_job_id), JobStatus.PROCESSING
            )

        question = prev["question"]
        selected = prev.get("selected") or []
        use_s2b = prev.get("use_small_to_big", cfg.get("use_small_to_big", True))

        if not selected:
            final = {
                "question": question,
                "answer": "No relevant documents found to answer this question.",
                "sources": [],
                "chunks_retrieved": 0,
                "queries_used": prev.get("queries", []),
                "mode": "chain",
            }
        else:
            context_chunks = (
                _rag._expand_to_parents(selected) if use_s2b else selected
            )
            context_chunks = _json_safe_chunks(context_chunks)
            prompt = _rag._build_prompt(question, context_chunks)
            answer = _rag._generate_answer(prompt)
            sources = [
                {
                    "chunk_id": str(c["chunk_id"]),
                    "document_id": str(c["document_id"]),
                    "document_title": c.get("document_title"),
                    "chunk_index": c.get("chunk_index"),
                    "similarity": round(float(c.get("similarity", 0.0)), 4),
                    "rerank_score": (
                        round(float(c["rerank_score"]), 4)
                        if "rerank_score" in c
                        else None
                    ),
                    "text_preview": (
                        c["text"][:200] + "..."
                        if len(c.get("text", "")) > 200
                        else c.get("text", "")
                    ),
                    "expanded_from_child": c.get("expanded_from_child", False),
                }
                for c in context_chunks
            ]
            final = {
                "question": question,
                "answer": answer,
                "sources": sources,
                "chunks_retrieved": len(context_chunks),
                "queries_used": prev.get("queries", []),
                "rerank_observability": prev.get("rerank_observability"),
                "mode": "chain",
                "model": _rag._embedding_model_name,
            }

        _mark(
            generate_job_id,
            status=JobStatus.COMPLETED,
            result={"chunks_retrieved": final.get("chunks_retrieved", 0)},
            log_msg="generate completed",
        )
        _mark(
            parent_job_id,
            status=JobStatus.COMPLETED,
            result=final,
            log_msg="RAG chain completed",
        )
        return final
    except Exception as exc:
        _mark(generate_job_id, status=JobStatus.FAILED, error=str(exc), log_msg=str(exc))
        _mark(parent_job_id, status=JobStatus.FAILED, error=str(exc), log_msg=str(exc))
        raise