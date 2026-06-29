from typing import Any, Callable

from app.models.job import JobType

# Type alias: input dict → result dict
JobHandler = Callable[[dict[str, Any]], dict[str, Any]]


def _summarize(input_payload: dict[str, Any]) -> dict[str, Any]:
    from app.workers.summarization_worker import summarize
    text = input_payload.get("text", "")
    if not text or not isinstance(text, str) or not text.strip():
        raise ValueError("Summarization requires a non-empty 'text' field")
    return summarize(text)


def _ocr(input_payload: dict[str, Any]) -> dict[str, Any]:
    # TODO: return fake OCR result
    return {"text": "ocr completed"}


def _embeddings(input_payload: dict[str, Any]) -> dict[str, Any]:
    # TODO: return fake embeddings result
    return {"embedding": [0.1, 0.2, 0.3], "dimensions": 3}


def _transcription(input_payload: dict[str, Any]) -> dict[str, Any]:
    # TODO: return fake transcription result
    return {"transcript": "transcription completed"}


def _recommendations(input_payload: dict[str, Any]) -> dict[str, Any]:
    # TODO: return fake recommendations result
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