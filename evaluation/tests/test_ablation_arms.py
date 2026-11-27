"""Phase 10: the seven Table XV arms as data and the parity check's refusals (spec 3.6, 4.6; PD-67)."""

from __future__ import annotations

import copy
import json

import pytest

from evaluation.qcai_eval import ablation


def raw():
    return json.loads(ablation.ARMS_PATH.read_text(encoding="utf-8"))


def manifests(table, arms=ablation.ARM_IDS):
    return {arm: {**ablation.arm_configuration(table, arm), "package_sha256": "p", "items_sha256": "i"} for arm in arms}


def test_arm_configuration_is_gate_plus_the_declared_ablation():
    table = ablation.load_arms()
    assert ablation.arm_configuration(table, "GATE") == table.gate_configuration
    nr = ablation.arm_configuration(table, "NR")
    assert nr["retrieval"] == "none" and nr["abstention_gate"] is False and nr["verification"] == "none"
    assert ablation.arm_configuration(table, "LEX")["abstention_gate"] is True
    with pytest.raises(ablation.ParityError, match="unknown arm"):
        ablation.arm_configuration(table, "A")


@pytest.mark.parametrize(("change", "message"), [
    (lambda r: r["arms"].pop(0), "exactly NR"),
    (lambda r: r.update(baseline="SEM"), "baseline"),
    (lambda r: r["arms"][3].update(ablation={"verification": "v1-only"}), "declares no ablation"),
    (lambda r: r["arms"][1]["ablation"].update(abstention_gate=True), "declared_but_equal"),
    (lambda r: r["arms"][2].update(ablation={"top_k": 9}), "not an ablation variable"),
    (lambda r: r["arms"][5].update(ablation={"verification": "v9"}), "outside its domain"),
    (lambda r: r["arms"][2].update(ablation={"abstention_gate": 0}), "outside its domain"),
    (lambda r: r["arms"][6].update(ablation={"verification": "v1-only"}), "identical configuration"),
])
def test_check_table_refuses_each_malformed_table(change, message):
    value = raw()
    change(value)
    with pytest.raises(ablation.ParityError, match=message):
        ablation.check_table(ablation.table_from_raw(value))


def test_parity_refusals_name_the_arm_and_key_only():
    table = ablation.load_arms()
    good = manifests(table)
    ablation.assert_arm_parity(good, table=table)
    for arm, edit, message in (("SEM", {"top_k": 9}, "key_set_differs"), ("SEM", {"package_sha256": "q"}, "SEM: undeclared_difference:package_sha256"),
                               ("LEX", {"retrieval": "semantic"}, "LEX: retrieval declared_mismatch"),
                               ("GATE", {"abstention_gate": False}, "GATE: abstention_gate declared_mismatch")):
        broken = copy.deepcopy(good)
        broken[arm].update(edit)
        with pytest.raises(ablation.ParityError, match=message) as raised:
            ablation.assert_arm_parity(broken, table=table)
        assert "'q'" not in str(raised.value)


def test_a_subset_of_arms_must_include_gate_and_equal_the_required_set():
    table = ablation.load_arms()
    ablation.assert_arm_parity(manifests(table, ("GATE", "NR")), table=table, required=("GATE", "NR"))
    with pytest.raises(ablation.ParityError, match="GATE: missing"):
        ablation.assert_arm_parity(manifests(table, ("SEM", "NR")), table=table, required=("SEM", "NR"))
    with pytest.raises(ablation.ParityError, match="exactly the required"):
        ablation.assert_arm_parity(manifests(table, ("GATE", "NR")), table=table)
