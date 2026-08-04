"""
Stage 13c — RAG Query Worker.

Pipeline: Question → Embed → Top-K retrieval → Build prompt → Generate answer.

DSA Focus:
----------
- Top-K retrieval: pgvector's <=> operator computes cosine distance and
  returns the K nearest vectors. With an HNSW index, this is O(log n)
  per query instead of O(n) brute-force.
- Cosine distance vs cosine similarity:
    distance = 1 - similarity
    <=> returns distance (lower = more similar)
    So ORDER BY embedding <=> query_vector ASC gives most similar first.
- Prompt engineering: the retrieved chunks become the "context" section
  of the prompt. The LLM generates an answer grounded in that context.

Python Internals Focus:
-----------------------
- Raw SQL via text(): pgvector operators (<=> for cosine distance) aren't
  natively supported in SQLAlchemy's ORM query builder. We use text()
  to write the vector search query directly. This is safe because we
  pass the query vector as a bind parameter (:embedding), not string
  concatenation — no SQL injection risk.
"""
from typing import Any
from uuid import UUID

from sqlalchemy import text

from app.core.database import db_session
from app.models.document import DocumentStatus
from app.workers.base import BaseJobHandler


class RAGQueryHandler(BaseJobHandler[dict[str, Any], dict[str, Any]]):
    """
    Answers a question using Retrieval-Augmented Generation:
    1. Embed the question
    2. Find top-K similar chunks from the vector store
    3. Build a grounded prompt
    4. Generate an answer using the summarization pipeline
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
        # Chunks below this cosine similarity are filtered out.
        # 0.3 is intentionally low for Stage 13 (naive RAG) —
        # better to include marginal chunks than miss relevant ones.
        # Stage 14's reranker will fix precision.
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
        """
        Reuse the same BART model from your summarization worker.
        
        In a real RAG system, you'd use a chat/instruction-tuned LLM
        (GPT-4, Claude, Llama, etc.) via API. But your platform runs
        locally without API keys, so we reuse BART as a "generate text
        from context" model. It's not great at Q&A, but it demonstrates
        the pipeline. Stage 15 will add a proper LLM router.
        
        IMPORTANT CAVEAT: BART is trained for summarization, not Q&A.
        It will try to summarize the context, not directly answer the
        question. The answers will be mediocre — that's expected for
        Stage 13 (naive RAG). The architecture matters more than the
        output quality at this stage.
        """
        if self._summarization_pipeline is None:
            from transformers import pipeline
            self._summarization_pipeline = pipeline(
                "summarization",
                model="facebook/bart-large-cnn",
                device=-1,
                model_kwargs={"use_safetensors": True},
            )
        return self._summarization_pipeline

    # ─── VALIDATION ──────────────────────────────────────────────────

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

    # ─── MAIN PIPELINE ──────────────────────────────────────────────

    def process(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        question = input_payload["question"]
        top_k = input_payload.get("top_k", self._top_k)
        document_ids = input_payload.get("document_ids")

        # Step 1: Embed the question
        # The question and chunks must use the SAME embedding model.
        # If they don't, the vectors live in different "spaces" and
        # cosine similarity becomes meaningless — like measuring distance
        # between a point in miles and another in kilometers.
        query_embedding = self._embed_question(question)

        # Step 2: Top-K retrieval from vector store
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

        # Step 3: Build the prompt with retrieved context
        prompt = self._build_prompt(question, retrieved_chunks)

        # Step 4: Generate the answer
        answer = self._generate_answer(prompt)

        # Step 5: Format sources for the response
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

    # ─── STEP 1: EMBED THE QUESTION ─────────────────────────────────

    def _embed_question(self, question: str) -> list[float]:
        """
        Convert the question string into the same vector space as our chunks.
        
        This is a single encode() call — no batching needed for one string.
        Returns a list[float] of length 384 (for all-MiniLM-L6-v2).
        """
        model = self._get_embedding_model()
        return model.encode(question).tolist()

    # ─── STEP 2: TOP-K RETRIEVAL (DSA: Vector Search) ────────────────

    def _retrieve_top_k(
        self,
        query_embedding: list[float],
        top_k: int,
        document_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """
        DSA: Top-K nearest neighbor search using pgvector.
        
        The SQL query:
          SELECT ... 
          FROM chunk_embeddings ce
          JOIN chunks c ON c.id = ce.chunk_id
          JOIN documents d ON d.id = c.document_id
          WHERE 1 - (ce.embedding <=> :embedding) > :threshold
          ORDER BY ce.embedding <=> :embedding ASC
          LIMIT :top_k
        
        Breaking down the key parts:
        
        1. ce.embedding <=> :embedding
           The <=> operator computes COSINE DISTANCE between two vectors.
           Cosine distance = 1 - cosine_similarity.
           Result range: 0.0 (identical) to 2.0 (opposite).
        
        2. ORDER BY ... ASC
           Ascending order = smallest distance first = most similar first.
           This is why it's distance, not similarity — ORDER BY ASC is natural.
        
        3. 1 - (ce.embedding <=> :embedding) > :threshold
           Convert distance back to similarity for the threshold filter.
           This removes chunks that are too dissimilar to be useful context.
        
        4. LIMIT :top_k
           Only return the K most similar chunks. With HNSW index,
           pgvector uses the index to avoid scanning all vectors —
           it navigates the HNSW graph to find approximate top-K
           in O(log n) time.
        
        Why raw SQL (text()) instead of ORM?
        SQLAlchemy's ORM doesn't have built-in support for pgvector's <=>
        operator. You could register custom operators, but text() is clearer
        for learning. The bind parameter (:embedding) prevents SQL injection.
        """
        # Build the query string.
        # str(query_embedding) converts [0.1, 0.2, ...] to the string
        # "[0.1, 0.2, ...]" which pgvector accepts as vector literal input.
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

        # Optional: filter by specific documents.
        # This lets the user ask questions about only their uploaded docs,
        # not the entire knowledge base.
        if document_ids:
            # Convert list to a format Postgres can use with IN clause
            placeholders = ", ".join(f":doc_id_{i}" for i in range(len(document_ids)))
            query += f" AND c.document_id IN ({placeholders})"

        query += """
            ORDER BY ce.embedding <=> :embedding ASC
            LIMIT :top_k
        """

        # SQLAlchemy's default Postgres Enum stores member NAMES (READY),
        # not values (ready). Raw SQL must match the DB label.
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

        # Convert rows to dicts.
        # Each row is a SQLAlchemy Row object — ._ fields gives named access.
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

    # ─── STEP 3: BUILD THE PROMPT ────────────────────────────────────

    def _build_prompt(
        self, question: str, chunks: list[dict[str, Any]]
    ) -> str:
        """
        Construct the prompt that the LLM will process.
        
        The prompt has three parts:
        1. System instruction: tells the model to answer from context only
        2. Context: the retrieved chunks, numbered for source attribution
        3. Question: the user's original question
        
        This is the simplest possible RAG prompt. Stage 14 will add:
        - Token budget management (truncate context if too long)
        - Source citation instructions
        - Few-shot examples
        
        BART has a 1024-token input limit. If your chunks exceed this,
        the model silently truncates. For Stage 13, we just concatenate
        and hope for the best. Stage 14 fixes this properly.
        """
        context_parts = []
        for i, chunk in enumerate(chunks, 1):
            source_label = f"[Source {i}: {chunk['document_title']}]"
            context_parts.append(f"{source_label}\n{chunk['text']}")

        context = "\n\n".join(context_parts)

        # BART doesn't follow instructions well (it's a seq2seq model,
        # not an instruction-tuned chat model). But this prompt structure
        # is the standard RAG template you'd use with GPT-4 or Claude.
        prompt = (
            f"Use the following context to answer the question. "
            f"If the context doesn't contain the answer, say so.\n\n"
            f"Context:\n{context}\n\n"
            f"Question: {question}\n\n"
            f"Answer:"
        )

        return prompt

    # ─── STEP 4: GENERATE ANSWER ─────────────────────────────────────

    def _generate_answer(self, prompt: str) -> str:
        """
        Run the prompt through the summarization model.
        
        The model treats the entire prompt as "text to summarize" and
        produces a condensed version. This isn't true Q&A — it's a hack
        that works ~okay because the context + question together form a
        passage that the model compresses into an "answer-like" summary.
        
        For real Q&A, you'd call an API like:
            openai.chat.completions.create(
                model="gpt-4",
                messages=[{"role": "user", "content": prompt}]
            )
        """
        pipe = self._get_summarization_pipeline()

        # BART's max input is 1024 tokens. Truncate if necessary.
        # The pipeline handles tokenization internally, but we do a
        # rough word-level check to avoid feeding it 50,000 words.
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