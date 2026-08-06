from app.models.job import JobType
from app.workers.base import BaseJobHandler

_instances: dict[JobType, BaseJobHandler] = {}


def _get_or_create(job_type: JobType) -> BaseJobHandler:
    """Return a cached handler instance for the job type, creating it if needed."""
    if job_type not in _instances:
        _instances[job_type] = _create_handler(job_type)
    return _instances[job_type]


def _create_handler(job_type: JobType) -> BaseJobHandler:
    if job_type == JobType.SUMMARIZATION:
        from app.workers.summarization_worker import SummarizationHandler

        return SummarizationHandler()

    if job_type == JobType.EMBEDDINGS:
        from app.workers.embedding_worker import EmbeddingHandler

        return EmbeddingHandler()

    if job_type == JobType.OCR:
        from app.workers.ocr_worker import OCRHandler

        return OCRHandler()

    if job_type == JobType.TRANSCRIPTION:
        from app.workers.transcription_worker import TranscriptionHandler

        return TranscriptionHandler()

    if job_type == JobType.RECOMMENDATIONS:
        from app.workers.recommendation_worker import RecommendationHandler

        return RecommendationHandler()

    raise ValueError(f"No handler registered for job type: {job_type}")


def get_handler(job_type: JobType):
    """Return the handler runnable for the given job type."""
    handler = _get_or_create(job_type)
    return handler.run
