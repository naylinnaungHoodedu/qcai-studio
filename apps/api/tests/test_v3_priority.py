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
        # An item created before its record's draw (an X3 flag before the scan) counts the earlier deliveries only.
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
