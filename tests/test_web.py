import json
import pytest
from pathlib import Path
from httpx import AsyncClient, ASGITransport
from agent_manager.web.app import create_app
from agent_manager.store import Store
from agent_manager.models import Session


@pytest.fixture
def tmp_agents_dir(tmp_path):
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "finance.yaml").write_text(
        "name: finance\n"
        "description: Financial advisor\n"
        "system_prompt: You are a financial advisor.\n"
        "model: claude-opus-4-6\n"
        "max_tokens: 1024\n"
        "temperature: 1.0\n"
        "tags: [finance]\n"
    )
    return agents_dir


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "test.db")


@pytest.fixture
def app(store, tmp_agents_dir):
    return create_app(store=store, agents_dir=str(tmp_agents_dir))


@pytest.mark.asyncio
async def test_index_returns_200(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_create_session_redirects(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
    ) as client:
        resp = await client.post("/sessions", data={"message": "hello"})
    assert resp.status_code == 303
    assert "/sessions/" in resp.headers["location"]


@pytest.mark.asyncio
async def test_sessions_list_returns_200(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/sessions")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_session_detail_returns_200(app, store):
    session = Session()
    store.create_session(session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/sessions/{session.id}")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_session_detail_404(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/sessions/nonexistent-id")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_agents_page_returns_200(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/agents")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_create_agent_via_post(app, tmp_agents_dir):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
    ) as client:
        resp = await client.post("/agents", data={
            "name": "health",
            "description": "Health advisor",
            "system_prompt": "You are a health advisor.",
        })
    assert resp.status_code == 303
    assert (tmp_agents_dir / "health.yaml").exists()


@pytest.mark.asyncio
async def test_delete_agent(app, tmp_agents_dir):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete("/agents/finance")
    assert resp.status_code == 200
    assert not (tmp_agents_dir / "finance.yaml").exists()
    assert (tmp_agents_dir / "_archived" / "finance.yaml").exists()


@pytest.mark.asyncio
async def test_delete_nonexistent_agent_404(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete("/agents/nonexistent")
    assert resp.status_code == 404
