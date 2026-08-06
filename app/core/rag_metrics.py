"""
Stage 14 observability helpers.

Why a dedicated module?
-----------------------
Your jobs already log via log_service + timed_block. Stage 14 needs
*per-stage* timings and quality signals (rerank lift, filter hit rate)
so you can debug "answers are still messy" without guessing which step failed.

DSA: sliding-window averages for slow queries belong in admin later (Stage 15e).
Here we just emit structured dicts into the job result + logger.
"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from typing import Any, Generator

logger = logging.getLogger("rag.metrics")


@dataclass
class StageTimer:
    """Mutable timer — same idea as your TimerResult in decorators.py."""
    name: str
    elapsed_ms: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class RAGTrace:
    """
    Accumulates one query's observability payload.

    Stored in result_payload["observability"] so GET /jobs/{id}
    shows the full trace without a separate metrics DB.
    """
    question: str
    stages: list[dict[str, Any]] = field(default_factory=list)
    # Quality signals — filled after rerank
    retrieve_k: int = 0
    after_filter_k: int = 0
    after_dedupe_k: int = 0
    after_rerank_k: int = 0
    # Rerank lift: how often the #1 after rerank was NOT #1 after bi-encoder
    rerank_changed_top1: bool | None = None
    # Cosine of top-1 before vs cross-encoder score of top-1 after
    biencoder_top1_similarity: float | None = None
    reranker_top1_score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@contextmanager
def trace_stage(
    trace: RAGTrace, name: str, **meta: Any
) -> Generator[StageTimer, None, None]:
    """
    Time a pipeline stage and append to the trace.

    IMPORTANT LINE: we log at INFO with a stable prefix `[rag.stage]`
    so you can grep worker logs / ship to Loki later without parsing free text.
    """
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
            "meta": {**timer.meta, **meta},
        }
        # Allow stage code to mutate timer.meta during the block
        payload["meta"] = timer.meta
        trace.stages.append(payload)
        logger.info(
            "[rag.stage] done name=%s elapsed_ms=%.2f meta=%s",
            name,
            timer.elapsed_ms,
            timer.meta,
        )