"""Phase 3: the provenance audit that stands in for F-2's logged-prompt check (DI-49; spec 4.12, 5.4).

L7  package v2 pins the legacy path's ids and containment rule hash (tutor_pipeline.legacy, compared with the code and
    on /ready), ledger_provenance compares every record with the pins, the worker and the script run it
    (--check-provenance), and the spec and the runbooks say so.
Each test fails if its defect comes back; the spec's review history (18.4) names the round behind each group.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.core.config_package import DEFAULT_PACKAGE_PATH, ConfigPackageError, get_config_package, parse_config_package
from app.core.db import Base
from app.core.schema_upgrades import run_schema_upgrades
from app.main import app
from app.services import ledger
from app.services.contained_answers import EXTRACTIVE_MODE
from app.services.ledger import (
    LegacyDelivery,
    append_ledger_entry,
    build_legacy_entry,
    ledger_provenance,
    record_legacy_delivery,
    verify_response_ledger,
)
from app.services.retrieval_engine import RetrievalEngine
from app.services.store import get_course_store
from app.services.tutor_pipeline.contracts import ENTRY_SCHEMAS, LedgerEntry, PresentationPlan
from app.services.tutor_pipeline.package_check import check_tutor_pipeline_package
from app.services.tutor_pipeline.pipeline import PipelineInput, TwoPassPipeline
from app.services.tutor_pipeline.resolve import LearnerTurn, resolve_turns

from tutor_fakes import make_entry


API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parents[1]
SPEC = (REPO_ROOT / "docs" / "architecture" / "phase3-implementation-spec.md").read_text(encoding="utf-8")
RUNBOOK = (REPO_ROOT / "infra" / "cloudrun" / "deployment.md").read_text(encoding="utf-8").split("## Phase 3", 1)[1]
OBSERVABILITY = (REPO_ROOT / "infra" / "cloudrun" / "observability.md").read_text(encoding="utf-8").split("## Phase 3", 1)[1]
V2_RAW = json.loads((API_ROOT / "app" / "config_package" / "v2.json").read_text(encoding="utf-8"))
PACKAGE = get_config_package(Settings())
PARAMS = PACKAGE.tutor_pipeline
MULTI_CLAIM = "Explain why quantum logistics needs both problem reduction before execution and routing control during compilation."


def _section(title: str, end: str) -> str:
    return SPEC.split(title, 1)[1].split(end, 1)[0]


@pytest.fixture
def isolated(fresh_database_url):
    engine = create_engine(fresh_database_url)
    Base.metadata.create_all(engine)
    run_schema_upgrades(engine)
    try:
        yield engine, sessionmaker(bind=engine)
    finally:
        engine.dispose()


def _pipeline_run(pipeline: TwoPassPipeline, query: str, *, record: bool = False):
    resolved = resolve_turns([], LearnerTurn(f"message-{uuid4()}", query), package=pipeline.package)
    return pipeline.run(PipelineInput(resolved=resolved, lesson_slug=None, presentation=PresentationPlan(plan_id="concise", source="request"),
                                      response_id=f"shadow-{uuid4()}", delivery="shadow", shadowed_response_id=f"turn-{uuid4()}"), record=record)


# =============================================================================================================== L7


def test_l7_package_v2_pins_the_legacy_path_and_package_check_compares_it():
    assert (PARAMS.legacy_pipeline_version, PARAMS.legacy_generator_id, PARAMS.legacy_generator_model_id, PARAMS.legacy_containment_rule_hash) == (
        ledger.LEGACY_PIPELINE_VERSION, ledger.LEGACY_GENERATOR_ID, EXTRACTIVE_MODE, ledger.LEGACY_CONTAINMENT_RULE_HASH)
    assert check_tutor_pipeline_package(PACKAGE, structural=False) == []
    for field, value in (("legacy_pipeline_version", "legacy-contained-v2"), ("legacy_generator_id", "contained-answers-v2"),
                         ("legacy_generator_model_id", "extractive-other"), ("legacy_containment_rule_hash", "e" * 64)):
        changed = dataclasses.replace(PACKAGE, tutor_pipeline=dataclasses.replace(PARAMS, **{field: value}))
        problems = check_tutor_pipeline_package(changed, structural=False)
        assert any(f"tutor_pipeline.legacy.{field.removeprefix('legacy_')} in the package ({value})" in problem for problem in problems), field
    unknown = dataclasses.replace(PACKAGE, tutor_pipeline=dataclasses.replace(PARAMS, legacy_pipeline_version="legacy-contained-v2"))
    assert any("not a pipeline the LedgerEntry contract accepts" in problem for problem in check_tutor_pipeline_package(unknown, structural=False))
    # The loader refuses a v2 package without the block, or with a malformed hash.
    for mutate in (lambda p: p["tutor_pipeline"].pop("legacy"), lambda p: p["tutor_pipeline"]["legacy"].update(containment_rule_hash="0" * 63),
                   lambda p: p["tutor_pipeline"]["legacy"].pop("generator_id")):
        payload = copy.deepcopy(V2_RAW)
        mutate(payload)
        with pytest.raises(ConfigPackageError):
            parse_config_package(payload, path=DEFAULT_PACKAGE_PATH, sha256="", hash_verified=False)
    # /ready reports the pins an operator compares records with.
    body = TestClient(app).get("/ready").json()
    assert body["tutor_pipeline"]["legacy"] == {
        "pipeline_version": PARAMS.legacy_pipeline_version, "generator_id": PARAMS.legacy_generator_id,
        "generator_model_id": PARAMS.legacy_generator_model_id, "containment_rule_hash": PARAMS.legacy_containment_rule_hash,
    }


def _legacy(*, claims: tuple = ()) -> LegacyDelivery:
    return LegacyDelivery(
        response_id=f"turn-{uuid4()}", decision="answer" if claims else "abstain", reason="no_approved_span", claims=claims, quoted=(),
        retrieved=None, answer_sha256="c" * 64, retrieval_mode="lexical-extractive-lexically-screened", provider="none",
        model=EXTRACTIVE_MODE, corpus_version="corpus-test", index_version="index-test", gate="p1-floor", threshold_version="score-floor-p1-v1",
        floor=6.0, margin=0.0, policy_version="cs595-v1",
    )


CLAIM = (("Routing adds SWAP gates on sparse hardware.", ("span-" + "1" * 64,)),)


def _changed(entry: LedgerEntry, *, entry_provenance: dict | None = None, claim_provenance: dict | None = None,
             resolver_prompt_hash: str | None = None) -> LedgerEntry:
    """A copy of entry under a new response id, with its record's and/or its claims' provenance changed."""
    data = entry.model_dump(mode="json")
    if resolver_prompt_hash is not None:
        data["resolved_question"]["resolver"]["prompt_hash"] = resolver_prompt_hash
    prefix = data["response_id"].split("-", 1)[0]
    data["response_id"] = f"{prefix}-{uuid4()}"
    if data["shadowed_response_id"] is not None:
        data["shadowed_response_id"] = f"turn-{uuid4()}"
    data["provenance"].update(entry_provenance or {})
    for claim in data["claims"]:
        claim["response_id"] = data["response_id"]
        claim["provenance"] = {**data["provenance"], **(claim_provenance or {})} if claim_provenance else dict(data["provenance"])
    # Each record validates as its own entry schema (a two-pass record is ledger-entry-v2 since Phase 4).
    return ENTRY_SCHEMAS[data["entry_schema"]].model_validate(data)


def test_l7_the_provenance_audit_passes_on_the_records_the_code_writes_and_names_each_record_that_differs(isolated):
    _, factory = isolated
    settings = Settings()
    assert record_legacy_delivery(_legacy(claims=CLAIM), settings=settings, session_factory=factory).seq == 1
    assert record_legacy_delivery(_legacy(), settings=settings, session_factory=factory).seq == 2
    pipeline = TwoPassPipeline(RetrievalEngine(get_course_store(), settings), settings, session_factory=factory)
    answered = _pipeline_run(pipeline, MULTI_CLAIM, record=True)
    abstained = _pipeline_run(pipeline, "the of and", record=True)
    assert answered.decision == "answer" and answered.entry.claims and abstained.decision == "abstain" and not abstained.entry.claims
    with factory() as db:
        audit = ledger_provenance(db, PACKAGE)
    assert audit == {"package_version": PACKAGE.package_version, "package_sha256": PACKAGE.sha256, "records": 4, "checked": 4, "other_package": 0,
                     "problem_count": 0, "problems": []}
    legacy_entry = build_legacy_entry(_legacy(claims=CLAIM), settings=settings, package=PACKAGE, manifest_sha256=None)
    budget = 5000
    append_ledger_entry(_changed(legacy_entry, entry_provenance={"evidential_prompt_hash": "d" * 64}), session_factory=factory, budget_ms=budget)
    generator = legacy_entry.model_dump(mode="json")
    generator["response_id"] = f"turn-{uuid4()}"
    generator["versions"]["generator_id"] = "contained-answers-v9"
    for claim in generator["claims"]:
        claim["response_id"] = generator["response_id"]
    append_ledger_entry(ENTRY_SCHEMAS[generator["entry_schema"]].model_validate(generator), session_factory=factory, budget_ms=budget)
    append_ledger_entry(_changed(abstained.entry, entry_provenance={"pedagogical_prompt_hash": "e" * 64}), session_factory=factory, budget_ms=budget)
    append_ledger_entry(_changed(answered.entry, resolver_prompt_hash="f" * 64), session_factory=factory, budget_ms=budget)
    append_ledger_entry(make_entry(), session_factory=factory, budget_ms=budget)  # stamped with another package (b * 64)
    with factory() as db:
        audit = ledger_provenance(db, PACKAGE)
        chain = verify_response_ledger(db)
    assert chain.ok and chain.count == 9  # every record is a sound link: the audit checks what the chain check cannot
    assert (audit["records"], audit["checked"], audit["other_package"]) == (9, 8, 1)
    assert audit["problems"] == [
        "seq 5 provenance.evidential_prompt_hash is not the package pin",
        "seq 6 versions.generator_id is not the package pin",
        "seq 7 provenance.pedagogical_prompt_hash is not the package pin",
        "seq 8 resolved_question.resolver.prompt_hash is not the package pin",
    ] and audit["problem_count"] == 4
    # A record naming a pipeline the package does not pin, and one whose generator it does not allow.
    two_pass = json.loads(json.dumps(answered.entry.model_dump(mode="json")))
    assert ledger._provenance_problems(10, {**two_pass, "pipeline": "two-pass-v9"}, PARAMS, PACKAGE.v1, ledger.phase5_blocks(PACKAGE)) == ["seq 10 names a pipeline the package does not pin"]
    two_pass["versions"]["generator_id"] = "gateway-v1"
    assert ledger._provenance_problems(11, two_pass, PARAMS, PACKAGE.v1, ledger.phase5_blocks(PACKAGE)) == ["seq 11 versions.generator_id is not a generator the package allows"]
    # A claim whose provenance differs from its record's: the LedgerEntry contract refuses one, so the audit's check is a
    # second line, shown here on a raw entry.
    legacy = legacy_entry.model_dump(mode="json")
    legacy["claims"][0]["provenance"] = {**legacy["provenance"], "threshold_set_version": "other"}
    assert ledger._provenance_problems(12, legacy, PARAMS, PACKAGE.v1, ledger.phase5_blocks(PACKAGE)) == ["seq 12 has a claim whose provenance differs from its record's"]


def _run_worker(database_url: str, *args: str) -> tuple[int, dict]:
    env = {**os.environ, "DATABASE_URL": database_url, "PYTHONUNBUFFERED": "1"}
    completed = subprocess.run([sys.executable, "-m", "app.workers.response_ledger", *args], cwd=API_ROOT, env=env, capture_output=True,
                               text=True, timeout=120)
    report = next(line for line in completed.stderr.splitlines() if '"job": "response_ledger"' in line)
    return completed.returncode, json.loads(report[report.index("{"):])


def _load_verify_script():
    import importlib.util

    spec = importlib.util.spec_from_file_location("phase3_verify_ledger_l7", REPO_ROOT / "scripts" / "verify_ledger.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_l7_the_worker_and_the_script_check_provenance(fresh_database_url, isolated, capsys):
    _, factory = isolated
    settings = Settings()
    record_legacy_delivery(_legacy(claims=CLAIM), settings=settings, session_factory=factory)
    returncode, report = _run_worker(fresh_database_url, "--check-provenance")
    assert returncode == 0 and report["status"] == "ok" and report["provenance"]["checked"] == 1 and report["provenance"]["problems"] == []
    returncode, report = _run_worker(fresh_database_url)
    assert returncode == 0 and "provenance" not in report  # only when asked
    script = _load_verify_script()
    assert script.main(["--database-url", fresh_database_url, "--check-provenance"]) == 0
    assert json.loads(capsys.readouterr().out)["provenance"]["problem_count"] == 0
    entry = build_legacy_entry(_legacy(claims=CLAIM), settings=settings, package=PACKAGE, manifest_sha256=None)
    append_ledger_entry(_changed(entry, entry_provenance={"evidential_prompt_hash": "d" * 64}, claim_provenance={"evidential_prompt_hash": "d" * 64}),
                        session_factory=factory, budget_ms=5000)
    returncode, report = _run_worker(fresh_database_url, "--check-provenance")
    assert returncode == 1 and (report["status"], report["severity"]) == ("provenance_mismatch", "ERROR")
    assert report["problems"] == [] and report["provenance"]["problems"] == ["seq 2 provenance.evidential_prompt_hash is not the package pin"]
    assert script.main(["--database-url", fresh_database_url, "--check-provenance"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "provenance_mismatch"
    assert script.main(["--database-url", fresh_database_url]) == 0  # the chain itself is sound
    capsys.readouterr()


def test_l7_the_records_say_the_audit_exists_and_what_package_v2_pins():
    di_49 = next(line for line in SPEC.splitlines() if line.startswith("| DI-49 |"))
    assert "--check-provenance" in di_49 and "`test_l7_*`" in di_49 and "not yet run in production" in di_49
    assert "--check-provenance" in RUNBOOK and "provenance_mismatch" in RUNBOOK and "provenance_mismatch" in OBSERVABILITY
    assert "**`ledger_provenance(db, package)`**" in _section("### 4.12 Ledger", "### 4.13")
    assert "| legacy |" in _section("### 5.2 Loader", "### 5.3") and "`legacy.containment_rule_hash` against" in _section("### 5.4", "### 5.5")
    # The register's DI-49 row and the closure notes are checked by the evidence package's 00_meta/check_records.py
    # (check_l7_*).
