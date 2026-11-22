"""The daily budget (plan Phase 5 task 5.10 "daily budget hard stop"; plan I "alert at 80% of budget"; A-15 open, hold
H9; PD-26; Phase 5 spec 4.4).

DailyBudget keeps the day's spend in one process: the budget a test or the fixture runner passes. The process gateway's
budget is app.gateway.controls.DatabaseBudget, the same rule over one row per registry and UTC day that every instance
spends from. remaining() is what is left today; eligibility drops an adapter whose cost per call exceeds it, and a budget of 0 makes every adapter ineligible (staging, production and default are 0 while A-15 is
open). reserve(cost) refuses a call that would cross the budget (the gateway then stops with budget_breach) and logs
gateway.budget_alert once per UTC day when spending reaches 4/5 of it. A cache hit costs nothing.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
import logging
import threading

from app.core.structured_logging import FIELDS

LOGGER = logging.getLogger("qcai.gateway")


def utc_date() -> date:
    return datetime.now(UTC).date()


class DailyBudget:
    def __init__(self, daily_units: int, *, alert: tuple[int, int] = (4, 5), today: Callable[[], date] = utc_date) -> None:
        if daily_units < 0:
            raise ValueError("a daily budget is not negative")
        self.daily_units = int(daily_units)
        self.alert = alert
        self.today = today
        self.spent = 0
        self.alerted = False
        self._day = today()
        self._lock = threading.Lock()

    def _roll(self) -> None:
        day = self.today()
        if day != self._day:
            self._day, self.spent, self.alerted = day, 0, False

    def remaining(self) -> int:
        with self._lock:
            self._roll()
            return max(self.daily_units - self.spent, 0)

    def reserve(self, cost: int) -> bool:
        with self._lock:
            self._roll()
            if self.spent + cost > self.daily_units:
                return False
            self.spent += cost
            numerator, denominator = self.alert
            alert = not self.alerted and self.daily_units > 0 and self.spent * denominator >= self.daily_units * numerator
            if alert:
                self.alerted = True
            spent = self.spent
        if alert:
            LOGGER.warning("The gateway has spent 4/5 of its daily budget",
                           extra={FIELDS: {"event": "gateway.budget_alert", "share": f"{numerator}/{denominator}",
                                           "daily_units": self.daily_units, "spent": spent}})
        return True

    def snapshot(self) -> dict:
        with self._lock:
            self._roll()
            return {"daily_units": self.daily_units, "spent_today": self.spent, "alerted": self.alerted}
