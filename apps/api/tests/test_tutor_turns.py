"""Phase 3: the tutor-turn routes keep a thread's messages in order and share one rate-limit window (spec 7.13).

C12 a thread's messages are timezone-aware UTC and strictly ordered, also under concurrency on PostgreSQL.
H5  POST /tutor/turns and POST /assistant/chat share one rate-limit window.
Each test fails if its defect comes back; the spec's review history (18.4) names the round behind each group.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import threading
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.api.routes import assistant as assistant_route
from app.core.auth import AuthUser
from app.core.config import Settings
from app.core.db import Base, SessionLocal
from app.core.db import engine as session_engine
from app.core.schema_upgrades import run_schema_upgrades
from app.db_models import TutorMessage, TutorTurn
from app.main import app
from app.schemas import AssistantChatRequest
from app.services import tutor_orchestrator as orchestrator_module
from app.services.retrieval_engine import RetrievalEngine
from app.services.store import get_course_store
from app.services.teaching_assistant import TeachingAssistantService
from app.services.tutor_orchestrator import TutorOrchestrator


IN_DOMAIN = "Why does routing depth matter?"
client = TestClient(app)
API_ROOT = Path(__file__).resolve().parents[1]


def demo(prefix: str, role: str = "learner") -> dict[str, str]:
    return {"x-demo-user": f"{prefix}-{uuid4().hex[:12]}", "x-demo-role": role, "x-forwarded-for": f"hardening-{uuid4().hex}"}


def fresh(headers: dict[str, str]) -> dict[str, str]:
    # A distinct client address per request keeps the per-address limits apart.
    return {**headers, "x-forwarded-for": f"hardening-{uuid4().hex}"}


def fresh_sessions(database_url: str):
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args)
    Base.metadata.create_all(engine)
    run_schema_upgrades(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False), engine


# ============================================================================================================== C12


def _thread_messages(factory, thread_id: str) -> list[TutorMessage]:
    with factory() as db:
        return list(db.scalars(select(TutorMessage).where(TutorMessage.thread_id == thread_id).order_by(TutorMessage.created_at, TutorMessage.id)))


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _assert_strict_pairs(messages: list[TutorMessage], turns: int, dialect: str) -> None:
    assert [message.role for message in messages] == ["user", "assistant"] * turns
    times = [_as_utc(message.created_at) for message in messages]
    assert all(earlier < later for earlier, later in zip(times, times[1:]))
    assert all(times[index + 1] - times[index] == timedelta(microseconds=1) for index in range(0, len(times), 2))
    if dialect == "postgresql":
        # timestamptz comes back aware, in the session's time zone (not UTC on every cluster): the instants compare.
        assert all(message.created_at.tzinfo is not None for message in messages)


def test_c12_messages_stay_strictly_ordered_when_the_clock_stalls_or_goes_back(monkeypatch):
    base = datetime.now(UTC).replace(microsecond=0)
    clock = iter([base, base, base - timedelta(seconds=5)])
    monkeypatch.setattr(orchestrator_module, "_utc_now", lambda: next(clock))
    headers = demo("order-clock")
    first = client.post("/assistant/chat", headers=fresh(headers), json={"message": IN_DOMAIN}).json()
    for question in ("Why does it matter?", "What about graph shrinking?"):
        assert client.post("/assistant/chat", headers=fresh(headers), json={"message": question, "thread_id": first["thread_id"]}).status_code == 200
    messages = _thread_messages(SessionLocal, first["thread_id"])
    _assert_strict_pairs(messages, 3, session_engine.dialect.name)
    # The first turn took the clock's UTC instant; the later two, the thread's latest message plus 1 microsecond.
    assert [_as_utc(message.created_at) - base for message in messages] == [timedelta(microseconds=n) for n in range(6)]
    detail = client.get(f"/assistant/threads/{first['thread_id']}", headers=fresh(headers)).json()
    assert [message["id"] for message in detail["messages"]] == [message.id for message in messages]
    assert [message["role"] for message in detail["messages"]] == ["user", "assistant"] * 3


def test_c12_concurrent_turns_of_one_thread_keep_a_strict_order_on_postgresql(fresh_database_url, monkeypatch):
    factory, engine = fresh_sessions(fresh_database_url)
    settings = Settings(two_pass_tutor="off", tutor_ledger_enabled=False)
    orchestrator = TutorOrchestrator(TeachingAssistantService(RetrievalEngine(get_course_store(), settings), settings), settings)
    user = AuthUser(user_id=f"order-{uuid4().hex[:12]}", email=None, role="learner", provider="demo")
    stalled = datetime.now(UTC)
    monkeypatch.setattr(orchestrator_module, "_utc_now", lambda: stalled)  # every turn asks for the same instant
    try:
        with factory() as db:
            thread_id = orchestrator.create_thread(db, user, "order").id
            db.commit()
        turns = 6
        errors: list[BaseException] = []

        def worker(index: int) -> None:
            try:
                with factory() as db:
                    orchestrator.chat(db, user, AssistantChatRequest(message=f"{IN_DOMAIN} ({index})", thread_id=thread_id))
                    db.commit()
            except BaseException as exc:  # noqa: BLE001 - reported below
                errors.append(exc)

        if engine.dialect.name == "postgresql":
            barrier = threading.Barrier(turns)
            workers = [threading.Thread(target=lambda index=index: (barrier.wait(), worker(index))) for index in range(turns)]
            for thread in workers:
                thread.start()
            for thread in workers:
                thread.join(120)
        else:  # SQLite (development and tests) serialises writers; the order rule is the same, one turn after another
            for index in range(turns):
                worker(index)
        assert errors == []
        messages = _thread_messages(factory, thread_id)
        _assert_strict_pairs(messages, turns, engine.dialect.name)
        with factory() as db:
            turn_times = sorted(_as_utc(turn.created_at) for turn in db.scalars(select(TutorTurn).where(TutorTurn.thread_id == thread_id)))
        assert turn_times == [_as_utc(message.created_at) for message in messages if message.role == "user"]
    finally:
        engine.dispose()


# =============================================================================================================== H5


def test_h5_the_two_tutor_turn_paths_share_one_rate_limit_window(monkeypatch):
    limited = Settings(assistant_chat_rate_limit="2/minute")
    monkeypatch.setattr(assistant_route, "get_settings", lambda: limited)
    client = TestClient(app)
    user = {"x-demo-user": f"h5-{uuid4().hex[:12]}", "x-demo-role": "learner"}

    def send(path: str) -> int:
        return client.post(path, headers={**user, "x-forwarded-for": f"h5-{uuid4().hex}"}, json={"message": "Why does routing depth matter?"}).status_code

    assert [send("/assistant/chat"), send("/tutor/turns")] == [200, 200]
    # The budget is spent whichever path asks next: alternating the two no longer doubles it.
    assert [send("/assistant/chat"), send("/tutor/turns")] == [429, 429]
    other = {"x-demo-user": f"h5-{uuid4().hex[:12]}", "x-demo-role": "learner", "x-forwarded-for": f"h5-{uuid4().hex}"}
    assert client.post("/tutor/turns", headers=other, json={"message": "Why does routing depth matter?"}).status_code == 200
    assert not hasattr(Settings(), "tutor_turns_rate_limit")
    for module in ("assistant", "tutor"):
        source = (API_ROOT / "app" / "api" / "routes" / f"{module}.py").read_text(encoding="utf-8")
        assert "@limiter.shared_limit(tutor_turn_rate_limit, scope=TUTOR_TURN_RATE_LIMIT_SCOPE)" in source
        assert "@limiter.limit(" not in source
