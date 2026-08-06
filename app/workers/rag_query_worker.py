"""RAG query worker: embed question, retrieve top-K chunks, generate answer."""
from typing import Any
from uuid import UUID

from sqlalchemy import text

from app.core.database import db_session
from app.models.document import DocumentStatus
from app.workers.base import BaseJobHandler


class RAGQueryHandler(BaseJobHandler[dict[str, Any], dict[str, Any]]):
    """
    Answer a question with retrieval-augmented generation:
    embed → top-K vector search → grounded prompt → generate.
    """

    def __init__(
        self,
        embedding_model_name: str = "all-MiniLM-L6-v2",
        top_k: int = 5,
        similarity_threshold: float = 0.3,
    ):
        self._embedding_model_name = embedding_model_name
        self._embedding_model = None
        self._top_k = top_k
        self._similarity_threshold = similarity_threshold
        self._summarization_pipeline = None

    def _get_embedding_model(self):
        if self._embedding_model is None:
            from sentence_transformers import SentenceTransformer
            self._embedding_model = SentenceTransformer(
                self._embedding_model_name, device="cpu"
            )
        return self._embedding_model

    def _get_summarization_pipeline(self):
        """Local answer generation via BART summarization (no external LLM API)."""
        if self._summarization_pipeline is None:
            from transformers import pipeline
            self._summarization_pipeline = pipeline(
                "summarization",
                model="facebook/bart-large-cnn",
                device=-1,
                model_kwargs={"use_safetensors": True},
            )
        return self._summarization_pipeline

    def validate_input(self, input_payload: dict[str, Any]) -> None:
        question = input_payload.get("question")
        if not question or not isinstance(question, str) or not question.strip():
            raise ValueError("RAG query requires a non-empty 'question' field")

        top_k = input_payload.get("top_k")
        if top_k is not None:
            if not isinstance(top_k, int) or top_k < 1 or top_k > 50:
                raise ValueError("'top_k' must be an integer between 1 and 50")

        doc_ids = input_payload.get("document_ids")
        if doc_ids is not None:
            if not isinstance(doc_ids, list):
                raise ValueError("'document_ids' must be a list of UUID strings")
            for did in doc_ids:
                try:
                    UUID(str(did))
                except ValueError:
                    raise ValueError(f"Invalid document_id: {did}")

    def process(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        question = input_payload["question"]
        top_k = input_payload.get("top_k", self._top_k)
        document_ids = input_payload.get("document_ids")

        query_embedding = self._embed_question(question)

        retrieved_chunks = self._retrieve_top_k(
            query_embedding, top_k, document_ids
        )

        if not retrieved_chunks:
            return {
                "question": question,
                "answer": "No relevant documents found to answer this question.",
                "sources": [],
                "chunks_retrieved": 0,
            }

        prompt = self._build_prompt(question, retrieved_chunks)
        answer = self._generate_answer(prompt)

        sources = [
            {
                "chunk_id": str(chunk["chunk_id"]),
                "document_id": str(chunk["document_id"]),
                "document_title": chunk["document_title"],
                "chunk_index": chunk["chunk_index"],
                "similarity": round(chunk["similarity"], 4),
                "text_preview": chunk["text"][:200] + "..."
                if len(chunk["text"]) > 200
                else chunk["text"],
            }
            for chunk in retrieved_chunks
        ]

        return {
            "question": question,
            "answer": answer,
            "sources": sources,
            "chunks_retrieved": len(retrieved_chunks),
            "top_k_requested": top_k,
            "model": self._embedding_model_name,
        }

    def format_result(self, raw_result: dict[str, Any]) -> dict[str, Any]:
        return raw_result

    def _embed_question(self, question: str) -> list[float]:
        """Embed the question with the same model used for chunk vectors."""
        model = self._get_embedding_model()
        return model.encode(question).tolist()

    def _retrieve_top_k(
        self,
        query_embedding: list[float],
        top_k: int,
        document_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Return the top-K most similar chunks via pgvector cosine distance."""
        query = """
            SELECT 
                c.id AS chunk_id,
                c.document_id,
                c.content AS chunk_text,
                c.chunk_index,
                c.token_count,
                c.metadata AS chunk_metadata,
                d.title AS document_title,
                1 - (ce.embedding <=> :embedding) AS similarity
            FROM chunk_embeddings ce
            JOIN chunks c ON c.id = ce.chunk_id
            JOIN documents d ON d.id = c.document_id
            WHERE d.status = :doc_status
              AND 1 - (ce.embedding <=> :embedding) > :threshold
        """

        if document_ids:
            placeholders = ", ".join(f":doc_id_{i}" for i in range(len(document_ids)))
            query += f" AND c.document_id IN ({placeholders})"

        query += """
            ORDER BY ce.embedding <=> :embedding ASC
            LIMIT :top_k
        """

        # SQLAlchemy Postgres Enum stores member NAMES (READY), not values.
        params = {
            "embedding": str(query_embedding),
            "threshold": self._similarity_threshold,
            "top_k": top_k,
            "doc_status": DocumentStatus.READY.name,
        }
        if document_ids:
            for i, doc_id in enumerate(document_ids):
                params[f"doc_id_{i}"] = doc_id

        with db_session() as db:
            result = db.execute(text(query), params)
            rows = result.fetchall()

        retrieved = []
        for row in rows:
            retrieved.append({
                "chunk_id": row.chunk_id,
                "document_id": row.document_id,
                "text": row.chunk_text,
                "chunk_index": row.chunk_index,
                "token_count": row.token_count,
                "chunk_metadata": row.chunk_metadata,
                "document_title": row.document_title,
                "similarity": float(row.similarity),
            })

        return retrieved

    def _build_prompt(
        self, question: str, chunks: list[dict[str, Any]]
    ) -> str:
        """Build a grounded prompt from the retrieved context chunks."""
        context_parts = []
        for i, chunk in enumerate(chunks, 1):
            source_label = f"[Source {i}: {chunk['document_title']}]"
            context_parts.append(f"{source_label}\n{chunk['text']}")

        context = "\n\n".join(context_parts)

        prompt = (
            f"Use the following context to answer the question. "
            f"If the context doesn't contain the answer, say so.\n\n"
            f"Context:\n{context}\n\n"
            f"Question: {question}\n\n"
            f"Answer:"
        )

        return prompt

    def _generate_answer(self, prompt: str) -> str:
        """Generate an answer from the grounded prompt via the local model."""
        pipe = self._get_summarization_pipeline()

        words = prompt.split()
        if len(words) > 900:
            prompt = " ".join(words[:900])

        result = pipe(
            prompt,
            max_length=200,
            min_length=30,
            do_sample=False,
        )
        return result[0]["summary_text"]
