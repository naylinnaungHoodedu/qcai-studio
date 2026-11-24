"""Phase 10: the ULQS v1.0 validator, states, splits and rated units (spec 3.1, 4.2; PD-60)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from evaluation.qcai_eval import synthetic, ulqs
from evaluation.qcai_eval.canonical import read_jsonl
from evaluation.qcai_eval.lqs_loader import load_lqs, validate_lqs

REPO_ROOT = Path(__file__).resolve().parents[2]


def codes(item):
    return {(problem.path, problem.code) for problem in ulqs.validate_item(item)}


def item(stratum="A", number=1, **kwargs):
    return synthetic.synthetic_item(stratum, number, page=number, **kwargs)


def test_every_synthetic_stratum_item_validates():
    assert ulqs.validate_dataset(synthetic.synthetic_dataset(synthetic.PAPER_TARGETS)) == []


def test_the_committed_fixtures_validate_and_are_the_small_synthetic_set():
    items = read_jsonl(synthetic.ITEMS_FIXTURE)
    assert ulqs.validate_dataset(items) == []
    assert items == synthetic.synthetic_dataset(synthetic.SMALL)
    assert ulqs.stratum_counts(items) == synthetic.SMALL
    assert all(entry["status"] == "candidate" and entry["validation"]["human_reviewed"] is False for entry in items)
    d_behaviours = sorted(entry["expected_behavior"] for entry in items if entry["stratum"] == "D")
    assert d_behaviours == ["abstain", "answer"]  # one D item is a premise correction
    assert read_jsonl(synthetic.CATALOG_FIXTURE) == synthetic.synthetic_catalog(items)


@pytest.mark.parametrize(("mutate", "expected"), [
    (lambda i: i.pop("question"), ("question", "missing")),
    (lambda i: i.update(question="  "), ("question", "empty")),
    (lambda i: i.update(weight=True), ("weight", "type")),
    (lambda i: i.update(weight=0), ("weight", "enum")),
    (lambda i: i.update(bloom="memorise"), ("bloom", "enum")),
    (lambda i: i.update(item_id="SYN-A-1"), ("item_id", "pattern")),
    (lambda i: i.update(item_id="SYN-B-001"), ("item_id", "stratum_mismatch")),
    (lambda i: i.update(license_class="private_eval_full_span"), ("item_id", "synthetic_mismatch")),
    (lambda i: i.update(schema_version="2.0"), ("schema_version", "schema_version")),
    (lambda i: i.pop("dataset_version"), ("dataset_version", "missing")),
    (lambda i: i.update(corpus_scope=["synthetic", "synthetic"]), ("corpus_scope", "duplicate")),
    (lambda i: i.update(corpus_scope=[]), ("corpus_scope", "empty")),
    (lambda i: i.update(evidence_ids=["EV-SYN-p001-01", "EV-SYN-p001-01"]), ("evidence_ids", "duplicate")),
    (lambda i: i.update(evidence_ids=["EV-XYZ-p001-01"]), ("evidence_ids[0]", "pattern")),
    (lambda i: i["atomic_claims"][0].update(evidence_ids=["EV-SYN-p002-01"]), ("atomic_claims[0].evidence_ids", "claim_pointer_not_in_item")),
    (lambda i: i["atomic_claims"][0].update(claim_id="SYN-A-001-x1"), ("atomic_claims[0].claim_id", "pattern")),
    (lambda i: i.pop("gold_answer"), ("gold_answer", "required_for_stratum")),
    (lambda i: i.update(conversation=[]), ("conversation", "forbidden_for_stratum")),
    (lambda i: i.update(quality_scores={**i["quality_scores"], "educational_value": 4}), ("quality_scores.educational_value", "enum")),
    (lambda i: i.update(extra_field=1), ("extra_field", "unexpected")),
    (lambda i: i.update(item_kind="anecdotal"), ("item_kind", "enum")),
])
def test_each_problem_code_names_the_field(mutate, expected):
    entry = item()
    mutate(entry)
    assert expected in codes(entry)


def test_the_stratum_rules():
    c_item = item("C")
    c_item["evidence_ids"] = ["EV-SYN-p001-01"]
    assert ("evidence_ids", "forbidden_for_stratum") in codes(c_item)
    no_negative = item("E")
    no_negative.pop("negative_evidence")
    assert ("negative_evidence", "required_for_stratum") in codes(no_negative)
    assert ("expected_behavior", "enum") in codes(item("C", expected_behavior="answer"))
    b_item = item("B")
    b_item["evidence_ids"] = b_item["evidence_ids"][:1]
    b_item["atomic_claims"] = b_item["atomic_claims"][:1]
    assert ("evidence_ids", "required_for_stratum") in codes(b_item)
    assert codes(item("D", 2)) == set() and codes(item("D", 1)) == set()  # premise correction, and abstain
    g_item = item("G")
    g_item["replays"][2]["level"] = "beginner"
    assert ("replays", "replay_levels") in codes(g_item)
    g_bad = item("G", expected_behavior="answer")
    assert ("expected_behavior", "forbidden_for_stratum") in codes(g_bad)
    f_item = item("F")
    f_item["conversation"][1]["evidence_ids"] = ["EV-SYN-p001-01"]
    assert ("conversation[1].evidence_ids", "forbidden_for_stratum") in codes(f_item)
    f_short = item("F")
    f_short["conversation"] = f_short["conversation"][:1]
    assert ("conversation", "required_for_stratum") in codes(f_short)
    ev_syn_on_licensed = item("A", item_id="ULQS-A-001", license_class="private_eval_full_span")
    assert ("evidence_ids[0]", "synthetic_mismatch") in codes(ev_syn_on_licensed)


def test_the_dataset_checks_unique_item_claim_and_turn_ids():
    first, second = item("F"), item("F")
    problems = ulqs.validate_dataset([first, second])
    assert {(p.path, p.code) for p in problems} >= {("item_id", "duplicate"), ("atomic_claims.claim_id", "duplicate"),
                                                    ("conversation.turn_id", "duplicate")}


def test_no_problem_string_contains_a_value():
    entry = item()
    entry["question"] = 12345
    entry["topic"] = synthetic.SENTINEL * 0 + " "
    entry["bloom"] = synthetic.SENTINEL
    entry["corpus_version"] = synthetic.SENTINEL
    for problem in ulqs.validate_item(entry):
        assert synthetic.SENTINEL not in str(problem) and "12345" not in str(problem)


def test_transitions_follow_the_state_machine_and_frozen_content_is_immutable():
    review = item(status="review")
    frozen = copy.deepcopy(review)
    frozen["status"] = "frozen"
    assert [p.code for p in ulqs.check_transition(review, frozen)] == ["human_review_missing"]
    frozen["validation"]["human_reviewed"] = True
    assert ulqs.check_transition(review, frozen) == []
    unmarked = copy.deepcopy(frozen)
    unmarked["item_kind"] = None
    assert "item_kind_unmarked" in [p.code for p in ulqs.check_transition(review, unmarked)]
    flags = copy.deepcopy(frozen)
    flags["validation"]["evidence_verified"] = False
    assert "validation_flags_false" in [p.code for p in ulqs.check_transition(review, flags)]
    assert [p.code for p in ulqs.check_transition(item(status="draft"), frozen)] == ["transition"]
    assert [p.code for p in ulqs.check_transition(None, frozen)] == ["transition"]
    released = copy.deepcopy(frozen)
    released["status"] = "release"
    released["question"] = "An edited invented question?"
    assert [p.code for p in ulqs.check_transition(frozen, released)] == ["frozen_content_changed"]
    retired = copy.deepcopy(frozen)
    retired["status"] = "retired"
    assert ulqs.check_transition(frozen, retired) == []
    assert [p.code for p in ulqs.check_transition(retired, frozen)] == ["transition"]


def test_assign_splits_alternates_within_each_stratum_in_hash_order():
    items = synthetic.synthetic_dataset(synthetic.PAPER_TARGETS)
    splits = ulqs.assign_splits(items)
    assert set(splits) == {entry["item_id"] for entry in items}
    for letter, target in synthetic.PAPER_TARGETS.items():
        members = [entry["item_id"] for entry in items if entry["stratum"] == letter]
        calibration = sum(splits[item_id] == "calibration" for item_id in members)
        assert calibration == (target + 1) // 2
    assert ulqs.assign_splits(list(reversed(items))) == splits


def test_rated_units_include_abstention_units():
    assert ulqs.rated_units(item("A")) == ["SYN-A-001-c1"]
    assert ulqs.rated_units(item("C")) == ["SYN-C-001-abstention"]
    assert ulqs.rated_units(item("F")) == ["SYN-F-001-t1-c1", "SYN-F-001-t2-abstention"]
    assert ulqs.rated_units(item("G")) == ["SYN-G-001-c1"]


def test_the_rc1_shape_validates_as_schema_1_0():
    entry = item()
    for key in ("dataset_version", "item_kind", "split"):
        entry.pop(key)
    entry["validation"].pop("human_reviewed")
    entry["schema_version"] = "1.0"
    assert ulqs.validate_item(entry) == []


def test_the_schema_file_agrees_with_the_validator():
    schema = json.loads(ulqs.SCHEMA_PATH.read_text(encoding="utf-8"))
    properties = schema["properties"]
    assert tuple(schema["required"]) == ulqs.REQUIRED
    assert set(properties) == set(ulqs.REQUIRED) | set(ulqs.OPTIONAL)
    assert tuple(properties["status"]["enum"]) == ulqs.STATES
    assert tuple(properties["stratum"]["enum"]) == ulqs.STRATA
    assert tuple(properties["bloom"]["enum"]) == ulqs.BLOOM
    assert tuple(properties["difficulty"]["enum"]) == ulqs.DIFFICULTY
    assert tuple(properties["retrieval_type"]["enum"]) == ulqs.RETRIEVAL_TYPES
    assert tuple(properties["leakage_risk"]["enum"]) == ulqs.LEAKAGE
    assert tuple(properties["license_class"]["enum"]) == ulqs.LICENSE_CLASSES
    assert tuple(properties["schema_version"]["enum"]) == ulqs.SCHEMA_VERSIONS
    assert properties["item_kind"]["enum"] == [*ulqs.ITEM_KINDS, None]
    assert properties["split"]["enum"] == [*ulqs.SPLITS, None]
    assert tuple(properties["quality_scores"]["required"]) == ulqs.QUALITY_KEYS
    assert properties["item_id"]["pattern"] == ulqs.ITEM_ID.pattern
    assert properties["corpus_version"]["pattern"] == ulqs.CORPUS_VERSION.pattern
    assert schema["$defs"]["pointer"]["pattern"] == ulqs.EVIDENCE_ID.pattern
    assert tuple(schema["$defs"]["negative_evidence"]["required"]) == ulqs.NEGATIVE_KEYS
    assert tuple(schema["$defs"]["negative_evidence"]["properties"]["methods"]["items"]["enum"]) == ulqs.NEGATIVE_METHODS
    assert tuple(properties["replays"]["items"]["properties"]["level"]["enum"]) == ulqs.REPLAY_LEVELS
    conditions = json.dumps(schema["allOf"])
    for rule in ('"const": "1.1"', '"minItems": 2', '"const": "abstain"', '"const": "G"', '"const": "F"'):
        assert rule in conditions, rule
    # Where jsonschema happens to be installed (it is not an API requirement, so CI checks the structure above only), the
    # schema accepts every synthetic stratum item and rejects what the validator rejects.
    try:
        import jsonschema
    except ImportError:
        return
    validator = jsonschema.Draft202012Validator(schema)
    for entry in synthetic.synthetic_dataset(synthetic.SMALL):
        assert not list(validator.iter_errors(entry)), entry["item_id"]
    for mutate in (lambda i: i.pop("question"), lambda i: i.update(bloom="memorise"), lambda i: i.pop("gold_answer"),
                   lambda i: i.update(conversation=[]), lambda i: i.update(extra_field=1)):
        entry = item()
        mutate(entry)
        assert ulqs.validate_item(entry) and list(validator.iter_errors(entry))


def test_the_legacy_loader_still_reads_and_validates_its_own_schema():
    items = load_lqs(REPO_ROOT / "lqs" / "manifest.jsonl")
    assert items == []
    validate_lqs(items, enforce_proposal_range=False)


def test_transition_problems_compare_an_item_set_with_its_predecessor():
    reviewed = [{**item, "status": "review", "item_kind": "instructional",
                 "validation": {**item["validation"], "human_reviewed": True}} for item in synthetic.synthetic_dataset({"A": 2, "C": 1})]
    frozen = [{**item, "status": "frozen"} for item in reviewed]
    assert ulqs.transition_problems(reviewed, frozen) == []
    assert ulqs.transition_problems(frozen, frozen) == []
    skipped = [{**reviewed[0], "status": "candidate"}] + reviewed[1:]
    assert [(p.item_id, p.code) for p in ulqs.transition_problems(skipped, frozen)] == [("SYN-A-001", "transition")]
    edited = [{**frozen[0], "topic": "another invented topic"}] + frozen[1:]
    assert [p.code for p in ulqs.transition_problems(frozen, edited)] == ["frozen_content_changed"]
    assert [(p.item_id, p.code) for p in ulqs.transition_problems(frozen, frozen[1:])] == [("SYN-A-001", "removed")]
    assert [p.code for p in ulqs.transition_problems(frozen[1:], frozen)] == ["transition"]  # a new item cannot start frozen
    assert ulqs.transition_problems(frozen, [{**frozen[0], "status": "retired"}] + frozen[1:]) == []
