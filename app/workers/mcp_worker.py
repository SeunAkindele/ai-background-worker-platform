"""MCP tool-call worker for external web search and third-party integrations."""
from __future__ import annotations

import logging
from typing import Any

from app.config import settings
from app.core.mcp_client import McpClient, McpClientError
from app.core.rag_metrics import RAGTrace, trace_stage
from app.workers.base import BaseJobHandler

logger = logging.getLogger(__name__)


class McpToolCallHandler(BaseJobHandler[dict[str, Any], dict[str, Any]]):
    """Invokes a configured MCP tool and returns normalized result snippets."""

    def validate_input(self, input_payload: dict[str, Any]) -> None:
        if not input_payload.get("question") and not input_payload.get("arguments"):
            raise ValueError("MCP tool call needs 'question' or 'arguments'")

    def process(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        question = input_payload.get("question", "")
        tool_name = input_payload.get("tool_name", "web_search")
        mcp_url = input_payload.get("mcp_url") or settings.mcp_web_url
        arguments = input_payload.get("arguments") or {"query": question}

        trace = RAGTrace(question=question or str(arguments))
        client = McpClient(mcp_url)

        with trace_stage(trace, "mcp_list_tools") as st:
            try:
                tools = client.list_tools()
                st.meta["tool_count"] = len(tools)
                st.meta["tool_names"] = [t.get("name") for t in tools][:20]
            except McpClientError as exc:
                st.meta["list_error"] = str(exc)
                tools = []

        with trace_stage(trace, "mcp_call") as st:
            st.meta["tool_name"] = tool_name
            try:
                raw = client.call_tool(tool_name, arguments)
                st.meta["ok"] = True
            except McpClientError as exc:
                logger.error("[mcp.worker] tool=%s failed: %s", tool_name, exc)
                return {
                    "question": question,
                    "answer": f"MCP tool '{tool_name}' failed: {exc}",
                    "sources": [],
                    "route": "web",
                    "chunks_retrieved": 0,
                    "observability": trace.to_dict(),
                }

        snippets = self._normalize_snippets(raw)
        answer = self._summarize_snippets(question, snippets)

        logger.info(
            "[mcp.worker] tool=%s snippets=%d answer_chars=%d",
            tool_name, len(snippets), len(answer),
        )
        return {
            "question": question,
            "answer": answer,
            "sources": snippets,
            "route": "web",
            "tool_name": tool_name,
            "chunks_retrieved": len(snippets),
            "observability": trace.to_dict(),
        }

    def format_result(self, raw_result: dict[str, Any]) -> dict[str, Any]:
        return raw_result

    def _normalize_snippets(self, raw: Any) -> list[dict[str, Any]]:
        """Normalize heterogeneous MCP payloads to a common source shape."""
        if isinstance(raw, dict) and isinstance(raw.get("hits"), list) and raw["hits"]:
            return self._normalize_snippets(raw["hits"])

        if isinstance(raw, dict) and "content" in raw:
            texts = [
                c.get("text", "")
                for c in raw["content"]
                if isinstance(c, dict) and c.get("type") == "text"
            ]
            return [{"title": "mcp", "url": None, "text_preview": t[:300]} for t in texts if t]

        if isinstance(raw, list):
            out = []
            for i, item in enumerate(raw):
                if isinstance(item, dict):
                    out.append({
                        "title": item.get("title") or f"result_{i}",
                        "url": item.get("url"),
                        "text_preview": (item.get("snippet") or item.get("text") or "")[:300],
                    })
            return out

        return [{"title": "mcp", "url": None, "text_preview": str(raw)[:300]}]

    def _summarize_snippets(self, question: str, snippets: list[dict[str, Any]]) -> str:
        if not snippets:
            return "No web results returned by MCP tool."
        joined = "\n".join(f"- {s.get('text_preview')}" for s in snippets[:5])
        return f"Based on web/MCP results for '{question}':\n{joined}"
