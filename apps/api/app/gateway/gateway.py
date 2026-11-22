"""The model gateway: the only module that may make model egress (plan Phase 5 E1, D-23, task 5.10, plan L; Phase 5
spec 4.2-4.5, 4.17).

One process gateway (get_gateway) holds the state, the stop, the secret flag, the daily budget and the metrics;
everything per pipeline or per call (the settings for eligibility, the registry, the policy context) is passed per
call, so pipelines over different settings, stores or manifests share one budget and one stop without sharing a store.

Eligibility (before any panel is built; R-b): an adapter is dropped when the gateway is stopped, a kill switch is on
(MODEL_GATEWAY_KILL_SWITCH abstain_only or pre_verified_only), it is in MODEL_GATEWAY_DISABLED_ADAPTERS, its provider
is not opted in (egress_allowed), the remaining daily budget is below one call's cost (a budget of 0 drops every
adapter), or it reports itself down. Each drop is counted by reason.

A call: the shared stop, the secret flag, then the stop, the payload policy, the budget, the capture hook, then the
adapter; a fake call whose measured duration (an injectable clock) exceeds its caps.timeout_ms is a timeout, and an adapter exception
other than AdapterError becomes AdapterError(kind="error"), so a misbehaving member is only unavailable. Every call
logs gateway.call (outcome ok, error, timeout, or refused for a call the gateway refused before the adapter), and a
failed one gateway.call_failed. Three runtime guards stop the gateway (plan L "Stop on a payload violation, secret in
logs or budget breach"): PayloadPolicy refused a request, a gateway-owned secret reached a log record (the redaction
listener only sets a flag; the gateway stops at its next eligibility decision or call, outside the logging call), or
a call would cross the daily budget or reported a cost above its reservation (cost_overrun). A stop logs
gateway.stopped (origin instance), writes the security event gateway.stopped, refuses every later call and writes the
registry's shared stop (app.gateway.controls.DatabaseStopStore); every other instance's gateway, and every new process,
reads that stop before its next eligibility decision or call and stops too (gateway.stopped, origin shared, no second
security event). The stop lasts until an operator clears it (python -m app.workers.gateway_stop --clear), and the V2
track's effective mode is off from the next response on (v2_panel.mode). The process gateway's daily budget is the
registry's shared DatabaseBudget, so every instance spends from one budget (package v4 gateway.budgets.scope and
gateway.stop.scope "database"; a test or the fixture runner passes its own budget and no stop store).
"""

from __future__ import annotations

from collections.abc import Callable
import logging
import threading
import time
from typing import Any
import weakref

from app.core.structured_logging import FIELDS
from app.gateway.adapters import AdapterError, FakeAdapter, HttpJsonAdapter, ModelAdapter, project_alignment, project_verdict
from app.gateway.budget import DailyBudget
from app.gateway.contracts import AdapterVerdict, AlignmentRequest, AlignmentVerdict, VerdictRequest
from app.gateway.egress import egress_allowed, log_refusal
from app.gateway.metrics import GATEWAY_METRICS
from app.gateway.policy import PayloadPolicy, PayloadViolation, PolicyContext
from app.gateway.registry import AdapterSpec
from app.gateway.secrets import EnvironmentSecretStore

LOGGER = logging.getLogger("qcai.gateway")
STOP_REASONS = ("payload_violation", "secret_in_logs", "budget_breach")
INELIGIBLE_REASONS = ("stopped", "kill_switch", "disabled", "egress_refused", "budget", "down")
SECRET_OWNER = "gateway"


class GatewayRefused(RuntimeError):
    """The gateway refused a call (the member becomes unavailable for the rest of the response)."""


class GatewayStopped(GatewayRefused):
    """The gateway is stopped: every call is refused until an operator clears the stop."""


class ModelGateway:
    def __init__(self, *, budget: DailyBudget, secret_store=None, adapters: dict[str, ModelAdapter] | None = None,
                 clock: Callable[[], float] = time.monotonic, policy: PayloadPolicy | None = None, transport=None,
                 stop_store=None) -> None:
        self.budget = budget
        # The registry's shared, durable stop (DatabaseStopStore), or None: this gateway's stop is then its own only.
        self.stop_store = stop_store
        self.secret_store = secret_store if secret_store is not None else EnvironmentSecretStore()
        self._adapters: dict[str, ModelAdapter] = dict(adapters or {})
        self.clock = clock
        self.policy = policy or PayloadPolicy()
        self.transport = transport
        self.state = "open"
        self.stop_reason: str | None = None
        self.captured: list | None = None
        self._secret_seen = False
        self._lock = threading.Lock()
        from app.core.log_redaction import add_secret_listener

        add_secret_listener(SECRET_OWNER, weakref.WeakMethod(self._on_secret_logged))

    # ------------------------------------------------------------------------------------------- guards

    def _on_secret_logged(self, owner: str) -> None:
        # Runs inside the logging call that made the record: it only sets a flag (no log, no raise, no database).
        self._secret_seen = True

    def check_secret_flag(self) -> None:
        if self._secret_seen and self.state == "open":
            self.stop("secret_in_logs")

    def refresh(self) -> None:
        """Adopt the registry's shared stop, written by this or another instance (no second security event). A store
        that cannot be read leaves the state as it is: the next read tries again."""
        if self.state == "stopped" or self.stop_store is None:
            return
        try:
            reason = self.stop_store.read()
        except Exception:  # noqa: BLE001 - an unreadable store never opens a stopped gateway and never raises into a call
            LOGGER.warning("The shared gateway stop could not be read", extra={FIELDS: {"event": "gateway.stop_unread"}})
            return
        if reason is None:
            return
        with self._lock:
            if self.state == "stopped":
                return
            self.state, self.stop_reason = "stopped", reason
        LOGGER.error("The model gateway stopped; every later call is refused",
                     extra={FIELDS: {"event": "gateway.stopped", "reason": self.stop_reason, "origin": "shared"}})

    def stop(self, reason: str) -> None:
        if reason not in STOP_REASONS:
            raise ValueError(f"unknown stop reason {reason!r}")
        with self._lock:
            if self.state == "stopped":
                return
            self.state, self.stop_reason = "stopped", reason
        GATEWAY_METRICS.refusal(reason)
        LOGGER.error("The model gateway stopped; every later call is refused",
                     extra={FIELDS: {"event": "gateway.stopped", "reason": reason, "origin": "instance"}})
        from app.services.security_log import record_security_event

        record_security_event("gateway.stopped", "denied", actor_role="system", details={"reason": reason})
        if self.stop_store is not None:
            try:
                self.stop_store.write(reason)
            except Exception:  # noqa: BLE001 - this instance stays stopped; the others read the store on their next call
                LOGGER.error("The gateway stop could not be shared; this instance stays stopped",
                             extra={FIELDS: {"event": "gateway.stop_unshared", "reason": reason}})

    # --------------------------------------------------------------------------------------- eligibility

    def ineligible_reason(self, spec: AdapterSpec, *, settings) -> str | None:
        if self.state == "stopped":
            return "stopped"
        if (settings.model_gateway_kill_switch or "none") != "none":
            return "kill_switch"
        if spec.adapter_id in (settings.model_gateway_disabled_adapters or []):
            return "disabled"
        if not egress_allowed(settings, spec.provider):
            log_refusal(spec.provider, spec.adapter_id)
            return "egress_refused"
        remaining = self.budget.remaining()
        if self.budget.daily_units == 0 or remaining < spec.cost_units_per_call:
            return "budget"
        if not self.adapter_for(spec).available():
            return "down"
        return None

    def eligible(self, specs, *, settings) -> list[AdapterSpec]:
        self.refresh()
        self.check_secret_flag()
        kept = []
        for spec in specs:
            reason = self.ineligible_reason(spec, settings=settings)
            if reason is None:
                kept.append(spec)
            else:
                GATEWAY_METRICS.ineligible_for(reason)
        return kept

    def adapter_for(self, spec: AdapterSpec) -> ModelAdapter:
        adapter = self._adapters.get(spec.adapter_id)
        if adapter is None:
            if spec.provider == "fake":
                adapter = FakeAdapter(spec)
            else:
                adapter = HttpJsonAdapter(spec, secret_store=self.secret_store, transport=self.transport)
            self._adapters[spec.adapter_id] = adapter
        return adapter

    # --------------------------------------------------------------------------------------------- calls

    def capture(self, request: Any) -> None:
        """The test hook of AC-5-3: every request contract that would leave the platform, when capturing."""
        if self.captured is not None:
            self.captured.append(request)

    def verify(self, spec: AdapterSpec, request: VerdictRequest, *, context: PolicyContext) -> AdapterVerdict:
        raw = self._call(spec, request, context, "claim")
        return project_verdict(raw, request, spec.adapter_id)

    def align(self, spec: AdapterSpec, request: AlignmentRequest, *, context: PolicyContext) -> AlignmentVerdict:
        raw = self._call(spec, request, context, "alignment")
        return project_alignment(raw, spec.adapter_id)

    def _refused(self, spec: AdapterSpec, item: str) -> None:
        """A call the gateway refused before the adapter (stopped, a payload violation, a budget breach): counted and
        logged as gateway.call with outcome refused, no latency and no cost."""
        GATEWAY_METRICS.call(spec.adapter_id, "refused", None, 0)
        LOGGER.info("Gateway call", extra={FIELDS: {"event": "gateway.call", "adapter_id": spec.adapter_id, "family": spec.family,
                                                     "item": item, "outcome": "refused", "latency_ms": 0.0, "cost_units": 0}})

    def _call(self, spec: AdapterSpec, request, context: PolicyContext, item: str):
        self.refresh()
        self.check_secret_flag()
        if self.state == "stopped":
            self._refused(spec, item)
            raise GatewayStopped("the model gateway is stopped")
        try:
            self.policy.check(request, context)
        except PayloadViolation:
            violation = True
        else:
            violation = False
        if violation:
            self.stop("payload_violation")
            self._refused(spec, item)
            raise GatewayStopped("the payload policy refused a request")
        if not self.budget.reserve(spec.cost_units_per_call):
            self.stop("budget_breach")
            self._refused(spec, item)
            raise GatewayStopped("the daily budget is spent")
        self.capture(request)
        adapter = self.adapter_for(spec)
        started = self.clock()
        error: AdapterError | None = None
        misbehaved = False
        raw = None
        try:
            raw = adapter.verify(request) if item == "claim" else adapter.align(request)
        except AdapterError as exc:
            error = exc
        except Exception:  # noqa: BLE001 - any other adapter exception makes the member unavailable; nothing of it is kept
            misbehaved = True
        if misbehaved:
            error = AdapterError(spec.adapter_id, "error")
        latency_ms = (self.clock() - started) * 1000.0
        if error is None and spec.provider == "fake" and latency_ms > spec.caps.timeout_ms:
            error = AdapterError(spec.adapter_id, "timeout")
        outcome = "ok" if error is None else ("timeout" if error.kind == "timeout" else "error")
        GATEWAY_METRICS.call(spec.adapter_id, outcome, latency_ms, spec.cost_units_per_call)
        LOGGER.info("Gateway call", extra={FIELDS: {"event": "gateway.call", "adapter_id": spec.adapter_id, "family": spec.family,
                                                     "item": item, "outcome": outcome, "latency_ms": round(latency_ms, 3),
                                                     "cost_units": spec.cost_units_per_call}})
        if error is not None:
            kind, status = error.kind, error.status
            error = None
            LOGGER.warning("Gateway call failed", extra={FIELDS: {"event": "gateway.call_failed", "adapter_id": spec.adapter_id,
                                                                  "kind": kind, "status": status}})
            if kind == "cost_overrun":
                # The provider reported a cost above the call's reservation: the daily budget no longer bounds the spend.
                self.stop("budget_breach")
                raise GatewayStopped("a call cost more than its reservation")
            raise AdapterError(spec.adapter_id, kind, status)
        return raw

    def summary(self) -> dict:
        return {"state": self.state, "stop_reason": self.stop_reason, **self.budget.snapshot()}


_PROCESS: ModelGateway | None = None
_PROCESS_LOCK = threading.Lock()


def get_gateway() -> ModelGateway:
    """The process gateway. Its budget is the package's daily units for this process's registry, kept in the shared
    store (DatabaseBudget), and its stop is the registry's shared stop (DatabaseStopStore), as package v4 names them
    (gateway.budgets.scope, gateway.stop.scope); it adopts a recorded stop at once."""
    global _PROCESS
    with _PROCESS_LOCK:
        if _PROCESS is None:
            from app.core.config import get_settings
            from app.core.config_package import get_config_package
            from app.gateway.registry import registry_name

            settings = get_settings()
            package = get_config_package(settings)
            gateway = package.gateway
            if gateway is None:
                _PROCESS = ModelGateway(budget=DailyBudget(0))
            else:
                from app.gateway.controls import DatabaseBudget, DatabaseStopStore

                name = registry_name(settings, gateway.registries)
                units = gateway.daily_units.get(name, 0)
                budget = (DatabaseBudget(name, units, alert=gateway.alert_share) if gateway.budget_scope == "database"
                          else DailyBudget(units, alert=gateway.alert_share))
                stops = DatabaseStopStore(name) if gateway.stop_scope == "database" else None
                _PROCESS = ModelGateway(budget=budget, stop_store=stops)
                _PROCESS.refresh()
        return _PROCESS


def process_gateway_stopped() -> bool:
    gateway = _PROCESS
    if gateway is None:
        return False
    gateway.refresh()
    return gateway.state == "stopped"


def process_gateway_state() -> tuple[str, str | None]:
    """The process gateway's state (the shared stop adopted), or open when this process has built none."""
    gateway = _PROCESS
    if gateway is None:
        return ("open", None)
    gateway.refresh()
    return (gateway.state, gateway.stop_reason)


def reset_process_gateway() -> None:
    """The test seam (conftest's autouse fixture, with app.gateway.controls.clear_shared_controls): a new process
    gateway on next use."""
    global _PROCESS
    with _PROCESS_LOCK:
        _PROCESS = None
