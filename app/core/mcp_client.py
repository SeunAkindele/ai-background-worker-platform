"""JSON-RPC MCP client for HTTP-based tool servers."""
from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger("mcp.client")


class McpClientError(RuntimeError):
    pass


class McpClient:
    """Calls MCP tools/list and tools/call over HTTP with bounded timeouts."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_s: float = 20.0,
        headers: dict[str, str] | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.headers = headers or {"Content-Type": "application/json"}

    def _rpc(self, method: str, params: dict[str, Any] | None = None) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params or {},
        }
        logger.info("[mcp] → %s params_keys=%s", method, list((params or {}).keys()))
        try:
            with httpx.Client(timeout=self.timeout_s, headers=self.headers) as client:
                resp = client.post(self.base_url, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.exception("[mcp] transport failure method=%s", method)
            raise McpClientError(str(exc)) from exc

        if "error" in data and data["error"]:
            logger.error("[mcp] rpc error method=%s error=%s", method, data["error"])
            raise McpClientError(str(data["error"]))

        logger.info("[mcp] ← %s ok", method)
        return data.get("result")

    def list_tools(self) -> list[dict[str, Any]]:
        result = self._rpc("tools/list")
        return (result or {}).get("tools") or []

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        return self._rpc("tools/call", {"name": name, "arguments": arguments})
