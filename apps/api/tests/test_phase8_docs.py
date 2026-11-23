"""Phase 8 authoring, ownership, and test traceability guards."""

import ast
from pathlib import Path
import re

from app import db_models
from app.core.authorization import ROUTE_POLICIES
from app.core.phase8_settings import PHASE8_FLAGS
from app.services.erasure import RETENTION_EXEMPT_TABLES, user_keyed_tables
from app.services.learner_record_planner import ADVANCED_THRESHOLD, FOUNDATION_THRESHOLD
from app.services.learner_record_privacy import CONSENT_CLASSES, CONSENT_VERSION
from app.services.learner_record_shadow import COMPLETION_THRESHOLD, PLANNER_BUDGET_MS
from app.services.learner_record_sync import ASSESSMENT_LIMIT, ASSESSMENT_WINDOW, MAX_ISSUED_REPLICAS
from app.services.retention import retention_classes
from scripts.run_invariance_harness import LEVELS
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
PHASE8_EXTENDED_MODULES = {
    "test_api.py", "test_authorization.py", "test_cs595_increment.py", "test_erasure_retention.py",
    "test_malformed_input.py", "apps/frontend/tests/privacy-inventory.integration.test.ts",
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


def _names():
    return {
        node.name for path in TESTS.glob("test_*.py")
        for node in ast.parse(path.read_text(encoding="utf-8")).body if isinstance(node, ast.FunctionDef)
    }


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


def test_phase8_docs_spec_headings_shapes_and_plan_quotes():
    spec = SPEC.read_text(encoding="utf-8")
    assert [int(name) for name in re.findall(r"^## (\d+)\.", spec, re.M)] == list(range(19))
    assert _section(18).count("| Round |") == 1 and not re.search(r"^#+ ", _section(18), re.M)
    assert _section(18).count("| Review 1 |") == 1
    for model in PHASE8_MODELS:
        line = next(line for line in _section(3).splitlines() if line.startswith(f"| `{model}` |"))
        listed = set(re.findall(r"`([a-z][a-z_]+)`", line.split("|")[2]))
        assert listed == set(getattr(db_models, model).__table__.c.keys()), model
    assert "Flags for planner and sync. Stop: any harness violation blocks adaptation (never evidence)." in _section(6)
    assert "residual: backups keep erased rows for a window." in _section(16)
    assert "AC-8-1 to AC-8-7 green; harness in CI." in _section(17)
    for number in range(300, 317):
        assert _row(f"DI-{number}")
    retention = (ROOT / "infra" / "cloudrun" / "retention-job.md").read_text(encoding="utf-8").split("\n## Phase 8\n")[1]
    for flag in PHASE8_FLAGS:
        assert flag.upper() in retention and flag.upper() in _section(6)


def test_phase8_docs_the_test_strategy_maps_every_test_module_the_phase_added():
    phase = STRATEGY.read_text(encoding="utf-8").split("\n## Phase 8 acceptance map", 1)[1].split("\n## ", 1)[0]
    added, changed = phase.split("### Phase 8 changes to existing test modules", 1)
    def rows(text):
        return dict(re.findall(r"^\| `([^\x60]+)\x60 \| (.+) \|$", text, re.M))
    declared = rows(added)
    assert set(declared) == {path.name for path in TESTS.glob("test_phase8_*.py")} | {
        "apps/frontend/tests/phase8-learner-sync.integration.test.ts",
    }
    assert all(len(description) > 100 for description in declared.values())
    assert set(rows(changed)) == PHASE8_EXTENDED_MODULES
    assert "**Exit gate.**" in changed and "phase8_exit_passed" in changed
    names = _names()
    for text in (phase, _section(13), _section(18)):
        assert set(re.findall(r"`(test_\w+)`", text)) <= names
    ac_lines = [line for line in phase.splitlines() if line.startswith("| AC-8-")]
    assert len(ac_lines) == 7 and all(re.search(r"`test_\w+`", line) for line in ac_lines)


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
    assert not NARRATIVE.search(spec)
    assert not NARRATIVE.search(STRATEGY.read_text(encoding="utf-8").split("## Phase 8 acceptance map", 1)[1])
    for path in paths:
        assert not NARRATIVE.search(path.read_text(encoding="utf-8")), path.name


def test_phase8_docs_spec_section_10_names_every_learner_event_in_code():
    paths = [*APP.glob("api/routes/*.py"), *APP.glob("services/learner_record*.py"),
             APP / "services" / "tutor_orchestrator.py", ROOT / "scripts" / "run_invariance_harness.py"]
    events = set()
    for path in paths:
        events.update(re.findall(r'"((?:learner|subject)\.[a-z_.]+|analytics\.consent_withheld)"',
                                path.read_text(encoding="utf-8")))
    assert events and all(f"`{name}`" in _section(10) for name in events), events


def test_phase8_docs_the_consent_schema_lists_the_retention_classes_in_code():
    doc = (ROOT / "docs" / "security" / "consent-schema.md").read_text(encoding="utf-8")
    names = {table.name for table in user_keyed_tables()}
    assert dict(re.findall(r"^\| `(\w+)` \| `([^\x60]+)\x60 \|$", doc, re.M)) == retention_classes()
    assert names == retention_classes().keys() and retention_classes()["user_accounts"] == "until-erasure"
    assert all(cls in doc for cls in (*CONSENT_CLASSES, CONSENT_VERSION, "LEARNER_PRIVACY=on"))


def test_retention_exempt_tables_each_have_a_reason():
    assert {"learner_subjects", "user_accounts", "user_sessions"} <= RETENTION_EXEMPT_TABLES.keys()
    assert all(reason.strip() for reason in RETENTION_EXEMPT_TABLES.values())


def test_phase8_docs_adr_003_has_a_phase8_revision():
    adr = (ROOT / "docs" / "adr" / "ADR-003-learner-record-synchronization.md").read_text(encoding="utf-8")
    tail = adr.split("(Phase 8: server-issued replicas and compare-and-set)", 1)[1]
    assert all(text in tail for text in ("PD-201", "expected_record_version", "/learner-record/replicas"))


def test_phase8_docs_names_the_shared_files_and_changes_to_existing_tests():
    app_modules = {
        file.relative_to(APP).as_posix() for file in APP.glob("services/learner_record*.py")
    } | {
        "core/phase8_settings.py", "core/config.py", "core/auth.py", "core/authorization.py", "db_models.py",
        "schemas.py", "api/routes/learner_record.py", "api/routes/auth.py", "api/routes/content.py",
        "api/routes/analytics.py", "services/tutor_orchestrator.py", "src/lib/api.ts", "src/lib/learner-record-api.ts",
    }
    assert all(f"`{path}`" in _section(7) for path in app_modules)
    table = _section(13).split("### 13.3 Changes to existing tests", 1)[1]
    for name in (
        "test_progress_endpoint_aggregates_activity", "test_a_refused_caller_is_refused",
        "test_no_caller_scoped_read_returns_another_learners_data",
        "test_learner_record_api_requires_a_durable_session_and_accepts_idempotent_operations",
        "test_retention_removes_stale_guest_rows_in_every_table_and_keeps_the_rest",
        "test_non_finite_preference_follows_the_flagged_backend_contract",
        "test_a_learner_record_value_that_cannot_be_stored_is_refused_and_the_record_still_reads",
    ):
        assert name in table and name in _names()
