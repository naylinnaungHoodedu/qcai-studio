"""Legacy citation migration units (plan Phase 2 task 2.3, G; decision D3; spec 3.8, 2.7)."""

from __future__ import annotations

import json

import pytest

from app.core.config import Settings
from app.services.citation_migration import (
    MatchIndex,
    build_match_index,
    classify_citation,
    is_canonical_json_text,
    wilson_interval,
)
from app.services.provenance import UNRESOLVED_LABEL
from app.services.spans import SpanRecord, SpanRegistry, content_hash, legacy_excerpt_keys, span_id_for
from app.workers import migrate_citations as worker
from evaluation.qcai_eval import statistics


def record(item_id: str, text: str, start: int = 0, *, source_title: str = "Source", section_title: str = "Section") -> SpanRecord:
    digest = content_hash(text)
    return SpanRecord(span_id_for(item_id, start, start + len(text), digest), "span-v2", item_id, "sha256:" + "0" * 16, "document",
                      "public", 0, section_title, source_title, f"{item_id}.docx", start, start + len(text), digest, text, legacy_excerpt_keys(text))


def index_of(*records: SpanRecord) -> MatchIndex:
    class _NoDatabase:
        def scalars(self, _statement):
            return type("Rows", (), {"all": staticmethod(lambda: [])})()

    return build_match_index(_NoDatabase(), SpanRegistry(records))


def legacy(excerpt: str, **extra) -> dict:
    return {"chunk_id": "lesson:doc:1", "source_title": "Source", "source_kind": "document", "section_title": "Section",
            "excerpt": excerpt, "timestamp_label": None, **extra}


SETTINGS = Settings()


def classify(raw, index):
    return classify_citation(raw, index, corpus_version="corpus-test", settings=SETTINGS)


def test_a_unique_excerpt_hash_migrates_and_keeps_the_original():
    span = record("doc-a", "Routing adds SWAP gates.")
    original = legacy("Routing adds   SWAP gates.", span_id="span-" + "a" * 64)
    new, outcome, diagnostics = classify(original, index_of(span))
    assert outcome == "migrated"
    assert (new["span_id"], new["chunk_id"], new["content_hash"], new["citation_schema"]) == (span.span_id, span.span_id, span.content_hash, 2)
    assert (new["legacy_chunk_id"], new["legacy_span_id"], new["legacy_original"]) == ("lesson:doc:1", "span-" + "a" * 64, original)
    assert (new["resolution"], new["migration_status"], new["provisional"]) == ("resolved", "migrated", True)
    assert diagnostics["title_equal"] is True


def test_ambiguous_and_unmatched_excerpts_stay_legacy_unresolved():
    twin_a, twin_b = record("doc-a", "Same text."), record("doc-b", "Same text.")
    ambiguous, outcome, _ = classify(legacy("Same text."), index_of(twin_a, twin_b))
    assert outcome == "legacy_unresolved:excerpt_ambiguous"
    assert (ambiguous["resolution"], ambiguous["label"], ambiguous["provisional"]) == ("legacy_unresolved", UNRESOLVED_LABEL, True)
    _, outcome, _ = classify(legacy("Nothing like it."), index_of(twin_a))
    assert outcome == "legacy_unresolved:excerpt_no_match"


def test_diagnostics_never_change_the_outcome():
    span = record("doc-a", "Routing adds SWAP gates.", source_title="Another title")
    contains = record("doc-b", "Before. Routing adds SWAP gates. After.")
    new, outcome, diagnostics = classify(legacy("Routing adds SWAP gates.", content_hash="f" * 64), index_of(span, contains))
    assert outcome == "migrated" and new["span_id"] == span.span_id
    assert diagnostics["title_equal"] is False and diagnostics["v1_content_hash_agrees"] is False
    assert diagnostics["containment_also_in_other_span"] is True


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        (legacy("A chapter summary.", source_kind="video", timestamp_label="01:10"), "chapter_summary_excluded"),
        (legacy("   "), "missing_excerpt"),
        ({"source_title": "no id or excerpt"}, "invalid_shape"),
    ],
)
def test_video_blank_and_malformed_citations_are_labelled(raw, reason):
    new, outcome, _ = classify(raw, index_of(record("doc-a", "A chapter summary.")))
    assert outcome == f"legacy_unresolved:{reason}" and new["unresolved_reason"] == reason and new["legacy_original"] == raw


def test_v2_citations_are_never_rewritten():
    span = record("doc-a", "Routing adds SWAP gates.")
    index = index_of(span)
    migrated, _, _ = classify(legacy("Routing adds SWAP gates."), index)
    assert classify(migrated, index)[1] == "already_migrated" and classify(migrated, index)[0] is migrated
    native = {**legacy("x"), "chunk_id": span.span_id, "span_id": span.span_id, "content_hash": span.content_hash,
              "citation_schema": 2, "resolution": "resolved", "migration_status": "native"}
    assert classify(native, index)[1] == "native_v2"
    assert classify({**native, "content_hash": "0" * 64}, index)[1] == "native_unresolved"
    unresolved, _, _ = classify(legacy("Nothing like it."), index)
    assert classify(unresolved, index)[1] == "already_unresolved"  # monotonic: never revisited


def test_the_canonical_json_precondition():
    value = [{"chunk_id": "a", "excerpt": "café"}]
    assert is_canonical_json_text(json.dumps(value))
    assert not is_canonical_json_text(json.dumps(value, separators=(",", ":")))
    assert not is_canonical_json_text(json.dumps(value, ensure_ascii=False))
    assert not is_canonical_json_text("not json")


def test_the_wilson_interval_equals_the_evaluation_harness():
    for successes, total in ((0, 0), (0, 10), (3, 10), (10, 10), (17, 412)):
        assert wilson_interval(successes, total) == statistics.wilson_interval(successes, total)


def test_the_worker_reports_usage_errors_with_exit_2(capsys):
    assert worker.main(["--tables", "learner_records"]) == 2
    with pytest.raises(SystemExit) as raised:
        worker.main(["--apply", "--downgrade"])
    assert raised.value.code == 2


def test_the_worker_dry_run_prints_a_count_only_report(tmp_path, capsys, monkeypatch, fresh_database_url):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.core.db import Base
    from app.core.schema_upgrades import run_schema_upgrades
    from app.db_models import QAInteraction

    engine = create_engine(fresh_database_url)
    try:
        Base.metadata.create_all(engine)
        run_schema_upgrades(engine)
        sessions = sessionmaker(bind=engine)
        with sessions() as db:
            db.add(QAInteraction(user_id="worker-test-learner", question="q", answer="a", citations=[legacy("A distinctive stored excerpt.")]))
            db.commit()
        monkeypatch.setattr(worker, "SessionLocal", sessions)
        report_path = tmp_path / "report.json"
        assert worker.main(["--dry-run", "--report", str(report_path)]) == 0
    finally:
        engine.dispose()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["report"] == "qcai-citation-migration" and report["mode"] == "dry-run"
    assert set(report["tables"]) == {"qa_interactions", "tutor_turns"}
    assert set(report["totals"]) >= {"legacy_citations", "migrated", "legacy_unresolved", "unresolved_share", "native_unresolved", "exact_match_regressions"}
    assert report["totals"]["legacy_unresolved"] == 1 and report["totals"]["unresolved_share"] == 1.0
    assert report["threshold"]["decision"] == "D-30" and report["threshold"]["status"] == "provisional"
    assert report["span_sources"]["memory_spans"] > 1000  # every public-plane, bound document on disk plus the authored item
    text = report_path.read_text(encoding="utf-8")
    assert "worker-test-learner" not in text and "distinctive stored excerpt" not in text  # counts only
