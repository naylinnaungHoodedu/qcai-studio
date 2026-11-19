"""Register span identity in corpus_spans (plan Phase 2 task 2.2; Phase 2 spec 4.22).

Run: python -m app.workers.register_spans [--dry-run | --apply]

Builds the text-free identity of the authored item and every public-plane, bound document present on disk
(approved or not: legacy citation matching needs them; nothing serves them) and, with --apply, inserts the spans
not yet stored. --dry-run (the default) only counts. Logs one JSON line; exit 1 on failure. This is the explicit
alternative to a start-up write: API start-up never writes span rows. In production --apply is a database write
that needs Platform Owner approval (D-05).
"""

from __future__ import annotations

import argparse
import sys
import time

from app.core.config import get_settings
from app.core.corpus_governance import get_corpus_registry
from app.core.db import SessionLocal
from app.core.structured_logging import FIELDS
from app.services.span_store import persist_spans
from app.services.spans import build_identity_registry
from app.workers.common import LOGGER


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    started = time.monotonic()
    try:
        settings = get_settings()
        registry, items = build_identity_registry(settings, include_unapproved=True)
        inserted = 0
        if args.apply:
            with SessionLocal() as db:
                inserted = persist_spans(
                    db, registry.records, corpus_version=get_corpus_registry(settings).corpus_version, registered_by="register-job"
                )
                db.commit()
    except Exception:
        LOGGER.exception("Span registration failed", extra={FIELDS: {"job": "register_spans", "status": "failed"}})
        return 1
    LOGGER.info(
        "Span registration finished",
        extra={
            FIELDS: {
                "job": "register_spans",
                "status": "ok",
                "mode": "apply" if args.apply else "dry-run",
                "items": len(items),
                "spans": len(registry),
                "inserted": inserted,
                "duration_ms": round((time.monotonic() - started) * 1000),
            }
        },
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
