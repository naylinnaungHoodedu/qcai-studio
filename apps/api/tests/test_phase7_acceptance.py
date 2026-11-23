"""Phase 7 acceptance: EHMF operationalization (plan Phase 7 K AC-7-1 to AC-7-6, and the plan F, G, H, I, J, L, P rows;
Phase 7 spec 13.1). Development pipelines over the development store and fake adapters, fresh databases, temporary
package copies and the committed records; nothing is written into the checkout.
"""

from __future__ import annotations

import ast
import json
import logging
from pathlib import Path
import re
import subprocess
import sys

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.config_package import (
    DEFAULT_PACKAGE_PATH,
    V5_PACKAGE_PATH,
    ConfigPackageError,
    get_config_package,
    load_config_package,
)
from app.core.structured_logging import FIELDS
from app.services import ehmf
from app.services.ehmf import vocabulary
from app.services.ehmf.conflicts import SourceMetadata, precedence
from app.services.ehmf.correction import CorrectionGuard, CorrectionLimit
from app.services.ledger import config_version_of
from app.services.tutor_pipeline.contracts import LedgerEntryV3, LedgerEntryV4, VerificationRecordV4
from ehmf_fakes import (
    INVENTED,
    REPO_ROOT,
    TIER2,
    UnresolvableThenCleanGenerator,
    ehmf_settings,
    leaking_alignment,
    negating_generator,
    package_copy,
    scripted_adapters,
    scripts_module,
    typed_record,
)

API_ROOT = REPO_ROOT / "apps" / "api"
SPEC_PATH = REPO_ROOT / "docs" / "architecture" / "phase7-implementation-spec.md"
RECORD = REPO_ROOT / "docs" / "evaluation" / "phase7" / "golden_run_v1.json"
GOLDEN = REPO_ROOT / "docs" / "evaluation" / "phase7" / "golden_set_v1.json"
PACKAGE = get_config_package(Settings())


def spec_text() -> str:
    return SPEC_PATH.read_text(encoding="utf-8")


def refused(model, payload: dict, edit, match: str) -> None:
    import copy

    changed = copy.deepcopy(payload)
    edit(changed)
    with pytest.raises(ValidationError, match=match):
        model.model_validate(changed)


def all_types(record) -> set[str]:
    return {f.type for claim in record.ehmf.claims for f in claim.findings} | {f.type for f in record.ehmf.response_findings}


# ===================================================================================================== AC-7-1


def test_ac_7_1_a_negated_claim_fixture_is_tagged_type_a_and_not_delivered():
    from app.services.tutor_pipeline.bind import claim_id_for
    from v1_fakes import AlwaysContradictedChecker

    for mode in ("on", "shadow"):
        generator = negating_generator()
        result = typed_record(settings=ehmf_settings(mode), generator=generator)
        record = result.entry.verification
        assert result.entry.entry_schema == "ledger-entry-v4" and isinstance(record, VerificationRecordV4)
        assert generator.attacked is not None
        text, spans = generator.attacked
        claim_id = claim_id_for(text, spans)
        dropped = [f for f in record.ehmf.response_findings if f.source == "V1.2" and f.claim_id == claim_id]
        assert [(f.reason_code, f.type) for f in dropped] == [("negation_mismatch", "A")]
        assert claim_id not in {verdict.claim_id for verdict in record.verdicts}
        assert claim_id not in set(result.entry.presentation.rendered_claim_ids)
    # A verbatim claim the V1.3 checker contradicts: an A finding on its own entry, and it is not delivered (V2 shadow
    # keeps Phase 4's finals: a V1.3 flag withholds, D-20).
    result = typed_record(settings=Settings(model_gateway="shadow", ehmf="on"), checker=AlwaysContradictedChecker())
    record = result.entry.verification
    for claim, verdict in zip(record.ehmf.claims, record.verdicts):
        assert ("V1.3", "contradicted", "A") in {(f.source, f.reason_code, f.type) for f in claim.findings}
        assert verdict.final != "deliver"


# ===================================================================================================== AC-7-2


def test_ac_7_2_an_unresolvable_citation_is_b1_final_whatever_the_votes_or_a_gold_label():
    supported = scripted_adapters(("SUPPORTED", None))
    # (a) every candidate cites an invented id, and every panel member would vote SUPPORTED
    result = typed_record(generator=UnresolvableThenCleanGenerator(always=True), adapters=supported)
    record = result.entry.verification
    assert record.final == "abstain" and record.hard_fail is True
    b1 = [f for f in record.ehmf.response_findings if f.type == "B1"]
    assert sorted({f.attempt for f in b1}) == list(range(1, record.generation_attempts + 1)) and record.generation_attempts >= 2
    assert all(verdict.v2 is None for verdict in record.verdicts) and record.v2.calls == 0
    # (b) attempt 1 has one invented citation among valid claims: the whole candidate is discarded, attempt 2 is judged
    # from the start, and the record keeps the attempt-1 B1 finding (rule 3 reads the accepted attempt)
    result = typed_record(generator=UnresolvableThenCleanGenerator(), adapters=supported)
    record = result.entry.verification
    assert record.generation_attempts == 2
    assert [(f.source, f.attempt) for f in record.ehmf.response_findings if f.type == "B1"] == [("V1.1", 1)]
    assert {r.attempt for r in record.checks if r.check_id == "V1.2"} == {2}
    assert INVENTED not in result.v1.locked.span_ids
    assert any(verdict.final == "deliver" for verdict in record.verdicts)
    LedgerEntryV4.model_validate(result.entry.model_dump(mode="json"))
    # (d) the contract refuses a delivered or voted B1, and a delivery while the accepted V1.1 result is B1
    good = result.entry.verification.model_dump(mode="json")

    def accepted_b1(raw):
        # the B1 result as if it were the accepted attempt's, while claims are delivered
        for check in raw["checks"]:
            if check["check_id"] == "V1.1":
                check.update(attempt=2, outcome="hard_fail", reason_code="unresolvable")
    refused(VerificationRecordV4, good, accepted_b1, "B1")

    def b1_on_delivered(raw):
        index = next(i for i, v in enumerate(raw["verdicts"]) if v["final"] == "deliver")
        claim = raw["ehmf"]["claims"][index]
        claim["findings"].append({"source": "V1.1", "reason_code": "unresolvable", "type": "B1", "attempt": 2, "claim_id": claim["claim_id"],
                                  "reported_type": None, "family": None})
        claim["primary"], claim["weight"] = "B1", "1"
    refused(VerificationRecordV4, good, b1_on_delivered, "B1 finding")


# ===================================================================================================== AC-7-3


def _conflict_run(case_id: str = "conflict-version-01"):
    fixtures_module = scripts_module("run_v1_fixtures")
    golden = scripts_module("run_golden_set")
    fixtures = fixtures_module.load_fixtures(fixtures_module.DEFAULT_FIXTURES)
    case = next(case for case in fixtures["cases"] if case["id"] == case_id)
    env = fixtures_module.gate_environment("bm25f-v1")
    settings = golden._settings(env, DEFAULT_PACKAGE_PATH)
    v1 = fixtures_module.overlay_v1(PACKAGE, fixtures.get("fixture_package") or {})
    from v3_fakes import fresh_v3_sessions

    with fresh_v3_sessions() as (factory, _engine):
        _row, result = fixtures_module.run_pipeline_case(case, env, v1, "deterministic_only", fixtures, settings=settings,
                                                         pipeline_options=golden._options(PACKAGE, settings, factory))
    return result


def test_ac_7_3_contradicting_spans_are_disclosed_and_the_disclosed_conflict_weighs_zero():
    from app.services.v3 import triggers

    result = _conflict_run()
    record = result.entry.verification
    assert record.disclosure is not None and record.disclosure.policy == "disclose"
    disclosure = record.ehmf.disclosure
    assert disclosure.template == "conflict-disclosure-v2"
    items = {item for conflict in record.ehmf.conflicts for item in conflict.item_ids}
    assert all(item in disclosure.text for item in items)
    for claim in result.v1.locked.claims:
        assert claim.text not in disclosure.text
    for conflict in record.ehmf.conflicts:
        assert conflict.disclosed and conflict.d_weight == "0" and conflict.winner_item_id is None and conflict.basis == "metadata_incomplete"
    named = {claim_id for conflict in record.ehmf.conflicts for claim_id in conflict.claim_ids}
    for claim in record.ehmf.claims:
        has_d = any(f.source == "V1.7" for f in claim.findings)
        assert has_d == (claim.claim_id in named)
    # V3 severity: a disclosed conflict weighs nothing (triggers.claim_types excludes it)
    for verdict in record.verdicts:
        if verdict.claim_id in named:
            assert "D" not in triggers.claim_types(verdict)
    payload = record.model_dump(mode="json")

    def heavy(raw):
        raw["ehmf"]["conflicts"][0]["d_weight"] = "3/5"
    refused(VerificationRecordV4, payload, heavy, "D_disclosed")


# ===================================================================================================== AC-7-4


def test_ac_7_4_a_corrected_type_e_finding_leaves_the_claim_and_span_sets_unchanged():
    result = typed_record(adapters=leaking_alignment())
    record = result.entry.verification
    correction = record.ehmf.corrections[0]
    assert (correction.kind, correction.types, correction.outcome) == ("re_render", ("E",), "applied")
    assert correction.claim_set_after == correction.claim_set_before and correction.span_set_after == correction.span_set_before
    assert record.v2.corrections[0].revised_claim_ids == ()
    assert result.v1.locked.claim_set_hash == record.claim_set_hash


def test_ac_7_4_the_engine_refuses_a_re_render_that_changes_the_claim_or_span_set(monkeypatch, caplog):
    import dataclasses

    from app.services.v1_checks import runner

    other = typed_record("What is the difference between QAI and AI4QC?", settings=Settings(model_gateway="on", ehmf="off")).v1.locked
    original = runner.V1Track._render

    def changed(self, ctx, state, generation, budget_over, stopwords, *, presentation=None, omit_extra=frozenset()):
        decision = original(self, ctx, state, generation, budget_over, stopwords, presentation=presentation, omit_extra=omit_extra)
        if presentation is not None and presentation.plan_id == self.v1.socratic_plan and isinstance(decision, runner.V1Passed):
            return dataclasses.replace(decision, locked=other, verdicts=())
        return decision

    monkeypatch.setattr(runner.V1Track, "_render", changed)
    with caplog.at_level(logging.WARNING, logger="qcai.tutor"):
        result = typed_record(adapters=leaking_alignment())
    record = result.entry.verification
    assert record.final == "abstain" and record.final_reason == "ehmf_set_changed"
    assert [c.outcome for c in record.ehmf.corrections][-1] == "refused_set_changed"
    assert all(verdict.final == "abstain" for verdict in record.verdicts)
    LedgerEntryV4.model_validate(result.entry.model_dump(mode="json"))
    assert any(getattr(r, FIELDS, {}).get("event") == "tutor.ehmf.correction_refused" and getattr(r, FIELDS).get("reason") == "set_changed"
               for r in caplog.records)
    monkeypatch.undo()
    good = typed_record(adapters=leaking_alignment()).entry.verification.model_dump(mode="json")

    def drift(raw):
        raw["ehmf"]["corrections"][0]["span_set_after"] = "0" * 64
    refused(VerificationRecordV4, good, drift, "keeps the claim set and the span set")


# ===================================================================================================== AC-7-5


def test_ac_7_5_a_third_correction_attempt_is_refused_the_claim_abstains_and_x2_is_emitted(monkeypatch, caplog, tmp_path):
    from app.services.ehmf import correction as correction_module
    from v3_fakes import NoCache

    asked: list[int] = []
    original = correction_module.CorrectionGuard.begin_cycle

    def spy(self, next_cycle):
        asked.append(next_cycle)
        return original(self, next_cycle)

    monkeypatch.setattr(correction_module.CorrectionGuard, "begin_cycle", spy)
    with caplog.at_level(logging.WARNING, logger="qcai.tutor"):
        result = typed_record(adapters=scripted_adapters(("NOT_ENOUGH_INFO", "C")), cache=NoCache())
    record = result.entry.verification
    assert record.v2.cycles == 2 and 3 in asked
    assert any(getattr(r, FIELDS, {}).get("reason") == "cycle_limit" for r in caplog.records)
    x2 = [verdict.claim_id for verdict in record.verdicts if verdict.v3 is not None and verdict.v3.escalation == "X2"]
    assert x2 and record.ehmf.x2_emitted == tuple(sorted(x2))
    assert all(verdict.final == "abstain" for verdict in record.verdicts if verdict.claim_id in x2)
    with pytest.raises(CorrectionLimit):
        CorrectionGuard(max_cycles=2).begin_cycle(3)
    # x-triggers-v2: the scan queues an X2 item for an exhausted claim whose reported type is C
    from sqlalchemy import select

    from app.db_models import V3QueueItem
    from app.services.v3.scan import run_scan
    from v3_fakes import append_all, dev_settings, fresh_v3_sessions

    with fresh_v3_sessions() as (factory, _engine):
        append_all(factory, [result.entry])
        run_scan(settings=dev_settings(v3_queue="shadow"), package=PACKAGE, session_factory=factory)
        with factory() as db:
            triggers = {row.claim_key: row.triggers for row in db.execute(select(V3QueueItem)).scalars()}
    assert all("X2" in triggers.get(claim_id, "") for claim_id in x2)
    # the loader refuses a third cycle in the package
    copy = package_copy(tmp_path, lambda raw: raw["v2"]["correction"].update(max_cycles=3))
    with pytest.raises(ConfigPackageError):
        load_config_package(copy, governed=False)


# ===================================================================================================== AC-7-6


def test_ac_7_6_a_package_edit_without_a_golden_set_run_fails_the_ci_check(tmp_path, capsys):
    from v3_fakes import repository_tree, tree_changes

    before = repository_tree()
    golden = scripts_module("run_golden_set")
    copy = package_copy(tmp_path / "a", lambda raw: raw["ehmf"]["stop"].update(window_claims=201))
    assert golden.main(["--check", str(RECORD), "--package", str(copy)]) == 6
    assert "config_package sha256 differs" in capsys.readouterr().err
    edited = package_copy(tmp_path / "b", library_edit=lambda raw: raw.update(status=raw["status"] + " (edited)"))
    assert golden.main(["--check", str(RECORD), "--package", str(edited)]) == 6
    assert "misconception_library sha256 differs" in capsys.readouterr().err
    assert golden.main(["--check", str(RECORD)]) == 0
    completed = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "run_golden_set.py"), "--check", str(RECORD), "--package", str(copy)],
                               cwd=REPO_ROOT, capture_output=True, text=True, timeout=300)
    assert completed.returncode == 6
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "python scripts/run_golden_set.py --check docs/evaluation/phase7/golden_run_v1.json" in workflow
    assert tree_changes(before, repository_tree()) == []


# ===================================================================================================== plan J


def test_plan_j_fixtures_per_type_are_typed_as_the_routing_table_says():
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    golden = {item["id"]: item for item in json.loads(GOLDEN.read_text(encoding="utf-8"))["items"]}
    expected = {"negation": "A", "invented_citation": "B1", "non_supporting_citation": "B2", "misconception": "C", "conflict": "D", "leakage": "E"}
    seen = set()
    for outcome in record["outcomes"]:
        item = golden[outcome["id"]]
        if item["class"] in expected:
            assert expected[item["class"]] in outcome["types"] and outcome["met"] and not outcome["delivered"], outcome
            seen.add(item["class"])
    assert seen == set(expected)
    assert record["result"] == "pass"


@pytest.mark.parametrize("detector", ["V1.1", "V1.7", "V1.8", "V2", "alignment"])
def test_plan_j_detector_down_withholds_the_claim(detector, monkeypatch, caplog):
    from app.services.v1_checks import runner
    from app.services.v2_panel.track import V2Track

    def boom(*args, **kwargs):
        raise RuntimeError("detector fault")

    library = None
    if detector == "V1.1":
        monkeypatch.setattr(runner, "check_v1_1", boom)
    elif detector == "V1.7":
        monkeypatch.setattr(runner, "check_v1_7", boom)
    elif detector == "V1.8":
        from app.services.v1_checks.v1_8_misconceptions import MisconceptionLibrary

        library = MisconceptionLibrary(version="down", sha256="0" * 64, entries=(), available=False)
    elif detector == "V2":
        monkeypatch.setattr(V2Track, "consult", boom)
    else:
        monkeypatch.setattr(V2Track, "align", boom)
    with caplog.at_level(logging.WARNING, logger="qcai.tutor"):
        result = typed_record(library=library)
    record = result.entry.verification
    assert record.final == "abstain" and record.final_reason == "ehmf_detector_down"
    assert record.ehmf.detector_down == (detector,)
    assert not any(verdict.final == "deliver" for verdict in record.verdicts)
    assert [r for r in caplog.records if getattr(r, FIELDS, {}).get("event") == "tutor.ehmf.detector_down"]


def test_plan_j_a_raising_checker_keeps_checker_unavailable_and_off_keeps_phase_6(monkeypatch):
    from app.services.v1_checks import runner
    from v1_fakes import RaisingChecker

    record = typed_record(checker=RaisingChecker()).entry.verification
    assert record.final_reason == "checker_unavailable" and record.ehmf.detector_down == ("V1.3",)
    monkeypatch.setattr(runner, "check_v1_1", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("fault")))
    with pytest.raises(RuntimeError):
        typed_record(settings=ehmf_settings("off"))


# ===================================================================================================== plan H, task 2


def test_plan_h_the_library_holds_public_corpus_paraphrases_edited_only_by_the_content_owner_or_v3(tmp_path):
    from app.services.ehmf.library import library_problems
    from app.services.store import get_course_store
    from app.services.v1_checks.v1_8_misconceptions import load_library
    from app.workers import ehmf as worker

    shipped = json.loads((DEFAULT_PACKAGE_PATH.parent / "misconceptions" / "v1.json").read_text(encoding="utf-8"))
    assert shipped["entries"] == [] and shipped["synthetic"] is False and load_library(PACKAGE).entries == ()
    store = get_course_store()
    span_id = store.chunks[0].span_id
    text = store.span_registry.get(span_id).text
    entry = {"id": "mc-one", "terms": ["alpha", "beta"], "paraphrase": "A short public paraphrase of the idea.", "span_ids": [span_id],
             "editor": "content_owner", "edited": "2026-11-23"}
    base = {**shipped, "entries": [entry]}
    assert library_problems(base, store=store, shipped=False) == []
    assert library_problems({**base, "entries": [{**entry, "editor": "v3:" + "a" * 64}]}, store=store, shipped=False) == []
    assert any("editor" in p for p in library_problems({**base, "entries": [{**entry, "editor": "engineer"}]}, store=store, shipped=False))
    assert any("does not resolve" in p for p in library_problems({**base, "entries": [{**entry, "span_ids": ["span-" + "9" * 64]}]},
                                                                  store=store, shipped=False))
    words = re.findall(r"[^\W_]+", text)[:9]
    if len(words) == 9:
        copied = {**entry, "paraphrase": " ".join(words)[:280]}
        assert any("consecutive words" in p for p in library_problems({**base, "entries": [copied]}, store=store, shipped=False))
    assert any("synthetic" in p for p in library_problems({**base, "synthetic": True}, store=None, shipped=True))
    before = (DEFAULT_PACKAGE_PATH.parent / "misconceptions" / "v1.json").read_bytes()
    assert worker.main(["export-library-proposals", "--path", str(tmp_path / "proposals.jsonl")]) == 0
    assert worker.main(["export-library-proposals", "--path", str(REPO_ROOT / "proposals.jsonl")]) == 2
    assert not (REPO_ROOT / "proposals.jsonl").exists()
    assert (DEFAULT_PACKAGE_PATH.parent / "misconceptions" / "v1.json").read_bytes() == before


# ===================================================================================================== task 3


def test_plan_task_3_precedence_never_picks_with_incomplete_metadata():
    import itertools

    from app.core.manifest_v2 import source_metadata_problems

    full = SourceMetadata(2024, True, "primary")
    for year, reviewed, role in itertools.product((None, 2020), (None, True), (None, "secondary")):
        partial = SourceMetadata(year, reviewed, role)
        if not partial.complete():
            assert precedence(full, partial, item_a="a", item_b="b").basis == "metadata_incomplete"
            assert precedence(partial, full, item_a="a", item_b="b").winner_item_id is None
    assert precedence(SourceMetadata(2024, True, "primary"), SourceMetadata(2020, True, "primary"), item_a="a", item_b="b").basis == "newer_peer_reviewed"
    assert precedence(SourceMetadata(2020, False, "primary"), SourceMetadata(2024, False, "secondary"), item_a="a", item_b="b").basis == "primary_over_secondary"
    assert precedence(SourceMetadata(2024, True, "primary"), SourceMetadata(2020, True, "secondary"), item_a="a", item_b="b").basis == "both_rules"
    assert precedence(SourceMetadata(2020, True, "primary"), SourceMetadata(2024, True, "secondary"), item_a="a", item_b="b").basis == "rules_disagree"
    assert precedence(SourceMetadata(2020, False, "primary"), SourceMetadata(2024, False, "primary"), item_a="a", item_b="b").basis == "no_rule_applies"
    manifest = json.loads((REPO_ROOT / "corpus" / "public" / "manifest.json").read_text(encoding="utf-8"))
    assert all(not ({"source_year", "peer_reviewed", "source_role"} & set(item)) for item in manifest["items"])
    partial_manifest = {"items": [{**manifest["items"][0], "source_year": 2024}]}
    assert source_metadata_problems(partial_manifest)
    # recorded only: with complete metadata a winner is recorded and the finals equal the no-metadata finals
    without = _conflict_run().entry.verification
    from app.services.v1_checks import runner

    items = {item for conflict in without.ehmf.conflicts for item in conflict.item_ids}
    metadata = {item: {"source_year": 2020 + index, "peer_reviewed": True, "source_role": "primary"} for index, item in enumerate(sorted(items))}
    original = runner._manifest_of
    runner._manifest_of = lambda pipeline: metadata
    try:
        with_metadata = _conflict_run().entry.verification
    finally:
        runner._manifest_of = original
    assert all(conflict.winner_item_id is not None for conflict in with_metadata.ehmf.conflicts)
    assert [v.final for v in with_metadata.verdicts] == [v.final for v in without.verdicts] and with_metadata.final == without.final


# ===================================================================================================== plan G


def test_plan_g_earlier_ledger_rows_read_as_config_version_pre_phase_7(tmp_path):
    from app.services import ledger
    from tutor_fakes import make_entry
    from v3_fakes import append_all, fresh_v3_sessions

    assert config_version_of({"config_package_version": "5.0.0"}) == "pre-phase-7"
    assert config_version_of({"config_package_version": "6.0.1"}) == "6.0.1"
    assert config_version_of({"config_package_version": "bad"}) == "pre-phase-7" and config_version_of(None) == "pre-phase-7"
    legacy = make_entry("turn-00000000-0000-0000-0000-000000000001")
    legacy5 = legacy.model_copy(update={"versions": legacy.versions.model_copy(update={"config_package_version": "5.0.0"})})
    typed = typed_record().entry
    payload = typed_record("What is the difference between QAI and AI4QC?").entry.model_dump(mode="json")
    payload["verification"]["ehmf"]["weights"] = {**payload["verification"]["ehmf"]["weights"], "E": "1/2"}
    for claim in payload["verification"]["ehmf"]["claims"]:
        from app.services.tutor_pipeline.contracts import EhmfFinding, primary_of

        claim["primary"], claim["weight"] = primary_of([EhmfFinding(**f) for f in claim["findings"]], payload["verification"]["ehmf"]["weights"])
    reweighted = LedgerEntryV4.model_validate(payload)
    with fresh_v3_sessions() as (factory, _engine):
        append_all(factory, [legacy5, typed, reweighted])
        with factory() as db:
            assert ledger.verify_response_ledger(db).ok
            path = tmp_path / "export.jsonl"
            ledger.export_ledger(db, path)
    versions = [json.loads(line)["config_version"] for line in path.read_text(encoding="utf-8").splitlines()]
    assert versions == ["pre-phase-7", "6.0.0", "6.0.0"]


def test_plan_g_v5_stays_readable_and_v6_parses_v1_to_v4_records():
    from app.services.tutor_pipeline.package_check import check_tutor_pipeline_package

    v5 = load_config_package(V5_PACKAGE_PATH, governed=True)
    assert v5.v3.trigger_registry_version == "x-triggers-v1" and v5.ehmf is None
    assert check_tutor_pipeline_package(v5, structural=True) == []
    v4 = load_config_package(V5_PACKAGE_PATH.with_name("v4.json"), governed=True)
    assert check_tutor_pipeline_package(v4, structural=True) == []
    assert DEFAULT_PACKAGE_PATH.name == "v6.json" and PACKAGE.package_version == "6.0.0" and PACKAGE.v3.trigger_registry_version == "x-triggers-v2"
    assert check_tutor_pipeline_package(PACKAGE, structural=True) == []


# ===================================================================================================== plan I


def test_plan_i_ready_reports_config_version_and_the_ehmf_fields_and_no_count():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        body = client.get("/ready").json()
    assert body["config_package_version"] == "6.0.0" and body["config_version"] == "6.0.0"
    assert {"ehmf_mode", "ehmf_setting", "phase7_exit_passed", "ehmf"} <= set(body) and body["phase7_exit_passed"] is False
    fields = body["ehmf"]
    assert fields["routing"] == "ehmf-routing-v1" and fields["weights"]["D_disclosed"] == "0" and fields["weights"]["C"] == "3/5"
    assert fields["library"]["entries"] == 0 and fields["golden_set"]["items"] == 40 and fields["max_cycles"] == 2
    assert set(fields["stop"]) == {"revert_required"}
    flat = json.dumps(fields)
    assert "count" not in flat and "rate" not in flat


def test_plan_i_per_type_rates_disclosure_share_and_correction_cycles():
    from app.services.ehmf.metrics import EVIDENCE_CLASS, slis
    from v3_fakes import append_all, fresh_v3_sessions

    entries = [typed_record(generator=UnresolvableThenCleanGenerator(always=True)).entry,
               typed_record(adapters=scripted_adapters(("CONTRADICTED", "A"))).entry]
    with fresh_v3_sessions() as (factory, _engine):
        append_all(factory, entries)
        with factory() as db:
            body = slis(db, PACKAGE)
    group = body["by_config_version"]["6.0.0"]
    assert group["per_100_responses"]["B1"] == "1/2" and group["per_100_responses"]["responses"] == 2
    claims = group["per_100_claims"]["claims"]
    assert claims >= 1 and group["per_100_claims"]["A"].endswith(f"/{claims}")
    assert group["correction_cycles"]["exhausted"] == 1 and group["x2_emissions"] >= 1
    assert body["evidence_class"] == EVIDENCE_CLASS and body["config_version"] == "6.0.0"


# ===================================================================================================== plan L


def test_plan_l_a_rising_a_b_rate_after_a_change_requires_a_revert_and_raises_the_audit_to_one_fifth(tmp_path):
    from datetime import UTC, datetime

    from app.services.ehmf.stop import _fires, detect, stop_state
    from v3_fakes import fresh_v3_sessions

    copy = package_copy(tmp_path, lambda raw: raw.update(package_version="6.0.1"))
    package601 = load_config_package(copy, governed=False)
    params = PACKAGE.ehmf
    assert _fires(120, 2, 100, 10, params) and not _fires(120, 2, 100, 1, params) and not _fires(0, 0, 100, 10, params)
    assert not _fires(120, 20, 100, 10, params)
    with fresh_v3_sessions() as (factory, _engine):
        _seed_stop_simple(factory)
        with factory() as db:
            seq = detect(db, package601, now=datetime.now(UTC))
            db.commit()
        assert seq is not None
        with factory() as db:
            state = stop_state(db, package601)
            assert state.revert_required is True and state.reason == "rising_ab"
            assert detect(db, package601, now=datetime.now(UTC)) is None
            from app.services.v3.scan import open_windows

            assert any(remaining > 0 for _start, remaining in open_windows(db))
            prior = stop_state(db, PACKAGE)
            assert prior.revert_required is False and prior.reason == "reverted"


def _seed_stop_simple(factory) -> None:
    """Typed rows: 60 records of 2 claims at 6.0.0 (one A/B record), then 50 at 6.0.1 (five A/B records)."""
    from app.services.ledger import append_ledger_entry

    clean = typed_record(settings=ehmf_settings("shadow")).entry.model_dump(mode="json")
    bad = typed_record(adapters=scripted_adapters(("CONTRADICTED", "A"))).entry.model_dump(mode="json")
    index = 0
    for version, count, ab in (("6.0.0", 60, 1), ("6.0.1", 50, 5)):
        for number in range(count):
            raw = json.loads(json.dumps(bad if number < ab else clean))
            index += 1
            raw["response_id"] = f"shadow-00000000-0000-0000-0000-{index:012d}"
            raw["shadowed_response_id"] = f"turn-00000000-0000-0000-0000-{index:012d}"
            for claim in raw["claims"]:
                claim["response_id"] = raw["response_id"]
            raw["versions"]["config_package_version"] = version
            raw["verification"]["ehmf"]["config_version"] = version
            append_ledger_entry(LedgerEntryV4.model_validate(raw), session_factory=factory, budget_ms=60000, attempts=3)


def test_plan_l_reloading_the_prior_package_clears_the_revert_state():
    from app.services.ehmf.stop import process_stop_state, reset_stop_cache

    reset_stop_cache()
    state = process_stop_state(Settings(environment="production", allowed_origins=["https://qantumlearn.academy"]), PACKAGE)
    assert state.revert_required is None and state.reason == "not_evaluated"


def test_plan_l_ehmf_defaults_and_refusals():
    assert Settings().ehmf == "shadow" and Settings(environment="production", allowed_origins=["https://qantumlearn.academy"]).ehmf == "off"
    with pytest.raises(ValidationError, match="EHMF=on is refused outside development"):
        Settings(environment="production", allowed_origins=["https://qantumlearn.academy"], ehmf="on")
    assert ehmf.mode(Settings(model_gateway="off"), PACKAGE) == "off"
    assert ehmf.mode(Settings(environment="production", allowed_origins=["https://qantumlearn.academy"]), PACKAGE) == "off"
    from app.core.config import EHMF_DEFAULT_DEVELOPMENT, EHMF_DEFAULT_ELSEWHERE

    assert PACKAGE.raw["flag_policy"]["ehmf"]["default_development"] == EHMF_DEFAULT_DEVELOPMENT
    assert PACKAGE.raw["flag_policy"]["ehmf"]["default_elsewhere"] == EHMF_DEFAULT_ELSEWHERE
    source = (API_ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert '("ehmf_shadow", settings.ehmf == "shadow")' in source and '("ehmf_on", settings.ehmf == "on")' in source


# ===================================================================================================== task 5


def test_plan_task_5_the_span_penalty_is_inert_outside_development_and_keeps_invariant_1(tmp_path):
    from app.services.content_assembler import _span_penalties
    from app.services.lexical_index import LexicalIndex
    from app.services.store import get_course_store

    store = get_course_store()
    queries = [item["query"] for item in json.loads((API_ROOT / "tests" / "data" / "score_floor_queries.json").read_text(encoding="utf-8"))["in_domain"][:20]]
    for settings in (Settings(ehmf="shadow"), Settings(ehmf="on", model_gateway="on"),
                     Settings(environment="production", allowed_origins=["https://qantumlearn.academy"])):
        assert _span_penalties(settings, PACKAGE) == {}
    assert PACKAGE.ehmf.penalty_factor("production") == 1 and PACKAGE.ehmf.penalty_factor("staging") == 1
    # A development copy with one penalised span: the shared index takes it under EHMF=on only.
    span_id = store.chunks[0].span_id
    copy = load_config_package(package_copy(tmp_path, lambda raw: raw["ehmf"]["retrieval_penalty"]["registries"]["development"].update(
        spans=[{"span_id": span_id, "reason": "B2", "gold": "synthetic"}])), governed=False)
    assert _span_penalties(Settings(ehmf="shadow"), copy) == {}
    assert _span_penalties(Settings(ehmf="on", model_gateway="on"), copy) == {span_id: copy.ehmf.penalty_factor("development")}
    assert _span_penalties(Settings(ehmf="on", model_gateway="off"), copy) == {}
    assert PACKAGE.ehmf.penalty_factor("development") == pytest.approx(0.5)
    for gate in ("bm25f-v1", "p1-floor"):
        plain = LexicalIndex(store.chunks, PACKAGE.retrieval, PACKAGE.abstention, gate=gate)
        empty = LexicalIndex(store.chunks, PACKAGE.retrieval, PACKAGE.abstention, gate=gate, penalties={})
        for query in queries:
            assert plain.evaluate(query) == empty.evaluate(query)
        top = next(decision for query in queries if (decision := plain.evaluate(query)).results and len(decision.results) > 1)
        demoted = top.results[0].entry.span_id
        from fractions import Fraction

        penalised = LexicalIndex(store.chunks, PACKAGE.retrieval, PACKAGE.abstention, gate=gate, penalties={demoted: Fraction(1, 1000)})
        query = next(query for query in queries if plain.evaluate(query) == top)
        result = penalised.evaluate(query)
        assert result.reason == top.reason and [r.entry.span_id for r in result.results][0] != demoted
        scores = {r.entry.span_id: r.score for r in plain.eligible_unfloored(query)} if gate == "bm25f-v1" else None
        if scores is not None:  # the ranking moved; the scores did not
            assert all(r.score == scores[r.entry.span_id] for r in result.results)
    # invariant 1: the mapping depends on span ids and the environment only (no learner input reaches it)
    import inspect

    assert list(inspect.signature(_span_penalties).parameters) == ["settings", "package"]
    with pytest.raises(ConfigPackageError):
        load_config_package(package_copy(Path(__import__("tempfile").mkdtemp()), lambda raw: raw["ehmf"]["retrieval_penalty"]["registries"]["staging"]
                                         .update(factor={"numerator": 1, "denominator": 2})), governed=False)


# ===================================================================================================== plan P (R-18)


def test_plan_p_the_source_fidelity_check_reports_the_quen_transposition():
    fidelity = scripts_module("check_source_fidelity")
    report = fidelity.compute()
    assert len(report["docx"]) == 12 and report["mismatches"] == 3
    values = {entry["id"]: (entry["docx_value"], entry["source_value"]) for entry in report["entries"]}
    assert values == {"quen-external-sensitivity": ("1.143", "0.828"), "quen-external-fp-rate": ("0.828", "1.143"),
                      "gea-alignment-wording": ("present", "GEA = 0.40")}
    committed = REPO_ROOT / "docs" / "evaluation" / "phase7" / "source_fidelity_report_v1.json"
    assert fidelity.main(["--check", str(committed)]) == 0
    assert fidelity.main(["--require-zero"]) == 7
    for path in (committed, REPO_ROOT / "docs" / "evaluation" / "phase7" / "source_fidelity_register.json"):
        def strings(value, key=None):
            if isinstance(value, dict):
                for k, v in value.items():
                    yield from strings(v, k)
            elif isinstance(value, list):
                for v in value:
                    yield from strings(v, key)
            elif isinstance(value, str):
                yield key, value
        assert all(len(text) <= 160 or key == "authority" for key, text in strings(json.loads(path.read_text(encoding="utf-8"))))


# ===================================================================================================== golden set, routing


def test_golden_set_is_public_or_synthetic_and_disjoint_from_ulqs():
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    fixtures = json.loads((REPO_ROOT / golden["phase4_fixtures"]).read_text(encoding="utf-8"))
    ids = {case["id"] for case in fixtures["cases"]}

    def norm(text: str) -> str:
        return " ".join(text.casefold().split())

    ulqs = set()
    for line in (REPO_ROOT / "lqs" / "manifest.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            for key in ("question", "prompt", "text", "query"):
                if isinstance(row.get(key), str):
                    ulqs.add(norm(row[key]))
    for item in golden["items"]:
        assert item["source"] == "synthetic" or item["source"].split(":", 1)[1] in ids
        assert norm(item["query"]) not in ulqs and "lqs/" not in json.dumps(item)
    covered = {t for item in golden["items"] for t in item["expect"]["types"]}
    assert covered == set(vocabulary.FINDING_TYPES)
    from app.core.config_package import canonical_sha256

    assert PACKAGE.ehmf.golden_set_sha256 == canonical_sha256(golden) and PACKAGE.ehmf.golden_set_items == len(golden["items"]) == 40


def test_plan_f_the_routing_document_matches_the_package():
    doc = (REPO_ROOT / "docs" / "architecture" / "ehmf-routing.md").read_text(encoding="utf-8")
    table = PACKAGE.raw["ehmf"]["routing"]["table"]
    weights = PACKAGE.ehmf.weight_strings()
    for name, row in table.items():
        line = next(line for line in doc.splitlines() if line.startswith(f"| {name} |"))
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        assert cells[1] == ", ".join(f"`{d}`" for d in row["detectors"])
        assert cells[2:5] == [row["mitigation"], row["owner"], f"`{row['telemetry']}`"]
        assert cells[5] == weights[vocabulary.TYPE_OF[name]] and cells[6] == ("yes" if row["final"] else "no")
    assert PACKAGE.ehmf.disclosure_template_text in doc


# ===================================================================================================== freeze


def test_freeze_outside_development_ehmf_is_off_and_no_learner_path_changes():
    production = Settings(environment="production", allowed_origins=["https://qantumlearn.academy"])
    staging = Settings(environment="staging", allowed_origins=["https://staging.example.test"], guest_token_secret="s" * 32)
    for settings in (production, staging):
        assert ehmf.mode(settings, PACKAGE) == "off" and settings.ehmf == "off"
    capture = scripts_module("capture_public_payloads")
    golden_path = API_ROOT / "tests" / "data" / "phase4_public_payloads_v1.json"
    assert capture.main(["--check", str(golden_path)]) == 0
    # development default (shadow): the learner-facing retrieval is the penalty-free index
    from app.services.store import get_course_store

    assert get_course_store().penalties == {}


# ===================================================================================================== vocabulary


def test_the_ehmf_vocabulary_lives_in_one_module():
    target = ("A", "B", "C", "D", "E")
    offenders = []
    for path in (API_ROOT / "app").rglob("*.py"):
        if path.as_posix().endswith("services/ehmf/vocabulary.py"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        for node in ast.walk(tree):
            if isinstance(node, (ast.Tuple, ast.List, ast.Set)) and all(isinstance(e, ast.Constant) for e in node.elts):
                if tuple(e.value for e in node.elts) == target and not isinstance(parents.get(node), ast.Subscript):
                    offenders.append(f"{path.relative_to(API_ROOT)}:{node.lineno}")
    assert offenders == []
    from app.services.v2_panel.rules import verifier_prompt_hash

    assert verifier_prompt_hash() == PACKAGE.raw["v2"]["prompt"]["verifier_prompt_hash"]
    v5 = json.loads(V5_PACKAGE_PATH.read_text(encoding="utf-8"))
    assert v5["v2"]["prompt"]["verifier_prompt_hash"] == verifier_prompt_hash()
    assert v5["tutor_pipeline"]["schemas"]["V2VerdictRequest"]["sha256"] == PACKAGE.raw["tutor_pipeline"]["schemas"]["V2VerdictRequest"]["sha256"]


# ===================================================================================================== plan E


def test_plan_e_the_phase_7_revision_is_additive_reversible_and_keeps_its_rows():
    from alembic.script import ScriptDirectory
    from alembic.config import Config

    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "alembic"))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["20261123_phase7_ehmf"]
    revision = script.get_revision("20261123_phase7_ehmf")
    assert revision.down_revision == "20261122_phase6_v3_audit"
    source = Path(revision.path).read_text(encoding="utf-8")
    assert "allow_ehmf_drop" in source and "v3_append_only" in source and "DROP FUNCTION" not in source
    from datetime import UTC, datetime

    from sqlalchemy import text

    from v3_fakes import fresh_v3_sessions

    with fresh_v3_sessions() as (factory, engine):
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO ehmf_stops (from_config_version, to_config_version, change_seq, detected_seq, before_claims, "
                                    "before_ab, after_claims, after_ab, window_deliveries, package_sha256, created_at) VALUES "
                                    "('6.0.0', '6.0.1', 1, 2, 3, 4, 5, 6, 7, :sha, :now)"), {"sha": "0" * 64, "now": datetime.now(UTC)})
        for statement in ("UPDATE ehmf_stops SET after_ab = 0", "DELETE FROM ehmf_stops"):
            with pytest.raises(Exception, match="append-only"):
                with engine.begin() as connection:
                    connection.execute(text(statement))


# ===================================================================================================== docs


def test_phase7_docs_quote_the_plan_and_state_the_current_rules():
    spec = spec_text()
    plan_p = ("AC-7-1 to AC-7-6 green; package v1 hash in the ledger; R-18 closure evidence in Section 5: corrected DOCX values and the "
              "source-fidelity CI job over the 12 DOCX passing (Phase 11 task 3 and AC-11-3 brought forward to this exit).")
    assert plan_p in spec
    adr = (REPO_ROOT / "docs" / "adr" / "ADR-010-ehmf-operationalization.md").read_text(encoding="utf-8")
    assert "[Risk R-16][Risk R-19][Risk R-46][Risk R-18]; residual: conflicts outside the corpus." in adr
    runbook = (REPO_ROOT / "infra" / "cloudrun" / "deployment.md").read_text(encoding="utf-8")
    assert "allow_ehmf_drop" in runbook and "## Phase 7: EHMF operationalization (runbook)" in runbook
    for text in (spec, runbook, (REPO_ROOT / "infra" / "cloudrun" / "api-production.env.example.yaml").read_text(encoding="utf-8")):
        assert "EHMF" in text
    for number in range(40, 50):
        assert f"PD-{number}" in spec
    for number in range(104, 114):
        assert f"DI-{number}" in spec


def test_phase7_docs_the_test_strategy_maps_every_test_module_the_phase_added():
    strategy = (REPO_ROOT / "docs" / "testing" / "test-strategy.md").read_text(encoding="utf-8")
    section = strategy.split("## Phase 7 acceptance map (plan Phase 7 K)", 1)[1]
    for name in ("test_phase7_acceptance.py", "test_ehmf_units.py", "ehmf_fakes.py"):
        assert f"`{name}`" in section
    assert "**Exit gate.**" in section and "The exit is not passed." in section


def test_phase7_spec_section_3_lists_the_code_s_fields():
    from app.services.tutor_pipeline import contracts

    block = spec_text().split("### 3.3", 1)[1].split("### 3.4", 1)[0]
    code = block.split("```python", 1)[1].split("```", 1)[0]
    classes = re.findall(r"^class (\w+)\(", code, flags=re.MULTILINE)
    assert classes
    for name in classes:
        documented = re.findall(r"^    (\w+): ", code.split(f"class {name}(", 1)[1].split("\nclass ", 1)[0], flags=re.MULTILINE)
        model = getattr(contracts, name)
        own = [field for field in model.model_fields if field in documented or field not in getattr(model.__mro__[1], "model_fields", {})]
        assert documented == own, name


def test_phase7_docs_the_spec_ends_in_one_review_history_table():
    head, history = spec_text().split("\n## 18. Review history\n", 1)
    assert re.findall(r"^## (\d+)\. ", head, flags=re.MULTILINE) == [str(number) for number in range(18)]
    assert "\n## " not in history and history.count("\n| Round |") == 1
    names = set()
    for path in (API_ROOT / "tests").glob("test_*.py"):
        names |= set(re.findall(r"^def (test_\w+)\(", path.read_text(encoding="utf-8"), flags=re.MULTILINE))
    for name in re.findall(r"`(test_[a-z0-9_]+)`", history):
        assert name in names, name
