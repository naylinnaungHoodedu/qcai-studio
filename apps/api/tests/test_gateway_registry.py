"""Phase 5 adapter registry and the loader's gateway refusals (plan Phase 5 tasks 5.1, 5.10; D-07, D-12, Q-09, A-15 open;
AC-5-10; Phase 5 spec 4.1, 4.2, 5.2)."""

from __future__ import annotations

import copy
import json

import pytest

from app.core.config import Settings
from app.core.config_package import DEFAULT_PACKAGE_PATH, ConfigPackageError, get_config_package, parse_config_package
from app.gateway.registry import GeneratorFamilyUnknown, generator_family, registry_for

RAW = json.loads(DEFAULT_PACKAGE_PATH.read_text(encoding="utf-8"))
PACKAGE = get_config_package(Settings())
HTTP_MEMBER = {"adapter_id": "test-http-v1", "family": "test-family", "provider": "test-provider", "model_id": "test-model",
               "model_version": "2026-11-21", "capabilities": ["verify"], "caps": {"max_tokens": 256, "timeout_ms": 500, "max_retries": 1},
               "cost_units_per_call": 1, "endpoint": "https://verifier.invalid/v1", "auth_header": "x-api-key", "secret_ref": "TEST_KEY"}


def parse(edit=None):
    raw = copy.deepcopy(RAW)
    if edit is not None:
        edit(raw)
    return parse_config_package(raw, path=DEFAULT_PACKAGE_PATH, sha256="0" * 64, hash_verified=False)


def refused(edit, match: str) -> None:
    with pytest.raises(ConfigPackageError, match=match):
        parse(edit)


def dev(raw):
    return raw["gateway"]["registries"]["development"]


def test_each_environment_reads_its_registry_and_an_unknown_one_reads_default():
    for environment, name, members in (("development", "development", 4), ("production", "production", 0), ("staging", "staging", 0),
                                       ("preview-7", "default", 0)):
        registry = registry_for(PACKAGE, Settings.model_construct(environment=environment))
        assert (registry.name, len(registry.members)) == (name, members), environment
    development = registry_for(PACKAGE, Settings())
    assert development.families() == ("fake-alpha", "fake-beta", "fake-gamma", "fake-delta")
    assert [spec.adapter_id for spec in development.verifiers()] == ["fake-alpha-v1", "fake-beta-v1", "fake-gamma-v1", "fake-delta-v1"]
    assert all(spec.provider == "fake" and spec.model_version == "2026-11-21" for spec in development.members)


def test_the_generator_family_comes_from_the_package_or_a_generate_capable_adapter():
    registry = registry_for(PACKAGE, Settings())
    assert generator_family(PACKAGE, registry, "extractive-d19-v1") == "extractive-d19"
    assert generator_family(PACKAGE, registry, "fake-delta-v1") == "fake-delta"
    for unknown in ("fake-alpha-v1", "another-generator"):
        with pytest.raises(GeneratorFamilyUnknown):
            generator_family(PACKAGE, registry, unknown)


def test_every_gateway_refusal_of_the_loader_is_structural():
    refused(lambda raw: dev(raw)[0].update(model_version="latest"), "unpinned")
    refused(lambda raw: dev(raw)[0].pop("model_version"), "unpinned: lacks a version")
    refused(lambda raw: dev(raw)[0].update(model_id="fake-alpha-preview"), "unpinned")
    refused(lambda raw: raw["gateway"]["registries"]["production"].append(HTTP_MEMBER), "non-fake provider|must be empty")
    refused(lambda raw: dev(raw).append(HTTP_MEMBER), "no non-fake provider")
    refused(lambda raw: raw["gateway"]["registries"]["staging"].append(dict(dev(raw)[0], adapter_id="fake-x-v1")), "must be empty")
    refused(lambda raw: dev(raw).append(dict(dev(raw)[0])), "listed twice")
    refused(lambda raw: dev(raw)[0].update(adapter_id="Fake_Alpha"), "adapter_id")
    refused(lambda raw: dev(raw)[0].update(capabilities=["rank"]), "capabilities")
    refused(lambda raw: dev(raw)[0]["caps"].update(max_tokens=0), "max_tokens")
    refused(lambda raw: dev(raw)[0]["caps"].update(timeout_ms=10), "timeout_ms")
    refused(lambda raw: dev(raw)[0]["caps"].update(max_retries=3), "max_retries")
    refused(lambda raw: dev(raw)[0]["caps"].update(timeout_ms=1500, max_retries=2), "shadow_ms")
    refused(lambda raw: dev(raw)[0].update(cost_units_per_call=-1), "cost_units_per_call")
    refused(lambda raw: dev(raw)[0].update(fake={"rule": "always-yes"}), "wired fake rule")
    refused(lambda raw: dev(raw)[0].update(endpoint="https://x.invalid/v1"), "no endpoint")
    refused(lambda raw: raw["gateway"]["registries"].update(preview=[]), "names only")
    refused(lambda raw: raw["gateway"]["budgets"]["daily_units"].update(production=10), "while A-15 is open")
    refused(lambda raw: raw["gateway"]["budgets"]["alert_share"].update(numerator=3), "4/5")
    refused(lambda raw: raw["gateway"]["cache"]["max_entries"].update(verdict=0), "verdict")
    refused(lambda raw: raw["gateway"].update(retired_settings=["VERTEX_AI_API_KEY"]), "retired_settings")
    refused(lambda raw: raw["gateway"].update(terms={"provider": "x"}), "terms must be null")
    refused(lambda raw: raw["gateway"]["egress"].update(default=["x"]), "default")
    refused(lambda raw: raw["gateway"].update(provisional=False), "provisional")
    refused(lambda raw: raw["gateway"]["stop"].update(on=["budget_breach"]), "stop.on")
    refused(lambda raw: raw["gateway"]["payload_policy"].update(on_violation="log"), "on_violation")
    refused(lambda raw: raw["owner_decisions"].pop("Q-09"), "Q-09")


def embeddings(raw):
    return raw["gateway"]["embeddings"]


def test_the_embedding_entry_is_versioned_configuration_and_names_no_unpinned_model():
    # Plan 5.10 "Token, timeout and retry caps" and D-07's pinning rule for the gateway's embedding egress: its model,
    # caps and cost are package v4's gateway.embeddings (provisional, PD-26), and no model is named while the provider
    # gates are open; an unpinned one stops the load (AC-5-10).
    spec = PACKAGE.gateway.embeddings
    assert (spec.provider, spec.secret_ref, spec.model_id, spec.model_version) == ("openai-embeddings", "OPENAI_API_KEY", None, None)
    assert (spec.caps.max_items, spec.caps.max_input_chars, spec.caps.timeout_ms, spec.caps.max_retries, spec.cost_units_per_item) == (
        256, 8000, 10000, 2, 1)
    assert RAW["gateway"]["embeddings"]["provisional"] is True and RAW["gateway"]["embeddings"]["record"] == "PD-26"
    refused(lambda raw: raw["gateway"].pop("embeddings"), "embeddings")
    refused(lambda raw: embeddings(raw).update(provisional=False), "provisional")
    refused(lambda raw: embeddings(raw).update(provider="other"), "provider openai-embeddings")
    refused(lambda raw: embeddings(raw).update(secret_ref="OTHER_KEY"), "secret_ref")
    refused(lambda raw: embeddings(raw).pop("model_version"), "model_version")
    refused(lambda raw: embeddings(raw).update(model_id="text-embedding-3-small"), "unpinned: lacks a version")
    refused(lambda raw: embeddings(raw).update(model_id="text-embedding-latest", model_version="2024-01-25"), "unpinned")
    refused(lambda raw: embeddings(raw).update(model_id="text-embedding-3-small", model_version="2024-01-25"), "names no model while")
    for key, value in (("max_items", 0), ("max_input_chars", 0), ("timeout_ms", 10), ("max_retries", 3)):
        refused(lambda raw, key=key, value=value: embeddings(raw)["caps"].update({key: value}), key)
    refused(lambda raw: embeddings(raw).update(cost_units_per_item=0), "cost_units_per_item")
    # With every gate settled a pinned model loads.
    pinned = parse(lambda raw: (settle(raw), embeddings(raw).update(model_id="text-embedding-3-small", model_version="2024-01-25")))
    assert (pinned.gateway.embeddings.model_id, pinned.gateway.embeddings.model_version) == ("text-embedding-3-small", "2024-01-25")


def settle(raw, *, review: bool = True):
    for name in ("D-12", "D-07"):
        raw["owner_decisions"][name]["state"] = "decided"
    raw["owner_decisions"]["Q-09"]["state"] = "resolved"
    if review:
        raw["owner_decisions"]["Q-15"]["state"] = "reviewed"


def test_a_non_fake_member_waits_for_the_q_15_payload_review_as_the_embedding_egress_does():
    # The payload register: "no non-fake adapter may be registered before the review" (Q-15, DI-71). The loader and the
    # embedding egress share one rule (app.gateway.registry.providers_open).
    from app.gateway.embeddings import providers_open
    from app.gateway.registry import providers_open as gates_open

    refused(lambda raw: (settle(raw, review=False), dev(raw).append(dict(HTTP_MEMBER))), "Q-15 payload review is pending")
    refused(lambda raw: (settle(raw, review=False), raw["gateway"]["registries"]["staging"].append(dict(HTTP_MEMBER))),
            "must be empty while .* Q-15")
    pending = parse(lambda raw: settle(raw, review=False))
    assert gates_open(pending.owner_decisions) and providers_open(pending)
    assert not gates_open(parse(settle).owner_decisions)
    assert gates_open({**parse(settle).owner_decisions, "D-12": None}), "a decision the package does not hold is open"


def test_a_non_fake_member_loads_only_once_every_provider_decision_is_settled():
    def settled(raw):
        settle(raw)
        dev(raw).append(dict(HTTP_MEMBER))

    package = parse(settled)
    spec = package.gateway.registries["development"][-1]
    assert (spec.provider, spec.endpoint, spec.secret_ref) == ("test-provider", "https://verifier.invalid/v1", "TEST_KEY")
    for endpoint in ("https://verifier.invalid/v1?key=1", "http://verifier.invalid/v1", "https://u:p@verifier.invalid/v1"):
        refused(lambda raw, endpoint=endpoint: (settled(raw), dev(raw)[-1].update(endpoint=endpoint)), "endpoint")
    refused(lambda raw: (settled(raw), dev(raw)[-1].update(secret_ref="lower_case")), "secret_ref")
    # With every provider decision settled, a fake member is still refused outside development.
    refused(lambda raw: (settled(raw), raw["gateway"]["registries"]["staging"].append(dict(dev(raw)[0], adapter_id="fake-x-v1"))),
            "development only")
