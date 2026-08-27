"""Four-arm experiment configuration and parity checks (RevB §8.4)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class AblationArm:
    arm_id: str
    retrieval_mode: str
    abstention_gate: bool


ARMS = {
    "A": AblationArm("A", "none", False),
    "B": AblationArm("B", "lexical", True),
    "C": AblationArm("C", "semantic", False),
    "D": AblationArm("D", "semantic", True),
}


def assert_arm_parity(run_manifests: Mapping[str, Mapping[str, object]]) -> None:
    if set(run_manifests) != set(ARMS):
        raise ValueError("Ablation requires exactly arms A, B, C, and D.")
    baseline = {key: value for key, value in run_manifests["A"].items() if key not in {"arm", "retrieval_mode", "abstention_gate"}}
    for arm_id, manifest in run_manifests.items():
        if manifest.get("retrieval_mode") != ARMS[arm_id].retrieval_mode or manifest.get("abstention_gate") != ARMS[arm_id].abstention_gate:
            raise ValueError(f"Arm {arm_id} configuration does not match the frozen design.")
        comparable = {key: value for key, value in manifest.items() if key not in {"arm", "retrieval_mode", "abstention_gate"}}
        if comparable != baseline:
            raise ValueError(f"Arm {arm_id} differs from arm A outside its intended ablation variables.")
