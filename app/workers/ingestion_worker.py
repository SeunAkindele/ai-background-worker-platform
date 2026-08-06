"""Ingestion worker: chunk document text, embed, and store vectors."""
from typing import Any, Generator
from uuid import UUID

from app.core.database import db_session
from app.models.document import (
    Chunk,
    ChunkEmbedding,
    Document,
    DocumentStatus,
    EMBEDDING_DIMENSIONS,
)
from app.workers.base import BaseJobHandler


class IngestionHandler(BaseJobHandler[dict[str, Any], dict[str, Any]]):
    """Chunk a document, embed each chunk, and persist vectors in pgvector."""

    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
        default_chunk_size: int = 512,
        default_chunk_overlap: int = 50,
        batch_size: int = 32,
    ):
        self._model_name = model_name
        self._model = None
        self._default_chunk_size = default_chunk_size
        self._default_chunk_overlap = default_chunk_overlap
        self._batch_size = batch_size

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self._model_name, device="cpu")
        return self._model

    def validate_input(self, input_payload: dict[str, Any]) -> None:
        doc_id = input_payload.get("document_id")
        if doc_id is None:
            raise ValueError("Ingestion requires 'document_id'")
        try:
            UUID(str(doc_id))
        except ValueError:
            raise ValueError("'document_id' must be a valid UUID")

    def process(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Load document, chunk, embed in batches, and store results."""
        document_id = UUID(str(input_payload["document_id"]))
        chunk_size = input_payload.get("chunk_size", self._default_chunk_size)
        chunk_overlap = input_payload.get("chunk_overlap", self._default_chunk_overlap)

        with db_session() as db:
            document = db.query(Document).filter(Document.id == document_id).first()
            if document is None:
                raise ValueError(f"Document {document_id} not found")

            document.status = DocumentStatus.INGESTING
            db.commit()

            text = document.content
            title = document.title

        chunks_data = list(self._chunk_text(text, chunk_size, chunk_overlap))

        if not chunks_data:
            with db_session() as db:
                document = db.query(Document).filter(Document.id == document_id).first()
                document.status = DocumentStatus.READY
            return {
                "document_id": str(document_id),
                "title": title,
                "chunks_created": 0,
                "status": "ready",
            }

        chunk_texts = [c["text"] for c in chunks_data]
        all_embeddings = self._embed_in_batches(chunk_texts)

        with db_session() as db:
            document = db.query(Document).filter(Document.id == document_id).first()

            for i, chunk_data in enumerate(chunks_data):
                chunk = Chunk(
                    document_id=document_id,
                    content=chunk_data["text"],
                    chunk_index=chunk_data["index"],
                    token_count=chunk_data["token_count"],
                    metadata_=chunk_data.get("metadata"),
                )
                db.add(chunk)
                # flush() populates chunk.id without committing the transaction.
                db.flush()

                chunk_embedding = ChunkEmbedding(
                    chunk_id=chunk.id,
                    embedding=all_embeddings[i],
                    model_name=self._model_name,
                )
                db.add(chunk_embedding)

            document.status = DocumentStatus.READY

        return {
            "document_id": str(document_id),
            "title": title,
            "chunks_created": len(chunks_data),
            "embedding_dimensions": EMBEDDING_DIMENSIONS,
            "model": self._model_name,
            "status": "ready",
        }

    def format_result(self, raw_result: dict[str, Any]) -> dict[str, Any]:
        return raw_result

    def _chunk_text(
        self, text: str, chunk_size: int, overlap: int
    ) -> Generator[dict[str, Any], None, None]:
        """Yield overlapping word-window chunks with index and token estimate."""
        words = text.split()
        if not words:
            return

        step = max(1, chunk_size - overlap)
        chunk_index = 0
        start = 0

        while start < len(words):
            end = min(start + chunk_size, len(words))
            chunk_text = " ".join(words[start:end])
            word_count = end - start

            yield {
                "text": chunk_text,
                "index": chunk_index,
                "token_count": int(word_count * 1.3),
                "metadata": {
                    "start_word": start,
                    "end_word": end,
                },
            }

            chunk_index += 1
            if end >= len(words):
                break
            start += step

    def _embed_in_batches(self, texts: list[str]) -> list[list[float]]:
        """Embed texts in fixed-size batches to bound peak memory usage."""
        model = self._get_model()
        all_embeddings = []

        for i in range(0, len(texts), self._batch_size):
            batch = texts[i : i + self._batch_size]
            batch_embeddings = model.encode(batch).tolist()
            all_embeddings.extend(batch_embeddings)

        return all_embeddings
