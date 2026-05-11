import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from agent_manager.secretary import Secretary
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
def session(store):
    s = Session()
    store.create_session(s)
    return s


def _mock_response(text):
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    msg.usage = MagicMock(input_tokens=10, output_tokens=20)
    return msg


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.messages = MagicMock()
    return client


@pytest.mark.asyncio
async def test_evaluate_brief_insufficient(store, session, mock_client, tmp_agents_dir):
    mock_client.messages.create = AsyncMock(return_value=_mock_response(
        json.dumps({"sufficient": False, "question": "What is your monthly income?"})
    ))
    sec = Secretary(mock_client, str(tmp_agents_dir), store)
    result = await sec.evaluate_brief(session.id, "I need help with money")
    assert result["sufficient"] is False
    assert "question" in result
    msgs = store.get_messages(session.id)
    assert len(msgs) == 2  # user message + secretary question


@pytest.mark.asyncio
async def test_evaluate_brief_sufficient(store, session, mock_client, tmp_agents_dir):
    mock_client.messages.create = AsyncMock(return_value=_mock_response(
        json.dumps({"sufficient": True, "summary": "User wants help budgeting $5k/month"})
    ))
    sec = Secretary(mock_client, str(tmp_agents_dir), store)
    result = await sec.evaluate_brief(session.id, "I earn $5000/month and want to save more")
    assert result["sufficient"] is True
    assert "summary" in result
    msgs = store.get_messages(session.id)
    assert len(msgs) == 1  # only the user message (no secretary follow-up)


@pytest.mark.asyncio
async def test_run_council_yields_required_event_types(
    store, session, mock_client, tmp_agents_dir
):
    responses = [
        # select call
        json.dumps({"selected": ["finance"], "rationale": "Financial question.", "create": []}),
        # agent run (run_agent calls messages.create internally)
        "Finance advisor response.",
        # synthesis call
        "Here is the Secretary's synthesis.",
    ]
    idx = 0

    async def side_effect(**kwargs):
        nonlocal idx
        r = _mock_response(responses[idx % len(responses)])
        idx += 1
        return r

    mock_client.messages.create = side_effect

    sec = Secretary(mock_client, str(tmp_agents_dir), store)
    events = []
    async for event in sec.run_council(session.id, "Help me budget $5k/month"):
        events.append(event)

    types = {e["type"] for e in events}
    assert "council_selected" in types
    assert "agent_start" in types
    assert "agent_complete" in types
    assert "synthesis" in types
    assert "session_complete" in types


@pytest.mark.asyncio
async def test_run_council_silent_mode_omits_response_content(
    store, session, mock_client, tmp_agents_dir
):
    responses = [
        json.dumps({"selected": ["finance"], "rationale": "Financial.", "create": []}),
        "Finance advisor response.",
        "Secretary synthesis.",
    ]
    idx = 0

    async def side_effect(**kwargs):
        nonlocal idx
        r = _mock_response(responses[idx % len(responses)])
        idx += 1
        return r

    mock_client.messages.create = side_effect

    sec = Secretary(mock_client, str(tmp_agents_dir), store)
    events = []
    async for event in sec.run_council(session.id, "Budget help", silent_mode=True):
        events.append(event)

    agent_complete_events = [e for e in events if e["type"] == "agent_complete"]
    for e in agent_complete_events:
        assert "response" not in e


@pytest.mark.asyncio
async def test_session_status_transitions_to_complete(store, session, mock_client, tmp_agents_dir):
    responses = [
        json.dumps({"selected": ["finance"], "rationale": "Finance.", "create": []}),
        "Agent response.",
        "Synthesis.",
    ]
    idx = 0

    async def side_effect(**kwargs):
        nonlocal idx
        r = _mock_response(responses[idx % len(responses)])
        idx += 1
        return r

    mock_client.messages.create = side_effect

    sec = Secretary(mock_client, str(tmp_agents_dir), store)
    async for _ in sec.run_council(session.id, "Budget"):
        pass

    final = store.get_session(session.id)
    assert final.status == "complete"
    assert final.completed_at is not None
