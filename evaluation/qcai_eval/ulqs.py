"""ULQS v1.0: the item validator, states, splits, rated units and the freeze check (Phase 10 spec 3.1-3.2, 4.2; PD-60, PD-64).

The validator accepts the rc1 record shape (`schema_version` "1.0") and the v1.0 records the migrator writes
(`schema_version` "1.1", `dataset_version` "ULQS-v1.0"). It is hand-written (no jsonschema in the API requirements);
`lqs/ulqs-v1.0.schema.json` states the same rules for interoperability; unit tests that run in CI keep the two in
agreement (structurally, and on valid and invalid items through a dependency-free evaluator of the schema's keywords).

Every problem names an item id, a field path and a code, never a value: an item's text is research data (R-25).
Standard library only.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from fractions import Fraction
from math import ceil
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from .canonical import canonical_sha256, hashed_hex, read_jsonl
from . import inputs

PROVISIONAL_DEFAULTS = ("PD-60", "PD-61", "PD-64")
REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "lqs" / "ulqs-v1.0.schema.json"
DEFAULT_FREEZE_RULES = REPO_ROOT / "lqs" / "ulqs-v1.0-freeze-rules.json"

STRATA = ("A", "B", "C", "D", "E", "F", "G")
PAPER = {letter: f"S{index}" for index, letter in enumerate(STRATA, start=1)}
STATES = ("draft", "candidate", "review", "frozen", "release", "retired")
TRANSITIONS: dict[str, set[str]] = {
    "draft": {"candidate", "retired"},
    "candidate": {"review", "draft", "retired"},
    "review": {"frozen", "candidate", "retired"},
    "frozen": {"release", "retired"},
    "release": {"retired"},
    "retired": set(),
}
FROZEN_STATES = ("frozen", "release")
SCHEMA_VERSIONS = ("1.0", "1.1")
DATASET_VERSION = "ULQS-v1.0"
DIFFICULTY = ("easy", "medium", "hard")
BLOOM = ("remember", "understand", "apply", "analyze", "evaluate", "create")
BLOOM_UNDERSTAND_OR_ABOVE = frozenset(BLOOM[1:])
RETRIEVAL_TYPES = ("single_span", "multi_span", "negative_evidence", "multi_turn")
LEAKAGE = ("low", "medium", "high")
LICENSE_CLASSES = ("private_eval_full_span", "synthetic")
QUALITY_KEYS = ("retrieval_difficulty", "grounding_difficulty", "citation_difficulty", "abstention_difficulty", "educational_value")
BEHAVIOURS = ("answer", "abstain")
ITEM_KINDS = ("instructional", "bibliographic")
SPLITS = ("calibration", "confirmation")
DISPOSITIONS = ("convert", "revise")
NEGATIVE_METHODS = ("lexical_bm25", "regex", "semantic")
REPLAY_LEVELS = ("beginner", "intermediate", "advanced")
VALIDATION_FLAGS = ("citation_resolved", "evidence_verified", "duplicate_checked")
SPLIT_RULE = "ulqs-split-v1"

ITEM_ID = re.compile(r"^(ULQS|SYN)-([A-G])-([0-9]{3,})$")
CORPUS_VERSION = re.compile(r"^(QCAI-CORPUS-[0-9]{4}-[0-9]{2}-[0-9]{2}|SYNTHETIC-CORPUS-v1)$")
EVIDENCE_ID = re.compile(r"^(EV-(2025|2026|IND|SYN)-p[0-9]{3}-[0-9]{2}|span-[0-9a-f]{64})$")
UTC = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")

REQUIRED = ("item_id", "schema_version", "corpus_version", "status", "stratum", "corpus_scope", "topic", "concepts", "difficulty",
            "bloom", "retrieval_type", "question", "weight", "leakage_risk", "license_class", "quality_scores", "provenance",
            "validation")
OPTIONAL = ("dataset_version", "item_kind", "split", "expected_behavior", "evidence_ids", "atomic_claims", "gold_answer",
            "abstention_rationale", "reasoning_chain", "notes", "negative_evidence", "base_question", "replays",
            "invariance_checked", "conversation")
TEXTS = ("gold_answer", "abstention_rationale", "reasoning_chain", "notes")
TURN_KEYS = ("turn_id", "user_utterance", "resolved_query", "expected_behavior", "gold_answer", "evidence_ids", "atomic_claims",
             "abstention_rationale", "negative_evidence")
NEGATIVE_KEYS = ("corpus_version", "sections_searched", "queries", "methods", "verdict", "verified_utc", "limitations")
PROVENANCE_KEYS = ("created_utc", "author", "migrated_from", "migration_disposition", "note")


def _schema_vocabulary() -> tuple[str, ...]:
    # The corpus-scope vocabulary is read from the schema file: the one place it is written down.
    schema = inputs.read_json(SCHEMA_PATH)
    return tuple(schema["properties"]["corpus_scope"]["items"]["enum"])


CORPUS_SCOPES = _schema_vocabulary()


@dataclass(frozen=True)
class Problem:
    item_id: str | None
    path: str
    code: str

    def __str__(self) -> str:
        return f"{self.item_id or '-'}:{self.path}:{self.code}"


@dataclass(frozen=True)
class Dataset:
    items: tuple[Mapping[str, Any], ...]
    sha256: str
    content_sha256: str
    problems: tuple[Problem, ...]


@dataclass(frozen=True)
class FreezeRules:
    raw: Mapping[str, Any]
    sha256: str
    targets: Mapping[str, int]
    items_min: int
    items_max: int
    alpha_min: Fraction
    share_min: Fraction
    bloom_min: Fraction
    bibliographic_max: Fraction
    agent_models: tuple[str, ...] = ()


@dataclass(frozen=True)
class FreezeReport:
    passed: bool
    failures: tuple[str, ...]
    counts: Mapping[str, int]
    dataset_sha256: str
    rules_sha256: str


# --------------------------------------------------------------------------------------------------- the validator


class _Checker:
    def __init__(self, item_id: str | None) -> None:
        self.item_id = item_id
        self.problems: list[Problem] = []

    def add(self, path: str, code: str) -> None:
        self.problems.append(Problem(self.item_id, path, code))

    def string(self, value: Any, path: str) -> bool:
        if not isinstance(value, str):
            self.add(path, "type")
            return False
        if not value.strip():
            self.add(path, "empty")
            return False
        return True

    def enum(self, value: Any, path: str, allowed: Sequence[Any], *, nullable: bool = False) -> bool:
        if value is None and nullable:
            return True
        if not isinstance(value, str):
            self.add(path, "type")
            return False
        if value not in allowed:
            self.add(path, "enum")
            return False
        return True

    def string_list(self, value: Any, path: str, *, non_empty: bool = True) -> bool:
        if not isinstance(value, list):
            self.add(path, "type")
            return False
        if non_empty and not value:
            self.add(path, "empty")
            return False
        ok = True
        for index, entry in enumerate(value):
            ok = self.string(entry, f"{path}[{index}]") and ok
        return ok

    def text(self, value: Any, path: str) -> None:
        if isinstance(value, list):
            self.string_list(value, path)
        else:
            self.string(value, path)

    def boolean(self, value: Any, path: str) -> None:
        if not isinstance(value, bool):
            self.add(path, "type")

    def pointers(self, value: Any, path: str, *, synthetic: bool) -> list[str]:
        if not isinstance(value, list):
            self.add(path, "type")
            return []
        found: list[str] = []
        for index, entry in enumerate(value):
            where = f"{path}[{index}]"
            if not isinstance(entry, str):
                self.add(where, "type")
                continue
            if not EVIDENCE_ID.match(entry):
                self.add(where, "pattern")
                continue
            if entry.startswith("EV-SYN-") and not synthetic:
                self.add(where, "synthetic_mismatch")
            found.append(entry)
        if len(set(found)) != len(found):
            self.add(path, "duplicate")
        return found


def _claims(check: _Checker, value: Any, path: str, owner: str, owner_pointers: list[str], *, synthetic: bool) -> list[str]:
    if not isinstance(value, list):
        check.add(path, "type")
        return []
    pattern = re.compile(rf"^{re.escape(owner)}-c[0-9]+$")
    ids: list[str] = []
    for index, claim in enumerate(value):
        where = f"{path}[{index}]"
        if not isinstance(claim, dict):
            check.add(where, "type")
            continue
        for key in claim:
            if key not in ("claim_id", "text", "evidence_ids"):
                check.add(f"{where}.{key}", "unexpected")
        for key in ("claim_id", "text", "evidence_ids"):
            if key not in claim:
                check.add(f"{where}.{key}", "missing")
        claim_id = claim.get("claim_id")
        if "claim_id" in claim and check.string(claim_id, f"{where}.claim_id"):
            if not pattern.match(claim_id):
                check.add(f"{where}.claim_id", "pattern")
            ids.append(claim_id)
        if "text" in claim:
            check.string(claim.get("text"), f"{where}.text")
        if "evidence_ids" in claim:
            cited = check.pointers(claim.get("evidence_ids"), f"{where}.evidence_ids", synthetic=synthetic)
            if isinstance(claim.get("evidence_ids"), list) and not claim["evidence_ids"]:
                check.add(f"{where}.evidence_ids", "empty")
            if any(pointer not in owner_pointers for pointer in cited):
                check.add(f"{where}.evidence_ids", "claim_pointer_not_in_item")
    return ids


def _negative_evidence(check: _Checker, value: Any, path: str) -> None:
    if not isinstance(value, dict):
        check.add(path, "type")
        return
    for key in value:
        if key not in NEGATIVE_KEYS:
            check.add(f"{path}.{key}", "unexpected")
    for key in NEGATIVE_KEYS:
        if key not in value:
            check.add(f"{path}.{key}", "missing")
    if "corpus_version" in value and check.string(value["corpus_version"], f"{path}.corpus_version"):
        if not CORPUS_VERSION.match(value["corpus_version"]):
            check.add(f"{path}.corpus_version", "pattern")
    for key in ("sections_searched", "queries"):
        if key in value:
            check.string_list(value[key], f"{path}.{key}")
    if "methods" in value and check.string_list(value["methods"], f"{path}.methods"):
        for index, method in enumerate(value["methods"]):
            check.enum(method, f"{path}.methods[{index}]", NEGATIVE_METHODS)
    if "verdict" in value:
        check.enum(value["verdict"], f"{path}.verdict", ("none_found",))
    if "verified_utc" in value and check.string(value["verified_utc"], f"{path}.verified_utc"):
        if not UTC.match(value["verified_utc"]):
            check.add(f"{path}.verified_utc", "pattern")
    if "limitations" in value:
        check.text(value["limitations"], f"{path}.limitations")


def _behaviour_block(check: _Checker, record: Mapping[str, Any], prefix: str, owner: str, behaviour: str | None, *,
                     synthetic: bool, min_evidence: int, require_gold: bool = True) -> list[str]:
    """The answer or abstain rules of an item (A-E) or a turn (F). Returns the claim ids."""
    pointers = check.pointers(record["evidence_ids"], f"{prefix}evidence_ids", synthetic=synthetic) if "evidence_ids" in record else []
    claim_ids = (_claims(check, record["atomic_claims"], f"{prefix}atomic_claims", owner, pointers, synthetic=synthetic)
                 if "atomic_claims" in record else [])
    for key in TEXTS:
        if key in record:
            check.text(record[key], f"{prefix}{key}")
    if "negative_evidence" in record:
        _negative_evidence(check, record["negative_evidence"], f"{prefix}negative_evidence")
    if behaviour == "answer":
        if len(pointers) < min_evidence:
            check.add(f"{prefix}evidence_ids", "required_for_stratum")
        if not record.get("atomic_claims"):
            check.add(f"{prefix}atomic_claims", "required_for_stratum")
        if require_gold and "gold_answer" not in record:
            check.add(f"{prefix}gold_answer", "required_for_stratum")
    elif behaviour == "abstain":
        for key in ("negative_evidence", "abstention_rationale"):
            if key not in record:
                check.add(f"{prefix}{key}", "required_for_stratum")
        for key in ("evidence_ids", "atomic_claims", "gold_answer"):
            if key in record:
                check.add(f"{prefix}{key}", "forbidden_for_stratum")
    return claim_ids


def validate_item(raw: Mapping[str, Any]) -> list[Problem]:
    if not isinstance(raw, Mapping):
        return [Problem(None, "", "type")]
    item_id = raw.get("item_id") if isinstance(raw.get("item_id"), str) else None
    check = _Checker(item_id)
    for key in REQUIRED:
        if key not in raw:
            check.add(key, "missing")
    for key in raw:
        if key not in REQUIRED and key not in OPTIONAL:
            check.add(key, "unexpected")
    stratum = raw.get("stratum")
    if "stratum" in raw:
        check.enum(stratum, "stratum", STRATA)
    synthetic = raw.get("license_class") == "synthetic"
    if "item_id" in raw and check.string(raw["item_id"], "item_id"):
        match = ITEM_ID.match(raw["item_id"])
        if not match:
            check.add("item_id", "pattern")
        else:
            if match.group(2) != stratum:
                check.add("item_id", "stratum_mismatch")
            if (match.group(1) == "SYN") != synthetic:
                check.add("item_id", "synthetic_mismatch")
    version = raw.get("schema_version")
    if "schema_version" in raw and version not in SCHEMA_VERSIONS:
        check.add("schema_version", "schema_version")
    if version == "1.1":
        if "dataset_version" not in raw:
            check.add("dataset_version", "missing")
    if "dataset_version" in raw:
        check.enum(raw["dataset_version"], "dataset_version", (DATASET_VERSION,))
    if "corpus_version" in raw and check.string(raw["corpus_version"], "corpus_version"):
        if not CORPUS_VERSION.match(raw["corpus_version"]):
            check.add("corpus_version", "pattern")
    if "status" in raw:
        check.enum(raw["status"], "status", STATES)
    if "corpus_scope" in raw and check.string_list(raw["corpus_scope"], "corpus_scope"):
        for index, scope in enumerate(raw["corpus_scope"]):
            check.enum(scope, f"corpus_scope[{index}]", CORPUS_SCOPES)
        if len(set(raw["corpus_scope"])) != len(raw["corpus_scope"]):
            check.add("corpus_scope", "duplicate")
    if "topic" in raw:
        check.string(raw["topic"], "topic")
    if "concepts" in raw:
        check.string_list(raw["concepts"], "concepts")
    for key, allowed in (("difficulty", DIFFICULTY), ("bloom", BLOOM), ("retrieval_type", RETRIEVAL_TYPES),
                         ("leakage_risk", LEAKAGE), ("license_class", LICENSE_CLASSES)):
        if key in raw:
            check.enum(raw[key], key, allowed)
    if "question" in raw:
        check.string(raw["question"], "question")
    if "weight" in raw:
        weight = raw["weight"]
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            check.add("weight", "type")
        elif not weight > 0:
            check.add("weight", "enum")
    if "quality_scores" in raw:
        scores = raw["quality_scores"]
        if not isinstance(scores, dict):
            check.add("quality_scores", "type")
        else:
            for key in QUALITY_KEYS:
                if key not in scores:
                    check.add(f"quality_scores.{key}", "missing")
                elif isinstance(scores[key], bool) or not isinstance(scores[key], int):
                    check.add(f"quality_scores.{key}", "type")
                elif not 0 <= scores[key] <= 3:
                    check.add(f"quality_scores.{key}", "enum")
            for key in scores:
                if key not in QUALITY_KEYS:
                    check.add(f"quality_scores.{key}", "unexpected")
    if "provenance" in raw:
        provenance = raw["provenance"]
        if not isinstance(provenance, dict):
            check.add("provenance", "type")
        else:
            for key in provenance:
                if key not in PROVENANCE_KEYS:
                    check.add(f"provenance.{key}", "unexpected")
            for key in ("created_utc", "author"):
                if key not in provenance:
                    check.add(f"provenance.{key}", "missing")
            if "created_utc" in provenance and check.string(provenance["created_utc"], "provenance.created_utc"):
                if not UTC.match(provenance["created_utc"]):
                    check.add("provenance.created_utc", "pattern")
            for key in ("author", "migrated_from", "note"):
                if key in provenance:
                    check.string(provenance[key], f"provenance.{key}")
            if "migration_disposition" in provenance:
                check.enum(provenance["migration_disposition"], "provenance.migration_disposition", DISPOSITIONS)
    if "validation" in raw:
        validation = raw["validation"]
        if not isinstance(validation, dict):
            check.add("validation", "type")
        else:
            for key in VALIDATION_FLAGS:
                if key not in validation:
                    check.add(f"validation.{key}", "missing")
                else:
                    check.boolean(validation[key], f"validation.{key}")
            if "human_reviewed" in validation:
                check.boolean(validation["human_reviewed"], "validation.human_reviewed")
            for key in validation:
                if key not in (*VALIDATION_FLAGS, "human_reviewed"):
                    check.add(f"validation.{key}", "unexpected")
    if "item_kind" in raw:
        check.enum(raw["item_kind"], "item_kind", ITEM_KINDS, nullable=True)
    if "split" in raw:
        check.enum(raw["split"], "split", SPLITS, nullable=True)

    behaviour = raw.get("expected_behavior")
    if stratum in ("F", "G"):
        if "expected_behavior" in raw:
            check.add("expected_behavior", "forbidden_for_stratum")
        behaviour = None
    elif stratum in STRATA:
        if "expected_behavior" not in raw:
            check.add("expected_behavior", "required_for_stratum")
        elif check.enum(behaviour, "expected_behavior", BEHAVIOURS):
            if stratum in ("A", "B", "G") and behaviour != "answer":
                check.add("expected_behavior", "enum")
            if stratum in ("C", "E") and behaviour != "abstain":
                check.add("expected_behavior", "enum")
        else:
            behaviour = None
    if stratum not in ("F",) and "conversation" in raw:
        check.add("conversation", "forbidden_for_stratum")
    if stratum != "G":
        for key in ("base_question", "replays", "invariance_checked"):
            if key in raw:
                check.add(key, "forbidden_for_stratum")
    owner = item_id or "-"
    if stratum in ("A", "B", "C", "D", "E"):
        _behaviour_block(check, raw, "", owner, behaviour if behaviour in BEHAVIOURS else None, synthetic=synthetic,
                         min_evidence=2 if stratum == "B" else 1)
    elif stratum == "G":
        _behaviour_block(check, raw, "", owner, "answer", synthetic=synthetic, min_evidence=1, require_gold=False)
        if "base_question" not in raw:
            check.add("base_question", "required_for_stratum")
        else:
            check.string(raw["base_question"], "base_question")
        if "invariance_checked" not in raw:
            check.add("invariance_checked", "required_for_stratum")
        else:
            check.boolean(raw["invariance_checked"], "invariance_checked")
        replays = raw.get("replays")
        if "replays" not in raw:
            check.add("replays", "required_for_stratum")
        elif not isinstance(replays, list):
            check.add("replays", "type")
        else:
            levels = []
            for index, replay in enumerate(replays):
                where = f"replays[{index}]"
                if not isinstance(replay, dict):
                    check.add(where, "type")
                    continue
                for key in replay:
                    if key not in ("level", "gold_answer", "presentation_notes"):
                        check.add(f"{where}.{key}", "unexpected")
                if check.enum(replay.get("level"), f"{where}.level", REPLAY_LEVELS):
                    levels.append(replay["level"])
                if "gold_answer" not in replay:
                    check.add(f"{where}.gold_answer", "missing")
                else:
                    check.text(replay["gold_answer"], f"{where}.gold_answer")
                if "presentation_notes" in replay:
                    check.text(replay["presentation_notes"], f"{where}.presentation_notes")
            if sorted(levels) != sorted(REPLAY_LEVELS) or len(replays) != 3:
                check.add("replays", "replay_levels")
    elif stratum == "F":
        for key in ("evidence_ids", "atomic_claims", "gold_answer"):
            if key in raw:
                check.add(key, "forbidden_for_stratum")
        for key in ("abstention_rationale", "reasoning_chain", "notes"):
            if key in raw:
                check.text(raw[key], key)
        conversation = raw.get("conversation")
        if "conversation" not in raw:
            check.add("conversation", "required_for_stratum")
        elif not isinstance(conversation, list):
            check.add("conversation", "type")
        else:
            if len(conversation) < 2:
                check.add("conversation", "required_for_stratum")
            turn_pattern = re.compile(rf"^{re.escape(owner)}-t[0-9]+$")
            for index, turn in enumerate(conversation):
                where = f"conversation[{index}]"
                if not isinstance(turn, dict):
                    check.add(where, "type")
                    continue
                for key in turn:
                    if key not in TURN_KEYS:
                        check.add(f"{where}.{key}", "unexpected")
                for key in ("turn_id", "user_utterance", "resolved_query", "expected_behavior"):
                    if key not in turn:
                        check.add(f"{where}.{key}", "missing")
                turn_id = turn.get("turn_id")
                if "turn_id" in turn and check.string(turn_id, f"{where}.turn_id") and not turn_pattern.match(turn_id):
                    check.add(f"{where}.turn_id", "pattern")
                for key in ("user_utterance", "resolved_query"):
                    if key in turn:
                        check.string(turn[key], f"{where}.{key}")
                turn_behaviour = turn.get("expected_behavior")
                if "expected_behavior" in turn and not check.enum(turn_behaviour, f"{where}.expected_behavior", BEHAVIOURS):
                    turn_behaviour = None
                _behaviour_block(check, turn, f"{where}.", turn_id if isinstance(turn_id, str) else owner, turn_behaviour,
                                 synthetic=synthetic, min_evidence=1)
    return check.problems


def _list(value: Any) -> list[Any]:
    """`value` when it is a list, else empty: the duplicate checks read only what `validate_item` can report on, so a
    field of the wrong type (a bool, a number, an object) is its problem, never a TypeError here."""
    return value if isinstance(value, list) else []


def _claim_ids(item: Mapping[str, Any]) -> list[str]:
    ids = [claim.get("claim_id") for claim in _list(item.get("atomic_claims")) if isinstance(claim, dict)]
    for turn in _list(item.get("conversation")):
        if isinstance(turn, dict):
            ids += [claim.get("claim_id") for claim in _list(turn.get("atomic_claims")) if isinstance(claim, dict)]
    return [value for value in ids if isinstance(value, str)]


def _turn_ids(item: Mapping[str, Any]) -> list[str]:
    return [turn.get("turn_id") for turn in _list(item.get("conversation"))
            if isinstance(turn, dict) and isinstance(turn.get("turn_id"), str)]


def validate_dataset(items: Sequence[Mapping[str, Any]]) -> list[Problem]:
    problems: list[Problem] = []
    for item in items:
        problems += validate_item(item)
    for label, values in (("item_id", [item.get("item_id") for item in items if isinstance(item, Mapping)]),
                          ("atomic_claims.claim_id", [value for item in items if isinstance(item, Mapping) for value in _claim_ids(item)]),
                          ("conversation.turn_id", [value for item in items if isinstance(item, Mapping) for value in _turn_ids(item)])):
        for value, count in sorted(Counter(v for v in values if isinstance(v, str)).items()):
            if count > 1:
                owner = value if label == "item_id" else None
                problems.append(Problem(owner, label, "duplicate"))
    return problems


def _sorted_items(items: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return sorted(items, key=lambda item: str(item.get("item_id", "")))


def dataset_sha256(items: Sequence[Mapping[str, Any]]) -> str:
    return canonical_sha256([dict(item) for item in _sorted_items(items)])


def dataset_content_sha256(items: Sequence[Mapping[str, Any]]) -> str:
    """The dataset hash with each item's `status` removed: an agreement record stays current when items move state."""
    return canonical_sha256([{key: value for key, value in item.items() if key != "status"} for item in _sorted_items(items)])


def load_ulqs(path: Path) -> Dataset:
    items = tuple(read_jsonl(Path(path)))
    return Dataset(items=items, sha256=dataset_sha256(items), content_sha256=dataset_content_sha256(items),
                   problems=tuple(validate_dataset(items)))


def stratum_counts(items: Sequence[Mapping[str, Any]], *, include_retired: bool = False) -> dict[str, int]:
    counts = {letter: 0 for letter in STRATA}
    for item in items:
        if item.get("status") == "retired" and not include_retired:
            continue
        if item.get("stratum") in counts:
            counts[item["stratum"]] += 1
    return counts


def pointers_of(item: Mapping[str, Any]) -> list[tuple[str, str]]:
    """(field path, pointer) for every evidence pointer of an item and its turns."""
    found = [(f"evidence_ids[{index}]", pointer) for index, pointer in enumerate(item.get("evidence_ids", []) or [])]
    for turn_index, turn in enumerate(item.get("conversation", []) or []):
        if isinstance(turn, dict):
            found += [(f"conversation[{turn_index}].evidence_ids[{index}]", pointer)
                      for index, pointer in enumerate(turn.get("evidence_ids", []) or [])]
    return [(path, pointer) for path, pointer in found if isinstance(pointer, str)]


def _unit_owners(item: Mapping[str, Any]) -> list[tuple[str, str | None, Mapping[str, Any]]]:
    """(owner id, behaviour, record) for each answerable or abstaining unit of an item."""
    stratum = item.get("stratum")
    if stratum == "F":
        return [(turn.get("turn_id"), turn.get("expected_behavior"), turn) for turn in item.get("conversation", []) or []
                if isinstance(turn, dict)]
    behaviour = "answer" if stratum == "G" else item.get("expected_behavior")
    return [(item.get("item_id"), behaviour, item)]


def rated_units(item: Mapping[str, Any]) -> list[str]:
    """The units a rater labels: each gold claim id, and `<item or turn id>-abstention` for an abstaining unit."""
    units: list[str] = []
    for owner, behaviour, record in _unit_owners(item):
        if behaviour == "abstain":
            units.append(f"{owner}-abstention")
        else:
            units += [claim["claim_id"] for claim in record.get("atomic_claims", []) or []
                      if isinstance(claim, dict) and isinstance(claim.get("claim_id"), str)]
    return units


def check_transition(before: Mapping[str, Any] | None, after: Mapping[str, Any]) -> list[Problem]:
    item_id = after.get("item_id") if isinstance(after.get("item_id"), str) else None
    problems: list[Problem] = []
    target = after.get("status")
    source = None if before is None else before.get("status")
    if source is None:
        if target not in ("draft", "candidate"):
            problems.append(Problem(item_id, "status", "transition"))
        return problems
    if not isinstance(source, str) or not isinstance(target, str):  # a state of another type is never a transition
        problems.append(Problem(item_id, "status", "transition"))
        return problems
    if source != target and target not in TRANSITIONS.get(source, set()):
        problems.append(Problem(item_id, "status", "transition"))
    if source == "review" and target == "frozen":
        validation = after.get("validation") or {}
        if validation.get("human_reviewed") is not True:
            problems.append(Problem(item_id, "validation.human_reviewed", "human_review_missing"))
        if not all(validation.get(flag) is True for flag in VALIDATION_FLAGS):
            problems.append(Problem(item_id, "validation", "validation_flags_false"))
        if after.get("item_kind") not in ITEM_KINDS:
            problems.append(Problem(item_id, "item_kind", "item_kind_unmarked"))
    if source in FROZEN_STATES:
        strip = lambda item: {key: value for key, value in item.items() if key != "status"}  # noqa: E731
        if canonical_sha256(strip(before)) != canonical_sha256(strip(after)):
            problems.append(Problem(item_id, "", "frozen_content_changed"))
    return problems


def transition_problems(previous: Sequence[Mapping[str, Any]], items: Sequence[Mapping[str, Any]]) -> list[Problem]:
    """`check_transition` for every item against its predecessor in `previous` (matched by `item_id`; an item absent there
    is new), plus `removed` for a predecessor with no successor (an item leaves only by moving to `retired`)."""
    before = {item["item_id"]: item for item in previous if isinstance(item, Mapping) and isinstance(item.get("item_id"), str)}
    problems: list[Problem] = []
    seen: set[str] = set()
    for item in items:
        item_id = item.get("item_id")
        if isinstance(item_id, str):
            seen.add(item_id)
        problems += check_transition(before.get(item_id) if isinstance(item_id, str) else None, item)
    problems += [Problem(item_id, "", "removed") for item_id in sorted(set(before) - seen)]
    return problems


def assign_splits(items: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """`ulqs-split-v1`: within each stratum, items in sha256 order alternate calibration and confirmation."""
    splits: dict[str, str] = {}
    for letter in STRATA:
        members = sorted((item["item_id"] for item in items if item.get("stratum") == letter),
                         key=lambda item_id: hashed_hex(SPLIT_RULE, item_id))
        for index, item_id in enumerate(members):
            splits[item_id] = SPLITS[index % 2]
    return splits



def split_failures(items: Sequence[Mapping[str, Any]]) -> list[str]:
    """The freeze codes of the calibration/confirmation split (plan 10.5(2), Risk R-25; PD-61): every live item carries a
    split (`split_missing`); within each stratum the items that carry one (retired items included, since a frozen item's
    split never changes) are balanced to within one (`split_unbalanced:<letter>`), as `ulqs-split-v1` assigns them; and
    a stratum with two or more live items keeps a live item in each split (`split_live_missing:<letter>`), so that
    retirements cannot leave a stratum with no live calibration or no live confirmation item."""
    failures = []
    if any(item.get("split") not in SPLITS for item in items if item.get("status") != "retired"):
        failures.append("split_missing")
    for letter in STRATA:
        splits = [item.get("split") for item in items if item.get("stratum") == letter and item.get("split") in SPLITS]
        if abs(splits.count(SPLITS[0]) - splits.count(SPLITS[1])) > 1:
            failures.append(f"split_unbalanced:{letter}")
        live = [item.get("split") for item in items if item.get("stratum") == letter and item.get("status") != "retired"]
        if len(live) >= 2 and not all(split in live for split in SPLITS):
            failures.append(f"split_live_missing:{letter}")
    return failures

def _fraction(value: Any) -> Fraction:
    if isinstance(value, bool) or not isinstance(value, str):
        raise ValueError("freeze rules: a rational must be a decimal or p/q string")
    return Fraction(value)


def load_freeze_rules(path: Path = DEFAULT_FREEZE_RULES) -> FreezeRules:
    """The freeze rules at `path`. Every way the file can be wrong (unreadable aside: OSError) raises ValueError: bytes
    that are not UTF-8 JSON or nest too deeply to parse, a value that is not an object, a section or key missing, a value
    of the wrong type (an item bound that is not an integer, `Infinity` and `1.5` included) or out of range."""
    text = Path(path).read_text(encoding="utf-8")
    try:
        raw = inputs.loads(text)
    except RecursionError:
        raise ValueError("freeze rules: nested too deeply to parse") from None
    except inputs.InputInvalid as error:
        raise ValueError(f"freeze rules: {error}") from None
    if not isinstance(raw, Mapping):
        raise ValueError("freeze rules: not a JSON object")
    try:
        return _freeze_rules(raw)
    except (KeyError, TypeError, AttributeError, ZeroDivisionError, OverflowError, RecursionError) as error:
        raise ValueError(f"freeze rules: malformed ({type(error).__name__}: {error})") from None


def _freeze_rules(raw: Mapping[str, Any]) -> FreezeRules:
    if raw.get("rules") != "ulqs-v1.0-freeze-rules-v1":
        raise ValueError("freeze rules: not a ulqs-v1.0-freeze-rules-v1 file")
    strata = raw.get("strata") or {}
    if not isinstance(strata, Mapping) or sorted(strata) != list(STRATA):
        raise ValueError("freeze rules: the strata must be exactly A-G")
    targets = {}
    for letter in STRATA:
        target = strata[letter].get("target") if isinstance(strata[letter], Mapping) else None
        if isinstance(target, bool) or not isinstance(target, int) or target < 1:
            raise ValueError(f"freeze rules: strata.{letter}.target must be a positive integer")
        targets[letter] = target
    items_min, items_max = raw["items"]["min"], raw["items"]["max"]
    if any(isinstance(bound, bool) or not isinstance(bound, int) or bound < 0 for bound in (items_min, items_max)):
        raise ValueError("freeze rules: items.min and items.max must be non-negative integers")
    total = sum(targets.values())
    if not items_min <= total <= items_max:
        raise ValueError(f"freeze rules: the strata targets total {total}, outside [{items_min}, {items_max}]")
    agreement, coverage = raw["agreement"], raw["coverage"]
    agent = raw.get("agent_check")
    if not isinstance(agent, Mapping) or agent.get("record") != AGENT_CHECK_RECORD or not isinstance(agent.get("pinned_models"), list)             or not all(isinstance(model, str) and model for model in agent["pinned_models"]):
        raise ValueError("freeze rules: agent_check must name the ulqs-agent-check-v1 record and a list of pinned models")
    return FreezeRules(raw=raw, sha256=canonical_sha256(raw), targets=targets, items_min=items_min, items_max=items_max,
                       alpha_min=_fraction(agreement["alpha_min"]), share_min=_fraction(agreement["second_rated_share_min"]),
                       bloom_min=_fraction(coverage["bloom_understand_or_above_min"]),
                       bibliographic_max=_fraction(coverage["bibliographic_max"]),
                       agent_models=tuple(agent["pinned_models"]))


# The AI-agent re-check (VBT RevB p. 15, Sec. VIII-B, "Benchmark verification before use"): after the conventional check,
# an LLM verifier agent, one of the V2 verifier models chosen before the check, re-checks every item against its evidence
# with the V2 verdict schema; its disagreements with the deterministic and human checks are adjudicated by a claim rater
# who did not review that item; the counts of agent-detected defects, agent false alarms and missed defects are reported.
# Items changed after one of the agent's flags are listed, so that its E2 accuracy can be reported with and without them:
# the record binds each item's content as the agent checked it (`checked_items`), and the freeze accepts a later change
# to exactly the listed items, each listed with its reason: after one of the agent's flags (`items_changed_after_flag`)
# or for another reason (`items_changed_without_flag`).
AGENT_CHECK_RECORD = "ulqs-agent-check-v1"
AGENT_CHECK_KEYS = ("record", "checked_items", "agent_model_id", "model_chosen_before_check", "verdict_schema",
                    "report_sha256", "items_checked", "disagreements", "disagreements_adjudicated",
                    "adjudicated_by_non_reviewer", "agent_detected_defects", "agent_false_alarms", "agent_missed_defects",
                    "items_changed_after_flag", "items_changed_without_flag")
AGENT_CHANGE_LISTS = ("items_changed_after_flag", "items_changed_without_flag")
AGENT_CHECK_COUNTS = ("items_checked", "disagreements", "disagreements_adjudicated", "agent_detected_defects",
                      "agent_false_alarms", "agent_missed_defects")
AGENT_VERDICT_SCHEMA = "v2"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def item_content_sha256(item: Mapping[str, Any]) -> str:
    """One item's content hash with its `status` removed (the per-item form of `dataset_content_sha256`)."""
    return canonical_sha256({key: value for key, value in item.items() if key != "status"})


def agent_check_shape_ok(record: Any) -> bool:
    """An `ulqs-agent-check-v1` record's shape: exactly its keys, counts that are non-negative integers, a model id, the
    report's sha256, the V2 verdict schema, `checked_items` mapping item ids to content sha256s and two lists of item
    ids, those changed after a flag and those changed for another reason."""
    return isinstance(record, Mapping) and record.get("record") == AGENT_CHECK_RECORD and set(record) == set(AGENT_CHECK_KEYS) \
        and all(_count(record[key]) for key in AGENT_CHECK_COUNTS) \
        and isinstance(record["agent_model_id"], str) and bool(record["agent_model_id"]) \
        and isinstance(record["report_sha256"], str) and bool(_HEX64.match(record["report_sha256"])) \
        and record["verdict_schema"] == AGENT_VERDICT_SCHEMA and isinstance(record["checked_items"], Mapping) \
        and all(isinstance(key, str) and isinstance(value, str) and _HEX64.match(value) for key, value in record["checked_items"].items()) \
        and all(isinstance(record[key], list) and all(isinstance(entry, str) for entry in record[key]) for key in AGENT_CHANGE_LISTS)


def agent_check_failures(record: Mapping[str, Any] | None, items: Sequence[Mapping[str, Any]], *, rules: FreezeRules,
                         previous: Sequence[Mapping[str, Any]] | None = None) -> list[str]:
    """The freeze codes of the agent re-check (spec 4.2): missing, malformed, not covering every item the agent had to
    check (incomplete), an item changed since the agent checked it that neither list names (stale), by a model the rules
    do not pin (none is pinned while D-07 is open: DI-142), or with an unadjudicated disagreement.

    The agent checks the set the freeze starts from (`previous`, the review set; runbook step 3), so `checked_items` must
    name exactly every item live now plus every item live in `previous` (an item retired since the check stays in it);
    with no previous set (the freeze then fails with `no_previous_set`) the items it holds that are retired now are
    accepted in place of the previous set's live items. `items_checked` is its size. An item whose content differs from
    `checked_items` now, or that the agent checked and is retired now, is changed and must be listed with its reason:
    `items_changed_after_flag` (after one of the agent's flags; at most as many as it flagged, detected defects plus false
    alarms) or `items_changed_without_flag` (for another reason, such as trimming a stratum to its target). A listed
    item must be one that changed, in one list only and once."""
    if record is None:
        return ["agent_check_missing"]
    if not agent_check_shape_ok(record):
        return ["agent_check_invalid"]
    failures = []
    live = [item for item in items if item.get("status") != "retired"]
    checked = record["checked_items"]
    live_ids = {item.get("item_id") for item in live}
    current_ids = {item.get("item_id") for item in items}
    if previous is None:
        required = live_ids | {item_id for item_id in checked if item_id in current_ids}
    else:
        required = live_ids | {item.get("item_id") for item in previous if isinstance(item, Mapping) and isinstance(item.get("item_id"), str)
                               and item.get("status") != "retired" and item.get("item_id") in current_ids}
    retired_checked = {item.get("item_id") for item in items if item.get("status") == "retired" and item.get("item_id") in checked}
    changed = {item.get("item_id") for item in live if item.get("item_id") in checked and checked[item["item_id"]] != item_content_sha256(item)}
    changed |= retired_checked
    after_flag, without_flag = (record[key] for key in AGENT_CHANGE_LISTS)
    listed = set(after_flag) | set(without_flag)
    if changed - listed:
        failures.append("agent_check_stale")
    if record["items_checked"] != len(checked) or set(checked) != required:
        failures.append("agent_check_incomplete")
    if record["model_chosen_before_check"] is not True:
        failures.append("agent_model_not_chosen_before_check")
    if record["agent_model_id"] not in rules.agent_models:
        failures.append("agent_model_not_pinned")
    if record["disagreements_adjudicated"] != record["disagreements"] or record["adjudicated_by_non_reviewer"] is not True:
        failures.append("agent_disagreements_unadjudicated")
    if listed - changed or len(listed) != len(after_flag) + len(without_flag) \
            or len(after_flag) > record["agent_detected_defects"] + record["agent_false_alarms"]:
        failures.append("agent_check_invalid")
    return failures


def _alpha(value: Any) -> Fraction | None:
    if not isinstance(value, str):
        return None
    try:
        return Fraction(value)
    except (ValueError, ZeroDivisionError):
        return None


def freeze_check(items: Sequence[Mapping[str, Any]], *, rules: FreezeRules, pointer_report: Any, agreement: Mapping[str, Any] | None,
                 previous: Sequence[Mapping[str, Any]] | None = None, require_licensed: bool = True,
                 agent_check: Mapping[str, Any] | None = None) -> FreezeReport:
    """The freeze conditions (spec 4.2). `previous` is the item set the freeze starts from (the review set, or the last
    frozen set): every item's move from it must be in `TRANSITIONS` (`transition_invalid`) and frozen content may not change
    (`frozen_content_changed`); with no previous set the freeze fails (`no_previous_set`). Every resolved EV pointer must
    have been checked against the corpus text (`pointers_not_text_verified`). The conventional check is followed by the
    AI-agent re-check (`agent_check`, an `ulqs-agent-check-v1` record; `agent_check_failures`), so no freeze passes
    without it."""
    failures: list[str] = []
    live = [item for item in items if item.get("status") != "retired"]
    if validate_dataset(items):
        failures.append("schema_problems")
    if require_licensed and any(item.get("license_class") == "synthetic" for item in live):
        failures.append("synthetic_items")
    if not rules.items_min <= len(live) <= rules.items_max:
        failures.append("count_out_of_range")
    counts = stratum_counts(items)
    for letter in STRATA:
        if counts[letter] == 0:
            failures.append(f"stratum_missing:{letter}")
        elif counts[letter] != rules.targets[letter]:
            failures.append(f"stratum_off_target:{letter}")
    if any(item.get("status") not in FROZEN_STATES for item in live):
        failures.append("state_not_frozen")
    if previous is None:
        failures.append("no_previous_set")
    else:
        codes = {problem.code for problem in transition_problems(previous, items)}
        if codes & {"transition", "removed"}:
            failures.append("transition_invalid")
        if "frozen_content_changed" in codes:
            failures.append("frozen_content_changed")
    if any((item.get("validation") or {}).get("human_reviewed") is not True for item in live):
        failures.append("human_review_missing")
    if any(not all((item.get("validation") or {}).get(flag) is True for flag in VALIDATION_FLAGS) for item in live):
        failures.append("validation_flags_false")
    if any(item.get("item_kind") not in ITEM_KINDS for item in live):
        failures.append("item_kind_unmarked")
    failures += split_failures(items)
    if live:
        bloom = Fraction(sum(item.get("bloom") in BLOOM_UNDERSTAND_OR_ABOVE for item in live), len(live))
        if bloom < rules.bloom_min:
            failures.append("bloom_below_share")
        bibliographic = Fraction(sum(item.get("item_kind") == "bibliographic" for item in live), len(live))
        if bibliographic > rules.bibliographic_max:
            failures.append("bibliographic_above_share")
    if len({item.get("corpus_version") for item in live}) > 1:
        failures.append("corpus_versions_differ")
    if pointer_report is None:
        failures.append("unresolved_pointers")
    else:
        statuses = {problem[2] for problem in pointer_report.problems}
        if statuses - {"hash_mismatch"}:
            failures.append("unresolved_pointers")
        if "hash_mismatch" in statuses:
            failures.append("pointer_hash_mismatch")
        if getattr(pointer_report, "text_verified", 0) != getattr(pointer_report, "evidence_resolved", 0):
            failures.append("pointers_not_text_verified")
    if agreement is None:
        failures.append("no_agreement_record")
    else:
        if agreement.get("dataset_content_sha256") != dataset_content_sha256(items):
            failures.append("agreement_stale")
        alpha = _alpha(agreement.get("alpha_nominal_label"))
        if alpha is None or alpha < rules.alpha_min:
            failures.append("alpha_below_floor")
        coverage = agreement.get("coverage") or {}
        share = _alpha(coverage.get("share"))
        if share is None or share < rules.share_min:
            failures.append("second_rated_below_share")
        per_stratum = coverage.get("per_stratum") or {}
        for letter in STRATA:
            rated, total = (per_stratum.get(letter) or [0, counts[letter]])
            if rated < ceil(total * rules.share_min):
                failures.append(f"stratum_second_rated_below_share:{letter}")
    failures += agent_check_failures(agent_check, items, rules=rules, previous=previous)
    return FreezeReport(passed=not failures, failures=tuple(failures), counts=counts, dataset_sha256=dataset_sha256(items),
                        rules_sha256=rules.sha256)
