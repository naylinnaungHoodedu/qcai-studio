"""Phase 10: IRB, OSF and freeze records and the confirmatory refusal order (spec 3.13, 4.10; PD-69)."""

from __future__ import annotations

from pathlib import Path

import pytest

from evaluation.qcai_eval import governance, synthetic

REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN_SHA = "c" * 64


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
    return governance.confirmatory_refusals(base, analysis_plan_sha256=PLAN_SHA, dataset_sha256="d" * 64, items_states={"frozen": 3},
                                            package_raw={"owner_decisions": {"D-14": {"state": "decided"}}}, repo_root=REPO_ROOT)


def test_dates_and_hashes_are_checked_against_the_run(tmp_path):
    irb = synthetic.irb_record(tmp_path / "irb.private.json")
    osf = synthetic.osf_record(tmp_path / "osf.private.json", analysis_plan_sha256=PLAN_SHA)
    scan = synthetic.pass_scan(tmp_path / "scan.json")
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
        items_states={"candidate": 2}, package_raw={"owner_decisions": {"D-14": {"state": "open"}}}, repo_root=REPO_ROOT)
    assert reasons == ["irb_missing", "osf_missing", "D-14 open", "items_not_frozen", "freeze_record_missing", "pre_run_scan_missing",
                       "stub_not_confirmatory"]


def test_a_governance_record_on_a_public_repository_path_is_refused(tmp_path):
    public = REPO_ROOT / "lqs" / "README.md"
    reference = {"path": "lqs/README.md", "sha256": governance.lf_sha256(public)}
    reasons = refusals(tmp_path, governance={"irb_record": reference, "osf_record": None})
    assert "governance_record_public" in reasons and "irb_invalid:file" in reasons
