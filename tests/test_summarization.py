import types
from unittest.mock import MagicMock, patch

import pytest

from app.workers.summarization_worker import SummarizationHandler


def _handler(**kwargs) -> SummarizationHandler:
    defaults = {
        "chunk_size": 10,
        "overlap": 3,
        "max_length": 150,
        "min_length": 40,
        "max_depth": 3,
    }
    defaults.update(kwargs)
    return SummarizationHandler(**defaults)


# --- chunking tests ---


class TestChunkText:
    def test_returns_generator(self):
        result = _handler()._chunk_text("some words here")
        assert isinstance(result, types.GeneratorType)

    def test_short_text_yields_single_chunk(self):
        text = "hello world this is short"
        chunks = list(_handler(chunk_size=100, overlap=10)._chunk_text(text))
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_empty_text_yields_nothing(self):
        chunks = list(_handler()._chunk_text(""))
        assert chunks == []

    def test_exact_chunk_size_yields_single_chunk(self):
        words = [f"w{i}" for i in range(10)]
        text = " ".join(words)
        chunks = list(_handler(chunk_size=10, overlap=3)._chunk_text(text))
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_produces_multiple_chunks(self):
        words = [f"w{i}" for i in range(25)]
        text = " ".join(words)
        chunks = list(_handler(chunk_size=10, overlap=3)._chunk_text(text))
        assert len(chunks) > 1

    def test_chunks_overlap_correctly(self):
        words = [f"w{i}" for i in range(20)]
        text = " ".join(words)
        chunks = list(_handler(chunk_size=10, overlap=3)._chunk_text(text))

        c0_words = chunks[0].split()
        c1_words = chunks[1].split()
        assert c0_words[-3:] == c1_words[:3]

    def test_all_words_are_covered(self):
        words = [f"w{i}" for i in range(23)]
        text = " ".join(words)
        chunks = list(_handler(chunk_size=10, overlap=3)._chunk_text(text))

        first_word = chunks[0].split()[0]
        last_word = chunks[-1].split()[-1]
        assert first_word == "w0"
        assert last_word == "w22"

    def test_chunk_size_not_exceeded(self):
        words = [f"w{i}" for i in range(50)]
        text = " ".join(words)
        chunks = list(_handler(chunk_size=10, overlap=2)._chunk_text(text))

        for chunk in chunks:
            assert len(chunk.split()) <= 10


# --- summarize / run tests (model mocked) ---


class TestSummarize:
    @patch("app.workers.summarization_worker._get_pipeline")
    def test_short_text_no_chunking(self, mock_get_pipeline):
        mock_pipe = MagicMock()
        mock_pipe.return_value = [{"summary_text": "A short summary."}]
        mock_get_pipeline.return_value = mock_pipe

        result = _handler(chunk_size=500).run({"text": "This is a short text."})

        assert result["summary"] == "A short summary."
        assert result["chunks_processed"] == 1
        assert result["original_word_count"] == 5
        mock_pipe.assert_called_once()

    @patch("app.workers.summarization_worker._get_pipeline")
    def test_long_text_gets_chunked(self, mock_get_pipeline):
        mock_pipe = MagicMock()
        mock_pipe.return_value = [{"summary_text": "Chunk summary."}]
        mock_get_pipeline.return_value = mock_pipe

        words = ["word"] * 1200
        text = " ".join(words)

        result = _handler(chunk_size=500, overlap=50).run({"text": text})

        assert result["chunks_processed"] > 1
        assert result["original_word_count"] == 1200
        assert mock_pipe.call_count > 1

    @patch("app.workers.summarization_worker._get_pipeline")
    def test_result_contains_expected_keys(self, mock_get_pipeline):
        mock_pipe = MagicMock()
        mock_pipe.return_value = [{"summary_text": "Result."}]
        mock_get_pipeline.return_value = mock_pipe

        result = _handler().run({"text": "Some input text to summarize here."})

        assert "summary" in result
        assert "chunks_processed" in result
        assert "original_word_count" in result
        assert "summary_word_count" in result

    @patch("app.workers.summarization_worker._get_pipeline")
    def test_recursive_summarization_when_merged_too_long(self, mock_get_pipeline):
        call_count = {"n": 0}

        def fake_summarize(text, **kwargs):
            call_count["n"] += 1
            if call_count["n"] <= 5:
                return [{"summary_text": " ".join(["sum"] * 200)}]
            return [{"summary_text": "Final short summary."}]

        mock_pipe = MagicMock()
        mock_pipe.side_effect = fake_summarize
        mock_get_pipeline.return_value = mock_pipe

        words = ["word"] * 2000
        text = " ".join(words)

        result = _handler(chunk_size=500, overlap=50).run({"text": text})

        assert result["chunks_processed"] > 1
        assert "summary" in result

    @patch("app.workers.summarization_worker._get_pipeline")
    def test_max_depth_prevents_infinite_recursion(self, mock_get_pipeline):
        mock_pipe = MagicMock()
        mock_pipe.return_value = [{"summary_text": " ".join(["w"] * 600)}]
        mock_get_pipeline.return_value = mock_pipe

        words = ["word"] * 2000
        text = " ".join(words)

        result = _handler(chunk_size=500, overlap=50, max_depth=3).run({"text": text})

        assert "summary" in result

    def test_validate_input_rejects_empty_text(self):
        with pytest.raises(ValueError, match="non-empty"):
            _handler().validate_input({"text": "   "})
