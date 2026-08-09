"""Cross-encoder reranker for shortlisted retrieval candidates."""
from __future__ import annotations

import heapq
import logging
from typing import Any

from app.workers.base import BaseJobHandler
from app.workers.decorators import timed_block

logger = logging.getLogger(__name__)


class RerankHandler(BaseJobHandler[dict[str, Any], dict[str, Any]]):
    """Score (query, passage) pairs with a cross-encoder and keep the top-N."""

    def __init__(
        self,
        model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
        keep_top_n: int = 3,
    ):
        self._model_name = model_name
        self._keep_top_n = keep_top_n
        self._model = None

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder
            logger.info("[rerank] loading model=%s", self._model_name)
            self._model = CrossEncoder(self._model_name, device="cpu")
        return self._model

    def validate_input(self, input_payload: dict[str, Any]) -> None:
        if not input_payload.get("question"):
            raise ValueError("rerank requires 'question'")
        candidates = input_payload.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ValueError("rerank requires non-empty 'candidates' list")
        for c in candidates:
            if "text" not in c or "chunk_id" not in c:
                raise ValueError("each candidate needs chunk_id and text")

    def process(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        question = input_payload["question"]
        candidates = input_payload["candidates"]
        keep_top_n = int(input_payload.get("keep_top_n", self._keep_top_n))

        pairs = [(question, c["text"]) for c in candidates]

        with timed_block("rerank.cross_encoder") as timer:
            model = self._get_model()
            scores = model.predict(pairs)

        scored: list[tuple[float, int, dict[str, Any]]] = []
        for i, (cand, score) in enumerate(zip(candidates, scores)):
            item = dict(cand)
            item["rerank_score"] = float(score)
            item["biencoder_similarity"] = float(cand.get("similarity", 0.0))
            scored.append((float(score), i, item))

        top = heapq.nlargest(keep_top_n, scored, key=lambda t: t[0])
        reranked = [t[2] for t in top]

        bi_top = max(candidates, key=lambda c: float(c.get("similarity", 0.0)))
        changed = str(bi_top.get("chunk_id")) != str(reranked[0].get("chunk_id"))

        logger.info(
            "[rerank] candidates=%d keep=%d changed_top1=%s elapsed=%.3fs "
            "top1_score=%.4f bi_top1_sim=%.4f",
            len(candidates),
            keep_top_n,
            changed,
            timer.elapsed,
            reranked[0]["rerank_score"],
            float(bi_top.get("similarity", 0.0)),
        )

        return {
            "question": question,
            "reranked": reranked,
            "observability": {
                "candidates_in": len(candidates),
                "kept": len(reranked),
                "changed_top1": changed,
                "model": self._model_name,
                "elapsed_seconds": timer.elapsed,
            },
        }

    def format_result(self, raw_result: dict[str, Any]) -> dict[str, Any]:
        return raw_result
