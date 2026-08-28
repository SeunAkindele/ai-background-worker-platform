from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.mcp_web_server import app, _call_tool, _web_search


client = TestClient(app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_tools_list():
    resp = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert resp.status_code == 200
    tools = resp.json()["result"]["tools"]
    names = [t["name"] for t in tools]
    assert "web_search" in names


def test_tools_call_web_search_uses_wikipedia():
    wiki = {
        "query": {
            "search": [
                {
                    "title": "Artificial intelligence",
                    "snippet": "<span class=\"searchmatch\">AI</span> is intelligence.",
                }
            ]
        }
    }
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = wiki

    with patch("app.mcp_web_server.httpx.Client") as mock_client_cls:
        mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_resp
        resp = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "web_search", "arguments": {"query": "AI news"}},
            },
        )

    body = resp.json()
    assert "error" not in body or body["error"] is None
    result = body["result"]
    assert result["hits"][0]["title"] == "Artificial intelligence"
    assert "AI is intelligence." in result["hits"][0]["snippet"]
    assert result["content"][0]["type"] == "text"


def test_web_search_empty_query():
    assert _web_search("") == []
    assert _web_search("   ") == []


def test_unknown_tool_raises():
    try:
        _call_tool("not_a_tool", {})
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "Unknown tool" in str(exc)


def test_unknown_method_is_rpc_error():
    resp = client.post("/mcp", json={"jsonrpc": "2.0", "id": 9, "method": "nope"})
    assert resp.json()["error"]["code"] == -32601


def test_sync_response_accepts_web_and_sql_sources():
    from app.schemas.document_schema import RAGQuerySyncResponse

    web = RAGQuerySyncResponse.model_validate({
        "question": "q",
        "answer": "a",
        "chunks_retrieved": 1,
        "route": "web",
        "sources": [{"title": "T", "url": "https://example.com", "text_preview": "hi"}],
    })
    assert web.sources[0].title == "T"
    assert web.sources[0].url == "https://example.com"

    sql = RAGQuerySyncResponse.model_validate({
        "question": "q",
        "answer": "Pending Jobs: 0",
        "chunks_retrieved": 0,
        "route": "sql",
        "sources": [{"source": "postgres.jobs", "label": "pending_jobs", "value": 0}],
    })
    assert sql.sources[0].model_extra["label"] == "pending_jobs"
