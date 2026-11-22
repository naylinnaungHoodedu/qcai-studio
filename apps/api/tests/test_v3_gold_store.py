"""Phase 6 gold store and the append-only V3 tables (plan Phase 6 D task 3 "append-only gold store"; plan 7.4 AuditEvent;
R-22; AC-6-4; Phase 6 spec 4.6, 8, 13.2). The trigger tests run on a fresh database of the session's dialect
(fresh_database_url: SQLite, or PostgreSQL under psycopg or pg8000 in CI)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json

import pytest
from sqlalchemy import create_engine, insert, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.core.config_package import get_config_package
from app.core.db import Base
from app.core.schema_upgrades import V3_APPEND_ONLY_TABLES, run_schema_upgrades
from app.db_models import V3Draw, V3GoldLabelRecord, V3QueueItem
from app.services.tutor_pipeline.contracts import ledger_canonical, sha256_hex
from app.services.v3.contracts import GoldLabel
from app.services.v3.gold import append_gold, export_gold, gold_hash_for, verify_gold_store
from app.services.v3.rules import GOLD_GENESIS

PACKAGE = get_config_package(Settings())
NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


def label(item: str = "v3i-" + "a" * 24, review_round: int = 1) -> GoldLabel:
    return GoldLabel(item_id=item, review_round=review_round, subject="response", triggers=("X6",), reasons=(), ledger_seq=1,
                     response_digest="d" * 32, delivery_digest="d" * 32, delivered_answer=False, claims=(), claim_labels=(),
                     abstention_label="correct", residual_error=False, reviewer_digest="c" * 32, client_key="client-key-1",
                     package_version=PACKAGE.package_version, package_sha256=PACKAGE.sha256, adjudicated_at="2026-11-20T12:00:00.000000Z")


def _sessions(url: str):
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, connect_args=connect_args)
    Base.metadata.create_all(engine)
    run_schema_upgrades(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False), engine


def test_the_chain_follows_its_hash_rule_and_verifies(fresh_database_url):
    factory, engine = _sessions(fresh_database_url)
    try:
        with factory() as db:
            first = append_gold(db, label("v3i-" + "1" * 24), now=NOW)
            second = append_gold(db, label("v3i-" + "2" * 24), now=NOW + timedelta(seconds=1))
            db.commit()
        with factory() as db:
            rows = db.execute(select(V3GoldLabelRecord).order_by(V3GoldLabelRecord.seq)).scalars().all()
            check = verify_gold_store(db, expected_head=second)
        assert [row.seq for row in rows] == [1, 2] and rows[0].prev_hash == GOLD_GENESIS and rows[1].prev_hash == first[1]
        digest = sha256_hex(ledger_canonical(label("v3i-" + "1" * 24).model_dump(mode="json")))
        assert rows[0].entry_sha256 == digest and rows[0].record_hash == gold_hash_for(seq=1, created_at=NOW, prev_hash=GOLD_GENESIS, entry_sha256=digest)
        assert (rows[0].actor_role, rows[0].action) == ("reviewer", "adjudicate")
        assert check.ok and check.count == 2 and (check.head_seq, check.head_hash) == second
        with factory() as db:
            assert not verify_gold_store(db, expected_head=(3, "f" * 64)).ok
    finally:
        engine.dispose()


def _refused(factory, statement) -> None:
    with factory() as db:
        with pytest.raises((DBAPIError, IntegrityError)):
            db.execute(text(statement))
            db.commit()
        db.rollback()


def test_update_delete_truncate_and_an_unchained_insert_are_refused(fresh_database_url):
    factory, engine = _sessions(fresh_database_url)
    try:
        with factory() as db:
            append_gold(db, label(), now=NOW)
            db.commit()
        _refused(factory, "UPDATE v3_gold_labels SET action = 'edited'")
        _refused(factory, "DELETE FROM v3_gold_labels")
        if engine.dialect.name == "postgresql":
            _refused(factory, "TRUNCATE v3_gold_labels")
        with factory() as db:
            with pytest.raises((DBAPIError, IntegrityError)):
                db.execute(insert(V3GoldLabelRecord).values(seq=5, item_id="v3i-" + "c" * 24, review_round=1, actor_role="reviewer", action="adjudicate",
                                                            reviewer_digest="c" * 32, entry="{}", entry_sha256="0" * 64, prev_hash="0" * 64,
                                                            record_hash="0" * 64, created_at=NOW))
                db.commit()
            db.rollback()
        with factory() as db:
            assert db.scalar(text("SELECT COUNT(*) FROM v3_gold_labels")) == 1 and verify_gold_store(db).ok
    finally:
        engine.dispose()


def test_the_other_append_only_v3_tables_refuse_update_and_delete_and_the_queue_refuses_delete(fresh_database_url):
    factory, engine = _sessions(fresh_database_url)
    try:
        with factory() as db:
            db.execute(insert(V3Draw).values(ledger_seq=1, delivered_at=NOW, claim_set_key=None, rate_numerator=1, rate_denominator=20, x5_active=False,
                                             drawn=None, rule="seeded-sha256-bernoulli-v1", package_sha256="0" * 64, considered_at=NOW))
            db.execute(text("INSERT INTO v3_events (kind, payload, from_ledger_seq, window_deliveries, created_at) "
                            "VALUES ('cusum_alarm', '{}', 0, 10, CURRENT_TIMESTAMP)"))
            db.execute(text("INSERT INTO v3_model_versions (model_key, model_version, first_seen_seq, source, seen_at) "
                            "VALUES ('verifier:m', 'v', 0, 'registry', CURRENT_TIMESTAMP)"))
            db.execute(text("INSERT INTO v3_scans (from_seq, to_seq, records, deliveries, drawn_x6, drawn_x5, items_created, items_updated, "
                            "model_changes, unparsed, package_version, package_sha256, created_at) "
                            "VALUES (0, 0, 0, 0, 0, 0, 0, 0, 0, 0, '5.0.0', 'x', CURRENT_TIMESTAMP)"))
            db.execute(insert(V3QueueItem).values(item_id="v3i-" + "e" * 24, ledger_seq=1, claim_key="", subject="response", record_kind="delivery",
                                                  response_digest="d" * 32, triggers="X6", reasons="", ehmf_types="", held=False, severity=1.0,
                                                  exposure=1, k=0.0, priority=1.0, state="queued", review_round=1, double_review=False,
                                                  enqueued_at=NOW, package_version="5.0.0", package_sha256="x"))
            db.commit()
        for table in V3_APPEND_ONLY_TABLES:
            if table == "v3_gold_labels":
                continue
            _refused(factory, f"UPDATE {table} SET {'kind' if table == 'v3_events' else 'source' if table == 'v3_model_versions' else 'rule' if table == 'v3_draws' else 'package_version'} = 'x'")
            _refused(factory, f"DELETE FROM {table}")
            if engine.dialect.name == "postgresql":
                _refused(factory, f"TRUNCATE {table}")
        _refused(factory, "DELETE FROM v3_queue_items")
        if engine.dialect.name == "postgresql":
            _refused(factory, "TRUNCATE v3_queue_items")
        with factory() as db:
            db.execute(text("UPDATE v3_queue_items SET state = 'adjudicated'"))   # the workflow moves an item's state
            db.commit()
            assert db.scalar(text("SELECT state FROM v3_queue_items")) == "adjudicated"
    finally:
        engine.dispose()


def test_verify_finds_an_edited_entry_a_gap_and_a_broken_link():
    # On a fresh SQLite database whose triggers are dropped, as an operator with DDL rights could (R-22's residual).
    from sqlalchemy.pool import StaticPool

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    try:
        Base.metadata.create_all(engine)
        run_schema_upgrades(engine)
        factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        with factory() as db:
            for index in range(4):
                append_gold(db, label("v3i-" + f"{index}" * 24), now=NOW + timedelta(seconds=index))
            db.commit()
        with engine.begin() as connection:
            for name in ("v3_gold_labels_no_update", "v3_gold_labels_no_delete", "v3_gold_labels_links_to_chain"):
                connection.exec_driver_sql(f"DROP TRIGGER {name}")
        with factory() as db:
            edited = json.loads(db.scalar(select(V3GoldLabelRecord.entry).where(V3GoldLabelRecord.seq == 2)))
            edited["abstention_label"] = "missed_answer"
            db.execute(text("UPDATE v3_gold_labels SET entry = :entry WHERE seq = 2"), {"entry": ledger_canonical(edited).decode()})
            db.commit()
            assert "seq 2 entry does not match its entry_sha256" in verify_gold_store(db).problems
            db.execute(text("UPDATE v3_gold_labels SET entry_sha256 = :digest WHERE seq = 2"), {"digest": sha256_hex(ledger_canonical(edited))})
            db.commit()
            assert "seq 2 does not match its record_hash" in verify_gold_store(db).problems
            db.execute(text("DELETE FROM v3_gold_labels WHERE seq = 3"))
            db.commit()
            problems = verify_gold_store(db).problems
            assert "seq 3 to 3 missing" in problems and "seq 4 does not chain onto seq 2" in problems
    finally:
        engine.dispose()


def test_export_writes_the_applied_finals_or_every_row_and_refuses_the_application_tree_and_the_repository(tmp_path):
    from sqlalchemy.pool import StaticPool

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    try:
        Base.metadata.create_all(engine)
        run_schema_upgrades(engine)
        factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        with factory() as db:
            seq, _ = append_gold(db, label("v3i-" + "a" * 24), now=NOW)
            append_gold(db, label("v3i-" + "b" * 24), now=NOW)
            db.execute(insert(V3QueueItem).values(item_id="v3i-" + "a" * 24, ledger_seq=1, claim_key="", subject="response", record_kind="delivery",
                                                  response_digest="d" * 32, triggers="X6", reasons="", ehmf_types="", held=False, severity=1.0,
                                                  exposure=1, k=0.0, priority=1.0, state="applied", review_round=1, double_review=False,
                                                  enqueued_at=NOW, closed_at=NOW, final_gold_seq=seq, package_version="5.0.0", package_sha256="x"))
            db.commit()
            assert export_gold(db, tmp_path / "applied.jsonl") == 1
            assert export_gold(db, tmp_path / "all.jsonl", applied_only=False) == 2
            lines = [json.loads(line) for line in (tmp_path / "applied.jsonl").read_text(encoding="utf-8").splitlines()]
            assert lines[0]["seq"] == seq and lines[0]["entry"]["item_id"] == "v3i-" + "a" * 24 and set(lines[0]) == {"seq", "record_hash", "entry", "created_at"}
            from pathlib import Path

            import app as application

            with pytest.raises(ValueError):
                export_gold(db, Path(application.__file__).resolve().parent / "gold.jsonl")
            # Plan L627-628: gold labels "MUST NOT enter the public repository": no path inside the checkout is written.
            from app.services.v3.gold import refused_export_roots

            repository = Path(__file__).resolve().parents[3]
            if (repository / ".git").exists():                  # a checkout (CI and the workstation); an archive has none
                for target in (repository / "gold.jsonl", repository / "apps" / "api" / "gold.jsonl", repository / "docs" / "gold" / "gold.jsonl"):
                    try:
                        with pytest.raises(ValueError, match="repository checkout"):
                            export_gold(db, target, applied_only=False)
                        assert not target.exists(), target
                    finally:                                    # an export that was let through never stays in the checkout
                        target.unlink(missing_ok=True)
                        if target.parent.name == "gold" and target.parent.exists():
                            target.parent.rmdir()
                assert not (repository / "docs" / "gold").exists()
            checkout = tmp_path / "checkout"
            (checkout / ".git").mkdir(parents=True)
            module = checkout / "apps" / "api" / "app" / "services" / "v3" / "gold.py"
            assert refused_export_roots(module) == (checkout / "apps" / "api" / "app", checkout)
            assert refused_export_roots(tmp_path / "image" / "app" / "services" / "v3" / "gold.py") == (tmp_path / "image" / "app",)
    finally:
        engine.dispose()
