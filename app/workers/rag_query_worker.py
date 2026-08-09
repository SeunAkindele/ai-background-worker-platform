"""RAG query worker: expand → retrieve → merge → rerank → small-to-big → generate."""
from typing import Any
from uuid import UUID

from sqlalchemy import text

from app.core.database import db_session
from app.models.document import DocumentStatus
from app.workers.base import BaseJobHandler

import logging

from app.core.rag_metrics import RAGTrace, trace_stage
from app.workers.query_expand_worker import QueryExpandHandler
from app.workers.rerank_worker import RerankHandler

logger = logging.getLogger(__name__)


class RAGQueryHandler(BaseJobHandler[dict[str, Any], dict[str, Any]]):
    """Answer a question via advanced RAG over ingested document chunks."""

    def __init__(
        self,
        embedding_model_name: str = "all-MiniLM-L6-v2",
        retrieve_k: int = 50,
        keep_top_n: int = 3,
        similarity_threshold: float = 0.2,
        num_query_variants: int = 3,
    ):
        self._embedding_model_name = embedding_model_name
        self._embedding_model = None
        self._retrieve_k = retrieve_k
        self._keep_top_n = keep_top_n
        self._similarity_threshold = similarity_threshold
        self._num_query_variants = num_query_variants
        self._summarization_pipeline = None
        self._expander = QueryExpandHandler()
        self._reranker = RerankHandler(keep_top_n=keep_top_n)

    def _get_embedding_model(self):
        if self._embedding_model is None:
            from sentence_transformers import SentenceTransformer
            self._embedding_model = SentenceTransformer(
                self._embedding_model_name, device="cpu"
            )
        return self._embedding_model

    def _get_summarization_pipeline(self):
        """Lazy-load the local BART summarization pipeline used for answer generation."""
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

        for key, lo, hi in (("retrieve_k", 1, 100), ("keep_top_n", 1, 10), ("top_k", 1, 50)):
            val = input_payload.get(key)
            if val is not None and (not isinstance(val, int) or val < lo or val > hi):
                raise ValueError(f"'{key}' must be an integer between {lo} and {hi}")

        doc_ids = input_payload.get("document_ids")
        if doc_ids is not None:
            if not isinstance(doc_ids, list):
                raise ValueError("'document_ids' must be a list of UUID strings")
            for did in doc_ids:
                try:
                    UUID(str(did))
                except ValueError:
                    raise ValueError(f"Invalid document_id: {did}")

        mf = input_payload.get("metadata_filter")
        if mf is not None and not isinstance(mf, dict):
            raise ValueError("'metadata_filter' must be an object")

    def process(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        """Run the full advanced RAG pipeline and return answer + observability."""
        question = input_payload["question"]
        # Explicit null should fall through like a missing key.
        retrieve_k = input_payload.get("retrieve_k")
        if retrieve_k is None:
            retrieve_k = input_payload.get("top_k")
        if retrieve_k is None:
            retrieve_k = self._retrieve_k
        retrieve_k = int(retrieve_k)

        keep_top_n = input_payload.get("keep_top_n")
        if keep_top_n is None:
            keep_top_n = self._keep_top_n
        keep_top_n = int(keep_top_n)
        document_ids = input_payload.get("document_ids")
        metadata_filter = input_payload.get("metadata_filter")
        use_expansion = input_payload.get("use_multi_query", True)
        use_rerank = input_payload.get("use_rerank", True)
        use_s2b = input_payload.get("use_small_to_big", True)

        trace = RAGTrace(question=question)

        with trace_stage(trace, "expand") as st:
            if use_expansion:
                exp = self._expander.run({
                    "question": question,
                    "num_queries": int(
                        input_payload.get("num_queries", self._num_query_variants)
                    ),
                })
                queries = exp["queries"]
            else:
                queries = [question]
            st.meta["queries"] = queries

        per_query_hits: list[list[dict[str, Any]]] = []
        with trace_stage(trace, "retrieve_multi") as st:
            for i, q in enumerate(queries):
                emb = self._embed_question(q)
                hits = self._retrieve_top_k(
                    emb,
                    top_k=retrieve_k,
                    document_ids=document_ids,
                    metadata_filter=metadata_filter,
                )
                per_query_hits.append(hits)
                logger.info(
                    "[rag.retrieve] q_index=%d hits=%d query=%r",
                    i, len(hits), q[:80],
                )
            st.meta["per_query_hit_counts"] = [len(h) for h in per_query_hits]

        with trace_stage(trace, "merge_dedupe") as st:
            merged = self.merge_and_dedupe(per_query_hits)
            pool = merged[:retrieve_k]
            st.meta.update({"merged": len(merged), "pool": len(pool)})
            trace.after_dedupe_k = len(pool)
            trace.retrieve_k = retrieve_k

        if not pool:
            return {
                "question": question,
                "answer": "No relevant documents found to answer this question.",
                "sources": [],
                "chunks_retrieved": 0,
                "queries_used": queries,
                "observability": trace.to_dict(),
            }

        trace.biencoder_top1_similarity = float(pool[0]["similarity"])

        with trace_stage(trace, "rerank") as st:
            if use_rerank:
                rr = self._reranker.run({
                    "question": question,
                    "candidates": pool,
                    "keep_top_n": keep_top_n,
                })
                selected = rr["reranked"]
                st.meta.update(rr["observability"])
                trace.rerank_changed_top1 = rr["observability"]["changed_top1"]
                trace.reranker_top1_score = selected[0]["rerank_score"]
            else:
                selected = pool[:keep_top_n]
            trace.after_rerank_k = len(selected)

        with trace_stage(trace, "small_to_big") as st:
            context_chunks = (
                self._expand_to_parents(selected) if use_s2b else selected
            )
            st.meta["context_chunks"] = len(context_chunks)

        with trace_stage(trace, "generate") as st:
            prompt = self._build_prompt(question, context_chunks)
            answer = self._generate_answer(prompt)
            st.meta["prompt_chars"] = len(prompt)

        sources = [
            {
                "chunk_id": str(c["chunk_id"]),
                "document_id": str(c["document_id"]),
                "document_title": c["document_title"],
                "chunk_index": c["chunk_index"],
                "similarity": round(float(c.get("similarity", 0.0)), 4),
                "rerank_score": (
                    round(float(c["rerank_score"]), 4) if "rerank_score" in c else None
                ),
                "text_preview": (
                    c["text"][:200] + "..." if len(c["text"]) > 200 else c["text"]
                ),
                "metadata": c.get("chunk_metadata"),
                "expanded_from_child": c.get("expanded_from_child", False),
            }
            for c in context_chunks
        ]

        logger.info(
            "[rag.done] answer_chars=%d sources=%d changed_top1=%s",
            len(answer),
            len(sources),
            trace.rerank_changed_top1,
        )

        return {
            "question": question,
            "answer": answer,
            "sources": sources,
            "chunks_retrieved": len(context_chunks),
            "retrieve_k": retrieve_k,
            "keep_top_n": keep_top_n,
            "queries_used": queries,
            "model": self._embedding_model_name,
            "observability": trace.to_dict(),
        }
        

    def _expand_to_parents(self, children: list[dict[str, Any]]) -> list[dict[str, Any]]:
        parent_ids = [
            str(c["parent_chunk_id"])
            for c in children
            if c.get("parent_chunk_id") is not None
        ]
        if not parent_ids:
            logger.warning("[rag.s2b] no parent_chunk_id on hits; using child text")
            return children

        placeholders = ", ".join(f":pid_{i}" for i in range(len(parent_ids)))
        sql = f"""
            SELECT id, document_id, content, chunk_index, token_count, metadata
            FROM chunks
            WHERE id IN ({placeholders}) AND level = 'parent'
        """
        params = {f"pid_{i}": pid for i, pid in enumerate(parent_ids)}

        with db_session() as db:
            rows = db.execute(text(sql), params).fetchall()

        by_id = {str(r.id): r for r in rows}

        seen: set[str] = set()
        expanded: list[dict[str, Any]] = []
        for child in children:
            pid = str(child.get("parent_chunk_id"))
            if pid in seen:
                continue
            parent = by_id.get(pid)
            if parent is None:
                expanded.append(child)
                continue
            seen.add(pid)
            expanded.append({
                **child,
                "text": parent.content,
                "child_chunk_id": child["chunk_id"],
                "chunk_id": parent.id,
                "chunk_index": parent.chunk_index,
                "token_count": parent.token_count,
                "expanded_from_child": True,
            })

        logger.info(
            "[rag.s2b] children_in=%d parents_out=%d",
            len(children),
            len(expanded),
        )
        return expanded


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
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """ANN search over child-chunk embeddings with optional metadata filters."""
        query = """
            SELECT
                c.id AS chunk_id,
                c.document_id,
                c.content AS chunk_text,
                c.chunk_index,
                c.token_count,
                c.metadata AS chunk_metadata,
                c.parent_chunk_id,
                d.title AS document_title,
                1 - (ce.embedding <=> :embedding) AS similarity
            FROM chunk_embeddings ce
            JOIN chunks c ON c.id = ce.chunk_id
            JOIN documents d ON d.id = c.document_id
            WHERE d.status = :doc_status
            AND c.level = 'child'
            AND 1 - (ce.embedding <=> :embedding) > :threshold
        """

        params: dict[str, Any] = {
            "embedding": str(query_embedding),
            "threshold": self._similarity_threshold,
            "top_k": top_k,
            "doc_status": DocumentStatus.READY.name,
        }

        if document_ids:
            placeholders = ", ".join(f":doc_id_{i}" for i in range(len(document_ids)))
            query += f" AND c.document_id IN ({placeholders})"
            for i, doc_id in enumerate(document_ids):
                params[f"doc_id_{i}"] = doc_id

        if metadata_filter:
            import json
            query += " AND c.metadata @> CAST(:metadata_filter AS jsonb)"
            params["metadata_filter"] = json.dumps(metadata_filter)

        query += """
            ORDER BY ce.embedding <=> :embedding ASC
            LIMIT :top_k
        """

        with db_session() as db:
            rows = db.execute(text(query), params).fetchall()

        return [
            {
                "chunk_id": row.chunk_id,
                "document_id": row.document_id,
                "text": row.chunk_text,
                "chunk_index": row.chunk_index,
                "token_count": row.token_count,
                "chunk_metadata": row.chunk_metadata,
                "parent_chunk_id": row.parent_chunk_id,
                "document_title": row.document_title,
                "similarity": float(row.similarity),
            }
            for row in rows
        ]

    @staticmethod
    def merge_and_dedupe(
        result_lists: list[list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        """Merge multi-query hits, keep max similarity per chunk_id, sort descending."""
        best: dict[str, dict[str, Any]] = {}
        for results in result_lists:
            for row in results:
                cid = str(row["chunk_id"])
                prev = best.get(cid)
                if prev is None or float(row["similarity"]) > float(prev["similarity"]):
                    best[cid] = dict(row)

        merged = sorted(
            best.values(),
            key=lambda r: float(r["similarity"]),
            reverse=True,
        )
        return merged

    def _build_prompt(self, question: str, chunks: list[dict[str, Any]]) -> str:
        """Pack ranked sources into a prompt within a rough word budget."""
        max_context_words = 700
        parts: list[str] = []
        used = 0
        for i, chunk in enumerate(chunks, 1):
            words = chunk["text"].split()
            if used >= max_context_words:
                break
            take = words[: max_context_words - used]
            used += len(take)
            meta = chunk.get("chunk_metadata") or {}
            label = (
                f"[Source {i}: {chunk['document_title']}"
                f" dept={meta.get('department')} page={meta.get('page')}]"
            )
            parts.append(f"{label}\n{' '.join(take)}")

        context = "\n\n".join(parts)
        return (
            "Use ONLY the following context to answer the question. "
            "If the answer is not in the context, say you don't know.\n\n"
            f"Context:\n{context}\n\n"
            f"Question: {question}\n\n"
            "Answer:"
        )

    def _generate_answer(self, prompt: str) -> str:
        """Generate an answer from the grounded prompt via the local summarization model."""
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
