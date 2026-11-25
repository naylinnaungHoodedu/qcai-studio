"""Inspect and change the shared planner stop using the API database configuration."""

import argparse
import json
import sys

from sqlalchemy.exc import SQLAlchemyError

from app.core.db import SessionLocal
from app.db_models import LearnerAdaptationStop
from app.services.learner_record_shadow import STOP_REASONS, change_adaptation_stop


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("status", help="read the current stop")
    stop = commands.add_parser("stop", help="hold the planner on the static order")
    stop.add_argument("--reason", choices=STOP_REASONS, required=True)
    clear = commands.add_parser("clear", help="clear the stop after investigation")
    clear.add_argument("--confirm", action="store_true", required=True)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code

    try:
        if args.action == "status":
            with SessionLocal() as db:
                row = db.get(LearnerAdaptationStop, "planner")
                result = {"state": "stopped", "reason": row.reason} if row else {"state": "clear"}
        else:
            reason = args.reason if args.action == "stop" else None
            change_adaptation_stop(SessionLocal, reason)
            result = {"action": args.action, "outcome": "committed"}
    except (SQLAlchemyError, RuntimeError):
        print("Planner stop command failed. Verify the Phase 8 schema and database access.", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
