"""Phase 5 daily budget (plan Phase 5 task 5.10 "daily budget hard stop"; plan I "alert at 80% of budget"; AC-5-9; A-15,
hold H9; PD-26; Phase 5 spec 4.4)."""

from __future__ import annotations

from datetime import date
import json
import logging

from app.core.config import Settings
from app.gateway.budget import DailyBudget
from v2_fakes import fake_spec, fresh_gateway


class Today:
    def __init__(self) -> None:
        self.value = date(2026, 11, 21)

    def __call__(self) -> date:
        return self.value


def _alerts(caplog) -> list[dict]:
    return [record.json_fields for record in caplog.records if getattr(record, "json_fields", {}).get("event") == "gateway.budget_alert"]


def test_reserve_alerts_once_at_four_fifths_and_refuses_beyond_the_budget(caplog):
    caplog.set_level(logging.WARNING, logger="qcai.gateway")
    budget = DailyBudget(10)
    assert [budget.reserve(1) for _ in range(7)] == [True] * 7 and _alerts(caplog) == []
    assert budget.reserve(1) and _alerts(caplog) == [{"event": "gateway.budget_alert", "share": "4/5", "daily_units": 10, "spent": 8}]
    assert budget.reserve(2) and budget.remaining() == 0
    assert not budget.reserve(1) and budget.spent == 10
    assert len(_alerts(caplog)) == 1
    assert json.dumps(budget.snapshot()) and budget.snapshot() == {"daily_units": 10, "spent_today": 10, "alerted": True}


def test_the_budget_resets_at_the_utc_day(caplog):
    caplog.set_level(logging.WARNING, logger="qcai.gateway")
    today = Today()
    budget = DailyBudget(5, today=today)
    assert all(budget.reserve(1) for _ in range(5)) and not budget.reserve(1)
    today.value = date(2026, 11, 22)
    assert budget.remaining() == 5 and budget.reserve(4) and budget.alerted
    assert len(_alerts(caplog)) == 2


def test_a_zero_budget_makes_every_adapter_ineligible_and_a_low_one_drops_a_costly_adapter():
    settings = Settings()
    specs = [fake_spec("fake-alpha"), fake_spec("fake-beta", cost=0)]
    assert fresh_gateway(0).eligible(specs, settings=settings) == []
    gateway = fresh_gateway(3)
    assert [spec.adapter_id for spec in gateway.eligible([fake_spec("fake-alpha", cost=4), fake_spec("fake-beta", cost=3)], settings=settings)] == ["fake-beta-v1"]
    assert gateway.ineligible_reason(fake_spec("fake-alpha", cost=4), settings=settings) == "budget"
