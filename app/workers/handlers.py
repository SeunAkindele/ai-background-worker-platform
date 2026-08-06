from typing import Any, Callable

from app.models.job import JobType

JobHandler = Callable[[dict[str, Any]], dict[str, Any]]


def _summarize(input_payload: dict[str, Any]) -> dict[str, Any]:
    return {"summary": "summary generated"}


def _ocr(input_payload: dict[str, Any]) -> dict[str, Any]:
    return {"text": "ocr completed"}


def _embeddings(input_payload: dict[str, Any]) -> dict[str, Any]:
    return {"embedding": [0.1, 0.2, 0.3], "dimensions": 3}


def _transcription(input_payload: dict[str, Any]) -> dict[str, Any]:
    return {"transcript": "transcription completed"}


def _recommendations(input_payload: dict[str, Any]) -> dict[str, Any]:
    return {"recommendations": ["item-a", "item-b"]}


HANDLERS: dict[JobType, JobHandler] = {
    JobType.SUMMARIZATION: _summarize,
    JobType.OCR: _ocr,
    JobType.EMBEDDINGS: _embeddings,
    JobType.TRANSCRIPTION: _transcription,
    JobType.RECOMMENDATIONS: _recommendations,
}


def get_handler(job_type: JobType) -> JobHandler:
    return HANDLERS[job_type]
