"""Phase 5 ledger records: VerificationRecordV2 and LedgerEntryV3 (plan 7.4 VerificationVerdict v2; E10 "additive record
version"; invariants 3, 4, 6, 10; Phase 5 spec 3.3, 7.3, 8)."""

from __future__ import annotations

from collections.abc import Iterator
import copy
import json

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.core.config_package import get_config_package
from app.core.db import Base
from app.core.schema_upgrades import run_schema_upgrades
from app.db_models import ResponseLedgerRecord
from app.services import ledger
from app.services.tutor_pipeline import contracts
from app.services.tutor_pipeline.contracts import LedgerEntryV2, LedgerEntryV3, VerificationRecord, VerificationRecordV2
from app.services.tutor_pipeline.package_check import model_schema
from v1_fakes import MULTI_CLAIM, dev_pipeline, run
from v2_fakes import adapters_of, claim_key, fresh_gateway, make_registry, v2_pipeline

TIER2 = "Why do the sources repeatedly emphasize hybrid loops instead of end-to-end quantum models?"
PACKAGE = get_config_package(Settings())
REGISTRY = make_registry(("fake-alpha", "fake-beta", "fake-gamma"))


@pytest.fixture
def isolated(fresh_database_url) -> Iterator[tuple]:
    engine = create_engine(fresh_database_url)
    Base.metadata.create_all(engine)
    run_schema_upgrades(engine)
    try:
        yield engine, sessionmaker(bind=engine)
    finally:
        engine.dispose()


def on_record(**kwargs):
    """An on-mode record of TIER2 in which every member contradicts the second claim (abstained with X2)."""
    claims = run(dev_pipeline(), TIER2).locked.claims
    script = {claim_key(claims[1].text, span_id): ("CONTRADICTED", "A") for span_id in claims[1].span_ids}
    adapters = adapters_of(REGISTRY, **{spec.adapter_id: {"script": script} for spec in REGISTRY.members})
    return run(v2_pipeline(gateway=fresh_gateway(adapters=adapters), registry=REGISTRY, **kwargs), TIER2, legacy_decision="answer")


def refused(payload: dict, edit, match: str, model=VerificationRecordV2) -> None:
    changed = copy.deepcopy(payload)
    edit(changed)
    with pytest.raises(ValidationError, match=match):
        model.model_validate(changed)


def test_every_verification_record_v2_rule_refuses_its_inconsistency():
    record = on_record().entry.verification
    payload = record.model_dump(mode="json")
    assert VerificationRecordV2.model_validate(payload) == record
    judged = [index for index, verdict in enumerate(payload["verdicts"]) if verdict["v2"] is not None]
    delivered = next(index for index in judged if payload["verdicts"][index]["final"] == "deliver")
    failed = next(index for index in judged if payload["verdicts"][index]["v2"]["outcome"] == "fail")

    def verdict(index):
        return lambda raw: raw["verdicts"][index]

    refused(payload, lambda raw: raw["verdicts"][delivered]["v2"].update(generator_family="fake-alpha"), "generator's family")
    refused(payload, lambda raw: raw["verdicts"][delivered]["v2"].update(mode="REDUCED-2"), "the mode is the one")
    refused(payload, lambda raw: raw["verdicts"][delivered]["v2"].update(rule="1oo3"), "the rule is the routing table")
    refused(payload, lambda raw: raw["verdicts"][delivered]["v2"].update(objections=1), "the objections, split and outcome")
    refused(payload, lambda raw: raw["verdicts"][delivered]["v2"].update(outcome="fail"), "objections, split and outcome")
    refused(payload, lambda raw: raw["verdicts"][delivered]["v2"]["votes"][0].update(verifier_prompt_hash="0" * 64), "verifier prompt hash")
    refused(payload, lambda raw: raw["verdicts"][delivered]["v2"]["votes"].append(dict(raw["verdicts"][delivered]["v2"]["votes"][0])),
            "one vote per family and span")
    refused(payload, lambda raw: raw["verdicts"][failed].update(final="withhold"), "not abstained with X2")
    refused(payload, lambda raw: raw["verdicts"][failed]["v3"].update(escalation=None), "X2 escalation is set exactly")
    refused(payload, lambda raw: raw["v2"].update(cycles=1, corrections=raw["v2"]["corrections"][:1]), "X2 escalation follows the last")
    refused(payload, lambda raw: raw["v2"].update(corrections=[]), "the corrections are the cycles")
    refused(payload, lambda raw: raw["v2"].update(shadow={"would_deliver": 1, "would_fail": 0, "would_withhold": 0}), "no would-summary")
    refused(payload, lambda raw: raw.update(labels=[*raw["labels"], "degraded"]), "degraded label")
    refused(payload, lambda raw: raw["v2"].update(banner="degraded-zero-v1"), "banner")
    refused(payload, lambda raw: raw["v2"].update(degraded_mode="ZERO"), "worst mode")
    refused(payload, lambda raw: raw["v2"].update(panel_reached=False), "never reached")
    refused(payload, lambda raw: raw["v2"].update(members=["extractive-d19", "fake-alpha"]), "excludes the generator")
    refused(payload, lambda raw: raw["v2"].update(kill_switch="abstain_only"), "kill switch")
    refused(payload, lambda raw: raw.update(final="correct"), "correct")
    # A delivered claim must hold a passing V2 vote; outside on, a V1.3 flag keeps it from delivery (D-20).
    refused(payload, lambda raw: raw["verdicts"][delivered].update(v2=None), "passing V2 vote")
    shadowed = copy.deepcopy(payload)
    shadowed["v2"].update(mode="shadow", cycles=0, corrections=[], shadow={"would_deliver": 0, "would_fail": 0, "would_withhold": 0})
    for item in shadowed["verdicts"]:
        if item["v3"] is not None:
            item["v3"]["escalation"] = None
    with pytest.raises(ValidationError, match="V1 result that is not pass|escalation"):
        VerificationRecordV2.model_validate(shadowed)


def test_v2_never_overwrites_a_v1_hard_fail_and_v2_reasons_belong_to_the_v2_record_only():
    record = on_record().entry.verification
    payload = record.model_dump(mode="json")
    refused(payload, lambda raw: raw.update(hard_fail=True), "V2 never overwrites a V1 decision|hard fail is final")
    phase4 = run(dev_pipeline(), TIER2, legacy_decision="answer").entry.verification
    v4 = phase4.model_dump(mode="json")
    for reason in ("v2_correction_exhausted", "v2_alignment_failed", "v2_degraded_withheld", "v2_kill_switch"):
        refused(v4, lambda raw, reason=reason: raw.update(final_reason=reason), "unknown final_reason", model=VerificationRecord)
    with pytest.raises(ValidationError, match="correct"):
        VerificationRecord.model_validate({**v4, "final": "correct"})


def test_the_factored_phase_4_rules_are_unchanged_with_their_defaults():
    from app.services.tutor_pipeline.contracts import PHASE4_FINAL_REASONS, verification_problems

    phase4 = run(dev_pipeline(), MULTI_CLAIM, legacy_decision="answer").entry.verification
    assert verification_problems(phase4) == []
    assert PHASE4_FINAL_REASONS == (*contracts.ABSTENTION_REASONS, *contracts.V1_ABSTENTION_REASONS, *contracts.V1_WITHHOLD_REASONS)
    delivered = phase4.model_copy(update={"final": "deliver", "final_reason": None, "replacement": "none",
                                          "verdicts": tuple(verdict.model_copy(update={"final": "deliver"}) for verdict in phase4.verdicts)})
    assert any("delivered despite a V1 result" in problem for problem in verification_problems(delivered))
    assert verification_problems(delivered, v1_3_routed=lambda verdict: True) == []


def test_ledger_entry_v3_rules_and_the_on_record_s_decision_follows_its_final():
    result = on_record()
    entry = result.entry
    assert isinstance(entry, LedgerEntryV3) and entry.entry_schema == "ledger-entry-v3"
    assert entry.provenance.tool_contract_version == "mcp-tools-v1" and entry.provenance.routing_table_version == "degraded-matrix-v1"
    payload = entry.model_dump(mode="json")
    assert LedgerEntryV3.model_validate(payload) == entry
    refused(payload, lambda raw: (raw["provenance"].update(tool_contract_version="mcp-tools-v0"),
                                  [claim["provenance"].update(tool_contract_version="mcp-tools-v0") for claim in raw["claims"]]),
            "provenance.tool_contract_version", model=LedgerEntryV3)
    refused(payload, lambda raw: raw["verification"]["verdicts"][0]["v2"]["votes"][0].update(span_id="span-" + "c" * 64),
            "every vote names one of its claim's spans|objections", model=LedgerEntryV3)
    # The on record abstains exactly when its final does.
    leaky = adapters_of(REGISTRY, **{"fake-alpha-v1": {"alignment": {"rating": 2, "leakage": True}}})
    abstained = run(v2_pipeline(gateway=fresh_gateway(adapters=leaky), registry=REGISTRY), TIER2).entry
    assert (abstained.decision, abstained.abstention_reason, abstained.verification.final) == ("abstain", "v2_alignment_failed", "abstain")
    assert "v2_alignment_failed" in contracts.ACCEPTED_ABSTENTION_REASONS["ledger-entry-v3"]
    assert "v2_alignment_failed" not in contracts.ACCEPTED_ABSTENTION_REASONS["ledger-entry-v2"]
    assert contracts.ENTRY_SCHEMAS["ledger-entry-v3"] is LedgerEntryV3 and contracts.SCHEMA_MODELS["LedgerEntryV3"] is LedgerEntryV3
    assert model_schema("LedgerEntryV3")["properties"]["entry_schema"]["const"] == "ledger-entry-v3"
    assert model_schema("V2VerdictRequest")["properties"]["item"]["const"] == "claim"


def test_a_mixed_v1_v2_v3_chain_verifies_exports_restores_and_its_v3_intents_carry_the_escalation(isolated, tmp_path):
    from tutor_fakes import make_entry

    engine, factory = isolated
    ledger.append_ledger_entry(make_entry(), session_factory=factory, budget_ms=5000)
    run(dev_pipeline(Settings(model_gateway="off"), session_factory=factory), MULTI_CLAIM, record=True, legacy_decision="answer")
    v3 = on_record(session_factory=factory)
    appended = ledger.append_ledger_entry(v3.entry, session_factory=factory, budget_ms=5000)
    assert appended.seq == 3
    with factory() as db:
        schemas = [row.entry_schema for row in db.scalars(select(ResponseLedgerRecord).order_by(ResponseLedgerRecord.seq))]
        assert schemas == ["ledger-entry-v1", "ledger-entry-v2", "ledger-entry-v3"]
        assert ledger.verify_response_ledger(db).ok
        exported = tmp_path / "ledger.jsonl"
        assert ledger.export_ledger(db, exported) == 3
        intents = ledger.pending_v3_intents(db)
        provenance = ledger.ledger_provenance(db, PACKAGE)
    assert provenance["problem_count"] == 0, provenance["problems"]
    v2_items = [item for item in intents if item["seq"] == 2]
    v3_items = [item for item in intents if item["seq"] == 3]
    assert v2_items and all("escalation" not in item for item in v2_items)
    assert any(item["escalation"] == "X2" for item in v3_items) and all("escalation" in item for item in v3_items)
    restored = create_engine(f"sqlite:///{(tmp_path / 'restored.db').as_posix()}")
    try:
        Base.metadata.create_all(restored)
        run_schema_upgrades(restored)
        with sessionmaker(bind=restored)() as db:
            assert ledger.restore_ledger(db, exported)[0] == 3 and ledger.verify_response_ledger(db).ok
    finally:
        restored.dispose()


def test_a_mixed_v1_to_v4_chain_verifies_exports_restores_and_reads_its_config_versions(isolated, tmp_path):
    # Phase 7 (spec 8, E2): ledger-entry-v4 is additive. A chain of v1, v2, v3 and v4 records verifies, passes the
    # provenance audit, exports with each line's read-time config_version and restores into a fresh database, where it
    # verifies again with the same records.
    from ehmf_fakes import SHIPPED_VERSION, typed_record
    from tutor_fakes import make_entry

    engine, factory = isolated
    ledger.append_ledger_entry(make_entry(), session_factory=factory, budget_ms=5000)
    run(dev_pipeline(Settings(model_gateway="off"), session_factory=factory), MULTI_CLAIM, record=True, legacy_decision="answer")
    ledger.append_ledger_entry(on_record().entry, session_factory=factory, budget_ms=5000)
    typed = typed_record().entry
    assert typed.entry_schema == "ledger-entry-v4"
    ledger.append_ledger_entry(typed, session_factory=factory, budget_ms=5000)
    with factory() as db:
        rows = list(db.scalars(select(ResponseLedgerRecord).order_by(ResponseLedgerRecord.seq)))
        assert [row.entry_schema for row in rows] == ["ledger-entry-v1", "ledger-entry-v2", "ledger-entry-v3", "ledger-entry-v4"]
        assert ledger.verify_response_ledger(db).ok
        provenance = ledger.ledger_provenance(db, PACKAGE)
        exported = tmp_path / "ledger.jsonl"
        assert ledger.export_ledger(db, exported) == 4
        hashes = [row.record_hash for row in rows]
    assert provenance["problem_count"] == 0, provenance["problems"]
    lines = [json.loads(line) for line in exported.read_text(encoding="utf-8").splitlines()]
    expected = [ledger.config_version_of(json.loads(line["entry"]).get("versions")) for line in lines]
    assert [line["config_version"] for line in lines] == expected and expected[-1] == SHIPPED_VERSION
    restored = create_engine(f"sqlite:///{(tmp_path / 'restored.db').as_posix()}")
    try:
        Base.metadata.create_all(restored)
        run_schema_upgrades(restored)
        with sessionmaker(bind=restored)() as db:
            assert ledger.restore_ledger(db, exported)[0] == 4 and ledger.verify_response_ledger(db).ok
            again = list(db.scalars(select(ResponseLedgerRecord).order_by(ResponseLedgerRecord.seq)))
            assert [row.entry_schema for row in again][-1] == "ledger-entry-v4" and [row.record_hash for row in again] == hashes
    finally:
        restored.dispose()


def test_the_provenance_audit_compares_a_v3_record_with_the_package_s_phase_5_pins():
    entry = on_record().entry.model_dump(mode="json")
    params = ledger.ledger_params(PACKAGE)
    phase5 = ledger.phase5_blocks(PACKAGE)
    assert ledger._provenance_problems(1, entry, params, PACKAGE.v1, phase5) == []
    for field in ("tool_contract_version", "panel_weights_version", "routing_table_version"):
        changed = json.loads(json.dumps(entry))
        changed["provenance"][field] = "other"
        for claim in changed["claims"]:
            claim["provenance"][field] = "other"
        assert ledger._provenance_problems(1, changed, params, PACKAGE.v1, phase5) == [f"seq 1 provenance.{field} is not the package pin"]
    changed = json.loads(json.dumps(entry))
    changed["verification"]["v2"]["verifier_prompt_hash"] = "0" * 64
    assert ledger._provenance_problems(1, changed, params, PACKAGE.v1, phase5) == ["seq 1 verification.v2.verifier_prompt_hash is not the package pin"]
    changed["verification"]["policy"]["rules_hash"] = "0" * 64
    assert "seq 1 verification.policy.rules_hash is not the package pin" in ledger._provenance_problems(1, changed, params, PACKAGE.v1, phase5)
    assert "seq 1 is a V2-verified record but the package has no v2 or tools block" in ledger._provenance_problems(1, entry, params, PACKAGE.v1, None)
    assert LedgerEntryV2.model_fields["entry_schema"].default == "ledger-entry-v2"
