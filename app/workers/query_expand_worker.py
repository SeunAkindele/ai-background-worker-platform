"""Multi-query expansion: one question → several rewordings for retrieval."""
from __future__ import annotations

import logging
import re
from typing import Any

from app.workers.base import BaseJobHandler

logger = logging.getLogger(__name__)


class QueryExpandHandler(BaseJobHandler[dict[str, Any], dict[str, Any]]):
    """Expand a question into deterministic query variants for multi-query retrieval."""

    def validate_input(self, input_payload: dict[str, Any]) -> None:
        q = input_payload.get("question")
        if not q or not isinstance(q, str) or not q.strip():
            raise ValueError("query_expand requires non-empty 'question'")

    def process(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        question = input_payload["question"].strip()
        n = int(input_payload.get("num_queries", 3))
        n = max(1, min(n, 5))

        variants = self._expand(question, n=n)
        logger.info(
            "[query_expand] original=%r variants=%s",
            question,
            variants,
        )
        return {
            "question": question,
            "queries": variants,
            "observability": {"num_queries": len(variants)},
        }

    def format_result(self, raw_result: dict[str, Any]) -> dict[str, Any]:
        return raw_result

    def _expand(self, question: str, n: int) -> list[str]:
        """Return up to n distinct queries; original is always first."""
        q = question.strip()
        base = re.sub(r"\s+", " ", q)
        base_no_q = base[:-1].strip() if base.endswith("?") else base

        candidates = [
            base,
            f"What is {base_no_q}?",
            f"Explain {base_no_q}",
            f"Details about {base_no_q}",
            f"Summary of {base_no_q}",
        ]

        unique: list[str] = list(dict.fromkeys(candidates))
        return unique[:n]
