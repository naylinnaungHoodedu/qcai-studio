"""The gateway's shared controls in the application database (plan Phase 5 task 5.10 "daily budget hard stop"; plan L
"Stop on a payload violation, secret in logs or budget breach."; 7.5 "shared verdict cache and rate-limit store";
Phase 5 spec 4.4, 4.5; PD-26, PD-28).

Every API instance and worker of an environment reads and writes the same rows, as the rate-limit counters do (task
1.6, P1-D-06), so neither a scale event nor a new revision resets them:
  DatabaseBudget     the registry's spend for the UTC day (gateway_budget_days). reserve(cost) is one atomic UPDATE that
                     refuses a cost the day's remaining units cannot cover, and the first reservation that reaches 4/5 of
                     the day's units, across every instance, logs gateway.budget_alert.
  DatabaseStopStore  the registry's stop (gateway_stops): the first stop guard to fire writes its reason, every instance's
                     gateway reads it before each eligibility decision and call, and it lasts until an operator clears
                     it (python -m app.workers.gateway_stop --clear; infra/cloudrun/deployment.md, Phase 5).
No row holds learner data: a registry name, a UTC date, counts, a stop reason and its time. Package v4 names the scope
(gateway.budgets.scope and gateway.stop.scope "database"); get_gateway builds these for the process gateway, and a
test or the fixture runner may pass the per-process DailyBudget instead.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
import logging

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.structured_logging import FIELDS
from app.gateway.budget import utc_date

LOGGER = logging.getLogger("qcai.gateway")


def _engine():
    from app.core.db import engine

    return engine


def _insert(table):
    return (postgresql_insert if _engine().dialect.name == "postgresql" else sqlite_insert)(table)


def _budget_table():
    from app.db_models import GatewayBudgetDay

    return GatewayBudgetDay.__table__


def _stop_table():
    from app.db_models import GatewayStop

    return GatewayStop.__table__


class DatabaseBudget:
    """A daily budget shared by every instance of one registry (the DailyBudget interface)."""

    def __init__(self, registry: str, daily_units: int, *, alert: tuple[int, int] = (4, 5), today: Callable[[], date] = utc_date) -> None:
        if daily_units < 0:
            raise ValueError("a daily budget is not negative")
        self.registry = registry
        self.daily_units = int(daily_units)
        self.alert = alert
        self.today = today

    def _spent(self, connection, day: str) -> tuple[int, bool]:
        table = _budget_table()
        row = connection.execute(select(table.c.spent, table.c.alerted).where(table.c.registry == self.registry, table.c.day == day)).first()
        return (int(row.spent), bool(row.alerted)) if row else (0, False)

    def remaining(self) -> int:
        with _engine().connect() as connection:
            spent, _ = self._spent(connection, self.today().isoformat())
        return max(self.daily_units - spent, 0)

    def reserve(self, cost: int) -> bool:
        table = _budget_table()
        day = self.today().isoformat()
        numerator, denominator = self.alert
        where = (table.c.registry == self.registry, table.c.day == day)
        with _engine().begin() as connection:
            connection.execute(_insert(table).values(registry=self.registry, day=day, spent=0, alerted=False)
                               .on_conflict_do_nothing(index_elements=[table.c.registry, table.c.day]))
            spent = connection.execute(update(table).where(*where, table.c.spent + cost <= self.daily_units)
                                       .values(spent=table.c.spent + cost).returning(table.c.spent)).scalar_one_or_none()
            if spent is None:
                return False
            alerted = None
            if self.daily_units > 0:
                alerted = connection.execute(update(table).where(*where, table.c.alerted.is_(False),
                                                                 table.c.spent * denominator >= self.daily_units * numerator)
                                             .values(alerted=True).returning(table.c.spent)).scalar_one_or_none()
        if alerted is not None:
            LOGGER.warning("The gateway has spent 4/5 of its daily budget",
                           extra={FIELDS: {"event": "gateway.budget_alert", "share": f"{numerator}/{denominator}",
                                           "daily_units": self.daily_units, "spent": int(alerted)}})
        return True

    def snapshot(self) -> dict:
        with _engine().connect() as connection:
            spent, alerted = self._spent(connection, self.today().isoformat())
        return {"daily_units": self.daily_units, "spent_today": spent, "alerted": alerted}


class DatabaseStopStore:
    """The registry's durable stop, shared by every instance: the first reason written stands until it is cleared."""

    def __init__(self, registry: str) -> None:
        self.registry = registry

    def read(self) -> str | None:
        table = _stop_table()
        with _engine().connect() as connection:
            return connection.execute(select(table.c.reason).where(table.c.registry == self.registry)).scalar_one_or_none()

    def write(self, reason: str) -> None:
        table = _stop_table()
        with _engine().begin() as connection:
            connection.execute(_insert(table).values(registry=self.registry, reason=reason, stopped_at=datetime.now(UTC))
                               .on_conflict_do_nothing(index_elements=[table.c.registry]))

    def clear(self) -> str | None:
        """Remove the stop (an operator's step); returns the reason it held, or None."""
        table = _stop_table()
        with _engine().begin() as connection:
            reason = connection.execute(select(table.c.reason).where(table.c.registry == self.registry)).scalar_one_or_none()
            connection.execute(delete(table).where(table.c.registry == self.registry))
        return reason


def stop_rows() -> list[dict]:
    """Every registry's stop: {registry, reason, stopped_at} (the operator's status read)."""
    table = _stop_table()
    with _engine().connect() as connection:
        rows = connection.execute(select(table.c.registry, table.c.reason, table.c.stopped_at).order_by(table.c.registry)).all()
    return [{"registry": row.registry, "reason": row.reason, "stopped_at": row.stopped_at.isoformat() if row.stopped_at else None} for row in rows]


def clear_shared_controls() -> None:
    """The test seam (conftest's autouse fixture, with reset_process_gateway): no budget day and no stop."""
    with _engine().begin() as connection:
        connection.execute(delete(_budget_table()))
        connection.execute(delete(_stop_table()))
