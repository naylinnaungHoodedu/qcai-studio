"""Fakes for the Phase 7 EHMF tests (Phase 7 spec 13.1). Not a test module: a typed (ledger-entry-v4) development record,
a negating generator, an unresolvable-then-clean generator, scripted and leaking adapters, a package-directory copy and
the Phase 4 fixture runner loaded by path. No learner data, no network call; nothing is written into the checkout.
"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import shutil
import sys

from app.core.config import Settings
from app.core.config_package import DEFAULT_PACKAGE_PATH, canonical_sha256
from app.gateway.adapters import FakeAdapter
from app.services.tutor_pipeline.contracts import ClaimPlan, ProposedClaim

REPO_ROOT = Path(__file__).resolve().parents[3]
TIER2 = "Why do the sources repeatedly emphasize hybrid loops instead of end-to-end quantum models?"
INVENTED = "span-" + "0" * 64


def scripts_module(name: str):
    """A script under scripts/, loaded by path (once per process)."""
    key = f"ehmf_test_{name}"
    if key not in sys.modules:
        spec = importlib.util.spec_from_file_location(key, REPO_ROOT / "scripts" / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[key] = module
        spec.loader.exec_module(module)
    return sys.modules[key]


def ehmf_settings(ehmf: str = "on", **overrides) -> Settings:
    options = dict(model_gateway="on", ehmf=ehmf)
    options.update(overrides)
    return Settings(**options)


def typed_record(query: str = TIER2, *, settings: Settings | None = None, adapters: dict | None = None, generator=None, checker=None,
                 library=None, cache=None, legacy_decision: str | None = "answer", **kwargs):
    """A development shadow run through v2_fakes.v2_pipeline with EHMF set (on by default)."""
    from v1_fakes import run
    from v2_fakes import fresh_gateway, v2_pipeline

    options = dict(kwargs)
    for name, value in (("generator", generator), ("checker", checker), ("misconceptions", library)):
        if value is not None:
            options[name] = value
    if cache is not None:
        options["cache"] = cache
    pipeline = v2_pipeline(settings or ehmf_settings(), gateway=fresh_gateway(adapters=adapters), **options)
    return run(pipeline, query, legacy_decision=legacy_decision)


class TransformGenerator:
    """The extractive generator with its first claim (that transform changes) rewritten; `attacked` holds (text, spans)."""

    def __init__(self, transform) -> None:
        from app.core.config import Settings as _Settings
        from app.core.config_package import get_config_package
        from app.services.tutor_pipeline.evidential import ExtractiveD19Generator

        self.inner = ExtractiveD19Generator(get_config_package(_Settings()))
        self.ref = self.inner.ref
        self.transform = transform
        self.attacked: tuple[str, tuple[str, ...]] | None = None

    def propose(self, envelope) -> ClaimPlan:
        plan = self.inner.propose(envelope)
        claims = list(plan.claims)
        for index, claim in enumerate(claims):
            changed = self.transform(claim.text)
            if changed and changed != claim.text:
                claims[index] = ProposedClaim(text=changed, span_ids=claim.span_ids)
                self.attacked = (changed, tuple(claim.span_ids))
                break
        return ClaimPlan(generator=plan.generator, claims=tuple(claims))


def negating_generator() -> TransformGenerator:
    from app.core.config_package import get_config_package

    fixtures = scripts_module("run_v1_fixtures")
    lexicon = get_config_package(Settings()).v1.lexicon
    return TransformGenerator(lambda text: fixtures.insert_negation(text, lexicon))


class UnresolvableThenCleanGenerator:
    """Attempt 1: the extractive plan with one claim citing an invented span id (among valid claims); later attempts: the
    plan with that claim left out. always=True cites the invented id on every claim of every attempt."""

    def __init__(self, *, always: bool = False) -> None:
        from app.core.config_package import get_config_package
        from app.services.tutor_pipeline.evidential import ExtractiveD19Generator

        self.inner = ExtractiveD19Generator(get_config_package(Settings()))
        self.ref = self.inner.ref
        self.always = always
        self.proposals = 0

    def propose(self, envelope) -> ClaimPlan:
        self.proposals += 1
        plan = self.inner.propose(envelope)
        claims = list(plan.claims)
        if self.always:
            claims = [ProposedClaim(text=claim.text, span_ids=(INVENTED,)) for claim in claims]
        elif self.proposals == 1:
            claims[-1] = ProposedClaim(text=claims[-1].text, span_ids=(INVENTED,))
        else:
            claims = claims[:-1]
        return ClaimPlan(generator=plan.generator, claims=tuple(claims))


def scripted_adapters(verdict: tuple | None = None, *, alignment: dict | None = None, registry=None) -> dict:
    """A fake per member of the development registry, every pair scripted with `verdict` (None: the verbatim rule)."""
    from app.core.config_package import get_config_package
    from app.gateway.registry import registry_for

    settings = ehmf_settings()
    registry = registry or registry_for(get_config_package(settings), settings)
    script = {"*": tuple(verdict)} if verdict is not None else None
    return {spec.adapter_id: FakeAdapter(spec, script=script, alignment=alignment) for spec in registry.members}


class LeakOnceAdapter(FakeAdapter):
    """An alignment member that flags leakage on its first alignment call only."""

    def align(self, request):
        result = super().align(request)
        self.aligned = getattr(self, "aligned", 0) + 1
        if self.aligned == 1:
            result = dict(result, leakage=True)
        return result


def leaking_alignment() -> dict:
    from app.core.config_package import get_config_package
    from app.gateway.registry import registry_for

    settings = ehmf_settings()
    registry = registry_for(get_config_package(settings), settings)
    return {spec.adapter_id: (LeakOnceAdapter(spec) if index == 0 else FakeAdapter(spec)) for index, spec in enumerate(registry.members)}


def package_copy(tmp_path: Path, edit=None, *, library_edit=None) -> Path:
    """A copy of the shipped package directory (v6.json, misconceptions/, schemas/) in tmp_path: edit(raw) changes the
    package, library_edit(raw) the library (its sidecar and the package pin re-hashed); the package sidecar is re-hashed."""
    source = DEFAULT_PACKAGE_PATH.parent
    target = tmp_path / "package"
    shutil.copytree(source / "schemas", target / "schemas")
    shutil.copytree(source / "misconceptions", target / "misconceptions")
    raw = copy.deepcopy(json.loads(DEFAULT_PACKAGE_PATH.read_text(encoding="utf-8")))
    if library_edit is not None:
        library_path = target / raw["v1"]["v1_8"]["library"]["path"]
        library = json.loads(library_path.read_text(encoding="utf-8"))
        library_edit(library)
        library_path.write_text(json.dumps(library, indent=2) + "\n", encoding="utf-8")
        digest = canonical_sha256(library)
        library_path.with_name(library_path.name + ".sha256").write_text(digest + "\n", encoding="utf-8")
        raw["v1"]["v1_8"]["library"]["sha256"] = digest
    if edit is not None:
        edit(raw)
    path = target / DEFAULT_PACKAGE_PATH.name
    path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    path.with_name(path.name + ".sha256").write_text(canonical_sha256(raw) + "\n", encoding="utf-8")
    return path
