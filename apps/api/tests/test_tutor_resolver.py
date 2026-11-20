"""Resolver thread-resolver-v1 (plan task 3.1; AC-3-5; Phase 3 spec 4.2, 13.2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.core.config_package import get_config_package
from app.core.db import SessionLocal
from app.db_models import TutorMessage, TutorThread
from app.services.tutor_pipeline.resolve import (
    RESOLVER_ID,
    LearnerTurn,
    ResolverInputError,
    resolve_thread,
    resolve_turns,
    resolver_prompt_hash,
)

PACKAGE = get_config_package(Settings())


def _turn(text: str) -> LearnerTurn:
    return LearnerTurn(f"message-{uuid4()}", text)


@pytest.mark.parametrize(
    ("current", "follow_up"),
    [
        ("How does QUBO routing work under noise?", False),  # eight words, three content terms: standalone
        ("What is QUBO optimization in logistics?", False),
        ("Why?", True),  # no content term
        ("Why does it matter?", True),  # one content term
        ("And for finance?", True),  # a continuation cue
        ("what about quantum kernels for finance", True),
        ("Explain routing depth under hardware constraints", False),
    ],
)
def test_the_follow_up_rule_is_content_terms_and_cues_not_a_word_count(current, follow_up):
    anchor = _turn("What is QUBO optimization in logistics?")
    resolved = resolve_turns([anchor], _turn(current), package=PACKAGE)
    if follow_up:
        assert resolved.text == f"{anchor.text}\n{' '.join(current.split())}"
        assert resolved.source_turn_ids[0] == anchor.message_id and len(resolved.source_turn_ids) == 2
    else:
        assert resolved.text == current and len(resolved.source_turn_ids) == 1
    assert resolved.contains_learner_state is False and resolved.resolver.model_id == RESOLVER_ID


def test_the_anchor_is_the_most_recent_eligible_turn_within_the_lookback():
    eligible = _turn("Explain routing depth under hardware constraints")
    fillers = [_turn("Why?"), _turn("ok"), _turn("and?"), _turn("hmm")]
    assert resolve_turns([eligible, *fillers], _turn("Why?"), package=PACKAGE).source_turn_ids[0] != eligible.message_id
    within = resolve_turns([eligible, *fillers[:3]], _turn("Why?"), package=PACKAGE)
    assert within.source_turn_ids[0] == eligible.message_id
    newer = _turn("What is QUBO optimization in logistics?")
    assert resolve_turns([eligible, newer], _turn("Why?"), package=PACKAGE).source_turn_ids[0] == newer.message_id
    # No anchor among the last four user turns: the question stands alone.
    alone = resolve_turns(fillers, _turn("Why?"), package=PACKAGE)
    assert alone.text == "Why?" and len(alone.source_turn_ids) == 1


def test_the_resolver_is_deterministic_and_its_prompt_hash_is_pinned():
    prior = [_turn("What is QUBO optimization in logistics?")]
    current = _turn("Why does it matter?")
    assert resolve_turns(prior, current, package=PACKAGE) == resolve_turns(prior, current, package=PACKAGE)
    assert resolver_prompt_hash(PACKAGE.tutor_pipeline, PACKAGE.retrieval) == PACKAGE.tutor_pipeline.resolver_prompt_hash


def _thread(db, user: str) -> TutorThread:
    thread = TutorThread(id=f"thread-{uuid4()}", user_id=user, title="t")
    db.add(thread)
    db.flush()
    return thread


def test_resolve_thread_orders_by_time_then_id_and_reads_only_user_turns():
    user = f"resolver-{uuid4().hex[:8]}"
    now = datetime.now(UTC)
    with SessionLocal() as db:
        thread = _thread(db, user)
        anchor = TutorMessage(id=f"message-{uuid4()}", thread_id=thread.id, role="user", content="What is QUBO optimization in logistics?",
                              created_at=now)
        reply = TutorMessage(id=f"message-{uuid4()}", thread_id=thread.id, role="assistant",
                             content="Explain routing depth under hardware constraints", created_at=now + timedelta(microseconds=1))
        current = TutorMessage(id=f"message-{uuid4()}", thread_id=thread.id, role="user", content="Why does it matter?",
                               created_at=now + timedelta(microseconds=2))
        later = TutorMessage(id=f"message-{uuid4()}", thread_id=thread.id, role="user", content="Explain quantum kernels for finance",
                             created_at=now + timedelta(seconds=5))
        db.add_all([anchor, reply, current, later])
        db.commit()
        resolved = resolve_thread(db, thread.id, current.id, package=PACKAGE)
        assert resolved.source_turn_ids == (anchor.id, current.id)  # never the assistant reply, never a later turn
        assert resolved.text == "What is QUBO optimization in logistics?\nWhy does it matter?"
        with pytest.raises(ResolverInputError):
            resolve_thread(db, thread.id, reply.id, package=PACKAGE)  # an assistant message is not a learner turn
        other = _thread(db, user)
        db.commit()
        with pytest.raises(ResolverInputError):
            resolve_thread(db, other.id, current.id, package=PACKAGE)  # a message of another thread


def test_resolve_thread_handles_whole_second_legacy_rows_and_equal_times():
    user = f"resolver-{uuid4().hex[:8]}"
    with SessionLocal() as db:
        thread = _thread(db, user)
        # A legacy row written with the database clock (whole seconds on SQLite), then two rows with one time.
        legacy = TutorMessage(id=f"message-0-{uuid4()}", thread_id=thread.id, role="user", content="Explain routing depth under hardware constraints")
        db.add(legacy)
        db.commit()
        now = datetime.now(UTC) + timedelta(seconds=2)
        tie = uuid4().hex[:8]  # equal times: the id orders them, so "a" precedes "b"
        first = TutorMessage(id=f"message-a-{tie}", thread_id=thread.id, role="user", content="ok", created_at=now)
        current = TutorMessage(id=f"message-b-{tie}", thread_id=thread.id, role="user", content="Why?", created_at=now)
        db.add_all([first, current])
        db.commit()
        resolved = resolve_thread(db, thread.id, current.id, package=PACKAGE)
        assert resolved.source_turn_ids == (legacy.id, current.id)
        assert current.id not in resolved.text.split("\n")[0]
