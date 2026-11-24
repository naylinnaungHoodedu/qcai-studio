"""Responders for the runner: the stub, recorded responses, a scripted fake provider, and the live refusal (spec 4.9; PD-68).

No responder here touches the network or imports a model client. Live adapters are not wired (DI-132): `LIVE_ADAPTERS` is
empty, and a live adapter, once one exists, runs on a research gateway separate from the application's process gateway
(plan section 7: "research runs use a separate gateway and span store"). `live_refusal_reasons` names every condition a
live run still lacks; in this repository a live run is always refused.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from .canonical import read_jsonl

UNRESOLVABLE_POINTER = "EV-SYN-p999-99"
FAILURE_REASONS = ("timeout", "rate_limited", "server_error", "refused_payload", "recorded_missing")
RECORDING_FORMAT = "recorded-responses-v1"


class ProviderOutage(RuntimeError):
    """The provider is down: the run stops at a checkpoint and resumes later (plan J: "provider outage resumes")."""


class TransientFailure(RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class Responder(Protocol):
    rule: str

    def respond(self, request: Any) -> dict[str, Any]: ...


def _owner(request: Any) -> str:
    unit = request.unit
    return unit if isinstance(unit, str) and "-t" in unit else request.item_id


def stub_response(prefix: bytes, request: Any, *, model_id: str | None = None) -> dict[str, Any]:
    """`stub-responder-v1`: decisions from sha256(prefix + request_key), the same rule for every arm (R-f)."""
    digest = hashlib.sha256(prefix + request.request_key.encode("utf-8")).digest()
    follows = digest[0] < 224
    answers = (request.gold == "answer") == follows
    text = "stub:" + request.request_key[:16]
    usage = {"input_units": 1, "output_units": 1}
    if not answers:
        return {"outcome": "abstained", "claims": [], "text": text, "usage": usage, "model_id": model_id}
    claims = []
    if request.gold == "answer":
        for index, claim_id in enumerate(request.gold_claims):
            value = digest[1 + index % 31] % 16
            if value == 0:
                label, cited, ehmf = "fabricated", [UNRESOLVABLE_POINTER], "B1"
            elif value == 1:
                label, cited, ehmf = "attribution_error", list(request.evidence), "B2"
            elif value == 2:
                label, cited, ehmf = "unsupported_but_true", [], None
            else:
                label, cited, ehmf = "supported", list(request.evidence), None
            claims.append({"claim_id": claim_id, "cited": cited, "label": label, "ehmf_type": ehmf})
    else:
        fabricated = digest[1] % 2 == 0
        claims.append({"claim_id": f"{_owner(request)}-stub-c1", "cited": [UNRESOLVABLE_POINTER] if fabricated else [],
                       "label": "fabricated" if fabricated else "unsupported_but_true", "ehmf_type": "B1" if fabricated else None})
    return {"outcome": "answered", "claims": claims, "text": text, "usage": usage, "model_id": model_id}


class StubResponder:
    rule = "stub-responder-v1"

    def respond(self, request: Any) -> dict[str, Any]:
        return stub_response(b"stub-responder-v1", request)


class RecordedResponder:
    """Replays a `recorded-responses-v1` file: each recorded failed attempt raises again, in order, then the response."""

    rule = RECORDING_FORMAT

    def __init__(self, path: Path) -> None:
        lines = read_jsonl(Path(path))
        if not lines or lines[0].get("recording") != RECORDING_FORMAT:
            raise ValueError("not a recorded-responses-v1 file")
        self.header = lines[0]
        self.entries = {line["request_key"]: line for line in lines[1:]}
        self.calls: dict[str, int] = {}

    @property
    def source(self) -> str:
        return str(self.header.get("source"))

    def respond(self, request: Any) -> dict[str, Any]:
        entry = self.entries.get(request.request_key)
        if entry is None:
            raise TransientFailure("recorded_missing")
        index = self.calls.get(request.request_key, 0)
        self.calls[request.request_key] = index + 1
        attempts = entry.get("attempts", [{"status": "ok"}])
        status = attempts[index]["status"] if index < len(attempts) else attempts[-1]["status"]
        if status != "ok":
            raise TransientFailure(status)
        return dict(entry["response"])


class ScriptedProvider:
    """A fake provider for tests: the stub rule under its own prefix, a scripted outage and scripted transient failures."""

    rule = "scripted-provider-v1"

    def __init__(self, *, outage_at: int | None = None, transient: Mapping[str, list[str]] | None = None,
                 model_id: str = "scripted-model-v1") -> None:
        self.outage_at = outage_at
        self.transient = {key: list(value) for key, value in (transient or {}).items()}
        self.model_id = model_id
        self.calls = 0
        self.outage_done = False

    def respond(self, request: Any) -> dict[str, Any]:
        call = self.calls
        self.calls += 1
        if self.outage_at is not None and call == self.outage_at and not self.outage_done:
            self.outage_done = True
            raise ProviderOutage("scripted outage")
        pending = self.transient.get(request.request_key)
        if pending:
            raise TransientFailure(pending.pop(0))
        return stub_response(b"scripted-provider-v1", request, model_id=self.model_id)


LIVE_ADAPTERS: Mapping[str, Callable[..., Responder]] = {}


def _decided(package_raw: Mapping[str, Any], name: str) -> bool:
    return ((package_raw.get("owner_decisions") or {}).get(name) or {}).get("state") == "decided"


def live_refusal_reasons(spec: Mapping[str, Any], package_raw: Mapping[str, Any], environ: Mapping[str, str], arms: Any, *,
                         out_dir: Path | None = None, repo_root: Path | None = None) -> list[str]:
    """Every condition a live run lacks, in order (spec 4.9). An empty list is never reached in this repository."""
    from .ablation import arm_configuration
    from .governance import GovernanceError, load_irb, resolve_record
    from .planes import REPO_ROOT, inside_checkout

    root = repo_root or REPO_ROOT
    reasons: list[str] = []
    adapter = ((spec.get("responder") or {}).get("live") or {}).get("adapter")
    if adapter not in LIVE_ADAPTERS:
        reasons.append("no_live_adapter")
    plane = environ.get("RESEARCH_PLANE_ROOT")
    plane_ok = False
    if plane:
        plane_path = Path(os.path.abspath(plane))
        if plane_path.is_dir() and not inside_checkout(plane_path, root):
            if out_dir is not None:
                try:
                    Path(os.path.abspath(out_dir)).relative_to(plane_path)
                    plane_ok = True
                except ValueError:
                    plane_ok = False
    if not plane_ok:
        reasons.append("research_plane_absent")
    for name in ("D-14", "D-07", "D-08", "D-12"):
        if not _decided(package_raw, name):
            reasons.append(f"{name} open")
    irb_ok = False
    reference = (spec.get("governance") or {}).get("irb_record")
    if reference:
        try:
            load_irb(resolve_record(reference, root))
            irb_ok = True
        except (GovernanceError, OSError, ValueError):
            irb_ok = False
    if not irb_ok:
        reasons.append("irb_not_filed")
    if not spec.get("provider_terms"):
        reasons.append("provider_terms_unrecorded")
    ruling = spec.get("licence_ruling")
    if not ruling:
        reasons.append("licence_ruling_unrecorded")
    elif ruling.get("determination") == "negative":
        reasons.append("licence_negative")
    elif ruling.get("determination") != "permits":
        reasons.append("licence_ruling_unrecorded")
    if not spec.get("research_use_confirmation"):
        reasons.append("research_use_unconfirmed")
    selected = (spec.get("arms") or {}).get("selected") or []
    semantic_on = bool((package_raw.get("semantic") or {}).get("enabled_by_default"))
    if not semantic_on and any(arm_configuration(arms, arm).get("retrieval") == "semantic" for arm in selected if arm in arms.arms):
        reasons.append("semantic_backend_off")
    return reasons
