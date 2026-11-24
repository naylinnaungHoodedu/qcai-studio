"""The seven E1 arms of Table XV as data, and the parity check (Phase 10 spec 3.6, 4.6; AC-10-2; PD-67).

Each arm is GATE's full configuration plus a declared ablation: a mapping of ablation variables to values. Parity means
each arm differs from GATE exactly on its declared variables and on nothing else. The table lives in
`evaluation/config/arms_v1.json`; an arm's retrieval behaviour is configuration only until a live adapter exists.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .canonical import canonical_sha256

PROVISIONAL_DEFAULTS = ("PD-67",)  # Phase 10 spec 12.1; ratified under DI-140

REPO_ROOT = Path(__file__).resolve().parents[2]
ARMS_PATH = REPO_ROOT / "evaluation" / "config" / "arms_v1.json"
ARM_IDS = ("NR", "LEX", "SEM", "GATE", "GATE+SV", "GATE+V1", "VLOOP")
ABLATION_VARIABLES = ("retrieval", "abstention_gate", "verification")
BASELINE = "GATE"


class ParityError(ValueError):
    """An arm differs from GATE outside its declared ablation variables (messages name the arm and the key only)."""


@dataclass(frozen=True)
class Arm:
    arm: str
    scenario: str
    ablation: Mapping[str, Any]
    isolates: str


@dataclass(frozen=True)
class ArmTable:
    version: str
    sha256: str
    baseline: str
    gate_configuration: Mapping[str, Any]
    arms: Mapping[str, Arm]
    variables: Mapping[str, tuple]
    raw: Mapping[str, Any]


def table_from_raw(raw: Mapping[str, Any]) -> ArmTable:
    arms = {}
    for entry in raw.get("arms", []):
        arm = Arm(arm=entry["arm"], scenario=entry["scenario"], ablation=dict(entry.get("ablation", {})), isolates=entry["isolates"])
        if arm.arm in arms:
            raise ParityError(f"{arm.arm}: duplicate arm")
        arms[arm.arm] = arm
    variables = {key: tuple(values) for key, values in dict(raw.get("variables", {})).items()}
    return ArmTable(version=str(raw.get("arms_version")), sha256=canonical_sha256(raw), baseline=str(raw.get("baseline")),
                    gate_configuration=dict(raw.get("gate_configuration", {})), arms=arms, variables=variables, raw=raw)


def load_arms(path: Path = ARMS_PATH) -> ArmTable:
    table = table_from_raw(json.loads(Path(path).read_text(encoding="utf-8")))
    check_table(table)
    return table


def arm_configuration(table: ArmTable, arm_id: str) -> dict[str, Any]:
    if arm_id not in table.arms:
        raise ParityError(f"{arm_id}: unknown arm")
    return {**table.gate_configuration, **table.arms[arm_id].ablation}


def check_table(table: ArmTable) -> None:
    if tuple(table.arms) != ARM_IDS:
        raise ParityError("arms: the table must hold exactly NR, LEX, SEM, GATE, GATE+SV, GATE+V1 and VLOOP, in that order")
    if table.baseline != BASELINE:
        raise ParityError("baseline: must be GATE")
    if table.arms[BASELINE].ablation:
        raise ParityError("GATE: the baseline declares no ablation")
    if tuple(table.variables) != ABLATION_VARIABLES:
        raise ParityError("variables: must be exactly retrieval, abstention_gate and verification")
    for key in ABLATION_VARIABLES:
        if key not in table.gate_configuration:
            raise ParityError(f"GATE: {key} missing from gate_configuration")
        if table.gate_configuration[key] not in table.variables[key]:
            raise ParityError(f"GATE: {key} outside its domain")
    seen: dict[str, str] = {}
    for arm_id, arm in table.arms.items():
        for key, value in arm.ablation.items():
            if key not in ABLATION_VARIABLES:
                raise ParityError(f"{arm_id}: {key} is not an ablation variable")
            if value not in table.variables[key] or isinstance(value, bool) != isinstance(table.variables[key][0], bool):
                raise ParityError(f"{arm_id}: {key} outside its domain")
            if value == table.gate_configuration[key]:
                raise ParityError(f"{arm_id}: {key} declared_but_equal")
        fingerprint = canonical_sha256(arm_configuration(table, arm_id))
        if fingerprint in seen:
            raise ParityError(f"{arm_id}: identical configuration to {seen[fingerprint]}")
        seen[fingerprint] = arm_id


def assert_arm_parity(run_manifests: Mapping[str, Mapping[str, Any]], *, table: ArmTable | None = None,
                      required: Sequence[str] | None = None) -> None:
    table = table if table is not None else load_arms()
    wanted = tuple(required) if required is not None else ARM_IDS
    if BASELINE not in run_manifests:
        raise ParityError("GATE: missing (every comparison is against GATE)")
    if set(run_manifests) != set(wanted):
        raise ParityError("arms: the manifests do not cover exactly the required arms")
    gate = dict(run_manifests[BASELINE])
    expected_gate = arm_configuration(table, BASELINE)
    for key in ABLATION_VARIABLES:
        if gate.get(key) != expected_gate[key]:
            raise ParityError(f"GATE: {key} declared_mismatch")
    for arm_id, manifest in run_manifests.items():
        if arm_id == BASELINE:
            continue
        if arm_id not in table.arms:
            raise ParityError(f"{arm_id}: unknown arm")
        manifest = dict(manifest)
        if set(manifest) != set(gate):
            raise ParityError(f"{arm_id}: key_set_differs")
        declared = table.arms[arm_id].ablation
        for key, value in declared.items():
            if manifest.get(key) != value:
                raise ParityError(f"{arm_id}: {key} declared_mismatch")
        for key in manifest:
            if key not in declared and key != "arm" and manifest[key] != gate[key]:
                raise ParityError(f"{arm_id}: undeclared_difference:{key}")
