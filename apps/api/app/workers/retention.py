"""One retention pass for a scheduled job (plan Action 22).

Runs every retention rule once, logs one JSON line with the rows deleted per table, and exits.
A failure logs the error and exits with status 1, so the scheduler records a failed run instead
of a silent one. Run as: python -m app.workers.retention
"""

import json
import sys
import time

from app.core.db import SessionLocal
from app.services.retention import run_retention_cleanup
from app.workers.common import LOGGER


def main() -> int:
    started = time.monotonic()
    try:
        with SessionLocal() as db:
            counts = run_retention_cleanup(db)
    except Exception:
        LOGGER.exception(json.dumps({"job": "retention", "status": "failed"}))
        return 1
    LOGGER.info(
        json.dumps(
            {
                "job": "retention",
                "status": "ok",
                "deleted": counts,
                "duration_ms": round((time.monotonic() - started) * 1000),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
