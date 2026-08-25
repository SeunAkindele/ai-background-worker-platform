"""Handler registry mapping JobType to BaseJobHandler instances."""
from typing import Any

from app.models.job import JobType
from app.workers.base import BaseJobHandler

_instances: dict[JobType, BaseJobHandler] = {}


def _get_or_create(job_type: JobType) -> BaseJobHandler:
    """Return a lazily created singleton handler for the job type."""
    if job_type not in _instances:
        _instances[job_type] = _create_handler(job_type)
    return _instances[job_type]


def _create_handler(job_type: JobType) -> BaseJobHandler:
    """Create the handler subclass for a job type."""
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

    elif job_type == JobType.QUERY_EXPAND:
        from app.workers.query_expand_worker import QueryExpandHandler
        return QueryExpandHandler()

    elif job_type == JobType.RERANK:
        from app.workers.rerank_worker import RerankHandler
        return RerankHandler()

    elif job_type == JobType.RAG_RETRIEVE:
        from app.workers.rag_step_handlers import RagRetrieveHandler
        return RagRetrieveHandler()

    elif job_type == JobType.RAG_GENERATE:
        from app.workers.rag_step_handlers import RagGenerateHandler
        return RagGenerateHandler()

    elif job_type == JobType.ROUTE_QUERY:
        from app.workers.router_worker import RouterHandler
        return RouterHandler()

    elif job_type == JobType.CRITIC:
        from app.workers.critic_worker import CriticHandler
        return CriticHandler()

    elif job_type == JobType.RAG_EVAL:
        from app.workers.rag_eval_worker import RagEvalHandler
        return RagEvalHandler()

    elif job_type == JobType.MCP_TOOL_CALL:
        from app.workers.mcp_worker import McpToolCallHandler
        return McpToolCallHandler()

    raise ValueError(f"No handler registered for job type: {job_type}")


def get_handler(job_type: JobType):
    """Return handler.run for the given job type (used by Celery tasks)."""
    handler = _get_or_create(job_type)
    return handler.run
