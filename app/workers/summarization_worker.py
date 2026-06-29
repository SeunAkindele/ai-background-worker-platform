"""
Real summarization worker — Stage 4.

Implements text chunking with sliding window overlap
and Hugging Face pipeline-based summarization.
"""
from typing import Any, Generator

_pipeline = None


def summarize(
    text: str,
    chunk_size: int = 500,
    overlap: int = 50,
    max_length: int = 150,
    min_length: int = 40,
    _depth: int = 0,
    _max_depth: int = 3,
) -> dict[str, Any]:
    """
    Summarize text of any length using chunking + recursive merge.

    1. If text is short enough, summarize directly.
    2. Otherwise, chunk it, summarize each chunk, merge the summaries.
    3. If merged summary is still too long, recurse (up to _max_depth).

    Args:
        text: The input text to summarize.
        chunk_size: Max words per chunk for the sliding window.
        overlap: Overlapping words between chunks.
        max_length: Max tokens in each chunk's summary output.
        min_length: Min tokens in each chunk's summary output.
        _depth: Current recursion depth (internal use).
        _max_depth: Maximum recursion depth to prevent infinite loops.

    Returns:
        Dict with summary, chunks_processed, original_word_count, summary_word_count.
    """
    original_word_count = len(text.split())
    chunks_processed = 0

    words = text.split()

    if len(words) <= chunk_size:
        summary_text = summarize_chunk(text, max_length=max_length, min_length=min_length)
        return {
            "summary": summary_text,
            "chunks_processed": 1,
            "original_word_count": original_word_count,
            "summary_word_count": len(summary_text.split()),
        }

    chunk_summaries = []
    for chunk in chunk_text(text, chunk_size=chunk_size, overlap=overlap):
        chunk_summary = summarize_chunk(chunk, max_length=max_length, min_length=min_length)
        chunk_summaries.append(chunk_summary)
        chunks_processed += 1

    merged = " ".join(chunk_summaries)

    if len(merged.split()) > chunk_size and _depth < _max_depth:
        recursive_result = summarize(
            merged,
            chunk_size=chunk_size,
            overlap=overlap,
            max_length=max_length,
            min_length=min_length,
            _depth=_depth + 1,
            _max_depth=_max_depth,
        )
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


def chunk_text(
    text: str,
    chunk_size: int = 500,
    overlap: int = 50,
) -> Generator[str, None, None]:
    """
    Split text into overlapping word-based chunks using a sliding window.

    Yields one chunk at a time (generator — lazy evaluation, memory-efficient).

    Args:
        text: The input text to chunk.
        chunk_size: Maximum number of words per chunk.
        overlap: Number of overlapping words between consecutive chunks.

    Yields:
        A string chunk of at most chunk_size words.

    Raises:
        ValueError: If overlap >= chunk_size (step would be zero or negative).
    """
    if overlap >= chunk_size:
        raise ValueError(
            f"overlap ({overlap}) must be less than chunk_size ({chunk_size})"
        )

    words = text.split()
    total_words = len(words)

    if total_words == 0:
        return

    if total_words <= chunk_size:
        yield text
        return

    step = chunk_size - overlap
    start = 0

    while start < total_words:
        end = start + chunk_size
        chunk_words = words[start:end]
        yield " ".join(chunk_words)

        if end >= total_words:
            break

        start += step


def summarize_chunk(text: str, max_length: int = 150, min_length: int = 40) -> str:
    """Summarize a single chunk of text using the Hugging Face pipeline."""
    pipe = get_summarization_pipeline()
    result = pipe(text, max_length=max_length, min_length=min_length, do_sample=False)
    return result[0]["summary_text"]


def get_summarization_pipeline():
    """
    Lazy-loading singleton for the summarization model.

    First call downloads/loads the model (~1.6GB, takes a while).
    Subsequent calls return the cached pipeline instantly.
    Uses safetensors weights (no torch.load — works on torch < 2.6).
    """
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