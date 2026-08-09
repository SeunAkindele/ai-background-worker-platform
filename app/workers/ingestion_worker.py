"""Document ingestion: chunk text, embed children, store vectors for RAG."""
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
    """Chunk a document, embed searchable children, and persist embeddings."""

    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
        default_chunk_size: int = 512,
        default_chunk_overlap: int = 50,
        parent_size: int = 1024,
        parent_overlap: int = 128,
        child_size: int = 128,
        child_overlap: int = 32,
        batch_size: int = 32,
    ):
        self._model_name = model_name
        self._model = None
        self._default_chunk_size = default_chunk_size
        self._default_chunk_overlap = default_chunk_overlap
        self._parent_size = parent_size
        self._parent_overlap = parent_overlap
        self._child_size = child_size
        self._child_overlap = child_overlap
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
        document_id = UUID(str(input_payload["document_id"]))
        use_s2b = input_payload.get("use_small_to_big", True)

        parent_size = int(input_payload.get("parent_size", self._parent_size))
        parent_overlap = int(input_payload.get("parent_overlap", self._parent_overlap))
        child_size = int(input_payload.get("child_size", self._child_size))
        child_overlap = int(input_payload.get("child_overlap", self._child_overlap))
        # Flat fallback uses document/API chunk_size
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
            base_metadata = dict(document.metadata_ or {})

        if use_s2b:
            rows = self._chunk_small_to_big(
                text,
                parent_size=parent_size,
                parent_overlap=parent_overlap,
                child_size=child_size,
                child_overlap=child_overlap,
                base_metadata=base_metadata,
            )
        else:
            # Flat chunking: every chunk is a child with no parent
            rows = []
            for c in self._chunk_text(text, chunk_size, chunk_overlap):
                rows.append({
                    **c,
                    "temp_key": f"c{c['index']}",
                    "level": "child",
                    "parent_temp_key": None,
                    "metadata": {**(c.get("metadata") or {}), **base_metadata, "level": "child"},
                })

        if not rows:
            with db_session() as db:
                document = db.query(Document).filter(Document.id == document_id).first()
                document.status = DocumentStatus.READY
            return {
                "document_id": str(document_id),
                "title": title,
                "chunks_created": 0,
                "parents_created": 0,
                "status": "ready",
            }

        child_rows = [r for r in rows if r["level"] == "child"]
        child_texts = [r["text"] for r in child_rows]
        all_embeddings = self._embed_in_batches(child_texts) if child_texts else []

        parents_created = 0
        children_created = 0

        with db_session() as db:
            document = db.query(Document).filter(Document.id == document_id).first()

            temp_to_id: dict[str, UUID] = {}
            for row in rows:
                if row["level"] != "parent":
                    continue
                chunk = Chunk(
                    document_id=document_id,
                    content=row["text"],
                    chunk_index=row["index"],
                    token_count=row["token_count"],
                    level="parent",
                    parent_chunk_id=None,
                    metadata_=row["metadata"],
                )
                db.add(chunk)
                db.flush()
                temp_to_id[row["temp_key"]] = chunk.id
                parents_created += 1

            emb_i = 0
            for row in rows:
                if row["level"] != "child":
                    continue
                parent_id = None
                if row.get("parent_temp_key"):
                    parent_id = temp_to_id[row["parent_temp_key"]]

                chunk = Chunk(
                    document_id=document_id,
                    content=row["text"],
                    chunk_index=row["index"],
                    token_count=row["token_count"],
                    level="child",
                    parent_chunk_id=parent_id,
                    metadata_=row["metadata"],
                )
                db.add(chunk)
                db.flush()

                db.add(ChunkEmbedding(
                    chunk_id=chunk.id,
                    embedding=all_embeddings[emb_i],
                    model_name=self._model_name,
                ))
                emb_i += 1
                children_created += 1

            document.status = DocumentStatus.READY

        return {
            "document_id": str(document_id),
            "title": title,
            "chunks_created": children_created,
            "parents_created": parents_created,
            "embedding_dimensions": EMBEDDING_DIMENSIONS,
            "model": self._model_name,
            "use_small_to_big": use_s2b,
            "status": "ready",
        }


    def format_result(self, raw_result: dict[str, Any]) -> dict[str, Any]:
        return raw_result


    def _chunk_small_to_big(
        self,
        text: str,
        *,
        parent_size: int = 1024,
        parent_overlap: int = 128,
        child_size: int = 128,
        child_overlap: int = 32,
        base_metadata: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Build parent/child chunk rows via nested sliding windows."""
        words = text.split()
        if not words:
            return []

        base_metadata = base_metadata or {}
        parent_step = max(1, parent_size - parent_overlap)
        child_step = max(1, child_size - child_overlap)

        rows: list[dict[str, Any]] = []
        parent_local_index = 0
        start = 0

        while start < len(words):
            pend = min(start + parent_size, len(words))
            parent_words = words[start:pend]
            parent_text = " ".join(parent_words)
            temp_parent_key = f"p{parent_local_index}"

            rows.append({
                "temp_key": temp_parent_key,
                "level": "parent",
                "text": parent_text,
                "index": parent_local_index,
                "token_count": int(len(parent_words) * 1.3),
                "metadata": {
                    **base_metadata,
                    "level": "parent",
                    "start_word": start,
                    "end_word": pend,
                },
                "parent_temp_key": None,
            })

            cstart = 0
            child_local = 0
            while cstart < len(parent_words):
                cend = min(cstart + child_size, len(parent_words))
                child_words = parent_words[cstart:cend]
                rows.append({
                    "temp_key": f"{temp_parent_key}_c{child_local}",
                    "level": "child",
                    "text": " ".join(child_words),
                    "index": child_local,
                    "token_count": int(len(child_words) * 1.3),
                    "metadata": {
                        **base_metadata,
                        "level": "child",
                        "start_word": start + cstart,
                        "end_word": start + cend,
                    },
                    "parent_temp_key": temp_parent_key,
                })
                child_local += 1
                if cend >= len(parent_words):
                    break
                cstart += child_step

            parent_local_index += 1
            if pend >= len(words):
                break
            start += parent_step

        return rows
        

    def _chunk_text(
        self, text: str, chunk_size: int, overlap: int
    ) -> Generator[dict[str, Any], None, None]:
        """Yield overlapping word-window chunks with index and token estimates."""
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
        """Embed texts in fixed-size batches to bound peak memory."""
        model = self._get_model()
        all_embeddings = []

        for i in range(0, len(texts), self._batch_size):
            batch = texts[i : i + self._batch_size]
            batch_embeddings = model.encode(batch).tolist()
            all_embeddings.extend(batch_embeddings)

        return all_embeddings