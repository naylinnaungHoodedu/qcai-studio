"""Phase 10: IRB, OSF, freeze, plan H and pre-run scan records and the confirmatory refusal order (spec 3.13, 4.10; PD-69)."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

from evaluation.qcai_eval import contamination, governance, synthetic

REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN_SHA = "c" * 64
CONTENT_SHA = "e" * 64


@pytest.mark.parametrize(("overrides", "field"), [
    ({"protocol_number": "x"}, "protocol_number"), ({"determination": "pending"}, "determination"),
    ({"approval_date": "2026-13-01"}, "approval_date"), ({"approval_date": "24 Nov 2026"}, "approval_date"),
    ({"expiry_date": "2026-01-01"}, "expiry_date"), ({"letter_sha256": "abc"}, "letter_sha256"), ({"reviewer": "R1"}, "reviewer"),
])
def test_irb_record_validation_names_the_field(tmp_path, overrides, field):
    reference = synthetic.irb_record(tmp_path / "irb.private.json", **overrides)
    with pytest.raises(governance.GovernanceError) as raised:
        governance.load_irb(Path(reference["path"]))
    assert raised.value.field == field


@pytest.mark.parametrize(("doi", "ok"), [("10.17605/OSF.IO/SYN0001", True), ("10.17605/OSF.IO/ABCDE", True), ("10.17605/osf.io/abcde", False),
                                         ("10.1234/OSF.IO/ABCDE", False), ("10.17605/OSF.IO/ABC", False), ("https://osf.io/abcde", False)])
def test_osf_doi_pattern(tmp_path, doi, ok):
    reference = synthetic.osf_record(tmp_path / "osf.private.json", analysis_plan_sha256=PLAN_SHA, doi=doi)
    if ok:
        assert governance.load_osf(Path(reference["path"]))["doi"] == doi
    else:
        with pytest.raises(governance.GovernanceError, match="doi"):
            governance.load_osf(Path(reference["path"]))


def refusals(tmp_path, **spec):
    base = {"created_at": "2026-11-24T00:00:00Z", "mode": "live", "governance": {"irb_record": None, "osf_record": None}}
    base.update(spec)
    return governance.confirmatory_refusals(base, analysis_plan_sha256=PLAN_SHA, dataset_sha256="d" * 64, dataset_content_sha256=CONTENT_SHA,
                                            items_states={"frozen": 3}, package_raw={"owner_decisions": {"D-14": {"state": "decided"}}},
                                            repo_root=REPO_ROOT)


def test_dates_and_hashes_are_checked_against_the_run(tmp_path):
    irb = synthetic.irb_record(tmp_path / "irb.private.json")
    osf = synthetic.osf_record(tmp_path / "osf.private.json", analysis_plan_sha256=PLAN_SHA)
    scan = synthetic.pass_scan(tmp_path / "scan.json", dataset_content_sha256=CONTENT_SHA)
    freeze = synthetic.freeze_record(tmp_path / "freeze.private.json", dataset_sha256="d" * 64)
    ok = {"governance": {"irb_record": irb, "osf_record": osf}, "freeze_record": freeze, "pre_run_scan": scan}
    assert refusals(tmp_path, **ok) == []
    late = synthetic.irb_record(tmp_path / "late.private.json", approval_date="2026-11-25", expiry_date=None)
    assert refusals(tmp_path, **{**ok, "governance": {"irb_record": late, "osf_record": osf}}) == ["irb_not_yet_approved"]
    expired = synthetic.irb_record(tmp_path / "old.private.json", approval_date="2025-01-01", expiry_date="2026-01-01")
    assert refusals(tmp_path, **{**ok, "governance": {"irb_record": expired, "osf_record": osf}}) == ["irb_expired"]
    after = synthetic.osf_record(tmp_path / "after.private.json", analysis_plan_sha256=PLAN_SHA, registered_date="2026-12-01")
    assert refusals(tmp_path, **{**ok, "governance": {"irb_record": irb, "osf_record": after}}) == ["osf_registered_after_run"]
    other = synthetic.osf_record(tmp_path / "other.private.json", analysis_plan_sha256="e" * 64)
    assert refusals(tmp_path, **{**ok, "governance": {"irb_record": irb, "osf_record": other}}) == ["osf_plan_mismatch"]
    tampered = dict(irb, sha256="0" * 64)
    assert refusals(tmp_path, **{**ok, "governance": {"irb_record": tampered, "osf_record": osf}}) == ["irb_invalid:sha256"]
    failed = synthetic.freeze_record(tmp_path / "failed.private.json", dataset_sha256="d" * 64, passed=False)
    assert refusals(tmp_path, **{**ok, "freeze_record": failed}) == ["freeze_record_failed"]
    other_set = synthetic.freeze_record(tmp_path / "otherset.private.json", dataset_sha256="f" * 64)
    assert refusals(tmp_path, **{**ok, "freeze_record": other_set}) == ["freeze_record_failed"]
    assert refusals(tmp_path, **{**ok, "pre_run_scan": None}) == ["pre_run_scan_missing"]
    assert refusals(tmp_path, **{**ok, "mode": "stub"}) == ["stub_not_confirmatory"]
    assert refusals(tmp_path, **{**ok, "mode": "recorded"}) == ["recording_not_live"]


def test_the_refusal_order_with_nothing_supplied(tmp_path):
    reasons = governance.confirmatory_refusals(
        {"created_at": "2026-11-24T00:00:00Z", "mode": "stub", "governance": {}}, analysis_plan_sha256=PLAN_SHA, dataset_sha256="d" * 64,
        dataset_content_sha256=CONTENT_SHA, items_states={"candidate": 2}, package_raw={"owner_decisions": {"D-14": {"state": "open"}}}, repo_root=REPO_ROOT)
    assert reasons == ["irb_missing", "osf_missing", "D-14 open", "items_not_frozen", "freeze_record_missing", "pre_run_scan_missing",
                       "stub_not_confirmatory"]


def test_a_governance_record_on_a_public_repository_path_is_refused(tmp_path):
    public = REPO_ROOT / "lqs" / "README.md"
    reference = {"path": "lqs/README.md", "sha256": governance.lf_sha256(public)}
    reasons = refusals(tmp_path, governance={"irb_record": reference, "osf_record": None})
    assert "governance_record_public" in reasons and "irb_invalid:file" in reasons


def _ci_scan_report(tmp_path):
    """The report CI's own --repo step writes: synthetic fingerprint sets over the tracked tree."""
    if str(REPO_ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import scan_research_logs

    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "payload_log.jsonl").write_text("{}\n", encoding="utf-8")
    path = tmp_path / "ci-scan.json"
    assert scan_research_logs.main(["--synthetic-fixture", str(synthetic.CONTAMINATION_FIXTURE), "--path", str(tmp_path / "logs"),
                                    "--report", str(path)]) == 0
    return synthetic.record_ref(path)


_TARGET_REPO = {"target": "repository", "root": ".", "files": 3, "scanned": 2, "excluded": [], "files_with_hits": []}
_TARGET_LOGS = {"target": "research-logs", "root": "prior-run", "files": 4, "scanned": 3,
                "excluded": [{"path": "responses.jsonl", "reason": "research data (model outputs)"}], "files_with_hits": []}


@pytest.mark.parametrize(("overrides", "reason"), [
    ({"result": "fail", "matches_total": 2}, "pre_run_scan_invalid:result"),
    ({"result": "incomplete"}, "pre_run_scan_invalid:result"),
    ({"matches_total": 1}, "pre_run_scan_invalid:result"),
    ({"fingerprint_sets": []}, "pre_run_scan_invalid:fingerprint_sets"),
    ({"fingerprint_sets": [{"id": "synthetic-licensed-v1", "kind": "licensed", "dataset_content_sha256": None},
                           {"id": "synthetic-ulqs-v1", "kind": "ulqs", "dataset_content_sha256": CONTENT_SHA}]},
     "pre_run_scan_invalid:fingerprint_sets"),
    ({"fingerprint_sets": [{"id": "research-ulqs-t1", "kind": "ulqs", "dataset_content_sha256": CONTENT_SHA}]},
     "pre_run_scan_invalid:fingerprint_sets"),
    ({"fingerprint_sets": [{"id": "research-licensed-t1", "kind": "licensed", "dataset_content_sha256": None},
                           {"id": "research-ulqs-t1", "kind": "ulqs", "dataset_content_sha256": "f" * 64}]}, "pre_run_scan_invalid:dataset"),
    ({"targets": []}, "pre_run_scan_invalid:targets"),
    ({"targets": [{"target": "repository", "root": ".", "files": 3, "scanned": 2, "excluded": [], "files_with_hits": []}]},
     "pre_run_scan_invalid:targets"),
    ({"targets": [{"target": "research-logs", "root": "r", "files": 3, "scanned": 2, "excluded": [], "files_with_hits": []}]},
     "pre_run_scan_invalid:targets"),
    ({"targets": [{"target": "repository", "root": ".", "files": 3, "scanned": 0, "excluded": [], "files_with_hits": []},
                  {"target": "path", "root": "p", "files": 1, "scanned": 1, "excluded": [], "files_with_hits": []}]},
     "pre_run_scan_invalid:targets"),
    ({"report": "something-else"}, "pre_run_scan_invalid:report"),
    # Coverage: a target that scanned no file (a mistyped prompts directory), or a file excluded as too large or
    # unreadable, leaves the scan unable to prove zero, whatever the report's result says.
    ({"targets": [_TARGET_REPO, _TARGET_LOGS, {"target": "path", "root": "prompts", "files": 0, "scanned": 0, "excluded": [],
                                               "files_with_hits": []}]}, "pre_run_scan_invalid:coverage"),
    ({"targets": [_TARGET_REPO, {**_TARGET_LOGS, "excluded": [{"path": "big.jsonl", "reason": "too_large"}]}]},
     "pre_run_scan_invalid:coverage"),
    ({"targets": [_TARGET_REPO, {**_TARGET_LOGS, "excluded": [{"path": "locked.jsonl", "reason": "unreadable"}]}]},
     "pre_run_scan_invalid:coverage"),
    ({"targets": [_TARGET_REPO, {**_TARGET_LOGS, "excluded": "none"}]}, "pre_run_scan_invalid:coverage"),
    ({"targets": [_TARGET_REPO, _TARGET_LOGS, "not a target"]}, "pre_run_scan_invalid:coverage"),
    ({"incomplete_targets": ["prior-run"]}, "pre_run_scan_invalid:coverage"),
])
def test_a_pre_run_scan_must_be_a_passing_research_scan_bound_to_the_items(tmp_path, overrides, reason):
    ok = synthetic.pass_scan(tmp_path / "ok.json", dataset_content_sha256=CONTENT_SHA)
    assert governance.scan_refusals(ok, REPO_ROOT, dataset_content_sha256=CONTENT_SHA, missing="m") == []
    broken = synthetic.pass_scan(tmp_path / "broken.json", dataset_content_sha256=CONTENT_SHA, **overrides)
    assert reason in governance.scan_refusals(broken, REPO_ROOT, dataset_content_sha256=CONTENT_SHA, missing="m")


def test_a_scan_the_scanner_wrote_with_incomplete_coverage_says_incomplete_and_is_refused(tmp_path):
    # The scanner writes its report before its --require-zero exit: a scan with zero matches over a target that scanned
    # nothing says `incomplete` (never `pass`), names the target, and the gate refuses it for coverage.
    if str(REPO_ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import scan_research_logs

    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "payload_log.jsonl").write_text("{}\n", encoding="utf-8")
    (tmp_path / "prompts").mkdir()
    path = tmp_path / "scan.json"
    assert scan_research_logs.main(["--synthetic-fixture", str(synthetic.CONTAMINATION_FIXTURE), "--path", str(tmp_path / "logs"),
                                    "--path", str(tmp_path / "prompts"), "--require-zero", "--report", str(path)]) == 1
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["matches_total"] == 0 and report["result"] == "incomplete" and report["incomplete_targets"] == ["prompts"]
    reasons = governance.scan_refusals(synthetic.record_ref(path), REPO_ROOT, dataset_content_sha256=CONTENT_SHA, missing="m")
    assert "pre_run_scan_invalid:result" in reasons and "pre_run_scan_invalid:coverage" in reasons
    assert governance.INCOMPLETE_REASONS == contamination.INCOMPLETE_REASONS


def test_a_record_path_open_refuses_is_an_invalid_file_never_a_traceback(tmp_path):
    # An embedded NUL makes open() raise ValueError: a governance record, a pre-run scan and the public-path check refuse it
    # as `file` (or not public) instead of raising.
    nul = {"path": "a\x00b.json", "sha256": "0" * 64}
    with pytest.raises(governance.GovernanceError) as error:
        governance.resolve_record(nul, REPO_ROOT)
    assert error.value.field == "file"
    assert governance.scan_refusals(nul, REPO_ROOT, dataset_content_sha256=CONTENT_SHA, missing="m") == ["pre_run_scan_invalid:file"]
    assert governance.irb_refusals(nul, governance.run_date({"created_at": synthetic.CREATED}), REPO_ROOT, missing="m") == ["irb_invalid:file"]
    assert governance.is_public(nul, REPO_ROOT) in (True, False)
    assert governance.is_public({"path": "lqs/private/a\x00b.json", "sha256": "0" * 64}, REPO_ROOT) in (True, False)


def test_ci_s_synthetic_scan_report_and_dangling_references_do_not_pass_the_pre_run_scan(tmp_path):
    ci = _ci_scan_report(tmp_path)
    reasons = governance.scan_refusals(ci, REPO_ROOT, dataset_content_sha256=CONTENT_SHA, missing="m")
    assert "pre_run_scan_invalid:fingerprint_sets" in reasons and "pre_run_scan_invalid:dataset" in reasons
    assert governance.scan_refusals(None, REPO_ROOT, dataset_content_sha256=CONTENT_SHA, missing="m") == ["m"]
    assert governance.scan_refusals({"path": str(tmp_path / "absent.json"), "sha256": "0" * 64}, REPO_ROOT,
                                    dataset_content_sha256=CONTENT_SHA, missing="m") == ["pre_run_scan_invalid:file"]
    tampered = dict(ci, sha256="0" * 64)
    assert governance.scan_refusals(tampered, REPO_ROOT, dataset_content_sha256=CONTENT_SHA, missing="m") == ["pre_run_scan_invalid:sha256"]


@pytest.mark.parametrize(("builder", "loader", "overrides", "field"), [
    ("provider_terms_record", "load_provider_terms", {"provider_id": "x"}, "provider_id"),
    ("provider_terms_record", "load_provider_terms", {"training_recorded": False}, "training_recorded"),
    ("provider_terms_record", "load_provider_terms", {"retention_recorded": "yes"}, "retention_recorded"),
    ("provider_terms_record", "load_provider_terms", {"terms_sha256": "abc"}, "terms_sha256"),
    ("licence_ruling_record", "load_licence_ruling", {"determination": "pending"}, "determination"),
    ("licence_ruling_record", "load_licence_ruling", {"ruling_date": "soon"}, "ruling_date"),
    ("research_use_record", "load_research_use", {"confirmation": "pending"}, "confirmation"),
    ("research_use_record", "load_research_use", {"note": "x"}, "note"),
])
def test_plan_h_records_are_validated_by_field(tmp_path, builder, loader, overrides, field):
    good = getattr(synthetic, builder)(tmp_path / "good.json")
    getattr(governance, loader)(Path(good["path"]))
    reference = getattr(synthetic, builder)(tmp_path / "bad.json", **overrides)
    with pytest.raises(governance.GovernanceError) as raised:
        getattr(governance, loader)(Path(reference["path"]))
    assert raised.value.field == field


def test_the_irb_condition_checks_the_dates_for_every_caller(tmp_path):
    from datetime import date

    on = date(2026, 11, 24)
    assert governance.irb_refusals(None, on, REPO_ROOT, missing="irb_not_filed") == ["irb_not_filed"]
    assert governance.irb_refusals(synthetic.irb_record(tmp_path / "ok.json"), on, REPO_ROOT, missing="x") == []
    late = synthetic.irb_record(tmp_path / "late.json", approval_date="2026-12-01", expiry_date=None)
    assert governance.irb_refusals(late, on, REPO_ROOT, missing="x") == ["irb_not_yet_approved"]
    old = synthetic.irb_record(tmp_path / "old.json", approval_date="2025-01-01", expiry_date="2026-01-01")
    assert governance.irb_refusals(old, on, REPO_ROOT, missing="x") == ["irb_expired"]
    assert governance.irb_refusals({"path": str(tmp_path / "none.json"), "sha256": "0" * 64}, on, REPO_ROOT, missing="x") == ["irb_invalid:file"]
