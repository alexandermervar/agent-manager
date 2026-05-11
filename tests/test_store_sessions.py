import pytest
from agent_manager.store import Store
from agent_manager.models import Session, SessionMessage


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "test.db")


def test_create_and_get_session(store):
    session = Session()
    store.create_session(session)
    retrieved = store.get_session(session.id)
    assert retrieved is not None
    assert retrieved.id == session.id
    assert retrieved.status == "briefing"
    assert retrieved.silent_mode is False


def test_list_sessions(store):
    for i in range(3):
        s = Session(title=f"Session {i}")
        store.create_session(s)
    sessions = store.list_sessions()
    assert len(sessions) == 3


def test_update_session(store):
    session = Session()
    store.create_session(session)
    store.update_session(session.id, status="selecting")
    updated = store.get_session(session.id)
    assert updated.status == "selecting"


def test_add_and_get_messages(store):
    session = Session()
    store.create_session(session)
    msg = SessionMessage(
        session_id=session.id, role="user", stage="brief", content="hello", seq=0
    )
    store.add_message(msg)
    messages = store.get_messages(session.id)
    assert len(messages) == 1
    assert messages[0].content == "hello"
    assert messages[0].role == "user"


def test_messages_ordered_by_seq(store):
    session = Session()
    store.create_session(session)
    for i in range(3):
        store.add_message(SessionMessage(
            session_id=session.id, role="user", stage="brief",
            content=f"msg {i}", seq=i
        ))
    msgs = store.get_messages(session.id)
    assert [m.seq for m in msgs] == [0, 1, 2]


def test_next_seq_empty(store):
    session = Session()
    store.create_session(session)
    assert store.next_seq(session.id) == 0


def test_next_seq_increments(store):
    session = Session()
    store.create_session(session)
    store.add_message(SessionMessage(
        session_id=session.id, role="user", stage="brief", content="a", seq=0
    ))
    store.add_message(SessionMessage(
        session_id=session.id, role="secretary", stage="brief", content="b", seq=1
    ))
    assert store.next_seq(session.id) == 2


def test_update_session_rejects_unknown_field(store):
    session = Session()
    store.create_session(session)
    with pytest.raises(ValueError, match="Invalid session field"):
        store.update_session(session.id, injected_field="bad")
