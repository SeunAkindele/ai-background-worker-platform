"""
Stage 13b — Ingestion Worker.

Pipeline: Document text → Chunk → Embed → Store in vector DB.

DSA Focus:
----------
- Sliding window chunking: O(n) where n = character count of document.
  Same concept as your SummarizationHandler, but optimized for retrieval
  (smaller chunks, more overlap for context continuity).
- Batch embedding: process multiple chunks in one model.encode() call.
  GPU/CPU vectorization makes batch encoding ~10x faster than one-by-one.
  model.encode(["chunk1", "chunk2", ...]) uses internal batching with
  matrix multiplication — O(batch_size * seq_len * d_model) but with
  SIMD/BLAS parallelism.

Python Internals Focus:
-----------------------
- Generator for chunking: yields one chunk at a time, never holding the
  entire chunk list in memory. For a 10MB document producing 10,000 chunks,
  this avoids allocating a 10,000-element list upfront.
- The batch_size parameter controls the trade-off between memory and speed.
  Too large → OOM on CPU. Too small → underutilizes vectorization.
  32 is a safe default for all-MiniLM-L6-v2 on CPU.
"""
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
    """
    Ingests a document: chunk its text, embed each chunk, store vectors.
    
    Reuses the same sentence-transformers model as EmbeddingHandler
    (all-MiniLM-L6-v2) but loads its own instance. In production,
    you'd share a model server (like Triton) to avoid duplicate memory.
    For Stage 13, each worker process has its own copy — simple and isolated.
    """

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

    # ─── VALIDATION ──────────────────────────────────────────────────

    def validate_input(self, input_payload: dict[str, Any]) -> None:
        doc_id = input_payload.get("document_id")
        if doc_id is None:
            raise ValueError("Ingestion requires 'document_id'")
        try:
            UUID(str(doc_id))
        except ValueError:
            raise ValueError("'document_id' must be a valid UUID")

    # ─── MAIN PIPELINE ──────────────────────────────────────────────

    def process(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """
        The ingestion pipeline in 4 steps:
        
        1. Load document from DB
        2. Chunk the text (sliding window)
        3. Embed chunks in batches
        4. Store chunks + embeddings in DB
        
        This runs inside a Celery worker (sync context), so we use
        the sync db_session() — same as every other worker.
        """
        document_id = UUID(str(input_payload["document_id"]))
        chunk_size = input_payload.get("chunk_size", self._default_chunk_size)
        chunk_overlap = input_payload.get("chunk_overlap", self._default_chunk_overlap)

        # Step 1: Load the document
        with db_session() as db:
            document = db.query(Document).filter(Document.id == document_id).first()
            if document is None:
                raise ValueError(f"Document {document_id} not found")

            # Mark as INGESTING so the API can show progress
            document.status = DocumentStatus.INGESTING
            db.commit()

            # Read the text while the session is open.
            # After db_session() closes, lazy attributes would fail.
            text = document.content
            title = document.title

        # Step 2: Chunk the text
        # Collect chunks into a list because we need random access for
        # batch embedding. The generator gives us lazy evaluation during
        # iteration, but we materialize here because step 3 needs indices.
        chunks_data = list(self._chunk_text(text, chunk_size, chunk_overlap))

        if not chunks_data:
            # Edge case: empty document or document shorter than overlap
            with db_session() as db:
                document = db.query(Document).filter(Document.id == document_id).first()
                document.status = DocumentStatus.READY
            return {
                "document_id": str(document_id),
                "title": title,
                "chunks_created": 0,
                "status": "ready",
            }

        # Step 3: Embed in batches
        # Extract just the text strings for the model
        chunk_texts = [c["text"] for c in chunks_data]
        all_embeddings = self._embed_in_batches(chunk_texts)

        # Step 4: Store everything in DB
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
                # flush() sends the INSERT to Postgres and populates chunk.id,
                # but does NOT commit the transaction. This lets us use chunk.id
                # for the embedding row while keeping everything in one atomic
                # transaction. If any step fails, the entire batch rolls back.
                db.flush()

                chunk_embedding = ChunkEmbedding(
                    chunk_id=chunk.id,
                    embedding=all_embeddings[i],
                    model_name=self._model_name,
                )
                db.add(chunk_embedding)

            document.status = DocumentStatus.READY
            # db_session() context manager calls db.commit() on exit

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

    # ─── CHUNKING (DSA: Sliding Window) ─────────────────────────────

    def _chunk_text(
        self, text: str, chunk_size: int, overlap: int
    ) -> Generator[dict[str, Any], None, None]:
        """
        DSA: Sliding window over words — O(n) single pass.
        
        This is the SAME algorithm as SummarizationHandler._chunk_text()
        but returns richer metadata per chunk (index, token count).
        
        Why word-based instead of character-based?
        - Word boundaries are natural semantic breaks
        - Token counts approximate better with words than characters
        - For production, you'd use tiktoken (token-level chunking) to
          precisely control how many tokens each chunk uses in the LLM prompt
        
        Why overlap?
        - A sentence split between two chunks loses context at the boundary.
        - Overlap (typically 10-20% of chunk_size) ensures boundary sentences
          appear in BOTH adjacent chunks, so retrieval can find them.
        - Trade-off: more overlap = more chunks = more storage + slower search.
        
        Visual:
        Document: [w1 w2 w3 w4 w5 w6 w7 w8 w9 w10 w11 w12]
        chunk_size=5, overlap=2:
          Chunk 0: [w1  w2  w3  w4  w5]        ← start=0
          Chunk 1: [w4  w5  w6  w7  w8]        ← start=3 (step = 5-2 = 3)
          Chunk 2: [w7  w8  w9  w10 w11]       ← start=6
          Chunk 3: [w10 w11 w12]               ← start=9, partial final chunk
                        ^^
                    overlap zone — these words appear in two chunks
        """
        words = text.split()
        if not words:
            return

        # step = how far to advance the window start each iteration.
        # step = chunk_size - overlap ensures the overlap zone.
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
                # Rough token estimate: ~1.3 tokens per English word.
                # In production, use tiktoken.encode() for exact counts.
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

    # ─── BATCH EMBEDDING ────────────────────────────────────────────

    def _embed_in_batches(self, texts: list[str]) -> list[list[float]]:
        """
        Embed texts in fixed-size batches to control memory usage.
        
        Why batch instead of all-at-once?
        - model.encode(texts) loads ALL texts into a tensor at once.
          For 10,000 chunks, that's a ~10,000 × 128 token × 384 dim tensor
          → potential OOM on machines with limited RAM.
        - Batching: process 32 texts at a time, collect results.
          Peak memory = batch_size × max_seq_len × hidden_dim.
        
        DSA Focus:
        - This is the classic "process in blocks" pattern — same idea as
          reading a file in 8KB buffers instead of loading it all into memory.
        - Time complexity: O(n * d) where n=total texts, d=model dimensions.
          Batching doesn't change Big-O, it changes the constant (memory).
        """
        model = self._get_model()
        all_embeddings = []

        for i in range(0, len(texts), self._batch_size):
            batch = texts[i : i + self._batch_size]
            # model.encode() returns a numpy ndarray of shape (batch_size, 384).
            # .tolist() converts to a Python list[list[float]] for JSON/DB storage.
            batch_embeddings = model.encode(batch).tolist()
            all_embeddings.extend(batch_embeddings)

        return all_embeddings