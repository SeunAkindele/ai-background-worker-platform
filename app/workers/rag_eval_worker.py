"""RAG evaluation worker: compute triad metrics and persist to rag_query_metrics."""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

from app.core.database import db_session
from app.workers.base import BaseJobHandler
from app.workers.critic_worker import CriticHandler

logger = logging.getLogger(__name__)


class RagEvalHandler(BaseJobHandler[dict[str, Any], dict[str, Any]]):
    """Computes context relevance, answer relevance, and groundedness per query."""

    def __init__(self) -> None:
        self._critic = CriticHandler()

    def validate_input(self, input_payload: dict[str, Any]) -> None:
        for key in ("question", "answer", "contexts"):
            if key not in input_payload:
                raise ValueError(f"rag_eval requires '{key}'")

    def process(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        question = input_payload["question"]
        answer = input_payload.get("answer") or ""
        contexts: list[str] = input_payload["contexts"]
        job_id = input_payload.get("job_id")
        route = input_payload.get("route", "vector")
        obs = input_payload.get("observability") or {}

        context_relevance = self._context_relevance(question, contexts)
        answer_relevance = self._critic._token_overlap(question, answer)
        groundedness = self._critic._token_overlap_groundedness(answer, contexts)

        triad = {
            "context_relevance": round(context_relevance, 4),
            "answer_relevance": round(answer_relevance, 4),
            "groundedness": round(groundedness, 4),
        }
        logger.info("[rag.eval] job=%s triad=%s route=%s", job_id, triad, route)

        self._persist_metric(
            job_id=job_id,
            question=question,
            answer=answer,
            route=route,
            triad=triad,
            observability=obs,
        )
        return {"triad": triad, "route": route, "job_id": job_id}

    def format_result(self, raw_result: dict[str, Any]) -> dict[str, Any]:
        return raw_result

    def _context_relevance(self, question: str, contexts: list[str]) -> float:
        """Mean token overlap between the question and each context chunk."""
        if not contexts:
            return 0.0
        scores = [self._critic._token_overlap(question, c) for c in contexts]
        return sum(scores) / len(scores)

    def _persist_metric(
        self,
        *,
        job_id: str | None,
        question: str,
        answer: str,
        route: str,
        triad: dict[str, float],
        observability: dict[str, Any],
    ) -> None:
        import json

        sql = """
            INSERT INTO rag_query_metrics (
                job_id, question, route, answer,
                context_relevance, answer_relevance, groundedness,
                critic_passed, critic_attempts, retrieve_hit,
                rerank_changed_top1, total_latency_ms, observability
            ) VALUES (
                :job_id, :question, :route, :answer,
                :cr, :ar, :gr,
                :critic_passed, :critic_attempts, :retrieve_hit,
                :rerank_changed_top1, :total_latency_ms,
                CAST(:observability AS jsonb)
            )
        """
        stages = observability.get("stages") or []
        total_latency_ms = round(sum(s.get("elapsed_ms", 0) for s in stages), 2)

        params = {
            "job_id": job_id,
            "question": question,
            "route": route,
            "answer": answer,
            "cr": triad["context_relevance"],
            "ar": triad["answer_relevance"],
            "gr": triad["groundedness"],
            "critic_passed": observability.get("critic_passed"),
            "critic_attempts": observability.get("critic_attempts") or 1,
            "retrieve_hit": (observability.get("after_dedupe_k") or 0) > 0,
            "rerank_changed_top1": observability.get("rerank_changed_top1"),
            "total_latency_ms": total_latency_ms,
            "observability": json.dumps(observability),
        }
        with db_session() as db:
            db.execute(text(sql), params)
        logger.info(
            "[rag.eval] persisted job=%s groundedness=%.2f latency_ms=%.1f",
            job_id, triad["groundedness"], total_latency_ms,
        )
