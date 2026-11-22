"""Phase 6 adjudication workflow (plan Phase 6 D task 3 "Workflow queued -> claimed -> adjudicated -> applied; ... 10%
double review"; plan 16.1 "the X6 auditor MUST NOT audit their own change [Risk R-35]"; Phase 6 spec 4.5, 13.2; PD-36).
Fresh in-memory databases; reviewers are synthetic ids."""

from __future__ import annotations

from datetime import timedelta
from fractions import Fraction
import threading

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings, get_settings
from app.core.config_package import get_config_package
from app.core.db import Base
from app.core.schema_upgrades import run_schema_upgrades
from app.db_models import V3Claim, V3GoldLabelRecord, V3QueueItem
from app.services.erasure import erase_user
from app.services.v3 import queue
from app.services.v3.contracts import ApplyRequest
from app.services.v3.draw import bernoulli
from app.services.v3.queue import V3Conflict
from app.services.v3.triggers import response_spec
import v3_fakes

PACKAGE = get_config_package(Settings(environment="development", v3_queue="shadow"))
NOW = v3_fakes.FIXED_NOW
A, B, C = "synthetic-reviewer-a", "synthetic-reviewer-b", "synthetic-reviewer-c"


@pytest.fixture
def seeded():
    with v3_fakes.fresh_v3_sessions() as (factory, _engine):
        entries = v3_fakes.reviewable_deliveries(3)
        ids = v3_fakes.seed_items(factory, entries, package=PACKAGE, now=NOW, double_review=False)
        yield factory, ids, v3_fakes.supported_labels(entries[0])


def _conflict(reason, call):
    with pytest.raises(V3Conflict) as raised:
        call()
    assert raised.value.reason == reason


def _state(factory, item_id, now):
    with factory() as db:
        return queue.workflow_state(db, queue.get_item(db, item_id), now=now)


def test_claimed_is_derived_from_a_live_lease_and_an_expired_lease_returns_the_item_to_queued(seeded):
    factory, ids, _ = seeded
    with factory() as db:
        lease = queue.claim_item(db, ids[0], user_id=A, now=NOW, package=PACKAGE)
        again = queue.claim_item(db, ids[0], user_id=A, now=NOW + timedelta(seconds=5), package=PACKAGE)
    assert lease == again and lease.lease_expires_at == NOW + timedelta(seconds=PACKAGE.v3.lease_s) and lease.review_round == 1
    assert _state(factory, ids[0], NOW + timedelta(seconds=10)) == "claimed"
    with factory() as db:
        assert queue.get_item(db, ids[0]).state == "queued"   # stored state: claimed is never written
        _conflict("claimed_by_another", lambda: queue.claim_item(db, ids[0], user_id=B, now=NOW + timedelta(seconds=10), package=PACKAGE))
    expired = NOW + timedelta(seconds=PACKAGE.v3.lease_s + 1)
    assert _state(factory, ids[0], expired) == "queued"
    with factory() as db:
        taken = queue.claim_item(db, ids[0], user_id=B, now=expired, package=PACKAGE)
        assert taken.lease_expires_at == expired + timedelta(seconds=PACKAGE.v3.lease_s)
        assert db.scalar(select(func.count()).select_from(V3Claim).where(V3Claim.item_id == ids[0])) == 1


def test_adjudication_needs_a_live_lease_and_labels_that_match_the_subject(seeded):
    factory, ids, request = seeded
    from app.services.v3.contracts import AdjudicationRequest

    with factory() as db:
        _conflict("not_claimed", lambda: queue.adjudicate(db, ids[0], request("key-0000a"), user_id=A, now=NOW, package=PACKAGE))
        queue.claim_item(db, ids[0], user_id=A, now=NOW, package=PACKAGE)
        _conflict("lease_expired", lambda: queue.adjudicate(db, ids[0], request("key-0000a"), user_id=A,
                                                            now=NOW + timedelta(seconds=PACKAGE.v3.lease_s), package=PACKAGE))
        _conflict("labels_do_not_match_subject", lambda: queue.adjudicate(db, ids[0], AdjudicationRequest(client_key="key-0000b"), user_id=A,
                                                                          now=NOW, package=PACKAGE))
        _conflict("labels_do_not_match_subject", lambda: queue.adjudicate(
            db, ids[0], AdjudicationRequest(client_key="key-0000c", claim_labels=request("x" * 8).claim_labels, abstention_label="correct"),
            user_id=A, now=NOW, package=PACKAGE))
        result = queue.adjudicate(db, ids[0], request("key-0000d"), user_id=A, now=NOW + timedelta(seconds=1), package=PACKAGE)
        assert (result.state, result.review_round, result.duplicate) == ("adjudicated", 1, False)
        _conflict("already_adjudicated", lambda: queue.claim_item(db, ids[0], user_id=B, now=NOW, package=PACKAGE))


def test_adjudicate_and_apply_are_idempotent_by_client_key(seeded, caplog):
    factory, ids, request = seeded
    caplog.set_level("INFO", logger="qcai.v3")
    with factory() as db:
        queue.claim_item(db, ids[0], user_id=A, now=NOW, package=PACKAGE)
        first = queue.adjudicate(db, ids[0], request("key-1111a"), user_id=A, now=NOW, package=PACKAGE)
        again = queue.adjudicate(db, ids[0], request("key-1111a"), user_id=A, now=NOW + timedelta(seconds=9), package=PACKAGE)
        assert (again.gold_seq, again.record_hash, again.duplicate) == (first.gold_seq, first.record_hash, True)
        _conflict("already_adjudicated", lambda: queue.adjudicate(db, ids[0], request("key-1111b"), user_id=A, now=NOW, package=PACKAGE))
        assert db.scalar(select(func.count()).select_from(V3GoldLabelRecord)) == 1
        final = queue.apply_item(db, ids[0], ApplyRequest(client_key="apply-0001"), user_id=B, now=NOW)
        repeat = queue.apply_item(db, ids[0], ApplyRequest(client_key="apply-0001"), user_id=B, now=NOW)
        assert (final, repeat) == ((first.gold_seq, False), (first.gold_seq, True))
        _conflict("not_adjudicated", lambda: queue.apply_item(db, ids[0], ApplyRequest(client_key="apply-0002"), user_id=C, now=NOW))
        assert db.scalar(select(func.count()).select_from(V3GoldLabelRecord)) == 1
    # A repeat writes nothing and logs nothing: v3.applied and v3.adjudicated count distinct actions only.
    from app.core.structured_logging import FIELDS

    events = [getattr(record, FIELDS, {}).get("event") for record in caplog.records]
    assert events.count("v3.applied") == 1 and events.count("v3.adjudicated") == 1


def test_the_same_reviewer_never_reviews_twice_and_an_adjudicator_never_applies():
    with v3_fakes.fresh_v3_sessions() as (factory, _engine):
        entries = v3_fakes.reviewable_deliveries(2)
        ids = v3_fakes.seed_items(factory, entries, package=PACKAGE, now=NOW, double_review=True)
        request = v3_fakes.supported_labels(entries[0])
        with factory() as db:
            queue.claim_item(db, ids[0], user_id=A, now=NOW, package=PACKAGE)
            assert queue.adjudicate(db, ids[0], request("key-2222a"), user_id=A, now=NOW, package=PACKAGE).state == "queued"
            assert queue.get_item(db, ids[0]).review_round == 2
            _conflict("independent_review_required", lambda: queue.claim_item(db, ids[0], user_id=A, now=NOW, package=PACKAGE))
            queue.claim_item(db, ids[0], user_id=B, now=NOW, package=PACKAGE)
            closed = queue.adjudicate(db, ids[0], request("key-2222b"), user_id=B, now=NOW, package=PACKAGE)
            assert (closed.state, closed.review_round) == ("adjudicated", 2)   # round 2 agrees with round 1
            item = queue.get_item(db, ids[0])
            assert item.final_gold_seq == closed.gold_seq and item.closed_at is not None
            for reviewer in (A, B):
                _conflict("adjudicator_cannot_apply", lambda reviewer=reviewer: queue.apply_item(
                    db, ids[0], ApplyRequest(client_key="apply-2222"), user_id=reviewer, now=NOW))
            assert queue.apply_item(db, ids[0], ApplyRequest(client_key="apply-2222"), user_id=C, now=NOW).final_gold_seq == closed.gold_seq


def test_a_disagreeing_second_review_goes_to_a_third_reviewer_whose_label_is_final():
    with v3_fakes.fresh_v3_sessions() as (factory, _engine):
        entries = v3_fakes.reviewable_deliveries(1)
        (item_id,) = v3_fakes.seed_items(factory, entries, package=PACKAGE, now=NOW, double_review=True)
        request = v3_fakes.supported_labels(entries[0])
        with factory() as db:
            for reviewer, labels, expected in ((A, request("key-3333a"), (2, "queued")),
                                               (B, request("key-3333b", "CONTRADICTED", "A"), (3, "queued")),
                                               (C, request("key-3333c"), (3, "adjudicated"))):
                queue.claim_item(db, item_id, user_id=reviewer, now=NOW, package=PACKAGE)
                result = queue.adjudicate(db, item_id, labels, user_id=reviewer, now=NOW, package=PACKAGE)
                item = queue.get_item(db, item_id)
                assert (item.review_round, item.state) == expected, reviewer
            assert item.final_gold_seq == result.gold_seq and result.review_round == 3
            assert db.scalar(select(func.count()).select_from(V3GoldLabelRecord)) == 3
            _conflict("already_adjudicated", lambda: queue.claim_item(db, item_id, user_id="synthetic-reviewer-d", now=NOW, package=PACKAGE))


def test_double_review_selection_is_the_seeded_rule_on_the_item_id():
    with v3_fakes.fresh_v3_sessions() as (factory, _engine):
        ids = v3_fakes.seed_items(factory, v3_fakes.reviewable_deliveries(200), package=PACKAGE, now=NOW)
        with factory() as db:
            selected = {row.item_id for row in db.execute(select(V3QueueItem.item_id).where(V3QueueItem.double_review.is_(True)))}
    assert selected == {item_id for item_id in ids if bernoulli("double-review-v1", PACKAGE.v3.draw_seed, item_id, Fraction(1, 10))}
    assert 5 <= len(selected) <= 40


def test_independence_survives_a_guest_secret_rotation(seeded, monkeypatch):
    factory, ids, request = seeded
    from sqlalchemy import update

    with factory() as db:
        db.execute(update(V3QueueItem).where(V3QueueItem.item_id == ids[1]).values(double_review=True))
        db.commit()
        queue.claim_item(db, ids[1], user_id=A, now=NOW, package=PACKAGE)
        queue.adjudicate(db, ids[1], request("key-4444a"), user_id=A, now=NOW, package=PACKAGE)
    # The keyed digests rotate with the guest secret; the round records do not.
    monkeypatch.setattr(get_settings(), "guest_token_secret", "rotated-" + "x" * 40)
    with factory() as db:
        _conflict("independent_review_required", lambda: queue.claim_item(db, ids[1], user_id=A, now=NOW, package=PACKAGE))
        queue.claim_item(db, ids[1], user_id=B, now=NOW, package=PACKAGE)
        queue.adjudicate(db, ids[1], request("key-4444b"), user_id=B, now=NOW, package=PACKAGE)
        _conflict("adjudicator_cannot_apply", lambda: queue.apply_item(db, ids[1], ApplyRequest(client_key="apply-4444"), user_id=A, now=NOW))
        digests = [row[0] for row in db.execute(select(V3GoldLabelRecord.reviewer_digest).where(V3GoldLabelRecord.item_id == ids[1]))]
    assert len(set(digests)) == 2


def test_a_late_trigger_on_a_closed_item_is_recorded_and_never_reopens_it(seeded, caplog):
    factory, ids, request = seeded
    with factory() as db:
        queue.claim_item(db, ids[2], user_id=A, now=NOW, package=PACKAGE)
        queue.adjudicate(db, ids[2], request("key-5555a"), user_id=A, now=NOW, package=PACKAGE)
        item = queue.get_item(db, ids[2])
        row = queue.record_row(db, item.ledger_seq)
        caplog.set_level("INFO", logger="qcai.v3")
        # A scan's merge after the adjudication (it read the item before the adjudication committed).
        _, created = queue.upsert_item(db, record_row=row, spec=response_spec(queue.parse_entry(row), "X3"), entry=queue.parse_entry(row),
                                       package=PACKAGE, now=NOW + timedelta(seconds=5))
        db.commit()
        after = queue.get_item(db, ids[2])
    assert created is False and after.state == "adjudicated" and after.final_gold_seq == item.final_gold_seq and after.review_round == 1
    assert queue.split(after.triggers) == {"X3", "X6"} and after.closed_at == item.closed_at
    assert any(getattr(record, "fields", {}).get("event") == "v3.trigger_after_close" for record in caplog.records) or any(
        "closed V3 item" in record.getMessage() for record in caplog.records)


def test_two_concurrent_claims_leave_exactly_one_lease(fresh_database_url):
    connect_args = {"check_same_thread": False, "timeout": 30} if fresh_database_url.startswith("sqlite") else {}
    engine = create_engine(fresh_database_url, connect_args=connect_args)
    try:
        Base.metadata.create_all(engine)
        run_schema_upgrades(engine)
        factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        (item_id,) = v3_fakes.seed_items(factory, v3_fakes.reviewable_deliveries(1), package=PACKAGE, now=NOW)
        barrier = threading.Barrier(2)
        outcomes: list = []

        def claim(reviewer: str) -> None:
            with factory() as db:
                barrier.wait()
                try:
                    outcomes.append(queue.claim_item(db, item_id, user_id=reviewer, now=NOW, package=PACKAGE))
                except V3Conflict as exc:
                    outcomes.append(exc.reason)
                except Exception as exc:  # noqa: BLE001 - a locked SQLite file is the other refusal
                    outcomes.append(type(exc).__name__ + ":" + str(exc)[:80])

        threads = [threading.Thread(target=claim, args=(name,)) for name in (A, B)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(60)
        with factory() as db:
            leases = db.scalar(select(func.count()).select_from(V3Claim).where(V3Claim.item_id == item_id))
        assert leases == 1
        refusals = [outcome for outcome in outcomes if not isinstance(outcome, queue.Lease)]
        assert len(outcomes) == 2 and len(refusals) == 1
        # A file SQLite's "database is locked" (both claims began deferred transactions) is retried, so the loser sees the
        # winner's lease on every database.
        assert refusals == ["claimed_by_another"], refusals
    finally:
        engine.dispose()


def test_a_sqlite_lock_is_retried_and_one_that_outlasts_the_attempts_is_busy(seeded, monkeypatch):
    import sqlite3

    from sqlalchemy.exc import OperationalError

    factory, ids, _request = seeded
    locked = OperationalError("INSERT INTO v3_claims", {}, sqlite3.OperationalError("database is locked"))
    assert queue.sqlite_busy(locked) and not queue.sqlite_busy(OperationalError("x", {}, sqlite3.OperationalError("no such table: v3")))
    real, calls = queue._item, []

    def flaky(db, item_id, *, lock=False, failures):
        calls.append(item_id)
        if len(calls) <= failures:
            raise locked
        return real(db, item_id, lock=lock)

    with factory() as db:
        monkeypatch.setattr(queue, "_item", lambda db, item_id, lock=False: flaky(db, item_id, lock=lock, failures=2))
        lease = queue.claim_item(db, ids[0], user_id=A, now=NOW, package=PACKAGE)
        assert lease.item_id == ids[0] and len(calls) == 3
        calls.clear()
        monkeypatch.setattr(queue, "_item", lambda db, item_id, lock=False: flaky(db, item_id, lock=lock, failures=99))
        with pytest.raises(queue.V3Busy):
            queue.claim_item(db, ids[1], user_id=A, now=NOW, package=PACKAGE)
        assert len(calls) == queue.ATTEMPTS
        # Any other operational error is not retried.
        monkeypatch.setattr(queue, "_item", lambda db, item_id, lock=False: (_ for _ in ()).throw(
            OperationalError("SELECT", {}, sqlite3.OperationalError("no such table: v3_queue_items"))))
        with pytest.raises(OperationalError):
            queue.claim_item(db, ids[1], user_id=A, now=NOW, package=PACKAGE)
    # The scan retries its whole transaction the same way.
    from app.services.v3 import scan as scan_module

    real_once, tries = scan_module._scan_once, []

    def once(**kwargs):
        tries.append(1)
        if len(tries) == 1:
            raise locked
        return real_once(**kwargs)

    monkeypatch.setattr(scan_module, "_scan_once", once)
    result = scan_module.run_scan(settings=Settings(environment="development", v3_queue="shadow"), package=PACKAGE, session_factory=factory, now=NOW)
    assert len(tries) == 2 and result.records == 3
    monkeypatch.setattr(scan_module, "_scan_once", lambda **kwargs: (_ for _ in ()).throw(locked))
    with pytest.raises(queue.V3Busy):
        scan_module.run_scan(settings=Settings(environment="development", v3_queue="shadow"), package=PACKAGE, session_factory=factory, now=NOW)


def test_erasing_a_reviewer_deletes_their_lease_and_round_records(seeded):
    factory, ids, request = seeded
    with factory() as db:
        queue.claim_item(db, ids[0], user_id=A, now=NOW, package=PACKAGE)
        queue.adjudicate(db, ids[0], request("key-6666a"), user_id=A, now=NOW, package=PACKAGE)
        queue.claim_item(db, ids[1], user_id=A, now=NOW, package=PACKAGE)
        assert queue.workflow_state(db, queue.get_item(db, ids[1]), now=NOW) == "claimed"
        erase_user(db, A)
        db.commit()
        assert db.scalar(select(func.count()).select_from(V3Claim).where(V3Claim.user_id == A)) == 0
        assert queue.workflow_state(db, queue.get_item(db, ids[1]), now=NOW) == "queued"
        assert db.scalar(select(func.count()).select_from(V3GoldLabelRecord)) == 1   # the gold row stays (its digest is the record)
