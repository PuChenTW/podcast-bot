import json

import pytest
from httpx import ASGITransport, AsyncClient

from core import database as db
from web.app import create_app
from web.mcp import MCP_TOOLS

_MCP_HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}


def _tool_names(app):
    from fastapi_mcp import FastApiMCP

    return {tool.name for tool in FastApiMCP(app, include_operations=MCP_TOOLS).tools}


async def _rpc(client, method, params=None, session_id=None):
    headers = dict(_MCP_HEADERS)
    if session_id:
        headers["mcp-session-id"] = session_id
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    response = await client.post("/mcp", json=body, headers=headers)
    payload = response.text
    for line in payload.splitlines():
        if line.startswith("data: "):
            payload = line[6:]
            break
    return response, json.loads(payload)


async def _setup(monkeypatch, transcript="Transcript body"):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("WEB_USER_TELEGRAM_ID", "9911")
    await db.init_db()
    user_id = await db.get_or_create_user(9911, chat_id=0)
    podcast_id = await db.get_or_create_podcast("http://mcp-test.com/feed.rss", "MCP Pod")
    await db.add_subscription(user_id, "MCP Pod", "http://mcp-test.com/feed.rss")
    await db.mark_episode_seen(user_id, podcast_id, "mcp-ep", title="MCP Episode", published_at="2024-05-01", transcript=transcript, description="Desc")
    return user_id, podcast_id, await db.get_episode_id(podcast_id, "mcp-ep")


def test_mcp_exposes_only_the_agent_workflow_tools():
    assert _tool_names(create_app()) == set(MCP_TOOLS)


def test_mcp_excludes_destructive_and_redundant_tools():
    names = _tool_names(create_app())
    # Destructive, or duplicates a better tool, or runs a second LLM the client already is.
    for excluded in ("delete_subscription", "download_episode_transcript", "chat_with_episode", "update_subscription_prompts", "update_subscription_delivery", "create_subscription_prompt_draft"):
        assert excluded not in names


@pytest.mark.asyncio
async def test_mcp_initialize_reports_instructions_not_version(pg_fresh_db, monkeypatch):
    await _setup(monkeypatch)
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
        _, payload = await _rpc(client, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}})
    result = payload["result"]
    assert result["serverInfo"]["version"] == "1.0.0"
    assert "fast path" in result["instructions"]


@pytest.mark.asyncio
async def test_mcp_tools_call_returns_cached_transcript(pg_fresh_db, monkeypatch):
    _, _, episode_id = await _setup(monkeypatch, transcript="Hello transcript")
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
        response, _ = await _rpc(client, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}})
        session_id = response.headers["mcp-session-id"]
        await client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers={**_MCP_HEADERS, "mcp-session-id": session_id})
        _, listed = await _rpc(client, "tools/list", session_id=session_id)
        assert {tool["name"] for tool in listed["result"]["tools"]} == set(MCP_TOOLS)
        _, called = await _rpc(client, "tools/call", {"name": "fetch_episode_transcript", "arguments": {"episode_id": episode_id}}, session_id=session_id)
    payload = json.loads(called["result"]["content"][0]["text"])
    assert payload["status"] == "ready"
    assert payload["content"] == "Hello transcript"
    assert payload["chars"] == len("Hello transcript")


@pytest.mark.asyncio
async def test_fetch_transcript_queues_job_when_missing(pg_fresh_db, monkeypatch):
    _, _, episode_id = await _setup(monkeypatch, transcript=None)
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
        response = await client.get(f"/api/v1/episodes/{episode_id}/transcript-text")
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "generating"
    assert body["content"] is None
    assert body["job_id"]


@pytest.mark.asyncio
async def test_fetch_transcript_is_idempotent_while_generating(pg_fresh_db, monkeypatch):
    _, _, episode_id = await _setup(monkeypatch, transcript=None)
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
        first = (await client.get(f"/api/v1/episodes/{episode_id}/transcript-text")).json()
        second = (await client.get(f"/api/v1/episodes/{episode_id}/transcript-text")).json()
    # Repeated agent polls must not pile up duplicate transcription jobs.
    assert first["job_id"] == second["job_id"]


@pytest.mark.asyncio
async def test_fetch_transcript_surfaces_a_failed_job(pg_fresh_db, monkeypatch):
    user_id, _, episode_id = await _setup(monkeypatch, transcript=None)
    job = await db.create_api_job(user_id, episode_id, "transcript", "/x")
    await db.claim_api_job("worker-1")
    await db.fail_api_job(job["id"], "worker-1", ("transcript_unavailable", "No audio"))
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
        body = (await client.get(f"/api/v1/episodes/{episode_id}/transcript-text")).json()
    # A permanently untranscribable episode must not look like it is still working.
    assert body["status"] == "failed"
    assert body["error_code"] == "transcript_unavailable"


@pytest.mark.asyncio
async def test_transcript_get_still_404s_for_the_frontend(pg_fresh_db, monkeypatch):
    user_id, _, episode_id = await _setup(monkeypatch, transcript=None)
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
        response = await client.get(f"/api/v1/episodes/{episode_id}/transcript")
    # The web UI drives its own regenerate button off this 404; it must not auto-queue.
    assert response.status_code == 404
    assert await db.get_latest_api_job(user_id, episode_id, "transcript") is None
