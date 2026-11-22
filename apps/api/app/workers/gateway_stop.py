"""Read or clear the model gateway's shared stop (plan Phase 5 L "Stop on a payload violation, secret in logs or budget
breach."; Phase 5 spec 4.5; infra/cloudrun/deployment.md, Phase 5).

A stop guard that fires writes its registry's stop to gateway_stops, and every instance then refuses every gateway
call; a process started while the stop is recorded starts stopped. This in-image command is the operator's only way
to clear it. It connects as the API does (the Cloud SQL Python connector when CLOUD_SQL_CONNECTION_NAME is set) and
logs one JSON line on the qcai.worker logger (event gateway.stop_status: every registry's stop, reason and time;
registry names, reasons and times only).
  --clear REGISTRY  removes that registry's stop, after the cause is fixed, and writes the security event
                    gateway.stop_cleared (actor_role operator, the registry and the reason it held). Instances already
                    running stay stopped until they are replaced (a new revision), because each keeps its own stop.
Exit codes: 0 ok (nothing to clear included), 2 a usage error.
Run as: python -m app.workers.gateway_stop [--clear REGISTRY]
"""

import argparse
import sys

from app.core.structured_logging import FIELDS
from app.gateway.controls import DatabaseStopStore, stop_rows
from app.gateway.registry import REGISTRY_NAMES
from app.workers.common import LOGGER


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--clear", choices=REGISTRY_NAMES, help="the registry whose stop to clear")
    args = parser.parse_args(argv)
    cleared = None
    if args.clear:
        cleared = DatabaseStopStore(args.clear).clear()
        if cleared is not None:
            from app.services.security_log import record_security_event

            record_security_event("gateway.stop_cleared", "success", actor_role="operator",
                                  details={"registry": args.clear, "reason": cleared})
    LOGGER.info("Gateway stop status", extra={FIELDS: {"event": "gateway.stop_status", "stops": stop_rows(),
                                                        "cleared": {"registry": args.clear, "reason": cleared} if args.clear else None}})
    return 0


if __name__ == "__main__":
    sys.exit(main())
