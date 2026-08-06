"""Text embedding handler with optional cosine similarity and nearest-neighbor lookup."""
import math
from typing import Any

from app.workers.base import BaseJobHandler


class EmbeddingHandler(BaseJobHandler[dict[str, Any], dict[str, Any]]):
    """Generates text embeddings using sentence-transformers."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self._model_name = model_name
        self._model = None

    def _get_model(self):
        """Lazy-load the sentence-transformer model (one per process)."""
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self._model_name, device="cpu")
        return self._model

    def validate_input(self, input_payload: dict[str, Any]) -> None:
        text = input_payload.get("text")
        texts = input_payload.get("texts")

        if text is None and texts is None:
            raise ValueError(
                "Embeddings require either 'text' (single string) "
                "or 'texts' (list of strings)"
            )

        if text is not None and not isinstance(text, str):
            raise ValueError("'text' must be a string")

        if texts is not None:
            if not isinstance(texts, list) or not all(isinstance(t, str) for t in texts):
                raise ValueError("'texts' must be a list of strings")
            if len(texts) == 0:
                raise ValueError("'texts' must not be empty")
            if len(texts) > 100:
                raise ValueError("Batch size limited to 100 texts")

    def process(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Encode text(s); optionally compare or find the nearest match."""
        model = self._get_model()

        text = input_payload.get("text")
        texts = input_payload.get("texts")
        compare_to = input_payload.get("compare_to")

        if text is not None:
            embedding = model.encode(text).tolist()
            result: dict[str, Any] = {
                "embedding": embedding,
                "dimensions": len(embedding),
            }

            if compare_to and isinstance(compare_to, str):
                other_embedding = model.encode(compare_to).tolist()
                similarity = self._cosine_similarity(embedding, other_embedding)
                result["similarity"] = similarity
                result["compare_to_embedding"] = other_embedding

            return result

        embeddings = model.encode(texts).tolist()
        result = {
            "embeddings": embeddings,
            "count": len(embeddings),
            "dimensions": len(embeddings[0]) if embeddings else 0,
        }

        if compare_to and isinstance(compare_to, str):
            query_embedding = model.encode(compare_to).tolist()
            nearest_idx, nearest_score = self._find_nearest(
                query_embedding, embeddings
            )
            result["nearest"] = {
                "index": nearest_idx,
                "text": texts[nearest_idx],
                "similarity": nearest_score,
            }

        return result

    def format_result(self, raw_result: dict[str, Any]) -> dict[str, Any]:
        if "embedding" in raw_result:
            raw_result["embedding"] = [
                round(v, 6) for v in raw_result["embedding"]
            ]
        if "embeddings" in raw_result:
            raw_result["embeddings"] = [
                [round(v, 6) for v in emb] for emb in raw_result["embeddings"]
            ]
        return raw_result

    @staticmethod
    def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
        """Return cosine similarity between two vectors in [-1, 1]."""
        dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
        magnitude_a = math.sqrt(sum(a * a for a in vec_a))
        magnitude_b = math.sqrt(sum(b * b for b in vec_b))

        if magnitude_a == 0 or magnitude_b == 0:
            return 0.0

        return dot_product / (magnitude_a * magnitude_b)

    @staticmethod
    def _find_nearest(
        query: list[float], candidates: list[list[float]]
    ) -> tuple[int, float]:
        """Return the index and score of the most similar candidate embedding."""
        best_idx = 0
        best_score = -1.0

        for idx, candidate in enumerate(candidates):
            score = EmbeddingHandler._cosine_similarity(query, candidate)
            if score > best_score:
                best_score = score
                best_idx = idx

        return best_idx, round(best_score, 6)
