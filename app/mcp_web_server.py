"""HTTP MCP server exposing a web_search tool for the RAG web route."""
from __future__ import annotations

import html
import logging
import re
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import FastAPI, Request

logger = logging.getLogger("mcp.web")

app = FastAPI(title="MCP Web Search", version="0.15.0")

WIKI_API = "https://en.wikipedia.org/w/api.php"
USER_AGENT = "ai-background-worker-platform/0.15 (educational; web_search MCP)"


def _rpc_result(rpc_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rpc_id, "result": result}


def _rpc_error(rpc_id: Any, message: str, code: int = -32000) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}}


def _list_tools() -> dict[str, Any]:
    return {
        "tools": [
            {
                "name": "web_search",
                "description": "Search the public web (Wikipedia) and return title/url/snippet hits.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                    },
                    "required": ["query"],
                },
            }
        ]
    }


def _web_search(query: str, limit: int = 5) -> list[dict[str, str]]:
    """Search Wikipedia; no API key required."""
    q = (query or "").strip()
    if not q:
        return []

    params = {
        "action": "query",
        "list": "search",
        "srsearch": q,
        "srlimit": str(limit),
        "srprop": "snippet|timestamp",
        "format": "json",
    }
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    with httpx.Client(timeout=15.0, headers=headers, follow_redirects=True) as client:
        resp = client.get(WIKI_API, params=params)
        resp.raise_for_status()
        data = resp.json()

    hits: list[dict[str, str]] = []
    for row in (data.get("query") or {}).get("search") or []:
        title = row.get("title") or "Untitled"
        snippet = html.unescape(re.sub(r"<[^>]+>", "", row.get("snippet") or ""))
        hits.append({
            "title": title,
            "url": f"https://en.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}",
            "snippet": snippet,
        })
    return hits


def _call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name != "web_search":
        raise ValueError(f"Unknown tool: {name}")
    query = arguments.get("query") or arguments.get("q") or ""
    hits = _web_search(str(query))
    if not hits:
        text = f"No web results for {query!r}."
        return {"content": [{"type": "text", "text": text}]}

    lines = [f"{h['title']}: {h['snippet']} ({h['url']})" for h in hits]
    return {
        "content": [{"type": "text", "text": "\n".join(lines)}],
        "hits": hits,
    }


@app.post("/mcp")
async def mcp_endpoint(request: Request) -> dict[str, Any]:
    payload = await request.json()
    rpc_id = payload.get("id")
    method = payload.get("method")
    params = payload.get("params") or {}

    logger.info("[mcp.web] method=%s", method)
    try:
        if method == "tools/list":
            return _rpc_result(rpc_id, _list_tools())
        if method == "tools/call":
            name = params.get("name") or ""
            arguments = params.get("arguments") or {}
            return _rpc_result(rpc_id, _call_tool(name, arguments))
        return _rpc_error(rpc_id, f"Unknown method: {method}", code=-32601)
    except Exception as exc:
        logger.exception("[mcp.web] method=%s failed", method)
        return _rpc_error(rpc_id, str(exc))


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
