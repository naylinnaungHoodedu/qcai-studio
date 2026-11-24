"""Phase 7 acceptance: EHMF operationalization (plan Phase 7 K AC-7-1 to AC-7-6, and the plan F, G, H, I, J, L, P rows;
Phase 7 spec 13.1). Development pipelines over the development store and fake adapters, fresh databases, temporary
package copies and the committed records; nothing is written into the checkout.
"""

from __future__ import annotations

import ast
from fractions import Fraction
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
    EHMF_SCHEMA_VERSION,
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
    NEXT_MINOR,
    NEXT_PATCH,
    REPO_ROOT,
    SHIPPED_VERSION as SHIPPED,
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
# Every test module Phase 7 added or changed (git diff --name-only 31343c8 -- apps/api/tests, plus this review's
# additions); docs/testing/test-strategy.md's Phase 7 map names each with what it proves.
PHASE7_TEST_MODULES = (
    "test_phase7_acceptance.py", "test_ehmf_units.py", "ehmf_fakes.py", "conftest.py", "v1_fakes.py", "v2_fakes.py",
    "test_phase2_acceptance.py", "test_phase3_acceptance.py", "test_phase4_acceptance.py", "test_phase5_acceptance.py",
    "test_phase6_acceptance.py", "test_config_package.py", "test_configuration_overrides.py", "test_v1_8_misconceptions.py",
    "test_v2_ledger_records.py", "test_response_ledger_migrations.py", "test_response_ledger_provenance.py",
)


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
    _a_gold_label_leaves_the_b1_record_final(result.entry)
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


def _a_gold_label_leaves_the_b1_record_final(entry) -> None:
    """(c) a V3 gold label that calls every claim SUPPORTED and the abstention a missed answer, adjudicated and applied,
    appends one gold row and changes no ledger row: the record stays abstain with its B1 findings (gold labels never
    rewrite the ledger, Phase 6 AC-6-4)."""
    from sqlalchemy import select

    from app.db_models import ResponseLedgerRecord, V3GoldLabelRecord
    from app.services.v3 import queue
    from app.services.v3.contracts import ApplyRequest
    from v3_fakes import FIXED_NOW, fresh_v3_sessions, seed_items, supported_labels

    with fresh_v3_sessions() as (factory, _engine):
        ids = seed_items(factory, [entry], package=PACKAGE, now=FIXED_NOW, double_review=False)
        with factory() as db:
            before = db.execute(select(ResponseLedgerRecord.entry, ResponseLedgerRecord.record_hash)).all()
            request = supported_labels(entry)("ac72-gold").model_copy(update={"abstention_label": "missed_answer"})
            queue.claim_item(db, ids[0], user_id="synthetic-reviewer-a", now=FIXED_NOW, package=PACKAGE)
            queue.adjudicate(db, ids[0], request, user_id="synthetic-reviewer-a", now=FIXED_NOW, package=PACKAGE)
            queue.apply_item(db, ids[0], ApplyRequest(client_key="ac72-apply"), user_id="synthetic-reviewer-b", now=FIXED_NOW)
            assert len(db.execute(select(V3GoldLabelRecord.seq)).all()) == 1
            after = db.execute(select(ResponseLedgerRecord.entry, ResponseLedgerRecord.record_hash)).all()
        assert after == before
        stored = LedgerEntryV4.model_validate_json(after[0][0]).verification
        assert stored.final == "abstain" and stored.hard_fail is True
        assert [f.type for f in stored.ehmf.response_findings if f.source == "V1.1"] and all(
            f.type == "B1" for f in stored.ehmf.response_findings if f.source == "V1.1")


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


def test_ac_7_6_a_package_edit_that_keeps_its_version_is_refused_at_write(tmp_path, capsys):
    # config_version is the package version and the rising-A/B stop sees a change only where it differs, so --write
    # refuses (exit 6) a package whose sha256 differs from the record's under the same package_version.
    golden = scripts_module("run_golden_set")
    record = tmp_path / "golden_run.json"
    record.write_text(RECORD.read_text(encoding="utf-8"), encoding="utf-8")
    edited = package_copy(tmp_path / "a", lambda raw: raw["ehmf"]["stop"].update(window_claims=201))
    # A copy of the history: a --write that got past its refusals would append to it, never to the committed one.
    history = tmp_path / "history.json"
    history.write_bytes(golden.DEFAULT_HISTORY.read_bytes())
    assert golden.main(["--write", str(record), "--package", str(edited), "--history", str(history), "--allow-dirty"]) == golden.EXIT_PIN
    assert "bump package_version" in capsys.readouterr().err
    assert record.read_text(encoding="utf-8") == RECORD.read_text(encoding="utf-8")
    assert history.read_bytes() == golden.DEFAULT_HISTORY.read_bytes()
    committed = json.loads(RECORD.read_text(encoding="utf-8"))
    assert golden.same_version_edit(committed, PACKAGE) is None
    bumped = load_config_package(package_copy(tmp_path / "b", lambda raw: (raw["ehmf"]["stop"].update(window_claims=201),
                                                                           raw.update(package_version=NEXT_PATCH))), governed=False)
    assert golden.same_version_edit(committed, bumped) is None


def test_ac_7_6_a_same_version_edit_fails_the_ci_check_whatever_record_is_checked(tmp_path, capsys):
    # The committed package version history (append-only) pins each package_version's sha256, and --check (the CI step)
    # verifies it: a record re-written for an edited package that keeps its package_version (the committed record deleted
    # first, or written to a new path and copied over) still exits 6, and --write to a fresh path is refused too.
    golden = scripts_module("run_golden_set")
    edited_path = package_copy(tmp_path / "a", lambda raw: raw["ehmf"]["stop"].update(window_claims=201))
    edited = load_config_package(edited_path, governed=False)
    assert edited.package_version == PACKAGE.package_version and edited.sha256 != PACKAGE.sha256
    fresh = json.loads(RECORD.read_text(encoding="utf-8"))
    fresh["pins"] = golden.pins(edited)
    assert golden.check_pins(fresh, edited) is None
    fresh_path = tmp_path / "fresh.json"
    fresh_path.write_text(json.dumps(fresh), encoding="utf-8")
    assert golden.main(["--check", str(fresh_path), "--package", str(edited_path)]) == golden.EXIT_PIN
    assert "recorded in the package version history" in capsys.readouterr().err
    history = tmp_path / "history.json"
    history.write_bytes(golden.DEFAULT_HISTORY.read_bytes())
    target = tmp_path / "new.json"
    assert golden.main(["--write", str(target), "--package", str(edited_path), "--history", str(history), "--allow-dirty"]) == golden.EXIT_PIN
    assert "recorded in the package version history" in capsys.readouterr().err
    assert not target.exists() and history.read_bytes() == golden.DEFAULT_HISTORY.read_bytes()
    # The CI step reads the committed history, which records the shipped package.
    assert golden.DEFAULT_HISTORY == REPO_ROOT / "docs" / "evaluation" / "phase7" / "package_versions.json"
    entries = golden.load_history(golden.DEFAULT_HISTORY)["entries"]
    # It ends with exactly one entry for the shipped package, whose sha256 is the committed package's (and its sidecar's).
    sidecar = DEFAULT_PACKAGE_PATH.with_name(DEFAULT_PACKAGE_PATH.name + ".sha256").read_text(encoding="utf-8").strip()
    assert PACKAGE.hash_verified and PACKAGE.sha256 == sidecar
    assert entries[-1] == {"version": PACKAGE.package_version, "sha256": sidecar}
    assert [entry["version"] for entry in entries].count(PACKAGE.package_version) == 1
    # A version the history lacks, a new version not newer than the newest entry, and a missing or malformed history.
    bumped = load_config_package(package_copy(tmp_path / "b", lambda raw: (raw["ehmf"]["stop"].update(window_claims=201),
                                                                           raw.update(package_version=NEXT_PATCH))), governed=False)
    recorded = golden.load_history(golden.DEFAULT_HISTORY)
    assert golden.history_problem(recorded, bumped)[0] == golden.EXIT_PIN and golden.append_problem(recorded, bumped) is None
    ahead = {**recorded, "entries": [*recorded["entries"], {"version": NEXT_MINOR, "sha256": "0" * 64}]}
    assert "not newer" in golden.append_problem(ahead, bumped)[1]
    assert golden.main(["--check", str(RECORD), "--history", str(tmp_path / "absent.json")]) == golden.EXIT_USAGE
    duplicated = {**recorded, "entries": recorded["entries"] * 2}
    history.write_text(json.dumps(duplicated), encoding="utf-8")
    assert golden.main(["--check", str(RECORD), "--history", str(history)]) == golden.EXIT_USAGE
    assert "each package_version once" in capsys.readouterr().err


def test_ac_7_6_write_appends_a_new_package_version_to_the_history(tmp_path):
    golden = scripts_module("run_golden_set")
    bumped_path = package_copy(tmp_path / "a", lambda raw: raw.update(package_version=NEXT_PATCH))
    bumped = load_config_package(bumped_path, governed=False)
    history = tmp_path / "history.json"
    history.write_bytes(golden.DEFAULT_HISTORY.read_bytes())
    target = tmp_path / "run.json"
    assert golden.main(["--write", str(target), "--package", str(bumped_path), "--history", str(history), "--allow-dirty"]) == golden.EXIT_OK
    entries = golden.load_history(history)["entries"]
    assert entries[:-1] == golden.load_history(golden.DEFAULT_HISTORY)["entries"]
    assert entries[-1] == {"version": NEXT_PATCH, "sha256": bumped.sha256}
    assert json.loads(target.read_text(encoding="utf-8"))["pins"]["config_package"] == {"version": NEXT_PATCH, "sha256": bumped.sha256}


def test_ac_7_6_no_test_runs_a_golden_set_write_against_the_committed_history():
    # Test hygiene (Phase 9 D4): a --write that gets past its refusals appends to its --history, so every test call of the
    # golden runner with --write names a temporary history (a literal "--history" or a starred list of arguments that holds
    # one); otherwise a package mid-edit makes the test append a stray entry to the committed package_versions.json.
    import ast

    offenders = []
    for path in sorted((API_ROOT / "tests").glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "main"
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == "golden" and node.args
                    and isinstance(node.args[0], ast.List)):
                continue
            items = node.args[0].elts
            constants = [item.value for item in items if isinstance(item, ast.Constant)]
            if "--write" in constants and "--history" not in constants and not any(isinstance(item, ast.Starred) for item in items):
                offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == []


def test_ac_7_6_a_same_version_edit_hidden_by_editing_the_history_fails_the_ci_check_against_the_base(tmp_path, capsys):
    # A same-version package edit whose history entry is rewritten to the edited sha256 (or removed, so --write
    # appends it again) passes without a base. With the base branch's committed history (CI: --base-ref) the history
    # must start with the base's entries unchanged, so both exit 6 at --check and are refused at --write.
    golden = scripts_module("run_golden_set")
    edited_path = package_copy(tmp_path / "a", lambda raw: raw["ehmf"]["stop"].update(window_claims=201))
    edited = load_config_package(edited_path, governed=False)
    assert edited.package_version == PACKAGE.package_version and edited.sha256 != PACKAGE.sha256
    base = tmp_path / "base.json"
    base.write_bytes(golden.DEFAULT_HISTORY.read_bytes())
    shipped = golden.load_history(base)
    history = tmp_path / "history.json"
    rewritten = [entry for entry in shipped["entries"] if entry["version"] != PACKAGE.package_version]
    history.write_text(json.dumps({**shipped, "entries": [*rewritten, {"version": PACKAGE.package_version, "sha256": edited.sha256}]}), encoding="utf-8")
    record = tmp_path / "run.json"
    common = ["--package", str(edited_path), "--history", str(history)]
    assert golden.main(["--write", str(record), *common, "--allow-dirty"]) == golden.EXIT_OK
    assert golden.main(["--check", str(record), *common]) == golden.EXIT_OK
    capsys.readouterr()
    assert golden.main(["--check", str(record), *common, "--base-history", str(base)]) == golden.EXIT_PIN
    assert f"rewrites or removes the base branch's entries ({PACKAGE.package_version})" in capsys.readouterr().err
    written = record.read_bytes()
    assert golden.main(["--write", str(record), *common, "--allow-dirty", "--base-history", str(base)]) == golden.EXIT_PIN
    assert record.read_bytes() == written
    # Removed: an emptied history, which --write alone would re-fill with the edited sha256.
    history.write_text(json.dumps({**shipped, "entries": []}), encoding="utf-8")
    fresh = tmp_path / "fresh.json"
    assert golden.main(["--write", str(fresh), *common, "--allow-dirty", "--base-history", str(base)]) == golden.EXIT_PIN
    assert not fresh.exists() and golden.load_history(history)["entries"] == []
    # Appending a newer version keeps the base as a prefix; reordering or dropping it does not.
    newer = {**shipped, "entries": [*shipped["entries"], {"version": NEXT_PATCH, "sha256": "1" * 64}]}
    assert golden.base_problem(shipped, newer) is None and golden.base_problem(None, {**shipped, "entries": []}) is None
    assert golden.base_problem(newer, shipped)[0] == golden.EXIT_PIN
    assert golden.base_problem(newer, {**newer, "entries": newer["entries"][::-1]})[0] == golden.EXIT_PIN


def test_ac_7_6_the_base_ref_reads_the_committed_history_and_ci_passes_the_base_branch(monkeypatch, capsys):
    # --base-ref reads the history committed at the ref (git show, file content, so a squash merge does not matter);
    # a ref without the file has no entries (before the first merge) and an unknown ref is a refusal, never a pass.
    golden = scripts_module("run_golden_set")
    at_head = golden.base_history_at("HEAD")
    assert at_head is not None and golden.base_problem(at_head, golden.load_history(golden.DEFAULT_HISTORY)) is None
    assert golden.main(["--check", str(RECORD), "--base-ref", "no-such-branch-x"]) == golden.EXIT_USAGE
    assert "is not a commit in this clone" in capsys.readouterr().err
    assert golden.main(["--check", str(RECORD), "--base-ref", "HEAD"]) == golden.EXIT_OK
    real = golden._git

    def without_file(*args):
        if args[0] == "cat-file":
            return subprocess.CompletedProcess(["git", *args], 128, "", "")
        return real(*args)

    monkeypatch.setattr(golden, "_git", without_file)
    assert golden.base_history_at("HEAD") is None
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "BASE_REF: ${{ github.base_ref || 'main' }}" in workflow
    assert 'git fetch --no-tags --depth=1 origin "$BASE_REF"' in workflow
    assert "python scripts/run_golden_set.py --check docs/evaluation/phase7/golden_run_v1.json --base-ref FETCH_HEAD" in workflow


def test_ac_7_6_a_package_version_that_is_not_major_minor_patch_is_a_refusal_not_a_traceback(tmp_path, capsys):
    # The loader checks only the major part of package_version, so "6.1.0-rc1" loads; the gate refuses it (exit 2) in
    # both modes instead of raising, and writes nothing.
    golden = scripts_module("run_golden_set")
    odd_path = package_copy(tmp_path / "a", lambda raw: raw.update(package_version="6.1.0-rc1"))
    assert load_config_package(odd_path, governed=False).package_version == "6.1.0-rc1"
    history = tmp_path / "history.json"
    history.write_bytes(golden.DEFAULT_HISTORY.read_bytes())
    target = tmp_path / "run.json"
    assert golden.main(["--write", str(target), "--package", str(odd_path), "--history", str(history), "--allow-dirty"]) == golden.EXIT_USAGE
    assert "is not MAJOR.MINOR.PATCH" in capsys.readouterr().err
    assert not target.exists() and history.read_bytes() == golden.DEFAULT_HISTORY.read_bytes()
    assert golden.main(["--check", str(RECORD), "--package", str(odd_path), "--history", str(history)]) == golden.EXIT_USAGE
    assert "is not MAJOR.MINOR.PATCH" in capsys.readouterr().err


def test_plan_j_fixtures_per_type_are_typed_as_the_routing_table_says():
    # Plan J "Fixtures per type (negation, invented citation, analogy, conflict, leakage)": the analogy fixture is the
    # golden set's misconception class (Type C, a V1.8 library match; spec section 1, resolution 28).
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


DETECTOR_CASES = ("V1.1", "V1.2", "V1.3", "V1.4", "V1.5", "V1.6", "V1.7", "V1.8", "V1.9", "V2", "alignment")


GUARD_CALLS = {"_guard", "guarded", "DetectorDown"}
RUNNER = "app/services/v1_checks/runner.py"


def _guarded_names() -> tuple[set[str], list[str]]:
    """The detector names the application passes to a guard (V1Track._guard, guarded, DetectorDown, and in the V1
    runner the post-render hook's local alias guard = self.track._guard) as string literals, and every call site that
    passes anything else."""
    literal, other = set(), []
    for path in sorted((API_ROOT / "app").rglob("*.py")):
        relative = path.relative_to(API_ROOT).as_posix()
        names = GUARD_CALLS | ({"guard"} if relative == RUNNER else set())
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else None
            if name not in names:
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                literal.add(first.value)
            else:
                other.append(f"{relative}:{node.lineno}:{ast.unparse(first)}")
    return literal, other


def test_plan_j_every_guarded_detector_has_a_detector_down_case():
    # The cases equal DETECTORS, every detector name a guard call site passes is in DETECTORS (and each one is
    # passed), and the guard refuses a name outside DETECTORS, so a new or renamed guard needs a case here.
    from app.services.ehmf.detectors import DETECTORS, DetectorDown, guarded

    assert DETECTOR_CASES == DETECTORS
    literal, other = _guarded_names()
    assert literal == set(DETECTORS), literal ^ set(DETECTORS)
    # The only non-literal names are the wrappers forwarding their own detector argument.
    assert sorted(site.split(":", 2)[0] + ":" + site.split(":", 2)[2] for site in other) == [
        "app/services/ehmf/detectors.py:detector", "app/services/v1_checks/runner.py:detector"], other
    with pytest.raises(ValueError, match="not a guarded EHMF detector"):
        guarded("V1.10", lambda: None)
    with pytest.raises(ValueError, match="not a guarded EHMF detector"):
        DetectorDown("V1.10")
    assert guarded("V1.1", lambda: 7) == 7 and DetectorDown("V2").detector == "V2"


@pytest.mark.parametrize("detector", DETECTOR_CASES)
def test_plan_j_detector_down_withholds_the_claim(detector, monkeypatch, caplog):
    # Every name in ehmf.detectors.DETECTORS is exercised (the test above pins DETECTOR_CASES to it).
    # V1.4's detector is the post-render subset checker (pipeline.check_subset, guarded through V1Track._subset_check);
    # V1.4, V1.6 and V1.9 run in the post-render hook, whose DetectorDown must leave the render loop (never a render fault).
    from app.services.tutor_pipeline import pipeline
    from app.services.v1_checks import runner
    from app.services.v2_panel.track import V2Track

    def boom(*args, **kwargs):
        raise RuntimeError("detector fault")

    library = None
    if detector == "V1.1":
        monkeypatch.setattr(runner, "check_v1_1", boom)
    elif detector == "V1.2":
        monkeypatch.setattr(runner, "check_v1_2", boom)
    elif detector == "V1.3":
        monkeypatch.setattr(runner, "check_v1_3", boom)   # a fault in check_v1_3 itself, outside the checker call
    elif detector == "V1.5":
        monkeypatch.setattr(runner, "check_v1_5", boom)
    elif detector == "V1.4":
        monkeypatch.setattr(pipeline, "check_subset", boom)
    elif detector == "V1.6":
        monkeypatch.setattr(runner, "check_v1_6", boom)
    elif detector == "V1.9":
        monkeypatch.setattr(runner, "check_v1_9_readability", boom)
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


def test_plan_j_a_raising_subset_checker_is_a_render_fault_only_while_ehmf_is_not_on(monkeypatch):
    # Under EHMF shadow (Phase 6 behaviour) a raising subset checker is a render fault: every attempt fails, the response
    # abstains with render_failed and no detector is recorded down; under EHMF on it is DetectorDown("V1.4") (above).
    from app.services.tutor_pipeline import pipeline

    monkeypatch.setattr(pipeline, "check_subset", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("fault")))
    record = typed_record(settings=ehmf_settings("shadow")).entry.verification
    assert record.final == "abstain" and record.final_reason == "render_failed" and record.ehmf.detector_down == ()


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
    assert config_version_of({"config_package_version": NEXT_PATCH}) == NEXT_PATCH
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
    assert versions == ["pre-phase-7", SHIPPED, SHIPPED]


def test_plan_g_v5_stays_readable_and_v6_parses_v1_to_v4_records():
    from app.services.tutor_pipeline.package_check import check_tutor_pipeline_package

    v5 = load_config_package(V5_PACKAGE_PATH, governed=True)
    assert v5.v3.trigger_registry_version == "x-triggers-v1" and v5.ehmf is None
    assert check_tutor_pipeline_package(v5, structural=True) == []
    v4 = load_config_package(V5_PACKAGE_PATH.with_name("v4.json"), governed=True)
    assert check_tutor_pipeline_package(v4, structural=True) == []
    # v6 (the first package with an ehmf block) is read explicitly since Phase 9 ships v7, which keeps every v6 rule.
    from app.core.config_package import V6_PACKAGE_PATH

    v6 = load_config_package(V6_PACKAGE_PATH, governed=True)
    assert V6_PACKAGE_PATH.name == f"v{EHMF_SCHEMA_VERSION}.json" and v6.schema_version == EHMF_SCHEMA_VERSION == vocabulary.EHMF_FIRST_MAJOR
    assert v6.v3.trigger_registry_version == "x-triggers-v2" and PACKAGE.v3.trigger_registry_version == "x-triggers-v2"
    assert check_tutor_pipeline_package(v6, structural=True) == [] and check_tutor_pipeline_package(PACKAGE, structural=True) == []


# ===================================================================================================== plan I


def test_plan_i_ready_reports_config_version_and_the_ehmf_fields_and_no_count():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        body = client.get("/ready").json()
    assert body["config_package_version"] == SHIPPED and body["config_version"] == SHIPPED
    assert {"ehmf_mode", "ehmf_setting", "phase7_exit_passed", "ehmf"} <= set(body) and body["phase7_exit_passed"] is False
    fields = body["ehmf"]
    assert fields["routing"] == "ehmf-routing-v1" and fields["weights"]["D_disclosed"] == "0" and fields["weights"]["C"] == "3/5"
    assert fields["library"]["entries"] == 0 and fields["golden_set"]["items"] == 40 and fields["max_cycles"] == 2
    assert set(fields["stop"]) == {"revert_required"}
    flat = json.dumps(fields)
    assert "count" not in flat and "rate" not in flat
    assert fields["weights_provisional"] is PACKAGE.raw["ehmf"]["weights"]["provisional"] is True
    assert fields["golden_set"]["version"] == PACKAGE.raw["ehmf"]["golden_set"]["version"] == vocabulary.GOLDEN_SET_VERSION


def test_plan_i_ready_reads_the_ehmf_values_from_the_package_in_force(monkeypatch):
    # /ready states the package's own ehmf values (weights_provisional, the golden-set version), never a literal: a
    # package whose values differ is reported as it is.
    import dataclasses
    from types import SimpleNamespace

    from app import main
    from app.services.ehmf import stop

    monkeypatch.setattr(stop, "process_stop_state", lambda *_args, **_kwargs: stop.StopState(None, "not_evaluated", None, None))
    other = dataclasses.replace(PACKAGE, ehmf=dataclasses.replace(PACKAGE.ehmf, weights_provisional=False, golden_set_version="golden-set-v9"))
    fields = main._ehmf_fields(other, SimpleNamespace(penalty_active=False))
    assert fields["weights_provisional"] is False and fields["golden_set"]["version"] == "golden-set-v9"
    assert main._ehmf_fields(PACKAGE, SimpleNamespace(penalty_active=False))["weights_provisional"] is True


def test_plan_i_per_type_rates_disclosure_share_and_correction_cycles():
    from app.services.ehmf.metrics import EVIDENCE_CLASS, slis
    from v3_fakes import append_all, fresh_v3_sessions

    entries = [typed_record(generator=UnresolvableThenCleanGenerator(always=True)).entry,
               typed_record(adapters=scripted_adapters(("CONTRADICTED", "A"))).entry]
    with fresh_v3_sessions() as (factory, _engine):
        append_all(factory, entries)
        with factory() as db:
            body = slis(db, PACKAGE)
    group = body["by_config_version"][SHIPPED]
    # per_100_* hold the rate per 100 (100*k/n as an exact fraction), with the counts k beside them.
    assert group["per_100_responses"]["B1"] == "50" and group["per_100_responses"]["responses"] == 2
    assert group["response_type_counts"]["B1"] == 1
    claims = group["per_100_claims"]["claims"]
    count = group["claim_type_counts"]["A"]
    assert claims >= 1 and count >= 1 and group["per_100_claims"]["A"] == str(Fraction(100 * count, claims))
    assert group["correction_cycles"]["exhausted"] == 1 and group["x2_emissions"] >= 1
    assert body["evidence_class"] == EVIDENCE_CLASS and body["config_version"] == SHIPPED
    assert group["type_d_disclosure_share"] == {"disclosed": 0, "conflicts": 0, "share": "0/0"}
    # The Type D disclosure share over the AC-7-3 conflict run: every detected conflict is disclosed.
    conflict = _conflict_run().entry
    detected = len(conflict.verification.ehmf.conflicts)
    assert detected >= 1 and all(item.disclosed for item in conflict.verification.ehmf.conflicts)
    with fresh_v3_sessions() as (factory, _engine):
        append_all(factory, [conflict])
        with factory() as db:
            share = slis(db, PACKAGE)["by_config_version"][SHIPPED]["type_d_disclosure_share"]
    assert share == {"disclosed": detected, "conflicts": detected, "share": f"{detected}/{detected}"}


def test_plan_i_a_dropped_proposal_is_a_typed_claim_in_the_per_type_rates_as_the_stop_counts_it():
    # AC-7-1's negated claim is dropped by V1.2 (a response finding with its claim id, Type A): the SLIs count it as a
    # typed claim carrying A, and as a response with an A finding, as stop._typed_counts does for the rising-A/B stop.
    from app.services.ehmf.metrics import slis
    from app.services.ehmf.stop import _typed_counts
    from v3_fakes import append_all, fresh_v3_sessions

    entry = typed_record(generator=negating_generator()).entry
    ehmf_record = entry.verification.ehmf
    dropped = {f.claim_id for f in ehmf_record.response_findings if f.claim_id is not None}
    assert len(dropped) == 1 and not any(f.type == "A" for claim in ehmf_record.claims for f in claim.findings)
    claims = len(ehmf_record.claims) + 1
    assert _typed_counts(entry.model_dump(mode="json")) == (claims, 1)
    with fresh_v3_sessions() as (factory, _engine):
        append_all(factory, [entry])
        with factory() as db:
            group = slis(db, PACKAGE)["by_config_version"][SHIPPED]
    assert group["per_100_claims"]["claims"] == claims and group["per_100_claims"]["A"] == str(Fraction(100, claims))
    assert group["claim_type_counts"]["A"] == 1 and group["per_100_responses"]["A"] == "100"
    assert group["per_100_claims"]["B1"] == "0" and group["response_type_counts"]["B1"] == 0


def test_plan_i_a_per_100_rate_over_a_zero_denominator_is_null_not_zero():
    # A config_version group whose typed records carry no typed claim (a response finding without a claim id only):
    # every per_100_claims rate is null (no claim to divide by), never "0", while the per-response rates are counted.
    from app.db_models import ResponseLedgerRecord
    from app.services.ehmf.metrics import slis
    from v3_fakes import fresh_v3_sessions

    entry = json.dumps({"versions": {"config_package_version": PACKAGE.package_version},
                        "verification": {"ehmf": {"claims": [], "response_findings": [{"type": "E", "claim_id": None}]}}})
    row = dict(seq=1, response_id="shadow-1", delivery="shadow", decision="abstain", entry_schema="ledger-entry-v4", entry=entry,
               entry_sha256="0" * 64, prev_hash="0" * 64, record_hash="0" * 64, created_at=datetime_now())
    with fresh_v3_sessions() as (factory, _engine):
        with factory() as db:
            db.execute(ResponseLedgerRecord.__table__.insert(), [row])
            db.commit()
        with factory() as db:
            group = slis(db, PACKAGE)["by_config_version"][SHIPPED]
    assert group["per_100_claims"]["claims"] == 0
    assert all(group["per_100_claims"][name] is None for name in vocabulary.FINDING_TYPES)
    assert group["per_100_responses"]["responses"] == 1 and group["per_100_responses"]["E"] == "100"
    assert group["per_100_responses"]["A"] == "0" and group["claim_type_counts"]["E"] == 0


def test_plan_i_an_unreadable_stop_table_leaves_the_v3_slis_and_the_status_worker_working(fresh_database_url, monkeypatch, caplog):
    # ehmf_stops absent (an image ahead of its schema): with EHMF off the V3 SLIs carry ehmf null and read nothing of
    # EHMF (Phase 6 exactly); with EHMF not off the stop reads unreadable and, on PostgreSQL, its failed read is rolled
    # back to a SAVEPOINT, so the later queries of the same session (V3 residual, gold, stop, events) still run, and
    # the EHMF status worker logs its line.
    from datetime import UTC, datetime

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.core.db import Base
    from app.services.v3.metrics import slis
    from app.workers import ehmf as worker

    connect_args = {"check_same_thread": False} if fresh_database_url.startswith("sqlite") else {}
    engine = create_engine(fresh_database_url, connect_args=connect_args)
    try:
        Base.metadata.create_all(engine, tables=[table for name, table in Base.metadata.tables.items() if name != "ehmf_stops"])
        factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        now = datetime.now(UTC)
        with factory() as db:
            assert slis(db, PACKAGE, now=now, settings=ehmf_settings("off"))["ehmf"] is None
            assert slis(db, PACKAGE, now=now)["ehmf"] is None
            body = slis(db, PACKAGE, now=now, settings=ehmf_settings("shadow"))
        assert body["ehmf"]["stop"]["reason"] == "unreadable" and body["ehmf"]["stop"]["revert_required"] is None
        assert body["gold"]["rows"] == 0 and body["x5"]["events"] == 0
        monkeypatch.setattr(worker, "get_settings", lambda: ehmf_settings("shadow"))
        monkeypatch.setattr(worker, "get_config_package", lambda _settings: PACKAGE)
        monkeypatch.setattr(worker, "SessionLocal", factory)
        with caplog.at_level(logging.INFO, logger="qcai.worker"):
            assert worker.main(["status"]) == worker.EXIT_OK
        status = [getattr(r, FIELDS) for r in caplog.records if getattr(r, FIELDS, {}).get("event") == "ehmf.status"]
        assert len(status) == 1 and status[0]["stop_state"]["reason"] == "unreadable" and status[0]["stops"] is None
    finally:
        engine.dispose()


def test_plan_i_ready_reports_the_penalty_the_shared_index_applies(monkeypatch):
    # retrieval_penalty.active is the store's (fixed when the index was built), never the mode recomputed per /ready: a
    # gateway that stops after start-up turns the mode off but leaves the index as built.
    from types import SimpleNamespace

    from app import main
    from app.services.store import get_course_store

    assert get_course_store().penalty_active is False  # development default: EHMF shadow
    monkeypatch.setattr(main, "settings", ehmf_settings("shadow"))
    assert main._ehmf_fields(PACKAGE, SimpleNamespace(penalty_active=True))["retrieval_penalty"]["active"] is True
    monkeypatch.setattr(main, "settings", ehmf_settings("on"))
    assert main._ehmf_fields(PACKAGE, SimpleNamespace(penalty_active=False))["retrieval_penalty"]["active"] is False


# ===================================================================================================== plan L


def test_plan_l_a_rising_a_b_rate_after_a_change_requires_a_revert_and_raises_the_audit_to_one_fifth(tmp_path):
    from datetime import UTC, datetime

    from app.services.ehmf.stop import _fires, detect, stop_state
    from v3_fakes import fresh_v3_sessions

    copy = package_copy(tmp_path, lambda raw: raw.update(package_version=NEXT_PATCH))
    package_next = load_config_package(copy, governed=False)
    params = PACKAGE.ehmf
    assert _fires(120, 2, 100, 10, params) and not _fires(120, 2, 100, 1, params) and not _fires(0, 0, 100, 10, params)
    assert not _fires(120, 20, 100, 10, params)
    with fresh_v3_sessions() as (factory, _engine):
        _seed_stop_simple(factory)
        with factory() as db:
            seq = detect(db, package_next, now=datetime.now(UTC))
            db.commit()
        assert seq is not None
        with factory() as db:
            state = stop_state(db, package_next)
            assert state.revert_required is True and state.reason == "rising_ab"
            assert detect(db, package_next, now=datetime.now(UTC)) is None
            from app.services.v3.scan import open_windows

            assert any(remaining > 0 for _start, remaining in open_windows(db))
            prior = stop_state(db, PACKAGE)
            assert prior.revert_required is False and prior.reason == "reverted"


def _seed_stop_simple(factory) -> None:
    """Typed rows: 60 records of 2 claims at the shipped version (one A/B record), then 50 at its next patch (five A/B records)."""
    from app.services.ledger import append_ledger_entry

    clean = typed_record(settings=ehmf_settings("shadow")).entry.model_dump(mode="json")
    bad = typed_record(adapters=scripted_adapters(("CONTRADICTED", "A"))).entry.model_dump(mode="json")
    index = 0
    for version, count, ab in ((SHIPPED, 60, 1), (NEXT_PATCH, 50, 5)):
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


def test_plan_l_reloading_the_prior_package_clears_the_revert_state(tmp_path, monkeypatch, caplog):
    # A stop follows a change between two packages with an ehmf block: /ready's cached state reads revert_required true
    # under the package the stop followed (the next patch) and false, reason reverted, once the prior package (the shipped
    # version) is in force. Reloading v5 (no ehmf
    # block) turns EHMF off: not_evaluated with no read, and the worker's status refuses but still logs the stop rows.
    from datetime import UTC, datetime

    from app.core.config_package import load_config_package as load
    from app.services.ehmf.stop import detect, process_stop_state, reset_stop_cache
    from app.workers import ehmf as worker
    from v3_fakes import fresh_v3_sessions

    package_next = load_config_package(package_copy(tmp_path, lambda raw: raw.update(package_version=NEXT_PATCH)), governed=False)
    settings = ehmf_settings("shadow")
    v5 = load(V5_PACKAGE_PATH, governed=True)
    with fresh_v3_sessions() as (factory, _engine):
        _seed_stop_simple(factory)
        with factory() as db:
            assert detect(db, package_next, now=datetime.now(UTC)) is not None
            db.commit()
        try:
            reset_stop_cache()
            state = process_stop_state(settings, package_next, session_factory=factory)
            assert (state.revert_required, state.reason) == (True, "rising_ab")
            reset_stop_cache()
            state = process_stop_state(settings, PACKAGE, session_factory=factory)
            assert (state.revert_required, state.reason, state.from_config_version) == (False, "reverted", SHIPPED)
            reset_stop_cache()
            assert process_stop_state(settings, v5, session_factory=factory).reason == "not_evaluated"
        finally:
            reset_stop_cache()
        monkeypatch.setattr(worker, "get_config_package", lambda _settings: v5)
        monkeypatch.setattr(worker, "SessionLocal", factory)
        with caplog.at_level(logging.WARNING, logger="qcai.worker"):
            assert worker.main(["status"]) == worker.EXIT_USAGE
        refused = [getattr(r, FIELDS) for r in caplog.records if getattr(r, FIELDS, {}).get("event") == "ehmf.status_refused"]
        assert len(refused) == 1 and refused[0]["reason"] == "no_ehmf_block"
        assert [(row["from_config_version"], row["to_config_version"]) for row in refused[0]["stops"]] == [(SHIPPED, NEXT_PATCH)]
    state = process_stop_state(Settings(environment="production", allowed_origins=["https://qantumlearn.academy"]), PACKAGE)
    assert state.revert_required is None and state.reason == "not_evaluated"
    reset_stop_cache()


def _insert_typed_rows(factory, rows: list[tuple[str, bool]], *, start: int = 1) -> None:
    """Bare ledger-entry-v4 rows (one typed claim each, A when the flag is set) at the given config_versions: the stop
    reads only versions and findings, so no full entry is needed. Fresh SQLite only (no chain is checked here)."""
    from app.db_models import ResponseLedgerRecord

    now = datetime_now()
    values = []
    for offset, (version, ab) in enumerate(rows):
        seq = start + offset
        entry = json.dumps({"versions": {"config_package_version": version},
                            "verification": {"ehmf": {"claims": [{"findings": [{"type": "A"}] if ab else []}], "response_findings": []}}})
        values.append(dict(seq=seq, response_id=f"shadow-{seq}", delivery="shadow", decision="answer", entry_schema="ledger-entry-v4",
                           entry=entry, entry_sha256="0" * 64, prev_hash="0" * 64, record_hash="0" * 64, created_at=now))
    with factory() as db:
        db.execute(ResponseLedgerRecord.__table__.insert(), values)
        db.commit()


def datetime_now():
    from datetime import UTC, datetime

    return datetime.now(UTC)


def test_plan_l_a_change_point_whose_before_window_the_scan_cut_never_fires_without_a_rise():
    # The shipped stop (200 typed claims per window, 100 after, 2 A/B, rise 3/2, scan 5000 records): 400 records at
    # the shipped version then records at its next minor, A/B on exactly every tenth record in both versions (no rise). As records arrive the
    # change point slides to the start of the scan; once its old-version window is cut it is skipped, never fired.
    from app.services.ehmf.stop import detect
    from v3_fakes import fresh_v3_sessions

    params = PACKAGE.ehmf
    assert (params.stop_window_claims, params.stop_min_claims, params.stop_min_ab, params.stop_scan_records) == (200, 100, 2, 5000)
    rows = [(SHIPPED, index % 10 == 0) for index in range(400)] + [(NEXT_MINOR, index % 10 == 0) for index in range(4998)]
    with fresh_v3_sessions() as (factory, _engine):
        _insert_typed_rows(factory, rows[:700])
        with factory() as db:
            assert detect(db, PACKAGE, now=datetime_now()) is None  # whole windows, no rise
        _insert_typed_rows(factory, rows[700:], start=701)
        with factory() as db:
            # the before-window is 2 records (0 A/B) when 5398 records exist: cut by the scan, so skipped
            assert detect(db, PACKAGE, now=datetime_now()) is None
            from app.db_models import EhmfStop
            from sqlalchemy import select

            assert db.execute(select(EhmfStop.seq)).first() is None
    # A real rise with whole windows still fires: 400 records at 1/10 A/B, then 200 at 1/2.
    rising = [(SHIPPED, index % 10 == 0) for index in range(400)] + [(NEXT_MINOR, index % 2 == 0) for index in range(200)]
    with fresh_v3_sessions() as (factory, _engine):
        _insert_typed_rows(factory, rising)
        with factory() as db:
            assert detect(db, PACKAGE, now=datetime_now()) is not None


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



def test_plan_l_a_package_problem_stops_a_production_start_up_only_under_the_recorded_shadow_override(monkeypatch):
    # Outside development the default (EHMF off) never stops a start-up: EHMF is reported unavailable. The recorded
    # EHMF=shadow override (config.override ehmf_shadow) asks for EHMF, so a governed start-up with a package problem stops.
    import inspect

    from app import main
    from app.services.ehmf import package_check

    monkeypatch.setattr(package_check, "check_ehmf_package", lambda package, structural=False: ["a seeded ehmf problem"])
    production = {"environment": "production", "allowed_origins": ["https://qantumlearn.academy"]}
    monkeypatch.setattr(main, "settings", Settings(**production))
    assert main.settings.enforce_corpus_governance and main.settings.ehmf == "off"
    main._check_ehmf_package(PACKAGE)
    assert ehmf.EHMF_UNAVAILABLE_REASON == "a seeded ehmf problem"
    monkeypatch.setattr(main, "settings", Settings(**production, ehmf="shadow"))
    with pytest.raises(ConfigPackageError, match="a seeded ehmf problem"):
        main._check_ehmf_package(PACKAGE)
    doc = " ".join(inspect.getdoc(main._check_ehmf_package).split())
    assert "never stops a production start-up" not in doc
    assert "the default (EHMF off) never stops a start-up" in doc and "a recorded EHMF=shadow override" in doc


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


def _norm(text: str) -> str:
    return " ".join(text.casefold().split())


def _ulqs_overlap(golden: dict, manifest: Path) -> list[str]:
    """The golden items whose query, normalised, is a ULQS question (the schema's `question` field) in `manifest`."""
    ulqs = set()
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            for key in ("question", "prompt", "text", "query"):
                if isinstance(row.get(key), str):
                    ulqs.add(_norm(row[key]))
    return [item["id"] for item in golden["items"] if _norm(item["query"]) in ulqs]


def test_golden_set_is_public_or_synthetic_and_disjoint_from_ulqs(tmp_path):
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    fixtures = json.loads((REPO_ROOT / golden["phase4_fixtures"]).read_text(encoding="utf-8"))
    ids = {case["id"] for case in fixtures["cases"]}
    # The committed ULQS manifest holds no validated item yet (validate_lqs.py --allow-draft: 0 items), so disjointness
    # is checked against it as it grows, and the check itself is proven on a seeded copy holding one golden query.
    schema = json.loads((REPO_ROOT / "lqs" / "schema.json").read_text(encoding="utf-8"))
    assert "question" in schema["required"] and "question" in schema["properties"]
    assert _ulqs_overlap(golden, REPO_ROOT / "lqs" / "manifest.jsonl") == []
    seeded = tmp_path / "manifest.jsonl"
    seeded.write_text(json.dumps({"id": "seeded", "question": "  " + golden["items"][0]["query"].upper() + " "}) + "\n", encoding="utf-8")
    same_query = [item["id"] for item in golden["items"] if _norm(item["query"]) == _norm(golden["items"][0]["query"])]
    assert _ulqs_overlap(golden, seeded) == same_query and golden["items"][0]["id"] in same_query
    for item in golden["items"]:
        assert item["source"] == "synthetic" or item["source"].split(":", 1)[1] in ids
        assert "lqs/" not in json.dumps(item)
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
    # The Phase 9 revision follows this one (the head since Phase 9).
    assert script.get_revision(script.get_heads()[0]).down_revision == "20261123_phase7_ehmf"
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


def _alembic(database_url: str, *args: str) -> subprocess.CompletedProcess:
    import os

    env = {**os.environ, "DATABASE_URL": database_url, "ENVIRONMENT": "development", "PYTHONUNBUFFERED": "1"}
    env.pop("CLOUD_SQL_CONNECTION_NAME", None)
    return subprocess.run([sys.executable, "-m", "alembic", *args], cwd=API_ROOT, env=env, capture_output=True, text=True, timeout=240)


def test_plan_e_the_phase_7_downgrade_refuses_while_ehmf_stops_holds_rows_and_the_table_refuses_truncate(fresh_database_url):
    # The runbook's rollback step, run: on the session's dialect (SQLite, or PostgreSQL with psycopg or pg8000) with the
    # start-up triggers, UPDATE, DELETE and (PostgreSQL) TRUNCATE are refused; the downgrade to the Phase 6 revision
    # refuses while a row exists and names allow_ehmf_drop; with -x allow_ehmf_drop=true it drops ehmf_stops and nothing else.
    from datetime import UTC, datetime

    from sqlalchemy import create_engine, text
    from sqlalchemy import inspect as sa_inspect

    from app.core.db import Base
    from app.core.schema_upgrades import run_schema_upgrades
    from app.services.ledger import SCHEMA_REVISION

    assert SCHEMA_REVISION == "20261123_phase9_ranking"  # the head since Phase 9, which follows the Phase 7 revision
    phase9 = {"ranking_events", "ranking_scans", "ranking_states", "ranking_incumbents"}
    connect_args = {"check_same_thread": False} if fresh_database_url.startswith("sqlite") else {}
    engine = create_engine(fresh_database_url, connect_args=connect_args)
    try:
        Base.metadata.create_all(engine)
        run_schema_upgrades(engine)
        others = set(sa_inspect(engine).get_table_names()) - {"ehmf_stops"}
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO ehmf_stops (from_config_version, to_config_version, change_seq, detected_seq, before_claims, "
                                    "before_ab, after_claims, after_ab, window_deliveries, package_sha256, created_at) VALUES "
                                    "('6.0.0', '6.0.1', 1, 2, 3, 4, 5, 6, 7, :sha, :now)"), {"sha": "0" * 64, "now": datetime.now(UTC)})
        statements = ["UPDATE ehmf_stops SET after_ab = 0", "DELETE FROM ehmf_stops"]
        if engine.dialect.name == "postgresql":
            statements.append("TRUNCATE ehmf_stops")
        for statement in statements:
            with pytest.raises(Exception, match="append-only"):
                with engine.begin() as connection:
                    connection.execute(text(statement))
        engine.dispose()
        assert _alembic(fresh_database_url, "stamp", SCHEMA_REVISION).returncode == 0
        refused = _alembic(fresh_database_url, "downgrade", "20261122_phase6_v3_audit")
        assert refused.returncode != 0 and "ehmf_stops holds 1 rows" in refused.stderr, refused.stderr[-2000:]
        assert "allow_ehmf_drop=true" in refused.stderr and "python -m app.workers.ehmf status" in refused.stderr
        assert "ehmf_stops" in sa_inspect(engine).get_table_names()
        engine.dispose()
        dropped = _alembic(fresh_database_url, "-x", "allow_ehmf_drop=true", "downgrade", "20261122_phase6_v3_audit")
        assert dropped.returncode == 0, dropped.stderr[-2000:]
        remaining = set(sa_inspect(engine).get_table_names())
        assert "ehmf_stops" not in remaining and remaining - {"alembic_version"} == others - {"alembic_version"} - phase9
    finally:
        engine.dispose()


def test_phase7_no_new_source_literal_starts_with_qcai_():
    # Spec 0.1: the privacy guard reads a qcai_-prefixed name as a cookie name, so no Phase 7 source holds such a
    # literal (an f-string's constant parts included). The prefix is built here so this test holds none either.
    prefix = "qcai" + "_"
    sources = [*(API_ROOT / "app" / "services" / "ehmf").glob("*.py"), API_ROOT / "app" / "workers" / "ehmf.py",
               REPO_ROOT / "scripts" / "run_golden_set.py", REPO_ROOT / "scripts" / "check_source_fidelity.py",
               API_ROOT / "tests" / "ehmf_fakes.py", API_ROOT / "tests" / "test_ehmf_units.py", Path(__file__)]
    offenders = []
    for path in sources:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.startswith(prefix):
                offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == []


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
    for number in range(104, 115):
        assert f"DI-{number}" in spec
    # Plan L's automatic revert is not implemented (D-05): conflict 7 and its deferred row say so, and PD-46 calls the
    # revert the operator's, never an applied value.
    section_16 = spec.split("## 16. Provisional defaults and deferred items", 1)[1].split("## 17.", 1)[0]
    di114 = next(line for line in section_16.splitlines() if line.startswith("| DI-114 |"))
    assert "reverts it and sets audit to 20%" in di114 and "D-05" in di114
    assert "DI-114" in spec.split("\n7. **Plan L", 1)[1].split("\n8. ", 1)[0]
    pd46 = next(line for line in section_16.splitlines() if line.startswith("| PD-46 |"))
    assert "the revert, which is the operator's" in pd46 and "DI-114" in pd46
    pd44 = next(line for line in section_16.splitlines() if line.startswith("| PD-44 |"))
    assert "spec conflict 3" in pd44
    # 3.7 states the golden-run record's informational keys, the --allow-dirty procedure and the runner's inputs rule.
    golden = scripts_module("run_golden_set")
    record_shape = spec.split("### 3.7", 1)[1].split("### 3.8", 1)[0]
    for phrase in ("`created_at` and `commit` are informational", "`--allow-dirty`", "`-dirty`", f"`{golden.INPUTS_RULE}`", *golden.INPUT_SCRIPTS):
        assert phrase in record_shape, phrase
    # E16: the renumbering procedure (package number and Alembic parent) is written in the change-control doc.
    control = (REPO_ROOT / "docs" / "architecture" / "ehmf-change-control.md").read_text(encoding="utf-8")
    renumbering = control.split("## Renumbering the Phase 7 package", 1)[1]
    for name in ("EHMF_SCHEMA_VERSION", "EHMF_FIRST_MAJOR", "first_package", "down_revision", "supersedes", "--rehash", "--write"):
        assert name in renumbering, name


def test_phase7_docs_name_every_modified_file_and_the_ready_stop_read():
    spec = SPEC_PATH.read_text(encoding="utf-8")
    modified = spec.split("### 7.3 MOD", 1)[1].split("### 7.4", 1)[0]
    for name in ("`api/routes/v3.py`", "`workers/v3_queue.py`", "`services/tutor_followups.py`", "`services/tutor_pipeline/__init__.py`",
                 "the Phase 3, 4, 5 and 6 specs", "`docs/architecture/v3-trigger-registry.md`"):
        assert name in modified, name
    assert "`app/workers/v3_queue.py` are unchanged" not in modified and "`app/api/routes/ledger.py` is unchanged." in modified
    texts = spec.split("### 7.4", 1)[1].split("## 8.", 1)[0]
    assert "The Phase 3 spec names" in texts and "the Phase 4 spec names" in texts and "`x-triggers-v2` (package v6)" in texts
    m17 = next(line for line in spec.splitlines() if line.startswith("- **M17. Registers.**"))
    assert "DI-104..DI-114" in m17
    detector = next(line for line in spec.splitlines() if line.startswith("- **R-c. Detector.**"))
    assert "V1.5's sufficiency check" in detector
    change = spec.split("### 4.8", 1)[1].split("### 4.9", 1)[0]
    assert "so it is written with `--allow-dirty` and its `commit` names the parent commit" not in change
    for phrase in ("package_versions.json", "`history_problem`", "Two write modes", "on a tree equal to HEAD", "prior image digest"):
        assert phrase in change, phrase
    # /ready carries the cached stop state, not only static values (ADR-010, the observability runbook).
    adr = " ".join((REPO_ROOT / "docs" / "adr" / "ADR-010-ehmf-operationalization.md").read_text(encoding="utf-8").split())
    observability = (REPO_ROOT / "infra" / "cloudrun" / "observability.md").read_text(encoding="utf-8")
    for text in (adr, observability):
        assert "static EHMF values only" not in text and "`ehmf.stop.revert_required`" in text
    # The change-control doc: the history, both write modes, the image-digest rollback, the renumbering steps that change tests.
    control = (REPO_ROOT / "docs" / "architecture" / "ehmf-change-control.md").read_text(encoding="utf-8")
    runbook = (REPO_ROOT / "infra" / "cloudrun" / "deployment.md").read_text(encoding="utf-8")
    for text in (control, runbook):
        assert "set `CONFIG_PACKAGE_PATH` to it" not in text and "deploy the prior image digest" in text and "package_versions.json" in text
    renumbering = control.split("## Renumbering the Phase 7 package", 1)[1]
    assert "so no test literal changes except the doc tests that quote file names" not in renumbering
    assert "`ledger.SCHEMA_REVISION` names this revision's own id, so it is unchanged" in renumbering
    for test in ("test_phase4_docs_the_phase3_spec_states_what_phase4_changed", "test_phase4_docs_the_code_texts_name_the_shipped_package",
                 "test_phase6_docs_the_texts_phase6_made_false_state_the_current_code"):
        assert test in renumbering, test
    assert "`--write` has two modes." in control and "with no suffix" in control
    # The runbook's rollback reaches the prior 6.x package only through the prior image digest (no package file is kept
    # to reload), and a prior Phase 7 image reads ehmf_stops; the change procedure commits the history too.
    rollback = next(line for line in runbook.splitlines() if line.startswith("**Rollback.** Set `EHMF=off`"))
    assert "reload the prior 6.x package" not in rollback and "the earlier image reads no Phase 7 table" not in rollback
    assert "deploy the prior image digest" in rollback and "A prior Phase 7 image keeps the `20261123_phase7_ehmf` schema and reads `ehmf_stops`" in rollback
    procedure = next(line for line in runbook.splitlines() if line.startswith("**Change procedure.**"))
    assert "commit the record and the package version history" in procedure
    # Append-only is enforced against the base branch, and the renumbering step is the one sanctioned hand edit.
    readme = (REPO_ROOT / "docs" / "evaluation" / "phase7" / "README.md").read_text(encoding="utf-8")
    history_row = next(line for line in readme.splitlines() if line.startswith("| `package_versions.json` |"))
    assert "except renumbering step 4" in history_row and "--base-ref" in history_row
    for text in (control, change):
        assert "--base-ref" in text
    flat_control, flat_renumbering = " ".join(control.split()), " ".join(renumbering.split())
    assert "The one sanctioned hand edit is renumbering step 4" in flat_control
    assert "this is the one sanctioned hand edit of the history" in flat_renumbering
    # 13.4 lists only mutation-checked fixes.
    mutations = spec.split("### 13.4", 1)[1].split("## 14.", 1)[0]
    assert "the shipped-schema comparison in the Phase 4 doc test;" not in mutations and "Review 4:" in mutations
    # The V3 SLI docstring describes the EHMF per-100 rates, which are not k/n.
    v3_metrics = (API_ROOT / "app" / "services" / "v3" / "metrics.py").read_text(encoding="utf-8")
    assert 'Ratios are "k/n" strings, so' not in v3_metrics and "100*k/n reduced" in v3_metrics


def test_phase7_docs_pd_47_states_the_version_bump_rule_the_history_and_the_image_digest_rollback():
    # Spec 16.1 PD-47 (which the BEP register holds verbatim, check_records.py) states the change procedure the code and
    # CI run: the same-version refusal (exit 6), the append-only history with its base-branch check, the procedure that
    # commits the record and the history, and rollback by the prior image digest; the version-bump rule and the history
    # are engineering parameters.
    spec = SPEC_PATH.read_text(encoding="utf-8")
    section = spec.split("## 16. Provisional defaults and deferred items", 1)[1].split("## 17.", 1)[0]
    pd_47 = next(line for line in section.splitlines() if line.startswith("| PD-47 |"))
    for phrase in (
        "CI also fails (exit 6) on a package edit that keeps its `package_version`",
        "`docs/evaluation/phase7/package_versions.json`, append-only",
        "`--check --base-ref FETCH_HEAD`",
        "edit, bump `package_version`, rehash, rerun, commit the record and the history in the same PR",
        "the operator deploys the prior image digest (no separate package file is kept)",
        "the exit codes, the version-bump rule, and the append-only history with its base-branch check.",
    ):
        assert phrase in pd_47, phrase
    assert "commit the record in the same PR" not in pd_47 and "rollback is reloading the prior package." not in pd_47
    # The text names what exists: the history file and CI's base-branch step.
    assert (REPO_ROOT / "docs" / "evaluation" / "phase7" / "package_versions.json").is_file()
    assert "--base-ref FETCH_HEAD" in (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


def test_phase7_docs_the_test_strategy_maps_every_test_module_the_phase_added():
    strategy = (REPO_ROOT / "docs" / "testing" / "test-strategy.md").read_text(encoding="utf-8")
    section = strategy.split("## Phase 7 acceptance map (plan Phase 7 K)", 1)[1].split("\n## ", 1)[0]
    added, changed = section.split("### Phase 7 test files", 1)[1].split("### Phase 7 changes to existing test modules", 1)
    rows = {}
    for part in (added, changed):
        for line in part.splitlines():
            if line.startswith("| `"):
                for name in re.findall(r"`([a-z0-9_]+\.py)`", line.split(" | ", 1)[0]):
                    rows[name] = line.split(" | ", 1)[1].strip(" |")
    # Every module the phase added or changed is mapped, with what it proves; each one exists.
    for name in PHASE7_TEST_MODULES:
        assert rows.get(name), name
        assert (API_ROOT / "tests" / name).is_file(), name
    assert set(rows) <= set(PHASE7_TEST_MODULES), set(rows) - set(PHASE7_TEST_MODULES)
    for name in ("test_phase7_acceptance.py", "test_ehmf_units.py", "ehmf_fakes.py"):
        assert f"| `{name}` |" in added, name
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


def test_phase7_docs_the_records_name_the_merge_and_the_cited_main_run():
    # PR #39 was squash-merged as 512b8a6 (tree identical to 4e682db); main run 45308186298 passed every job and is the
    # cited run (Phase 9 design E15). The spec's DI-104 row, its section 17 exit bullet and the test strategy's Phase 7 exit
    # paragraph name the merge, the merged tree and that run, none keeps a pre-merge phrase, and the exit stays not passed.
    spec = spec_text()
    head, history = spec.split("\n## 18. Review history\n", 1)
    exit_block = head.split("**Exit (plan P).**", 1)[1]
    strategy = (REPO_ROOT / "docs" / "testing" / "test-strategy.md").read_text(encoding="utf-8")
    texts = {
        "DI-104": next(line for line in head.splitlines() if line.startswith("| DI-104 |")),
        "spec 17": next(line for line in exit_block.splitlines() if line.startswith("- The AC tests are done in code.")),
        "test strategy": next(line for line in strategy.split("## Phase 7 acceptance map", 1)[1].splitlines() if line.startswith("**Exit gate.**")),
    }
    for name, text in texts.items():
        for fact in ("`512b8a6`", "`4e682db`", "45308186298"):
            assert fact in text, (name, fact)
        for stale in ("each later commit needs its own run", "the cited run must be on `main`", "the cited CI run must be on `main`",
                      "45234227899"):
            assert stale.lower() not in text.lower(), (name, stale)
    assert "The exit is not passed." in texts["DI-104"] and texts["DI-104"].endswith("| Eng / PI / CO | Open |")
    for blocker in ("DI-105", "DI-108", "DI-109", "DI-89"):
        assert blocker in texts["DI-104"], blocker
    assert "The exit is not passed." in texts["test strategy"]
    assert "- `phase7_exit_passed` stays `false`. The exit is not passed." in exit_block
    assert "| Merge | `512b8a6` |" in history
