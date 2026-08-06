"""Handler registry — maps JobType to its BaseJobHandler instance."""
from app.models.job import JobType
from app.workers.base import BaseJobHandler

_instances: dict[JobType, BaseJobHandler] = {}


def _get_or_create(job_type: JobType) -> BaseJobHandler:
    """Return a cached handler instance, creating it on first use."""
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

    raise ValueError(f"No handler registered for job type: {job_type}")


def get_handler(job_type: JobType):
    """Return handler.run for the given job type (used by Celery tasks)."""
    handler = _get_or_create(job_type)
    return handler.run
