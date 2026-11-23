"""Phase 6 queue priority severity x exposure x (1 - K) (plan Phase 6 D task 2, AC-6-3; Phase 6 spec 4.3, 13.2; PD-34)."""

from __future__ import annotations

from datetime import timedelta
from fractions import Fraction
import itertools
from types import SimpleNamespace

from app.core.config import Settings
from app.core.config_package import get_config_package
from app.services.v3 import priority, queue
from app.services.v3.scan import run_scan
from app.services.v3.triggers import ItemSpec
from tutor_fakes import make_entry
import v3_fakes

SETTINGS = Settings(environment="development", v3_queue="shadow")
PACKAGE = get_config_package(SETTINGS)
WEIGHTS = PACKAGE.v3.severity


def test_severity_is_the_largest_weight_unknown_is_1_and_the_plan_weights_are_exact():
    assert WEIGHTS == {"A": 1, "B": 1, "C": Fraction(3, 5), "D": Fraction(3, 5), "E": Fraction(2, 5), "unknown": 1, "disclosed_conflict": 0}
    assert priority.severity({"C", "E"}, WEIGHTS) == Fraction(3, 5) and priority.severity({"E"}, WEIGHTS) == Fraction(2, 5)
    assert priority.severity({"A", "E"}, WEIGHTS) == 1 and priority.severity(set(), WEIGHTS) == 1


def test_k_is_the_panel_support_share_its_mean_and_zero_without_a_vote():
    def v2(members, objections, outcome="pass"):
        return SimpleNamespace(members=tuple(members), objections=objections, outcome=outcome)

    assert priority.support_share(v2("abc", 1)) == Fraction(2, 3) and priority.support_share(v2("ab", 0)) == 1
    assert priority.support_share(None) == 0 and priority.support_share(v2("", 0)) == 0 and priority.support_share(v2("abc", 0, "withheld")) == 0
    record = SimpleNamespace(verification=SimpleNamespace(verdicts=(SimpleNamespace(v2=v2("abc", 1)), SimpleNamespace(v2=v2("abc", 3)),
                                                                     SimpleNamespace(v2=None))))
    assert priority.response_k(record) == Fraction(1, 3)
    assert priority.response_k(make_entry()) == 0


def test_exposure_counts_the_claim_set_s_deliveries_up_to_the_record_and_is_at_least_1():
    same = v3_fakes.synthetic_deliveries(3)
    other = v3_fakes.synthetic_deliveries(1, start=10, text="Another claim of the corpus.", span_id="span-" + "2" * 64)
    with v3_fakes.fresh_v3_sessions() as (factory, _engine):
        v3_fakes.append_all(factory, [same[0], other[0], same[1], same[2], make_entry(delivery="shadow"), make_entry(decision="abstain")])
        # Before the scan has drawn a record, exposure_for counts the deliveries considered so far (none here); the scan's
        # refresh_exposure raises an item created then (test_an_item_s_exposure_and_priority_do_not_depend_on_...).
        with factory() as db:
            early = queue.record_row(db, 3)
            assert priority.exposure_for(db, early, "missing-key") == 1
        run_scan(settings=SETTINGS, package=PACKAGE, session_factory=factory, now=v3_fakes.FIXED_NOW)
        with factory() as db:
            rows = [queue.record_row(db, seq) for seq in range(1, 7)]
            entries = [queue.parse_entry(row) for row in rows]
            from app.services.v3.draw import claim_set_key

            exposures = [priority.exposure_for(db, row, claim_set_key(entry)) for row, entry in zip(rows, entries)]
    assert exposures == [1, 1, 2, 3, 1, 1]


FLAGGER = "guest-synthetic-flagger"


def _turn_for(factory, seq: int) -> str:
    """A synthetic learner's tutor turn for ledger record `seq` (the flag route's precondition); returns its id."""
    from app.db_models import TutorThread, TutorTurn

    with factory() as db:
        response_id = queue.record_row(db, seq).response_id
        db.add(TutorThread(id=f"thread-synthetic-{seq}", user_id=FLAGGER, title="t"))
        db.flush()
        db.add(TutorTurn(id=response_id, thread_id=f"thread-synthetic-{seq}", user_id=FLAGGER, resolved_query="q", retrieval_mode="lexical",
                         provider="p", model="m", decision="answer", decision_reason="r", citations=[], claims=[], corpus_version="c",
                         policy_version="p", ledger_record_expected=True))
        db.commit()
    return response_id


def _flag(factory, response_id: str):
    from app.services.v3.feedback import record_flag

    with factory() as db:
        return record_flag(db, user_id=FLAGGER, response_id=response_id, settings=SETTINGS, package=PACKAGE, now=v3_fakes.FIXED_NOW)


def test_an_item_s_exposure_and_priority_do_not_depend_on_whether_a_flag_or_the_scan_came_first():
    # Twenty learner deliveries of one claim set; the learner flag path (feedback.record_flag) puts an X3 response item
    # on the twentieth before or after the scan reaches the record.
    outcomes = {}
    for order in ("flag_then_scan", "scan_then_flag", "flag_scan_flag"):
        with v3_fakes.fresh_v3_sessions() as (factory, _engine):
            v3_fakes.append_all(factory, v3_fakes.synthetic_deliveries(20))
            response_id = _turn_for(factory, 20)
            if order != "scan_then_flag":
                _flag(factory, response_id)
            run_scan(settings=SETTINGS, package=PACKAGE, session_factory=factory, now=v3_fakes.FIXED_NOW)
            if order != "flag_then_scan":
                _flag(factory, response_id)
            with factory() as db:
                item = queue.get_item(db, queue.item_id_for(20, ""))
                outcomes[order] = (item.exposure, item.priority, "X3" in queue.split(item.triggers))
    # The record's exposure is its 20 deliveries of the claim set; K is 0 and the unknown type weighs 1.
    assert set(outcomes.values()) == {(20, 20.0, True)}, outcomes


def test_a_flag_that_races_the_scan_gets_the_record_s_exposure(fresh_database_url, monkeypatch):
    # The flag path runs in a second session while the scan's transaction is open: after the scan drew the twentieth
    # record and refreshed its items, before it committed (spec 4.7). On PostgreSQL the flag waits on the scan's advisory
    # lock; on SQLite on the database lock. Either way it counts committed draws only, so the item gets the record's
    # exposure, never a count from a snapshot without the scan's draws (priority 1 instead of 20).
    import threading

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.core.db import Base
    from app.core.schema_upgrades import run_schema_upgrades
    from app.services.v3 import scan as scan_module

    connect_args = {"check_same_thread": False, "timeout": 30} if fresh_database_url.startswith("sqlite") else {}
    engine = create_engine(fresh_database_url, connect_args=connect_args)
    try:
        Base.metadata.create_all(engine)
        run_schema_upgrades(engine)
        factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        v3_fakes.append_all(factory, v3_fakes.synthetic_deliveries(20))
        response_id = _turn_for(factory, 20)
        refreshed, release, outcomes = threading.Event(), threading.Event(), {}
        real = scan_module.refresh_exposure

        def paused(db, *, record_row, entry, package):
            raised = real(db, record_row=record_row, entry=entry, package=package)
            if int(record_row.seq) == 20:
                refreshed.set()
                release.wait(60)            # the scan's transaction stays open with its 20 draws uncommitted
            return raised

        def run(name, call):
            try:
                outcomes[name] = call()
            except Exception as exc:  # noqa: BLE001 - reported by the assertion below
                outcomes[name] = exc

        monkeypatch.setattr(scan_module, "refresh_exposure", paused)
        scan = lambda: run_scan(settings=SETTINGS, package=PACKAGE, session_factory=factory, now=v3_fakes.FIXED_NOW)  # noqa: E731
        scanner = threading.Thread(target=run, args=("scan", scan))
        scanner.start()
        assert refreshed.wait(60)
        flagger = threading.Thread(target=run, args=("flag", lambda: _flag(factory, response_id)))
        flagger.start()
        flagger.join(2)
        release.set()
        scanner.join(60)
        flagger.join(60)
        assert not scanner.is_alive() and not flagger.is_alive()
        assert outcomes["flag"] == (20, False) and outcomes["scan"].deliveries == 20, outcomes
        with factory() as db:
            item = queue.get_item(db, queue.item_id_for(20, ""))
            assert (item.exposure, item.priority, "X3" in queue.split(item.triggers)) == (20, 20.0, True)
    finally:
        engine.dispose()


def test_priority_orders_an_exhaustive_grid_as_the_exact_products_do():
    grid = list(itertools.product(sorted({Fraction(1), Fraction(3, 5), Fraction(2, 5)}), (1, 2, 3),
                                  (Fraction(0), Fraction(1, 3), Fraction(1, 2), Fraction(2, 3), Fraction(1))))
    with v3_fakes.fresh_v3_sessions() as (factory, _engine):
        v3_fakes.append_all(factory, v3_fakes.synthetic_deliveries(len(grid)))
        expected = []
        with factory() as db:
            for index, (sev, exposure, k) in enumerate(grid, start=1):
                row = queue.record_row(db, index)
                types = {Fraction(1): {"A"}, Fraction(3, 5): {"C"}, Fraction(2, 5): {"E"}}[sev]
                spec = ItemSpec(claim_key="", subject="response", triggers=frozenset({"X6"}), reasons=frozenset(), ehmf_types=frozenset(types),
                                k=k, held=False)
                item_id, _ = queue.upsert_item(db, record_row=row, spec=spec, entry=None, package=PACKAGE,
                                               now=v3_fakes.FIXED_NOW + timedelta(seconds=len(grid) - index))
                from app.db_models import V3QueueItem
                from sqlalchemy import update

                db.execute(update(V3QueueItem).where(V3QueueItem.item_id == item_id).values(
                    exposure=exposure, priority=float(priority.priority(sev, exposure, k))))
                expected.append((-priority.priority(sev, exposure, k), v3_fakes.FIXED_NOW + timedelta(seconds=len(grid) - index), item_id))
            db.commit()
            listed = [row.item_id for row in queue.list_queue(db, limit=1000, now=v3_fakes.FIXED_NOW + timedelta(days=1))]
    assert listed == [item_id for _, _, item_id in sorted(expected)]


def test_equal_priorities_order_by_enqueue_time_then_item_id():
    with v3_fakes.fresh_v3_sessions() as (factory, _engine):
        v3_fakes.append_all(factory, v3_fakes.synthetic_deliveries(4))
        spec = ItemSpec(claim_key="", subject="response", triggers=frozenset({"X6"}), reasons=frozenset(), ehmf_types=frozenset({"A"}),
                        k=Fraction(0), held=False)
        times = [v3_fakes.FIXED_NOW + timedelta(seconds=2), v3_fakes.FIXED_NOW, v3_fakes.FIXED_NOW, v3_fakes.FIXED_NOW + timedelta(seconds=1)]
        with factory() as db:
            ids = [queue.upsert_item(db, record_row=queue.record_row(db, seq), spec=spec, entry=None, package=PACKAGE, now=when)[0]
                   for seq, when in zip(range(1, 5), times)]
            db.commit()
            listed = [row.item_id for row in queue.list_queue(db, now=v3_fakes.FIXED_NOW + timedelta(hours=1))]
    assert listed == sorted(ids[1:3]) + [ids[3], ids[0]]
