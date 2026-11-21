"""Phase 3: the records say what the code does (P2-12-D-03): the spec, the ADR revisions, the runbooks, the test
strategy, CI and the requirements.

The authoritative text of each record states the current code only, and the spec's review history (18.4) holds one
row per round. The tests are grouped by the finding they guard (D for the third round to M for the twelfth), each
beside the code it reads. K3 maps every Phase 3 test file: test_phase3_*.py and each feature module whose docstring
opens with "Phase 3". The plan and the evidence package are outside the repository, so their wording is checked by
the evidence package's own 00_meta/check_records.py, never here.
"""

from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path
import re
from typing import get_args

import google.cloud.sql.connector.connector as connector_module
import google.cloud.sql.connector.pg8000 as connector_pg8000
import pg8000
import pg8000.dbapi
import pg8000.exceptions
import pg8000.legacy
from sqlalchemy.dialects.postgresql.pg8000 import PGDialect_pg8000

from app.core import db as db_module
from app.core.config import Settings
from app.core.config_package import DEFAULT_PACKAGE_PATH
from app.schemas import LedgerResponseRead
from app.services import claim_gate, ledger
from app.services.tutor_pipeline import contracts
from app.services.tutor_pipeline.bind import BINDING_RULE
from app.services.tutor_pipeline.package_check import LEAF_KEYWORDS

from tutor_fakes import FAULT_MODES


API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parents[1]
SPEC = (REPO_ROOT / "docs" / "architecture" / "phase3-implementation-spec.md").read_text(encoding="utf-8")
RAW = json.loads(DEFAULT_PACKAGE_PATH.read_text(encoding="utf-8"))
RUNBOOK = (REPO_ROOT / "infra" / "cloudrun" / "deployment.md").read_text(encoding="utf-8")
OBSERVABILITY = (REPO_ROOT / "infra" / "cloudrun" / "observability.md").read_text(encoding="utf-8")
REPLAY_README = (REPO_ROOT / "docs" / "evaluation" / "phase3" / "README.md").read_text(encoding="utf-8")
MIGRATION = (API_ROOT / "alembic" / "versions" / "20261119_phase3_response_ledger.py").read_text(encoding="utf-8")
PHASE2_REVISION = "20261119_phase2_corpus_spans"
TEST_STRATEGY = (REPO_ROOT / "docs" / "testing" / "test-strategy.md").read_text(encoding="utf-8")
ADR = (REPO_ROOT / "docs" / "adr" / "ADR-001-grounding-separation.md").read_text(encoding="utf-8")
README = (REPO_ROOT / "docs" / "evaluation" / "phase3" / "README.md").read_text(encoding="utf-8")
FRONTEND = REPO_ROOT / "apps" / "frontend"
ADR_005 = (REPO_ROOT / "docs" / "adr" / "ADR-005-abstention-gate.md").read_text(encoding="utf-8")
STRATEGY = (REPO_ROOT / "docs" / "testing" / "test-strategy.md").read_text(encoding="utf-8")
RECORD = json.loads((REPO_ROOT / "docs" / "evaluation" / "phase3" / "three_plan_replay_v1.json").read_text(encoding="utf-8"))
ADR_001 = (REPO_ROOT / "docs" / "adr" / "ADR-001-grounding-separation.md").read_text(encoding="utf-8")
V1_RAW = json.loads((API_ROOT / "app" / "config_package" / "v1.json").read_text(encoding="utf-8"))
V2_RAW = json.loads((API_ROOT / "app" / "config_package" / "v2.json").read_text(encoding="utf-8"))
AUTHORITATIVE_SPEC = SPEC.split("## 18. Implementation record", 1)[0]
CI = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


def _section(title: str, end: str) -> str:
    return SPEC.split(title, 1)[1].split(end, 1)[0]


def _test_functions() -> set[str]:
    names = set()
    for path in (API_ROOT / "tests").glob("test_*.py"):
        names |= set(re.findall(r"^(?:async )?def (test_\w+)\(", path.read_text(encoding="utf-8"), flags=re.MULTILINE))
    return names


# =============================================================================================================== D1


def test_d1_the_runbook_sli_sums_the_ratio_terms_not_the_raw_counts():
    runbook = (REPO_ROOT / "infra" / "cloudrun" / "observability.md").read_text(encoding="utf-8")
    assert "jsonPayload.ratio_bound" in runbook and "jsonPayload.ratio_proposed" in runbook
    assert "sum of `jsonPayload.bound` over sum of `jsonPayload.proposed`" not in runbook
    shadow_source = (API_ROOT / "app" / "services" / "tutor_pipeline" / "shadow.py").read_text(encoding="utf-8")
    assert "bound_claim_ratio_terms(entry.counts)" in shadow_source


# =============================================================================================================== D2


def test_d2_the_atomic_claims_reading_is_an_unratified_recorded_deviation():
    decision = RAW["owner_decisions"]["PLAN-3.3"]
    assert decision["ratified"] is False and decision["status"] == "provisional" and "DI-47" in decision["record"]
    (deviation,) = decision["deviations"]
    # The plan itself is outside the repository: the evidence package's 00_meta/check_records.py (check_d2_*) finds this
    # quotation in it.
    assert deviation["plan"] == "3.3: \"Claim plan: atomic claims bound to span ids from a structured envelope; unbound dropped [Risk R-11].\""
    assert "one verbatim whole sentence" in deviation["applied"] and "Phase 5" in deviation["applied"]
    assert "**34. Task 3.3 \"atomic claims\"" in SPEC
    # The behaviour the reading describes: a clause cut from a sentence never binds (a cut can drop a negation).
    assert "not_verbatim" in contracts.BINDING_FAILURES


# =============================================================================================================== D3


def test_d3_plan_12_8_is_quoted_in_full_with_its_proposed_default_and_why_it_is_not_applied():
    retention = RAW["owner_decisions"]["PLAN-12.8"]
    full = "OPEN DECISION. Retention period (Product Owner; Principal Investigator consulted); proposed default release life plus 24 months."
    assert retention["text"] == full  # check_d3_* in the evidence package's 00_meta/check_records.py finds it in the plan
    assert (retention["proposed_default"], retention["proposed_default_applied"], retention["behaviour"]) == ("release life plus 24 months", False, "retain")
    assert "no release life has ended" in retention["why_not_applied"]
    assert "proposed default release life plus 24 months" in SPEC


# =============================================================================================================== D7


def test_d7_the_records_say_what_the_code_does():
    adr5 = (REPO_ROOT / "docs" / "adr" / "ADR-005-abstention-gate.md").read_text(encoding="utf-8")
    assert "NFKC normalisation" not in adr5 and "never NFKC-folded" in adr5 and claim_gate.SUBSET_CHECK_RULE in adr5
    # The spec names the sentence rule in force wherever it states the binding or the evidential rule.
    for stale in ("sentences_v1(span.text)", '"sentence_rule": "sentences-v1"', "a whole `sentences-v1` sentence of every cited span"):
        assert stale not in SPEC, stale
    assert RAW["tutor_pipeline"]["evidential"]["sentence_rule"] == "sentences-v2"


# ============================================================================================================== D10


def test_d10_no_code_claims_a_qa_record_is_unlinkable_while_the_qa_row_exists():
    sources = {
        "ledger.py": (API_ROOT / "app" / "services" / "ledger.py").read_text(encoding="utf-8"),
        "qa_engine.py": (API_ROOT / "app" / "services" / "qa_engine.py").read_text(encoding="utf-8"),
        "contracts.py": (API_ROOT / "app" / "services" / "tutor_pipeline" / "contracts.py").read_text(encoding="utf-8"),
        "verify_ledger.py": (REPO_ROOT / "scripts" / "verify_ledger.py").read_text(encoding="utf-8"),
        "deployment.md": (REPO_ROOT / "infra" / "cloudrun" / "deployment.md").read_text(encoding="utf-8"),
    }
    for name, source in sources.items():
        for claim in ("unlinkable from the start", "holds no learner link", "no learner link is stored", "with no learner link",
                      "holds no link to its Q&A row"):
            assert claim not in source, (name, claim)
    assert "rendered_text_sha256 is its sha256" in sources["ledger.py"]


# ============================================================================================================== D11


def test_d11_the_pydantic_floor_is_declared_and_the_start_up_probe_holds():
    import pydantic

    from app import schemas

    requirements = (API_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    assert "pydantic>=2.12.4,<3" in [line.strip() for line in requirements]
    major, minor, patch = (int(part) for part in pydantic.VERSION.split(".")[:3])
    assert (major, minor, patch) >= (2, 12, 4)
    assert "value" not in schemas._ExcludeIfProbe().model_dump()
    assert schemas.AssistantChatResponse.model_fields["evidence"].exclude_if is not None


# ============================================================================================================== D12


def test_d12_the_required_api_postgres_check_still_reports_under_the_driver_matrix():
    import yaml

    workflow = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    jobs = workflow["jobs"]
    # P1-D-12: the required checks on main are api-and-evaluation, api-postgres and frontend, by job name.
    for required in ("api-and-evaluation", "api-postgres", "frontend"):
        assert required in jobs and "strategy" not in jobs[required] and "name" not in jobs[required], required
    legs = jobs["api-postgres-driver"]
    assert legs["strategy"]["matrix"]["driver"] == ["psycopg", "pg8000"] and legs["name"] == "api-postgres (${{ matrix.driver }})"
    gate = jobs["api-postgres"]
    assert gate["needs"] == ["api-postgres-driver"] and gate["if"] == "always()"
    assert gate["steps"] == [{"run": 'test "${{ needs.api-postgres-driver.result }}" = "success"'}]


# ============================================================================================================== D13


def test_d13_the_runbook_runs_production_ledger_steps_through_the_worker():
    runbook = (REPO_ROOT / "infra" / "cloudrun" / "deployment.md").read_text(encoding="utf-8")
    assert "python -m app.workers.response_ledger --export" in runbook
    assert "python -m app.workers.response_ledger --coverage-since" in runbook
    assert "TUTOR_LEDGER_ENABLED=false" in runbook and "CPU" in runbook
    assert "scripts/verify_ledger.py --export" not in runbook
    # Review round 4 (spec 18.7 E9): the text an operator sees when the downgrade refuses names the worker too.
    migration = (API_ROOT / "alembic" / "versions" / "20261119_phase3_response_ledger.py").read_text(encoding="utf-8")
    assert "scripts/verify_ledger.py --export" not in migration and "python -m app.workers.response_ledger --export" in migration


# =============================================================================================================== E3


def test_e3_the_replay_readme_and_the_spec_say_where_the_ratio_is_reported():
    assert "reported live in `/ready`" not in REPLAY_README and "abstains on all 298 items" not in REPLAY_README
    assert "abstains on all 299 items" in REPLAY_README and "`tutor.two_pass.shadow`" in REPLAY_README
    conflict_11 = next(line for line in SPEC.splitlines() if "Phase 2 defined no such SLI. **Resolution:**" in line)
    assert "and `/ready` report the two-pass ratio" not in conflict_11 and "not on public `/ready`" in conflict_11


# =============================================================================================================== E4


def test_e4_f2_is_recorded_with_the_method_it_was_taken_by():
    di_49 = next(line for line in SPEC.split("## 16.", 1)[1].split("## 17.", 1)[0].splitlines() if line.startswith("| DI-49 |"))
    assert "F-2" in di_49 and "AC-3-1" in di_49 and "static check of logged prompts" in di_49
    history = SPEC.split("### 18.4 Review history", 1)[1]
    assert "<br>E4 F-2 recorded: `test_e4_*`" in history
    # The register row and the phase record are checked by the evidence package's 00_meta/check_records.py (check_e4_*).


# =============================================================================================================== E8


def test_e8_the_text_helpers_say_the_subset_check_never_folds():
    source = (API_ROOT / "app" / "services" / "tutor_pipeline" / "text.py").read_text(encoding="utf-8")
    docstring = source.split('"""')[1]
    assert "(binding and the subset check)" not in docstring and "never folds" in docstring
    package_check = (API_ROOT / "app" / "services" / "tutor_pipeline" / "package_check.py").read_text(encoding="utf-8")
    assert "a floor and a major-version" in package_check


# =============================================================================================================== E9


def test_e9_the_migration_names_the_worker_and_an_absolute_target():
    assert "scripts/verify_ledger.py --export" not in MIGRATION and "downgrade -1" not in MIGRATION
    assert "python -m app.workers.response_ledger --export" in MIGRATION
    assert f"downgrade {PHASE2_REVISION}" in MIGRATION
    conflict_22 = next(line for line in SPEC.splitlines() if line.startswith("**22. Plan G"))
    # The resolution states the current rule only; the superseded `downgrade -1` wording is in no current text.
    assert "scripts/verify_ledger.py --export" not in conflict_22 and "app.workers.response_ledger --export" in conflict_22
    assert "downgrade -1" not in conflict_22 and "--restore" in conflict_22 and "Corrected in" not in conflict_22
    assert "is measured by `verify_ledger.py --coverage-since`" not in SPEC
    assert "alembic -x allow_ledger_drop=true downgrade -1" not in RUNBOOK


# ============================================================================================================== E12


def test_e12_the_runbook_says_what_the_drop_costs_and_how_the_export_is_retired():
    rollback = RUNBOOK.split("**Roll back**", 1)[1]
    assert "--restore" in rollback and "retired chain" in rollback and "owner decision" in rollback
    assert "is optional" in rollback or "needs no downgrade" in rollback
    # The deletion rule is reachable: restore, then the exported head verifies.
    assert "once `python -m app.workers.response_ledger --restore" in rollback


# ============================================================================================================== E13


def test_e13_the_observability_tables_measure_coverage_and_name_every_stop_signal():
    phase3 = OBSERVABILITY.split("## Phase 3 SLIs", 1)[1]
    assert "| Ledger write failures (0) |" in phase3 and "| Ledger coverage (100%) | `jsonPayload.event=\"tutor.ledger.append_failed\"`" not in phase3
    coverage = next(line for line in phase3.splitlines() if line.startswith("| Ledger coverage (100%)"))
    assert "tutor.ledger.attempted" in coverage and "tutor.ledger.appended" in coverage and "surface" in coverage
    assert any(line.startswith("| Deferred appends") and "tutor.ledger.append_deferred" in line for line in phase3.splitlines())
    assert any(line.startswith("| Non-public spans excluded") and "tutor.evidence.non_public_excluded" in line for line in phase3.splitlines())
    integrity = next(line for line in phase3.splitlines() if line.startswith("| Chain integrity"))
    assert 'resource.type="cloud_run_job"' in integrity
    for field in ("tutor_ledger_enabled", "ledger_route_enabled", "evidence_panel_enabled", "tutor_turns_route_enabled"):
        assert f"`{field}`" in phase3, field
    assert "| `tutor.ledger.attempted` |" in phase3


# ============================================================================================================== E14


def test_e14_the_spec_says_what_the_code_and_the_page_do_now():
    conflict_29 = next(line for line in SPEC.splitlines() if "under a total deadline" in line)
    assert "ledger_wait_grace_ms" in conflict_29 and "(default 1500)" not in conflict_29 and "Corrected in" not in conflict_29
    # The superseded constant survives in no current text: only the review history may name it.
    assert "LEGACY_WAIT_GRACE_MS" not in SPEC.split("### 18.4 Review history", 1)[0]
    section_12 = SPEC.split("## 12. Frontend", 1)[1].split("## 13. Tests", 1)[0]
    row = next(line for line in section_12.splitlines() if "MOD `src/lib/privacy-disclosures.ts`" in line)
    for needed in ("can be matched to the learner's Q&A history while it is kept", "deleting the account deletes the tutor turns and the Q&A history",
                   "older than one year", "Kept as an audit record; the retention period is an open owner decision."):
        assert needed in row, needed
    assert "tutor history removes the link" not in row and "Superseded" not in row
    assert "`abstain`: \"No answer: no approved course passage matched this question closely enough\"" in section_12


# =============================================================================================================== F6


def test_f6_hold_h6_blocks_the_provider_interim_path_and_d19_runs_instead():
    path = RAW["owner_decisions"]["D-12"]["path"]
    assert "hold H6 blocks the provider interim path" in path and "runs D-19 extractive mode instead" in path
    assert "the D-19 extractive generator is the interim path" not in path


# =============================================================================================================== F7


def test_f7_the_records_say_what_the_code_does():
    authorization = (API_ROOT / "app" / "core" / "authorization.py").read_text(encoding="utf-8")
    assert "so outside development only owners read (PD-12)" not in authorization
    assert "the route answers 404 to everyone, owners included" in authorization
    ac33 = next(line for line in TEST_STRATEGY.splitlines() if line.startswith("| AC-3-3"))
    assert f"the {len(FAULT_MODES)} fault modes" in ac33 and len(FAULT_MODES) == 12


# ============================================================================================================== F11


def test_f11_the_coverage_stop_reads_terminal_lines_not_windows():
    phase3 = OBSERVABILITY.split("## Phase 3 SLIs", 1)[1]
    coverage = next(line for line in phase3.splitlines() if line.startswith("| Ledger coverage (100%)"))
    assert "exactly one terminal line" in coverage and "`attempt`" in coverage
    assert "an append still running at the window's end counts in the next" not in coverage.split("(spec 18.8 F11", 1)[0]
    stops = RUNBOOK.split("**Stop conditions** (plan Phase 3 L):", 1)[1].split("On a stop:", 1)[0]
    assert "no terminal line" in stops and "is not a loss" in stops
    assert "it is a stop only when its attempt ends in `tutor.ledger.append_failed`" in stops


# ============================================================================================================== F12


def test_f12_the_runbook_records_the_rollback_window():
    rollback = RUNBOOK.split("**Roll back**", 1)[1]
    assert "Record the rollback window" in rollback and "earlier_image" in rollback
    assert "from then on every delivery is expected to have a record" not in RUNBOOK.split("(Corrected in 18.8 F10", 1)[0]


# ============================================================================================================== F16


def _event_names(table_text: str) -> set[str]:
    names = set()
    for line in table_text.splitlines():
        match = re.match(r"\| `(tutor\.[a-z_.]+)` \|", line)
        if match:
            names.add(match.group(1))
    return names


def test_f16_the_spec_and_the_runbook_say_what_the_code_does():
    section_16 = SPEC.split("## 16. Provisional defaults", 1)[1].split("## 17.", 1)[0]
    # Section 16 lists every Phase 3 register row the fourth round added (DI-49, DI-50), in its current text.
    assert "| DI-49 |" in section_16 and "| DI-50 |" in section_16 and "Revised in" not in section_16
    alembic_block = SPEC.split("### 8.3 Alembic", 1)[1].split("### 8.4", 1)[0]
    assert "create the three tables" in alembic_block and "create both tables" not in alembic_block
    # 11.4 names every event the code logs, and so does observability.md.
    logged = set()
    for path in (API_ROOT / "app").rglob("*.py"):
        logged |= set(re.findall(r'"(tutor\.(?:ledger|two_pass|evidence)\.[a-z_]+)"', path.read_text(encoding="utf-8")))
    section_11_4 = SPEC.split("### 11.4 Structured log events", 1)[1].split("## 12.", 1)[0]
    observability = OBSERVABILITY.split("## Phase 3 SLIs", 1)[1]
    assert logged == _event_names(section_11_4) == _event_names(observability), (logged, _event_names(section_11_4), _event_names(observability))
    assert "as `/ready` counts them" not in OBSERVABILITY
    shadow = (API_ROOT / "app" / "services" / "tutor_pipeline" / "shadow.py").read_text(encoding="utf-8")
    assert "exactly as /ready and the replay count them" not in shadow
    metrics = (API_ROOT / "app" / "services" / "tutor_pipeline" / "metrics.py").read_text(encoding="utf-8")
    assert "tests and operators" not in metrics


# =============================================================================================================== G2


# The wording 18.8 F6 corrected in PD-09 and owner_decisions.D-12, and which survived in other records: read against
# plan 9.4 ("OPEN DECISION: a hold stops the named work until its release evidence is filed."; "H6 | Provider [Decision
# D-12] | P3 interim path; P5 exit | Payload register"), it names the running D-19 generator as the work H6 blocks.
SUPERSEDED_D12 = re.compile(r"(?:D-19|extractive)[^.;|\n]*?\bis the (?:Phase 3 |P3 )?interim path|H6 \(P3 interim path\) stays unresolved", re.IGNORECASE)
# A line may quote the old wording only when it says, on that line, that the wording was corrected.
CORRECTION_MARK = re.compile(r"[Cc]orrected in 18\.8 F6")


def _records() -> list[Path]:
    """The repository's record set: the API code and package, the repository docs and runbooks, the scripts and CI.
    Tests are not records. The evidence package's registers and Phase 3 records are outside the repository: its own
    00_meta/check_records.py scans them with the same pattern (check_g2_*)."""
    paths = [path for path in (API_ROOT / "app").rglob("*") if path.suffix in {".py", ".json"} and "__pycache__" not in path.parts]
    paths += list((REPO_ROOT / "docs").rglob("*.md")) + list((REPO_ROOT / "infra").rglob("*.md"))
    paths += list((REPO_ROOT / "scripts").glob("*.py")) + list(REPO_ROOT.glob("*.md")) + list((REPO_ROOT / ".github").rglob("*.yml"))
    return sorted(paths)


def test_g2_no_record_calls_the_running_d19_generator_the_interim_path_hold_h6_blocks():
    # The pattern catches each wording the reviews found (the package, PD-09, the WIRED_GENERATORS comment, the spec
    # 5.1 listing and the closure notes' R-11 line).
    for old in ("the D-19 extractive generator is the interim path",
                "no provider generator is wired; hold H6 (P3 interim path) stays unresolved",
                "H6 stays open. The D-19 extractive generator is the Phase 3 interim path, with no provider payloads",
                "(D-12 open; the D-19 extractive generator is the interim path)"):
        assert SUPERSEDED_D12.search(old), old
    records = _records()
    assert len(records) > 50 and (API_ROOT / "app" / "core" / "config_package.py") in records
    offending = [f"{path}:{number}: {line.strip()[:160]}" for path in records
                 for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
                 if SUPERSEDED_D12.search(line) and not CORRECTION_MARK.search(line)]
    assert offending == []


def test_g2_the_code_comment_the_spec_listing_and_the_closure_notes_say_h6_blocks_the_provider_interim_path():
    path = RAW["owner_decisions"]["D-12"]["path"]
    assert "hold H6 blocks the provider interim path" in path and "runs D-19 extractive mode instead" in path
    # The comment beside WIRED_GENERATORS (the contiguous comment lines above it).
    lines = (API_ROOT / "app" / "core" / "config_package.py").read_text(encoding="utf-8").splitlines()
    index = next(number for number, line in enumerate(lines) if line.startswith("WIRED_GENERATORS = "))
    comment = []
    while lines[index - 1 - len(comment)].startswith("#"):
        comment.insert(0, lines[index - 1 - len(comment)])
    comment_text = " ".join(line.lstrip("# ") for line in comment)
    assert "Hold H6 blocks the provider interim path" in comment_text and "D-19 extractive generator instead" in comment_text
    # The spec 5.1 listing of v2.json quotes the package's D-12 path and its evidential block's keys.
    listed = re.search(r'"D-12": \{"state": "open", "path": "([^"]+)"', SPEC)
    assert listed and listed.group(1) == path
    section = SPEC.split("### 5.1 File", 1)[1].split("### 5.2", 1)[0]
    evidential = section.split('"evidential": {', 1)[1].split("}", 1)[0]
    assert set(re.findall(r'"([a-z_]+)":', evidential)) == set(RAW["tutor_pipeline"]["evidential"])
    # The spec 16.1 PD-09 row states the current wording, as the register does.
    pd09 = next(line for line in SPEC.splitlines() if line.startswith("| PD-09 |"))
    assert "hold H6 blocks the provider interim path" in pd09 and not SUPERSEDED_D12.search(pd09)
    # The closure notes' R-11 line is checked by the evidence package's 00_meta/check_records.py (check_g2_*).


# =============================================================================================================== H1


def test_h1_the_records_say_binding_refuses_span_edge_fragments():
    assert BINDING_RULE == RAW["tutor_pipeline"]["evidential"]["binding_rule"] == "resolver-bundle-sentence-v2"
    conflict_32 = SPEC.split("**32. D-19", 1)[1].split("**33.", 1)[0]
    assert "resolver-bundle-sentence-v2" in conflict_32 and "partial_sentence" in conflict_32
    assert "resolver-bundle-sentence-v1" not in conflict_32  # the superseded rule is in the review history only
    bind_section = SPEC.split("### 4.6 Bind", 1)[1].split("### 4.7", 1)[0]
    assert "`partial_sentence`" in bind_section and "section text" in bind_section
    revision = ADR.split("## Revision 2026-11-19", 1)[1]
    assert "resolver-bundle-sentence-v2" in revision and "partial_sentence" in revision and "resolver-bundle-sentence-v1" not in revision
    assert "span's edge" in revision
    applied = RAW["owner_decisions"]["PLAN-3.3"]["deviations"][0]["applied"]
    assert "partial_sentence" in applied and "wholly inside the span" in applied
    bind_doc = ast.get_docstring(ast.parse((API_ROOT / "app" / "services" / "tutor_pipeline" / "bind.py").read_text(encoding="utf-8")))
    assert "section text" in bind_doc and "partial_sentence" in bind_doc
    assert "binding `resolver-bundle-sentence-v2`" in README
    record = json.loads((REPO_ROOT / "docs" / "evaluation" / "phase3" / "three_plan_replay_v1.json").read_text(encoding="utf-8"))
    assert record["tutor_pipeline"]["binding_rule"] == "resolver-bundle-sentence-v2"


# =============================================================================================================== H4


def test_h4_the_ac_3_2_record_test_supplies_its_commit_and_refuses_processes():
    acceptance = (API_ROOT / "tests" / "test_phase3_acceptance.py").read_text(encoding="utf-8")
    tree = ast.parse(acceptance)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    record_test = functions["test_ac_3_2_the_replay_finds_no_mismatch_and_is_labelled_not_e3_or_lq1"]
    calls = [node for node in ast.walk(record_test) if isinstance(node, ast.Call)]
    assert any(isinstance(call.func, ast.Name) and call.func.id == "refuse_processes" for call in calls)
    compute = next(call for call in calls if isinstance(call.func, ast.Attribute) and call.func.attr == "compute")
    assert "commit_source" in {keyword.arg for keyword in compute.keywords}
    # The run-time proof is in the acceptance file: a replay with its own commit and the record check run with every
    # process refused, and the default commit is the only process the replay starts.
    assert "test_ac_3_2_the_record_check_and_a_replay_with_its_own_commit_run_no_process" in functions
    history_scan = (API_ROOT / "tests" / "test_replay_history_scan.py").read_text(encoding="utf-8")
    assert "Corrected in 18.10 H4" in history_scan
    # The spec's review history records G1 with its tests and H4 with the run-time test.
    history = SPEC.split("### 18.4 Review history", 1)[1]
    seventh = next(line for line in history.splitlines() if line.startswith("| 7, H1-H9 "))
    assert "`test_h4_*`, `test_ac_3_2_the_record_check_and_a_replay_with_its_own_commit_run_no_process`" in seventh
    assert "| 6, G1-G2 " in history


# =========================================================================================================== H6, H7


def test_h6_the_ledger_records_say_what_the_code_does():
    models = (API_ROOT / "app" / "db_models.py").read_text(encoding="utf-8")
    head_comment = models.split("class ResponseLedgerHead", 1)[1].split("started_at: Mapped", 1)[0]
    assert "start-up while TUTOR_LEDGER_ENABLED" not in head_comment and "ledger_record_expected" in head_comment
    append = SPEC.split("**Append**", 1)[1].split("**`record_legacy_delivery`**", 1)[0]
    step_3 = next(line for line in append.splitlines() if line.startswith("3. "))
    assert "Start-up writes no head" in step_3 and "mark_ledger_started" not in step_3
    step_7 = next(line for line in append.splitlines() if line.startswith("7. "))
    assert "40P01" in step_7 and "40001" in step_7 and "other than `IntegrityError` raises at once" not in step_7
    conflict_29 = SPEC.split("**29. E1", 1)[1].split("**30.", 1)[0]
    assert "40P01" in conflict_29 and "only `IntegrityError` is retried" not in conflict_29
    orm = SPEC.split("### 8.1 ORM", 1)[1].split("### 8.2", 1)[0]
    started = next(line for line in orm.splitlines() if line.startswith("`started_at` is informational"))
    assert "ledger_record_expected" in started and "start-up marker" not in started
    triggers = SPEC.split("### 8.2 Triggers", 1)[1].split("**PostgreSQL**", 1)[0]
    assert "re-created only when" in triggers and "re-created on every start\"" not in triggers
    assert "mark_ledger_started" not in SPEC.split("### 18.4 Review history", 1)[0]
    for path in (API_ROOT / "app" / "core" / "schema_upgrades.py", API_ROOT / "alembic" / "versions" / "20261119_phase3_response_ledger.py",
                 API_ROOT / "alembic" / "versions" / "20261119_phase2_corpus_spans.py"):
        text = path.read_text(encoding="utf-8")
        assert "Re-created on every start" not in text
        assert not any("re-created on every" in line.lower() for line in text.splitlines()), path


def test_h7_the_verify_script_section_names_the_split_coverage_counts():
    section = SPEC.split("### 7.16 NEW `scripts/verify_ledger.py`", 1)[1].split("### 7.17", 1)[0]
    for key in ("turns_since", "unrecorded", "pending", "not_expected_earlier_image", "ledger_disabled", "qa_records_since"):
        assert f"`{key}`" in section, key
    assert '{"turns_since": n, "unrecorded": m}' not in section  # the superseded block is in the review history only


# =============================================================================================================== H8


def test_h8_spec_7_17_says_the_record_names_its_code_by_inputs():
    section = SPEC.split("### 7.17 NEW `scripts/replay_tutor_plans.py`", 1)[1].split("### 7.18", 1)[0]
    assert '"inputs": {"rule": "imported-repository-modules-sha256-lf-v1"' in section
    assert "**`inputs`**" in section and "**`commit`** is informational" in section
    stale = [line for line in SPEC.splitlines() if "names the commit that holds the code" in line and "Corrected in 18.10 H8" not in line]
    assert stale == [], stale


# =============================================================================================================== I1


def test_i1_the_records_name_both_reasons():
    listing = re.search(r"^ABSTENTION_REASONS = (\(.*?\))", SPEC, flags=re.MULTILINE | re.DOTALL)
    names = {"NO_QUOTABLE_EVIDENCE": contracts.NO_QUOTABLE_EVIDENCE, "NO_WHOLE_SENTENCE": contracts.NO_WHOLE_SENTENCE, "RENDER_FAILED": contracts.RENDER_FAILED}
    assert listing and eval(listing.group(1), {}, names) == contracts.ABSTENTION_REASONS  # noqa: S307 - the spec's listing of the code
    revision = ADR_005.split("## Revision 2026-11-19 (Phase 3)", 1)[1]
    for reason in set(contracts.ABSTENTION_REASONS) - set(contracts.GATE_ABSTENTION_REASONS):
        assert f"`{reason}`" in revision, reason
    envelope = _section("**`build_envelope`**", "**`ExtractiveD19Generator.propose`**")
    assert "`no_quotable_evidence`" in envelope and "`no_whole_sentence`" in envelope
    assert "the pipeline gave that reason for both causes" not in envelope
    step_3 = next(line for line in _section("### 4.10 Pipeline", "### 4.11").splitlines() if line.startswith("3. "))
    assert "`no_quotable_evidence`" in step_3 and "`no_whole_sentence`" in step_3
    assert "`no_whole_sentence` (11 under `bm25f-v1`, 13 under `p1-floor`)" in README
    observability = (REPO_ROOT / "infra" / "cloudrun" / "observability.md").read_text(encoding="utf-8")
    shadow_row = next(line for line in observability.splitlines() if line.startswith("| Shadow abstention by reason |"))
    assert "`no_quotable_evidence`" in shadow_row and "`no_whole_sentence`" in shadow_row
    by_name = {(config["name"], config["gate"]): config["abstention_by_reason"] for config in RECORD["configurations"]}
    assert by_name[("governed_empty", "p1-floor")].get("no_quotable_evidence", 0) > 0 and "no_whole_sentence" not in by_name[("governed_empty", "p1-floor")]
    for gate, count in (("bm25f-v1", 11), ("p1-floor", 13)):
        reasons = by_name[("all_public_approved", gate)]
        assert reasons.get("no_whole_sentence") == count and "no_quotable_evidence" not in reasons, (gate, reasons)
    # The superseded counts survive in no current text (the evidence package's: check_i1_* in its check_records.py).
    texts = {"spec": SPEC.split("### 18.4 Review history", 1)[0], "README": README}
    for name, text in texts.items():
        for line in text.splitlines():
            assert not re.search(r"`no_quotable_evidence` \(?11\b|extra abstentions are `no_quotable_evidence`", line), (name, line[:160])


# =============================================================================================================== I2


def test_i2_the_fault_tests_run_on_the_several_claim_query_and_the_records_say_so():
    acceptance = (API_ROOT / "tests" / "test_phase3_acceptance.py").read_text(encoding="utf-8")
    fault_test = acceptance.split("def test_ac_3_3_a_renderer_that_adds_a_claim_a_citation_or_a_fact_in_a_connective_is_caught", 1)[1].split("\ndef ", 1)[0]
    assert "query = MULTI_CLAIM" in fault_test and "exact=True" in fault_test and "FAULT_SIGNATURES[mode]" in fault_test
    rendering = (API_ROOT / "tests" / "test_tutor_pipeline_rendering.py").read_text(encoding="utf-8")
    for name in ("test_e1_a_rendering_that_lists_a_span_it_never_shows_never_answers", "test_e1_the_rule_id_names_the_new_behaviour_and_the_fault_modes_include_it"):
        body = rendering.split(f"def {name}", 1)[1].split("\ndef ", 1)[0]
        assert "IN_DOMAIN)" not in body and 'seen == [("citation_list_mismatch",)] * 3' in body, name
    eighth = next(line for line in SPEC.split("### 18.4 Review history", 1)[1].splitlines() if line.startswith("| 8, I1-I8 "))
    assert "I2 every fault mode is placed as itself on a several-claim answer: `test_i2_*`" in eighth
    item_9 = next(line for line in SPEC.splitlines() if line.startswith("9. `test_ac_3_3_a_renderer_that_adds"))
    assert "FAULT_SIGNATURES" in item_9 and "several-claim" in item_9


# =============================================================================================================== I3


def test_i3_the_contract_listing_and_the_evidential_pass_say_what_the_code_does():
    listing = _section("### 3.1 Evidential channel", "### 3.2")
    envelope_span = listing.split("class EnvelopeSpan(Contract):", 1)[1].split("\nclass ", 1)[0]
    assert "whole_sentence_text" in envelope_span
    assert "the span's own text from the span registry" not in envelope_span
    locked_claim = listing.split("class LockedClaim(Contract):", 1)[1].split("\nclass ", 1)[0]
    assert "source_order: tuple[str, int]" in locked_claim
    assert "(item_id, char_start) of the first span id in sorted order" not in locked_claim
    rule = _section("### 4.7 Lock", "### 4.8")
    assert "item offset of the sentence's first character" in rule
    # 4.5's prompt-hash listing holds exactly the keys the code hashes.
    source = (API_ROOT / "app" / "services" / "tutor_pipeline" / "evidential.py").read_text(encoding="utf-8")
    function = next(node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.FunctionDef) and node.name == "evidential_prompt_hash")
    hashed = {key.value for node in ast.walk(function) if isinstance(node, ast.Dict) for key in node.keys}
    assert "min_question_overlap_terms" in hashed
    evidential = _section("### 4.5 Evidential pass", "### 4.6")
    block = evidential.split("def evidential_prompt_hash(params) -> str:", 1)[1].split("```", 1)[0]
    assert set(re.findall(r'"(\w+)":', block)) == hashed, block
    propose = next(line for line in evidential.splitlines() if line.startswith("- For each envelope span"))
    assert "`min_question_overlap_terms`" in propose and "the intersection is non-empty" not in propose
    # 5.4 names the leaf comparison the structural check makes.
    structural = next(line for line in _section("### 5.4 Pipeline/package", "### 5.5").splitlines() if line.startswith("With `structural=True`"))
    assert "LEAF_KEYWORDS" in structural and "`$ref`" in structural
    named = {"type", "enum", "const", "pattern", "format", "multipleOf", "uniqueItems", "default"}
    assert all(f"`{key}`" in structural for key in named)
    assert all(re.match(r"(min|max|exclusive)", key) for key in set(LEAF_KEYWORDS) - named) and "bounds" in structural


# =============================================================================================================== I4


def test_i4_the_ledger_route_listing_and_its_no_record_rule_say_what_the_code_does():
    listing = _section("### 3.4 API additions", "### 4.").split("class LedgerResponseRead(BaseModel):", 1)[1].split("```", 1)[0]
    fields = re.findall(r"^    (\w+): ", listing, flags=re.MULTILINE)
    assert fields == list(LedgerResponseRead.model_fields), fields
    literal = re.search(r'unrecorded_reason: Literal\[(.*?)\]', listing)
    assert literal and set(ast.literal_eval(f"({literal.group(1)},)")) == set(get_args(get_args(LedgerResponseRead.model_fields["unrecorded_reason"].annotation)[0]))
    assert "ledger_record_expected" in listing and "ledger_started_at" not in listing
    step_3 = next(line for line in _section("### 7.13 Routes", "### 7.14").splitlines() if line.startswith("3. **Everyone else:**"))
    for needed in ("ledger_record_expected", "unrecorded_reason", "`earlier_image`", "`ledger_disabled`", "`missing`", "`ledger_started_at` decides nothing"):
        assert needed in step_3, needed
    stale = [line for line in SPEC.split("### 18.4 Review history", 1)[0].splitlines() if "created before `ledger.ledger_started_at" in line]
    assert stale == [], stale
    route = (API_ROOT / "app" / "api" / "routes" / "ledger.py").read_text(encoding="utf-8")
    assert "turn.ledger_record_expected" in route and "ledger_started_at" not in route


# =============================================================================================================== I5


def test_i5_the_registers_and_spec_sections_6_and_16_say_what_the_code_does():
    settings = Settings()
    assert hasattr(settings, "ledger_rate_limit") and not hasattr(settings, "tutor_turns_rate_limit")
    section_6 = _section("## 6. Settings", "## 7. File-by-file changes")
    table_settings = set(re.findall(r"^\| `([A-Z_]+)` \|", section_6, flags=re.MULTILINE))
    example = (REPO_ROOT / "infra" / "cloudrun" / "api-production.env.example.yaml").read_text(encoding="utf-8")
    set_keys = dict(re.findall(r'^([A-Z_]+): "([^"]*)"', example, flags=re.MULTILINE))
    phase3_set = {key: value for key, value in set_keys.items() if key in table_settings}
    bullet = next(line for line in section_6.splitlines() if line.startswith("- `infra/cloudrun/api-production.env.example.yaml`"))
    named = dict(re.findall(r'`([A-Z_]+): "([^"]*)"`', bullet))
    assert named == phase3_set and len(named) == 5, (named, phase3_set)
    for budget in ("TWO_PASS_SHADOW_BUDGET_MS", "TUTOR_LEDGER_APPEND_BUDGET_MS"):
        assert budget not in set_keys and f"`{budget}`" in bullet
    assert "TUTOR_TURNS_RATE_LIMIT" not in section_6 and not any("gains the eight settings" in line for line in SPEC.splitlines())
    section_16 = _section("## 16. Provisional defaults", "## 17.")
    from app.services.tutor_pipeline.bind import BINDING_RULE

    pd_08_copy = next(line for line in section_16.splitlines() if line.startswith("| PD-08 |"))
    assert f"`{BINDING_RULE}`" in pd_08_copy and "resolver-bundle-sentence-v1" not in pd_08_copy
    assert "Revised in" not in section_16
    # The register's PD-08 and PD-11 rows are checked by the evidence package's 00_meta/check_records.py (check_i5_*).


# =============================================================================================================== I6


def test_i6_spec_12_lists_every_production_frontend_change():
    proxy = (FRONTEND / "src" / "lib" / "guest-session.ts").read_text(encoding="utf-8")
    assert "/^\\/spans\\/span-[0-9a-f]{64}$/" in proxy and "/^\\/evidence\\/spans\\/span-[0-9a-f]{64}$/" in proxy
    section_12 = _section("## 12. Frontend", "## 13. Tests")
    rows = [line for line in section_12.splitlines() if line.startswith("| ") and not line.startswith("| File") and not line.startswith("|---")]
    for path in ("src/lib/types.ts", "src/lib/evidence-panel.ts", "src/components/evidence-panel.tsx", "src/components/teaching-assistant-chat.tsx",
                 "src/components/qa-panel.tsx", "src/app/globals.css", "src/lib/privacy-disclosures.ts", "src/lib/guest-session.ts"):
        assert (FRONTEND / path).exists(), path
        assert any(f"`{path}`" in row.split(" | ", 1)[0] for row in rows), path
    production = next(line for line in section_12.splitlines() if line.startswith("**Production.**"))
    assert "`guest-session.ts`" in production and "Two frontend changes ship to production" in production
    assert not any("the privacy row is the only production frontend change" in line for line in SPEC.splitlines())
    second = next(line for line in SPEC.split("### 18.4 Review history", 1)[1].splitlines() if line.startswith("| 2, C1-C12 "))
    assert "C11 a span link never mints a guest session in the proxy" in second


# =============================================================================================================== I8


def test_i8_the_test_strategy_maps_every_review_round_and_names_only_tests_that_exist():
    phase_3 = STRATEGY.split("## Phase 3 acceptance map", 1)[1].split("**Exit gate.**", 1)[0]
    functions = _test_functions()
    rows = [line for line in phase_3.splitlines() if line.startswith("| ") and not line.startswith("| AC |") and not line.startswith("| File |") and not line.startswith("|---")]
    for row in rows:
        ac = re.match(r"\| AC-3-(\d)", row)
        prefix = f"test_ac_3_{ac.group(1)}" if ac else None
        for match in re.finditer(r"`(test_[a-z0-9_]+)`", row):
            assert match.group(1) in functions, match.group(1)
        for match in re.finditer(r"`\.\.\.(_[a-z0-9_]+)`", row):
            assert prefix and prefix + match.group(1) in functions, (prefix, match.group(1))
        for match in re.finditer(r"`(test_[a-z0-9_]+?)_?\*`", row):
            assert any(name.startswith(match.group(1)) for name in functions), match.group(1)
    for name in _phase3_test_files():
        assert f"`{name}`" in phase_3, name
    for module in _phase3_test_files():
        if module == "test_phase3_acceptance.py":
            continue  # its rows are the AC rows above
        row = next((line for line in rows if line.startswith(f"| `{module}` |")), None)
        assert row, module
        source = (API_ROOT / "tests" / module).read_text(encoding="utf-8")
        for name in re.findall(r"^def (test_\w+)\(", source, flags=re.MULTILINE):
            group = re.match(r"(test_[a-z]\d*)_", name).group(1)
            assert f"`{group}_*`" in row, (module, name)
    ac_3_2 = next(line for line in rows if line.startswith("| AC-3-2"))
    assert "`..._the_record_check_and_a_replay_with_its_own_commit_run_no_process`" in ac_3_2
    ac_3_3 = next(line for line in rows if line.startswith("| AC-3-3"))
    assert "`partial_sentence`" in ac_3_3 and "several-claim answer" in ac_3_3


# =============================================================================================================== J1


def test_j1_the_records_count_a_duplicate_as_bound():
    constants = _section("### 3.3 Ledger entry", "### 3.4")
    assert 'BINDING_FAILURES = ("unbound", "outside_bundle", "unresolvable", "not_quotable", PARTIAL_SENTENCE, "not_verbatim")' in constants
    assert "DROP_REASONS = (*BINDING_FAILURES, MERGED, DUPLICATE, BUDGET_SKIPPED" in constants and "so the ratio counts it as bound" in constants
    row = next(line for line in _section("### 4.6 Bind", "### 4.7").splitlines() if line.startswith("| the same sentence was already bound on every span"))
    assert "`duplicate`" in row and "the ratio counts it as bound" in row
    metrics = next(line for line in _section("### 11.3 Metrics", "### 11.4").splitlines() if line.startswith("- `bound_claim_ratio = "))
    assert "`merged` and `duplicate` claims passed every binding check and are in both" in metrics
    assert "and so does a duplicate" in README and "a merged or duplicate claim in both" in OBSERVABILITY
    assert "which read a merge, a duplicate or a budget overrun as a binding failure" in OBSERVABILITY
    source = (API_ROOT / "app" / "services" / "tutor_pipeline" / "contracts.py").read_text(encoding="utf-8")
    terms = source.split("def bound_claim_ratio_terms", 1)[1].split("\nclass ", 1)[0]
    assert "dropped.get(DUPLICATE, 0)" in terms and "dropped.get(MERGED, 0)" in terms


# =============================================================================================================== J2


def test_j2_the_records_name_what_the_invariant_1_fixture_compares():
    acceptance = (API_ROOT / "tests" / "test_phase3_acceptance.py").read_text(encoding="utf-8")
    helper = acceptance.split("def observe_three_learners(", 1)[1].split("\ndef ", 1)[0]
    for needed in ('"retrieve":', '"top_k": kw.get("top_k")', '"envelopes":', '"plans":', '"record": learner_independent(entry)'):
        assert needed in helper, needed
    test = acceptance.split("def test_ac_3_1_what_the_evidential_pass_receives_holds_zero_learner_state_under_three_learner_contexts", 1)[1].split("\ndef ", 1)[0]
    assert "observe_three_learners(monkeypatch)" in test and "all(learner == observed[0] for learner in observed)" in test
    item_3 = next(line for line in SPEC.splitlines() if line.startswith("3. `test_ac_3_1_what_the_evidential_pass_receives"))
    for needed in ("`ClaimPlan`s", "threshold version", "abstention reason", "`top_k`", "`test_k1_*`"):
        assert needed in item_3, needed
    revision = ADR_001.split("## Revision 2026-11-19", 1)[1]
    sentence = next(line for line in revision.splitlines() if "The invariant 1 test replays" in line)
    assert "ClaimPlans" in sentence and "threshold version" in sentence and "every field of the shadow record but its ids" in sentence
    ac_3_1 = next(line for line in STRATEGY.splitlines() if line.startswith("| AC-3-1"))
    assert "ClaimPlans" in ac_3_1 and "`test_k1_*`" in ac_3_1 and "`test_j2_*`" in ac_3_1


# =============================================================================================================== J3


def test_j3_the_records_name_the_render_fault():
    step_7 = next(line for line in _section("### 4.10 Pipeline", "### 4.11").splitlines() if line.startswith("7. **Render loop.**"))
    assert "`tutor.two_pass.render_failed`" in step_7 and "`render_failed`" in step_7 and "the exception was swallowed" not in step_7
    revision = ADR_005.split("## Revision 2026-11-19 (Phase 3)", 1)[1]
    assert "`render_failed`" in revision and "`tutor.two_pass.render_failed`" in revision
    assert any(line.startswith("| `tutor.two_pass.render_failed` |") for line in OBSERVABILITY.splitlines())
    alert = next(line for line in OBSERVABILITY.splitlines() if line.startswith("| Shadow render faults |"))
    assert 'jsonPayload.event="tutor.two_pass.render_failed"' in alert and "Alert on any match" in alert
    reasons = next(line for line in OBSERVABILITY.splitlines() if line.startswith("| Shadow abstention by reason |"))
    assert "`render_failed`" in reasons
    source = (API_ROOT / "app" / "services" / "tutor_pipeline" / "pipeline.py").read_text(encoding="utf-8")
    function = source.split("def render_checked(", 1)[1].split("\nclass ", 1)[0]
    assert "except Exception:  # noqa: BLE001 - a renderer fault is a failed attempt" not in function
    assert '"tutor.two_pass.render_failed"' in function and "contracts.RENDER_FAILED" in function


# =============================================================================================================== J4


def test_j4_spec_18_11_says_what_the_pipeline_records_for_a_refused_fault():
    # The spec's current text and its review history never say the pipeline records `not_placed`: only the test fake does.
    assert "the pipeline records `not_placed`" not in SPEC
    item_9 = next(line for line in SPEC.splitlines() if line.startswith("9. `test_ac_3_3_a_renderer_that_adds"))
    assert "every exact injection asserts what it placed" in item_9
    ninth = next(line for line in SPEC.split("### 18.4 Review history", 1)[1].splitlines() if line.startswith("| 9, J1-J8 "))
    assert "J4 every exact fault test asserts what it placed: `test_j4_*`" in ninth
    assert "not_placed" not in "".join(path.read_text(encoding="utf-8") for path in (API_ROOT / "app").rglob("*.py"))


# =============================================================================================================== J5


def test_j5_the_runbook_and_the_spec_name_the_pending_count():
    bullet = next(line for line in RUNBOOK.splitlines() if line.startswith("- `python -m app.workers.response_ledger --coverage-since <time>`"))
    for needed in ("`pending`", "`horizon_s`", "360 s", "`--coverage-horizon-s 0`", "`ledger.attempt_horizon_s`"):
        assert needed in bullet, needed
    row = next(line for line in OBSERVABILITY.splitlines() if line.startswith("| Ledger coverage (100%) |"))
    assert "`pending`" in row and "360 s" in row
    for title, end in (("### 7.15 NEW", "### 7.16"), ("### 7.16 NEW", "### 7.17")):
        section = _section(title, end)
        assert "`--coverage-horizon-s" in section and "`pending`" in section, title
    script = _section("### 7.16 NEW", "### 7.17")
    for key in ("`pending`", "`horizon_s`", "`settled_before`"):
        assert key in script, key


# =============================================================================================================== J6


def test_j6_the_runbook_reads_the_horizon_by_cpu_allocation():
    stop = next(line for line in RUNBOOK.splitlines() if line.startswith("- ledger coverage below 100%"))
    for needed in ("360 s", "always-on CPU allocation", "until the allocation is read and recorded (DI-48)", "request-based CPU allocation recorded",
                   "has stopped", "`pending` is not a stop"):
        assert needed in stop, needed
    deferred = next(line for line in RUNBOOK.splitlines() if line.startswith("Each `tutor.ledger.append_deferred`"))
    assert "within the horizon is not a stop" in deferred and "30 s connect bound that `app.core.db` enforces" in deferred
    cpu = next(line for line in RUNBOOK.splitlines() if line.startswith("- **Check CPU allocation after the response.**"))
    assert "Until the allocation is read and recorded, read the stops as for always-on CPU" in cpu
    row = next(line for line in OBSERVABILITY.splitlines() if line.startswith("| Ledger coverage (100%) |"))
    for needed in ("360 s", "`ledger.attempt_horizon_s`", "30 s checkout timeout", "30 s connect bound that `app.core.db` enforces", "six statements",
                   "16 in flight on 4 workers", "always-on CPU allocation", "Python runs the queued appends before the process exits"):
        assert needed in row, needed
    # No current text gives the 60 s horizon: it is in the review history only. The 60 s keepalive bound on a read
    # whose peer is gone (app.core.db.DEAD_PEER_BOUND_S; round 11, L3) is not a horizon, so its phrases are read out
    # first.
    keepalive_bound = ("within 60 s of the connection's last traffic", "`DEAD_PEER_BOUND_S` (60 s)")
    for name, text in (("runbook", RUNBOOK), ("observability", OBSERVABILITY), ("spec", SPEC.split("### 18.4 Review history", 1)[0])):
        for line in text.splitlines():
            for phrase in keepalive_bound:
                line = line.replace(phrase, "")
            assert not (re.search(r"\b60 s\b", line) and "horizon" in line and "60 s for ingestion" not in line and "`HORIZON_MARGIN_S` (60 s)" not in line
                        and "`HORIZON_MARGIN_S` 60 s" not in line), (name, line[:160])


# =============================================================================================================== J7


def test_j7_spec_4_11_section_9_and_tests_28_and_39_say_what_the_code_does():
    shadow = _section("### 4.11 Shadow runner", "### 4.12")
    listing = shadow.split("```python", 1)[1].split("```", 1)[0]
    assert "TWO_PASS_DELIVERY_IMPLEMENTED = False" not in listing and "def shadow_budget_ms" in listing
    assert "TWO_PASS_DELIVERY_IMPLEMENTED lives in contracts.py" in listing
    step_3 = next(line for line in shadow.splitlines() if line.startswith("3. `pipeline.run("))
    assert "budget_ms=shadow_budget_ms(settings, pipeline.package)" in step_3 and "settings.two_pass_shadow_budget_ms`" not in step_3
    source = (API_ROOT / "app" / "services" / "tutor_pipeline" / "shadow.py").read_text(encoding="utf-8")
    assert "budget_ms=shadow_budget_ms(settings, pipeline.package)" in source and "TWO_PASS_DELIVERY_IMPLEMENTED =" not in source
    assert "TWO_PASS_DELIVERY_IMPLEMENTED = False" in (API_ROOT / "app" / "services" / "tutor_pipeline" / "contracts.py").read_text(encoding="utf-8")
    note = next(line for line in SPEC.splitlines() if line.startswith("**Connection note.**"))
    assert "`shadow_budget_ms`" in note and "the package's 2000 ms unless `TWO_PASS_SHADOW_BUDGET_MS` overrides it" in note
    item_28 = next(line for line in SPEC.splitlines() if line.startswith("28. `test_plan_l_a_shadow_or_ledger_failure"))
    assert "`TWO_PASS_METRICS.snapshot()`" in item_28 and "increments its counter in `/ready`" not in item_28
    item_39 = next(line for line in SPEC.splitlines() if line.startswith("39. `test_plan_l_a_held_ledger_lock"))
    assert "+ 500 ms + 1500 ms" in item_39 and "40P01" in item_39
    acceptance = (API_ROOT / "tests" / "test_phase3_acceptance.py").read_text(encoding="utf-8")
    assert "+ 500 + 1500" in acceptance.split("def test_plan_l_a_held_ledger_lock_never_delays_the_learner_beyond_the_append_budget", 1)[1]
    plan_l = acceptance.split("def test_plan_l_a_shadow_or_ledger_failure_never_changes_the_learner_response_and_is_counted", 1)[1].split("\ndef ", 1)[0]
    assert "TWO_PASS_METRICS.snapshot" in plan_l and '{"scheduled", "phase2_bound_claim_ratio_baseline"}' in plan_l


# =============================================================================================================== J8


def test_j8_spec_sections_14_and_15_mark_what_later_rounds_changed():
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert re.search(r"^  api-postgres-driver:", ci, flags=re.MULTILINE) and re.search(r"^  api-postgres:", ci, flags=re.MULTILINE)
    assert 'needs.api-postgres-driver.result' in ci
    section_14 = _section("## 14. CI changes", "## 15.")
    bullet = next(line for line in section_14.splitlines() if "runs the API suite on PostgreSQL 16" in line)
    assert bullet.startswith("- `api-postgres-driver` runs") and "needs both legs" in bullet
    item_5 = _section("5. **`infra/cloudrun/deployment.md`**", "6. **`infra/cloudrun/observability.md`:**")
    defaults = next(line for line in item_5.splitlines() if "**Defaults that ship:**" in line)
    assert "`TUTOR_LEDGER_APPEND_BUDGET_MS` and `TWO_PASS_SHADOW_BUDGET_MS` unset" in defaults and "`TUTOR_LEDGER_APPEND_BUDGET_MS` 1500" not in defaults
    before = next(line for line in item_5.splitlines() if "**Before the release:**" in line)
    assert "`alembic current`" in before and "alembic upgrade 20261119_phase3_response_ledger" in before and "Pre-deploy job (`alembic upgrade head`)" not in before
    config = (API_ROOT / "app" / "core" / "config.py").read_text(encoding="utf-8")
    assert re.search(r"tutor_ledger_append_budget_ms: int \| None = Field\(\s*default=None", config)
    assert "`alembic upgrade head` on such a database replays revisions" in RUNBOOK


# ========================================================================================================== records


def test_j_the_spec_record_and_the_evidence_package_name_the_ninth_round():
    history = SPEC.split("### 18.4 Review history", 1)[1]
    ninth = next(line for line in history.splitlines() if line.startswith("| 9, J1-J8 "))
    assert "`94aa3e6`" in ninth
    for group in ("J1", "J2", "J3", "J4", "J5", "J6", "J7", "J8"):
        assert f"{group} " in ninth and f"`test_{group.lower()}_*`" in ninth, group
    checked = 0
    for module in _phase3_test_files():
        names = re.findall(r"^def (test_j\d*_\w+)\(", (API_ROOT / "tests" / module).read_text(encoding="utf-8"), flags=re.MULTILINE)
        if not names:
            continue
        row = next(line for line in STRATEGY.splitlines() if line.startswith(f"| `{module}` |"))
        for name in names:
            group = re.match(r"(test_j\d*)_", name).group(1)
            assert f"`{group}_*`" in row, name
        checked += len(names)
    assert checked >= 20, checked  # every test of the ninth round


# =============================================================================================================== K3


# Phrases that narrate what an earlier round's text or code said. P2-12-D-03: the authoritative text states the current
# code only, and each round is one row of the spec's review history (18.4).
NARRATIVE = re.compile(
    r"\b(?:[Cc]orrected|[Ss]uperseded|[Rr]evised|[Rr]enamed|[Rr]eplaced|[Rr]emoved|[Mm]arked|[Aa]dded) in (?:Phase 3 )?(?:spec )?18\.\d"
    r"|\b[Uu]ntil (?:Phase 3 )?(?:spec )?18\.\d|\b[Ss]ince (?:Phase 3 )?(?:spec )?18\.\d|first wording|spec-time|kept as history"
    r"|\bthis (?:said|comment said|docstring said|row said|line said|bullet said|listing said)\b|^\s*History:",
    flags=re.MULTILINE,
)


def _phase3_test_files() -> list[str]:
    """Every Phase 3 test file: test_phase3_*.py and each feature module whose docstring opens with "Phase 3" (the review
    rounds' tests live in the module of the feature they prove)."""
    names = []
    for path in sorted((API_ROOT / "tests").glob("test_*.py")):
        docstring = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8"))) or ""
        if path.name.startswith("test_phase3_") or docstring.startswith("Phase 3"):
            names.append(path.name)
    return names


def _groups(path: Path) -> set[str]:
    return set(re.findall(r"^def (test_[a-z]\d*)_\w+\(", path.read_text(encoding="utf-8"), flags=re.MULTILINE))


def _round_of(group: str) -> int:
    """The review round a test group belongs to: the first round's findings are numbered, and later rounds' are lettered
    C for the second round to M for the twelfth (test_c1_* ... test_m2_*)."""
    letter = re.fullmatch(r"test_([c-z])\d*", group).group(1)
    return ord(letter) - ord("a")


def _review_groups() -> dict[str, set[str]]:
    """Each Phase 3 test file's review groups (the acceptance file holds the AC, plan and task tests)."""
    return {name: _groups(API_ROOT / "tests" / name) for name in _phase3_test_files() if name != "test_phase3_acceptance.py"}


def _last_round() -> int:
    """The latest review round: each round is one history row, and its tests are named after its findings."""
    rounds = sorted({_round_of(group) for groups in _review_groups().values() for group in groups})
    assert rounds and min(rounds) == 2 and rounds == list(range(2, max(rounds) + 1)), rounds
    return max(rounds)


def _resolves(text: str, functions: set[str], *, prefix: str | None = None) -> list[str]:
    """Backticked test names, wildcards and suffixes in text that name no test."""
    missing = []
    for match in re.finditer(r"`(test_[a-z0-9_]+)`", text):
        if match.group(1) not in functions:
            missing.append(match.group(1))
    for match in re.finditer(r"`(test_[a-z0-9_]+?)_?\*`", text):
        if not any(name.startswith(match.group(1)) for name in functions):
            missing.append(match.group(0))
    for match in re.finditer(r"`\.\.\.(_[a-z0-9_]+)`", text):
        if not (prefix and prefix + match.group(1) in functions):
            missing.append(match.group(0))
    for match in re.finditer(r"`(test_[a-z0-9_]+\.py)`", text):
        if not (API_ROOT / "tests" / match.group(1)).exists():
            missing.append(match.group(1))
    return missing


def test_k3_the_test_strategy_maps_every_phase3_test_file():
    phase_3 = STRATEGY.split("## Phase 3 acceptance map", 1)[1].split("**Exit gate.**", 1)[0]
    files_table = phase_3.split("### Phase 3 test files", 1)[1]
    rows = {match.group(1): line for line in files_table.splitlines() if (match := re.match(r"\| `(test_\w+\.py)` \| (.+) \|$", line))}
    files = _phase3_test_files()
    assert files and sorted(rows) == files, (sorted(rows), files)
    # Every review group the spec's history names has its tests in a file this map lists, so a group moved to a module
    # that is neither test_phase3_*.py nor opened with "Phase 3" fails here.
    named = set(re.findall(r"`(test_[c-m]\d+)_\*`", SPEC.split("### 18.4 Review history", 1)[1]))
    mapped = set().union(*_review_groups().values())
    assert named and named <= mapped, sorted(named - mapped)
    for name in files:
        row = rows[name]
        assert len(row) > 120, name  # it says what the file proves, not just its name
        for group in _groups(API_ROOT / "tests" / name):
            if name != "test_phase3_acceptance.py":
                assert f"`{group}_*`" in row, (name, group)
    functions = _test_functions()
    for line in phase_3.splitlines():
        if line.startswith("| AC-3-"):
            prefix = "test_ac_3_" + line[len("| AC-3-")]
            assert _resolves(line, functions, prefix=prefix) == [], line[:60]
        elif line.startswith("| "):
            assert _resolves(line, functions) == [], line[:60]


def test_k3_the_spec_records_each_round_once_in_the_review_history_table():
    record = SPEC.split("## 18. Implementation record", 1)[1]
    headings = re.findall(r"^### (18\.\d+) ", record, flags=re.MULTILINE)
    assert headings == ["18.1", "18.2", "18.3", "18.4"], headings  # no per-round narrative section
    history = record.split("### 18.4 Review history", 1)[1]
    intro = history.split("| Round", 1)[0]
    assert "may describe behaviour that a later round superseded" in intro and "sections 0-17 are authoritative" in intro
    rows = [line for line in history.splitlines() if re.match(r"\| \d+, ", line)]
    assert [int(re.match(r"\| (\d+),", row).group(1)) for row in rows] == list(range(1, _last_round() + 1))
    functions = _test_functions()
    for row in rows:
        commit = row.split(" | ")[1]
        assert re.search(r"`[0-9a-f]{7,40}`", commit), row[:40]
        findings = row.split(" | ", 2)[2].rstrip(" |").split("<br>")
        # Each finding names what fails if its defect comes back: a repository test, a frontend test or, for a finding
        # about the evidence package's own records, a check of the evidence package's 00_meta/check_records.py.
        assert findings and all("`" in finding and ("test_" in finding or ".test.ts" in finding or "check_records.py" in finding)
                                for finding in findings), row[:40]
        assert _resolves(row, functions) == [], (row[:30], _resolves(row, functions))
    # Each review group of every Phase 3 test file is in its round's row.
    for name, groups in _review_groups().items():
        for group in groups:
            if group != "test_j":
                row = rows[_round_of(group) - 1]
                assert f"`{group}_*`" in row, (name, group)


def test_k3_the_records_state_the_merge_and_the_cited_run_on_main():
    # PR #35 squash-merged as 078bc75 (tree identical to 82ded75); main run 44723513394 is the cited run, so DI-31 is
    # closed. The exit is still not passed (preconditions deviated under P1-D-18; no owner acceptance).
    di_31 = next(line for line in SPEC.splitlines() if line.startswith("| DI-31 |"))
    exit_text = _section("**Exit (plan Phase 3 P)**", "\n---")
    ci = next(line for line in _section("### 18.3 Verification results", "### 18.4").splitlines() if line.startswith("**CI:**"))
    strategy = STRATEGY.split("## Phase 3 acceptance map", 1)[1].split("**Exit gate.**", 1)[1].split("\n## ", 1)[0]
    for name, text in (("DI-31", di_31), ("section 17", exit_text), ("18.3", ci), ("strategy", strategy)):
        assert "44723513394" in text and "needs a cited green run on `main`" not in text, name
        assert "until a cited run is green on `main`" not in text, name
    for name, text in (("section 17", exit_text), ("18.3", ci), ("strategy", strategy), ("DI-31", di_31)):
        assert "`078bc75`" in text and ("44722532183" in text or name == "section 17"), name
    assert di_31.rstrip(" |").endswith("Closed (main run 44723513394)")
    assert "The exit is not passed" in exit_text and "P1-D-18" in exit_text and "no owner acceptance" in exit_text
    assert "The exit is not passed" in strategy and "no owner acceptance" in strategy
    round_12 = next(line for line in SPEC.split("### 18.4 Review history", 1)[1].splitlines() if line.startswith("| 12, M1-M2 |"))
    assert round_12.split(" | ")[1] == "`82ded75` (PR #35's head; squash-merged as `078bc75`)"


def _authoritative_texts() -> dict[str, str]:
    texts = {
        "spec 0-17": SPEC.split("## 18. Implementation record", 1)[0],
        "spec 18.1-18.3": SPEC.split("## 18. Implementation record", 1)[1].split("### 18.4 Review history", 1)[0],
        "test strategy": STRATEGY.split("## Phase 3 acceptance map", 1)[1],
        "README": (REPO_ROOT / "docs" / "evaluation" / "phase3" / "README.md").read_text(encoding="utf-8"),
        "env example": (REPO_ROOT / "infra" / "cloudrun" / "api-production.env.example.yaml").read_text(encoding="utf-8"),
        "ci": (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"),
    }
    for name in ("ADR-001-grounding-separation.md", "ADR-005-abstention-gate.md"):
        texts[name] = (REPO_ROOT / "docs" / "adr" / name).read_text(encoding="utf-8").split("## Revision 2026-11-19", 1)[1]
    for name in ("deployment.md", "observability.md"):
        texts[name] = (REPO_ROOT / "infra" / "cloudrun" / name).read_text(encoding="utf-8").split("## Phase 3", 1)[1]
    for root in ("app", "alembic"):
        for path in (API_ROOT / root).rglob("*.py"):
            texts[str(path.relative_to(REPO_ROOT))] = path.read_text(encoding="utf-8")
    for path in (REPO_ROOT / "scripts").glob("*.py"):
        texts[str(path.relative_to(REPO_ROOT))] = path.read_text(encoding="utf-8")
    return texts


def test_k3_the_authoritative_text_states_the_current_code_only():
    offending = [(name, match.group(0)) for name, text in _authoritative_texts().items() for match in NARRATIVE.finditer(text)]
    assert offending == []
    # The guard sees each kind of narrative the review rounds left behind.
    for sample in ("(Corrected in 18.10 H1: the rule cut ...)", "since 18.8 F3", "until spec 18.12 J1 it was", "Superseded in 18.5 C3",
                   "the first wording named", "this comment said \"only owners\"", "History: the spec-time block", "(Revised in 18.4"):
        assert NARRATIVE.search(sample), sample
    assert not NARRATIVE.search("the record can then no longer be tied to anyone; 18.4: \"D-19 RECOMMENDATION")


def _code_fields(source: str, name: str) -> list[str]:
    node = next(node for node in ast.parse(source).body if isinstance(node, ast.ClassDef) and node.name == name)
    return [ast.unparse(item) for item in node.body if isinstance(item, (ast.AnnAssign, ast.Assign))]


def test_k3_spec_section_3_lists_the_code_s_fields():
    section = SPEC.split("## 3. Data shapes", 1)[1].split("## 4. Algorithms", 1)[0]
    contracts = (API_ROOT / "app" / "services" / "tutor_pipeline" / "contracts.py").read_text(encoding="utf-8")
    schemas = (API_ROOT / "app" / "schemas.py").read_text(encoding="utf-8")
    code_classes = {node.name for node in ast.parse(contracts).body if isinstance(node, ast.ClassDef)}
    checked = 0
    for block in re.findall(r"```python\n(.*?)```", section, flags=re.DOTALL):
        for node in ast.parse(block).body:
            if not isinstance(node, ast.ClassDef):
                continue
            source = contracts if node.name in code_classes else schemas
            listed = [ast.unparse(item) for item in node.body if isinstance(item, (ast.AnnAssign, ast.Assign))]
            code = _code_fields(source, node.name)
            header = block.splitlines()[node.lineno - 1]
            if "additions only" in header:
                assert listed and set(listed) <= set(code), node.name
            else:
                assert listed == code, node.name
            checked += 1
    assert checked >= 30
    # Every contract the package pins a schema for is listed.
    for name in ("ResolvedQuestion", "RetrievalRequest", "EvidenceBundle", "EvidentialEnvelope", "ClaimPlan", "LockedClaimSet", "PresentationPlan",
                 "LedgerEntry", "BudgetStamp", "PresentationRecord"):
        assert f"class {name}(Contract):" in section, name


# =============================================================================================================== L1


# Each append statement: the phrase spec 4.12 names it by, and the code that issues it in append_ledger_entry.
APPEND_STATEMENTS = (
    ("SET LOCAL lock_timeout", 'text(f"SET LOCAL lock_timeout'),
    ("If a row with `response_id` exists", "ResponseLedgerRecord.response_id == entry.response_id"),
    ("insert(ResponseLedgerHead)", "module.insert(ResponseLedgerHead)"),
    ("FOR UPDATE", ".with_for_update()"),
    ("`INSERT` the record", "insert(ResponseLedgerRecord)"),
    ("UPDATE response_ledger_head", "update(ResponseLedgerHead)"),
)


def _append_steps() -> list[tuple[int, str]]:
    block = _section("**Append** (at most", "\n\nOn success")
    return [(int(number), text) for number, text in re.findall(r"^(\d)\. (.+)$", block, flags=re.MULTILINE)]


def test_l1_spec_4_12_lists_the_append_statements_in_the_code_s_order():
    source = inspect.getsource(ledger.append_ledger_entry)
    in_code_order = sorted(APPEND_STATEMENTS, key=lambda statement: source.index(statement[1]))
    # The SET LOCALs come first in the code: every later statement of the attempt, the response_id read included,
    # is bounded by the budget left (the ATTEMPT_STATEMENTS count starts after them).
    assert in_code_order[0][0] == "SET LOCAL lock_timeout" and in_code_order[1][0].startswith("If a row with")
    steps = _append_steps()
    assert [number for number, _ in steps] == list(range(1, 8))
    for (number, text), (phrase, _) in zip(steps, in_code_order):
        assert phrase in text, (number, phrase)
    read_step = next(number for number, text in steps if "If a row with `response_id` exists" in text)
    assert f"re-read as in step {read_step})" in steps[-1][1]
    comment = (API_ROOT / "app" / "services" / "ledger.py").read_text(encoding="utf-8").split("ATTEMPT_STATEMENTS = ", 1)[0].rsplit("\n\n", 1)[1]
    assert "after its PostgreSQL SET LOCALs" in comment and "the response_id read" in comment


# =============================================================================================================== L2


# The production files under apps/api this phase changes or adds (beside docs, infra and CI, which sections 14 and 15
# cover). Spec section 7 must name each one.
PRODUCTION_FILES = (
    "alembic/env.py", "alembic/versions/20261119_phase2_corpus_spans.py", "alembic/versions/20261119_phase3_response_ledger.py",
    "app/api/routes/assistant.py", "app/api/routes/ledger.py",
    "app/api/routes/qa.py", "app/api/routes/spans.py", "app/api/routes/tutor.py", "app/config_package/v2.json",
    "app/config_package/v2.json.sha256", "app/core/authorization.py", "app/core/config.py", "app/core/config_package.py",
    "app/core/corpus_governance.py", "app/core/db.py", "app/core/schema_upgrades.py", "app/db_models.py", "app/main.py", "app/schemas.py",
    "app/services/claim_gate.py", "app/services/contained_answers.py", "app/services/evidence_panel.py", "app/services/ledger.py",
    "app/services/qa_engine.py", "app/services/retention.py", "app/services/retrieval_engine.py", "app/services/teaching_assistant.py",
    "app/services/turn_idempotency.py", "app/services/tutor_followups.py", "app/services/tutor_orchestrator.py",
    "app/workers/response_ledger.py", "requirements.txt",
)


def _section_7() -> str:
    return _section("## 7. File-by-file changes", "## 8. Database")


def _names(section: str, relative: str) -> bool:
    base = relative.rsplit("/", 1)[-1]
    return relative in section or f"`{base}`" in section or f"/{base}`" in section


def test_l2_spec_section_7_names_every_production_file_the_phase_changes():
    section = _section_7()
    for relative in PRODUCTION_FILES:
        assert (API_ROOT / relative).exists(), relative
        assert _names(section, relative), relative
    # The tutor_pipeline package is listed module by module.
    for path in (API_ROOT / "app" / "services" / "tutor_pipeline").glob("*.py"):
        assert f"`{path.name}`" in section, path.name


def test_l2_section_7_states_the_database_start_up_and_requirements_changes_with_the_code_s_values():
    db_entry = _section("### 7.19 MOD `app/core/db.py`", "### 7.20")
    assert "**`classify_pg8000_errors`**" in db_entry and "handle_error" in db_entry and "every `Engine`" in db_entry
    by_class: dict[str, list[str]] = {}
    for prefix, cls in db_module._SQLSTATE_CLASSES.items():
        by_class.setdefault(cls.__name__, []).append(prefix)
    listed = db_entry.split("(`_SQLSTATE_CLASSES`: ", 1)[1].split(")", 1)[0]
    for name, prefixes in by_class.items():
        part = next(piece for piece in listed.split(";") if f"`{name}`" in piece)
        assert sorted(re.findall(r"\b\d\d\b", part)) == sorted(prefixes), name
    assert f"`CONNECT_TIMEOUT_S` ({db_module.CONNECT_TIMEOUT_S} s" in db_entry
    assert f"`CONNECT_MAX_PENDING` ({db_module.CONNECT_MAX_PENDING}:" in db_entry and "`db.connect.timeout`" in db_entry
    for name in ("KEEPALIVE_IDLE_S", "KEEPALIVE_INTERVAL_S"):
        assert f"`{name}`, {getattr(db_module, name)} s" in db_entry, name
    assert f"`KEEPALIVE_PROBES`, {db_module.KEEPALIVE_PROBES}" in db_entry
    assert f"`DEAD_PEER_BOUND_S`, {db_module.DEAD_PEER_BOUND_S} s" in db_entry and "`db.connect.keepalive_unset`" in db_entry
    schemas_entry = _section("### 7.20 MOD `app/schemas.py`", "### 7.21")
    schemas_source = (API_ROOT / "app" / "schemas.py").read_text(encoding="utf-8")
    assert "class _ExcludeIfProbe(BaseModel):" in schemas_source and "**`_ExcludeIfProbe`**" in schemas_entry
    message = re.search(r'"(pydantic >= [0-9.]+ is required)', schemas_source).group(1)
    assert message in schemas_entry and "does not start" in schemas_entry
    floor = next(line for line in (API_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines() if re.match(r"pydantic[<>=]", line))
    assert f"`{floor}`" in _section("### 7.21 MOD `apps/api/requirements.txt`", "### 7.22")
    # 18.1 lists them beside the other production departures.
    production = next(line for line in _section("### 18.1 Departures", "### 18.2").splitlines() if "Production-image changes" in line)
    for needed in ("classify_pg8000_errors", "cloud_sql_creator", "enable_tcp_keepalive", f"`{floor}`", "7.19-7.21"):
        assert needed in production, needed


# =============================================================================================================== L4


def test_l4_spec_13_2_describes_the_retry_test_test_response_ledger_holds():
    row = next(line for line in _section("### 13.2 NEW unit test files", "### 13.3").splitlines() if line.startswith("| `test_response_ledger.py` |"))
    assert "stale head (monkeypatched" not in row and "monkeypatched stale head" not in SPEC
    assert "`IntegrityError` at commit retried onto the head" in row and "`OperationalError` raised at once, never retried" in row
    source = (API_ROOT / "tests" / "test_response_ledger.py").read_text(encoding="utf-8")
    test = source.split("def test_an_integrity_error_retries_onto_the_head_and_other_errors_fail_at_once", 1)[1].split("\ndef ", 1)[0]
    assert "_Flaky(factory, 1, IntegrityError(" in test and "OperationalError(" in test and "attempts == 1" in test
    assert "chain_head" not in test and "monkeypatch" not in test  # the head is never faked


# =============================================================================================================== L5


def test_l5_the_adr_005_revision_withdraws_the_overlap_gate_and_keeps_fail_closed_abstention():
    decision = ADR_005.split("## Decision", 1)[1].split("## Consequences", 1)[0]
    assert "overlap" in decision  # the original decision is the overlap gate
    revision = ADR_005.split("## Revision 2026-11-19", 1)[1]
    opening = next(line for line in revision.splitlines() if line.startswith("The "))
    assert "stands as first written" not in revision
    assert "overlap `ClaimGate` of the decision above is withdrawn" in opening and "fail-closed rule stands" in opening
    assert "**The overlap `ClaimGate` is removed**" in revision
    assert not hasattr(claim_gate, "ClaimGate") and not hasattr(claim_gate, "evidence_digest")


# =============================================================================================================== L6


def test_l6_spec_5_1_names_the_owner_decisions_v2_keeps_and_adds_and_lists_every_tutor_pipeline_block():
    section = _section("### 5.1 File", "### 5.2")
    bullet = next(line for line in section.splitlines() if "`owner_decisions` keeps" in line)
    kept = re.findall(r"`([A-Z][A-Z0-9.-]+)`", bullet.split("`owner_decisions` keeps", 1)[1].split("unchanged", 1)[0])
    added = re.findall(r"`([A-Z][A-Z0-9.-]+)`", bullet.split(" adds ", 1)[1])
    assert set(kept) == set(V1_RAW["owner_decisions"])
    assert set(added) == set(V2_RAW["owner_decisions"]) - set(V1_RAW["owner_decisions"]) == {"D-19", "D-12", "PLAN-3.3", "PLAN-12.8"}
    assert all(V2_RAW["owner_decisions"][name] == V1_RAW["owner_decisions"][name] for name in kept)
    listing = section.split("```json", 1)[1].split("```", 1)[0]
    owner = listing.split('"owner_decisions": {', 1)[1]
    assert set(re.findall(r'"([A-Z][A-Z0-9.-]+)": ', owner)) == set(V2_RAW["owner_decisions"])
    tutor = listing.split('"tutor_pipeline": {', 1)[1].split('\n},', 1)[0]
    for key in V2_RAW["tutor_pipeline"]:
        assert f'"{key}":' in tutor, key
    legacy = tutor.split('"legacy": {', 1)[1].split("}", 1)[0]
    assert set(re.findall(r'"([a-z_]+)":', legacy)) == set(V2_RAW["tutor_pipeline"]["legacy"])


# =============================================================================================================== L8


def test_l8_spec_13_1_attributes_each_learner_dependent_mutation_to_its_test():
    item = next(line for line in _section("### 13.1 NEW", "### 13.2").splitlines() if line.startswith("3. `test_ac_3_1_what_the_evidential_pass"))
    j2 = item.split("`test_j2_*` makes ", 1)[1].split(", and `test_k1_*`", 1)[0]
    k1 = item.split(", and `test_k1_*` ", 1)[1].split(", each in turn", 1)[0]
    assert j2 == "the ClaimPlan and the threshold version learner-dependent"
    invariants = (API_ROOT / "tests" / "test_tutor_pipeline_invariants.py").read_text(encoding="utf-8")
    node = next(node for node in ast.parse(invariants).body if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "LEARNER_DEPENDENT")
    fields = {key.value for key in node.value.keys}
    assert fields == {"abstention_reason", "counts", "floor", "margin", "sufficiency_score", "top_k"}
    named = {"abstention_reason": "the abstention reason", "counts": "the counts", "floor": "the floor", "margin": "the margin",
             "sufficiency_score": "the sufficiency score", "top_k": "`top_k`"}
    assert all(named[field] in k1 for field in fields) and "ClaimPlan" not in k1 and "threshold" not in k1
    assert re.search(r"^def test_j2_a_learner_dependent_claim_plan_\w+\(", invariants, flags=re.MULTILINE)
    assert re.search(r"^def test_j2_a_learner_dependent_threshold_\w+\(", invariants, flags=re.MULTILINE)


# =============================================================================================================== M1


def test_m1_the_records_state_production_s_pg8000_interface_and_ci_s():
    # What the records state, read from the installed code: the connector's pg8000 adapter calls pg8000.dbapi.connect,
    # the connector uses that adapter for "pg8000", and app.core.db asks the connector for pg8000 on production's
    # engine; a postgresql+pg8000:// URL loads the pg8000 module, whose connect is the legacy interface.
    assert "pg8000.dbapi.connect(" in inspect.getsource(connector_pg8000.connect)
    assert '"pg8000": pg8000.connect' in inspect.getsource(connector_module)
    db_source = inspect.getsource(db_module)
    assert 'connector.connect(connection_name, "pg8000"' in db_source
    assert 'create_engine(URL.create("postgresql+pg8000"), creator=get_cloud_sql_connection' in db_source
    assert PGDialect_pg8000.import_dbapi() is pg8000 and "Connection(" in inspect.getsource(pg8000.connect)

    entry = _section("### 7.19 MOD `app/core/db.py`", "### 7.20")
    bullet = next(line for line in entry.splitlines() if line.startswith("- **pg8000's two interfaces raise different classes**"))
    for needed in ("`pg8000.dbapi.connect`", "plain `DatabaseError`, 23505 included", "legacy `pg8000.connect`",
                   "CI's pg8000 leg", "does not reproduce production's classes", "`test_m1_*`"):
        assert needed in bullet, needed
    comment = db_source.split("_SQLSTATE_CLASSES: dict", 1)[0].rsplit("\n\n", 1)[1]
    for needed in ("pg8000.dbapi.connect", "plain DatabaseError, 23505 included", "legacy pg8000.connect", "CI's pg8000 leg"):
        assert needed in comment, needed
    ci_comment = CI.split("  api-postgres-driver:", 1)[0].rsplit("\n\n", 1)[1]
    spec_14 = next(line for line in _section("## 14.", "## 15.").splitlines() if line.startswith("- `api-postgres-driver` runs"))
    spec_16 = next(line for line in _section("## 16.", "## 17.").splitlines() if line.startswith("| DI-46 |"))
    strategy = next(line for line in STRATEGY.splitlines() if "once with psycopg and once with pg8000" in line)
    # The register's DI-46 row and the evidence package's texts are checked by its 00_meta/check_records.py (check_m1_*).
    records = {"ci": ci_comment, "spec 14": spec_14, "spec 16": spec_16, "test strategy": strategy}
    for name, record in records.items():
        assert "pg8000.dbapi.connect" in record and "legacy pg8000.connect" in record.replace("`", "") and "test_m1_*" in record, name
    # No record says pg8000 raises IntegrityError only for 23505, or that pg8000 itself raises ProgrammingError for
    # every other server error, without naming the interface.
    texts = {"spec": SPEC, "test strategy": STRATEGY, "ci": CI, "app/core/db.py": db_source}
    for name, body in texts.items():
        assert not re.search(r"IntegrityError`? only for 23505", body), name
        assert "pg8000 (the production driver) raises" not in body, name


# =============================================================================================================== M2


def _row(fact: str) -> list[str]:
    line = next(line for line in AUTHORITATIVE_SPEC.splitlines() if line.startswith(f"| {fact} |"))
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _added_names(line: str) -> list[str]:
    tail = line.split(" adds ", 1)[1]
    sentence = re.split(r"\.(?:\s|$)|\(| \|", tail, maxsplit=1)[0]
    return re.findall(r"`([A-Z][A-Z0-9.-]+)`", sentence)


def test_m2_spec_0_2_m24_lists_v1_s_keys_and_names_every_owner_decision_v2_adds():
    _, fact, consequence = _row("M24")
    assert re.search(r"top-level keys: `([^`]+)`", fact).group(1).split(", ") == list(V1_RAW)
    assert re.search(r"`owner_decisions` holds `([^`]+)`", fact).group(1).split(", ") == list(V1_RAW["owner_decisions"])
    # "v2 keeps every v1 block"; "keeps those four unchanged and adds" the rest.
    assert consequence.startswith("v2 keeps every v1 block") and set(V1_RAW) <= set(V2_RAW)
    assert "keeps those four unchanged" in consequence and len(V1_RAW["owner_decisions"]) == 4
    assert all(V2_RAW["owner_decisions"][name] == value for name, value in V1_RAW["owner_decisions"].items())
    added = set(V2_RAW["owner_decisions"]) - set(V1_RAW["owner_decisions"])
    assert set(_added_names(consequence)) == added == {"D-19", "D-12", "PLAN-3.3", "PLAN-12.8"}
    # 5.1's blocks copied unchanged are unchanged, and the blocks it changes differ.
    bullet = next(line for line in _section("### 5.1 File", "### 5.2").splitlines() if line.startswith("- Blocks copied unchanged:"))
    unchanged = re.findall(r"`([a-z_]+)`", bullet.split(". ", 1)[0])
    assert unchanged and all(V2_RAW[name] == V1_RAW[name] for name in unchanged)
    assert {name for name in V1_RAW if V1_RAW[name] != V2_RAW[name]} == {"package_version", "schema_version", "phase", "abstention", "owner_decisions"}


def test_m2_every_line_that_says_what_v2_adds_to_owner_decisions_names_all_four():
    added = set(V2_RAW["owner_decisions"]) - set(V1_RAW["owner_decisions"])
    # The phase record's lines are checked by the evidence package's 00_meta/check_records.py (check_m2_*).
    texts = {"spec 0-17": AUTHORITATIVE_SPEC, "test strategy": STRATEGY}
    checked = 0
    for name, body in texts.items():
        for line in body.splitlines():
            if "owner_decisions" in line and " adds " in line:
                assert set(_added_names(line)) == added, (name, line[:80])
                checked += 1
    assert checked >= 2  # M24 and 5.1
    assert "adds D-19 and D-12" not in AUTHORITATIVE_SPEC
