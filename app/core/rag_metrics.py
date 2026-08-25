"""Structured per-step timings and quality signals for RAG queries."""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from typing import Any, Generator

logger = logging.getLogger("rag.metrics")


@dataclass
class StageTimer:
    """Elapsed time and optional metadata for one pipeline stage."""
    name: str
    elapsed_ms: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class RAGTrace:
    """Accumulates one query's observability payload for result_payload."""
    question: str
    stages: list[dict[str, Any]] = field(default_factory=list)
    retrieve_k: int = 0
    after_filter_k: int = 0
    after_dedupe_k: int = 0
    after_rerank_k: int = 0
    rerank_changed_top1: bool | None = None
    biencoder_top1_similarity: float | None = None
    reranker_top1_score: float | None = None

    route: str | None = None
    route_confidence: float | None = None
    critic_passed: bool | None = None
    critic_attempts: int = 1
    critic_reasons: list[str] = field(default_factory=list)
    triad: dict[str, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@contextmanager
def trace_stage(
    trace: RAGTrace, name: str, **meta: Any
) -> Generator[StageTimer, None, None]:
    """Time a pipeline stage and append it to the trace."""
    timer = StageTimer(name=name, meta=meta)
    start = time.perf_counter()
    logger.info("[rag.stage] start name=%s meta=%s", name, meta)
    try:
        yield timer
    finally:
        timer.elapsed_ms = (time.perf_counter() - start) * 1000.0
        payload = {
            "name": timer.name,
            "elapsed_ms": round(timer.elapsed_ms, 2),
            "meta": timer.meta,
        }
        trace.stages.append(payload)
        logger.info(
            "[rag.stage] done name=%s elapsed_ms=%.2f meta=%s",
            name,
            timer.elapsed_ms,
            timer.meta,
        )
