"""Verify the tutor response ledger (plan Phase 3 F: "ledger integrity script"; task 3.8; Phase 3 spec 7.16).

Run: python scripts/verify_ledger.py [--database-url URL] [--report PATH] [--expect-head SEQ:HASH]
                                     [--coverage-since ISO8601] [--coverage-horizon-s N] [--export PATH.jsonl]
                                     [--check-provenance]

Read-only. It walks the whole hash chain (gaps, broken links, edited entries or columns, non-canonical entries,
schema failures, a missing or mismatched head, a record past the head) and, with --expect-head, checks that the
chain still reaches a head logged earlier off the database (a forged head over a truncated tail). Appends that
commit while it runs are counted (appended_during_check), never reported as a break. --coverage-since reports
tutor turns created since then that have no ledger record (plan I "ledger writes 100% of deliveries"; report only):
unrecorded once older than --coverage-horizon-s (default ledger.attempt_horizon_s, 360 s), pending before that (an
append may still be running; spec 18.12 J5),
and counts the /qa/ask records since then (a qa- record holds no id of its Q&A row, so Q&A coverage is the
per-process legacy_by_surface.qa.coverage_rate SLI, not a join). --export writes every row as one JSON object per
line to a path outside the repository: the step before an Alembic downgrade. The restore that undoes the
downgrade's drop is the worker's --restore (spec 18.7 E12); this script stays read-only. --check-provenance compares
every record stamped with the shipped configuration package with that package's pins (ledger.ledger_provenance;
F-2's audit until a provider prompt exists, DI-49); a difference sets status provenance_mismatch.

The database URL comes from --database-url, else DATABASE_URL, and is never printed. This script builds a plain
engine from that URL (development, CI, a local copy). Against production, use the in-image worker
`python -m app.workers.response_ledger`, which has the same options and connects through the Cloud SQL connector
(infra/cloudrun/deployment.md, Phase 3). Both use app.services.ledger.ledger_coverage and export_ledger.
Exit codes: 0 ok, 1 the chain is broken or a provenance mismatch, 2 a usage or connection error.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
for path in (REPO_ROOT, API_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

_AMBIENT_URL = os.environ.get("DATABASE_URL")
# Importing the app must not create or touch a database file; this script builds its own engine.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.core.config import get_settings, normalize_sqlite_database_url  # noqa: E402
from app.core.config_package import get_config_package  # noqa: E402
from app.services.ledger import export_ledger, ledger_coverage, ledger_provenance, parse_head, verify_response_ledger  # noqa: E402

# The worker's implementations, under this script's earlier names.
coverage = ledger_coverage
export = export_ledger


def _inside_repository(path: Path) -> bool:
    try:
        path.resolve().relative_to(REPO_ROOT.resolve())
    except ValueError:
        return False
    return True


def _since(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--expect-head", default=None)
    parser.add_argument("--coverage-since", default=None)
    parser.add_argument("--coverage-horizon-s", type=int, default=None)
    parser.add_argument("--export", type=Path, default=None)
    parser.add_argument("--check-provenance", action="store_true")
    args = parser.parse_args(argv)
    url = args.database_url or _AMBIENT_URL
    if not url:
        print("verify_ledger: no database URL (pass --database-url or set DATABASE_URL)", file=sys.stderr)
        return 2
    if args.export is not None and _inside_repository(args.export):
        print("verify_ledger: --export must write outside the repository", file=sys.stderr)
        return 2
    try:
        expected = parse_head(args.expect_head)
        since = _since(args.coverage_since) if args.coverage_since else None
        if args.coverage_horizon_s is not None and args.coverage_horizon_s < 0:
            raise ValueError("--coverage-horizon-s takes a number of seconds, 0 or more")
    except ValueError as exc:
        print(f"verify_ledger: {exc}", file=sys.stderr)
        return 2
    engine = create_engine(normalize_sqlite_database_url(url))
    try:
        with sessionmaker(bind=engine)() as db:
            check = verify_response_ledger(db, expected_head=expected)
            report = {
                "report": "qcai-response-ledger-check",
                "format_version": 1,
                "checked_at": datetime.now(UTC).isoformat(),
                "status": "ok" if check.ok else "broken",
                "records": check.count,
                "first_seq": check.first_seq,
                "last_seq": check.last_seq,
                "head_hash": check.head_hash,
                "head_row": list(check.head_row) if check.head_row else None,
                "appended_during_check": check.appended_during_check,
                "expected_head": list(expected) if expected else None,
                "problems": list(check.problems),
            }
            if since is not None:
                report["coverage"] = ledger_coverage(db, since, horizon_s=args.coverage_horizon_s)
            if args.export is not None:
                report["exported"] = {"rows": export_ledger(db, args.export)}
            if args.check_provenance:
                settings = get_settings()   # a development clone record is accepted in development only (Phase 9 spec 4.12)
                report["provenance"] = ledger_provenance(db, get_config_package(settings), environment=settings.environment)
                if check.ok and report["provenance"]["problem_count"]:
                    report["status"] = "provenance_mismatch"
    except SQLAlchemyError as exc:
        print(f"verify_ledger: database error ({type(exc).__name__})", file=sys.stderr)
        return 2
    finally:
        engine.dispose()
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.report is not None:
        args.report.write_text(text + "\n", encoding="utf-8", newline="\n")
    print(text)
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
