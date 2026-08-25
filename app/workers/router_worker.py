"""Query router: classify intent and select cache, vector, SQL, or web backend."""
from __future__ import annotations

import hashlib
import logging
import re
from typing import Any, Literal

from sqlalchemy import text

from app.core.database import db_session
from app.core.rag_metrics import RAGTrace, trace_stage
from app.workers.base import BaseJobHandler

logger = logging.getLogger(__name__)

RouteName = Literal["cache", "vector", "sql", "web"]


class RouterHandler(BaseJobHandler[dict[str, Any], dict[str, Any]]):
    """Rule-based query classifier with scored route selection."""

    _SQL_HINTS = re.compile(
        r"\b(count|how many|average|sum|total|list all|group by|"
        r"jobs? (pending|failed|completed)|worker(s)? online)\b",
        re.I,
    )
    _WEB_HINTS = re.compile(
        r"\b(latest|today|current|news|weather|stock price|"
        r"who is the (ceo|president)|as of 20\d{2})\b",
        re.I,
    )

    def validate_input(self, input_payload: dict[str, Any]) -> None:
        q = input_payload.get("question")
        if not q or not isinstance(q, str) or not q.strip():
            raise ValueError("Router requires non-empty 'question'")

    def process(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        question = input_payload["question"].strip()
        trace = RAGTrace(question=question)
        force_route = input_payload.get("force_route")

        with trace_stage(trace, "route_classify") as st:
            if force_route:
                decision = {
                    "route": force_route,
                    "confidence": 1.0,
                    "reasons": [f"forced:{force_route}"],
                    "scores": {force_route: 1.0},
                }
            else:
                cached = self._lookup_cache(question)
                if cached is not None:
                    decision = {
                        "route": "cache",
                        "confidence": 1.0,
                        "reasons": ["cache_hit"],
                        "scores": {"cache": 1.0},
                        "cached_answer": cached,
                    }
                else:
                    decision = self._score_routes(question)

            st.meta.update({
                "route": decision["route"],
                "confidence": decision["confidence"],
                "reasons": decision["reasons"],
                "scores": decision["scores"],
            })
            trace.route = decision["route"]
            trace.route_confidence = decision["confidence"]

        logger.info(
            "[router] route=%s confidence=%.2f reasons=%s q=%r",
            decision["route"],
            decision["confidence"],
            decision["reasons"],
            question[:80],
        )

        # Returns a routing decision; execution stays in RAGQueryHandler.
        return {
            "question": question,
            "route": decision["route"],
            "confidence": decision["confidence"],
            "reasons": decision["reasons"],
            "scores": decision["scores"],
            "cached_result": decision.get("cached_answer"),
            "observability": trace.to_dict(),
        }

    def format_result(self, raw_result: dict[str, Any]) -> dict[str, Any]:
        return raw_result

    def _score_routes(self, question: str) -> dict[str, Any]:
        """Score candidate routes and return the highest-scoring selection."""
        scores: dict[str, float] = {
            "cache": 0.0,
            "vector": 0.35,
            "sql": 0.0,
            "web": 0.0,
        }
        reasons: list[str] = []

        if self._SQL_HINTS.search(question):
            scores["sql"] += 0.55
            reasons.append("sql_keywords")

        if self._WEB_HINTS.search(question):
            scores["web"] += 0.55
            reasons.append("web_keywords")

        if re.search(r"\b(document|policy|handbook|manual|chunk|ingest)\b", question, re.I):
            scores["vector"] += 0.25
            reasons.append("doc_keywords")

        if len(question.split()) <= 4 and question[0].isupper():
            scores["web"] += 0.15
            reasons.append("short_entity_question")

        route = max(scores, key=scores.get)  # type: ignore[arg-type]
        confidence = scores[route] / (sum(scores.values()) or 1.0)

        if not reasons:
            reasons.append("default_vector_prior")

        return {
            "route": route,
            "confidence": round(confidence, 4),
            "reasons": reasons,
            "scores": {k: round(v, 4) for k, v in scores.items()},
        }

    @staticmethod
    def normalize_question(question: str) -> str:
        """Normalize question text for stable cache key generation."""
        q = question.strip().lower()
        q = re.sub(r"\s+", " ", q)
        q = re.sub(r"[^\w\s?]", "", q)
        return q

    @classmethod
    def question_hash(cls, question: str) -> str:
        return hashlib.sha256(cls.normalize_question(question).encode("utf-8")).hexdigest()

    def _lookup_cache(self, question: str) -> dict[str, Any] | None:
        qh = self.question_hash(question)
        sql = """
            UPDATE rag_answer_cache
            SET hit_count = hit_count + 1, updated_at = now()
            WHERE question_hash = :qh
            RETURNING question, answer, sources, route, hit_count
        """
        with db_session() as db:
            row = db.execute(text(sql), {"qh": qh}).fetchone()
        if row is None:
            return None
        logger.info("[router.cache] HIT hash=%s hits=%s", qh[:12], row.hit_count)
        return {
            "question": row.question,
            "answer": row.answer,
            "sources": row.sources or [],
            "route": "cache",
            "hit_count": row.hit_count,
        }


def write_answer_cache(
    question: str,
    answer: str,
    sources: list[dict[str, Any]],
) -> None:
    """Upsert a successful answer into rag_answer_cache."""
    qh = RouterHandler.question_hash(question)
    sql = """
        INSERT INTO rag_answer_cache (question_hash, question, answer, sources, route)
        VALUES (:qh, :q, :a, CAST(:sources AS jsonb), 'vector')
        ON CONFLICT (question_hash) DO UPDATE
          SET answer = EXCLUDED.answer,
              sources = EXCLUDED.sources,
              updated_at = now()
    """
    import json
    with db_session() as db:
        db.execute(
            text(sql),
            {
                "qh": qh,
                "q": question,
                "a": answer,
                "sources": json.dumps(sources),
            },
        )
    logger.info("[router.cache] UPSERT hash=%s", qh[:12])
