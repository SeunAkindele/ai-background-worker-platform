"""Standalone handlers for RAG chain step job types (retrieve / generate)."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from app.workers.base import BaseJobHandler
from app.workers.rag_query_worker import RAGQueryHandler


def _json_safe_chunks(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    safe: list[dict[str, Any]] = []
    for c in chunks:
        item = dict(c)
        for key in ("chunk_id", "document_id", "parent_chunk_id", "child_chunk_id"):
            if key in item and item[key] is not None:
                item[key] = str(item[key])
        safe.append(item)
    return safe


class RagRetrieveHandler(BaseJobHandler[dict[str, Any], dict[str, Any]]):
    """Retrieve and merge/dedupe hits for one or more query strings."""

    def __init__(self) -> None:
        self._rag = RAGQueryHandler()

    def validate_input(self, input_payload: dict[str, Any]) -> None:
        queries = input_payload.get("queries")
        question = input_payload.get("question")
        if queries is not None:
            if not isinstance(queries, list) or not queries:
                raise ValueError("'queries' must be a non-empty list of strings")
            if not all(isinstance(q, str) and q.strip() for q in queries):
                raise ValueError("each query in 'queries' must be a non-empty string")
        elif not question or not isinstance(question, str) or not question.strip():
            raise ValueError("rag_retrieve requires 'queries' or a non-empty 'question'")

        doc_ids = input_payload.get("document_ids")
        if doc_ids is not None:
            if not isinstance(doc_ids, list):
                raise ValueError("'document_ids' must be a list of UUID strings")
            for did in doc_ids:
                try:
                    UUID(str(did))
                except ValueError as exc:
                    raise ValueError(f"Invalid document_id: {did}") from exc

    def process(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        queries = input_payload.get("queries")
        if not queries:
            queries = [input_payload["question"].strip()]

        question = input_payload.get("question") or queries[0]
        retrieve_k = input_payload.get("retrieve_k")
        if retrieve_k is None:
            retrieve_k = input_payload.get("top_k")
        if retrieve_k is None:
            retrieve_k = 50
        retrieve_k = int(retrieve_k)
        document_ids = input_payload.get("document_ids")
        metadata_filter = input_payload.get("metadata_filter")

        per_query_hits: list[list[dict[str, Any]]] = []
        for q in queries:
            emb = self._rag._embed_question(q)
            hits = self._rag._retrieve_top_k(
                emb,
                top_k=retrieve_k,
                document_ids=document_ids,
                metadata_filter=metadata_filter,
            )
            per_query_hits.append(hits)

        merged = self._rag.merge_and_dedupe(per_query_hits)
        pool = _json_safe_chunks(merged[:retrieve_k])

        return {
            "question": question,
            "queries": queries,
            "candidates": pool,
            "retrieve_k": retrieve_k,
            "candidates_count": len(pool),
        }

    def format_result(self, raw_result: dict[str, Any]) -> dict[str, Any]:
        return raw_result


class RagGenerateHandler(BaseJobHandler[dict[str, Any], dict[str, Any]]):
    """Optional small-to-big expansion, prompt construction, and answer generation."""

    def __init__(self) -> None:
        self._rag = RAGQueryHandler()

    def validate_input(self, input_payload: dict[str, Any]) -> None:
        question = input_payload.get("question")
        if not question or not isinstance(question, str) or not question.strip():
            raise ValueError("rag_generate requires a non-empty 'question'")

        selected = input_payload.get("selected")
        candidates = input_payload.get("candidates")
        chunks = selected if selected is not None else candidates
        if not isinstance(chunks, list):
            raise ValueError("rag_generate requires 'selected' or 'candidates' list")

    def process(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        question = input_payload["question"]
        selected = input_payload.get("selected")
        if selected is None:
            selected = input_payload.get("candidates") or []
        use_s2b = input_payload.get("use_small_to_big", True)

        if not selected:
            return {
                "question": question,
                "answer": "No relevant documents found to answer this question.",
                "sources": [],
                "chunks_retrieved": 0,
                "queries_used": input_payload.get("queries", []),
            }

        context_chunks = (
            self._rag._expand_to_parents(selected) if use_s2b else selected
        )
        context_chunks = _json_safe_chunks(context_chunks)
        prompt = self._rag._build_prompt(question, context_chunks)
        answer = self._rag._generate_answer(prompt)

        sources = [
            {
                "chunk_id": str(c["chunk_id"]),
                "document_id": str(c["document_id"]),
                "document_title": c.get("document_title"),
                "chunk_index": c.get("chunk_index"),
                "similarity": round(float(c.get("similarity", 0.0)), 4),
                "text_preview": (
                    c["text"][:200] + "..."
                    if len(c.get("text", "")) > 200
                    else c.get("text", "")
                ),
                "expanded_from_child": c.get("expanded_from_child", False),
            }
            for c in context_chunks
        ]

        return {
            "question": question,
            "answer": answer,
            "sources": sources,
            "chunks_retrieved": len(context_chunks),
            "queries_used": input_payload.get("queries", []),
            "model": self._rag._embedding_model_name,
        }

    def format_result(self, raw_result: dict[str, Any]) -> dict[str, Any]:
        return raw_result
