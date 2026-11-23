"""The EHMF operator commands (plan Phase 7 F, I; Phase 7 spec 4.5, 4.11; infra/cloudrun/deployment.md, Phase 7).

In-image; it connects as the API does and logs JSON lines on the qcai.worker logger (counts, versions and hashes only).
  status                                   ehmf.status with the mode, the SLIs (ehmf.metrics.slis), the stop state and every
                                           ehmf_stops row (the record to keep before a downgrade)
  export-library-proposals --path P        one JSON line per Type C claim label of an applied V3 item (a proposed
                                           misconception-library entry for the Content Owner; never applied), to a path
                                           outside the application tree and the repository checkout
Exit codes: 0 ok, 1 a check failed, 2 a usage error or a refusal (no ehmf block, an export path inside the application
tree or the repository checkout). Run as: python -m app.workers.ehmf <command> ...
Events: ehmf.status (mode, SLIs, stop, stops), ehmf.proposals_exported (count), ehmf.proposals_export_refused (reason).
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

from app.core.config import get_settings
from app.core.config_package import get_config_package
from app.core.db import SessionLocal
from app.core.structured_logging import FIELDS
from app.workers.common import LOGGER

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    export = commands.add_parser("export-library-proposals")
    export.add_argument("--path", type=Path, required=True)
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return EXIT_USAGE
    settings = get_settings()
    package = get_config_package(settings)
    if package.ehmf is None:
        return EXIT_USAGE
    if args.command == "status":
        from sqlalchemy import select

        from app.db_models import EhmfStop
        from app.services import ehmf
        from app.services.ehmf.metrics import slis
        from app.services.ehmf.stop import stop_state

        with SessionLocal() as db:
            state = stop_state(db, package)
            body = slis(db, package, stop=state)
            stops = [{"seq": row.seq, "from_config_version": row.from_config_version, "to_config_version": row.to_config_version,
                      "change_seq": row.change_seq, "detected_seq": row.detected_seq, "before_claims": row.before_claims,
                      "before_ab": row.before_ab, "after_claims": row.after_claims, "after_ab": row.after_ab,
                      "window_deliveries": row.window_deliveries, "package_sha256": row.package_sha256}
                     for row in db.execute(select(EhmfStop).order_by(EhmfStop.seq)).scalars()]
        LOGGER.info("EHMF status", extra={FIELDS: {"event": "ehmf.status", "mode": ehmf.mode(settings, package), **body,
                                                   "stop_state": asdict(state), "stops": stops}})
        return EXIT_OK
    from app.services.ehmf.library import proposals_from_gold
    from app.services.v3.gold import refused_export_roots

    target = Path(args.path).resolve()
    if any(target.is_relative_to(root) for root in refused_export_roots()):
        LOGGER.warning("EHMF library proposals refused: the path lies inside the application tree or the repository checkout",
                       extra={FIELDS: {"event": "ehmf.proposals_export_refused", "reason": "inside_checkout"}})
        return EXIT_USAGE
    with SessionLocal() as db:
        proposals = proposals_from_gold(db)
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        for proposal in proposals:
            handle.write(json.dumps(proposal, sort_keys=True, ensure_ascii=False) + "\n")
    LOGGER.info("EHMF library proposals exported", extra={FIELDS: {"event": "ehmf.proposals_exported", "count": len(proposals)}})
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
