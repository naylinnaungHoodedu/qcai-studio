"""The Phase 3 contracts and their committed schemas (plan Phase 3 F "versioned schemas"; spec 3, 5.4, 13.2)."""

from __future__ import annotations

import json
import math

from pydantic import ValidationError
import pytest

from app.core.config import Settings
from app.core.config_package import get_config_package
from app.services.tutor_pipeline import contracts
from app.services.tutor_pipeline.contracts import (
    SCHEMA_MODELS,
    ClaimLedgerEntry,
    ConfigStamp,
    EvidenceBundle,
    LedgerEntry,
    LockedClaim,
    LockedClaimSet,
    LockedClaimSetTampered,
    PipelineCounts,
    Provenance,
    ResolverRef,
    RetrievalRecord,
    Sufficiency,
    VersionStamps,
    BudgetStamp,
    ledger_canonical,
    lock_hash,
    verify_locked,
)
from app.services.tutor_pipeline.package_check import check_tutor_pipeline_package, schema_path

H = "a" * 64
SPAN_A = "span-" + "1" * 64
SPAN_B = "span-" + "2" * 64
TURN = "turn-12345678-1234-1234-1234-123456789abc"
SHADOW = "shadow-12345678-1234-1234-1234-123456789abc"


def test_the_committed_schemas_match_the_models_and_their_pins():
    package = get_config_package(Settings())
    assert check_tutor_pipeline_package(package, structural=True) == []
    assert set(package.tutor_pipeline.schemas) == set(SCHEMA_MODELS)
    for name, pin in package.tutor_pipeline.schemas.items():
        committed = json.loads(schema_path(package, pin.path).read_text(encoding="utf-8"))
        assert committed.get("additionalProperties") is False, name


def test_a_changed_schema_file_or_prompt_hash_is_a_package_problem(tmp_path):
    import shutil

    package = get_config_package(Settings())
    shutil.copytree(package.path.parent / "schemas", tmp_path / "schemas")
    raw = json.loads(package.path.read_text(encoding="utf-8"))
    (tmp_path / "v2.json").write_text(json.dumps(raw), encoding="utf-8")
    from app.core.config_package import load_config_package

    copy = load_config_package(tmp_path / "v2.json", governed=False)
    assert check_tutor_pipeline_package(copy, structural=True) == []
    target = tmp_path / package.tutor_pipeline.schemas["RetrievalRequest"].path
    schema = json.loads(target.read_text(encoding="utf-8"))
    schema["properties"]["page_path"] = {"type": "string"}
    target.write_text(json.dumps(schema), encoding="utf-8")
    problems = check_tutor_pipeline_package(copy, structural=True)
    assert any("RetrievalRequest" in problem and "sha256" in problem for problem in problems)
    assert any("structure differs" in problem for problem in problems)
    raw["tutor_pipeline"]["resolver"]["prompt_hash"] = "b" * 64
    (tmp_path / "v2.json").write_text(json.dumps(raw), encoding="utf-8")
    assert any("resolver prompt hash" in problem for problem in check_tutor_pipeline_package(load_config_package(tmp_path / "v2.json", governed=False), structural=False))


def _locked(**overrides) -> LockedClaimSet:
    claims = (
        LockedClaim(claim_id="claim-" + "1" * 32, text="Routing adds SWAP gates.", span_ids=(SPAN_A,), source_order=("item-a", 10)),
        LockedClaim(claim_id="claim-" + "2" * 32, text="Depth grows with SWAPs.", span_ids=(SPAN_A, SPAN_B), source_order=("item-a", 10)),
    )
    fields = dict(
        claims=claims,
        span_ids=(SPAN_A, SPAN_B),
        corpus_version="corpus-x",
        index_version="index-x",
        generator=None,
        evidential_prompt_hash=None,
        pedagogical_prompt_hash=H,
        resolver=ResolverRef(model_id="thread-resolver-v1", prompt_hash=H),
        config_package=ConfigStamp(version="2.0.0", sha256=H),
    )
    fields.update(overrides)
    draft = LockedClaimSet.model_construct(**fields, claim_set_hash="0" * 64)
    return LockedClaimSet.model_validate({**draft.model_dump(mode="json"), "claim_set_hash": lock_hash(draft)})


def test_contracts_are_frozen_and_refuse_unknown_fields():
    locked = _locked()
    with pytest.raises(ValidationError):
        locked.corpus_version = "other"  # frozen
    for model in SCHEMA_MODELS.values():
        assert model.model_config["extra"] == "forbid" and model.model_config["frozen"] is True


def test_the_locked_claim_set_refuses_a_wrong_hash_or_span_set_and_verify_catches_a_model_copy():
    locked = _locked()
    payload = locked.model_dump(mode="json")
    with pytest.raises(ValidationError, match="claim_set_hash"):
        LockedClaimSet.model_validate({**payload, "claim_set_hash": "b" * 64})
    with pytest.raises(ValidationError, match="span_ids"):
        LockedClaimSet.model_validate({**payload, "span_ids": [SPAN_A]})
    verify_locked(locked)
    tampered = locked.model_copy(update={"claims": locked.claims[:1]})
    with pytest.raises(LockedClaimSetTampered):
        verify_locked(tampered)
    edited = locked.model_copy(update={"corpus_version": "corpus-y"})
    with pytest.raises(LockedClaimSetTampered, match="claim_set_hash"):
        verify_locked(edited)


def _provenance() -> Provenance:
    return Provenance(generator_model_id="m", evidential_prompt_hash=H, pedagogical_prompt_hash=None, corpus_version="c", threshold_set_version="t")


def _entry(**overrides) -> dict:
    provenance = _provenance()
    response_id = overrides.get("response_id", TURN)
    claim = ClaimLedgerEntry(claim_id="claim-" + "1" * 32, response_id=response_id, text="A sentence.", span_ids=(SPAN_A,), provenance=provenance)
    base = dict(
        response_id=response_id,
        delivery="legacy",
        shadowed_response_id=None,
        pipeline="legacy-contained-v1",
        decision="answer",
        abstention_reason=None,
        resolved_question=None,
        retrieval=RetrievalRecord(corpus_version="c", index_version="i", gate="p1-floor", threshold_version="t", floor=6.0, margin=0.0,
                                  mode="lexical", evidence_scope="delivered_citations", sufficiency=None, evidence=()),
        claim_set_hash=None,
        claims=(claim,),
        span_ids=(SPAN_A,),
        presentation=None,
        rendered_text_sha256=H,
        provenance=provenance,
        versions=VersionStamps(pipeline_version="legacy-contained-v1", code_sha="x", schema_revision_expected="r", config_package_version="2.0.0",
                               config_package_sha256=H, manifest_sha256=None, span_scheme="span-v2", policy_version="p", resolver_id=None,
                               generator_id=None, renderer_id=None, budgets=BudgetStamp(shadow_ms=None, ledger_append_ms=1500)),
        counts=PipelineCounts(proposed_claims=1, bound_claims=1, dropped={}, render_attempts=0),
    )
    base.update(overrides)
    return base


def test_ledger_entry_rules_hold_both_ways():
    assert LedgerEntry(**_entry()).delivery == "legacy"
    shadow_claim = ClaimLedgerEntry(claim_id="claim-" + "1" * 32, response_id=SHADOW, text="A sentence.", span_ids=(SPAN_A,), provenance=_provenance())
    assert LedgerEntry(**_entry(response_id=SHADOW, delivery="shadow", shadowed_response_id=TURN, claims=(shadow_claim,))).delivery == "shadow"
    refused = [
        _entry(delivery="shadow"),  # a shadow record needs a shadow- id and the turn it shadowed
        _entry(shadowed_response_id=TURN),  # a legacy record shadows nothing
        _entry(delivery="delivered"),  # Phase 4's, refused before TWO_PASS_DELIVERY_IMPLEMENTED
        _entry(decision="abstain"),  # an abstention needs a reason
        _entry(abstention_reason="no_match"),  # and only an abstention has one
        _entry(decision="abstain", abstention_reason="made_up_reason"),
        _entry(span_ids=(SPAN_A, SPAN_B)),  # not the union of the claims' spans
        _entry(decision="answer", claims=(), span_ids=()),  # an answer has claims
        _entry(rendered_text_sha256=None),
        _entry(verification={"v1": "pass"}),  # no verdict exists before Phase 4
    ]
    for payload in refused:
        with pytest.raises(ValidationError):
            LedgerEntry(**payload)
    other = ClaimLedgerEntry(claim_id="claim-" + "1" * 32, response_id=SHADOW, text="A sentence.", span_ids=(SPAN_A,), provenance=_provenance())
    with pytest.raises(ValidationError, match="another response"):
        LedgerEntry(**_entry(claims=(other,)))
    assert contracts.TWO_PASS_DELIVERY_IMPLEMENTED is False


def test_counts_reconcile_and_the_bound_claim_ratio_terms_leave_skipped_claims_out():
    # Review 2026-11-19: every proposed claim is locked or dropped under exactly one known reason.
    def counts(proposed, bound, dropped):
        return PipelineCounts(proposed_claims=proposed, bound_claims=bound, dropped=dropped, render_attempts=0)

    assert contracts.bound_claim_ratio_terms(counts(3, 0, {"budget_exceeded": 3})) == (0, 0)  # bind never ran: no ratio
    assert contracts.bound_claim_ratio_terms(counts(3, 2, {"merged": 1})) == (3, 3)  # a merged claim did bind
    assert contracts.bound_claim_ratio_terms(counts(3, 2, {"duplicate": 1})) == (3, 3)  # so did a duplicate (spec 18.12 J1)
    assert contracts.bound_claim_ratio_terms(counts(4, 2, {"merged": 1, "unbound": 1})) == (4, 3)
    assert contracts.bound_claim_ratio_terms(counts(2, 1, {"unresolved_citation": 1})) == (2, 1)  # legacy
    assert contracts.bound_claim_ratio_terms(counts(0, 0, {})) == (0, 0)
    for proposed, bound, dropped, message in ((3, 0, {}, "proposed_claims"), (1, 2, {}, "proposed_claims"),
                                              (2, 1, {"rebound": 1}, "unknown drop reasons"), (1, 1, {"unbound": 0}, "positive count")):
        with pytest.raises(ValidationError, match=message):
            counts(proposed, bound, dropped)
    # not_public (2026-11-19 hardening): a delivered legacy quotation whose span's derived license class is not public.
    # duplicate (spec 18.12 J1) left the binding failures: it bound, as a merged claim did.
    assert "duplicate" not in contracts.BINDING_FAILURES
    assert set(contracts.DROP_REASONS) == {*contracts.BINDING_FAILURES, "merged", "duplicate", "budget_exceeded", "unresolved_citation", "not_public"}
    with pytest.raises(ValidationError, match="counts.bound_claims"):
        LedgerEntry(**_entry(counts=counts(2, 2, {})))  # two counted, one recorded


def test_the_bundle_refuses_conflicts_before_phase_4():
    sufficiency = Sufficiency(score=None, gate="p1-floor", threshold_version="t", floor=6.0, margin=0.0, decision="abstain", reason="no_match")
    with pytest.raises(ValidationError, match="Phase 4"):
        EvidenceBundle(corpus_version="c", index_version="i", retrieval_mode="lexical", spans=(), sufficiency=sufficiency, conflicts=("x",))
    with pytest.raises(ValidationError):
        EvidenceBundle(corpus_version="c", index_version="i", retrieval_mode="hybrid", spans=(), sufficiency=sufficiency)


def test_ledger_canonical_is_stable_and_refuses_nan():
    assert ledger_canonical({"b": 1, "a": [1.5, "é"]}) == '{"a":[1.5,"é"],"b":1}'.encode("utf-8")
    with pytest.raises(ValueError):
        ledger_canonical({"score": math.nan})
