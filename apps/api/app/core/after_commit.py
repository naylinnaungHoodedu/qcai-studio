"""Log lines that describe a transaction's writes, emitted only once that transaction commits.

A scan or an operator command can write an X5 window or a ranking event and then roll back (a refused commission, a
retried SQLite-busy attempt, an exception). A line logged before the commit would report a write that never happened,
and a later attempt would log it again. log_after_commit keeps the line on the session and emits it from the session's
after_commit event; the end of the root transaction without a commit (a rollback, a close, an exception) drops it.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core.structured_logging import FIELDS

_PENDING = "pending_log_lines"


def _emit(session: Session) -> None:
    pending = session.info.get(_PENDING)
    while pending:
        logger, level, message, fields = pending.pop(0)
        logger.log(level, message, extra={FIELDS: fields})


def _drop(session: Session, transaction: Any) -> None:
    # after_commit runs before after_transaction_end, so a committed transaction's lines are already out.
    if transaction.parent is None:
        session.info.get(_PENDING, []).clear()


def log_after_commit(db: Session, logger: logging.Logger, level: int, message: str, fields: dict[str, Any]) -> None:
    """Log `message` with `fields` once the root transaction of `db` commits; never when it ends without a commit."""
    pending = db.info.get(_PENDING)
    if pending is None:
        pending = db.info[_PENDING] = []
        event.listen(db, "after_commit", _emit)
        event.listen(db, "after_transaction_end", _drop)
    pending.append((logger, level, message, dict(fields)))
