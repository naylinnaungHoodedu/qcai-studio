"""The model gateway: the only module that may make model egress (plan Phase 5 E1, D-23, task 5.10, plan L; Phase 5
spec 4.2-4.5, 4.17).

One process gateway (get_gateway) holds the state, the stop, the secret flag, the daily budget and the metrics;
everything per pipeline or per call (the settings for eligibility, the registry, the policy context) is passed per
call, so pipelines over different settings, stores or manifests share one budget and one stop without sharing a store.

Eligibility (before any panel is built; R-b): an adapter is dropped when the gateway is stopped, a kill switch is on
(MODEL_GATEWAY_KILL_SWITCH abstain_only or pre_verified_only), it is in MODEL_GATEWAY_DISABLED_ADAPTERS, its provider
is not opted in (egress_allowed), the remaining daily budget is below one call's cost (a budget of 0 drops every
adapter), the budget's store cannot be read (budget_unavailable), or it reports itself down. Each drop is counted by
reason.

A call: the shared stop, the secret flag, then the stop, the payload policy, the budget, the capture hook, then the
adapter; a fake call whose measured duration (an injectable clock) exceeds its caps.timeout_ms is a timeout, and an adapter exception
other than AdapterError becomes AdapterError(kind="error"), so a misbehaving member is only unavailable. The call's
reservation covers its first attempt; an adapter that retries (HttpJsonAdapter) reserves each retry through the
call's reserve_retry hook before it sends it, so every attempt sent is counted. A budget store that cannot be read
or written refuses the call (GatewayRefused, gateway.budget_unavailable): the member is unavailable, nothing is sent
and nothing is spent, and the gateway does not stop. Every call logs gateway.call (outcome ok, error, timeout, or
refused for a call the gateway refused before the adapter; cost_units is what its attempts reserved), and a failed one
gateway.call_failed. Three runtime guards stop the gateway (plan L "Stop on a payload violation, secret in logs or
budget breach"): PayloadPolicy refused a request, a gateway-owned secret reached a log record (the redaction listener
only sets a flag; the gateway stops at its next eligibility decision or call, outside the logging call), or a call or
a retry would cross the daily budget or a reply reported a cost above its reservation (cost_overrun). A stop logs
gateway.stopped (origin instance), writes the security event gateway.stopped, refuses every later call and writes the
registry's shared stop (app.gateway.controls.DatabaseStopStore); every other instance's gateway, and every new process
that builds a gateway, reads that stop before its next eligibility decision or call and stops too (gateway.stopped,
origin shared, no second security event). A running gateway never reopens: a stopped instance refuses every call
until it is replaced, and an operator's clear (python -m app.workers.gateway_stop --clear) lets only the processes
started after it open, so service resumes with a new revision. The V2 track's effective mode is off from the next
response on (v2_panel.mode). The process gateway's daily budget is the registry's shared DatabaseBudget, so every
instance spends from one budget (package v4 gateway.budgets.scope and gateway.stop.scope "database"; a test or the
fixture runner passes its own budget and no stop store).
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
INELIGIBLE_REASONS = ("stopped", "kill_switch", "disabled", "egress_refused", "budget", "budget_unavailable", "down")
SECRET_OWNER = "gateway"


class GatewayRefused(RuntimeError):
    """The gateway refused a call (the member becomes unavailable for the rest of the response)."""


class GatewayStopped(GatewayRefused):
    """The gateway is stopped: this instance refuses every call for the rest of its life (an operator's clear of the
    shared stop opens only the processes started after it)."""


def budget_unavailable() -> None:
    """Log that the daily budget's store could not be read or written (no detail of the error is kept)."""
    LOGGER.warning("The gateway's daily budget could not be read; the call is refused", extra={FIELDS: {"event": "gateway.budget_unavailable"}})


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
        if self.budget.daily_units == 0:
            return "budget"
        try:
            remaining = self.budget.remaining()
        except Exception:  # noqa: BLE001 - an unreadable budget store makes the member ineligible (fail closed, no spend)
            budget_unavailable()
            return "budget_unavailable"
        if remaining < spec.cost_units_per_call:
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
        try:
            reserved = self.budget.reserve(spec.cost_units_per_call)
        except Exception:  # noqa: BLE001 - an unwritable budget store refuses the call: nothing is sent or spent, no stop
            reserved = None
        if reserved is None:
            budget_unavailable()
            self._refused(spec, item)
            raise GatewayRefused("the daily budget could not be read")
        if not reserved:
            self.stop("budget_breach")
            self._refused(spec, item)
            raise GatewayStopped("the daily budget is spent")
        self.capture(request)
        adapter = self.adapter_for(spec)
        # Each retry an adapter sends reserves one more call's cost first (task 5.10: the hard stop counts every attempt).
        spent = {"units": spec.cost_units_per_call, "store_failed": False}

        def reserve_retry() -> bool:
            try:
                granted = self.budget.reserve(spec.cost_units_per_call)
            except Exception:  # noqa: BLE001 - the retry is not sent; the member is unavailable, the gateway stays open
                spent["store_failed"] = True
                return False
            if granted:
                spent["units"] += spec.cost_units_per_call
            return bool(granted)

        started = self.clock()
        error: AdapterError | None = None
        misbehaved = False
        raw = None
        try:
            send = adapter.verify if item == "claim" else adapter.align
            raw = send(request, reserve_retry=reserve_retry) if isinstance(adapter, HttpJsonAdapter) else send(request)
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
        GATEWAY_METRICS.call(spec.adapter_id, outcome, latency_ms, spent["units"])
        LOGGER.info("Gateway call", extra={FIELDS: {"event": "gateway.call", "adapter_id": spec.adapter_id, "family": spec.family,
                                                     "item": item, "outcome": outcome, "latency_ms": round(latency_ms, 3),
                                                     "cost_units": spent["units"]}})
        if error is not None:
            kind, status = error.kind, error.status
            error = None
            LOGGER.warning("Gateway call failed", extra={FIELDS: {"event": "gateway.call_failed", "adapter_id": spec.adapter_id,
                                                                  "kind": kind, "status": status}})
            if kind == "budget" and spent["store_failed"]:
                budget_unavailable()
                raise GatewayRefused("the daily budget could not be read")
            if kind in ("budget", "cost_overrun"):
                # A retry the daily budget refused, or a reply that cost more than its reservation: the budget would no
                # longer bound the spend.
                self.stop("budget_breach")
                raise GatewayStopped("the daily budget no longer bounds the call")
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
    """The process gateway's state (the shared stop adopted), or open when this process has built none: a process whose
    V2 mode is off by its settings (MODEL_GATEWAY off, every environment outside development) builds no gateway and
    reads no stop; the operator's status command reads the registry's stops (python -m app.workers.gateway_stop)."""
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
