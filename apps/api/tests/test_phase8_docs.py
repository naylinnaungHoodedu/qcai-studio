"""Phase 8 authoring, ownership, and test traceability guards."""

import ast
import hashlib
import json
from pathlib import Path
import re

import pytest

from app import db_models
from app.core.authorization import ROUTE_POLICIES
from app.core.config import Settings
from app.core.config_package import LATEST_SCHEMA_VERSION
from app.core.phase8_settings import PHASE8_FLAGS
from app.services.erasure import RETENTION_EXEMPT_TABLES, guest_retention_age_columns, user_keyed_tables
from app.services.learner_record_planner import ADVANCED_THRESHOLD, FOUNDATION_THRESHOLD
from app.services.learner_record_privacy import CONSENT_CLASSES, CONSENT_VERSION
from app.services.learner_record_shadow import COMPLETION_THRESHOLD, PLANNER_BUDGET_MS
from app.services.learner_record_sync import ASSESSMENT_LIMIT, ASSESSMENT_WINDOW, MAX_ISSUED_REPLICAS
from app.services.ledger import SCHEMA_REVISION
from app.services.retention import retention_classes
from scripts.run_invariance_harness import LEVELS
from scripts.run_v1_fixtures import text_sha256
from test_phase3_docs import NARRATIVE


TESTS = Path(__file__).resolve().parent
APP = TESTS.parent / "app"
ROOT = TESTS.parents[2]
SPEC = ROOT / "docs" / "architecture" / "phase8-implementation-spec.md"
STRATEGY = ROOT / "docs" / "testing" / "test-strategy.md"
PHASE8_MODELS = (
    "LearnerIssuedReplica", "LearnerWriteGuard", "LearnerSubject", "LearnerGuestRevocation", "LearnerClaimAudit",
    "LearnerConsent", "LearnerConsentChange", "LearnerErasureAudit", "LearnerAdaptationStop", "LearnerAssessmentFact",
)
BASELINE = TESTS / "data" / "phase8_shared_baseline_v1.json"
CI_WORKFLOW = ROOT / ".github/workflows/ci.yml"
INPUT_RECORDS = (
    "docs/evaluation/phase3/three_plan_replay_v1.json",
    "docs/evaluation/phase4/v1_fixture_report_v1.json",
    "docs/evaluation/phase5/v2_fixture_report_v1.json",
    "docs/evaluation/phase6/v3_residual_report_v1.json",
    "docs/evaluation/phase7/golden_run_v1.json",
    "docs/evaluation/phase8/invariance_harness_report_v1.json",
    "docs/evaluation/phase9/ranking_replay_v1.json",
)
ERASURE_PROOF = "docs/evaluation/phase8/erasure_proof_v1.json"
HAND_BACK_FIELDS = (
    "Rules that no longer fit", "Dated revision sections appended", "Proposed package pins", "Stopped items",
)
PLAN_QUOTE_LINES = {
    "L1573": "2) Server-issued replica clocks, monotonic counters, compare-and-set on record_version [Decision D-26].",
    "L1574": "3) Mastery from server-scored assessments [Risk R-42]; planner (Loop 2) [Evidence E-74].",
    "L1577": "5) Consent record, scheduled retention, export, erasure across all providers with receipt [Risk R-08].",
    "L1606": "Flags for planner and sync. Stop: any harness violation blocks adaptation (never evidence).",
    "L1924": "| H13  | Consent [Decision D-27]       | P8 start                       | Consent classes        |",
    "L3017": "- D-27 OPEN DECISION: consent classes before Phase 8 [Risk R-09]. PO, PI.",
    "L2987": "D-08 |IRB and OSF timing (PI)             |(a) before research use; (b) fixtures     |No Phase 10 [Assumption A-10]",
    "L2988": "     |                                    |first                                     |",
}
RETIRED_PHASE8_TEST_NAMES = {
    "test_plan_j_a_forged_or_revoked_guest_token_cannot_claim",
    "test_phase8_assessment_quota_and_server_clock_are_subject_scoped",
    "test_a_non_finite_preference_is_refused_on_postgres_and_never_a_500",
    "test_phase8_legacy_delete_account_erases_the_bound_subject",
    "test_phase8_shared_demo_fallback_cannot_erase",
    "test_phase8_an_explicit_demo_principal_can_resume_after_erasure",
}
API_EXPORTS_AT_PHASE5 = """
    getApiBaseUrl getClientApiBaseUrl fetchCourseOverview fetchCourseProgress fetchModule
    fetchLesson fetchLessonNotes createLessonNote askQuestion chatWithTeachingAssistant
    fetchTutorThreads fetchTutorThread createTutorThread fetchLearnerRecord postLearnerRecordOperations
    fetchQAHistory searchContent fetchMe registerAccount loginAccount
    logoutAccount deleteAccount postAnalyticsEvent postPublicWebVital fetchPublicWebVitalsSummary
    fetchServiceHealth submitSupportRequest recordQuizAttempt fetchArenaLeaderboard fetchOwnArenaProfile
    requestArenaTicket fetchArenaStatus fetchBuilderScenarios fetchBuilderProfile fetchBuilderFeed
    submitBuilderScenario shareBuilderScenario fetchLearningDashboard fetchAdaptivePath fetchSkillGapReport
    updateLearnerProfile createLearningCheckIn requestRealtimeFeedback fetchProjectCatalog fetchMyProjectSubmissions
    fetchProjectReviewQueue createProjectSubmission submitPeerReview retractProjectSubmission
""".split()


def _section(number):
    return SPEC.read_text(encoding="utf-8").split(f"\n## {number}. ", 1)[1].split("\n## ", 1)[0]


def _row(identifier):
    return next(line for line in _section(16).splitlines() if line.startswith(f"| {identifier} |"))


def _api_ci_runs():
    import yaml

    workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    steps = yaml.safe_load(workflow)["jobs"]["api-and-evaluation"]["steps"]
    runs = [step["run"] for step in steps if "run" in step]
    marked = re.findall(r"(?m)^      # Phase 8\b[^\n]*\n(?:      #[^\n]*\n)*      - run: ([^\n]+)$", workflow)
    return runs, marked


def _names():
    return {
        node.name for path in TESTS.glob("test_*.py")
        for node in ast.parse(path.read_text(encoding="utf-8")).body if isinstance(node, ast.FunctionDef)
    }


def _test_source_symbols(path, source):
    """Fingerprint Python declarations and TypeScript integration check bodies."""
    if path.endswith(".ts"):
        # The integration files use node:test with one call per check. Pin its body as well as its name.
        tests = list(re.finditer(r"^[ \t]*(?:it|test)(?:\.(?:skip|only|todo))?\(\s*(['\"])(.*?)\1\s*,", source, re.M))
        declarations = {"module setup": source[:tests[0].start()] if tests else source}
        boundaries = [test.start() for test in tests] + [len(source)]
        for match, end in zip(tests, boundaries[1:]):
            assert match[2] not in declarations, (path, match[2])
            declarations[match[2]] = source[match.start():end]
        return {name: hashlib.sha256(body.rstrip().encode()).hexdigest() for name, body in declarations.items()}
    declarations = {}
    for node in ast.parse(source).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names = (node.name,)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
            names = tuple(child.id for target in targets for child in ast.walk(target)
                          if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store))
        else:
            continue
        for name in names:
            declarations.setdefault(name, []).append(ast.dump(node))
    return {name: hashlib.sha256("\n".join(nodes).encode()).hexdigest() for name, nodes in declarations.items()}


def _main_test_symbols(baseline):
    pinned = {**baseline["test_symbols"], **baseline["main_test_symbols"]}
    return {module: symbols for module, symbols in pinned.items() if module not in baseline["removed_on_main"]}


def _current_test_modules():
    paths = [*TESTS.rglob("*.py"), *(ROOT / "evaluation/tests").rglob("*.py"),
             *(ROOT / "apps/frontend/tests").rglob("*.test.ts")]
    return {path.name if path.parent == TESTS else path.relative_to(ROOT).as_posix() for path in paths}


def _phase8_test_module(module):
    name = Path(module).name
    return (name.startswith("test_phase8_") and name.endswith(".py")) or (
        name.startswith("phase8-") and name.endswith(".test.ts")
    )


def _test_changes(baseline):
    changed, removed = set(), set()
    for module, previous in baseline.items():
        path = (ROOT if "/" in module else TESTS) / module
        current = _test_source_symbols(module, path.read_text(encoding="utf-8"))
        changed.update((module, name) for name, digest in current.items() if previous.get(name) != digest)
        removed.update((module, name) for name in previous.keys() - current.keys())
    return changed, removed


def _without_renamed_test_references(text):
    return re.sub(r"(?i)renamed and replaced `[^`]+`", "", text)


def test_phase8_route_policies_form_one_block_after_the_learner_record_rows():
    keys = list(ROUTE_POLICIES)
    index = keys.index(("POST", "/learner-record/operations")) + 1
    phase8 = [key for key in keys if "Phase 8" in ROUTE_POLICIES[key].note]
    assert set(phase8) == {
        ("POST", "/learner-record/replicas"), ("POST", "/auth/guest-claim"), ("GET", "/auth/learner-consent"),
        ("PUT", "/auth/learner-consent"), ("GET", "/auth/learner-export"), ("POST", "/auth/learner-erasure"),
    }
    assert keys[index:index + len(phase8)] == phase8
    lib = ROOT / "apps" / "frontend" / "src" / "lib"
    assert re.findall(r"^export (?:async )?(?:function|const|type|class) (\w+)",
                      (lib / "api.ts").read_text(encoding="utf-8"), re.M) == API_EXPORTS_AT_PHASE5
    assert "export async function issueLearnerRecordReplica" in (lib / "learner-record-api.ts").read_text(encoding="utf-8")


def test_phase8_keeps_protected_acceptance_tests_at_the_phase7_baseline():
    # The Phase 9 merge updates the main baseline. Exclude only the permitted Phase 3 migration function.
    phase3 = (TESTS / "test_phase3_acceptance.py").read_text(encoding="utf-8")
    phase3 = re.sub(r"(?ms)^def test_plan_g_the_alembic_revision_is_reversible_and_refuses_to_drop_a_non_empty_ledger\(.*?(?=^def )", "", phase3)
    phase5 = (TESTS / "test_phase5_acceptance.py").read_text(encoding="utf-8")
    assert hashlib.sha256(phase3.encode()).hexdigest() == "e6f34990290d48b604b18314bcbcbd5f258a1b447870760229aaff98a22b162f"
    assert hashlib.sha256(phase5.encode()).hexdigest() == "6f14c88031b46453deada05ee69bd08fcbe9c7412f7d59d058c29b43b03aa3eb"


def test_phase8_docs_pd_204_states_the_engineering_constants_in_code():
    row = _row("PD-204")
    for value in (
        ASSESSMENT_LIMIT, MAX_ISSUED_REPLICAS, int(ASSESSMENT_WINDOW.total_seconds() / 60),
        int(ASSESSMENT_WINDOW.total_seconds()), FOUNDATION_THRESHOLD, ADVANCED_THRESHOLD,
        COMPLETION_THRESHOLD, PLANNER_BUDGET_MS, *LEVELS,
    ):
        assert str(value) in row
    assert all(value in row for value in ("409", "429", "once", "no server retry", "NDJSON", "zero counts", "retire"))
    assert f"{int(ASSESSMENT_WINDOW.total_seconds() / 60)} minutes" in row
    for index in range(200, 206):
        decision = _row(f"PD-{index}")
        assert re.search(r'L\d+: "', decision) and "future" not in decision
    quota = next(line for line in _section(4).splitlines() if "quota counts" in line)
    assert "authenticated principal's attempts" in quota and "subject's attempts" not in _section(4)


def test_phase8_docs_pd_quotes_match_the_plan_lines_verbatim():
    seen = {}
    for index in range(200, 206):
        for label, quote in re.findall(r'(L\d+): "([^"]+)"', _row(f"PD-{index}")):
            assert quote.replace(r"\|", "|") == PLAN_QUOTE_LINES[label], (index, label)
            seen[label] = quote
    assert set(seen) == set(PLAN_QUOTE_LINES)


def test_phase8_docs_section_1_records_the_h13_deviation():
    section = _section(1)
    assert all(value in section for value in ("H13", "L1566", "L1907", "P1-D-18", "P2-12-D-04", "DI-300", "DI-301"))
    assert all(value in section for value in ("tombstone", "synthetic mastery", "Notes, threads", "Stage-9", "R-03", "L938", "P2-12-D-05"))


def test_phase8_docs_di_300_names_its_open_items_and_blockers():
    row = _row("DI-300")
    assert all(value in row for value in (
        "DI-01", "DI-02", "DI-58", "DI-301", "DI-302", "DI-303", "DI-305",
        "network access", "production deploy", "No owner acceptance is recorded",
    ))
    assert "P2-12-D-05" in _row("DI-316") and "| Closed |" in _row("DI-316")


def test_phase8_docs_stopped_rows_record_an_open_owner_question():
    for line in _section(16).splitlines():
        if line.startswith("| DI-") and line.rstrip().endswith("| Stopped |"):
            assert "Owner question (open)" in line and "?" in line
    handback = _row("DI-318")
    assert all(term in handback for term in ("owner answered", "main track", "| Handed over |", "rule 12"))


def test_phase8_docs_spec_headings_shapes_and_plan_quotes():
    spec = SPEC.read_text(encoding="utf-8")
    assert [int(name) for name in re.findall(r"^## (\d+)\.", spec, re.M)] == list(range(19))
    assert _section(18).count("| Round |") == 1 and not re.search(r"^#+ ", _section(18), re.M)
    assert _section(18).count("| Review 1 |") == 1
    assert _section(18).count("| Review 2 |") == 1
    assert _section(18).count("| Review 3 |") == 1
    assert _section(18).count("| Review 4 |") == 1
    assert _section(18).count("| Review 5 |") == 1
    for model in PHASE8_MODELS:
        line = next(line for line in _section(3).splitlines() if line.startswith(f"| `{model}` |"))
        listed = set(re.findall(r"`([a-z][a-z_]+)`", line.split("|")[2]))
        assert listed == set(getattr(db_models, model).__table__.c.keys()), model
    assert "Flags for planner and sync. Stop: any harness violation blocks adaptation (never evidence)." in _section(6)
    assert "residual: backups keep erased rows for a window." in _section(16)
    assert "AC-8-1 to AC-8-7 green; harness in CI." in _section(17)
    for number in range(300, 320):
        assert _row(f"DI-{number}")
    retention = (ROOT / "infra" / "cloudrun" / "retention-job.md").read_text(encoding="utf-8").split("\n## Phase 8\n")[1]
    assert all(name in retention for name in (
        "learner_claim_audits", "learner_erasure_audits", "learner_write_guards", "last_used_at", "updated_at", "tombstone",
    ))
    deployment = (ROOT / "infra/cloudrun/deployment.md").read_text(encoding="utf-8")
    rollout = deployment.split("\n## Phase 8: ", 1)[1]
    assert "**Before the release.**" in rollout and "**After the deploy.**" in rollout
    assert "Settings refuse non-off values before the verified Phase 8 exit" in rollout
    assert "`phase8_exit_passed: false`" in rollout and "`learner_slis: {}`" in rollout
    for command in (
        "python scripts/config_package.py --check --path apps/api/app/config_package/v8.json",
        "python scripts/run_invariance_harness.py --check docs/evaluation/phase8/invariance_harness_report_v1.json",
        "python scripts/prove_erasure.py --check docs/evaluation/phase8/erasure_proof_v1.json",
    ):
        assert command in rollout and command in _section(17)
    stamps = deployment.split("3. **Check the stamp:** `alembic current`.", 1)[1].split("\n4. ", 1)[0]
    revision_lines = re.findall(r"(?m)^   - `(20\d{6}_phase\w+)( \(head\))?`:", stamps)
    create_all = next(line for line in stamps.splitlines() if "the tables came from `create_all`" in line)
    older_revisions = {revision for revision, head in revision_lines if not head}
    assert {revision for revision, head in revision_lines if head} == {SCHEMA_REVISION}
    assert set(re.findall(r"`alembic stamp (20\d{6}_phase\w+)`", create_all)) == older_revisions | {"20261119_phase2_corpus_spans"}
    assert "`alembic stamp head`" in create_all and "Phase 8 image" in create_all and "Phase 8 tables" in create_all
    release_checks = rollout.split("**Before the release.**", 1)[1].split("**After the deploy.**", 1)[0]
    _, phase8_steps = _api_ci_runs()
    predecessor_checks = [command for command in phase8_steps if "config_package.py --check --path" in command]
    assert predecessor_checks and all(f"`{command}`" in release_checks for command in predecessor_checks)
    proof_readme = (ROOT / "docs/evaluation/phase8/README.md").read_text(encoding="utf-8").split("`prove_erasure.py`", 1)[1]
    for document in (proof_readme, _section(12)):
        for code, reason in ((1, "drift"), (3, "failed proof"), (4, "dirty-tree write")):
            assert re.search(rf"\b{code}\b[^,.]*\b{reason}\b", document)
    for flag in PHASE8_FLAGS:
        assert flag.upper() in retention and flag.upper() in _section(6)
        assert flag.upper() in rollout


def test_phase8_docs_the_test_strategy_maps_every_test_module_the_phase_added():
    phase = STRATEGY.read_text(encoding="utf-8").split("\n## Phase 8 acceptance map", 1)[1].split("\n## ", 1)[0]
    added, changed = phase.split("### Phase 8 changes to existing test modules", 1)
    def rows(text):
        return dict(re.findall(r"^\| `([^\x60]+)\x60 \| (.+) \|$", text, re.M))
    declared = rows(added)
    authored = {module for module in _current_test_modules() if _phase8_test_module(module)}
    coverage = _section(13).split("### 13.2 Module coverage", 1)[1].split("### 13.3", 1)[0]
    assert set(declared) == set(rows(coverage)) == authored
    assert all(len(description) > 100 for description in declared.values())
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    changed_symbols, _ = _test_changes(_main_test_symbols(baseline))
    assert set(rows(changed)) == {module for module, _ in changed_symbols}
    assert "**Exit gate.**" in changed and "phase8_exit_passed" in changed
    names = _names()
    for text in (phase, _section(13), _section(18)):
        assert set(re.findall(r"`(test_\w+)`", _without_renamed_test_references(text))) <= names
    ac_lines = [line for line in phase.splitlines() if line.startswith("| AC-8-")]
    assert len(ac_lines) == 7 and all(re.search(r"`test_\w+`", line) for line in ac_lines)
    def mapped(text):
        return {match[1]: set(re.findall(r"`(test_\w+)`", match[2]))
                for match in re.finditer(r"^\| (AC-8-[1-7]) \| (.+) \|$", text, re.M)}
    coverage = mapped(_section(13).split("### 13.2 ", 1)[0])
    assert coverage == mapped(phase)
    assert "test_learner_record_merges_divergent_replicas_without_losing_completion" in coverage["AC-8-1"]
    current = _without_renamed_test_references(SPEC.read_text(encoding="utf-8"))
    assert not any(name in current for name in RETIRED_PHASE8_TEST_NAMES)


def test_phase8_docs_section_14_names_the_ci_steps_phase8_adds():
    runs, marked = _api_ci_runs()
    section = _section(14)
    assert re.findall(r"(?m)^- `([^`]+)`", section) == marked
    v7, invariance = marked
    assert v7.endswith("--check --path apps/api/app/config_package/v7.json")
    assert v7.replace("/v7.json", "/v6.json") == runs[runs.index(v7) - 1]
    assert "run_invariance_harness.py --check" in invariance
    assert "capture_public_payloads.py --check" in runs[runs.index(invariance) - 1]
    assert "DI-317" in section
    golden = json.loads((ROOT / "docs/evaluation/phase7/golden_run_v1.json").read_text(encoding="utf-8"))
    assert f"`{golden['pins']['config_package']['version']}` record" in section
    assert not re.search(r"checks v6 readability|v7 golden-set record", section, re.I)
    assert "--base-ref FETCH_HEAD" in section
    assert any("run_golden_set.py --check" in run and "--base-ref FETCH_HEAD" in run for run in runs)
    proof_test = "test_plan_f_the_committed_erasure_proof_matches_a_fresh_run"
    assert proof_test in _names() and f"`{proof_test}`" in section
    assert any("-m pytest" in run and "apps/api/tests" in run for run in runs)


def test_phase8_docs_the_bump_docstrings_name_v8_as_shipped():
    shipped = f"v{LATEST_SCHEMA_VERSION} since Phase 8"
    budget_versions = f"{shipped}, v7 since Phase 9, v6 since Phase 7, v5 since Phase 6 and v4 since Phase 5"
    for file in ("tutor_followups.py", "tutor_pipeline/package_check.py", "tutor_pipeline/__init__.py"):
        source = (APP / "services" / file).read_text(encoding="utf-8")
        doc = ast.get_docstring(ast.parse(source))
        assert shipped in doc and "v7 since Phase 9" in doc, file
        assert "v7 since Phase 9, the shipped package" not in doc, file
    phase5 = (ROOT / "docs/architecture/phase5-implementation-spec.md").read_text(encoding="utf-8")
    row = next(line for line in phase5.splitlines() if line.startswith("| `services/tutor_followups.py` |"))
    assert budget_versions in row and "v7 since Phase 8" not in row
    followups = (APP / "services/tutor_followups.py").read_text(encoding="utf-8")
    assert budget_versions in ast.get_docstring(ast.parse(followups))


def test_phase8_docs_the_strategy_has_one_exit_gate_per_phase_section():
    sections = re.split(r"^## Phase (\d+) acceptance map[^\n]*\n", STRATEGY.read_text(encoding="utf-8"), flags=re.M)
    for number, body in zip(sections[1::2], sections[2::2]):
        exits = [line for line in body.splitlines() if line.startswith("**Exit gate.**")]
        assert len(exits) == 1, number
        assert f"Phase {number}" in exits[0] or f"phase{number}_exit_passed" in exits[0], number


def test_phase8_docs_the_authoritative_text_describes_current_behavior():
    spec = SPEC.read_text(encoding="utf-8").split("\n## 18. ", 1)[0]
    paths = [
        *APP.rglob("*.py"), *(APP.parent / "alembic").rglob("*.py"), *(ROOT / "scripts").glob("*.py"),
        ROOT / ".github" / "workflows" / "ci.yml",
        ROOT / "docs" / "adr" / "ADR-001-grounding-separation.md",
        ROOT / "docs" / "adr" / "ADR-003-learner-record-synchronization.md",
        ROOT / "docs" / "evaluation" / "phase8" / "README.md",
        ROOT / "docs" / "security" / "consent-schema.md",
        ROOT / "docs" / "security" / "identity-linking.md",
    ]
    phase3 = (ROOT / "docs" / "architecture" / "phase3-implementation-spec.md").read_text(encoding="utf-8")
    texts = {
        "Phase 8 spec": spec,
        "Phase 3 spec": phase3.split("### 18.4 Review history", 1)[0],
        "test strategy": STRATEGY.read_text(encoding="utf-8").split("## Phase 3 acceptance map", 1)[1],
    }
    for name in ("deployment.md", "observability.md", "retention-job.md"):
        value = (ROOT / "infra" / "cloudrun" / name).read_text(encoding="utf-8")
        heading = "## Phase 8" if name == "retention-job.md" else "## Phase 3"
        texts[name] = value.split(heading, 1)[1]
        assert "## Phase 8" in value
    for name in ("ADR-001-grounding-separation.md", "ADR-005-abstention-gate.md"):
        texts[name] = (ROOT / "docs" / "adr" / name).read_text(encoding="utf-8").split("## Revision 2026-11-19", 1)[1]
    paths.append(ROOT / "docs" / "evaluation" / "phase3" / "README.md")
    texts.update({str(path.relative_to(ROOT)): path.read_text(encoding="utf-8") for path in paths})
    for name, value in texts.items():
        assert not NARRATIVE.search(value), name
    assert not any(term in spec.lower() for term in ("when it lands", "as each feature lands", "before wiring"))


def test_phase8_docs_spec_section_10_names_every_learner_event_in_code():
    paths = [*APP.glob("api/routes/*.py"), *APP.glob("services/learner_record*.py"),
             APP / "services" / "tutor_orchestrator.py", ROOT / "scripts" / "run_invariance_harness.py"]
    events = set()
    for path in paths:
        events.update(re.findall(r'"((?:learner|subject)\.[a-z_.]+|analytics\.consent_withheld)"',
                                path.read_text(encoding="utf-8")))
    assert events and all(f"`{name}`" in _section(10) for name in events), events
    observability = (ROOT / "infra/cloudrun/observability.md").read_text(encoding="utf-8").split("\n## Phase 8 ", 1)[1]
    assert {len(re.findall(r"(?<!\\)\|", line)) for line in observability.splitlines() if line.startswith("|")} == {3}
    erasure_time = next(line for line in observability.splitlines() if line.startswith("| Erasure time |"))
    assert all(value in erasure_time for value in ('"account.delete"', '"learner.erasure"', "details.duration_ms"))
    identity = (ROOT / "docs/security/identity-linking.md").read_text(encoding="utf-8")
    for key in ("auth_login_rate_limit", "guest_legacy_upgrade_rate_limit"):
        default = Settings.model_fields[key].default
        assert f"`{key}` (default {default})" in _section(9)
        assert f"`{key}` ({default} by default)" in identity
    assert "429" in _section(9) and "429" in identity


def test_phase8_docs_the_consent_schema_lists_the_retention_classes_in_code():
    doc = (ROOT / "docs" / "security" / "consent-schema.md").read_text(encoding="utf-8")
    names = {table.name for table in user_keyed_tables()}
    assert dict(re.findall(r"^\| `(\w+)` \| `([^\x60]+)\x60 \|$", doc, re.M)) == retention_classes()
    assert names == retention_classes().keys() and retention_classes()["user_accounts"] == "until-erasure"
    assert all(cls in doc for cls in (*CONSENT_CLASSES, CONSENT_VERSION, "LEARNER_PRIVACY=on"))


def _unexplained_retention_skips(privacy_on):
    timestamped = {table.name for table in user_keyed_tables() if {"created_at", "updated_at"} & set(table.c.keys())}
    classified = set(guest_retention_age_columns(privacy_on))
    reasons = {name for name, reason in RETENTION_EXEMPT_TABLES.items() if reason.strip()}
    # The frozen path has no updated-at rule. This table's update age activates with privacy.
    separate = set() if privacy_on else {"learner_consents"}
    return timestamped - classified - reasons - separate


def test_retention_exempt_tables_each_have_a_reason(monkeypatch):
    from app.services import retention

    assert {"learner_subjects", "user_accounts", "user_sessions"} <= RETENTION_EXEMPT_TABLES.keys()
    assert all(reason.strip() for reason in RETENTION_EXEMPT_TABLES.values())
    assert all(not _unexplained_retention_skips(enabled) for enabled in (False, True))
    monkeypatch.setitem(retention._RETENTION_CLASSES, "notes", "until-erasure")
    assert _unexplained_retention_skips(True) == {"notes"}


def test_phase8_docs_adr_003_has_a_phase8_revision():
    adr = (ROOT / "docs" / "adr" / "ADR-003-learner-record-synchronization.md").read_text(encoding="utf-8")
    tail = adr.split("(Phase 8: server-issued replicas and compare-and-set)", 1)[1]
    assert all(text in tail for text in ("PD-201", "expected_record_version", "/learner-record/replicas"))


def test_phase8_docs_names_the_shared_files_and_changes_to_existing_tests():
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    assert baseline["commit"] == "512b8a668f6bc95358183c4f173efb0daa44868c"
    assert baseline["main_commit"] == "d366e20980f1e26111ba9f45e95503715ec8564c"
    assert all(baseline[name] in _section(0) for name in ("commit", "main_commit"))
    main_symbols = _main_test_symbols(baseline)
    assert set(main_symbols) == {module for module in _current_test_modules() if not _phase8_test_module(module)}
    listed = set(re.findall(r"`([^ `]+)`", _section(7)))
    missing = set(baseline["shared_paths"]) - listed
    assert not missing, sorted(missing)

    table = _section(13).split("### 13.3 Changes to existing tests", 1)[1].split("### 13.4", 1)[0]
    rows = re.findall(r"^\| `([^`]+)` \| `([^`]+)` \| ([^|]+) \| ([^|]+) \|$", table, re.M)
    trace = {(module, name): (exception.strip(), reason.strip()) for module, name, exception, reason in rows}
    assert len(trace) == len(rows)
    changed, removed = _test_changes(main_symbols)
    assert set(trace) == changed, (sorted(changed - set(trace)), sorted(set(trace) - changed))
    assert all(exception and reason for exception, reason in trace.values())
    replaced = {
        (module, old_name)
        for (module, _), (_, reason) in trace.items()
        for old_name in re.findall(r"Renamed and replaced `([^`]+)`", reason)
    }
    assert replaced == removed, (sorted(removed - replaced), sorted(replaced - removed))
    for module, name in removed:
        if module.endswith(".py"):
            assert name in RETIRED_PHASE8_TEST_NAMES
    assert "test_a_non_finite_preference_is_refused_on_postgres_and_never_a_500" in STRATEGY.read_text(encoding="utf-8")


def test_phase8_docs_the_integration_base_is_the_latest_merged_main():
    intro = SPEC.read_text(encoding="utf-8").split("\n## 0. ", 1)[0]
    merges = re.findall(
        r"reached main as `([0-9a-f]{40})`[^.]*entered this branch in merge `([0-9a-f]{7,40})`", _section(0),
    )
    latest_base, merge = merges[-1]
    assert "The branch was cut at `98f7cc4`" in intro
    assert f"current integration base is Phase 9 main at `{latest_base[:7]}`, integrated in merge `{merge}`" in intro
    assert json.loads(BASELINE.read_text(encoding="utf-8"))["main_commit"] == latest_base


def _erasure_proof_digest_from_spec():
    match = re.search(
        rf"`{re.escape(ERASURE_PROOF)}` has record file SHA-256 after LF normalization `([0-9a-f]{{64}})`",
        _section(17),
    )
    assert match is not None
    return match[1]


def test_phase8_docs_the_erasure_proof_digest_ignores_crlf_checkouts(tmp_path):
    proof = ROOT / ERASURE_PROOF
    crlf = tmp_path / proof.name
    crlf.write_bytes(proof.read_text(encoding="utf-8").replace("\n", "\r\n").encode("utf-8"))
    assert b"\r\n" in crlf.read_bytes()
    assert text_sha256(crlf) == _erasure_proof_digest_from_spec()


def test_phase8_docs_section_17_states_only_the_current_verification():
    section = _section(17)
    assert not re.search(r"^#+ .*Round \d", section, re.M)
    assert not re.search(r"\bv5\b[^\n.]*\bas predecessors\b", section)
    digests = dict(re.findall(r"^\| `([^`]+\.json)` \| `([0-9a-f]{64})` \|$", section, re.M))
    assert set(digests) == set(INPUT_RECORDS)
    assert "| Record | Inputs SHA-256 (record `inputs.sha256`) |" in section
    source_commits = set()
    for path, digest in digests.items():
        record = json.loads((ROOT / path).read_text(encoding="utf-8"))
        assert digest == record["inputs"]["sha256"], path
        if "commit" in record:
            source_commits.add(record["commit"])
    assert len(source_commits) == 1
    evidence_commit = source_commits.pop()
    assert re.fullmatch(r"[0-9a-f]{40}", evidence_commit)
    assert set(re.findall(r"\b[0-9a-f]{7,40}\b", section)) == {evidence_commit}
    proof = ROOT / ERASURE_PROOF
    assert "inputs" not in json.loads(proof.read_text(encoding="utf-8"))
    assert _erasure_proof_digest_from_spec() == text_sha256(proof)
    assert "the proof has no inputs block" in section.lower()


def _require_review_response_fields(response):
    for field in HAND_BACK_FIELDS:
        assert len(re.findall(rf"^- \*\*{re.escape(field)}\.\*\* \S.+$", response, re.M)) == 1, field


def test_phase8_docs_the_handback_check_requires_all_reconciliation_fields():
    section = _section(17).split("\n### 17.2 ", 1)[1]
    fields = tuple(re.findall(r"^- ([^\n]+)$", section, re.M))
    assert fields == HAND_BACK_FIELDS
    response = [f"- **{field}.** Evidence for this field." for field in fields]
    _require_review_response_fields("\n".join(response))
    for index, field in enumerate(fields):
        with pytest.raises(AssertionError, match=field):
            _require_review_response_fields("\n".join(response[:index] + response[index + 1:]))


def test_phase8_docs_shared_file_rules_resolve_inside_the_spec():
    spec = SPEC.read_text(encoding="utf-8").split("\n## 18. ", 1)[0]
    headings = set(re.findall(r"^#{2,6} (\d+(?:\.\d+)*)(?=[. ])", spec, re.M))
    references = set(re.findall(r"§(\d+(?:\.\d+)*)", spec))
    assert not references - headings, sorted(references - headings)
    assert not re.search(r"\b(?:hand-?off|brief)\b", spec, re.I)
    ownership = _section(0).split("### 0.1", 1)[1]
    assert all(term in ownership for term in (
        "ci.yml", "test-strategy.md", "bump-docstring", "test_phase3_acceptance.py", "test_phase5_acceptance.py",
        "package bump exception", "migration-head exception",
        "docs/architecture/ehmf-change-control.md", "docs/architecture/phase7-implementation-spec.md",
        "docs/evaluation/phase7/README.md",
    ))


def test_phase8_docs_describe_the_shipped_package_and_inherited_version_guards():
    paths = [APP / "core/config_package.py", ROOT / "scripts/config_package.py"]
    for path in paths:
        doc = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8")))
        assert f"shipped package v{LATEST_SCHEMA_VERSION}" in doc and "DI-317" in doc
    phase4 = (ROOT / "docs/architecture/phase4-implementation-spec.md").read_text(encoding="utf-8")
    assert f"`v{LATEST_SCHEMA_VERSION}.json` with Phase 8" in phase4.split("### 5.2 Loader", 1)[1].split("\n### ", 1)[0]
    phase6 = (ROOT / "docs/architecture/phase6-implementation-spec.md").read_text(encoding="utf-8")
    inherited = (TESTS / "test_phase6_acceptance.py").read_text(encoding="utf-8")
    assert "test_plan_i_ready_reports_package_v5_and_the_v3_fields_and_no_count" in phase6
    assert "makes no statement beyond the shared gateway stop's" in phase6
    assert "statement.startswith(\"SELECT gateway_stops.reason FROM gateway_stops\")" in inherited
    assert "SELECT learner_adaptation_stops.reason" not in inherited
    structural = (TESTS / "test_config_package.py").read_text(encoding="utf-8").split("def test_v4_structural_errors", 1)[1].split("\ndef ", 1)[0]
    assert 'payload["schema_version"] = LATEST_SCHEMA_VERSION + 1' in structural
    assert f"`schema_version={LATEST_SCHEMA_VERSION + 1}`" in phase6
    assert "V5_RAW, V6_RAW, V7_RAW, RAW" in structural
    assert f"`v5.json`, `v6.json`, `v7.json`, and the shipped v{LATEST_SCHEMA_VERSION}" in phase6
    phase7 = (ROOT / "docs/architecture/phase7-implementation-spec.md").read_text(encoding="utf-8")
    provenance, loader, cli = (
        phase7.split(f"\n### {section} ", 1)[1].split("\n### ", 1)[0]
        for section in ("3.7", "5.2", "5.3")
    )
    evidence = ROOT / "docs/evaluation/phase7"
    readme = (evidence / "README.md").read_text(encoding="utf-8")
    record = json.loads((evidence / "golden_run_v1.json").read_text(encoding="utf-8"))
    assert record["pins"]["config_package"]["version"] == f"{LATEST_SCHEMA_VERSION}.0.0"
    assert re.fullmatch(r"[0-9a-f]{40}", record["commit"])
    for text in (provenance, loader, cli, readme):
        assert not any(stale in text.lower() for stale in (
            "default path is v6", "`default_package_path` is v6", "schema_version` 1-6", "51f4ba0",
        ))
    assert f"`DEFAULT_PACKAGE_PATH` is v{LATEST_SCHEMA_VERSION} with Phase 8" in loader
    assert f"accepts schemas 1-{LATEST_SCHEMA_VERSION} up to `LATEST_SCHEMA_VERSION`" in loader
    assert all(value in loader for value in ("`EHMF_SCHEMA_VERSION` (6)", "`V6_PACKAGE_PATH`", "`V7_PACKAGE_PATH`", "DI-317"))
    assert f"The default path is v{LATEST_SCHEMA_VERSION} with Phase 8" in cli
    acceptance = phase7.split("\n### 13.1 ", 1)[1].split("\n### 13.3 ", 1)[0]
    inherited_tests = phase7.split("\n### 13.3 ", 1)[1].split("\n## ", 1)[0]
    strategy = (ROOT / "docs/testing/test-strategy.md").read_text(encoding="utf-8")
    phase7_strategy = strategy.split("\n## Phase 7 ", 1)[1].split("\n## ", 1)[0]
    for text in (acceptance, inherited_tests, phase7_strategy):
        assert not re.search(r"shipped (?:package (?:is )?)?v[67]\b|v[67] is the default", text, re.I)
    assert "reads v6 explicitly" in acceptance and f"carried into v{LATEST_SCHEMA_VERSION}" in acceptance
    assert "first EHMF package" in acceptance and "independent loader ceiling" in acceptance
    for text in (inherited_tests, phase7_strategy):
        for version in (4, 5):
            assert f"v{version} through v{LATEST_SCHEMA_VERSION}" in text
        assert "`V6_PACKAGE_PATH`" in text and "DI-317" in text
    revision = r"(20\d{6}_phase\w+)"
    head_claim = re.compile(
        rf"\bhead(?: of `?\w+(?:\.py)?`?)?\s+(?:(?:is|at)\s+)?`{revision}`|"
        rf"`{revision}`\s+as (?:the )?head\b|`{revision} \(head\)`", re.I,
    )
    phase7_units = acceptance.split("\n### 13.2 ", 1)[1]
    strategy_rows = [line for line in strategy.splitlines() if line.startswith("|")]
    for line in [*phase7_units.splitlines(), *inherited_tests.splitlines(), *strategy_rows]:
        for clause in re.split(r"(?<=[.!?])\s+|;", line):
            if re.search(r"\b(?:until Phase 8|before Phase 8|at the Phase [5679] release)\b", clause, re.I):
                continue
            for claim in head_claim.finditer(clause):
                assert next(value for value in claim.groups() if value) == SCHEMA_REVISION, line
    phase9_strategy = strategy.split("\n## Phase 9 ", 1)[1].split("\n## ", 1)[0]
    migration_rows = [
        row for text in (inherited_tests, phase7_strategy, phase9_strategy) for row in text.splitlines()
        if row.startswith(("- `test_response_ledger_migrations.py`", "| `test_phase3_acceptance.py`,",
                           "- `test_phase6_acceptance.py`", "| `test_phase6_acceptance.py` |"))
        and "head" in row
    ]
    assert len(migration_rows) == 6
    assert all(f"`{SCHEMA_REVISION}`" in row and "Phase 8, Phase 9, and Phase 7" in row for row in migration_rows)
    for text in (provenance, readme):
        assert "clean Phase 8 integration source commit without a `-dirty` suffix" in text


def test_phase8_docs_phase6_m7_names_both_guest_retention_modes():
    phase6 = (ROOT / "docs/architecture/phase6-implementation-spec.md").read_text(encoding="utf-8")
    erasure = phase6.split("**M7. Erasure.**", 1)[1].split("\n**M8.", 1)[0]
    assert all(term in erasure for term in ("`LEARNER_PRIVACY=off`", "`LEARNER_PRIVACY=on`", "bound guests", "PD-205"))
    assert "legacy" in erasure or "Phase 6 guest-prefix rule" in erasure
    assert all(age == "created_at" for age in guest_retention_age_columns(False).values())
    assert "`created_at`" in erasure and "applies only to tables with" not in erasure
    for table, age in guest_retention_age_columns(True).items():
        if age != "created_at":
            assert f"`{table}`" in erasure and f"`{age}`" in erasure


def test_phase8_docs_distinguish_the_operator_stop_from_the_runtime_trigger():
    section = _section(1)
    for term in ("explicit operator harness run", "`--stop-sqlite`", "runtime stop-the-line trigger",
                 "learner state in an evidential prompt (plan 13.6)", "DI-319"):
        assert term in section
    row = _row("DI-319")
    assert all(term in row for term in (
        "runtime stop-the-line trigger", "Blocked", "tutor_pipeline/contracts.py", "gateway/tools.py", "Handed over",
    ))
    book = (ROOT / "infra/cloudrun/deployment.md").read_text(encoding="utf-8").split("\n## Phase 8:", 1)[1]
    for text in (_section(6), book):
        assert all(term in text for term in ("explicit operator", "runtime", "DI-319"))


def test_phase8_docs_explain_why_policy_fallbacks_are_not_degraded_logs():
    section = _section(1)
    row = next(line for line in section.splitlines() if line.startswith("- **Planner fallback signals.**"))
    assert all(term in row.lower() for term in (
        "flag-off", "no-consent", "held-stop", "static ordering", "do not generate fault alerts",
    ))
    slis = _section(10)
    assert all(term in slis for term in ("learner.planner.degraded", "No-consent", "held-stop", "budget overrun"))
