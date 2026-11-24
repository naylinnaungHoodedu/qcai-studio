"""The ranking operator commands (plan Phase 9 F, I, L; Phase 9 spec 4.10-4.13; infra/cloudrun/deployment.md, Phase 9).

In-image; it connects as the API does and logs JSON lines on the qcai.worker logger (counts, ids, versions and hashes
only; never a learner identifier, a response id or text). Every command but status needs RANKING=shadow.
  scan [--limit N] [--until-done]        consume ledger records into the ranking event log (ranking.scan per batch)
  status                                 ranking.status with the mode and the SLIs (ranking.metrics.slis)
  replay --check                         replay the stored log twice; a mismatch appends `stop {replay_mismatch}`,
                                         logs ranking.stop and exits 1 (the plan L stop)
  commission ADAPTER                     the shadow golden regression over the recommission set; appends `commission`
                                         (refused for a model with outcomes); exit 1 when it does not pass
  recommission ADAPTER                   the same regression; appends recommission_pass (the cap lifts) or
                                         recommission_fail (exit 1)
  clear-stop --cause {fixed_code,fixed_data,restored_backup}
                                         refused unless two in-process replays are equal; rewrites ranking_states and
                                         ranking_incumbents from the replay, appends a checkpoint and clear_stop
Exit codes: 0 ok; 1 a stop, a failed check or a failed regression; 2 usage or a refusal (ranking off, stopped,
uncommissioned, an unknown adapter). Run as: python -m app.workers.ranking <command> ...
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import sys

from app.core.config import get_settings
from app.core.config_package import get_config_package
from app.core.db import SessionLocal
from app.core.structured_logging import FIELDS
from app.workers.common import LOGGER

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2


def _refused(reason: str, **fields) -> int:
    LOGGER.warning("Ranking command refused", extra={FIELDS: {"event": "ranking.scan_refused", "reason": reason, **fields}})
    return EXIT_USAGE


def replay_check(*, session_factory=SessionLocal, now: datetime | None = None) -> tuple[bool, dict]:
    """Replay the stored log twice; on a mismatch append the stop row. (ok, fields)."""
    from app.services.ranking.replay import check, load_log, replay, stopped
    from app.services.ranking.scan import EventLog
    from app.services.ranking.state import canonical, empty_state

    with session_factory() as db:
        rows, stored = load_log(db)
        first = check(db)
        second = replay(rows)
        again = replay(rows)
        same = canonical(second.state) == canonical(again.state) and second.derived == again.derived
        ok = first.ok and same
        fields = {"ok": ok, "state_sha256": first.state_sha256, "stored_sha256": first.stored_sha256,
                  "first_mismatch_seq": first.first_mismatch_seq, "reason": first.reason}
        if not ok and not stopped(db):
            log = EventLog(db, empty_state(), now=now or datetime.now(UTC))
            log.control("stop", {"reason": "replay_mismatch", "expected_sha256": first.stored_sha256, "actual_sha256": first.state_sha256})
            db.commit()
    return ok, fields


def clear_stop(cause: str, *, session_factory=SessionLocal, now: datetime | None = None) -> bool:
    from app.services.ranking.replay import load_log, replay
    from app.services.ranking.scan import EventLog, save_state
    from app.services.ranking.state import canonical, state_sha256

    with session_factory() as db:
        rows, _stored = load_log(db)
        first, second = replay(rows), replay(rows)
        if canonical(first.state) != canonical(second.state) or first.derived != second.derived:
            return False
        log = EventLog(db, first.state, now=now or datetime.now(UTC))
        seq = log.control("checkpoint", {"state_sha256": state_sha256(first.state), "last_input_seq": int(first.state["last_input_seq"])})
        save_state(db, first.state, event_seq=seq)
        log.control("clear_stop", {"cause": cause})
        db.commit()
    return True


def regression(adapter_id: str, *, settings, package):
    from app.services.ranking.models import candidates
    from app.services.ranking.recommission import regression_run

    known = {model.adapter_id: model for model in candidates(package, settings)}
    if adapter_id not in known:
        return None
    return regression_run(known[adapter_id], package=package)


def main(argv: list[str] | None = None, *, session_factory=SessionLocal, now: datetime | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    scan = commands.add_parser("scan")
    scan.add_argument("--limit", type=int, default=500)
    scan.add_argument("--until-done", action="store_true")
    commands.add_parser("status")
    replay = commands.add_parser("replay")
    replay.add_argument("--check", action="store_true", required=True)
    for name in ("commission", "recommission"):
        command = commands.add_parser(name)
        command.add_argument("adapter")
    clear = commands.add_parser("clear-stop")
    clear.add_argument("--cause", choices=("fixed_code", "fixed_data", "restored_backup"), required=True)
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return EXIT_USAGE
    from app.services import ranking

    settings = get_settings()
    package = get_config_package(settings)
    if args.command == "status":
        from app.services.ranking.metrics import slis

        with session_factory() as db:
            body = slis(db, package)
        LOGGER.info("Ranking status", extra={FIELDS: {"event": "ranking.status", "mode": ranking.mode(settings, package), **body}})
        return EXIT_OK
    if ranking.mode(settings, package) != "shadow":
        return _refused("ranking_off")
    now = now or datetime.now(UTC)
    if args.command == "scan":
        from app.services.ranking.scan import run_scan, scan_until_done

        try:
            if args.until_done:
                scan_until_done(settings=settings, package=package, session_factory=session_factory, now=now, limit=args.limit)
            else:
                result = run_scan(settings=settings, package=package, session_factory=session_factory, now=now, limit=args.limit)
                if result.refused == "stopped":
                    return EXIT_FAILED
        except ranking.RankingStopped:
            return _refused("stopped")
        except ranking.RankingUncommissioned:
            return _refused("uncommissioned")
        return EXIT_OK
    if args.command == "replay":
        ok, fields = replay_check(session_factory=session_factory, now=now)
        if not ok:
            LOGGER.error("The ranking replay does not match the stored log: the ranking is stopped",
                         extra={FIELDS: {"event": "ranking.stop", "reason": "replay_mismatch", "expected_sha256": fields["stored_sha256"],
                                         "actual_sha256": fields["state_sha256"]}})
            return EXIT_FAILED
        LOGGER.info("Ranking replay checked", extra={FIELDS: {"event": "ranking.replay_checked", **fields}})
        return EXIT_OK
    if args.command == "clear-stop":
        if not clear_stop(args.cause, session_factory=session_factory, now=now):
            return _refused("replays_differ")
        LOGGER.info("The ranking stop was cleared", extra={FIELDS: {"event": "ranking.stop_cleared", "cause": args.cause}})
        return EXIT_OK
    run = regression(args.adapter, settings=settings, package=package)
    if run is None:
        return _refused("unknown_adapter")
    from app.services.ranking.scan import append_inputs

    if args.command == "commission":
        payload = {"adapter_id": run.adapter_id, "version": run.version, "clean": run.clean, "failed": run.failed, "generated": run.generated,
                   "mean_q": run.mean_q, "run_sha256": run.run_sha256}
        kind = "commission"
    else:
        payload = {"adapter_id": run.adapter_id, "version": run.version, "clean": run.clean, "failed": run.failed, "generated": run.generated,
                   "run_sha256": run.run_sha256}
        kind = "recommission_pass" if run.passed else "recommission_fail"
    try:
        with session_factory() as db:
            append_inputs(db, [(kind, payload)], settings=settings, package=package, now=now)
            db.commit()
    except ranking.RankingStopped:
        return _refused("stopped")
    event = "ranking.commissioned" if args.command == "commission" else "ranking.recommissioned"
    LOGGER.info("Ranking regression recorded", extra={FIELDS: {"event": event, "adapter_id": run.adapter_id, "kind": kind, "clean": run.clean,
                                                               "failed": run.failed, "generated": run.generated, "passed": run.passed}})
    return EXIT_OK if run.passed else EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
