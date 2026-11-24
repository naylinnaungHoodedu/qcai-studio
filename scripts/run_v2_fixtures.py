"""V2 fixture runs: F-1 and fault injection on the development fakes (plan Phase 5 P "ledger verdicts for 100% of test
responses (F-1)", J "Fault injection: one to three providers down"; Phase 5 spec 12.1, R-g).

Run: python scripts/run_v2_fixtures.py --write docs/evaluation/phase5/v2_fixture_report_v1.json [--allow-dirty]
     python scripts/run_v2_fixtures.py --check docs/evaluation/phase5/v2_fixture_report_v1.json

Public-corpus fixtures only (apps/api/tests/data/score_floor_queries.json: 174 in-domain, 124 off-topic and
stopword-only queries; anything under lqs/ is refused). The runner builds the all-public-approved store (a temporary
manifest approving every public-plane, bound item) in development with V1_PIPELINE=enforce and MODEL_GATEWAY=on, the
shipped development registry, a fresh model gateway and evidential cache per scenario, and an in-memory SQLite ledger,
and runs every query in five passes:
  all_up      every fake eligible (FULL)
  one_down    fake-gamma and fake-delta disabled (REDUCED-2; eligibility precedes the panel, so fake-delta is the spare)
  two_down    fake-beta to fake-delta disabled (REDUCED-1)
  three_down  all four disabled (ZERO)
  cache_pass  the all_up queries again on the all_up gateway and cache (claim-plan and verdict hits; verdict_calls
              counts the claim items that missed the cache, alignment_calls the alignment items, never cached)
Each scenario's calls_by_item splits its calls into claim and alignment items.
F-1 per response: the record verifies in its chain, every recorded claim has a verdict with at least one V1 result, every
V2-eligible claim of a final V1-passed candidate carries a v2 verdict, and no V2 verdict follows a V1 hard fail or a V1
abstention. The report is labelled "fixture measurements, not research results" (plan Phase 5 H: V-2 and V-4 are E2
results, never claimed from fixtures). `commit` is informational; `inputs` (the LF sha256 of every imported repository
module) is the provenance --check compares; latency values are measured and never compared.

Exit codes: 0 pass; 1 drift (--check: the record differs from a fresh run, created_at, commit and latency aside); 3 F-1
below 100% or a mode or rule that contradicts the routing table (a stop); 4 a dirty tree on --write; 5 a V2 verdict after
a V1 fail or a delivery without a passing vote (an invariant breach).
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
for path in (REPO_ROOT, API_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import os  # noqa: E402

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.core.config import Settings  # noqa: E402
from app.core.config_package import canonical_sha256, get_config_package  # noqa: E402
from app.core.manifest_v2 import with_all_public_approved  # noqa: E402

QUERIES_PATH = API_ROOT / "tests" / "data" / "score_floor_queries.json"
REPO_MANIFEST = REPO_ROOT / "corpus" / "public" / "manifest.json"
DEFAULT_REPORT = REPO_ROOT / "docs" / "evaluation" / "phase5" / "v2_fixture_report_v1.json"
EVIDENCE_CLASS = "fixture measurements, not research results (plan Phase 5 H: V-2, V-4 are E2 results, never claimed from fixtures)"
SCENARIOS = (("all_up", (), "FULL"), ("one_down", ("fake-gamma-v1", "fake-delta-v1"), "REDUCED-2"),
             ("two_down", ("fake-beta-v1", "fake-gamma-v1", "fake-delta-v1"), "REDUCED-1"),
             ("three_down", ("fake-alpha-v1", "fake-beta-v1", "fake-gamma-v1", "fake-delta-v1"), "ZERO"))
EXIT_DRIFT, EXIT_STOP, EXIT_DIRTY, EXIT_BREACH = 1, 3, 4, 5
INPUTS_RULE = "imported-repository-modules-sha256-lf-v1"
INPUT_PREFIXES = ("apps/api/app/", "scripts/")
SELF = "scripts/run_v2_fixtures.py"
_V1_REASONS: tuple[str, ...] = ()


def queries() -> list[str]:
    data = json.loads(QUERIES_PATH.read_text(encoding="utf-8"))
    return [item["query"] for item in data["in_domain"]] + list(data["off_topic"]) + list(data["stopword_only"])


def _refuse_lqs(path: Path) -> None:
    if "lqs" in Path(path).resolve().parts:
        raise SystemExit("refused: ULQS paths are never fixtures (plan H)")


def text_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def run_inputs() -> dict:
    root = REPO_ROOT.resolve()
    files: dict[str, str] = {}
    for module in list(sys.modules.values()):
        location = getattr(module, "__file__", None)
        if not location or not str(location).endswith(".py"):
            continue
        path = Path(location).resolve()
        if not path.is_relative_to(root):
            continue
        relative = path.relative_to(root).as_posix()
        if relative.startswith(INPUT_PREFIXES):
            files[relative] = text_sha256(path)
    files[SELF] = text_sha256(Path(__file__).resolve())
    ordered = dict(sorted(files.items()))
    return {"rule": INPUTS_RULE, "files": ordered, "sha256": canonical_sha256(ordered)}


def input_problems(inputs: dict, root: Path = REPO_ROOT) -> list[str]:
    """What in a record's `inputs` no longer matches the checkout (the rule, the digest, each listed file's hash)."""
    problems = []
    if inputs.get("rule") != INPUTS_RULE:
        problems.append(f"unknown inputs rule {inputs.get('rule')!r}")
    files = inputs.get("files") or {}
    if canonical_sha256(dict(sorted(files.items()))) != inputs.get("sha256"):
        problems.append("the inputs digest does not match its file map")
    for relative, digest in sorted(files.items()):
        path = Path(root) / relative
        if not path.is_file():
            problems.append(f"{relative} is listed but missing")
        elif text_sha256(path) != digest:
            problems.append(f"{relative} differs from the code the record ran")
    return problems


def nearest_rank_p95(values) -> float | None:
    import math

    ordered = sorted(values)
    return None if not ordered else round(float(ordered[max(math.ceil(0.95 * len(ordered)) - 1, 0)]), 3)


class Environment:
    """The all-public-approved development store and an in-memory SQLite ledger."""

    def __init__(self, temp: Path) -> None:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool

        from app.core.db import Base
        from app.core.schema_upgrades import run_schema_upgrades
        from app.services.content_assembler import CourseStore
        from app.services.retrieval_engine import RetrievalEngine

        manifest = temp / "manifest.json"
        manifest.write_text(json.dumps(with_all_public_approved(json.loads(REPO_MANIFEST.read_text(encoding="utf-8")))), encoding="utf-8")
        self.manifest = manifest
        base = self.settings(())
        self.store = CourseStore(base)
        self.engine = RetrievalEngine(self.store, base)
        self.database = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.database)
        run_schema_upgrades(self.database)
        self.sessions = sessionmaker(bind=self.database)

    def settings(self, down) -> Settings:
        return Settings(environment="development", enforce_corpus_governance=True, corpus_manifest_path=str(self.manifest),
                        retrieval_gate="bm25f-v1", two_pass_tutor="shadow", v1_pipeline="enforce", model_gateway="on",
                        model_gateway_disabled_adapters=list(down), ehmf="off", ranking="off")

    def close(self) -> None:
        self.database.dispose()


def _gateway(package, settings):
    from app.gateway.budget import DailyBudget
    from app.gateway.gateway import ModelGateway
    from app.gateway.registry import registry_name

    return ModelGateway(budget=DailyBudget(package.gateway.daily_units[registry_name(settings, package.gateway.registries)]))


def _pipeline(env: Environment, settings: Settings, gateway, cache):
    from app.services.retrieval_engine import RetrievalEngine
    from app.services.tutor_pipeline.pipeline import TwoPassPipeline

    return TwoPassPipeline(RetrievalEngine(env.store, settings), settings, gateway=gateway, cache=cache, session_factory=env.sessions)


def _turn(pipeline, query: str):
    from app.services.tutor_pipeline.contracts import PresentationPlan
    from app.services.tutor_pipeline.pipeline import PipelineInput
    from app.services.tutor_pipeline.resolve import LearnerTurn, resolve_turns

    resolved = resolve_turns([], LearnerTurn(f"message-{uuid4()}", query), package=pipeline.package)
    return pipeline.run(PipelineInput(resolved=resolved, lesson_slug=None, presentation=PresentationPlan(plan_id="concise", source="default"),
                                      response_id=f"shadow-{uuid4()}", delivery="shadow", shadowed_response_id=f"turn-{uuid4()}",
                                      legacy_decision=None), record=True)


def _f1(result, v1_reasons) -> tuple[bool, bool, int]:
    """(complete, a V2 verdict after a V1 fail, deliveries without a passing vote) of one response."""
    entry = result.entry
    verification = entry.verification
    judged = {verdict.claim_id for verdict in verification.verdicts if verdict.v2 is not None}
    v1_failed = verification.hard_fail or (verification.final == "abstain" and verification.final_reason in v1_reasons)
    after_fail = v1_failed and bool(judged)
    without_pass = sum(1 for verdict in verification.verdicts if verdict.final == "deliver" and (verdict.v2 is None or verdict.v2.outcome != "pass"))
    recorded = {claim.claim_id for claim in entry.claims}
    complete = {verdict.claim_id for verdict in verification.verdicts if verdict.v1} >= recorded
    outcome = result.v1.v2 if result.v1 is not None else None
    if outcome is not None:
        complete = complete and set(outcome.claims) <= judged
    complete = complete and not after_fail
    return complete, after_fail, without_pass


def _scenario(env: Environment, name: str, down, expected_mode: str, items, payload_fields: dict, latencies: dict, table, gateway=None, cache=None):
    from app.gateway.metrics import GATEWAY_METRICS
    from app.services.tutor_pipeline.contracts import ABSTENTION_REASONS, V1_ABSTENTION_REASONS
    from app.services.v2_panel.cache import ProcessEvidentialCache

    settings = env.settings(down)
    package = get_config_package(settings)
    gateway = gateway or _gateway(package, settings)
    cache = cache if cache is not None else ProcessEvidentialCache(max_plans=package.gateway.cache_max_plans,
                                                                   max_verdicts=package.gateway.cache_max_verdicts)
    pipeline = _pipeline(env, settings, gateway, cache)
    gateway.captured = []
    v1_reasons = (*ABSTENTION_REASONS, *V1_ABSTENTION_REASONS)
    modes, finals, tiers, outcomes = Counter(), Counter(), Counter(), Counter()
    complete = after_fail = without_pass = x2 = calls = cost = 0
    contradictions = []
    per_response_cost = []
    for query in items:
        result = _turn(pipeline, query)
        verification = result.entry.verification
        ok, failed, unpassed = _f1(result, v1_reasons)
        complete += int(ok)
        after_fail += int(failed)
        without_pass += unpassed
        block = verification.v2
        finals[verification.final] += 1
        if block.panel_reached:
            modes[block.degraded_mode] += 1
        for verdict in verification.verdicts:
            if verdict.v2 is None:
                continue
            tiers[str(verdict.v2.tier)] += 1
            outcomes[verdict.v2.outcome] += 1
            if verdict.v2.mode != expected_mode or verdict.v2.rule != table[verdict.v2.mode][verdict.v2.tier]:
                contradictions.append(f"{name}: a claim in {verdict.v2.mode} under {verdict.v2.rule}")
            if verdict.v3 is not None and verdict.v3.escalation == "X2":
                x2 += 1
        calls += block.calls
        cost += block.cost_units
        per_response_cost.append(block.cost_units)
        if result.v1 is not None and result.v1.v2 is not None:
            latencies.setdefault("panel", []).append(result.v1.v2.latency_ms)
    calls_by_item = Counter()
    for request in gateway.captured:
        payload_fields.setdefault(request.item, set()).update(request.model_dump().keys())
        calls_by_item[request.item] += 1
    latencies.setdefault("gateway_call", []).extend(value for values in GATEWAY_METRICS.latency.values() for value in values)
    responses = len(items)
    block = {"name": name, "down": sorted(down), "responses": responses, "f1": {"complete": complete, "rate": f"{complete}/{responses}"},
             "modes": {mode: modes.get(mode, 0) for mode in ("FULL", "REDUCED-2", "REDUCED-1", "ZERO")},
             "finals": {final: finals.get(final, 0) for final in ("deliver", "withhold", "abstain")},
             "tiers": {tier: tiers.get(tier, 0) for tier in ("1", "2", "3")},
             "outcomes": {outcome: outcomes.get(outcome, 0) for outcome in ("pass", "fail", "withheld")}, "x2": x2, "calls": calls,
             "calls_by_item": {item: calls_by_item.get(item, 0) for item in ("claim", "alignment")},
             "cost_units": {"total": cost, "per_response_mean": round(cost / responses, 3) if responses else 0.0},
             "v2_after_v1_fail": after_fail, "deliver_without_pass": without_pass}
    return block, contradictions, gateway, cache


def compute(*, items: list[str] | None = None, commit_source=None) -> dict:
    from app.gateway.metrics import GATEWAY_METRICS
    from app.services.v2_panel.rules import ROUTING_TABLES

    items = queries() if items is None else list(items)
    payload_fields: dict[str, set] = {}
    latencies: dict[str, list] = {}
    scenarios, problems = [], []
    GATEWAY_METRICS.reset()
    with tempfile.TemporaryDirectory(prefix="qcai-v2-fixtures-") as temp:
        env = Environment(Path(temp))
        try:
            package = get_config_package(env.settings(()))
            table = ROUTING_TABLES[package.v2.routing_table_version]
            all_up = None
            for name, down, mode in SCENARIOS:
                block, contradictions, gateway, cache = _scenario(env, name, down, mode, items, payload_fields, latencies, table)
                scenarios.append(block)
                problems.extend(contradictions[:5])
                if name == "all_up":
                    all_up = (gateway, cache, block["calls"])
            gateway, cache, first_calls = all_up
            before = cache.snapshot()
            again, contradictions, _, _ = _scenario(env, "cache_pass", (), "FULL", items, payload_fields, latencies, table, gateway=gateway, cache=cache)
            after = cache.snapshot()
            problems.extend(contradictions[:5])
            from app.services.ledger import verify_response_ledger

            with env.sessions() as db:
                chain = verify_response_ledger(db)
            if not chain.ok:
                problems.append("the fixture ledger chain does not verify")
        finally:
            env.close()
    cache_pass = {"claim_plan_hits": after["claim_plan"]["hits"] - before["claim_plan"]["hits"],
                  "verdict_hits": after["verdict"]["hits"] - before["verdict"]["hits"],
                  # Claim items that missed the cache, and alignment items (never cached: they judge rendered text).
                  "verdict_calls": again["calls_by_item"]["claim"], "alignment_calls": again["calls_by_item"]["alignment"],
                  "first_pass_calls": first_calls, "f1": again["f1"]}
    for block in scenarios + [dict(again, name="cache_pass")]:
        if block["f1"]["complete"] != block["responses"]:
            problems.append(f"{block['name']}: F-1 {block['f1']['rate']}")
        if block["v2_after_v1_fail"] or block["deliver_without_pass"]:
            problems.append(f"{block['name']}: {block['v2_after_v1_fail']} V2 verdicts after a V1 fail, "
                            f"{block['deliver_without_pass']} deliveries without a passing vote")
    report = {
        "report": "qcai-v2-fixture-report", "format_version": 1, "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "commit": (commit_source or _commit)(), "evidence_class": EVIDENCE_CLASS, "public_corpus_only": True,
        "config_package": {"version": package.package_version, "sha256": package.sha256},
        "queries": {"path": QUERIES_PATH.relative_to(REPO_ROOT).as_posix(), "count": len(items)},
        "scenarios": scenarios, "cache_pass": cache_pass,
        "voting_table_sha256": canonical_sha256({mode: {str(tier): rule for tier, rule in row.items()} for mode, row in table.items()}),
        "payload_fields": {item: sorted(fields) for item, fields in sorted(payload_fields.items())},
        "latency": {"p95_ms": {name: nearest_rank_p95(values) for name, values in sorted(latencies.items())}},
    }
    report["result"], report["problems"] = _result(report, problems)
    report["inputs"] = run_inputs()
    return report


def _result(report: dict, problems: list[str]) -> tuple[str, list[str]]:
    breach = any(block["v2_after_v1_fail"] or block["deliver_without_pass"] for block in report["scenarios"])
    if breach:
        return "breach", problems
    if problems:
        return "stop", problems
    return "pass", []


def exit_code(report: dict) -> int:
    return {"pass": 0, "stop": EXIT_STOP, "breach": EXIT_BREACH}[report["result"]]


def _strip_volatile(value):
    if isinstance(value, dict):
        return {key: _strip_volatile(item) for key, item in value.items() if key not in {"created_at", "commit", "latency"}}
    if isinstance(value, list):
        return [_strip_volatile(item) for item in value]
    return value


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, timeout=30)


def _commit() -> str:
    try:
        head = _git("rev-parse", "HEAD").stdout.strip()
        if not head:
            return "unknown"
        status = _git("status", "--porcelain")
        return head + ("-dirty" if status.returncode != 0 or status.stdout.strip() else "")
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", type=Path)
    mode.add_argument("--check", type=Path)
    parser.add_argument("--allow-dirty", action="store_true", help="--write from a working tree that differs from HEAD")
    args = parser.parse_args(argv)
    import logging

    # The degraded scenarios log tutor.v2.degraded per response by design; the report counts them instead.
    logging.getLogger("qcai").setLevel(logging.ERROR)
    target = args.write or args.check
    _refuse_lqs(target)
    if args.write and not args.allow_dirty and _commit().endswith("-dirty"):
        print("refused: the working tree differs from HEAD; commit first, or pass --allow-dirty", file=sys.stderr)
        return EXIT_DIRTY
    fresh = compute()
    if args.write:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        args.write.write_text(json.dumps(fresh, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {args.write}: result {fresh['result']}")
    else:
        committed = json.loads(args.check.read_text(encoding="utf-8"))
        if _strip_volatile(committed) != _strip_volatile(fresh):
            differing = sorted(key for key in set(committed) | set(fresh)
                               if key not in {"created_at", "commit", "latency"} and _strip_volatile(committed.get(key)) != _strip_volatile(fresh.get(key)))
            print(f"V2 fixture check failed: the record differs from a fresh run in: {', '.join(differing)}", file=sys.stderr)
            return EXIT_DRIFT
        print(f"V2 fixture record is current: result {fresh['result']}")
    for block in fresh["scenarios"]:
        print(f"  {block['name']}: F-1 {block['f1']['rate']}; modes {block['modes']}; finals {block['finals']}; calls {block['calls']}")
    print(f"  cache pass: {fresh['cache_pass']}; {EVIDENCE_CLASS}")
    for problem in fresh["problems"]:
        print(f"  {problem}", file=sys.stderr)
    return exit_code(fresh)


if __name__ == "__main__":
    sys.exit(main())
