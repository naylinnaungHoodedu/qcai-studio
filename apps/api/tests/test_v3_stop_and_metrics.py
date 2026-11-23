"""Phase 6 stop, SLIs and the X5 interface (plan Phase 6 I, L; plan 13.6, 13.7; Phase 6 spec 4.8, 4.10, 4.11, 13.2).
Fresh in-memory databases with an injected clock (never the shared database: spec 0.1)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import insert, update

from app.core.config import Settings
from app.core.config_package import get_config_package
from app.db_models import QAInteraction, V3QueueItem
from app.services.v3 import stop
from app.services.v3.contracts import CusumAlarm
from app.services.v3.events import record_cusum_alarm
from app.services.v3.metrics import nearest_rank, non_auditable, slis
from app.services.v3.queue import item_id_for
import v3_fakes

SETTINGS = Settings(environment="development", v3_queue="shadow")
PACKAGE = get_config_package(SETTINGS)
NOW = v3_fakes.FIXED_NOW
HOUR = timedelta(hours=1)
SLO = timedelta(seconds=PACKAGE.v3.queue_age_slo_s)


def _item(db, index: int, enqueued, closed=None, triggers="X6") -> None:
    db.execute(insert(V3QueueItem).values(
        item_id=item_id_for(index, ""), ledger_seq=index, claim_key="", subject="response", record_kind="delivery", response_digest="d" * 32,
        triggers=triggers, reasons="", ehmf_types="", held=False, severity=1.0, exposure=1, k=0.0, priority=1.0,
        state="adjudicated" if closed else "queued", review_round=1, double_review=False, enqueued_at=enqueued, closed_at=closed,
        package_version="5.0.0", package_sha256="x"))


def test_stop_state_samples_hourly_over_two_days_and_needs_every_sample_above_the_slo():
    with v3_fakes.fresh_v3_sessions() as (factory, _engine):
        with factory() as db:
            assert stop.stop_state(db, PACKAGE, now=NOW).reason == "clear"   # an empty queue
            _item(db, 1, NOW - (SLO + 48 * HOUR + HOUR))
            db.commit()
            state = stop.stop_state(db, PACKAGE, now=NOW)
            assert state.active and state.reason == "queue_age" and state.samples == 49 and state.open_items == 1
            assert state.oldest_age_s == int((SLO + 49 * HOUR).total_seconds())
            db.execute(update(V3QueueItem).values(state="adjudicated", closed_at=NOW - 30 * 60 * timedelta(seconds=1)))
            db.commit()
            assert stop.stop_state(db, PACKAGE, now=NOW).reason == "clear"   # closed before the last sample
    with v3_fakes.fresh_v3_sessions() as (factory, _engine):
        with factory() as db:
            _item(db, 1, NOW - (SLO + 47 * HOUR))   # above the SLO for the last 47 hours only
            db.commit()
            assert stop.stop_state(db, PACKAGE, now=NOW).active is False


def test_the_oldest_open_item_measures_the_stop_so_young_items_cannot_dilute_it():
    with v3_fakes.fresh_v3_sessions() as (factory, _engine):
        with factory() as db:
            _item(db, 1, NOW - (SLO + 50 * HOUR))
            for index in range(2, 40):
                _item(db, index, NOW - 47 * HOUR + timedelta(minutes=index))
            db.commit()
            state = stop.stop_state(db, PACKAGE, now=NOW)
            body = slis(db, PACKAGE, now=NOW)
    assert state.active and body["queue"]["age_p90_s"] < PACKAGE.v3.queue_age_slo_s   # the p90 alone would clear it
    assert body["queue"]["age_max_s"] == int((SLO + 50 * HOUR).total_seconds()) and body["queue"]["above_slo"] is False


def test_tier1_withheld_caches_per_session_factory_logs_transitions_and_fails_closed(caplog):
    caplog.set_level("INFO", logger="qcai.v3")
    with v3_fakes.fresh_v3_sessions() as (aged, _a), v3_fakes.fresh_v3_sessions() as (clear, _b):
        with aged() as db:
            _item(db, 1, NOW - (SLO + 49 * HOUR))
            db.commit()
        stop.reset_stop_cache()
        assert stop.tier1_withheld(SETTINGS, PACKAGE, now=NOW, session_factory=aged) is True
        assert stop.tier1_withheld(SETTINGS, PACKAGE, now=NOW, session_factory=clear) is False
        with aged() as db:   # cleared in the database: the cached value holds for stop_refresh_s, the seam empties it
            db.execute(update(V3QueueItem).values(state="adjudicated", closed_at=NOW))
            db.commit()
        assert stop.tier1_withheld(SETTINGS, PACKAGE, now=NOW, session_factory=aged) is True
        stop.reset_stop_cache()
        assert stop.tier1_withheld(SETTINGS, PACKAGE, now=NOW, session_factory=aged) is False
    events = [getattr(record, "fields", None) or {} for record in caplog.records]
    stops = [record for record in caplog.records if "V3 stop" in record.getMessage()]
    assert stops and stops[0].levelname == "WARNING"

    def broken():
        raise RuntimeError("no database")

    stop.reset_stop_cache()
    assert stop.tier1_withheld(SETTINGS, PACKAGE, session_factory=broken) is True
    assert any("could not be read" in record.getMessage() and record.levelname == "WARNING" for record in caplog.records)
    assert stop.tier1_withheld(SETTINGS, get_config_package(Settings(config_package_path=str(PACKAGE.path.parent / "v4.json"))),
                               session_factory=broken) is False   # a package without a v3 block reads no stop
    assert isinstance(events, list)


def test_nearest_rank_p90():
    assert nearest_rank([], 0.9) is None and nearest_rank([5], 0.9) == 5
    assert nearest_rank(list(range(1, 11)), 0.9) == 9 and nearest_rank(list(range(1, 101)), 0.9) == 90


def test_non_auditable_counts_turns_without_a_record_and_qa_before_the_ledger():
    with v3_fakes.fresh_v3_sessions() as (factory, _engine):
        with factory() as db:
            db.execute(insert(QAInteraction).values(user_id="guest-synthetic", lesson_slug=None, question="q", answer="a", citations=[],
                                                    created_at=NOW - timedelta(days=30)))
            db.commit()
            # No ledger yet: every Q&A answer is before it.
            assert non_auditable(db, now=NOW) == {"tutor_turns": 0, "qa_before_ledger": 1, "ledger_disabled": 0, "lost_records": 0, "pending": 0}
        v3_fakes.append_all(factory, v3_fakes.synthetic_deliveries(1), now=NOW - timedelta(days=1))
        with factory() as db:
            db.execute(insert(QAInteraction).values(user_id="guest-synthetic", lesson_slug=None, question="q", answer="a", citations=[], created_at=NOW))
            db.commit()
            assert non_auditable(db, now=NOW)["qa_before_ledger"] == 1


def test_non_auditable_reports_pre_ledger_turns_apart_from_kill_switch_turns_lost_records_and_pending_appends():
    # Plan Phase 6 G "pre-ledger deliveries reported as non-auditable": a tutor turn from an image that keeps no ledger is
    # pre-ledger; a turn created while the ledger kill switch was off, a lost append (it expected a record and has none
    # past the coverage horizon: a Phase 3 plan L stop) and an append still inside the horizon are reported apart.
    from app.db_models import TutorThread, TutorTurn

    with v3_fakes.fresh_v3_sessions() as (factory, _engine):
        with factory() as db:
            db.add(TutorThread(id="thread-synthetic", user_id="guest-synthetic", title="t"))
            db.flush()
            for index, (expected, created) in enumerate(((None, NOW - timedelta(days=9)), (False, NOW - timedelta(days=8)),
                                                         (True, NOW - timedelta(days=7)), (True, NOW - timedelta(days=6)),
                                                         (True, NOW - timedelta(seconds=5)))):
                db.add(TutorTurn(id=v3_fakes.synthetic_id(9000 + index), thread_id="thread-synthetic", user_id="guest-synthetic",
                                 resolved_query="q", retrieval_mode="lexical", provider="p", model="m", decision="answer", decision_reason="r",
                                 citations=[], claims=[], corpus_version="c", policy_version="p", ledger_record_expected=expected,
                                 created_at=created))
            db.commit()
            counts = non_auditable(db, now=NOW)
    assert counts == {"tutor_turns": 1, "qa_before_ledger": 0, "ledger_disabled": 1, "lost_records": 2, "pending": 1}


def test_the_residual_bound_is_null_while_nothing_is_audited():
    # An empty population is no evidence: the bound is null and no_audited_answers true, never an upper bound of 0 that
    # would read as a perfect residual (the deployment form of HR-3).
    from app.services.v3.residual import residual, wilson95, wilson_upper

    assert wilson_upper(0, 0) is None and wilson95(0, 0) is None and wilson_upper(0, 300) < 0.013
    with v3_fakes.fresh_v3_sessions() as (factory, _engine):
        with factory() as db:
            empty = residual(db, PACKAGE)
            body = slis(db, PACKAGE, now=NOW)
        # An audited abstention is not an answer: the population stays empty.
        entries = v3_fakes.reviewable_deliveries(1, decision="abstain")
        (item_id,) = v3_fakes.seed_items(factory, entries, package=PACKAGE, now=NOW, trigger="X6", double_review=False)
        from app.services.v3 import queue
        from app.services.v3.scan import run_scan

        run_scan(settings=SETTINGS, package=PACKAGE, session_factory=factory, now=NOW)
        with factory() as db:
            queue.claim_item(db, item_id, user_id="synthetic-reviewer-a", now=NOW, package=PACKAGE)
            queue.adjudicate(db, item_id, v3_fakes.supported_labels(entries[0])("key-empty01"), user_id="synthetic-reviewer-a", now=NOW,
                             package=PACKAGE)
            abstained = residual(db, PACKAGE)
    for block in (empty, body["residual"], abstained):
        assert (block["audited"], block["errors"], block["wilson95"], block["no_audited_answers"], block["by_month"]) == (0, 0, None, True, [])


def test_a_cusum_alarm_is_recorded_whatever_the_mode_and_a_synthetic_one_is_refused_outside_development():
    alarm = CusumAlarm(stream="verifier:fake-alpha", p0=0.05, p1=0.15, h=4.0, statistic=4.0, observations=50, raised_at="2026-11-20T12:00:00Z",
                       source="synthetic-test")
    with v3_fakes.fresh_v3_sessions() as (factory, _engine):
        off = Settings(environment="development", v3_queue="off")
        assert record_cusum_alarm(alarm, settings=off, package=PACKAGE, session_factory=factory, now=NOW) == 1
        with pytest.raises(ValueError):
            record_cusum_alarm(alarm, settings=v3_fakes.staging_settings(), package=PACKAGE, session_factory=factory, now=NOW)
        real = alarm.model_copy(update={"source": "phase9-cusum"})
        assert record_cusum_alarm(real, settings=v3_fakes.staging_settings(), package=PACKAGE, session_factory=factory, now=NOW) == 2
    for broken in ({"statistic": 3.9}, {"p0": 0.2}, {"source": "other"}, {"stream": "Bad Stream"}, {"observations": 0}):
        with pytest.raises(ValidationError):
            CusumAlarm(**{**alarm.model_dump(), **broken})
