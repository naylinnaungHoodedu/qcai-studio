"""The legacy citation migration job (plan Phase 2 task 2.3 and G; Phase 2 spec 2.7, 3.8).

Run: python -m app.workers.migrate_citations [--dry-run | --apply | --downgrade] [--report PATH]
     [--tables qa_interactions,tutor_turns] [--batch-size 500]

--dry-run (the default) writes nothing. --apply migrates citations whose normalised excerpt hash matches exactly
one span and labels the rest legacy_unresolved; --downgrade restores every migrated or labelled citation from its
legacy_original. The report (counts only) is printed and, with --report, written as JSON; it is compared with the
provisional D-30 rule from the configuration package. Exit 0 pass, 3 stop condition, 2 usage error, 1 other error.
In production every mode except --dry-run is a database write that needs Platform Owner approval (D-05).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

from app.core.config import get_settings
from app.core.config_package import get_config_package
from app.core.corpus_governance import get_corpus_registry
from app.core.db import SessionLocal
from app.core.structured_logging import FIELDS
from app.services.citation_migration import EXIT_ERROR, EXIT_PASS, EXIT_STOP, EXIT_USAGE, TABLES, migrate
from app.services.spans import build_identity_registry
from app.workers.common import LOGGER


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):  # usage errors exit 2, never 1
        self.print_usage(sys.stderr)
        print(f"usage error: {message}", file=sys.stderr)
        raise SystemExit(EXIT_USAGE)


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_const", const="dry-run", dest="mode")
    mode.add_argument("--apply", action="store_const", const="apply", dest="mode")
    mode.add_argument("--downgrade", action="store_const", const="downgrade", dest="mode")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--tables", default="qa_interactions,tutor_turns")
    parser.add_argument("--batch-size", type=int, default=500)
    args = parser.parse_args(argv)
    tables = [name.strip() for name in args.tables.split(",") if name.strip()]
    if not tables or any(name not in TABLES for name in tables) or args.batch_size < 1:
        print("usage error: --tables takes qa_interactions and/or tutor_turns; --batch-size must be >= 1", file=sys.stderr)
        return EXIT_USAGE
    started = time.monotonic()
    selected = args.mode or "dry-run"
    try:
        settings = get_settings()
        package = get_config_package(settings)
        memory, _ = build_identity_registry(settings, include_unapproved=True)
        report = migrate(
            SessionLocal,
            mode=selected,
            memory=memory,
            settings=settings,
            package=package,
            corpus_version=get_corpus_registry(settings).corpus_version,
            tables=tables,
            batch_size=args.batch_size,
        )
    except Exception:
        LOGGER.exception("Citation migration failed", extra={FIELDS: {"job": "migrate_citations", "status": "failed", "mode": selected}})
        return EXIT_ERROR
    text = json.dumps(report, indent=2, sort_keys=False)
    if args.report:
        args.report.write_text(text + "\n", encoding="utf-8", newline="\n")
    print(text)
    result = report["threshold"]["result"]
    LOGGER.info(
        "Citation migration finished",
        extra={
            FIELDS: {
                "job": "migrate_citations",
                "status": "ok" if result == "pass" else "stop",
                "mode": selected,
                "migrated": report["totals"]["migrated"],
                "legacy_unresolved": report["totals"]["legacy_unresolved"],
                "duration_ms": round((time.monotonic() - started) * 1000),
            }
        },
    )
    return EXIT_PASS if result == "pass" else EXIT_STOP


if __name__ == "__main__":
    sys.exit(main())
