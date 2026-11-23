"""The V3 residual report: the seeded audit draw, adjudication and the Wilson bound on synthetic deliveries (plan Phase 6 F
"residual report", D task 4 "Wilson residual bounds", AC-6-2, AC-6-5; Phase 6 spec 12.1).

Run: python scripts/run_v3_residual_report.py --write docs/evaluation/phase6/v3_residual_report_v1.json [--allow-dirty]
     python scripts/run_v3_residual_report.py --check docs/evaluation/phase6/v3_residual_report_v1.json

Synthetic telemetry, not research results (plan Phase 6 H: "audit counts are telemetry, not research results"); HR-3's
study form is Phase 10's. Public corpus only (anything under lqs/ is refused). The script:
  1. builds the template delivery: the legacy ledger entry of QAEngine.ask on in-domain fixture query 0
     (apps/api/tests/data/score_floor_queries.json) under the public-payload capture's configuration b (ENVIRONMENT=production,
     governance on, a temporary manifest approving every public-plane, bound item: the p1-floor gate), and asserts it is an
     answer that records its gate score, is not X4-marked under the package's margins and cites only spans a reviewer is
     shown (exit 3 otherwise);
  2. appends 6070 copies to its own in-memory SQLite ledger, differing only in response_id turn-{UUID(int=i)}, i = 1..6070,
     delivered at 2026-11-01T00:00:00Z plus i seconds;
  3. scans until done with V3_QUEUE=shadow in development (each delivery considered once at 1/20: 300 X6 draws, and no X5
     window), and replays the draw over the same ids (identical);
  4. adjudicates every X6 item as synthetic-reviewer-a with every claim SUPPORTED, gives each double-review item its round 2
     by synthetic-reviewer-b with the same labels, and applies every item as synthetic-reviewer-c (actions at
     2026-11-20T00:00:00Z plus n seconds);
  5. verifies the gold chain and the response ledger, and that every ledger row (seq, entry_sha256, record_hash) is
     unchanged by the adjudications;
and reports the Wilson 95% bound of 0 errors in 300 audited answer deliveries (below 0.013, AC-6-5), the 1/300 and 3/300
bounds, and whether the API's Wilson interval equals the evaluation harness's. `commit` is informational; `inputs` (the LF
sha256 of every imported repository module) is compared with the checkout; gold.head_record_hash covers keyed digests,
which depend on the guest-token secret, so it is informational while gold.verified is compared.

Exit codes: 0 pass; 1 drift (--check: the record differs from a fresh run, created_at, commit, inputs and
gold.head_record_hash aside, or its inputs differ from the checkout); 3 a stop (the template's assertions, the X6 count
outside its 99% interval, the bound not below 0.013, a replay that differs, an unequal harness, a gold or ledger check
that fails, or a changed ledger); 4 a dirty tree on --write.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from uuid import UUID

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
for path in (REPO_ROOT, API_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

QUERIES_PATH = API_ROOT / "tests" / "data" / "score_floor_queries.json"
REPO_MANIFEST = REPO_ROOT / "corpus" / "public" / "manifest.json"
DEFAULT_REPORT = REPO_ROOT / "docs" / "evaluation" / "phase6" / "v3_residual_report_v1.json"
EVIDENCE_CLASS = "synthetic telemetry, not research results (plan Phase 6 H: audit counts are telemetry, not research results)"
TEMPLATE = "the contained answer to in-domain fixture query 0 (capture configuration b; p1-floor; not X4-marked)"
DELIVERIES = 6070
INTERVAL_99 = (261, 348)
BELOW = "0.013"
DELIVERY_EPOCH = datetime(2026, 11, 1, tzinfo=UTC)
ACTION_EPOCH = datetime(2026, 11, 20, tzinfo=UTC)
REVIEWERS = ("synthetic-reviewer-a", "synthetic-reviewer-b", "synthetic-reviewer-c")
EXIT_DRIFT, EXIT_STOP, EXIT_DIRTY = 1, 3, 4
INPUTS_RULE = "imported-repository-modules-sha256-lf-v1"
INPUT_PREFIXES = ("apps/api/app/", "scripts/")
SELF = "scripts/run_v3_residual_report.py"
VOLATILE = ("created_at", "commit", "inputs")


class TemplateRefused(RuntimeError):
    pass


def _refuse_lqs(path: Path) -> None:
    if "lqs" in Path(path).resolve().parts:
        raise SystemExit("refused: ULQS paths are never fixtures (plan H)")


def text_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def run_inputs() -> dict:
    from app.core.config_package import canonical_sha256

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
    from app.core.config_package import canonical_sha256

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


def _query(index: int) -> str:
    return json.loads(QUERIES_PATH.read_text(encoding="utf-8"))["in_domain"][index]["query"]


def _template(temp: Path):
    """(template entry, store, corpus registry) under capture configuration b."""
    from app.core.config import Settings
    from app.core.config_package import get_config_package
    from app.core.corpus_governance import get_corpus_registry
    from app.core.manifest_v2 import with_all_public_approved
    from app.services.content_assembler import CourseStore
    from app.services.ledger import build_legacy_entry
    from app.services.qa_engine import QAEngine
    from app.services.retrieval_engine import RetrievalEngine
    from app.services.v3.queue import span_shown
    from app.services.v3.triggers import x4_fires

    manifest = temp / "manifest.json"
    manifest.write_text(json.dumps(with_all_public_approved(json.loads(REPO_MANIFEST.read_text(encoding="utf-8")))), encoding="utf-8")
    settings = Settings(environment="production", enforce_corpus_governance=True, allowed_origins=["https://qantumlearn.academy"],
                        corpus_manifest_path=str(manifest))
    package = get_config_package(settings)
    store = CourseStore(settings)
    registry = get_corpus_registry(settings)
    response = QAEngine(RetrievalEngine(store, settings), settings).ask(_query(0))
    delivery = getattr(response, "_ledger", None)
    if delivery is None or not hasattr(delivery, "claims"):
        raise TemplateRefused("query 0 gave no legacy delivery")
    entry = build_legacy_entry(delivery, settings=settings, package=package, manifest_sha256=registry.manifest_sha256)
    sufficiency = entry.retrieval.sufficiency
    if entry.decision != "answer" or not entry.claims:
        raise TemplateRefused("the template is not an answer")
    if sufficiency is None or sufficiency.score is None or sufficiency.gate != "p1-floor":
        raise TemplateRefused("the template does not record its p1-floor gate score")
    if x4_fires(entry, x4_margin=package.v1.x4_margin):
        raise TemplateRefused("the template is X4-marked")
    if not all(span_shown(span_id, store=store, corpus_registry=registry)[0] for claim in entry.claims for span_id in claim.span_ids):
        raise TemplateRefused("the template cites a span a reviewer is not shown")
    return entry, store, registry


def _copy(template, index: int):
    from app.services.tutor_pipeline.contracts import LedgerEntry

    response_id = f"turn-{UUID(int=index)}"
    data = template.model_dump(mode="json")
    data["response_id"] = response_id
    for claim in data["claims"]:
        claim["response_id"] = response_id
    return LedgerEntry.model_validate(data)


def _ledger_rows(db) -> list:
    from sqlalchemy import select

    from app.db_models import ResponseLedgerRecord

    return [tuple(row) for row in db.execute(select(ResponseLedgerRecord.seq, ResponseLedgerRecord.entry_sha256, ResponseLedgerRecord.record_hash)
                                              .order_by(ResponseLedgerRecord.seq))]


def run(*, commit_source=None) -> dict:
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.core.config import Settings
    from app.core.config_package import get_config_package
    from app.core.db import Base
    from app.core.schema_upgrades import run_schema_upgrades
    from app.db_models import ResponseLedgerRecord, V3Draw, V3QueueItem
    from app.services.citation_migration import wilson_interval
    from app.services.ledger import append_ledger_entry, verify_response_ledger
    from app.services.v3 import queue
    from app.services.v3.contracts import AdjudicationRequest, ApplyRequest, ClaimLabel
    from app.services.v3.draw import draw_trigger
    from app.services.v3.gold import verify_gold_store
    from app.services.v3.residual import residual, wilson_upper
    from app.services.v3.scan import scan_until_done
    from evaluation.qcai_eval.statistics import wilson_interval as harness_wilson

    problems: list[str] = []
    settings = Settings(environment="development", v3_queue="shadow")
    package = get_config_package(settings)
    params = package.v3
    database = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    clock = {"n": 0}

    def tick() -> datetime:
        clock["n"] += 1
        return ACTION_EPOCH + timedelta(seconds=clock["n"])

    try:
        Base.metadata.create_all(database)
        run_schema_upgrades(database)
        factory = sessionmaker(bind=database, autoflush=False, expire_on_commit=False)
        with tempfile.TemporaryDirectory(prefix="qcai-v3-residual-") as temp:
            template, store, corpus = _template(Path(temp))
        for index in range(1, DELIVERIES + 1):
            append_ledger_entry(_copy(template, index), session_factory=factory, budget_ms=60000, attempts=3,
                                now=DELIVERY_EPOCH + timedelta(seconds=index))
        scan_until_done(settings=settings, package=package, session_factory=factory, now=ACTION_EPOCH, limit=1000)
        with factory() as db:
            considered = len(db.execute(select(V3Draw.ledger_seq)).all())
            drawn_rows = db.execute(select(ResponseLedgerRecord.response_id, V3Draw.drawn).join(V3Draw, V3Draw.ledger_seq == ResponseLedgerRecord.seq)
                                    .where(V3Draw.drawn.is_not(None))).all()
            before = _ledger_rows(db)
        x6_ids = sorted(response_id for response_id, drawn in drawn_rows if drawn == "X6")
        x5_count = sum(1 for _, drawn in drawn_rows if drawn == "X5")
        replay = sorted(f"turn-{UUID(int=index)}" for index in range(1, DELIVERIES + 1)
                        if draw_trigger(params.draw_seed, f"turn-{UUID(int=index)}", base=params.draw_rate, elevated=params.x5_rate, x5_active=False) == "X6")
        replay_identical = replay == x6_ids
        labels = tuple(ClaimLabel(claim_id=claim.claim_id, verdict="SUPPORTED") for claim in sorted(template.claims, key=lambda claim: claim.claim_id))
        selected = pairs = agreeing = applied = 0
        with factory() as db:
            items = db.execute(select(V3QueueItem.item_id, V3QueueItem.triggers, V3QueueItem.double_review).order_by(V3QueueItem.item_id)).all()
        audit_items = [row for row in items if "X6" in queue.split(row.triggers)]
        for row in audit_items:
            with factory() as db:
                queue.claim_item(db, row.item_id, user_id=REVIEWERS[0], now=tick(), package=package, store=store, corpus_registry=corpus)
                result = queue.adjudicate(db, row.item_id, AdjudicationRequest(client_key=f"round1-{row.item_id[4:20]}", claim_labels=labels),
                                          user_id=REVIEWERS[0], now=tick(), package=package, store=store, corpus_registry=corpus)
            if row.double_review:
                selected += 1
                with factory() as db:
                    queue.claim_item(db, row.item_id, user_id=REVIEWERS[1], now=tick(), package=package, store=store, corpus_registry=corpus)
                    second = queue.adjudicate(db, row.item_id, AdjudicationRequest(client_key=f"round2-{row.item_id[4:20]}", claim_labels=labels),
                                              user_id=REVIEWERS[1], now=tick(), package=package, store=store, corpus_registry=corpus)
                pairs += 1
                agreeing += int(second.state == "adjudicated")
            elif result.state != "adjudicated":
                problems.append(f"{row.item_id} did not close after round 1")
            with factory() as db:
                queue.apply_item(db, row.item_id, ApplyRequest(client_key=f"apply-{row.item_id[4:20]}"), user_id=REVIEWERS[2], now=tick())
            applied += 1
        with factory() as db:
            gold = verify_gold_store(db)
            ledger_check = verify_response_ledger(db)
            after = _ledger_rows(db)
            bound = residual(db, package)
    finally:
        database.dispose()
    harness_equal = all(wilson_interval(errors, 300)["upper"] == harness_wilson(errors, 300)["upper"]
                        and wilson_interval(errors, 300)["lower"] == harness_wilson(errors, 300)["lower"] for errors in (0, 1, 3))
    upper = bound["wilson95"]["upper"]
    residual_pass = bound["audited"] == len(x6_ids) and bound["errors"] == 0 and upper < float(BELOW)
    x6 = len(x6_ids)
    if not INTERVAL_99[0] <= x6 <= INTERVAL_99[1]:
        problems.append(f"{x6} X6 draws lie outside the 99% interval {INTERVAL_99}")
    if considered != DELIVERIES or x5_count:
        problems.append(f"the scan considered {considered} deliveries and drew {x5_count} X5")
    if not replay_identical:
        problems.append("a same-seed replay drew other ids")
    if not residual_pass:
        problems.append(f"the residual bound {upper} is not below {BELOW} over the audited answers")
    if not harness_equal:
        problems.append("the API's Wilson interval differs from the evaluation harness's")
    if not gold.ok or not ledger_check.ok:
        problems.append("the gold chain or the response ledger does not verify")
    if before != after:
        problems.append("a ledger row changed during the adjudications")
    report = {
        "report": "qcai-v3-residual-report", "format_version": 1, "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "commit": (commit_source or _commit)(), "evidence_class": EVIDENCE_CLASS, "public_corpus_only": True,
        "config_package": {"version": package.package_version, "sha256": package.sha256},
        "deliveries": {"count": DELIVERIES, "ids": f"turn-{{UUID(int=i)}}, i = 1..{DELIVERIES}", "template": TEMPLATE},
        "draw": {"rule": params.draw_rule, "seed": params.draw_seed, "rate": f"{params.draw_rate.numerator}/{params.draw_rate.denominator}",
                 "considered": considered, "x6": x6, "x5": x5_count, "interval_99": list(INTERVAL_99), "replay_identical": replay_identical,
                 "drawn_ids_sha256": hashlib.sha256("\n".join(x6_ids).encode("utf-8")).hexdigest()},
        "adjudication": {"audited": len(audit_items), "double_review": {"selected": selected, "pairs": pairs, "agreeing": agreeing},
                         "applied": applied, "reviewers": len(REVIEWERS)},
        "residual": {"audited_answers": bound["audited"], "errors": bound["errors"], "wilson95": bound["wilson95"], "by_month": bound["by_month"],
                     "below": BELOW, "pass": residual_pass},
        "bounds": [{"errors": errors, "audited": 300, "upper": wilson_upper(errors, 300)} for errors in (0, 1, 3)],
        "harness_equal": harness_equal,
        "gold": {"rows": gold.count, "verified": gold.ok, "head_seq": gold.head_seq or 0, "head_record_hash": gold.head_hash},
        "ledger_unchanged": before == after and ledger_check.ok,
    }
    report["result"] = "stop" if problems else "pass"
    report["problems"] = problems
    report["inputs"] = run_inputs()
    return report


def exit_code(report: dict) -> int:
    return 0 if report["result"] == "pass" else EXIT_STOP


def comparable(report: dict) -> dict:
    value = {key: item for key, item in report.items() if key not in VOLATILE}
    if isinstance(value.get("gold"), dict):
        value["gold"] = {key: item for key, item in value["gold"].items() if key != "head_record_hash"}
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

    # The scan, the ledger and the workflow log per record and per action by design; the report counts them instead.
    for name in ("qcai.tutor", "qcai.v3", "qcai"):
        logging.getLogger(name).setLevel(logging.WARNING)
    target = args.write or args.check
    _refuse_lqs(target)
    if args.write and not args.allow_dirty and _commit().endswith("-dirty"):
        print("refused: the working tree differs from HEAD; commit first, or pass --allow-dirty", file=sys.stderr)
        return EXIT_DIRTY
    try:
        fresh = run()
    except TemplateRefused as exc:
        print(f"V3 residual report stopped: {exc}", file=sys.stderr)
        return EXIT_STOP
    if args.write:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        args.write.write_text(json.dumps(fresh, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {args.write}: result {fresh['result']}")
    else:
        committed = json.loads(args.check.read_text(encoding="utf-8"))
        drift = input_problems(committed.get("inputs") or {})
        if comparable(committed) != comparable(fresh):
            differing = sorted(key for key in set(committed) | set(fresh)
                               if key not in VOLATILE and comparable(committed).get(key) != comparable(fresh).get(key))
            drift.append(f"the record differs from a fresh run in: {', '.join(differing)}")
        if drift:
            for problem in drift:
                print(f"V3 residual check failed: {problem}", file=sys.stderr)
            return EXIT_DRIFT
        print(f"V3 residual record is current: result {fresh['result']}")
    print(f"  draw: {fresh['draw']['x6']} X6 of {fresh['draw']['considered']}; residual upper {fresh['residual']['wilson95']['upper']}; "
          f"{fresh['gold']['rows']} gold rows; {EVIDENCE_CLASS}")
    for problem in fresh["problems"]:
        print(f"  {problem}", file=sys.stderr)
    return exit_code(fresh)


if __name__ == "__main__":
    sys.exit(main())
