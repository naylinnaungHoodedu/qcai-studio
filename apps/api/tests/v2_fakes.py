"""Fakes for the Phase 5 gateway and V2 tests (Phase 5 spec 13.1). Not a test module: adapter specs and registries,
scripted fake adapters, a fake secret store, a revising generator, a generator of a registered family, a V2 pipeline
over the development store with a fresh gateway and cache, and a capture of every request the gateway would send. No
learner data, no network call.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from contextlib import contextmanager
import hashlib

from app.gateway.adapters import FakeAdapter
from app.gateway.budget import DailyBudget
from app.gateway.gateway import ModelGateway
from app.gateway.registry import AdapterRegistry, AdapterSpec, Caps
from app.services.tutor_pipeline.contracts import ClaimPlan, GeneratorRef

FAMILIES = ("fake-alpha", "fake-beta", "fake-gamma", "fake-delta")


def fake_spec(family: str, *, adapter_id: str | None = None, capabilities: Sequence[str] = ("verify",), provider: str = "fake",
              model_id: str | None = None, model_version: str = "2026-11-21", cost: int = 1, timeout_ms: int = 500, max_retries: int = 1,
              endpoint: str | None = None, auth_header: str | None = None, secret_ref: str | None = None) -> AdapterSpec:
    return AdapterSpec(adapter_id=adapter_id or f"{family}-v1", family=family, provider=provider, model_id=model_id or f"{family}-verifier",
                       model_version=model_version, capabilities=tuple(capabilities),
                       caps=Caps(max_tokens=256, timeout_ms=timeout_ms, max_retries=max_retries), cost_units_per_call=cost,
                       fake_rule="verbatim-support-v1" if provider == "fake" else None, endpoint=endpoint, auth_header=auth_header,
                       secret_ref=secret_ref)


def make_registry(families: Iterable[str] = FAMILIES[:3], *, name: str = "development", generator_family: str | None = None,
                  duplicate: str | None = None) -> AdapterRegistry:
    """A registry of one fake per family, in order; generator_family adds a generate-capable member of that family, and
    duplicate a second adapter of that family right after its first."""
    members = []
    for family in families:
        capabilities = ("generate", "verify") if family == generator_family else ("verify",)
        members.append(fake_spec(family, adapter_id=f"{family}-1" if family == duplicate else None, capabilities=capabilities))
        if family == duplicate:
            members.append(fake_spec(family, adapter_id=f"{family}-2"))
    return AdapterRegistry(name=name, members=tuple(members))


def claim_key(text: str, span_id: str) -> tuple[str, str]:
    return hashlib.sha256(text.encode("utf-8")).hexdigest(), span_id


class ScriptedFakeAdapter(FakeAdapter):
    """A fake whose verdicts can be scripted per (claim text sha256, span id) or for every pair ("*"), and that can fail
    on chosen call numbers (an AdapterError, as a provider error after retries would be)."""

    def __init__(self, spec: AdapterSpec, *, script: dict | None = None, down: bool = False, late_ms: float = 0.0, clock=None,
                 fail_calls: Iterable[int] = (), alignment: dict | None = None) -> None:
        super().__init__(spec, script=script, down=down, late_ms=late_ms, clock=clock, alignment=alignment)
        self.fail_calls = set(fail_calls)

    def _tick(self) -> None:
        super()._tick()
        if self.calls in self.fail_calls:
            from app.gateway.adapters import AdapterError

            raise AdapterError(self.spec.adapter_id, "scripted")


class FakeSecretStore:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = dict(values or {})
        self.reads: list[str] = []

    def get(self, ref: str) -> str | None:
        self.reads.append(ref)
        return self.values.get(ref)


class RevisingGenerator:
    """The extractive generator with the optional revise capability: it returns the scripted revision of a claim text
    (or the same text), counting its calls."""

    def __init__(self, inner, revisions: dict[str, str] | None = None) -> None:
        self.inner = inner
        self.ref = inner.ref
        self.revisions = dict(revisions or {})
        self.proposals = 0
        self.revised: list[tuple[str, str]] = []

    def propose(self, envelope) -> ClaimPlan:
        self.proposals += 1
        return self.inner.propose(envelope)

    def revise(self, claim_text: str, span_texts: tuple[str, ...], ehmf_type: str) -> str | None:
        self.revised.append((claim_text, ehmf_type))
        return self.revisions.get(claim_text, claim_text)


class FamilyGenerator:
    """The extractive generator's proposals under the id of a registry adapter with capability generate, so its family is
    that adapter's (AC-5-1)."""

    def __init__(self, inner, adapter_id: str) -> None:
        self.inner = inner
        self.ref = GeneratorRef(generator_id=adapter_id, model_id=adapter_id, kind="generative", prompt_hash=inner.ref.prompt_hash)
        self.proposals = 0

    def propose(self, envelope) -> ClaimPlan:
        self.proposals += 1
        plan = self.inner.propose(envelope)
        return ClaimPlan(generator=self.ref, claims=plan.claims)


def FakeAlphaGenerator(inner):  # noqa: N802 - a named generator of family fake-alpha (spec 13.1)
    return FamilyGenerator(inner, "fake-alpha-v1")


def fresh_gateway(units: int = 100000, *, adapters: dict | None = None, clock=None, **kwargs) -> ModelGateway:
    options = {"clock": clock} if clock is not None else {}
    return ModelGateway(budget=DailyBudget(units), adapters=adapters, **options, **kwargs)


def v2_pipeline(settings=None, *, gateway=None, registry=None, cache=None, **kwargs):
    """A two-pass pipeline over the development store with MODEL_GATEWAY=on (unless settings say otherwise), its own
    gateway (a fresh one by default) and its own cold evidential cache."""
    from app.core.config import Settings
    from app.services.retrieval_engine import RetrievalEngine
    from app.services.store import get_course_store
    from app.services.tutor_pipeline.pipeline import TwoPassPipeline
    from app.services.v2_panel.cache import ProcessEvidentialCache

    settings = settings or Settings(model_gateway="on")
    return TwoPassPipeline(RetrievalEngine(get_course_store(), settings), settings, gateway=gateway or fresh_gateway(),
                           adapter_registry=registry, cache=cache if cache is not None else ProcessEvidentialCache(), **kwargs)


@contextmanager
def captured(gateway: ModelGateway):
    """Every request contract the gateway would send while the block runs."""
    previous = gateway.captured
    gateway.captured = []
    try:
        yield gateway.captured
    finally:
        gateway.captured = previous


def adapters_of(registry: AdapterRegistry, **options) -> dict:
    """A scripted fake adapter for every member of a registry; options map an adapter id to its keyword arguments."""
    return {spec.adapter_id: ScriptedFakeAdapter(spec, **options.get(spec.adapter_id, {})) for spec in registry.members}
