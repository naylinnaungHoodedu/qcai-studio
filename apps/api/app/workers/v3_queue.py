"""The V3 queue's operator commands (plan Phase 6 F "runbook", I; Phase 6 spec 4.15; infra/cloudrun/deployment.md, Phase 6).

In-image; it connects as the API does (the Cloud SQL Python connector when CLOUD_SQL_CONNECTION_NAME is set) and logs
JSON lines on the qcai.worker logger (counts, seq numbers and hashes only).
  scan [--limit N] [--until-done]       one scan (or scans until the ledger is read); refused while V3_QUEUE is off
  status                                v3.status with the SLIs (metrics.slis) and the stop
  verify-gold [--expect-head SEQ:HASH]  walks the gold chain; v3.gold_verified with the count, the head and the problems
  export-gold --path P [--all]          the applied items' final gold rows (every row with --all) as JSON lines, to a
                                        path outside the application tree: the archive before a downgrade and the
                                        recalibration input Phase 7 consumes (DI-93)
Exit codes: 0 ok, 1 a check failed (a gold chain problem), 2 a usage error or a refusal (V3 off, an export path inside the
application tree). Run as: python -m app.workers.v3_queue <command> ...
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
import sys

from app.core.config import get_settings
from app.core.config_package import get_config_package
from app.core.db import SessionLocal
from app.core.structured_logging import FIELDS
from app.services import v3
from app.workers.common import LOGGER

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    scan = commands.add_parser("scan")
    scan.add_argument("--limit", type=int, default=500)
    scan.add_argument("--until-done", action="store_true")
    commands.add_parser("status")
    verify = commands.add_parser("verify-gold")
    verify.add_argument("--expect-head", default=None)
    export = commands.add_parser("export-gold")
    export.add_argument("--path", type=Path, required=True)
    export.add_argument("--all", action="store_true")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return EXIT_USAGE
    settings = get_settings()
    package = get_config_package(settings)
    if args.command == "scan":
        from app.services.v3.scan import run_scan, scan_until_done

        if not 1 <= args.limit <= 10_000:
            return EXIT_USAGE
        try:
            results = (scan_until_done(settings=settings, package=package, limit=args.limit) if args.until_done
                       else [run_scan(settings=settings, package=package, limit=args.limit)])
        except v3.V3Off:
            LOGGER.warning("V3 scan refused: V3_QUEUE is off", extra={FIELDS: {"event": "v3.scan_refused", "reason": "v3_off"}})
            return EXIT_USAGE
        LOGGER.info("V3 scan finished", extra={FIELDS: {"event": "v3.scan_finished", "scans": len(results), "last": asdict(results[-1])}})
        return EXIT_OK
    if args.command == "status":
        from app.services.v3.metrics import slis

        if package.v3 is None:
            return EXIT_USAGE
        with SessionLocal() as db:
            body = slis(db, package, now=datetime.now(UTC))
        LOGGER.info("V3 status", extra={FIELDS: {"event": "v3.status", "mode": v3.mode(settings, package), **body}})
        return EXIT_OK
    if args.command == "verify-gold":
        from app.services.ledger import parse_head
        from app.services.v3.gold import verify_gold_store

        try:
            expected = parse_head(args.expect_head)
        except ValueError:
            return EXIT_USAGE
        with SessionLocal() as db:
            check = verify_gold_store(db, expected_head=expected)
        LOGGER.info("V3 gold store verified", extra={FIELDS: {"event": "v3.gold_verified", "count": check.count, "head_seq": check.head_seq,
                                                               "head_hash": check.head_hash, "problem_count": len(check.problems),
                                                               "problems": list(check.problems)}})
        return EXIT_OK if check.ok else EXIT_FAILED
    from app.services.v3.gold import export_gold

    try:
        with SessionLocal() as db:
            count = export_gold(db, args.path, applied_only=not args.all)
    except ValueError:
        LOGGER.warning("V3 gold export refused: the path lies inside the application tree", extra={FIELDS: {"event": "v3.gold_export_refused"}})
        return EXIT_USAGE
    LOGGER.info("V3 gold rows exported", extra={FIELDS: {"event": "v3.gold_exported", "count": count, "applied_only": not args.all}})
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
