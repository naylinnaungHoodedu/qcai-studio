"""Phase 6 audit draw (plan Phase 6 D task 2 "seeded 5% draw over ledger deliveries"; J "property: each delivery
audit-eligible once"; AC-6-2; Phase 6 spec 4.2, 13.2). Fresh in-memory databases only (spec M17)."""

from __future__ import annotations

from contextlib import contextmanager
import dataclasses
from datetime import timedelta
from fractions import Fraction
import hashlib
import random

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.config_package import get_config_package
from app.db_models import V3Draw, V3Event, V3QueueItem
from app.services.v3 import draw
from app.services.v3.contracts import CusumAlarm
from app.services.v3.events import record_cusum_alarm
from app.services.v3.scan import run_scan, scan_until_done
from tutor_fakes import make_entry
import v3_fakes

SETTINGS = Settings(environment="development", v3_queue="shadow")
PACKAGE = get_config_package(SETTINGS)
SEED = PACKAGE.v3.draw_seed
ALARM = dict(stream="verifier:fake-alpha", p0=0.05, p1=0.15, h=4.0, statistic=4.2, observations=120, raised_at="2026-11-20T12:00:00Z",
             source="synthetic-test")


def test_u64_and_bernoulli_follow_the_exact_integer_rule():
    key = v3_fakes.synthetic_id(7)
    expected = int.from_bytes(hashlib.sha256(f"x6-draw-v1|{SEED}|{key}".encode()).digest()[:8], "big")
    assert draw.u64("x6-draw-v1", SEED, key) == expected
    assert draw.bernoulli("x6-draw-v1", SEED, key, Fraction(1, 20)) is (expected * 20 < 2**64)
    assert draw.bernoulli("p", "s", "k", Fraction(0)) is False and draw.bernoulli("p", "s", "k", Fraction(1)) is True


def test_the_draw_is_exact_at_the_rate_boundary_where_a_float_comparison_is_not(monkeypatch):
    # u = floor(2^64 / 20) is drawn at 1/20 by the integer rule (u * 20 < 2^64), and u + 1 is not. As floats, u / 2^64
    # rounds to exactly 0.05, so a float comparison (u / 2^64 < 0.05) would refuse the drawn one.
    boundary = (2**64) // 20
    assert boundary / 2**64 == 0.05
    monkeypatch.setattr(draw, "u64", lambda purpose, seed, key: boundary)
    assert draw.bernoulli("x6-draw-v1", SEED, "k", Fraction(1, 20)) is True
    assert draw.draw_trigger(SEED, "k", base=Fraction(1, 20), elevated=Fraction(1, 5), x5_active=False) == "X6"
    monkeypatch.setattr(draw, "u64", lambda purpose, seed, key: boundary + 1)
    assert draw.bernoulli("x6-draw-v1", SEED, "k", Fraction(1, 20)) is False
    assert draw.draw_trigger(SEED, "k", base=Fraction(1, 20), elevated=Fraction(1, 5), x5_active=True) == "X5"


def test_raising_the_rate_never_undraws_a_delivery():
    ids = [v3_fakes.synthetic_id(index) for index in range(1, 3001)]
    low = {key for key in ids if draw.bernoulli("x6-draw-v1", SEED, key, Fraction(1, 20))}
    high = {key for key in ids if draw.bernoulli("x6-draw-v1", SEED, key, Fraction(1, 5))}
    assert low < high
    for key in ids:
        got = draw.draw_trigger(SEED, key, base=Fraction(1, 20), elevated=Fraction(1, 5), x5_active=True)
        assert got == ("X6" if key in low else "X5" if key in high else None)
        assert draw.draw_trigger(SEED, key, base=Fraction(1, 20), elevated=Fraction(1, 5), x5_active=False) == ("X6" if key in low else None)


def test_claim_set_key_is_order_free_and_null_for_an_abstention():
    entry = make_entry("turn-00000000-0000-0000-0000-000000000001")
    assert draw.claim_set_key(entry) == hashlib.sha256("\n".join(sorted({claim.claim_id for claim in entry.claims})).encode()).hexdigest()
    reversed_entry = entry.model_copy(update={"claims": tuple(reversed(entry.claims))})
    assert draw.claim_set_key(reversed_entry) == draw.claim_set_key(entry)
    assert draw.claim_set_key(make_entry(decision="abstain")) is None and draw.claim_set_key(None) is None


def _draws(factory) -> dict[int, tuple]:
    with factory() as db:
        return {row.ledger_seq: (row.drawn, row.x5_active, row.rate_numerator, row.rate_denominator) for row in db.scalars(select(V3Draw))}


@contextmanager
def _copy_of(template_engine):
    """A fresh in-memory database holding the template's rows (sqlite3's backup API)."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    try:
        source, target = template_engine.raw_connection(), engine.raw_connection()
        try:
            source.driver_connection.backup(target.driver_connection)
        finally:
            source.close()
            target.close()
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    finally:
        engine.dispose()


def test_each_delivery_is_considered_exactly_once_under_every_split_of_scan_batches_and_mid_stream_x5_events():
    rng = random.Random(20261122)
    with v3_fakes.fresh_v3_sessions() as (template, engine):
        v3_fakes.append_all(template, v3_fakes.synthetic_deliveries(40))
        reference = None
        for split in range(200):
            alarm_after = rng.randint(0, 6) if split % 2 else None
            with _copy_of(engine) as factory:
                batches = 0
                while True:
                    result = run_scan(settings=SETTINGS, package=PACKAGE, session_factory=factory, now=v3_fakes.FIXED_NOW, limit=rng.randint(1, 13))
                    batches += 1
                    if alarm_after is not None and batches == alarm_after:
                        record_cusum_alarm(CusumAlarm(**ALARM), settings=SETTINGS, package=PACKAGE, session_factory=factory, now=v3_fakes.FIXED_NOW)
                    if result.done:
                        break
                # A later scan and a later X5 window never redraw a considered delivery.
                record_cusum_alarm(CusumAlarm(**ALARM), settings=SETTINGS, package=PACKAGE, session_factory=factory, now=v3_fakes.FIXED_NOW)
                run_scan(settings=SETTINGS, package=PACKAGE, session_factory=factory, now=v3_fakes.FIXED_NOW, limit=100)
                seen = _draws(factory)
                with factory() as db:
                    items = db.scalar(select(func.count()).select_from(V3QueueItem))
            assert sorted(seen) == list(range(1, 41)), split
            assert items == sum(1 for value in seen.values() if value[0] is not None), split
            if alarm_after is None:
                reference = reference or seen
                assert seen == reference, split


def test_an_x5_window_covers_the_next_deliveries_and_its_draws_are_x5_only_between_the_two_rates():
    entries = v3_fakes.synthetic_deliveries(400)
    with v3_fakes.fresh_v3_sessions() as (factory, _engine):
        v3_fakes.append_all(factory, entries[:100])
        scan_until_done(settings=SETTINGS, package=PACKAGE, session_factory=factory, now=v3_fakes.FIXED_NOW)
        record_cusum_alarm(CusumAlarm(**ALARM), settings=SETTINGS, package=PACKAGE, session_factory=factory, now=v3_fakes.FIXED_NOW)
        v3_fakes.append_all(factory, entries[100:])
        scan_until_done(settings=SETTINGS, package=PACKAGE, session_factory=factory, now=v3_fakes.FIXED_NOW + timedelta(hours=1), limit=37)
        seen = _draws(factory)
        with factory() as db:
            assert db.scalar(select(func.count()).select_from(V3Event)) == 1
    before = {seq: value for seq, value in seen.items() if seq <= 100}
    after = {seq: value for seq, value in seen.items() if seq > 100}
    assert all(value[1] is False and value[2:] == (1, 20) for value in before.values())
    assert all(value[1] is True and value[2:] == (1, 5) for value in after.values())   # 300 deliveries, inside the 1500 window
    for index, entry in enumerate(entries, start=1):
        expected = draw.draw_trigger(SEED, entry.response_id, base=Fraction(1, 20), elevated=Fraction(1, 5), x5_active=index > 100)
        assert seen[index][0] == expected, index
    assert any(value[0] == "X5" for value in after.values()) and all(value[0] != "X5" for value in before.values())


def test_a_window_closes_after_its_deliveries():
    small = dataclasses.replace(PACKAGE, v3=dataclasses.replace(PACKAGE.v3, x5_window_deliveries=20))
    with v3_fakes.fresh_v3_sessions() as (factory, _engine):
        record_cusum_alarm(CusumAlarm(**ALARM), settings=SETTINGS, package=small, session_factory=factory, now=v3_fakes.FIXED_NOW)
        v3_fakes.append_all(factory, v3_fakes.synthetic_deliveries(60))
        scan_until_done(settings=SETTINGS, package=small, session_factory=factory, now=v3_fakes.FIXED_NOW, limit=7)
        seen = _draws(factory)
    assert [seq for seq, value in sorted(seen.items()) if value[1]] == list(range(1, 21))


def test_a_model_version_change_between_scans_records_one_x5_event_and_raises_the_next_deliveries_to_1_5(monkeypatch):
    # Plan task 1 "X5 CUSUM alarm or model change (audit 20%)"; 6.3 L746 "version change -> X5 audit 20%". The scan names
    # each change through triggers.x5_model_changes: a registry verifier's new version, and a record's new generator version.
    import json

    from app.gateway import registry as gateway_registry
    from v2_fakes import make_registry

    first = make_registry(("fake-alpha", "fake-beta"))
    second = dataclasses.replace(first, members=tuple(dataclasses.replace(member, model_version="2099-01-01") if member.family == "fake-beta"
                                                      else member for member in first.members))
    current = {"registry": first}
    monkeypatch.setattr(gateway_registry, "registry_for", lambda package, settings: current["registry"])
    entries = v3_fakes.synthetic_deliveries(40)
    with v3_fakes.fresh_v3_sessions() as (factory, _engine):
        v3_fakes.append_all(factory, entries[:10])
        baseline = run_scan(settings=SETTINGS, package=PACKAGE, session_factory=factory, now=v3_fakes.FIXED_NOW)
        current["registry"] = second
        v3_fakes.append_all(factory, entries[10:])
        changed = run_scan(settings=SETTINGS, package=PACKAGE, session_factory=factory, now=v3_fakes.FIXED_NOW)
        again = run_scan(settings=SETTINGS, package=PACKAGE, session_factory=factory, now=v3_fakes.FIXED_NOW)
        with factory() as db:
            events = [(row.kind, json.loads(row.payload), row.from_ledger_seq) for row in db.execute(select(V3Event.__table__))]
        seen = _draws(factory)
    assert (baseline.model_changes, changed.model_changes, again.model_changes) == (0, 1, 0)
    assert events == [("model_change", {"model_key": "verifier:fake-beta-verifier", "from_version": first.members[1].model_version,
                                        "to_version": "2099-01-01", "source": "registry"}, 10)]
    assert all(value[1] is False and value[2:] == (1, 20) for seq, value in seen.items() if seq <= 10)
    assert all(value[1] is True and value[2:] == (1, 5) for seq, value in seen.items() if seq > 10)
    # A record whose verifier votes name another version than an earlier record's is a change from that record on (the
    # registry the scan compares stays the first one).
    from v1_fakes import run
    from v2_fakes import adapters_of, fresh_gateway, v2_pipeline

    def shadow_record(registry):
        return run(v2_pipeline(None, gateway=fresh_gateway(adapters=adapters_of(registry)), registry=registry), v3_fakes.CRITICAL_QUERY).entry

    three = make_registry(("fake-alpha", "fake-beta", "fake-gamma"))
    moved = dataclasses.replace(three, members=tuple(dataclasses.replace(member, model_version="2099-01-01") if member.family == "fake-beta"
                                                     else member for member in three.members))
    current["registry"] = three
    with v3_fakes.fresh_v3_sessions() as (factory, _engine):
        v3_fakes.append_all(factory, entries[:20] + [shadow_record(three), shadow_record(moved)] + v3_fakes.synthetic_deliveries(10, start=41))
        result = run_scan(settings=SETTINGS, package=PACKAGE, session_factory=factory, now=v3_fakes.FIXED_NOW)
        with factory() as db:
            events = [(row.kind, json.loads(row.payload), row.from_ledger_seq) for row in db.execute(select(V3Event.__table__))]
        seen = _draws(factory)
    assert result.model_changes == 1 and events == [("model_change", {"model_key": "verifier:fake-beta-verifier",
                                                                       "from_version": three.members[1].model_version,
                                                                       "to_version": "2099-01-01", "source": "record"}, 22)]
    assert sorted(seen) == list(range(1, 21)) + list(range(23, 33))                     # shadow records are never drawn
    assert all(value[1] is False and value[2:] == (1, 20) for seq, value in seen.items() if seq <= 20)
    assert all(value[1] is True and value[2:] == (1, 5) for seq, value in seen.items() if seq > 22)


def test_shadow_records_are_never_drawn_and_unparsed_deliveries_still_are(monkeypatch):
    from app.services.tutor_pipeline import contracts

    with v3_fakes.fresh_v3_sessions() as (factory, _engine):
        v3_fakes.append_all(factory, [make_entry(delivery="shadow"), make_entry(v3_fakes.synthetic_id(5))])
        schemas = dict(contracts.ENTRY_SCHEMAS)
        schemas.pop("ledger-entry-v1")
        monkeypatch.setattr(contracts, "ENTRY_SCHEMAS", schemas)
        result = run_scan(settings=SETTINGS, package=PACKAGE, session_factory=factory, now=v3_fakes.FIXED_NOW)
        seen = _draws(factory)
        with factory() as db:
            keys = [row[0] for row in db.execute(select(V3Draw.claim_set_key))]
    assert result.unparsed == 2 and result.deliveries == 1 and sorted(seen) == [2] and keys == [None]
