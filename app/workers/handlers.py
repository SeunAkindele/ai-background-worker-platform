"""
Handler registry — maps JobType to its BaseJobHandler instance.

Python Internals Focus:
-----------------------
- Lazy instantiation: handlers are created once on first access
- Dict as a registry/dispatch table: O(1) lookup
- The _instances dict acts as a simple service locator pattern
"""
from typing import Any

from app.models.job import JobType
from app.workers.base import BaseJobHandler

_instances: dict[JobType, BaseJobHandler] = {}


def _get_or_create(job_type: JobType) -> BaseJobHandler:
    """
    Lazy singleton per job type.

    Why lazy?
    - Embedding model is ~80MB — don't load until first embedding job
    - Summarization model is ~1.6GB — don't load until first summary job
    - Keeps startup fast, memory low until actually needed
    """
    if job_type not in _instances:
        _instances[job_type] = _create_handler(job_type)
    return _instances[job_type]


def _create_handler(job_type: JobType) -> BaseJobHandler:
    """Factory: create the right handler subclass for a job type."""
    if job_type == JobType.SUMMARIZATION:
        from app.workers.summarization_worker import SummarizationHandler
        return SummarizationHandler()

    elif job_type == JobType.EMBEDDINGS:
        from app.workers.embedding_worker import EmbeddingHandler
        return EmbeddingHandler()

    elif job_type == JobType.OCR:
        from app.workers.ocr_worker import OCRHandler
        return OCRHandler()

    elif job_type == JobType.TRANSCRIPTION:
        from app.workers.transcription_worker import TranscriptionHandler
        return TranscriptionHandler()

    elif job_type == JobType.RECOMMENDATIONS:
        from app.workers.recommendation_worker import RecommendationHandler
        return RecommendationHandler()

    elif job_type == JobType.INGESTION:
        from app.workers.ingestion_worker import IngestionHandler
        return IngestionHandler()

    elif job_type == JobType.RAG_QUERY:
        from app.workers.rag_query_worker import RAGQueryHandler
        return RAGQueryHandler()

    raise ValueError(f"No handler registered for job type: {job_type}")


def get_handler(job_type: JobType):
    """
    Public API: returns a callable that takes input_payload → result dict.

    This is what tasks.py calls. It returns handler.run (the template method),
    keeping backward compatibility with the existing Celery task.
    """
    handler = _get_or_create(job_type)
    return handler.run