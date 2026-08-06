import types
from unittest.mock import MagicMock, patch

import pytest

from app.workers.summarization_worker import chunk_text, summarize


class TestChunkText:
    def test_returns_generator(self):
        result = chunk_text("some words here")
        assert isinstance(result, types.GeneratorType)

    def test_short_text_yields_single_chunk(self):
        text = "hello world this is short"
        chunks = list(chunk_text(text, chunk_size=100, overlap=10))
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_empty_text_yields_nothing(self):
        chunks = list(chunk_text("", chunk_size=100, overlap=10))
        assert chunks == []

    def test_exact_chunk_size_yields_single_chunk(self):
        words = [f"w{i}" for i in range(10)]
        text = " ".join(words)
        chunks = list(chunk_text(text, chunk_size=10, overlap=3))
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_produces_multiple_chunks(self):
        words = [f"w{i}" for i in range(25)]
        text = " ".join(words)
        chunks = list(chunk_text(text, chunk_size=10, overlap=3))
        assert len(chunks) > 1

    def test_chunks_overlap_correctly(self):
        words = [f"w{i}" for i in range(20)]
        text = " ".join(words)
        chunks = list(chunk_text(text, chunk_size=10, overlap=3))

        c0_words = chunks[0].split()
        c1_words = chunks[1].split()
        assert c0_words[-3:] == c1_words[:3]

    def test_all_words_are_covered(self):
        words = [f"w{i}" for i in range(23)]
        text = " ".join(words)
        chunks = list(chunk_text(text, chunk_size=10, overlap=3))

        first_word = chunks[0].split()[0]
        last_word = chunks[-1].split()[-1]
        assert first_word == "w0"
        assert last_word == "w22"

    def test_chunk_size_not_exceeded(self):
        words = [f"w{i}" for i in range(50)]
        text = " ".join(words)
        chunks = list(chunk_text(text, chunk_size=10, overlap=2))

        for chunk in chunks:
            assert len(chunk.split()) <= 10

    def test_overlap_equals_chunk_size_raises(self):
        with pytest.raises(ValueError, match="overlap.*must be less than chunk_size"):
            list(chunk_text("hello world", chunk_size=5, overlap=5))

    def test_overlap_exceeds_chunk_size_raises(self):
        with pytest.raises(ValueError, match="overlap.*must be less than chunk_size"):
            list(chunk_text("hello world", chunk_size=5, overlap=10))


class TestSummarize:
    @patch("app.workers.summarization_worker.get_summarization_pipeline")
    def test_short_text_no_chunking(self, mock_get_pipeline):
        mock_pipe = MagicMock()
        mock_pipe.return_value = [{"summary_text": "A short summary."}]
        mock_get_pipeline.return_value = mock_pipe

        result = summarize("This is a short text.", chunk_size=500)

        assert result["summary"] == "A short summary."
        assert result["chunks_processed"] == 1
        assert result["original_word_count"] == 5
        mock_pipe.assert_called_once()

    @patch("app.workers.summarization_worker.get_summarization_pipeline")
    def test_long_text_gets_chunked(self, mock_get_pipeline):
        mock_pipe = MagicMock()
        mock_pipe.return_value = [{"summary_text": "Chunk summary."}]
        mock_get_pipeline.return_value = mock_pipe

        words = ["word"] * 1200
        text = " ".join(words)

        result = summarize(text, chunk_size=500, overlap=50)

        assert result["chunks_processed"] > 1
        assert result["original_word_count"] == 1200
        assert mock_pipe.call_count > 1

    @patch("app.workers.summarization_worker.get_summarization_pipeline")
    def test_result_contains_expected_keys(self, mock_get_pipeline):
        mock_pipe = MagicMock()
        mock_pipe.return_value = [{"summary_text": "Result."}]
        mock_get_pipeline.return_value = mock_pipe

        result = summarize("Some input text to summarize here.")

        assert "summary" in result
        assert "chunks_processed" in result
        assert "original_word_count" in result
        assert "summary_word_count" in result

    @patch("app.workers.summarization_worker.get_summarization_pipeline")
    def test_recursive_summarization_when_merged_too_long(self, mock_get_pipeline):
        call_count = {"n": 0}

        def fake_summarize(text, **kwargs):
            call_count["n"] += 1
            # Return something shorter than input but still many words on first passes
            if call_count["n"] <= 5:
                return [{"summary_text": " ".join(["sum"] * 200)}]
            return [{"summary_text": "Final short summary."}]

        mock_pipe = MagicMock()
        mock_pipe.side_effect = fake_summarize
        mock_get_pipeline.return_value = mock_pipe

        words = ["word"] * 2000
        text = " ".join(words)

        result = summarize(text, chunk_size=500, overlap=50)

        assert result["chunks_processed"] > 1
        assert "summary" in result

    @patch("app.workers.summarization_worker.get_summarization_pipeline")
    def test_max_depth_prevents_infinite_recursion(self, mock_get_pipeline):
        mock_pipe = MagicMock()
        # Always return something longer than chunk_size to force recursion
        mock_pipe.return_value = [{"summary_text": " ".join(["w"] * 600)}]
        mock_get_pipeline.return_value = mock_pipe

        words = ["word"] * 2000
        text = " ".join(words)

        # Should not hang — _max_depth=3 stops it
        result = summarize(text, chunk_size=500, overlap=50, _max_depth=3)

        assert "summary" in result