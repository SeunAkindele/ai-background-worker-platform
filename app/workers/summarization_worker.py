"""Summarization handler — chunked text summarization with recursive merge."""
from typing import Any, Generator

from app.workers.base import BaseJobHandler

_pipeline = None


class SummarizationHandler(BaseJobHandler[dict[str, Any], dict[str, Any]]):

    def __init__(
        self,
        chunk_size: int = 500,
        overlap: int = 50,
        max_length: int = 150,
        min_length: int = 40,
        max_depth: int = 3,
    ):
        self._chunk_size = chunk_size
        self._overlap = overlap
        self._max_length = max_length
        self._min_length = min_length
        self._max_depth = max_depth

    def validate_input(self, input_payload: dict[str, Any]) -> None:
        text = input_payload.get("text", "")
        if not text or not isinstance(text, str) or not text.strip():
            raise ValueError("Summarization requires a non-empty 'text' field")

    def process(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        text = input_payload["text"]
        return self._summarize(text, depth=0)

    def format_result(self, raw_result: dict[str, Any]) -> dict[str, Any]:
        return raw_result

    def _summarize(self, text: str, depth: int) -> dict[str, Any]:
        original_word_count = len(text.split())
        words = text.split()

        if len(words) <= self._chunk_size:
            summary_text = self._summarize_chunk(text)
            return {
                "summary": summary_text,
                "chunks_processed": 1,
                "original_word_count": original_word_count,
                "summary_word_count": len(summary_text.split()),
            }

        chunk_summaries = []
        chunks_processed = 0
        for chunk in self._chunk_text(text):
            chunk_summaries.append(self._summarize_chunk(chunk))
            chunks_processed += 1

        merged = " ".join(chunk_summaries)

        if len(merged.split()) > self._chunk_size and depth < self._max_depth:
            recursive_result = self._summarize(merged, depth + 1)
            return {
                "summary": recursive_result["summary"],
                "chunks_processed": chunks_processed + recursive_result["chunks_processed"],
                "original_word_count": original_word_count,
                "summary_word_count": recursive_result["summary_word_count"],
            }

        return {
            "summary": merged,
            "chunks_processed": chunks_processed,
            "original_word_count": original_word_count,
            "summary_word_count": len(merged.split()),
        }

    def _chunk_text(self, text: str) -> Generator[str, None, None]:
        """Split text into overlapping word windows for model input limits."""
        words = text.split()
        if not words:
            return
        if len(words) <= self._chunk_size:
            yield text
            return

        step = self._chunk_size - self._overlap
        start = 0
        while start < len(words):
            end = start + self._chunk_size
            yield " ".join(words[start:end])
            if end >= len(words):
                break
            start += step

    def _summarize_chunk(self, text: str) -> str:
        pipe = _get_pipeline()
        result = pipe(
            text,
            max_length=self._max_length,
            min_length=self._min_length,
            do_sample=False,
        )
        return result[0]["summary_text"]


def _get_pipeline():
    """Lazy singleton — model loads once per process, stays in memory."""
    global _pipeline
    if _pipeline is None:
        from transformers import pipeline
        _pipeline = pipeline(
            "summarization",
            model="facebook/bart-large-cnn",
            device=-1,
            model_kwargs={"use_safetensors": True},
        )
    return _pipeline