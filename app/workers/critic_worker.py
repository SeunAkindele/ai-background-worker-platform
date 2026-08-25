"""Critic worker: heuristic quality gate for generated RAG answers."""
from __future__ import annotations

import logging
import re
from typing import Any

from app.workers.base import BaseJobHandler

logger = logging.getLogger(__name__)


class CriticHandler(BaseJobHandler[dict[str, Any], dict[str, Any]]):
    """Evaluates answer quality and suggests retrieval adjustments on failure."""

    _BAD_PHRASES = re.compile(
        r"\b(i don't know|i do not know|not in the context|"
        r"no relevant documents|as an ai|cannot answer)\b",
        re.I,
    )

    def validate_input(self, input_payload: dict[str, Any]) -> None:
        if "answer" not in input_payload:
            raise ValueError("Critic requires 'answer'")
        if "question" not in input_payload:
            raise ValueError("Critic requires 'question'")
        if "contexts" not in input_payload or not isinstance(
            input_payload["contexts"], list
        ):
            raise ValueError("Critic requires 'contexts' list")

    def process(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        question = input_payload["question"]
        answer = (input_payload.get("answer") or "").strip()
        contexts: list[str] = [c for c in input_payload["contexts"] if c]
        min_groundedness = float(input_payload.get("min_groundedness", 0.25))
        min_answer_chars = int(input_payload.get("min_answer_chars", 40))

        reasons: list[str] = []
        score = 1.0

        if len(answer) < min_answer_chars or self._BAD_PHRASES.search(answer):
            score -= 0.5
            reasons.append("weak_or_refusal_answer")

        if not contexts:
            score -= 0.5
            reasons.append("empty_context")

        groundedness = self._token_overlap_groundedness(answer, contexts)
        if groundedness < min_groundedness:
            score -= 0.3
            reasons.append(f"low_groundedness:{groundedness:.2f}")

        answer_rel = self._token_overlap(question, answer)
        if answer_rel < 0.1:
            score -= 0.2
            reasons.append(f"low_answer_relevance:{answer_rel:.2f}")

        passed = score >= 0.5 and "empty_context" not in reasons

        logger.info(
            "[critic] passed=%s score=%.2f groundedness=%.2f reasons=%s",
            passed, score, groundedness, reasons,
        )

        return {
            "passed": passed,
            "score": round(score, 4),
            "groundedness": round(groundedness, 4),
            "answer_relevance": round(answer_rel, 4),
            "reasons": reasons,
            "suggested_strategy": self._suggest_strategy(reasons),
        }

    def format_result(self, raw_result: dict[str, Any]) -> dict[str, Any]:
        return raw_result

    def _suggest_strategy(self, reasons: list[str]) -> dict[str, Any]:
        """Map failure reasons to retrieval retry parameters."""
        strategy = {
            "retrieve_k_boost": 0,
            "drop_metadata_filter": False,
            "disable_multi_query": False,
            "disable_rerank": False,
        }
        joined = " ".join(reasons)
        if "empty_context" in joined or "low_groundedness" in joined:
            strategy["retrieve_k_boost"] = 50
            strategy["drop_metadata_filter"] = True
        if "low_answer_relevance" in joined:
            strategy["disable_multi_query"] = True
        return strategy

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 2}

    def _token_overlap(self, a: str, b: str) -> float:
        ta, tb = self._tokenize(a), self._tokenize(b)
        if not ta or not tb:
            return 0.0
        return len(ta & tb) / len(ta)

    def _token_overlap_groundedness(
        self, answer: str, contexts: list[str]
    ) -> float:
        """Share of answer tokens present in retrieved context."""
        ans = self._tokenize(answer)
        if not ans:
            return 0.0
        ctx = set()
        for c in contexts:
            ctx |= self._tokenize(c)
        if not ctx:
            return 0.0
        return len(ans & ctx) / len(ans)
