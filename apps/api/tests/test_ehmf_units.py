"""Phase 7 EHMF unit tests (Phase 7 spec 13.2): the routing table, typing, precedence and the template, the library,
the correction guard, the stop's arithmetic, the retrieval penalty, the v6 loader's refusals, the golden-set runner's
exit codes and the source-fidelity checker. Package and DOCX copies live in tmp_path; nothing is written into the checkout.
"""

from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.config_package import (
    DEFAULT_PACKAGE_PATH,
    EHMF_SCHEMA_VERSION,
    ConfigPackageError,
    canonical_sha256,
    get_config_package,
    load_config_package,
)
from app.services.ehmf import classify, routing, vocabulary
from app.services.ehmf.correction import CorrectionGuard, CorrectionLimit, claim_set_sha256, span_set_sha256
from app.services.tutor_pipeline import contracts
from ehmf_fakes import NEXT_PATCH, REPO_ROOT, SHIPPED_VERSION, package_copy, scripts_module

PACKAGE = get_config_package(Settings())


def test_the_routing_table_types_every_non_pass_v1_reason():
    for check_id, reasons in contracts.REASON_OUTCOMES.items():
        for reason, outcome in reasons.items():
            if outcome in ("pass", "mark") or (check_id, reason) in routing.NO_FINDING:
                continue
            assert (check_id, reason) in routing.FINDING_RULES, (check_id, reason)
    assert routing.FINDING_RULES[("V1.4", "unmapped_factual_sentence")] == "D"
    assert all(routing.FINDING_RULES[("V1.4", code)] == "E" for code in contracts.SUBSET_PROBLEM_CODES if code != "unmapped_factual_sentence")
    assert routing.FINDING_RULES[("V1.1", "unresolvable")] == "B1" and routing.routing_table()["B1"]["final"] is True
    assert PACKAGE.raw["ehmf"]["routing"]["sha256"] == routing.routing_sha256()


def test_findings_are_typed_by_failure_mode_and_response_results_stay_off_claim_entries():
    result = contracts.CheckResult(check_id="V1.4", stage="post_render", attempt=1, outcome="hard_fail", ehmf_types=("D", "E"),
                                   reason_code="unmapped_factual_sentence")
    finding = classify.finding_for_v1(result)
    assert finding.type == "D" and finding.claim_id is None
    passing = contracts.CheckResult(check_id="V1.4", stage="post_render", attempt=1, outcome="pass", ehmf_types=("D", "E"), reason_code="mapped")
    assert classify.finding_for_v1(passing) is None
    unavailable = contracts.CheckResult(check_id="V1.3", stage="pre_render", attempt=1, outcome="abstain", ehmf_types=("A", "B", "C"),
                                        reason_code="checker_unavailable", checker_model_id="none")
    assert classify.finding_for_v1(unavailable) is None
    claim_id = "claim-" + "1" * 32
    verdict = contracts.ClaimVerdictV2(claim_id=claim_id, v1=(result,), final="abstain", cycle_count=0)
    entry = classify.claim_entry(verdict, disclosure=None, generation=1, weights=PACKAGE.ehmf.weight_strings())
    assert entry.findings == () and entry.primary is None and entry.weight == "0"


def test_the_primary_type_is_the_heaviest_with_ties_in_primary_order():
    weights = PACKAGE.ehmf.weight_strings()

    def finding(kind: str):
        source, reason = next(key for key, value in routing.FINDING_RULES.items() if value == kind and key[0] != "V1.7")
        return contracts.EhmfFinding(source=source, reason_code=reason, type=kind, attempt=1, family="f" if source == "V2" else None)

    assert contracts.primary_of([finding("C"), finding("E")], weights) == ("C", "3/5")
    assert contracts.primary_of([finding("A"), finding("B1"), finding("B2")], weights) == ("B1", "1")
    assert contracts.primary_of([finding("D"), finding("C")], weights) == ("D", "3/5")
    disclosed = contracts.EhmfFinding(source="V1.7", reason_code="conflict_disclosed", type="D", attempt=1)
    assert contracts.primary_of([disclosed], weights) == ("D", "0")


def test_the_correction_guard_bounds_the_loop_and_hashes_the_sets():
    guard = CorrectionGuard(max_cycles=2)
    guard.begin_cycle(1)
    guard.begin_cycle(2)
    with pytest.raises(CorrectionLimit):
        guard.begin_cycle(3)

    class Claim:
        def __init__(self, claim_id):
            self.claim_id = claim_id

    class Locked:
        def __init__(self, ids, spans):
            self.claims = [Claim(i) for i in ids]
            self.span_ids = spans

    a, b = Locked(["c2", "c1"], ["s1"]), Locked(["c1", "c2"], ["s1"])
    assert claim_set_sha256(a) == claim_set_sha256(b) and guard.check_re_render(a, b)
    assert not guard.check_re_render(a, Locked(["c1"], ["s1"])) and not guard.check_re_render(a, Locked(["c1", "c2"], ["s2"]))
    assert span_set_sha256(a) != span_set_sha256(Locked([], ["s2"]))


def test_the_library_pin_resolves_next_to_the_package_file_and_its_sidecar(tmp_path):
    copy = package_copy(tmp_path / "a", library_edit=lambda raw: raw.update(status="edited status"))
    loaded = load_config_package(copy, governed=False)
    assert loaded.v1.library_sha256 != PACKAGE.v1.library_sha256
    broken = package_copy(tmp_path / "b")
    (broken.parent / "misconceptions" / "v1.json.sha256").write_text("0" * 64 + "\n", encoding="utf-8")
    with pytest.raises(ConfigPackageError, match="sidecar"):
        load_config_package(broken, governed=False)
    synthetic = package_copy(tmp_path / "c", library_edit=lambda raw: raw.update(synthetic=True))
    assert load_config_package(synthetic, governed=False).v1.library_entries == ()


def test_a_package_file_copied_without_its_library_folder_loads_only_the_library_its_pin_names(tmp_path):
    # A package file copied alone (no misconceptions/ folder beside it) reads the shipped library, which must still equal
    # the pin: a copy whose pin names another library is refused, never loaded with the shipped library in its place.
    raw = json.loads(DEFAULT_PACKAGE_PATH.read_text(encoding="utf-8"))
    alone = tmp_path / "alone" / DEFAULT_PACKAGE_PATH.name
    alone.parent.mkdir()
    (alone.parent / "schemas").mkdir()
    for schema in (DEFAULT_PACKAGE_PATH.parent / "schemas").iterdir():
        (alone.parent / "schemas" / schema.name).write_bytes(schema.read_bytes())
    alone.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    assert not (alone.parent / "misconceptions").exists()
    loaded = load_config_package(alone, governed=False)
    assert loaded.v1.library_sha256 == PACKAGE.v1.library_sha256 == raw["v1"]["v1_8"]["library"]["sha256"]
    other = json.loads(json.dumps(raw))
    other["v1"]["v1_8"]["library"]["sha256"] = canonical_sha256({"another": "library"})
    alone.write_text(json.dumps(other, indent=2), encoding="utf-8")
    with pytest.raises(ConfigPackageError, match="v1.v1_8.library"):
        load_config_package(alone, governed=False)
    other["v1"]["v1_8"]["library"]["version"] = "v2"
    other["v1"]["v1_8"]["library"]["sha256"] = raw["v1"]["v1_8"]["library"]["sha256"]
    alone.write_text(json.dumps(other, indent=2), encoding="utf-8")
    with pytest.raises(ConfigPackageError, match="library file's version"):
        load_config_package(alone, governed=False)


def test_the_phase_7_package_number_is_read_from_one_constant_per_side():
    # E16: the Phase 7 package may be renumbered (Phase 8 takes v6 if it reaches main first). The loader's schema rules
    # read EHMF_SCHEMA_VERSION and the ledger's config_version reads EHMF_FIRST_MAJOR; the two are equal, and the shipped
    # package is that schema and that major.
    assert EHMF_SCHEMA_VERSION == vocabulary.EHMF_FIRST_MAJOR == PACKAGE.schema_version == int(SHIPPED_VERSION.split(".")[0])
    assert PACKAGE.raw["ehmf"]["config_version"]["first_package"] == f"{vocabulary.EHMF_FIRST_MAJOR}.0.0"
    loader = (REPO_ROOT / "apps" / "api" / "app" / "core" / "config_package.py").read_text(encoding="utf-8")
    script = (REPO_ROOT / "scripts" / "config_package.py").read_text(encoding="utf-8")
    checks = [(REPO_ROOT / "apps" / "api" / "app" / "services" / name / "package_check.py").read_text(encoding="utf-8")
              for name in ("v3", "tutor_pipeline")]
    import re

    literal = re.compile(rf"\b(?:schema_)?version\s*(?:>=|<|==)\s*{EHMF_SCHEMA_VERSION}\b"
                         rf"|\b(?:schema_)?version in \([^)]*\b{EHMF_SCHEMA_VERSION}\)")
    for source in (loader, script, *checks):
        assert literal.search(source) is None, literal.search(source).group(0)


@pytest.mark.parametrize("edit, match", [
    (lambda raw: raw["ehmf"]["weights"].update(C=0.5), "plan's 6.3 weights"),
    (lambda raw: raw["ehmf"]["weights"].update(D_disclosed=0.1), "D_disclosed"),
    (lambda raw: raw["ehmf"]["routing"].update(sha256="0" * 64), "routing"),
    (lambda raw: raw["ehmf"]["conflicts"].update(applies="always"), "recorded_only"),
    (lambda raw: raw["ehmf"]["correction"].update(third_cycle="allowed"), "third_cycle"),
    (lambda raw: raw["ehmf"]["retrieval_penalty"]["registries"]["production"].update(spans=[{"span_id": "span-" + "1" * 64, "reason": "B2", "gold": "synthetic"}]), "synthetic|no span"),
    (lambda raw: raw["ehmf"]["stop"].update(rise={"numerator": 1, "denominator": 1}), "rise"),
    (lambda raw: raw["ehmf"]["config_version"].update(first_package=NEXT_PATCH), "first_package"),
    (lambda raw: raw["ehmf"].update(provisional=False), "provisional"),
    (lambda raw: raw["owner_decisions"].pop("EHMF-WEIGHTS"), "EHMF-WEIGHTS"),
    (lambda raw: raw["flag_policy"]["ehmf"].update(default_elsewhere="shadow"), "default_elsewhere"),
    (lambda raw: raw["v3"]["triggers"].update(version="x-triggers-v1"), "trigger registry"),
])
def test_v6_the_loader_refuses_what_the_plan_or_the_code_fixes(tmp_path, edit, match):
    with pytest.raises(ConfigPackageError, match=match):
        load_config_package(package_copy(tmp_path, edit), governed=False)


def test_v6_a_later_6_x_package_loads_and_v5_v4_still_parse(tmp_path):
    later = load_config_package(package_copy(tmp_path, lambda raw: raw.update(package_version=NEXT_PATCH)), governed=False)
    assert later.package_version == NEXT_PATCH and later.ehmf is not None
    v5 = load_config_package(PACKAGE.path.with_name("v5.json"), governed=True)
    assert v5.v3.x2_types == ("A", "B") and PACKAGE.v3.x2_types is None
    assert PACKAGE.v3.severity["disclosed_conflict"] == 0 and PACKAGE.v3.severity["C"] == Fraction(3, 5)


def test_the_stop_fires_on_integers_at_its_boundary():
    from app.services.ehmf.stop import _fires

    params = PACKAGE.ehmf
    # after/before rate equal to rise exactly does not fire; one more A/B claim does
    assert not _fires(100, 10, 100, 15, params) and _fires(100, 10, 100, 16, params)
    assert not _fires(100, 0, 99, 50, params) and not _fires(100, 0, 100, 1, params) and _fires(100, 0, 100, 2, params)


def test_the_golden_runner_exits_on_drift_dirty_and_unmet(tmp_path, monkeypatch):
    golden = scripts_module("run_golden_set")
    record = json.loads((REPO_ROOT / "docs" / "evaluation" / "phase7" / "golden_run_v1.json").read_text(encoding="utf-8"))
    drifted = json.loads(json.dumps(record))
    drifted["outcomes"][0]["final"] = "drifted"
    path = tmp_path / "drift.json"
    path.write_text(json.dumps(drifted), encoding="utf-8")
    assert golden.main(["--check", str(path)]) == 1
    monkeypatch.setattr(golden, "_commit", lambda: "abc-dirty")
    assert golden.main(["--write", str(tmp_path / "out.json")]) == 4
    assert golden.main(["--check", str(REPO_ROOT / "lqs" / "x.json")]) == 2
    unmet = json.loads(json.dumps(record))
    path.write_text(json.dumps(unmet), encoding="utf-8")
    original = golden.compute

    def failing(**kwargs):
        fresh = original(**kwargs)
        fresh["result"], fresh["problems"] = "unmet", ["gs-001 did not meet its expectation"]
        return fresh

    monkeypatch.setattr(golden, "compute", failing)
    assert golden.main(["--check", str(path)]) == 3


def test_the_fidelity_checker_refuses_a_moved_location_and_matches_a_corrected_copy(tmp_path):
    import docx

    fidelity = scripts_module("check_source_fidelity")
    register = json.loads(fidelity.DEFAULT_REGISTER.read_text(encoding="utf-8"))
    moved = json.loads(json.dumps(register))
    moved["entries"][0]["location"]["column"] = 3
    moved_path = tmp_path / "moved.json"
    moved_path.write_text(json.dumps(moved), encoding="utf-8")
    assert fidelity.main(["--require-zero", "--register", str(moved_path)]) == 2
    name = register["entries"][0]["docx"]
    document = docx.Document(str(REPO_ROOT / name))
    cells = document.tables[4].rows[2].cells
    cells[4].text, cells[5].text = "0.828", "1.143"
    for paragraph in document.paragraphs:
        if "perfectly aligned" in paragraph.text:
            for run in paragraph.runs:
                run.text = run.text.replace("perfectly aligned", "partly aligned")
    corrected = tmp_path / "corrected.docx"
    document.save(str(corrected))
    report = fidelity.compute(docx_paths={name: corrected})
    # every register entry matches the corrected copy: the two QUEN cells and the GEA wording
    assert report["mismatches"] == 0 and [entry["match"] for entry in report["entries"]] == [True, True, True]
