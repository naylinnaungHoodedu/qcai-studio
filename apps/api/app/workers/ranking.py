"""The ranking operator commands (plan Phase 9 F, I, L; Phase 9 spec 4.10-4.13; infra/cloudrun/deployment.md, Phase 9).

In-image; it connects as the API does and logs JSON lines on the qcai.worker logger (counts, ids, versions and hashes
only; never a learner identifier, a response id or text). Every command but status needs RANKING=shadow.
  scan [--limit N] [--until-done]        consume ledger records into the ranking event log (ranking.scan per batch);
                                         exits 1 when a scan stops the ranking on a state mismatch (--until-done
                                         included)
  status                                 ranking.status with the mode and the SLIs (ranking.metrics.slis)
  replay --check                         under the ranking locks, replay the stored log twice; a mismatch appends
                                         `stop {replay_mismatch, mismatch, first_mismatch_seq}`, logs ranking.stop
                                         (with mismatch and first_mismatch_seq) on qcai.worker and exits 1 (the plan L
                                         stop)
  commission ADAPTER                     the shadow golden regression over the recommission set; appends `commission`;
                                         exit 1 when it does not pass; refused (exit 2, commission_refused, nothing
                                         appended) for a model with outcomes
  recommission ADAPTER                   the same regression; appends recommission_pass (the cap lifts) or
                                         recommission_fail (exit 1); refused (exit 2, recommission_refused) for another
                                         version than the model's
  clear-stop --cause {fixed_code,fixed_data,restored_backup}
                                         under the ranking locks; refused (exit 2) unless the hash chain, every stored
                                         derived event and every stored checkpoint match the replay and two replays
                                         are equal, so only a stored-state mismatch is cleared; rewrites
                                         ranking_states and ranking_incumbents from the replay, appends a checkpoint
                                         and clear_stop (deployment.md, Phase 9, for the other mismatches)
Exit codes: 0 ok; 1 a stop, a failed check or a failed regression; 2 usage or a refusal (ranking off, stopped,
uncommissioned, an unknown adapter, a refused commission or recommission, an unreadable recommission set). Run as: python -m app.workers.ranking <command> ...
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
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
    """Replay the stored log twice, under the ranking locks (so no scan appends between the reads or forks the chain); on a
    mismatch append the stop row. (ok, fields)."""
    from app.services.ranking.replay import compare, load_log, replay, stopped
    from app.services.ranking.scan import EventLog, take_locks
    from app.services.ranking.state import canonical, empty_state

    with session_factory() as db:
        take_locks(db)
        rows, stored = load_log(db)
        first = compare(rows, stored)
        second = replay(rows)
        again = replay(rows)
        same = canonical(second.state) == canonical(again.state) and second.derived == again.derived
        ok = first.ok and same
        fields = {"ok": ok, "state_sha256": first.state_sha256, "stored_sha256": first.stored_sha256,
                  "first_mismatch_seq": first.first_mismatch_seq, "reason": first.reason, "mismatch": None}
        if not ok:
            # What mismatched (deployment.md, Phase 9, "The stop"): state, chain, derived, checkpoint, input:<error>, or
            # replays_differ when the log replays cleanly but two replays differ.
            fields["mismatch"] = first.reason if not first.ok else "replays_differ"
        if not ok and not stopped(db):
            log = EventLog(db, empty_state(), now=now or datetime.now(UTC))
            log.control("stop", {"reason": "replay_mismatch", "mismatch": fields["mismatch"], "first_mismatch_seq": first.first_mismatch_seq,
                                 "expected_sha256": first.stored_sha256, "actual_sha256": first.state_sha256})
            db.commit()
    return ok, fields


@dataclass(frozen=True)
class Cleared:
    ok: bool
    reason: str | None = None      # why it was refused: chain, derived, checkpoint, input:<error> or replays_differ

    def __bool__(self) -> bool:
        return self.ok


def clear_stop(cause: str, *, session_factory=SessionLocal, now: datetime | None = None) -> Cleared:
    """Resync the stored state from the replay and clear the stop, under the ranking locks. Refused unless the log itself
    replays cleanly (compare() without the stored state: the chain, every stored derived event, every checkpoint) and two
    replays are equal: ranking_events is append-only, so any other mismatch would stop the ranking again at the next
    replay --check."""
    from app.services.ranking.replay import compare, load_log, replay
    from app.services.ranking.scan import EventLog, save_state, take_locks
    from app.services.ranking.state import canonical, state_sha256

    with session_factory() as db:
        take_locks(db)
        rows, _stored = load_log(db)
        verdict = compare(rows, None)
        if not verdict.ok:
            return Cleared(False, verdict.reason)
        first, second = replay(rows), replay(rows)
        if canonical(first.state) != canonical(second.state) or first.derived != second.derived:
            return Cleared(False, "replays_differ")
        log = EventLog(db, first.state, now=now or datetime.now(UTC))
        seq = log.control("checkpoint", {"state_sha256": state_sha256(first.state), "last_input_seq": int(first.state["last_input_seq"])})
        save_state(db, first.state, event_seq=seq)
        log.control("clear_stop", {"cause": cause})
        db.commit()
    return Cleared(True)


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
                result = scan_until_done(settings=settings, package=package, session_factory=session_factory, now=now, limit=args.limit)[-1]
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
                         extra={FIELDS: {"event": "ranking.stop", "reason": "replay_mismatch", "mismatch": fields["mismatch"],
                                         "first_mismatch_seq": fields["first_mismatch_seq"], "expected_sha256": fields["stored_sha256"],
                                         "actual_sha256": fields["state_sha256"]}})
            return EXIT_FAILED
        LOGGER.info("Ranking replay checked", extra={FIELDS: {"event": "ranking.replay_checked", **fields}})
        return EXIT_OK
    if args.command == "clear-stop":
        cleared = clear_stop(args.cause, session_factory=session_factory, now=now)
        if not cleared:
            return _refused("replays_differ" if cleared.reason == "replays_differ" else "log_mismatch", mismatch=cleared.reason)
        LOGGER.info("The ranking stop was cleared", extra={FIELDS: {"event": "ranking.stop_cleared", "cause": args.cause}})
        return EXIT_OK
    from app.services.ranking.recommission import RecommissionSetError

    try:
        run = regression(args.adapter, settings=settings, package=package)
    except RecommissionSetError as exc:
        return _refused("recommission_set_unavailable", problem=exc.problem)
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
    except ranking.RankingInputRefused as refused:
        # Nothing was appended (append_inputs rolled back): an unknown model, a commission for a model with outcomes, or
        # another version than the model's.
        return _refused(f"{args.command}_refused", refusal=refused.reason, adapter_id=run.adapter_id)
    event = "ranking.commissioned" if args.command == "commission" else "ranking.recommissioned"
    LOGGER.info("Ranking regression recorded", extra={FIELDS: {"event": event, "adapter_id": run.adapter_id, "kind": kind, "clean": run.clean,
                                                               "failed": run.failed, "generated": run.generated, "passed": run.passed}})
    return EXIT_OK if run.passed else EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
