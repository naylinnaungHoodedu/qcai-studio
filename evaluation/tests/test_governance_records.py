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
                                            corpus_version=synthetic.CORPUS_VERSION, items_states={"frozen": 3}, package_raw={"owner_decisions": {"D-14": {"state": "decided"}}},
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
        dataset_content_sha256=CONTENT_SHA, corpus_version=synthetic.CORPUS_VERSION, items_states={"candidate": 2}, package_raw={"owner_decisions": {"D-14": {"state": "open"}}}, repo_root=REPO_ROOT)
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


def _licensed_entry(**changes):
    entry = {"id": "research-licensed-t1", "kind": "licensed", "dataset_content_sha256": CONTENT_SHA,
             "corpus_version": synthetic.CORPUS_VERSION, "shingle_words": 12, "fingerprints": 40, "exact": 0}
    return {**entry, **changes}


_ULQS_ENTRY = {"id": "research-ulqs-t1", "kind": "ulqs", "dataset_content_sha256": CONTENT_SHA, "corpus_version": None,
               "shingle_words": 6, "fingerprints": 30, "exact": 5}


@pytest.mark.parametrize(("overrides", "reason"), [
    ({"result": "fail", "matches_total": 2}, "pre_run_scan_invalid:result"),
    # Review 22: a licensed set counts only when it was built for this run: alongside its items (the same content sha256)
    # and for the corpus version they name. A set of any 12-word text, with no binding, never satisfies the gate.
    ({"fingerprint_sets": [_licensed_entry(dataset_content_sha256=None, corpus_version=None), _ULQS_ENTRY]},
     "pre_run_scan_invalid:licensed_corpus"),
    ({"fingerprint_sets": [_licensed_entry(dataset_content_sha256="f" * 64), _ULQS_ENTRY]}, "pre_run_scan_invalid:licensed_corpus"),
    ({"fingerprint_sets": [_licensed_entry(corpus_version="ANOTHER-CORPUS"), _ULQS_ENTRY]}, "pre_run_scan_invalid:licensed_corpus"),
    ({"fingerprint_sets": [_licensed_entry(corpus_version=None), _ULQS_ENTRY]}, "pre_run_scan_invalid:licensed_corpus"),
    ({"fingerprint_sets": [_licensed_entry(corpus_version=["x"]), _ULQS_ENTRY]}, "pre_run_scan_invalid:licensed_corpus"),
    ({"fingerprint_sets": [_licensed_entry(id="synthetic-licensed-v1"), _ULQS_ENTRY]}, "pre_run_scan_invalid:licensed_corpus"),
    ({"fingerprint_sets": [_licensed_entry(fingerprints=0), _ULQS_ENTRY]}, "pre_run_scan_invalid:licensed_corpus"),
    ({"result": "incomplete"}, "pre_run_scan_invalid:result"),
    ({"matches_total": 1}, "pre_run_scan_invalid:result"),
    ({"fingerprint_sets": []}, "pre_run_scan_invalid:fingerprint_sets"),
    ({"fingerprint_sets": [{"id": "synthetic-licensed-v1", "kind": "licensed", "dataset_content_sha256": None},
                           {"id": "synthetic-ulqs-v1", "kind": "ulqs", "dataset_content_sha256": CONTENT_SHA}]},
     "pre_run_scan_invalid:fingerprint_sets"),
    ({"fingerprint_sets": [{"id": "research-ulqs-t1", "kind": "ulqs", "dataset_content_sha256": CONTENT_SHA}]},
     "pre_run_scan_invalid:fingerprint_sets"),
    # An empty or unsized set never satisfies the gate (plan "Stop: contamination"): a licensed set of 0 shingles, one
    # with no size, one whose size is not a count, and a ULQS set with no fingerprint of either family.
    ({"fingerprint_sets": [{"id": "research-licensed-t1", "kind": "licensed", "dataset_content_sha256": None, "shingle_words": 12,
                            "fingerprints": 0, "exact": 0},
                           {"id": "research-ulqs-t1", "kind": "ulqs", "dataset_content_sha256": CONTENT_SHA, "fingerprints": 3, "exact": 1}]},
     "pre_run_scan_invalid:fingerprint_sets"),
    ({"fingerprint_sets": [{"id": "research-licensed-t1", "kind": "licensed", "dataset_content_sha256": None},
                           {"id": "research-ulqs-t1", "kind": "ulqs", "dataset_content_sha256": CONTENT_SHA, "fingerprints": 3, "exact": 1}]},
     "pre_run_scan_invalid:fingerprint_sets"),
    ({"fingerprint_sets": [{"id": "research-licensed-t1", "kind": "licensed", "dataset_content_sha256": None, "fingerprints": True,
                            "exact": 4},
                           {"id": "research-ulqs-t1", "kind": "ulqs", "dataset_content_sha256": CONTENT_SHA, "fingerprints": 3, "exact": 1}]},
     "pre_run_scan_invalid:fingerprint_sets"),
    ({"fingerprint_sets": [{"id": "research-licensed-t1", "kind": "licensed", "dataset_content_sha256": None, "fingerprints": 9},
                           {"id": "research-ulqs-t1", "kind": "ulqs", "dataset_content_sha256": CONTENT_SHA, "fingerprints": 0, "exact": 0}]},
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
    # A log or path target that excluded a file as binary or not text (a UTF-16 console log without a mark, a PDF)
    # cannot prove zero either.
    ({"targets": [_TARGET_REPO, {**_TARGET_LOGS, "excluded": [{"path": "console.log", "reason": "not_text"}]}]},
     "pre_run_scan_invalid:coverage"),
    ({"targets": [_TARGET_REPO, {**_TARGET_LOGS, "excluded": [{"path": "notes.pdf", "reason": "binary"}]}]},
     "pre_run_scan_invalid:coverage"),
    ({"targets": [_TARGET_REPO, {"target": "path", "root": "p", "files": 2, "scanned": 1, "excluded": [{"path": "x", "reason": "not_text"}],
                                 "files_with_hits": []}]}, "pre_run_scan_invalid:coverage"),
    # A report whose lists are not lists is invalid, never a traceback.
    ({"targets": 5}, "pre_run_scan_invalid:report"),
    ({"targets": "repository"}, "pre_run_scan_invalid:report"),
    ({"targets": None}, "pre_run_scan_invalid:report"),
    ({"fingerprint_sets": 7}, "pre_run_scan_invalid:report"),
    ({"fingerprint_sets": {"id": "research-ulqs-t1"}}, "pre_run_scan_invalid:report"),
])
def test_a_pre_run_scan_must_be_a_passing_research_scan_bound_to_the_items(tmp_path, overrides, reason):
    ok = synthetic.pass_scan(tmp_path / "ok.json", dataset_content_sha256=CONTENT_SHA)
    assert governance.scan_refusals(ok, REPO_ROOT, dataset_content_sha256=CONTENT_SHA, corpus_version=synthetic.CORPUS_VERSION, missing="m") == []
    broken = synthetic.pass_scan(tmp_path / "broken.json", dataset_content_sha256=CONTENT_SHA, **overrides)
    assert reason in governance.scan_refusals(broken, REPO_ROOT, dataset_content_sha256=CONTENT_SHA, corpus_version=synthetic.CORPUS_VERSION, missing="m")


def test_a_pre_run_scan_is_refused_for_a_run_whose_items_name_no_single_corpus_version(tmp_path):
    # The run passes the one corpus version its items name, or None when they name more than one: no licensed set
    # matches None, so the gate refuses the scan.
    ok = synthetic.pass_scan(tmp_path / "ok.json", dataset_content_sha256=CONTENT_SHA)
    assert governance.scan_refusals(ok, REPO_ROOT, dataset_content_sha256=CONTENT_SHA, corpus_version=None, missing="m") == [
        "pre_run_scan_invalid:licensed_corpus"]
    assert governance.scan_refusals(ok, REPO_ROOT, dataset_content_sha256=CONTENT_SHA, corpus_version="ANOTHER-CORPUS", missing="m") == [
        "pre_run_scan_invalid:licensed_corpus"]


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
    reasons = governance.scan_refusals(synthetic.record_ref(path), REPO_ROOT, dataset_content_sha256=CONTENT_SHA, corpus_version=synthetic.CORPUS_VERSION, missing="m")
    assert "pre_run_scan_invalid:result" in reasons and "pre_run_scan_invalid:coverage" in reasons
    assert governance.INCOMPLETE_REASONS == contamination.INCOMPLETE_REASONS


def test_a_repository_target_s_binary_assets_leave_the_pre_run_scan_complete(tmp_path):
    # The tracked tree holds images and fonts: listed as excluded (`binary`), they do not make the scan incomplete; the
    # gate's reasons equal the scanner's, for each target kind.
    repo = {**_TARGET_REPO, "excluded": [{"path": "logo.png", "reason": "binary"}, {"path": "font.woff2", "reason": "binary"}]}
    ok = synthetic.pass_scan(tmp_path / "ok.json", dataset_content_sha256=CONTENT_SHA, targets=[repo, _TARGET_LOGS])
    assert governance.scan_refusals(ok, REPO_ROOT, dataset_content_sha256=CONTENT_SHA, corpus_version=synthetic.CORPUS_VERSION, missing="m") == []
    assert governance.INCOMPLETE_REASONS == contamination.INCOMPLETE_REASONS
    assert governance.STRICT_TARGETS == contamination.STRICT_TARGETS
    assert governance.STRICT_INCOMPLETE_REASONS == contamination.STRICT_INCOMPLETE_REASONS
    for kind in ("repository", "research-logs", "path"):
        assert governance._incomplete_reasons(kind) == contamination.incomplete_reasons(kind)


def test_the_confirmatory_gate_judges_every_record_in_the_run_window(tmp_path, monkeypatch):
    # The run window (spec 3.13): the IRB approved by `start` and unexpired on `today`, the OSF record registered by
    # `start`; the spec's created_at only may not be in the future. A spec dated 2026-11-24 run in 2028 is judged on the
    # 2028 day, so the IRB that expired in 2027 refuses it however the spec is dated.
    from datetime import date

    irb = synthetic.irb_record(tmp_path / "irb.private.json", approval_date="2026-11-01", expiry_date="2027-06-30")
    osf = synthetic.osf_record(tmp_path / "osf.private.json", analysis_plan_sha256=PLAN_SHA, registered_date="2026-11-20")
    scan = synthetic.pass_scan(tmp_path / "scan.json", dataset_content_sha256=CONTENT_SHA)
    freeze = synthetic.freeze_record(tmp_path / "freeze.private.json", dataset_sha256="d" * 64)
    ok = {"governance": {"irb_record": irb, "osf_record": osf}, "freeze_record": freeze, "pre_run_scan": scan}

    def gate(start=None, today=None, **spec):
        return governance.confirmatory_refusals(
            {"created_at": "2026-11-24T00:00:00Z", "mode": "live", **ok, **spec}, analysis_plan_sha256=PLAN_SHA,
            dataset_sha256="d" * 64, dataset_content_sha256=CONTENT_SHA, corpus_version=synthetic.CORPUS_VERSION, items_states={"frozen": 3},
            package_raw={"owner_decisions": {"D-14": {"state": "decided"}}}, repo_root=REPO_ROOT, start=start, today=today)

    assert gate() == [] and refusals(tmp_path, **ok) == []
    # today: utc_today() by default, or the runner's day; the IRB must be unexpired on it, whatever created_at says.
    monkeypatch.setattr(governance, "utc_today", lambda: date(2028, 1, 10))
    assert gate() == ["irb_expired"] and refusals(tmp_path, **ok) == ["irb_expired"]
    assert gate(created_at="2028-01-10T08:00:00Z") == ["irb_expired"]
    assert gate(today=date(2027, 6, 30)) == []
    # created_at may not be after today; it is never a record's run date.
    assert gate(today=date(2026, 11, 23)) == ["created_at_in_future"]
    assert governance.created_at_refusals({"created_at": "garbage"}, date(2026, 11, 24)) == ["created_at"]
    # start: approval and registration must precede the day the run's data began to flow; an earlier start only tightens.
    assert gate(start=date(2026, 11, 22), today=date(2026, 12, 1)) == []
    assert gate(start=date(2026, 10, 31), today=date(2026, 12, 1)) == ["irb_not_yet_approved", "osf_registered_after_run"]
    assert gate(start=date(2026, 11, 19), today=date(2026, 12, 1)) == ["osf_registered_after_run"]
    # A start after today is clamped to today (it can never loosen the check).
    assert gate(start=date(2027, 9, 1), today=date(2026, 11, 24)) == gate(today=date(2026, 11, 24)) == []
    for start in (date(2026, 11, 21), date(2026, 11, 25), date(2027, 6, 30)):  # monotone: never fewer reasons than later
        assert set(gate(start=start, today=date(2027, 6, 30))) >= set(gate(start=date(2027, 6, 30), today=date(2027, 6, 30)))


def test_the_confirmatory_exit_code_is_one_rule_over_the_reason_classes():
    # Spec 5: 8 with any IRB or OSF reason, else 3 with any items or freeze-record reason, else 2.
    table = {("irb_missing",): 8, ("osf_plan_mismatch", "items_not_frozen"): 8, ("pre_run_scan_missing", "irb_expired"): 8,
             ("items_not_frozen",): 3, ("items_split_missing", "D-14 open"): 3, ("freeze_record_failed", "created_at_in_future"): 3,
             ("pre_run_scan_missing",): 2, ("created_at_in_future",): 2, ("run_start_invalid",): 2, ("recording_after_run",): 2,
             ("recording_started_on_missing",): 2, ("replicate_subsample_short",): 2, ("D-14 open", "governance_record_public"): 2,
             ("stub_not_confirmatory",): 2, ("recording_not_live",): 2}
    for reasons, code in table.items():
        assert governance.confirmatory_exit_code(list(reasons)) == code, reasons


def test_utc_today_is_the_utc_date_of_the_clock(monkeypatch):
    # The clock is pinned, so the check cannot straddle 00:00 UTC: 23:30 at UTC-05:00 is the next UTC day.
    import datetime as datetime_module

    monkeypatch.undo()  # the real utc_today, which conftest replaces with the synthetic spec's day

    instant = datetime_module.datetime(2026, 11, 24, 23, 30, tzinfo=datetime_module.timezone(datetime_module.timedelta(hours=-5)))

    class Clock(datetime_module.datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz)

    monkeypatch.setattr(governance._dt, "datetime", Clock)
    assert governance.utc_today() == datetime_module.date(2026, 11, 25)


def test_a_live_recording_must_state_its_start_which_is_not_after_today():
    # A confirmatory replay's recording header states the day its live run started; the runner moves the window's start
    # to it (test_phase10_acceptance covers the runner). A missing, malformed or future day is refused.
    from datetime import date

    today = date(2026, 11, 24)
    assert governance.recording_start_refusals("2026-11-24", today) == governance.recording_start_refusals("2026-11-20", today) == []
    assert governance.recording_start_refusals("2026-11-25", today) == ["recording_after_run"]
    for missing in (None, "", "2026-11-24T00:00:00Z", "2026-13-01", 20261124):
        assert governance.recording_start_refusals(missing, today) == ["recording_started_on_missing"], missing
        assert governance.iso_day(missing) is None


def posix_path_calls(monkeypatch):
    """Path calls as on POSIX, on every platform: `os.path.realpath` (and so `Path.resolve`) raises ValueError for a path
    holding a NUL, where Windows maps it silently (the review 7 CI failure on ubuntu-latest)."""
    import os

    realpath = os.path.realpath

    def posix_realpath(path, *args, **kwargs):
        if "\x00" in os.fspath(path):
            raise ValueError("lstat: embedded null character in path")
        return realpath(path, *args, **kwargs)

    monkeypatch.setattr(os.path, "realpath", posix_realpath)


@pytest.mark.parametrize("posix", [False, True], ids=["native", "posix"])
def test_a_record_path_open_refuses_is_an_invalid_file_never_a_traceback(tmp_path, monkeypatch, posix):
    # An embedded NUL makes open() raise ValueError (and, on POSIX, realpath too): a governance record and a pre-run scan
    # refuse it as `file`, and the public-path check counts it as public (fail closed: the gate refuses the run), on
    # every platform, instead of raising.
    if posix:
        posix_path_calls(monkeypatch)
    for path in ("a\x00b.json", "lqs/private/a\x00b.json", str(tmp_path / "a\x00b.json")):
        nul = {"path": path, "sha256": "0" * 64}
        with pytest.raises(governance.GovernanceError) as error:
            governance.resolve_record(nul, REPO_ROOT)
        assert error.value.field == "file"
        assert governance.scan_refusals(nul, REPO_ROOT, dataset_content_sha256=CONTENT_SHA, corpus_version=synthetic.CORPUS_VERSION, missing="m") == ["pre_run_scan_invalid:file"]
        assert governance.irb_refusals(nul, governance.run_date({"created_at": synthetic.CREATED}), REPO_ROOT, missing="m") == ["irb_invalid:file"]
        assert governance.is_public(nul, REPO_ROOT) is True, path


def test_ci_s_synthetic_scan_report_and_dangling_references_do_not_pass_the_pre_run_scan(tmp_path):
    ci = _ci_scan_report(tmp_path)
    reasons = governance.scan_refusals(ci, REPO_ROOT, dataset_content_sha256=CONTENT_SHA, corpus_version=synthetic.CORPUS_VERSION, missing="m")
    assert "pre_run_scan_invalid:fingerprint_sets" in reasons and "pre_run_scan_invalid:dataset" in reasons
    assert governance.scan_refusals(None, REPO_ROOT, dataset_content_sha256=CONTENT_SHA, corpus_version=synthetic.CORPUS_VERSION, missing="m") == ["m"]
    assert governance.scan_refusals({"path": str(tmp_path / "absent.json"), "sha256": "0" * 64}, REPO_ROOT,
                                    dataset_content_sha256=CONTENT_SHA, corpus_version=synthetic.CORPUS_VERSION, missing="m") == ["pre_run_scan_invalid:file"]
    tampered = dict(ci, sha256="0" * 64)
    assert governance.scan_refusals(tampered, REPO_ROOT, dataset_content_sha256=CONTENT_SHA, corpus_version=synthetic.CORPUS_VERSION, missing="m") == ["pre_run_scan_invalid:sha256"]


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
    # Approved by the window's start, unexpired on today: valid on every day the run's data flow.
    window = synthetic.irb_record(tmp_path / "window.json", approval_date="2026-11-01", expiry_date="2026-12-31")
    assert governance.irb_refusals(window, date(2026, 11, 1), REPO_ROOT, missing="x", today=date(2026, 12, 31)) == []
    assert governance.irb_refusals(window, date(2026, 10, 31), REPO_ROOT, missing="x", today=date(2027, 1, 1)) == [
        "irb_not_yet_approved", "irb_expired"]
