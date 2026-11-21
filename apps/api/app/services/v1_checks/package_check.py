"""Consistency of configuration package v3's v1 block with the V1 code (Phase 4 spec 5.3).

Always (start-up, tests, CI): v1.rules_hash equals the hash of the code's rule vocabulary and the package's lexicon
(v1_rules_hash); v1.rule_ids equal RULE_IDS (V1.4's is claim_gate.SUBSET_CHECK_RULE); the contract's
SUBSET_PROBLEM_CODES equal claim_gate.PROBLEM_CODES; REASON_OUTCOMES is total over bind's outcomes and the gate's
sufficiency reasons; the checker registry equals WIRED_CHECKERS; v1.quiz_feedback.rule is the quiz route's rule
(quiz_keys.FEEDBACK_RULE, PD-21).

structural=True (tests, CI and scripts/config_package.py --check only): the adversarial fixture file exists and its
set_sha256 and case count equal the package's pin. The image holds no docs/, so start-up never compares them, and the
repository root is found only when a structural check asks for it (repository_root): in the API image this module is
/app/app/services/v1_checks/package_check.py, which has fewer parents than a checkout, so nothing here may compute the
root at import (start-up imports this module).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, get_args

from app.core.config_package import canonical_sha256
from app.services.v1_checks.rules import REPOSITORY_DEPTH

if TYPE_CHECKING:  # pragma: no cover
    from app.core.config_package import ConfigPackage


def repository_root() -> Path:
    """The checkout this module runs from (tests, CI, scripts). FileNotFoundError where there is none: the API image
    has fewer parents than REPOSITORY_DEPTH and no docs/."""
    parents = Path(__file__).resolve().parents
    if len(parents) <= REPOSITORY_DEPTH:
        raise FileNotFoundError("no repository checkout holds this module (the API image has none)")
    return parents[REPOSITORY_DEPTH]


def fixture_set_sha256(cases: list) -> str:
    """set_sha256 = canonical sha256 of the sorted case sha256s (Phase 4 spec 12.1)."""
    return canonical_sha256(sorted(canonical_sha256(case) for case in cases))


def fixture_problems(package: "ConfigPackage", *, root: Path | None = None) -> list[str]:
    v1 = package.v1
    try:
        path = (root if root is not None else repository_root()) / v1.fixtures_path
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [f"v1 fixtures: {v1.fixtures_path} is missing or not JSON"]
    cases = payload.get("cases") if isinstance(payload, dict) else None
    if not isinstance(cases, list):
        return [f"v1 fixtures: {v1.fixtures_path} holds no case list"]
    problems = []
    if fixture_set_sha256(cases) != v1.fixtures_set_sha256:
        problems.append("v1 fixtures: the fixture set does not match the package's set_sha256 (run scripts/config_package.py --rehash)")
    if len(cases) != v1.fixtures_cases:
        problems.append(f"v1 fixtures: the file holds {len(cases)} cases, the package pins {v1.fixtures_cases}")
    return problems


def check_v1_package(package: "ConfigPackage", *, structural: bool) -> list[str]:
    if package.v1 is None:
        return ["the configuration package has no v1 block"]
    from app.services.claim_gate import PROBLEM_CODES, SUBSET_CHECK_RULE
    from app.services.lexical_index import Reason
    from app.services.tutor_pipeline.bind import DROP_REASONS
    from app.services.tutor_pipeline.contracts import (
        GATE_ABSTENTION_REASONS,
        NO_QUOTABLE_EVIDENCE,
        REASON_OUTCOMES,
        SUBSET_PROBLEM_CODES,
    )
    from app.services.v1_checks.rules import RULE_IDS, WIRED_CHECKERS, v1_rules_hash
    from app.services.v1_checks.v1_3_entailment import CHECKERS

    v1 = package.v1
    problems: list[str] = []
    if v1.rules_hash != v1_rules_hash(package):
        problems.append("v1.rules_hash differs from the code's rule vocabulary and the package lexicon (run scripts/config_package.py --rehash)")
    if dict(v1.rule_ids) != RULE_IDS:
        problems.append("v1.rule_ids differ from the code's RULE_IDS")
    if RULE_IDS["V1.4"] != SUBSET_CHECK_RULE:
        problems.append("V1.4's rule id is not the subset check's")
    if tuple(SUBSET_PROBLEM_CODES) != tuple(PROBLEM_CODES):
        problems.append("contracts.SUBSET_PROBLEM_CODES differ from claim_gate.PROBLEM_CODES")
    bind_outcomes = {"bound", *DROP_REASONS}
    if not bind_outcomes <= set(REASON_OUTCOMES["V1.2"]):
        problems.append(f"REASON_OUTCOMES V1.2 lacks bind outcomes {sorted(bind_outcomes - set(REASON_OUTCOMES['V1.2']))}")
    gate_reasons = {reason for reason in get_args(Reason) if reason != "evidence"} | set(GATE_ABSTENTION_REASONS) | {NO_QUOTABLE_EVIDENCE, "corpus_version_mismatch"}
    if not gate_reasons | {"answer", "near_miss"} <= set(REASON_OUTCOMES["V1.5"]):
        problems.append("REASON_OUTCOMES V1.5 is not total over the gate's sufficiency reasons")
    if set(CHECKERS) != set(WIRED_CHECKERS):
        problems.append("the checker registry differs from WIRED_CHECKERS")
    from app.services.quiz_keys import FEEDBACK_RULE

    if v1.quiz_feedback_rule != FEEDBACK_RULE:
        problems.append("v1.quiz_feedback.rule differs from the quiz route's rule (quiz_keys.FEEDBACK_RULE, PD-21)")
    if structural:
        problems.extend(fixture_problems(package))
    return problems
