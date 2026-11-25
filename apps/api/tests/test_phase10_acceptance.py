"""Phase 10 acceptance tests: the evaluation and research harness (plan L1680-1742; Phase 10 spec 8.1).

Every input is synthetic and built in the test's own tmp_path; scripts run in-process through main(argv). AC-10-1, AC-10-4,
AC-10-5 and AC-10-6 are proven on synthetic data and the live half of AC-10-3 with a scripted fake provider (spec R-e);
their real-data halves are deferred (DI-129..DI-143). No test reads a private file, and none writes into the checkout.
"""

from __future__ import annotations

import ast
from collections import Counter
import dataclasses
import datetime as datetime_module
from fractions import Fraction
import importlib
import inspect
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
API_ROOT = REPO_ROOT / "apps" / "api"
for _path in (REPO_ROOT, REPO_ROOT / "scripts"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from evaluation.qcai_eval import (  # noqa: E402
    ablation, agreement, analysis_plans, contamination, governance, planes, providers, runner, seeded_faults, synthetic, ulqs,
)
from evaluation.qcai_eval.canonical import canonical_sha256, dumps_line, lf_sha256, read_jsonl, write_lf  # noqa: E402
from evaluation.qcai_eval.payload_log import EVIDENCE_KEYS, LOG_KEYS  # noqa: E402
from evaluation.qcai_eval.pointers import EvidenceCatalog, PointerResolver, content_sha256, public_span_lookup, resolve_items  # noqa: E402

SPEC_PATH = REPO_ROOT / "docs" / "architecture" / "phase10-implementation-spec.md"
RECORDS = REPO_ROOT / "docs" / "evaluation" / "phase10"
SYNTHETIC_SPEC = RECORDS / "synthetic_run_spec_v1.json"
SYNTHETIC_RECORD = RECORDS / "synthetic_run_record_v1.json"
RUBRIC_SHA = "a" * 64
LIVE_REASONS = ["no_live_adapter", "research_plane_absent", "D-14 open", "D-07 open", "D-08 open", "D-12 open", "irb_not_filed",
                "provider_terms_unrecorded", "licence_ruling_unrecorded", "research_use_unconfirmed", "semantic_backend_off"]


def script(name):
    return importlib.import_module(name)


@pytest.fixture(autouse=True)
def _the_run_day_is_the_synthetic_specs_day(monkeypatch):
    """A confirmatory or live run is judged on the UTC day it is planned (the run window, spec 3.13): these tests plan
    theirs on synthetic.CREATED's day, whatever the clock says; a test of the rule sets another day."""
    monkeypatch.setattr(governance, "utc_today", lambda: datetime_module.date.fromisoformat(synthetic.CREATED[:10]))


def fixture_texts():
    return json.loads(synthetic.CONTAMINATION_FIXTURE.read_text(encoding="utf-8"))


def stub_spec(tmp_path, counts=synthetic.SMALL, **kwargs):
    items_path, catalog_path, _items = synthetic.write_fixture_set(tmp_path, counts)
    return synthetic.spec_dict(items_path=items_path, catalog_path=catalog_path, **kwargs)


def write_spec(tmp_path, spec, name="spec.json"):
    path = Path(tmp_path) / name
    write_lf(path, json.dumps(spec, indent=1, sort_keys=True) + "\n")
    return path


def run_main(argv):
    return script("run_evaluation").main([str(value) for value in argv])


# ===================================================================================================== AC-10-1


def _freeze_case(tmp_path, *, counts=synthetic.PAPER_TARGETS, mutate=None, rules=None, corpus_edit=None, agreement_edit=None,
                 share="1/4", require_licensed=False, frozen=True, previous_edit=None, corpus_check=True, agent_edit=None,
                 pin_agent=True):
    """One freeze case built from its own dataset: items, catalog, corpus text, ratings, the agreement record, the review
    set the freeze starts from (every candidate moved to review, then to frozen) and the AI-agent re-check record. The
    committed rules pin no verifier model (D-07; DI-142), so a case pins the synthetic one unless `pin_agent` is false."""
    items = synthetic.synthetic_dataset(counts, human_reviewed=True, splits=True)
    catalog = EvidenceCatalog.from_lines(synthetic.synthetic_catalog(items))
    corpus = synthetic.corpus_text(items)
    if mutate:
        mutate(items)
    if corpus_edit:
        corpus_edit(corpus)
    rules = rules or ulqs.load_freeze_rules()
    if pin_agent:
        rules = dataclasses.replace(rules, agent_models=(synthetic.SYNTHETIC_AGENT_MODEL,))
    ratings = synthetic.synthetic_ratings(items, rubric_sha256=RUBRIC_SHA, share=share, disagree=1)
    record = agreement.agreement_record(ratings, items, rules=rules, rubric_sha256=RUBRIC_SHA, ratings_sha256="b" * 64)
    if agreement_edit:
        record = agreement_edit(record, items)
    previous = [{**item, "status": "review"} if item["status"] == "candidate" else item for item in items]
    if previous_edit:
        previous = previous_edit(json.loads(json.dumps(previous)))
    if frozen:  # the agreement record is computed before freezing and stays current after it
        items = [{**item, "status": "frozen"} if item["status"] == "candidate" else item for item in items]
    report = resolve_items(items, PointerResolver(catalog=catalog, corpus_text=corpus.get if corpus_check else None))
    agent = synthetic.agent_check(items)
    if agent_edit:
        agent = agent_edit(agent, items)
    result = ulqs.freeze_check(items, rules=rules, pointer_report=report, agreement=record, previous=previous,
                               require_licensed=require_licensed, agent_check=agent)
    return result, items, record


def test_ac_10_1_a_v1_0_set_at_the_paper_targets_with_resolving_pointers_and_alpha_passes_the_freeze_check(tmp_path, capsys):
    result, items, record = _freeze_case(tmp_path)
    assert result.passed and result.failures == ()
    assert len(items) == 160 and ulqs.stratum_counts(items) == synthetic.PAPER_TARGETS
    assert Fraction(record["alpha_nominal_label"]) >= Fraction("0.667") and record["gate"]["passed"]
    kinds = {unit.endswith("-abstention") for item in items for unit in ulqs.rated_units(item)}
    assert kinds == {True, False}  # claim units and abstention units are both rated
    for letter, (rated, total) in record["coverage"]["per_stratum"].items():
        assert rated * 4 >= total, letter
    assert record["dataset_content_sha256"] == ulqs.dataset_content_sha256(items)
    # The strict freeze check is the research plane's: the script refuses the same synthetic set (exit 2), and refuses a
    # freeze without the set it starts from or without the corpus text before it reads anything.
    items_path = synthetic.write_jsonl(tmp_path / "frozen.jsonl", items)
    previous_path = synthetic.write_jsonl(tmp_path / "review.jsonl", [{**item, "status": "review"} for item in items])
    corpus_dir = tmp_path / "text"
    corpus_dir.mkdir()
    validate = script("validate_ulqs")
    capsys.readouterr()
    assert validate.main(["--items", str(items_path), "--freeze", "--previous", str(previous_path), "--corpus-text", str(corpus_dir)]) == 2
    assert "--freeze refuses synthetic items" in capsys.readouterr().err
    for missing in (["--previous", str(previous_path)], ["--corpus-text", str(corpus_dir)], []):
        assert validate.main(["--items", str(items_path), "--freeze", *missing]) == 2
        assert "--freeze needs --previous" in capsys.readouterr().err


def _rules_with(targets):
    rules = ulqs.load_freeze_rules()
    return dataclasses.replace(rules, targets=dict(targets))


def _with(counts, **changes):
    return {**counts, **changes}


def _set_one(path, value, count=1):
    def mutate(items):
        for item in items[:count]:
            target = item
            *parents, last = path
            for key in parents:
                target = target[key]
            target[last] = value
    return mutate


def _inject(**fields):
    def edit(record, items):
        record = json.loads(json.dumps(record))
        for key, value in fields.items():
            if key in ("share", "per_stratum"):
                record["coverage"][key] = value if key == "share" else {**record["coverage"]["per_stratum"], **value}
            else:
                record[key] = value
        return record
    return edit


def _stale(record, items):
    other = json.loads(json.dumps(items))
    other[0]["question"] = "A different invented question?"
    return {**record, "dataset_content_sha256": ulqs.dataset_content_sha256(other)}


def _stale_items(items):
    other = json.loads(json.dumps(items))
    other[0]["question"] = "A different invented question?"
    return other


def _agent_of(agent, items, changed=()):
    """The agent's record as if it had checked `items` (an earlier content), listing `changed` as changed after a flag."""
    return {**agent, "checked_items": synthetic.agent_check(items)["checked_items"], "items_changed_after_flag": list(changed)}


def _first_live_id(items):
    return next(item["item_id"] for item in items if item["status"] != "retired")


def _retire_first(items):
    items[0]["status"] = "retired"


def _previous_live_first(previous):
    """The set the freeze starts from, with the item retired since (`_retire_first`) still in review when the agent checked."""
    previous[0]["status"] = "review"
    return previous


def _retire_confirmation(letter):
    def mutate(items):
        for item in items:
            if item["stratum"] == letter and item["split"] == "confirmation":
                item["status"] = "retired"
    return mutate


def _as_checked_before_retirement(items):
    """`items` as the agent checked them: the item retired since was still live (status is not part of its content)."""
    return [{**item, "status": "frozen"} if item["status"] == "retired" else item for item in items]


def _flip_split(items):
    first = next(item for item in items if item["stratum"] == "A" and item["split"] == "calibration")
    first["split"] = "confirmation"


def _unknown_pointer(items):
    target = next(item for item in items if item["stratum"] == "A")
    target["evidence_ids"] = ["EV-SYN-p990-01"]
    target["atomic_claims"][0]["evidence_ids"] = ["EV-SYN-p990-01"]


def _bloom(items):
    for item in items[:34]:
        item["bloom"] = "remember"


def _bibliographic(items):
    for item in items[:18]:
        item["item_kind"] = "bibliographic"


def _first_previous(change):
    def edit(previous):
        previous[0].update(change)
        return previous
    return edit


def _extra_previous(previous):
    return previous + [{**previous[0], "item_id": "SYN-A-999"}]


def _bad_corpus(corpus):
    key = sorted(corpus)[0]
    corpus[key] = corpus[key].replace("Synthetic", "Synthetik")


T = synthetic.PAPER_TARGETS
FREEZE_CASES = {
    "119 items": (dict(counts=_with(T, A=1, B=23), rules=_rules_with(_with(T, A=1, B=23))), {"count_out_of_range"}),
    "201 items": (dict(counts=_with(T, A=81), rules=_rules_with(_with(T, A=81))), {"count_out_of_range"}),
    "stratum off target": (dict(counts=_with(T, A=41)), {"stratum_off_target:A"}),
    "stratum missing": (dict(counts=_with(T, A=65, G=0)), {"stratum_missing:G", "stratum_off_target:A"}),
    "unknown EV pointer": (dict(mutate=_unknown_pointer, corpus_edit=None), {"unresolved_pointers"}),
    "corpus text hash mismatch": (dict(corpus_edit=_bad_corpus), {"pointer_hash_mismatch"}),
    "alpha 666/1000": (dict(agreement_edit=_inject(alpha_nominal_label="666/1000")), {"alpha_below_floor"}),
    "alpha 2/3": (dict(agreement_edit=_inject(alpha_nominal_label="2/3")), {"alpha_below_floor"}),
    "alpha 667/1000": (dict(agreement_edit=_inject(alpha_nominal_label="667/1000")), set()),
    "coverage below 1/4": (dict(agreement_edit=_inject(share="1/5")), {"second_rated_below_share"}),
    "one stratum below ceil(n/4)": (dict(agreement_edit=_inject(per_stratum={"A": [9, 40]})), {"stratum_second_rated_below_share:A"}),
    "no agreement record": (dict(agreement_edit=lambda record, items: None), {"no_agreement_record"}),
    "agreement for other content": (dict(agreement_edit=_stale), {"agreement_stale"}),
    "an item in review": (dict(mutate=_set_one(("status",), "review")), {"state_not_frozen"}),
    "human review missing": (dict(mutate=_set_one(("validation", "human_reviewed"), False)), {"human_review_missing"}),
    "Bloom 79%": (dict(mutate=_bloom), {"bloom_below_share"}),
    "bibliographic 11%": (dict(mutate=_bibliographic), {"bibliographic_above_share"}),
    "item_kind null": (dict(mutate=_set_one(("item_kind",), None)), {"item_kind_unmarked"}),
    "two corpus versions": (dict(mutate=_set_one(("corpus_version",), "QCAI-CORPUS-2030-01-01")), {"corpus_versions_differ"}),
    "synthetic items when licensed are required": (dict(require_licensed=True), {"synthetic_items"}),
    "no corpus-text check": (dict(corpus_check=False), {"pointers_not_text_verified"}),
    "no previous set": (dict(previous_edit=lambda previous: None), {"no_previous_set"}),
    "candidate straight to frozen": (dict(previous_edit=_first_previous({"status": "candidate"})), {"transition_invalid"}),
    "draft straight to frozen": (dict(previous_edit=_first_previous({"status": "draft"})), {"transition_invalid"}),
    "frozen content changed": (dict(previous_edit=_first_previous({"status": "frozen", "topic": "an older invented topic"})),
                               {"frozen_content_changed"}),
    "an item dropped instead of retired": (dict(previous_edit=_extra_previous), {"transition_invalid"}),
    # VBT RevB p. 15, "Benchmark verification before use": the conventional check, then the AI-agent re-check.
    "no agent check": (dict(agent_edit=lambda agent, items: None), {"agent_check_missing"}),
    "no verifier model pinned (D-07)": (dict(pin_agent=False), {"agent_model_not_pinned"}),
    "agent check of other content": (dict(agent_edit=lambda agent, items: _agent_of(agent, _stale_items(items))), {"agent_check_stale"}),
    # VBT RevB p. 15: "items changed after one of its flags are listed": a listed change passes; the list must be exact.
    "an item changed after a flag, listed": (dict(agent_edit=lambda agent, items: _agent_of(agent, _stale_items(items),
                                                                                           [_first_live_id(items)])), set()),
    "a listed item that did not change": (dict(agent_edit=lambda agent, items: {**agent, "items_changed_after_flag": [_first_live_id(items)]}),
                                          {"agent_check_invalid"}),
    "more listed changes than flags": (dict(agent_edit=lambda agent, items: {**_agent_of(agent, _stale_items(items), [_first_live_id(items)]),
                                                                              "agent_detected_defects": 0, "agent_false_alarms": 0}),
                                       {"agent_check_invalid"}),
    "a listed item twice": (dict(agent_edit=lambda agent, items: _agent_of(agent, _stale_items(items), [_first_live_id(items)] * 2)),
                            {"agent_check_invalid"}),
    "an item the agent did not check": (dict(agent_edit=lambda agent, items: {**agent, "checked_items": dict(list(
        agent["checked_items"].items())[1:])}), {"agent_check_incomplete"}),
    "checked content that is not a sha256": (dict(agent_edit=lambda agent, items: {**agent, "checked_items": {
        key: "x" for key in agent["checked_items"]}}), {"agent_check_invalid"}),
    "agent checked fewer items": (dict(agent_edit=lambda agent, items: {**agent, "items_checked": agent["items_checked"] - 1}),
                                  {"agent_check_incomplete"}),
    "agent disagreement unadjudicated": (dict(agent_edit=lambda agent, items: {**agent, "disagreements": 2}),
                                         {"agent_disagreements_unadjudicated"}),
    "adjudicated by the item's reviewer": (dict(agent_edit=lambda agent, items: {**agent, "adjudicated_by_non_reviewer": False}),
                                           {"agent_disagreements_unadjudicated"}),
    "agent model chosen after the check": (dict(agent_edit=lambda agent, items: {**agent, "model_chosen_before_check": False}),
                                           {"agent_model_not_chosen_before_check"}),
    "agent record without its counts": (dict(agent_edit=lambda agent, items: {k: v for k, v in agent.items() if k != "agent_false_alarms"}),
                                        {"agent_check_invalid"}),
    "agent record with another verdict schema": (dict(agent_edit=lambda agent, items: {**agent, "verdict_schema": "v1"}),
                                                 {"agent_check_invalid"}),
    "an unknown item changed after a flag": (dict(agent_edit=lambda agent, items: {**agent, "items_changed_after_flag": ["SYN-A-999"]}),
                                             {"agent_check_invalid"}),
    # Reviewers retire an item the agent checked in the review set (41 A items, one retired since): listed with its reason
    # it passes; unlisted the record is stale; left out of checked_items the record is incomplete, since the agent checked
    # every item live in the set the freeze starts from. An item retired before the check is not in checked_items.
    "an item retired after a flag, listed": (dict(counts=_with(T, A=41), mutate=_retire_first, previous_edit=_previous_live_first,
                                                  agent_edit=lambda agent, items: _agent_of({**agent, "items_checked": len(items)},
                                                                                            _as_checked_before_retirement(items),
                                                                                            [items[0]["item_id"]])), set()),
    "an item retired after a flag, unlisted": (dict(counts=_with(T, A=41), mutate=_retire_first, previous_edit=_previous_live_first,
                                                    agent_edit=lambda agent, items: _agent_of({**agent, "items_checked": len(items)},
                                                                                              _as_checked_before_retirement(items))),
                                               {"agent_check_stale"}),
    "an item retired after the check, dropped from checked_items": (dict(counts=_with(T, A=41), mutate=_retire_first,
                                                                         previous_edit=_previous_live_first), {"agent_check_incomplete"}),
    "an item retired without a flag, listed as such": (dict(counts=_with(T, A=41), mutate=_retire_first, previous_edit=_previous_live_first,
                                                            agent_edit=lambda agent, items: {**_agent_of(
                                                                {**agent, "items_checked": len(items)}, _as_checked_before_retirement(items)),
                                                                "items_changed_without_flag": [items[0]["item_id"]],
                                                                "agent_detected_defects": 0, "agent_false_alarms": 0}), set()),
    "an item listed with both reasons": (dict(counts=_with(T, A=41), mutate=_retire_first, previous_edit=_previous_live_first,
                                              agent_edit=lambda agent, items: {**_agent_of(
                                                  {**agent, "items_checked": len(items)}, _as_checked_before_retirement(items),
                                                  [items[0]["item_id"]]), "items_changed_without_flag": [items[0]["item_id"]]}),
                                         {"agent_check_invalid"}),
    "an item retired before the check": (dict(counts=_with(T, A=41), mutate=_retire_first), set()),
    "an item retired before the check, in checked_items": (dict(counts=_with(T, A=41), mutate=_retire_first, agent_edit=lambda agent, items: _agent_of(
        {**agent, "items_checked": len(items)}, _as_checked_before_retirement(items), [items[0]["item_id"]])), {"agent_check_incomplete"}),
    # Plan 10.5(2) "calibration and confirmation items split [Risk R-25]": every live item carries a split, balanced per stratum.
    "an item without a split": (dict(mutate=_set_one(("split",), None)), {"split_missing"}),
    "a stratum's split unbalanced": (dict(mutate=_flip_split), {"split_unbalanced:A"}),
    # The balance counts retired items (a frozen item's split never changes), so retirements could leave a stratum with
    # one split only: 30 D items, the 15 confirmation items retired, balanced 15/15 but no live confirmation item.
    "a stratum left with no live confirmation item": (dict(counts=_with(T, D=30), mutate=_retire_confirmation("D")),
                                                      {"split_live_missing:D"}),
}


@pytest.mark.parametrize("case", sorted(FREEZE_CASES))
def test_ac_10_1_each_unmet_freeze_condition_fails_with_its_code(tmp_path, case):
    kwargs, expected = FREEZE_CASES[case]
    result, _items, _record = _freeze_case(tmp_path, **kwargs)
    assert set(result.failures) == expected, (case, result.failures)
    assert result.passed is (not expected)


def test_ac_10_1_freeze_rules_outside_the_item_range_are_refused(tmp_path):
    raw = json.loads(ulqs.DEFAULT_FREEZE_RULES.read_text(encoding="utf-8"))
    for changes, total in (({"A": 1, "B": 23}, 119), ({"A": 81}, 201)):
        changed = json.loads(json.dumps(raw))
        for letter, target in changes.items():
            changed["strata"][letter]["target"] = target
        path = tmp_path / f"rules-{total}.json"
        path.write_text(json.dumps(changed), encoding="utf-8")
        with pytest.raises(ValueError, match=f"total {total}"):
            ulqs.load_freeze_rules(path)
    assert sum(ulqs.load_freeze_rules().targets.values()) == 160


def test_ac_10_1_freeze_rules_without_the_agent_check_or_its_pinned_models_are_refused(tmp_path):
    # VBT RevB p. 15: no freeze without the AI-agent re-check, so the rules must name its record and a model list.
    raw = json.loads(ulqs.DEFAULT_FREEZE_RULES.read_text(encoding="utf-8"))
    for index, edit in enumerate((lambda r: r.pop("agent_check"), lambda r: r["agent_check"].update(record="other-v1"),
                                  lambda r: r["agent_check"].update(pinned_models="SYN-VERIFIER-1"),
                                  lambda r: r["agent_check"].update(pinned_models=[""]))):
        changed = json.loads(json.dumps(raw))
        edit(changed)
        path = tmp_path / f"rules-agent-{index}.json"
        path.write_text(json.dumps(changed), encoding="utf-8")
        with pytest.raises(ValueError, match="agent_check must name"):
            ulqs.load_freeze_rules(path)
    changed = json.loads(json.dumps(raw))
    changed["agent_check"]["pinned_models"] = [synthetic.SYNTHETIC_AGENT_MODEL]
    path = tmp_path / "rules-agent-pinned.json"
    path.write_text(json.dumps(changed), encoding="utf-8")
    assert ulqs.load_freeze_rules(path).agent_models == (synthetic.SYNTHETIC_AGENT_MODEL,)


def _research_plane_freeze(tmp_path):
    """The validator's strict freeze over a set shaped like research items (not synthetic, so --freeze runs), built from
    the invented synthetic texts in the test's own tmp_path (outside the checkout, so every path is private): the review
    set, the frozen set, its catalog and corpus text, ratings, a rubric, rules that pin the synthetic verifier model and
    an agent-check record whose first live item changed after a flag. Returns (argv, frozen items, the agent record)."""
    def research(records):
        text = json.dumps(records).replace("EV-SYN-", "EV-" + "2026-").replace("SYN-", "ULQS-")
        return json.loads(text.replace("SYNTHETIC-CORPUS-v1", "QCAI-CORPUS-" + "2026-01-01"))

    items = research(synthetic.synthetic_dataset(synthetic.PAPER_TARGETS, human_reviewed=True, splits=True))
    for item in items:
        item["license_class"] = "private_eval_full_span"
    previous = [{**item, "status": "review"} if item["status"] == "candidate" else item for item in items]
    frozen = [{**item, "status": "frozen"} if item["status"] == "candidate" else item for item in items]
    text = tmp_path / "text"
    text.mkdir()
    for document, body in synthetic.corpus_text(frozen).items():
        write_lf(text / f"{document}.txt", body)
    rubric = tmp_path / "rubric.md"
    write_lf(rubric, "# an invented rubric\n")
    ratings = synthetic.write_jsonl(tmp_path / "ratings.jsonl", synthetic.synthetic_ratings(
        frozen, rubric_sha256=lf_sha256(rubric), share="1/4", disagree=1))
    raw = json.loads(ulqs.DEFAULT_FREEZE_RULES.read_text(encoding="utf-8"))
    raw["agent_check"]["pinned_models"] = [synthetic.SYNTHETIC_AGENT_MODEL]
    rules = tmp_path / "rules.json"
    write_lf(rules, json.dumps(raw) + "\n")
    first = _first_live_id(frozen)
    agent_record = {**synthetic.agent_check(frozen), "report_sha256": "b" * 64, "agent_false_alarms": 2, "agent_missed_defects": 3,
                    "items_changed_after_flag": [first]}
    agent_record["checked_items"] = {**agent_record["checked_items"], first: "c" * 64}  # its content before the change
    agent = tmp_path / "agent-check.json"
    write_lf(agent, json.dumps(agent_record) + "\n")
    argv = ["--items", synthetic.write_jsonl(tmp_path / "frozen.jsonl", frozen), "--previous", synthetic.write_jsonl(tmp_path / "review.jsonl", previous),
            "--catalog", synthetic.write_jsonl(tmp_path / "catalog.jsonl", research(synthetic.synthetic_catalog(frozen))),
            "--corpus-text", text, "--rules", rules, "--ratings", ratings, "--rubric", rubric, "--agreement-out", tmp_path / "agreement.json",
            "--freeze", "--agent-check", agent, "--freeze-out", tmp_path / "freeze-record.json", "--access-log", tmp_path / "access.jsonl",
            "--actor-role", "RL"]
    return [str(value) for value in argv], frozen, agent_record


def test_ac_10_1_the_freeze_record_the_validator_writes_is_the_one_the_confirmatory_gate_loads(tmp_path):
    # validate_ulqs.py --freeze --freeze-out writes `ulqs-freeze-record-v1`; governance.load_freeze_record (the gate's
    # reader) accepts exactly FREEZE_RECORD_KEYS, so a writer that dropped, renamed or mis-filled a key fails here.
    argv, frozen, agent_record = _research_plane_freeze(tmp_path)
    assert script("validate_ulqs").main(argv) == 0
    path = tmp_path / "freeze-record.json"
    record = governance.load_freeze_record(path)
    assert set(record) == {"record", *governance.FREEZE_RECORD_KEYS} and record["record"] == "ulqs-freeze-record-v1"
    assert record["passed"] is True and record["failures"] == []
    assert record["dataset_sha256"] == ulqs.dataset_sha256(frozen) and record["dataset_content_sha256"] == ulqs.dataset_content_sha256(frozen)
    assert record["rules_sha256"] == ulqs.load_freeze_rules(Path(argv[argv.index("--rules") + 1])).sha256
    assert record["agreement_sha256"] == canonical_sha256(json.loads((tmp_path / "agreement.json").read_text(encoding="utf-8")))
    # agent_check_sha256 is the canonical sha256 of the agent-check record; the agent's full report is pinned by the
    # record's report_sha256, which the freeze record copies as agent_report_sha256.
    assert record["agent_check_sha256"] == canonical_sha256(agent_record)
    assert record["agent_report_sha256"] == agent_record["report_sha256"] == "b" * 64
    assert record["agent_model_id"] == agent_record["agent_model_id"] == synthetic.SYNTHETIC_AGENT_MODEL
    for key in ("agent_detected_defects", "agent_false_alarms", "agent_missed_defects", "disagreements_adjudicated"):
        assert record[key] == agent_record[key], key
    assert record["items_changed_after_flag"] == agent_record["items_changed_after_flag"] == [_first_live_id(frozen)]
    assert ("write", "freeze_record", lf_sha256(path)) in [
        (line["action"], line["artifact_kind"], line["artifact_sha256"]) for line in read_jsonl(tmp_path / "access.jsonl")]


def test_ac_10_1_the_validator_refuses_an_unreadable_rubric_rules_file_or_agent_record_with_exit_2(tmp_path, capsys):
    # The documented exit 2 inputs: a rubric that is not there, freeze rules that do not load (here an older rules file
    # without agent_check), and an agent-check record that is not shaped as ulqs-agent-check-v1. None is a traceback.
    argv, frozen, agent_record = _research_plane_freeze(tmp_path)
    validate = script("validate_ulqs")

    def swap(flag, value):
        changed = list(argv)
        changed[changed.index(flag) + 1] = str(value)
        return changed

    old_rules = json.loads(ulqs.DEFAULT_FREEZE_RULES.read_text(encoding="utf-8"))
    old_rules.pop("agent_check")
    write_lf(tmp_path / "old-rules.json", json.dumps(old_rules) + "\n")
    no_ratings = [value for index, value in enumerate(argv) if not (
        value in ("--ratings", "--rubric", "--agreement-out") or (index and argv[index - 1] in ("--ratings", "--rubric", "--agreement-out")))]
    cases = {"a missing rubric": swap("--rubric", tmp_path / "absent.md"),
             "rules without agent_check (ratings)": swap("--rules", tmp_path / "old-rules.json"),
             "rules without agent_check (freeze only)": [*no_ratings[:no_ratings.index("--rules") + 1], str(tmp_path / "old-rules.json"),
                                                         *no_ratings[no_ratings.index("--rules") + 2:]],
             "rules that are not there (freeze only)": [*no_ratings[:no_ratings.index("--rules") + 1], str(tmp_path / "absent.json"),
                                                        *no_ratings[no_ratings.index("--rules") + 2:]]}
    # Rules that parse but are shaped wrongly (a list, a section missing, a stratum or section that is not an object, a
    # bound that is not an integer, Infinity and 1.5 included, a file nested too deeply to parse) are invalid too, on the
    # --ratings path and on the --freeze path.
    malformed = {"a list": [], "no items": {k: v for k, v in old_rules.items() if k != "items"},
                 "no agreement": {k: v for k, v in old_rules.items() if k != "agreement"},
                 "no coverage": {k: v for k, v in old_rules.items() if k != "coverage"},
                 "a stratum that is a number": {**old_rules, "strata": {**old_rules["strata"], "A": 40}},
                 "items that are a list": {**old_rules, "items": [120, 200]},
                 "a null bound": {**old_rules, "items": {"min": None, "max": 200}},
                 "a zero denominator": {**old_rules, "agreement": {**old_rules["agreement"], "alpha_min": "1/0"}},
                 "an infinite bound": {**old_rules, "items": {"min": float("inf"), "max": 200}},
                 "a fractional bound": {**old_rules, "items": {"min": 1.5, "max": 200}},
                 "a boolean bound": {**old_rules, "items": {"min": 120, "max": True}},
                 "a bound past any float": {**old_rules, "items": {"min": 120, "max": "1e999"}},
                 "nesting too deep": "[" * 200000 + "]" * 200000}
    for name, value in malformed.items():
        if isinstance(value, dict):  # old_rules lacks agent_check: give each the valid one, so only its own defect remains
            value = {**value, "agent_check": {"record": "ulqs-agent-check-v1", "pinned_models": [synthetic.SYNTHETIC_AGENT_MODEL]}}
        path = tmp_path / f"rules-{name.replace(' ', '-')}.json"
        write_lf(path, (value if isinstance(value, str) else json.dumps(value)).replace('"1e999"', "1e999") + "\n")
        with pytest.raises(ValueError, match="freeze rules"):
            ulqs.load_freeze_rules(path)
        cases[f"rules: {name} (ratings)"] = swap("--rules", path)
        cases[f"rules: {name} (freeze only)"] = [*no_ratings[:no_ratings.index("--rules") + 1], str(path),
                                                 *no_ratings[no_ratings.index("--rules") + 2:]]
    for name, value in (("list", []), ("missing key", {k: v for k, v in agent_record.items() if k != "checked_items"}),
                        ("bad count", {**agent_record, "agent_false_alarms": -1})):
        write_lf(tmp_path / f"agent-{name}.json", json.dumps(value) + "\n")
        cases[f"an agent record: {name}"] = swap("--agent-check", tmp_path / f"agent-{name}.json")
    for name, case in cases.items():
        (tmp_path / "freeze-record.json").unlink(missing_ok=True)
        capsys.readouterr()
        assert validate.main(case) == 2, name
        err = capsys.readouterr().err
        assert "refused (exit 2)" in err and "Traceback" not in err, name
        assert not (tmp_path / "freeze-record.json").exists(), name
    # Without --freeze a malformed agent record is refused the same way (it is checked when read).
    write_lf(tmp_path / "agent-plain.json", "[]\n")
    assert validate.main(["--items", argv[argv.index("--items") + 1], "--agent-check", str(tmp_path / "agent-plain.json"),
                          "--access-log", str(tmp_path / "access.jsonl"), "--actor-role", "RL"]) == 2


def test_ac_10_1_the_strata_targets_are_the_paper_s_in_one_provisional_data_file():
    rules = ulqs.load_freeze_rules()
    raw = rules.raw
    assert rules.targets == {"A": 40, "B": 25, "C": 20, "D": 15, "E": 15, "F": 20, "G": 25} and sum(rules.targets.values()) == 160
    assert raw["provisional"] is True and "DI-136" in raw["authority"]
    assert [raw["strata"][letter]["paper"] for letter in ulqs.STRATA] == ["S1", "S2", "S3", "S4", "S5", "S6", "S7"]
    assert raw["strata"]["F"]["unit"] == "dialogues"
    assert raw["conflicting_allocation"]["strata"] == {"A": 44, "B": 28, "C": 20, "D": 14, "E": 14, "F": 12, "G": 28}
    assert raw["e1_label_agreement"]["double_labelled_claims_min"] == 200
    assert "not a ULQS freeze condition" in raw["e1_label_agreement"]["applies_to"]
    assert rules.alpha_min == Fraction("0.667") and rules.share_min == Fraction(1, 4)
    assert (rules.items_min, rules.items_max) == (120, 200)
    # The AI-agent re-check is a freeze condition; no verifier model is pinned until D-07 decides (DI-142).
    assert raw["agent_check"]["record"] == "ulqs-agent-check-v1" and rules.agent_models == ()
    assert "Benchmark verification before use" in raw["agent_check"]["source"] and "DI-142" in raw["agent_check"]["pinned_models_rule"]


def _rc1(items):
    """Synthetic items reshaped as rc1 records (schema 1.0, licensed class, EV-2026 pointers); every M5 field appears."""
    volume = "qcai" + "_2026"
    reshaped = []
    for index, item in enumerate(json.loads(json.dumps(items))):
        text = json.dumps(item).replace("SYN-", "ULQS-").replace("EV-ULQS-", "EV-2026-")
        rc1 = json.loads(text)
        for key in ("dataset_version", "item_kind", "split"):
            rc1.pop(key, None)
        rc1["validation"].pop("human_reviewed")
        rc1.update(schema_version="1.0", license_class="private_eval_full_span", corpus_version="QCAI-CORPUS-2030-01-01",
                   corpus_scope=[volume], status="candidate")
        rc1["provenance"] = {"created_utc": "2030-01-01T00:00:00Z", "author": synthetic.SENTINEL,
                             "migrated_from": "invented-v0", "migration_disposition": "convert" if index % 2 else "revise",
                             "note": "invented note"}
        rc1["question"] = f"{rc1['question']} {synthetic.SENTINEL}"
        if index == 0:
            rc1["reasoning_chain"] = ["invented step one", "invented step two"]
            rc1["notes"] = "invented notes"
        for block in [rc1] + rc1.get("conversation", []):
            if "negative_evidence" in block:
                block["negative_evidence"]["corpus_version"] = "QCAI-CORPUS-2030-01-01"
        reshaped.append(rc1)
    return reshaped


def test_ac_10_1_the_rc1_shape_migrates_to_v1_0_and_the_migrator_writes_only_private_paths(tmp_path, capsys):
    rc1 = _rc1(synthetic.synthetic_dataset(synthetic.SMALL))
    assert ulqs.validate_dataset(rc1) == []
    fields = {key for item in rc1 for key in item}
    for key in ulqs.REQUIRED + ("expected_behavior", "gold_answer", "evidence_ids", "atomic_claims", "reasoning_chain", "notes",
                                "abstention_rationale", "negative_evidence", "conversation", "base_question", "replays", "invariance_checked"):
        assert key in fields, key
    source = synthetic.write_jsonl(tmp_path / "rc1.jsonl", rc1)
    output, access = tmp_path / "v1.jsonl", tmp_path / "access.jsonl"
    migrate = script("migrate_ulqs_rc1")
    assert migrate.main(["--input", str(source), "--output", str(output), "--author-role", "RL", "--access-log", str(access)]) == 0
    migrated = read_jsonl(output)
    assert ulqs.validate_dataset(migrated) == []
    for before, after in zip(sorted(rc1, key=lambda i: i["item_id"]), migrated):
        assert after["status"] == "candidate" and after["schema_version"] == "1.1" and after["dataset_version"] == "ULQS-v1.0"
        assert after["validation"]["human_reviewed"] is False and after["item_kind"] is None
        assert after["provenance"]["author"] == "RL" and after["corpus_version"] == before["corpus_version"]
        assert {k: v for k, v in after.items() if k not in ("schema_version", "dataset_version", "provenance", "validation", "item_kind", "split")} == \
               {k: v for k, v in before.items() if k not in ("schema_version", "provenance", "validation")}
    for letter in ulqs.STRATA:
        splits = [item["split"] for item in migrated if item["stratum"] == letter]
        assert sorted(splits) == ["calibration", "confirmation"], letter
    access_lines = read_jsonl(access)
    assert [line["action"] for line in access_lines] == ["read", "write"] and all(set(line) <= {
        "log", "at", "actor_role", "action", "artifact_kind", "artifact_sha256", "purpose", "run_id"} for line in access_lines)
    for public in (REPO_ROOT / "docs" / "evaluation" / "rc1-migrated.jsonl", REPO_ROOT / "evaluation" / "rc1-migrated.jsonl"):
        assert migrate.main(["--input", str(source), "--output", str(public), "--author-role", "RL", "--access-log", str(access)]) == 2
        assert not public.exists()
    assert migrate.main(["--input", str(source), "--output", str(tmp_path / "x.jsonl"), "--author-role", "RL"]) == 2
    captured = capsys.readouterr()
    assert synthetic.SENTINEL not in captured.out + captured.err
    assert synthetic.SENTINEL not in json.dumps([item["provenance"] for item in migrated])


def test_ac_10_1_ev_ids_resolve_through_the_catalog_and_span_ids_through_the_phase_2_resolver():
    from app.services.store import get_course_store

    lookup = public_span_lookup()
    store = get_course_store()
    public = next(record.span_id for record in store.span_registry.records if lookup(record.span_id) is not None)
    resolver = PointerResolver(catalog=EvidenceCatalog.load(synthetic.CATALOG_FIXTURE), span_lookup=lookup)
    resolution = resolver.resolve(public)
    assert resolution.status == "resolved" and resolution.kind == "span"
    assert "text" not in resolution.locator and resolution.locator["byte_length"] > 0
    record = store.span_registry.get(public)
    assert record.text not in json.dumps(resolution.locator)
    assert resolution.locator["content_hash"] == record.content_hash
    ev = resolver.resolve("EV-SYN-p001-01")
    assert ev.status == "resolved" and "text" not in ev.locator and ev.locator["content_sha256"] == content_sha256(synthetic.evidence_text("EV-SYN-p001-01"))
    assert resolver.resolve("span-" + "0" * 64).status == "unknown_pointer"


# ===================================================================================================== AC-10-2

TABLE_XV = [("NR", "Base-1"), ("LEX", "Base-2"), ("SEM", "Base-3"), ("GATE", "Base-4"), ("GATE+SV", "Prior"), ("GATE+V1", "Own-1"),
            ("VLOOP", "Own-2")]


def test_ac_10_2_each_of_the_seven_arms_differs_from_gate_only_in_its_declared_ablation_variables():
    table = ablation.load_arms()
    ablation.check_table(table)
    assert [(arm.arm, arm.scenario) for arm in table.arms.values()] == TABLE_XV
    gate = ablation.arm_configuration(table, "GATE")
    for arm_id, arm in table.arms.items():
        configuration = ablation.arm_configuration(table, arm_id)
        assert set(configuration) == set(gate)
        for key in gate:
            if key in arm.ablation:
                assert configuration[key] != gate[key], (arm_id, key)
            else:
                assert configuration[key] == gate[key], (arm_id, key)
    assert table.arms["NR"].ablation == {"retrieval": "none", "abstention_gate": False}
    assert table.arms["LEX"].ablation == {"retrieval": "lexical"}  # LEX keeps the gate (spec conflict 10)
    manifests = {arm: {**ablation.arm_configuration(table, arm), "package_sha256": "p"} for arm in ablation.ARM_IDS}
    ablation.assert_arm_parity(manifests, table=table)


def _parity_case(name):
    raw = json.loads(ablation.ARMS_PATH.read_text(encoding="utf-8"))
    table = ablation.table_from_raw(raw)
    manifests = {arm: {**ablation.arm_configuration(table, arm), "package_sha256": "p"} for arm in ablation.ARM_IDS}
    if name == "top_k differs in SEM":
        for arm in manifests:
            manifests[arm]["top_k"] = 9 if arm == "SEM" else 4
        return lambda: ablation.assert_arm_parity(manifests, table=table), "SEM: undeclared_difference:top_k"
    if name == "LEX declares the gate":
        raw["arms"][1]["ablation"]["abstention_gate"] = True
        return lambda: ablation.check_table(ablation.table_from_raw(raw)), "LEX: abstention_gate declared_but_equal"
    if name == "a missing arm":
        manifests.pop("VLOOP")
        return lambda: ablation.assert_arm_parity(manifests, table=table), "exactly the required arms"
    if name == "an unknown variable":
        raw["arms"][2]["ablation"]["temperature"] = 0.7
        return lambda: ablation.check_table(ablation.table_from_raw(raw)), "SEM: temperature is not an ablation variable"
    if name == "GATE with an ablation":
        raw["arms"][3]["ablation"] = {"verification": "v1-only"}
        return lambda: ablation.check_table(ablation.table_from_raw(raw)), "GATE: the baseline declares no ablation"
    raise AssertionError(name)


@pytest.mark.parametrize("case", ["top_k differs in SEM", "LEX declares the gate", "a missing arm", "an unknown variable", "GATE with an ablation"])
def test_ac_10_2_an_undeclared_difference_or_a_declared_variable_equal_to_gate_is_refused(case):
    call, message = _parity_case(case)
    with pytest.raises(ablation.ParityError, match=re.escape(message)):
        call()


def test_ac_10_2_the_runner_refuses_a_run_whose_arm_manifests_break_parity(tmp_path, monkeypatch):
    spec = write_spec(tmp_path, stub_spec(tmp_path))

    def broken(manifests):
        manifests["SEM"] = {**manifests["SEM"], "top_k": 9}
        return manifests

    monkeypatch.setattr(runner, "_manifest_hook", broken)
    out = tmp_path / "out"
    assert run_main(["--spec", spec, "--output-dir", out]) == 7
    assert not out.exists()


# ===================================================================================================== AC-10-3

BYTE_COMPARED = ("run_record.json", "payload_log.jsonl", "responses.jsonl")


class _Clock(datetime_module.datetime):
    instant = datetime_module.datetime(2030, 1, 1, tzinfo=datetime_module.timezone.utc)

    @classmethod
    def now(cls, tz=None):
        return cls.instant

    @classmethod
    def utcnow(cls):
        return cls.instant


def _outputs(directory):
    return {name: (Path(directory) / name).read_bytes() for name in BYTE_COMPARED}


def test_ac_10_3_a_stub_run_repeats_byte_identically(tmp_path, monkeypatch):
    spec = write_spec(tmp_path, stub_spec(tmp_path))
    results = []
    for index, (instant, seconds) in enumerate(((datetime_module.datetime(2030, 1, 1, tzinfo=datetime_module.timezone.utc), 1.0e9),
                                                 (datetime_module.datetime(2041, 6, 7, tzinfo=datetime_module.timezone.utc), 2.2e9))):
        monkeypatch.setattr(_Clock, "instant", instant)
        monkeypatch.setattr(datetime_module, "datetime", _Clock)
        monkeypatch.setattr(time, "time", lambda: seconds)
        monkeypatch.setattr(time, "time_ns", lambda: int(seconds * 1e9))
        out = tmp_path / f"run-{index}"
        assert run_main(["--spec", spec, "--output-dir", out]) == 0
        monkeypatch.undo()
        results.append((out, _outputs(out)))
    (first_dir, first), (second_dir, second) = results
    assert first == second
    for directory in (first_dir, second_dir, REPO_ROOT):
        for form in (str(directory), directory.as_posix(), json.dumps(str(directory))[1:-1], directory.name):
            for name, data in first.items():
                assert form.encode("utf-8") not in data, (name, form)
    record = json.loads(first["run_record.json"])
    assert record["created_at"] == "2026-11-24T00:00:00Z" and "2030" not in first["run_record.json"].decode()


def _recorded_spec(tmp_path, **kwargs):
    recording = synthetic.RECORDED_FIXTURE
    return synthetic.spec_dict(items_path="evaluation/fixtures/synthetic_ulqs_v1.jsonl",
                               catalog_path="evaluation/fixtures/synthetic_evidence_catalog_v1.jsonl", run_id="synthetic-recorded-v1",
                               mode="recorded", responder={"recorded": {"path": "evaluation/fixtures/recorded_responses_synthetic_v1.jsonl",
                                                                        "sha256": lf_sha256(recording)}}, **kwargs)


def test_ac_10_3_a_recorded_run_repeats_byte_identically_and_replays_its_failures(tmp_path):
    spec = write_spec(tmp_path, _recorded_spec(tmp_path))
    assert run_main(["--spec", spec, "--output-dir", tmp_path / "a"]) == 0
    assert run_main(["--spec", spec, "--output-dir", tmp_path / "b"]) == 0
    assert _outputs(tmp_path / "a") == _outputs(tmp_path / "b")
    record = json.loads((tmp_path / "a" / "run_record.json").read_text(encoding="utf-8"))
    assert record["mode"] == "recorded" and record["slis"]["provider_failures"] == {"server_error": 1}
    assert record["slis"]["retries"] >= 2 + 3
    header = read_jsonl(synthetic.RECORDED_FIXTURE)[0]
    assert header["source"] == "synthetic"
    tampered = _recorded_spec(tmp_path)
    tampered["responder"]["recorded"]["sha256"] = "0" * 64
    assert run_main(["--spec", write_spec(tmp_path, tampered, "t.json"), "--output-dir", tmp_path / "c"]) == 6


def test_ac_10_3_the_committed_synthetic_run_record_is_current(tmp_path):
    assert run_main(["--check", SYNTHETIC_RECORD, "--spec", SYNTHETIC_SPEC]) == 0
    spec = json.loads(SYNTHETIC_SPEC.read_text(encoding="utf-8"))
    assert spec["mode"] == "stub" and spec["purpose"] == "exploratory" and spec["package"]["path"] == "apps/api/app/config_package/v7.json"
    changed = tmp_path / "record.json"
    text = SYNTHETIC_RECORD.read_text(encoding="utf-8")
    changed.write_text(text.replace('"format_version": 1', '"format_version": 2', 1), encoding="utf-8")
    assert run_main(["--check", changed, "--spec", SYNTHETIC_SPEC]) == 1


def test_ac_10_3_a_live_run_with_a_scripted_provider_matches_the_stub_run_s_keys_and_seeds_and_reports_replicate_variance(tmp_path,
                                                                                                                         monkeypatch):
    # The live spec is planned on its own through plan_run, with every live condition met in a temporary research plane
    # and a package copy whose decisions read decided; the stub spec is planned separately against the same package. The
    # keys and seeds of the two plans, of their payload logs and of their records are then compared.
    live_spec, _package, out = _live_ready(tmp_path, monkeypatch)
    package = synthetic.decided_package(tmp_path)
    stub = stub_spec(tmp_path, package=package)
    live = {**stub, **{key: live_spec[key] for key in ("governance", "provider_terms", "licence_ruling", "research_use_confirmation")},
            "mode": "live", "responder": {"live": {"adapter": "fake-adapter", "providers": ["SYN-PROVIDER-1"]}}}
    stub_plan = runner.plan_run(stub)
    live_plan = runner.plan_run(live, out_dir=out)
    assert live_plan.requests is not stub_plan.requests and live_plan.pins["package"]["owner_decisions"]["D-07"] == "decided"
    assert [(r.request_key, r.seed_hex) for r in live_plan.requests] == [(r.request_key, r.seed_hex) for r in stub_plan.requests]
    stub_record = runner.execute_run(stub_plan, providers.StubResponder(), tmp_path / "stub")
    live_record = runner.execute_run(live_plan, providers.LIVE_ADAPTERS["fake-adapter"](), out)
    assert live_record["requests"]["digest"] == stub_record["requests"]["digest"] == runner.requests_digest(stub_plan)
    columns = lambda directory: [(line["request_key"], line["seed_hex"]) for line in read_jsonl(Path(directory) / "payload_log.jsonl")]  # noqa: E731
    assert columns(out) == columns(tmp_path / "stub")
    assert [(line["request_key"], line["seed_hex"]) for line in read_jsonl(out / "responses.jsonl")] == columns(out)
    assert live_record["mode"] == "live" and live_record["pins"]["models"] == {"model_ids": ["scripted-model-v1"], "prices": None}
    assert stub_record["pins"]["models"] is None
    assert set(live_record["replicate_variance"]) == set(ablation.ARM_IDS)
    for arm, block in live_record["replicate_variance"].items():
        assert len(block["er_by_replicate"]) == 3 and block["variance"] is not None, arm
    # A live plan whose seeds differed from the stub plan's (another run id) is caught by the same comparison.
    other = runner.plan_run({**live, "run_id": "synthetic-live-other"}, out_dir=out)
    assert [r.seed_hex for r in other.requests] != [r.seed_hex for r in stub_plan.requests]


def test_ac_10_3_live_mode_is_refused_here_with_every_named_reason(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("RESEARCH_PLANE_ROOT", raising=False)
    spec = stub_spec(tmp_path, mode="live", responder={"live": {"adapter": "none-wired"}}, run_id="synthetic-live-v1")
    with pytest.raises(runner.RunRefused) as refused:
        runner.plan_run(spec, out_dir=tmp_path / "out")
    assert refused.value.code == 9 and refused.value.reasons == LIVE_REASONS
    assert run_main(["--spec", write_spec(tmp_path, spec), "--output-dir", tmp_path / "out"]) == 9
    assert not (tmp_path / "out").exists()
    negative = {**spec, "licence_ruling": synthetic.licence_ruling_record(tmp_path / "ruling.json", determination="negative")}
    with pytest.raises(runner.RunRefused) as refused:
        runner.plan_run(negative)
    assert "licence_negative" in refused.value.reasons and "licence_ruling_unrecorded" not in refused.value.reasons
    # The IRB condition of a live run checks the dates as the confirmatory gate does.
    for record, reason in ((synthetic.irb_record(tmp_path / "old.json", approval_date="2025-01-01", expiry_date="2026-06-30"), "irb_expired"),
                           (synthetic.irb_record(tmp_path / "late.json", approval_date="2026-12-01", expiry_date=None), "irb_not_yet_approved")):
        with pytest.raises(runner.RunRefused) as refused:
            runner.plan_run({**spec, "governance": {"irb_record": record, "osf_record": None}})
        assert reason in refused.value.reasons and "irb_not_filed" not in refused.value.reasons


def test_ac_10_3_seeds_are_hashed_from_run_arm_item_and_replicate(tmp_path):
    plan = runner.plan_run(stub_spec(tmp_path))
    for request in plan.requests:
        assert request.seed_hex == synthetic_seed(plan.spec["run_id"], request)
    seeds = {(r.arm, r.item_id, r.replicate): r.seed_hex for r in plan.requests}
    assert seeds[("GATE", "SYN-A-001", 1)] != seeds[("GATE", "SYN-A-001", 2)] != seeds[("VLOOP", "SYN-A-001", 2)]


def synthetic_seed(run_id, request):
    import hashlib

    return hashlib.sha256("\x1f".join([run_id, request.arm, request.item_id, str(request.replicate)]).encode()).hexdigest()[:16]


def test_ac_10_3_metrics_are_computed_not_empty(tmp_path):
    plan = runner.plan_run(stub_spec(tmp_path))
    record = runner.execute_run(plan, providers.StubResponder(), tmp_path / "out")
    assert set(record["metrics"]) == set(ablation.ARM_IDS)
    for arm, metrics in record["metrics"].items():
        for key in ("ER", "CF", "CP", "CR", "CA", "AR", "IV", "abstention_decay", "fabrication", "citation_existence"):
            assert key in metrics, (arm, key)
        assert metrics["ER"]["total"] > 0 and metrics["CA"]["total"] > 0 and metrics["AR"]["total"] > 0, arm
        assert metrics["abstention_decay"]["by_turn_depth"], arm
    assert record["comparisons"]["note"] == "synthetic: no arm effect by construction (R-f)"
    assert record["bootstrap"]["method"] == "percentile" and record["bootstrap"]["resamples"] == 1000


def test_ac_10_3_level_units_carry_identical_evidence_and_nr_sends_none(tmp_path):
    plan = runner.plan_run(stub_spec(tmp_path))
    runner.execute_run(plan, providers.StubResponder(), tmp_path / "out")
    log = read_jsonl(tmp_path / "out" / "payload_log.jsonl")
    for arm in ablation.ARM_IDS:
        levels = [line for line in log if line["arm"] == arm and line["item_id"] == "SYN-G-001"]
        assert [line["unit"] for line in levels] == ["beginner", "intermediate", "advanced"]
        assert len({json.dumps(line["evidence"]) for line in levels}) == 1
    assert all(line["evidence"] == [] for line in log if line["arm"] == "NR")
    assert all(line["evidence"] for line in log if line["arm"] == "GATE" and line["item_id"].startswith("SYN-A-"))


# ===================================================================================================== AC-10-4


def test_ac_10_4_the_repository_and_the_evaluation_outputs_hold_zero_synthetic_fingerprint_matches(tmp_path, monkeypatch):
    # The whole tracked tree is scanned once, by CI's --repo step (guarded by
    # test_contamination_scan.py::test_ci_scans_the_whole_tracked_tree_once_with_the_env_templates_and_require_zero); here
    # the repository target runs over the Phase 10 records and the fixture through the same script.
    scan = script("scan_research_logs")
    records = sorted(name for name in contamination.git_files(REPO_ROOT)
                     if name.startswith(("docs/evaluation/phase10/", "evaluation/", "lqs/")))
    assert "evaluation/fixtures/contamination_synthetic_v1.json" in records and len(records) > 40
    monkeypatch.setattr(contamination, "git_files", lambda root: records)
    report = tmp_path / "scan.json"
    assert scan.main(["--synthetic-fixture", str(synthetic.CONTAMINATION_FIXTURE), "--repo", "--path", "docs/evaluation/phase10",
                      "--require-zero", "--report", str(report)]) == 0
    result = json.loads(report.read_text(encoding="utf-8"))
    repository = result["targets"][0]
    assert result["result"] == "pass" and repository["target"] == "repository" and repository["scanned"] == len(records) - 1
    assert repository["excluded"] == [{"path": "evaluation/fixtures/contamination_synthetic_v1.json", "reason": "synthetic contamination fixture"}]
    plan = runner.plan_run(stub_spec(tmp_path))
    runner.execute_run(plan, providers.StubResponder(), tmp_path / "run")
    assert scan.main(["--synthetic-fixture", str(synthetic.CONTAMINATION_FIXTURE), "--research-logs", str(tmp_path / "run"), "--require-zero"]) == 0


def test_ac_10_4_the_scanner_finds_a_licensed_passage_and_a_short_ulqs_text_placed_outside_the_research_plane(tmp_path, capsys):
    texts = fixture_texts()
    (tmp_path / "report.md").write_text(f"Leaked: {texts['licensed_passages'][0]}\n", encoding="utf-8")
    (tmp_path / "ci.log").write_text("x", encoding="utf-8")
    (tmp_path / "notes.json").write_text(json.dumps({"q": texts["ulqs_texts"][1]}), encoding="utf-8")
    report = tmp_path / "scan.json"
    assert script("scan_research_logs").main(["--synthetic-fixture", str(synthetic.CONTAMINATION_FIXTURE), "--path", str(tmp_path),
                                               "--report", str(report)]) == 1
    hits = {hit["path"]: hit for hit in json.loads(report.read_text(encoding="utf-8"))["targets"][0]["files_with_hits"]}
    assert hits["report.md"]["licensed_hits"] >= 1 and hits["notes.json"]["ulqs_hits"] >= 1
    output = capsys.readouterr().out + report.read_text(encoding="utf-8")
    assert texts["licensed_passages"][0] not in output and texts["ulqs_texts"][1] not in output


def test_ac_10_4_research_plane_scripts_refuse_public_output_paths(tmp_path):
    items_path, catalog_path, items = synthetic.write_fixture_set(tmp_path, synthetic.SMALL)
    access = tmp_path / "access.jsonl"
    rc1 = synthetic.write_jsonl(tmp_path / "rc1.jsonl", _rc1(items))
    licensed = tmp_path / "licensed.txt"
    licensed.write_text(fixture_texts()["licensed_passages"][0], encoding="utf-8")
    salt = tmp_path / "salt.txt"
    salt.write_text("ab" * 32, encoding="utf-8")
    ratings = synthetic.write_jsonl(tmp_path / "r.private.jsonl", synthetic.synthetic_ratings(items, rubric_sha256=RUBRIC_SHA))
    for public in ("docs/evaluation/phase10/out.json", "evaluation/reports/out.json"):
        target = REPO_ROOT / public
        assert script("migrate_ulqs_rc1").main(["--input", str(rc1), "--output", str(target), "--author-role", "PI", "--access-log", str(access)]) == 2
        assert script("build_licensed_fingerprints").main([
            "--licensed-text", str(licensed), "--ulqs", str(items_path), "--set-id", "t", "--output-licensed", str(target),
            "--output-ulqs", str(tmp_path / "u.json"), "--salt-file", str(salt), "--access-log", str(access), "--actor-role", "MLE"]) == 2
        assert script("validate_ulqs").main(["--items", str(items_path), "--catalog", str(catalog_path), "--ratings", str(ratings),
                                             "--rubric", str(REPO_ROOT / "lqs" / "rubric.md"), "--agreement-out", str(target)]) == 2
        assert not target.exists()
        with pytest.raises(planes.PathRefused):
            planes.require_private_output(target)
    spec = write_spec(tmp_path, synthetic.spec_dict(items_path=items_path, catalog_path=catalog_path))
    inside = REPO_ROOT / "docs" / "evaluation" / "phase10" / "run-out"
    assert run_main(["--spec", spec, "--output-dir", inside]) == 2 and not inside.exists()
    assert planes.require_private_output(REPO_ROOT / "lqs" / "private" / "x") == REPO_ROOT / "lqs" / "private" / "x"
    assert not (REPO_ROOT / "lqs" / "private" / "x").exists()
    with pytest.raises(planes.PathRefused, match="git does not ignore"):
        planes.require_private_output(REPO_ROOT / "docs" / "x-unignored.txt", boundary=_globs_with("docs/x-unignored.txt"))


def _link_into(link, target):
    """A directory link to `target`: a symlink, or on Windows without the symlink privilege a junction."""
    try:
        os.symlink(target, link, target_is_directory=True)
    except OSError:
        import _winapi

        _winapi.CreateJunction(str(target), str(link))


def test_ac_10_4_a_checkout_path_in_another_spelling_is_still_refused(tmp_path):
    link = tmp_path / "alias"
    _link_into(link, REPO_ROOT / "docs")
    try:
        through_link = link / "evaluation" / "x.json"
        assert planes.checkout_relative(through_link) == "docs/evaluation/x.json" and planes.inside_checkout(through_link)
        with pytest.raises(planes.PathRefused, match="not a private-plane path"):
            planes.require_private_output(through_link)
        if os.name == "nt":
            extended = "\\\\?\\" + str(REPO_ROOT / "docs" / "x.json")
            assert planes.checkout_relative(extended) == "docs/x.json"
            with pytest.raises(planes.PathRefused):
                planes.require_private_output(extended)
        # A spelling every platform has (CI runs on Linux): a dotted detour back into the checkout.
        dotted = REPO_ROOT / "evaluation" / ".." / "docs" / "x.json"
        assert planes.checkout_relative(dotted) == "docs/x.json"
        with pytest.raises(planes.PathRefused):
            planes.require_private_output(dotted)
        assert planes.require_private_output(tmp_path / "private" / "x.json") == tmp_path / "private" / "x.json"
        assert planes.checkout_relative(tmp_path / "private") is None and planes.checkout_relative(REPO_ROOT) == "."
    finally:
        os.unlink(link) if link.is_symlink() else os.rmdir(link)
    assert not (REPO_ROOT / "docs" / "evaluation" / "x.json").exists() and not (REPO_ROOT / "docs" / "x.json").exists()


def test_ac_10_4_file_identity_alone_maps_an_alias_of_the_checkout_on_every_platform(tmp_path, monkeypatch):
    # The third reading (os.path.samefile on the ancestors) on its own: with the realpath reading disabled, a link into the
    # checkout (a symlink, or a junction on Windows) is mapped only by file identity, which CI's Linux runner exercises too.
    link = tmp_path / "alias"
    _link_into(link, REPO_ROOT)
    monkeypatch.setattr(planes, "_realpath", lambda path: path)
    try:
        assert planes.checkout_relative(link / "docs" / "x.json") == "docs/x.json"
        assert planes.checkout_relative(link) == "." and planes.inside_checkout(link / "lqs" / "absent" / "y.json")
        with pytest.raises(planes.PathRefused, match="not a private-plane path"):
            planes.require_private_output(link / "docs" / "x.json")
        assert planes.checkout_relative(tmp_path / "elsewhere" / "x.json") is None
    finally:
        os.unlink(link) if link.is_symlink() else os.rmdir(link)
    assert not (REPO_ROOT / "docs" / "x.json").exists()


def _posix_path_calls(monkeypatch):
    """Path calls as on POSIX, on every platform: `os.path.realpath` (and so `Path.resolve`) raises ValueError for a path
    holding a NUL, where Windows maps it silently (the review 7 CI failure on ubuntu-latest)."""
    realpath = os.path.realpath

    def posix_realpath(path, *args, **kwargs):
        if "\x00" in os.fspath(path):
            raise ValueError("lstat: embedded null character in path")
        return realpath(path, *args, **kwargs)

    monkeypatch.setattr(os.path, "realpath", posix_realpath)


NUL_ARGUMENTS = {  # one path option of each research-plane script, given a NUL
    "validate_ulqs": ["--items", "a\x00b.jsonl"],
    "migrate_ulqs_rc1": ["--input", "a\x00b.jsonl", "--output", "out.jsonl", "--author-role", "PI", "--access-log", "a.jsonl"],
    "build_licensed_fingerprints": ["--licensed-text", "a\x00b.txt"],
    "scan_research_logs": ["--self-test", "--synthetic-fixture", "a\x00b.json"],
    "check_research_harness": ["--check", "--dir", "a\x00b"],
    "run_evaluation": ["--spec", "spec.json", "--output-dir", "a\x00b"],
}


@pytest.mark.parametrize("posix", [False, True], ids=["native", "posix"])
def test_ac_10_4_a_path_holding_a_nul_is_refused_on_every_platform(tmp_path, monkeypatch, capsys, posix):
    # A NUL is in no file system path; `os.path.realpath` raises ValueError for it on POSIX and maps it on Windows (open()
    # raises on both). Either way the
    # path rule refuses it as an input or an output (PathRefused), a governance record at such a path counts as public
    # (the gate refuses the run, exit 8), and each research-plane script refuses it as an argument (exit 2), never a
    # traceback.
    if posix:
        _posix_path_calls(monkeypatch)
    for path in ("a\x00b.json", REPO_ROOT / "lqs" / "private" / "a\x00b.json", tmp_path / "a\x00b.json"):
        for check in (planes.require_private_input, planes.require_private_output):
            with pytest.raises(planes.PathRefused, match="NUL"):
                check(path)
    spec = _confirmatory(tmp_path, "both valid")
    for path in ("lqs/private/a\x00b.json", str(tmp_path / "a\x00b.json")):
        spec["governance"]["irb_record"] = {"path": path, "sha256": "0" * 64}
        with pytest.raises(runner.RunRefused) as refused:
            runner.plan_run(spec)
        assert refused.value.code == 8 and "governance_record_public" in refused.value.reasons, path
    for name, argv in NUL_ARGUMENTS.items():
        capsys.readouterr()
        assert script(name).main(argv) == 2, name
        err = capsys.readouterr().err
        assert "NUL character" in err and "Traceback" not in err, (name, err)
        source = (REPO_ROOT / "scripts" / f"{name}.py").read_text(encoding="utf-8")
        assert "type=Path" not in source and "type=planes.cli_path" in source, name  # every path option is checked


def _globs_with(pattern):
    boundary = planes.boundary_policy()
    return dataclasses.replace(boundary, private_plane_globs=boundary.private_plane_globs + (pattern,))


def test_ac_10_4_the_fingerprint_builder_writes_format_1_that_scan_boundary_reads(tmp_path, monkeypatch, capsys):
    items_path, _catalog, _items = synthetic.write_fixture_set(tmp_path, synthetic.SMALL)
    licensed = tmp_path / "licensed.txt"
    licensed.write_text("\n".join(fixture_texts()["licensed_passages"]), encoding="utf-8")
    salt_hex = "5a" * 32
    monkeypatch.setenv("FINGERPRINT_SALT_FOR_TEST", salt_hex)
    out_l, out_u, access = tmp_path / "l.private.json", tmp_path / "u.private.json", tmp_path / "access.jsonl"
    argv = ["--licensed-text", str(licensed), "--ulqs", str(items_path), "--set-id", "syn-1", "--output-licensed", str(out_l),
            "--output-ulqs", str(out_u), "--salt-env", "FINGERPRINT_SALT_FOR_TEST", "--access-log", str(access)]
    builder = script("build_licensed_fingerprints")
    assert builder.main(argv) == 2 and not access.exists()  # the access log needs the actor's role
    argv += ["--actor-role", "DS"]
    assert builder.main(argv) == 0
    lines = read_jsonl(access)
    assert [(line["action"], line["artifact_kind"]) for line in lines] == [
        ("read", "licensed_text"), ("read", "ulqs_items"), ("write", "fingerprints"), ("write", "fingerprints")]
    assert {line["actor_role"] for line in lines} == {"DS"}
    assert lines[0]["artifact_sha256"] == __import__("hashlib").sha256(licensed.read_bytes()).hexdigest()
    loaded = script("scan_boundary").load_fingerprints(out_l)
    assert loaded["n"] == 12 and loaded["id"] == "syn-1" and loaded["set"]
    ulqs_set = contamination.load_fingerprint_file(out_u)
    assert ulqs_set.kind == "ulqs" and ulqs_set.n == 6 and ulqs_set.exact
    question = read_jsonl(items_path)[0]["question"]
    assert contamination.scan_text(question, [ulqs_set])["ulqs"] >= 1
    monkeypatch.setenv("FINGERPRINT_SALT_FOR_TEST", "5a" * 16)
    assert builder.main(argv) == 3
    captured = capsys.readouterr()
    assert salt_hex not in captured.out + captured.err and ("5a" * 16) not in captured.out + captured.err
    assert salt_hex not in access.read_text(encoding="utf-8")


def test_ac_10_4_no_tracked_file_holds_a_real_catalog_pointer_or_ulqs_item_record():
    listed = subprocess.run(["git", "ls-files", "-z"], cwd=REPO_ROOT, capture_output=True, check=True).stdout.decode("utf-8")
    pointer = re.compile(r"EV-(?:2025|2026|IND)-p[0-9]{3}-[0-9]{2}")
    record = re.compile(r"\"item_id\"\s*:\s*\"ULQS-[A-G]-[0-9]{3,}\"")
    offenders, scanned = [], 0
    for name in filter(None, listed.split("\0")):
        # Every text file, whatever its suffix, as the scanner reads them; environment files are CI's (0.1).
        if Path(name).suffix.lower() in contamination.BINARY_EXTENSIONS or contamination.is_env_file(name):
            continue
        try:
            text = contamination._text_of(name, (REPO_ROOT / name).read_bytes())
        except OSError:
            continue
        if text is None:
            continue
        scanned += 1
        if pointer.search(text) or record.search(text):
            offenders.append(name)
    assert offenders == [] and scanned > 700


# ===================================================================================================== AC-10-5


def _confirmatory(tmp_path, case):
    spec = stub_spec(tmp_path, purpose="confirmatory", experiment="E1", run_id="synthetic-confirmatory-v1")
    plan_sha = spec["analysis_plan"]["sha256"]
    irb = synthetic.irb_record(tmp_path / "irb.private.json")
    osf = synthetic.osf_record(tmp_path / "osf.private.json", analysis_plan_sha256=plan_sha)
    records = {
        "no records": (None, None),
        "IRB only": (irb, None),
        "OSF only": (None, osf),
        "a bad DOI": (irb, synthetic.osf_record(tmp_path / "doi.private.json", analysis_plan_sha256=plan_sha, doi="10.17605/OSF/XY")),
        "IRB approved after the run starts": (synthetic.irb_record(tmp_path / "late.private.json", approval_date="2026-12-01", expiry_date=None), osf),
        "an expired IRB": (synthetic.irb_record(tmp_path / "old.private.json", approval_date="2025-01-01", expiry_date="2026-06-30"), osf),
        "an OSF plan sha mismatch": (irb, synthetic.osf_record(tmp_path / "mm.private.json", analysis_plan_sha256="e" * 64)),
        "OSF registered after the run": (irb, synthetic.osf_record(tmp_path / "after.private.json", analysis_plan_sha256=plan_sha,
                                                                    registered_date="2026-11-30")),
        "both valid": (irb, osf),
    }[case]
    spec["governance"] = {"irb_record": records[0], "osf_record": records[1]}
    return spec


IRB_OSF_CASES = {"no records": {"irb_missing", "osf_missing"}, "IRB only": {"osf_missing"}, "OSF only": {"irb_missing"},
                 "a bad DOI": {"osf_invalid:doi"}, "IRB approved after the run starts": {"irb_not_yet_approved"},
                 "an expired IRB": {"irb_expired"}, "an OSF plan sha mismatch": {"osf_plan_mismatch"},
                 "OSF registered after the run": {"osf_registered_after_run"}}


@pytest.mark.parametrize("case", sorted(IRB_OSF_CASES))
def test_ac_10_5_without_an_irb_letter_or_an_osf_doi_the_runner_refuses_confirmatory_runs(tmp_path, case):
    spec = _confirmatory(tmp_path, case)
    with pytest.raises(runner.RunRefused) as refused:
        runner.plan_run(spec)
    assert refused.value.code == 8
    assert {r for r in refused.value.reasons if r.startswith(("irb_", "osf_"))} == IRB_OSF_CASES[case]
    out = tmp_path / "out"
    assert run_main(["--spec", write_spec(tmp_path, spec), "--output-dir", out]) == 8
    assert not out.exists()


def test_ac_10_5_with_both_records_valid_the_refusal_moves_to_the_next_condition(tmp_path):
    spec = _confirmatory(tmp_path, "both valid")
    with pytest.raises(runner.RunRefused) as refused:
        runner.plan_run(spec)
    reasons = refused.value.reasons
    assert not [r for r in reasons if r.startswith(("irb_", "osf_"))]
    assert reasons == ["D-14 open", "items_not_frozen", "freeze_record_missing", "pre_run_scan_missing", "stub_not_confirmatory",
                       "items_split_missing"]  # the items carry no calibration/confirmation split (plan 10.5(2))
    assert refused.value.code == 3


def test_ac_10_5_a_public_path_governance_record_is_refused(tmp_path):
    spec = _confirmatory(tmp_path, "both valid")
    public = REPO_ROOT / "docs" / "evaluation" / "phase10" / "README.md"
    spec["governance"]["irb_record"] = {"path": "docs/evaluation/phase10/README.md", "sha256": lf_sha256(public)}
    with pytest.raises(runner.RunRefused) as refused:
        runner.plan_run(spec)
    assert "governance_record_public" in refused.value.reasons and refused.value.code == 8


def test_ac_10_5_exploratory_runs_are_labelled_exploratory_in_every_output(tmp_path):
    spec = write_spec(tmp_path, stub_spec(tmp_path))
    out = tmp_path / "out"
    assert run_main(["--spec", spec, "--output-dir", out]) == 0
    record = json.loads((out / "run_record.json").read_text(encoding="utf-8"))
    assert record["purpose"] == "exploratory" and record["evidence_class"].startswith("exploratory run; not a confirmatory test")
    assert record["governance"] == {"confirmatory": False, "irb": "not supplied", "osf": "not supplied"}
    assert all(line["purpose"] == "exploratory" for line in read_jsonl(out / "payload_log.jsonl"))
    assert all(line["purpose"] == "exploratory" for line in read_jsonl(out / "run_events.jsonl"))


def test_ac_10_5_an_e1_to_e4_experiment_cannot_run_exploratory(tmp_path):
    for experiment in ("E1", "E2", "E3", "E4"):
        spec = stub_spec(tmp_path, experiment=experiment)
        with pytest.raises(runner.RunRefused) as refused:
            runner.plan_run(spec)
        assert refused.value.code == 2 and refused.value.reasons == ["experiment_requires_confirmatory"]
        assert run_main(["--spec", write_spec(tmp_path, spec), "--output-dir", tmp_path / experiment]) == 2


# ===================================================================================================== AC-10-6


def _sentinel_set(tmp_path):
    """Items and a catalog whose every free text carries one of 20 numbered sentinels."""
    sentinels = [f"{synthetic.SENTINEL} number {index:02d}" for index in range(20)]
    items = synthetic.synthetic_dataset(synthetic.SMALL)
    counter = iter(range(10 ** 6))

    def mark(text):
        return f"{text} {sentinels[next(counter) % 10]}"

    for item in items:
        item["question"] = mark(item["question"])
        item["topic"] = mark(item["topic"])
        for claim in item.get("atomic_claims", []):
            claim["text"] = mark(claim["text"])
        if "gold_answer" in item:
            item["gold_answer"] = mark(item["gold_answer"])
        for turn in item.get("conversation", []):
            turn["user_utterance"] = mark(turn["user_utterance"])
    lines = synthetic.synthetic_catalog(items)
    for index, line in enumerate(lines):
        text = f"{line['text']} {sentinels[10 + index % 10]}"
        line.update(text=text, char_end=len(text), byte_length=len(text.encode("utf-8")), content_sha256=content_sha256(text))
    items_path = synthetic.write_jsonl(tmp_path / "items.jsonl", items)
    catalog_path = synthetic.write_jsonl(tmp_path / "catalog.jsonl", lines)
    return sentinels, synthetic.spec_dict(items_path=items_path, catalog_path=catalog_path)


def test_ac_10_6_payload_logs_record_pointers_hashes_and_sizes_only(tmp_path):
    sentinels, spec = _sentinel_set(tmp_path)
    plan = runner.plan_run(spec)
    runner.execute_run(plan, providers.StubResponder(), tmp_path / "out")
    for name in ("payload_log.jsonl", "run_record.json", "run_events.jsonl"):
        data = (tmp_path / "out" / name).read_text(encoding="utf-8")
        for sentinel in sentinels:
            assert sentinel not in data and synthetic.SENTINEL not in data, (name, sentinel)
    log = read_jsonl(tmp_path / "out" / "payload_log.jsonl")
    assert log and all(set(line) == LOG_KEYS for line in log)
    evidence = [entry for line in log for entry in line["evidence"]]
    assert evidence and all(set(entry) == EVIDENCE_KEYS and isinstance(entry["bytes"], int) for entry in evidence)
    catalog = EvidenceCatalog.load(tmp_path / "catalog.jsonl")
    for entry in evidence:
        assert entry["content_sha256"] == catalog.get(entry["pointer"]).content_sha256
        assert entry["bytes"] == catalog.get(entry["pointer"]).byte_length


def _leaky(original, text):
    def log_record(*args, **kwargs):
        record = original(*args, **kwargs)
        record["prompt"] = text
        return record
    return log_record


def test_ac_10_6_a_logger_that_writes_text_is_caught_by_the_scanner(tmp_path, monkeypatch):
    passage = fixture_texts()["licensed_passages"][2]
    spec = write_spec(tmp_path, stub_spec(tmp_path))
    monkeypatch.setattr(runner, "log_record", _leaky(runner.log_record, passage))
    assert run_main(["--spec", spec, "--output-dir", tmp_path / "guarded"]) == 3
    assert not (tmp_path / "guarded" / "payload_log.jsonl").exists()
    monkeypatch.setattr(runner, "validate_log_record", lambda record: None)
    assert run_main(["--spec", spec, "--output-dir", tmp_path / "leaky"]) == 0
    report = tmp_path / "scan.json"
    assert script("scan_research_logs").main(["--synthetic-fixture", str(synthetic.CONTAMINATION_FIXTURE), "--research-logs",
                                               str(tmp_path / "leaky"), "--report", str(report)]) == 1
    hits = json.loads(report.read_text(encoding="utf-8"))["targets"][0]["files_with_hits"]
    assert [hit["path"] for hit in hits] == ["payload_log.jsonl"]


def test_ac_10_6_the_scanner_covers_every_research_plane_log_and_reports_zero(tmp_path):
    plan = runner.plan_run(stub_spec(tmp_path))
    run_dir = tmp_path / "run"
    runner.execute_run(plan, providers.StubResponder(), run_dir)
    sets = contamination.synthetic_sets(synthetic.CONTAMINATION_FIXTURE)
    target = contamination.research_logs_target(run_dir, sets, label="run")
    assert target["files"] == 4 and target["scanned"] == 3 and target["files_with_hits"] == []
    assert target["excluded"] == [{"path": "responses.jsonl", "reason": "research data (model outputs)"}]
    # A run record that names payload_log.jsonl as research data does not exclude it.
    passage = fixture_texts()["licensed_passages"][0]
    record = json.loads((run_dir / "run_record.json").read_text(encoding="utf-8"))
    record["research_data_files"] = ["payload_log.jsonl", "run_record.json"]
    (run_dir / "run_record.json").write_text(json.dumps(record), encoding="utf-8")
    with (run_dir / "payload_log.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"leaked": passage}) + "\n")
    target = contamination.research_logs_target(run_dir, sets, label="run")
    assert [hit["path"] for hit in target["files_with_hits"]] == ["payload_log.jsonl"]


# ===================================================================================================== plan rows


def test_plan_b_hold_h12_refuses_runs_on_non_synthetic_items(tmp_path):
    items = json.loads(json.dumps(synthetic.synthetic_dataset({"C": 2, "E": 1})).replace("SYN-", "ULQS-"))
    for item in items:
        item["license_class"] = "private_eval_full_span"
    assert ulqs.validate_dataset(items) == []
    items_path = synthetic.write_jsonl(tmp_path / "items.jsonl", items)
    spec = synthetic.spec_dict(items_path=items_path, catalog_path=None)
    for mode in ("stub", "recorded"):
        with pytest.raises(runner.RunRefused) as refused:
            runner.plan_run({**spec, "mode": mode})
        if mode == "stub":
            assert refused.value.code == 9 and refused.value.reasons == ["hold_h12_data_plane"]
    assert run_main(["--spec", write_spec(tmp_path, spec), "--output-dir", tmp_path / "out"]) == 9
    assert not (tmp_path / "out").exists()


def _non_synthetic_set(tmp_path):
    items = json.loads(json.dumps(synthetic.synthetic_dataset({"C": 2, "E": 1})).replace("SYN-", "ULQS-"))
    for item in items:
        item["license_class"] = "private_eval_full_span"
    return items, synthetic.write_jsonl(tmp_path / "items.jsonl", items)


def test_plan_b_after_d14_a_non_synthetic_run_needs_the_access_log_and_a_research_pre_run_scan(tmp_path):
    # D-14 decided only in a package copy (no committed package decides it): hold H12 then gives way to the pre-run scan,
    # which must be a passing research scan bound to these items, never CI's synthetic report or an empty one.
    items, items_path = _non_synthetic_set(tmp_path)
    spec = synthetic.spec_dict(items_path=items_path, catalog_path=None, package=synthetic.decided_package(tmp_path))
    access, out = tmp_path / "access.jsonl", tmp_path / "private-run"
    with pytest.raises(runner.RunRefused) as refused:
        runner.plan_run(spec, out_dir=out)
    assert refused.value.code == 2 and refused.value.reasons == ["access_log_required", "pre_run_scan_required"]
    content = ulqs.dataset_content_sha256(items)
    empty = synthetic.pass_scan(tmp_path / "empty.json", dataset_content_sha256=content, fingerprint_sets=[], targets=[])
    ci_like = synthetic.pass_scan(tmp_path / "ci.json", dataset_content_sha256=content, fingerprint_sets=[
        {"id": "synthetic-licensed-v1", "kind": "licensed", "dataset_content_sha256": None},
        {"id": "synthetic-ulqs-v1", "kind": "ulqs", "dataset_content_sha256": content}])
    other_items = synthetic.pass_scan(tmp_path / "other.json", dataset_content_sha256="f" * 64)
    for scan, reason in ((empty, "pre_run_scan_invalid:fingerprint_sets"), (ci_like, "pre_run_scan_invalid:fingerprint_sets"),
                         (other_items, "pre_run_scan_invalid:dataset")):
        with pytest.raises(runner.RunRefused) as refused:
            runner.plan_run({**spec, "pre_run_scan": scan}, out_dir=out, access_log=access)
        assert refused.value.code == 2 and reason in refused.value.reasons
    good = synthetic.pass_scan(tmp_path / "good.json", dataset_content_sha256=content)
    plan = runner.plan_run({**spec, "pre_run_scan": good}, out_dir=out, access_log=access)
    assert plan.synthetic is False and not out.exists()


def _access(path):
    return [(line["action"], line["artifact_kind"], line.get("outcome")) for line in read_jsonl(path)]


def test_plan_f_the_access_log_records_every_read_and_each_run_s_outcome(tmp_path, monkeypatch, capsys):
    spec_path = write_spec(tmp_path, stub_spec(tmp_path))
    access = tmp_path / "access.jsonl"
    assert run_main(["--spec", spec_path, "--output-dir", tmp_path / "x", "--access-log", access]) == 2 and not access.exists()
    reads = [("read", "run_spec", None), ("read", "ulqs_items", None), ("read", "evidence_catalog", None)]
    # An interrupted run (a provider outage after its inputs were read and requests sent) leaves its reads and outcome.
    run_evaluation = script("run_evaluation")
    monkeypatch.setattr(run_evaluation, "_responder", lambda plan: providers.ScriptedProvider(outage_at=5))
    out = tmp_path / "run"
    assert run_main(["--spec", spec_path, "--output-dir", out, "--access-log", access, "--actor-role", "MLE"]) == 5
    assert _access(access) == reads + [("run", "run_spec", "started"), ("run", "run_output", "interrupted")]
    assert read_jsonl(access)[-1]["artifact_sha256"] == lf_sha256(out / "responses.jsonl")
    # Resumed by the same responder (the stub would not match the checkpoint: checkpoint_mismatch). The run logs each
    # checkpoint file it reads (run_events.jsonl, responses.jsonl: the sha256 of the bytes read) before any check.
    checkpoint = [runner.checkpoint_sha256(out / name) for name in ("run_events.jsonl", "responses.jsonl")]
    monkeypatch.setattr(run_evaluation, "_responder", lambda plan: providers.ScriptedProvider())
    assert run_main(["--spec", spec_path, "--output-dir", out, "--resume", "--access-log", access, "--actor-role", "MLE"]) == 0
    assert _access(access)[5:] == reads + [("run", "run_spec", "started"), ("read", "run_output", None), ("read", "run_output", None),
                                           ("run", "run_output", "completed")]
    assert [line["artifact_sha256"] for line in read_jsonl(access)[9:11]] == checkpoint
    record = json.loads((out / "run_record.json").read_text(encoding="utf-8"))
    assert read_jsonl(access)[-1]["artifact_sha256"] == record["outputs"]["payload_log_sha256"]
    # A resume refused on its checkpoint (run events that are not UTF-8) logs the checkpoint read before the refusal,
    # and exits 2 (checkpoint_mismatch), never a traceback.
    access.unlink()
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "run_events.jsonl").write_bytes(b"\xff\xfe{}\n")
    capsys.readouterr()
    assert run_main(["--spec", spec_path, "--output-dir", broken, "--resume", "--access-log", access, "--actor-role", "MLE"]) == 2
    err = capsys.readouterr().err
    assert "Traceback" not in err and err.strip() == "refused (exit 2): checkpoint_mismatch"
    assert _access(access) == reads + [("run", "run_spec", "started"), ("read", "run_output", None), ("run", "run_spec", "refused")]
    assert read_jsonl(access)[4]["artifact_sha256"] == runner.checkpoint_sha256(broken / "run_events.jsonl")
    # A refused run (here an E1 run that is not confirmatory) logs the spec read and the refusal.
    access.unlink()
    refused = write_spec(tmp_path, stub_spec(tmp_path, experiment="E1"), "e1.json")
    assert run_main(["--spec", refused, "--output-dir", tmp_path / "e1", "--access-log", access, "--actor-role", "PI"]) == 2
    assert _access(access) == [("read", "run_spec", None), ("run", "run_spec", "refused")]
    lines = read_jsonl(access)
    assert {line["actor_role"] for line in lines} == {"PI"} and all(set(line) <= {
        "log", "at", "actor_role", "action", "artifact_kind", "artifact_sha256", "purpose", "run_id", "outcome"} for line in lines)
    # A run the planner refuses after reading its private items (hold H12, today every non-synthetic run) still logs the
    # items read, with the dataset sha256, before the refusal.
    access.unlink()
    items, items_path = _non_synthetic_set(tmp_path / "h12")
    h12 = write_spec(tmp_path, synthetic.spec_dict(items_path=items_path, catalog_path=None), "h12.json")
    assert run_main(["--spec", h12, "--output-dir", tmp_path / "h12-out", "--access-log", access, "--actor-role", "MLE"]) == 9
    assert _access(access) == [("read", "run_spec", None), ("read", "ulqs_items", None), ("run", "run_spec", "refused")]
    assert read_jsonl(access)[1]["artifact_sha256"] == ulqs.dataset_sha256(items)
    # A confirmatory run refused at its gate logs each governance record the gate read (the sha256 of the bytes read,
    # here a record whose pinned sha256 does not match), after the items and the catalog.
    access.unlink()
    irb, scan = tmp_path / "irb.json", tmp_path / "scan.json"
    irb.write_text("{}", encoding="utf-8")
    scan.write_text("{}", encoding="utf-8")
    confirmatory = write_spec(tmp_path, stub_spec(tmp_path / "conf", purpose="confirmatory", experiment="E1",
                                                  governance={"irb_record": {"path": str(irb), "sha256": "0" * 64}, "osf_record": None},
                                                  pre_run_scan={"path": str(scan), "sha256": lf_sha256(scan)}), "conf.json")
    assert run_main(["--spec", confirmatory, "--output-dir", tmp_path / "conf-out", "--access-log", access, "--actor-role", "PI"]) == 8
    assert _access(access) == reads + [("read", "irb_record", None), ("read", "scan_report", None), ("run", "run_spec", "refused")]
    assert [line["artifact_sha256"] for line in read_jsonl(access)[3:5]] == [lf_sha256(irb), lf_sha256(scan)]
    # A confirmatory --resume reads its checkpoint's run events when it is planned (the run window's start): that read is
    # logged before the gate's reads, and run events that are not UTF-8 are refused (run_start_invalid), never a traceback.
    access.unlink()
    (broken / "run_events.jsonl").write_bytes(b'{"event": "start", "started_on": "2026-11-20"}\n\xff\xfe\n')
    capsys.readouterr()
    assert run_main(["--spec", confirmatory, "--output-dir", broken, "--resume", "--access-log", access, "--actor-role", "PI"]) == 8
    err = capsys.readouterr().err
    assert "Traceback" not in err and err.startswith("refused (exit 8): run_start_invalid; ")
    assert _access(access) == reads + [("read", "run_output", None), ("read", "irb_record", None), ("read", "scan_report", None),
                                       ("run", "run_spec", "refused")]
    assert read_jsonl(access)[3]["artifact_sha256"] == runner.checkpoint_sha256(broken / "run_events.jsonl")


def test_plan_f_the_validator_logs_each_input_it_reads_and_each_record_it_writes(tmp_path):
    items_path, catalog_path, items = synthetic.write_fixture_set(tmp_path, synthetic.SMALL)
    ratings = synthetic.write_jsonl(tmp_path / "r.private.jsonl", synthetic.synthetic_ratings(items, rubric_sha256=RUBRIC_SHA))
    text = tmp_path / "text"
    text.mkdir()
    for document, body in synthetic.corpus_text(items).items():
        write_lf(text / f"{document}.txt", body)
    access = tmp_path / "access.jsonl"
    argv = ["--items", str(items_path), "--catalog", str(catalog_path), "--corpus-text", str(text), "--ratings", str(ratings), "--rubric",
            str(REPO_ROOT / "lqs" / "rubric.md"), "--agreement-out", str(tmp_path / "agreement.json"), "--access-log", str(access)]
    validate = script("validate_ulqs")
    assert validate.main(argv) == 2 and not access.exists()  # --access-log needs --actor-role
    assert validate.main(argv + ["--actor-role", "RL"]) == 0
    assert _access(access) == [("read", "ulqs_items", None), ("read", "evidence_catalog", None), ("read", "corpus_text", None),
                               ("read", "ratings", None), ("write", "agreement_record", None)]
    assert read_jsonl(access)[0]["artifact_sha256"] == ulqs.dataset_sha256(items)
    assert read_jsonl(access)[3]["artifact_sha256"] == lf_sha256(ratings)
    # A refusal after a read still leaves the read: an invalid catalog (exit 5), invalid ratings (exit 2) and items that do
    # not parse (exit 2) are each logged, by the file's LF sha256, before the refusal; the agent-check record is logged.
    base = ["--items", str(items_path), "--access-log", str(access), "--actor-role", "RL"]
    bad_catalog = tmp_path / "bad-catalog.jsonl"
    bad_catalog.write_text("{not json\n", encoding="utf-8")
    access.unlink()
    assert validate.main(base + ["--catalog", str(bad_catalog)]) == 5
    assert _access(access) == [("read", "ulqs_items", None), ("read", "evidence_catalog", None)]
    assert read_jsonl(access)[1]["artifact_sha256"] == lf_sha256(bad_catalog)
    bad_ratings = tmp_path / "bad-ratings.jsonl"
    bad_ratings.write_text("{not json\n", encoding="utf-8")
    access.unlink()
    assert validate.main(base + ["--ratings", str(bad_ratings), "--rubric", str(REPO_ROOT / "lqs" / "rubric.md"), "--agreement-out",
                                 str(tmp_path / "a2.json")]) == 2
    assert _access(access) == [("read", "ulqs_items", None), ("read", "ratings", None)]
    assert read_jsonl(access)[1]["artifact_sha256"] == lf_sha256(bad_ratings)
    access.unlink()
    assert validate.main(["--items", str(bad_ratings), "--access-log", str(access), "--actor-role", "RL"]) == 2
    assert _access(access) == [("read", "ulqs_items", None)] and read_jsonl(access)[0]["artifact_sha256"] == lf_sha256(bad_ratings)
    agent = tmp_path / "agent.private.json"
    write_lf(agent, json.dumps(synthetic.agent_check(items)) + "\n")
    access.unlink()
    assert validate.main(base + ["--agent-check", str(agent), "--catalog", str(catalog_path)]) == 0
    assert _access(access) == [("read", "ulqs_items", None), ("read", "agent_check_record", None), ("read", "evidence_catalog", None)]
    assert read_jsonl(access)[1]["artifact_sha256"] == lf_sha256(agent)


def test_plan_f_a_refused_migration_still_logs_the_rc1_read(tmp_path):
    migrate = script("migrate_ulqs_rc1")
    rc1 = _rc1(synthetic.synthetic_dataset(synthetic.SMALL))
    rc1[0]["status"] = "frozen"  # not an rc1 state: rc1 validation fails (exit 3) after the read
    source = synthetic.write_jsonl(tmp_path / "rc1.jsonl", rc1)
    output, access = tmp_path / "v1.jsonl", tmp_path / "access.jsonl"
    argv = ["--input", str(source), "--output", str(output), "--author-role", "PI", "--access-log", str(access)]
    assert migrate.main(argv) == 3 and not output.exists()
    assert _access(access) == [("read", "ulqs_items", None)]
    assert read_jsonl(access)[0]["artifact_sha256"] == ulqs.dataset_sha256(rc1)
    source.write_text("{not json\n", encoding="utf-8")
    access.unlink()
    assert migrate.main(argv) == 3
    assert _access(access) == [("read", "ulqs_items", None)] and read_jsonl(access)[0]["artifact_sha256"] == lf_sha256(source)
    assert {line["actor_role"] for line in read_jsonl(access)} == {"PI"}


def _imports(path):
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
            found |= {f"{node.module}.{alias.name}" for alias in node.names}
    return found


NEW_SCRIPTS = ("run_evaluation.py", "validate_ulqs.py", "migrate_ulqs_rc1.py", "build_licensed_fingerprints.py", "scan_research_logs.py",
               "check_research_harness.py")
FORBIDDEN_IMPORTS = ("socket", "http", "urllib.request", "requests", "httpx", "aiohttp", "google", "openai", "anthropic", "vertexai", "grpc",
                     "app.services.gateway", "app.gateway", "app.models", "app.core.db", "app.db", "app.db_models", "sqlalchemy")


def _harness_sources():
    return sorted((REPO_ROOT / "evaluation").rglob("*.py")) + [REPO_ROOT / "scripts" / name for name in NEW_SCRIPTS]


def test_plan_e_phase_10_adds_no_production_component():
    for path in (API_ROOT / "app").rglob("*.py"):
        assert not {name for name in _imports(path) if name == "evaluation" or name.startswith("evaluation.")}, path
    dockerfile = (API_ROOT / "Dockerfile").read_text(encoding="utf-8")
    copies = [line for line in dockerfile.splitlines() if line.strip().startswith("COPY")]
    assert copies and not [line for line in copies if re.search(r"\s(evaluation|lqs|scripts)(/|\s)", line)]
    assert not [path.name for path in (API_ROOT / "alembic" / "versions").glob("*.py") if "phase10" in path.name]
    offenders = []
    for path in _harness_sources():
        text = path.read_text(encoding="utf-8")
        if "DEFAULT_PACKAGE_PATH" in text or "get_config_package" in text:
            offenders.append(f"{path.name}: package by default path")
        for name in _imports(path):
            if any(name == bad or name.startswith(bad + ".") for bad in FORBIDDEN_IMPORTS):
                offenders.append(f"{path.relative_to(REPO_ROOT).as_posix()}: {name}")
    assert offenders == []


def test_plan_g_the_mapping_table_keeps_corpus_version_separate(tmp_path):
    mapping = json.loads((REPO_ROOT / "lqs" / "ulqs-rc1-to-v1.0-mapping.json").read_text(encoding="utf-8"))
    assert mapping["fields"]["corpus_version"] == "copy" and "R-19" in mapping["corpus_version"]
    # The text states what the code does: corpus_version is never in an id, is pinned on its own, and the dataset sha256
    # (which hashes whole items) covers it.
    assert "never part of an id" in mapping["corpus_version"] and "covered by the dataset sha256" in mapping["corpus_version"]
    assert "separate from the dataset sha256" not in json.dumps(mapping)
    plan = runner.plan_run(stub_spec(tmp_path))
    assert plan.pins["items"]["corpus_version"] == synthetic.CORPUS_VERSION
    assert plan.pins["evidence_catalog"]["corpus_version"] == synthetic.CORPUS_VERSION
    assert mapping["provisional"] is True and "auto-promotion past candidate" in mapping["never"]
    assert set(mapping["strata"]) == set(ulqs.STRATA) and mapping["states"] == {"draft": "draft", "candidate": "candidate"}
    assert "CORPUS" not in ulqs.ITEM_ID.pattern and "CORPUS" not in ulqs.EVIDENCE_ID.pattern
    items = synthetic.synthetic_dataset(synthetic.SMALL)
    changed = [{**item, "corpus_version": "QCAI-CORPUS-2027-01-01"} for item in items]
    assert ulqs.dataset_sha256(changed) != ulqs.dataset_sha256(items)
    assert [item["item_id"] for item in changed] == [item["item_id"] for item in items]


def _live_ready(tmp_path, monkeypatch):
    """A live spec with every condition met (in a temporary research plane), and a package with every decision decided."""
    plane = tmp_path / "plane"
    plane.mkdir()
    monkeypatch.setenv("RESEARCH_PLANE_ROOT", str(plane))
    monkeypatch.setattr(providers, "LIVE_ADAPTERS", {"fake-adapter": providers.ScriptedProvider})
    spec = {"created_at": synthetic.CREATED, "responder": {"live": {"adapter": "fake-adapter", "providers": ["SYN-PROVIDER-1"]}},
            "governance": {"irb_record": synthetic.irb_record(plane / "irb.json"), "osf_record": None},
            "provider_terms": synthetic.provider_terms_record(plane / "terms.json"),
            "licence_ruling": synthetic.licence_ruling_record(plane / "ruling.json"),
            "research_use_confirmation": synthetic.research_use_record(plane / "research-use.json"), "arms": {"selected": list(ablation.ARM_IDS)}}
    package = {"owner_decisions": {name: {"state": "decided"} for name in ("D-07", "D-08", "D-12", "D-14")},
               "semantic": {"enabled_by_default": True}}
    return spec, package, plane / "out"


def test_plan_h_spans_reach_no_model_until_the_four_conditions_hold(tmp_path, monkeypatch):
    spec, package, out = _live_ready(tmp_path, monkeypatch)
    table = ablation.load_arms()
    reasons = lambda s: providers.live_refusal_reasons(s, package, __import__("os").environ, table, out_dir=out)  # noqa: E731
    plane = out.parent
    assert reasons(spec) == []
    assert reasons({**spec, "licence_ruling": None}) == ["licence_ruling_unrecorded"]                      # (a) Q-07
    negative = synthetic.licence_ruling_record(plane / "negative.json", determination="negative")
    assert reasons({**spec, "licence_ruling": negative}) == ["licence_negative"]                           # plan L
    assert reasons({**spec, "provider_terms": None}) == ["provider_terms_unrecorded"]                      # (b) A-11
    assert reasons({**spec, "governance": {"irb_record": None}}) == ["irb_not_filed"]                       # (c) D-08
    assert reasons({**spec, "research_use_confirmation": None}) == ["research_use_unconfirmed"]             # (d)
    # Each condition is a record resolved by path and sha256 and read under its format, never a mere non-empty value.
    dangling = {"path": str(plane / "absent.json"), "sha256": "0" * 64}
    assert reasons({**spec, "provider_terms": {"record_sha256": "0" * 64}}) == ["provider_terms_invalid:reference"]
    assert reasons({**spec, "provider_terms": dangling}) == ["provider_terms_invalid:file"]
    assert reasons({**spec, "licence_ruling": {"determination": "permits", "record_sha256": "0" * 64}}) == ["licence_ruling_invalid:reference"]
    assert reasons({**spec, "licence_ruling": dict(spec["licence_ruling"], sha256="0" * 64)}) == ["licence_ruling_invalid:sha256"]
    assert reasons({**spec, "research_use_confirmation": dangling}) == ["research_use_invalid:file"]
    unrecorded = synthetic.provider_terms_record(plane / "partial.json", publication_recorded=False)
    assert reasons({**spec, "provider_terms": unrecorded}) == ["provider_terms_invalid:publication_recorded"]
    expired = synthetic.irb_record(plane / "old.json", approval_date="2025-01-01", expiry_date="2026-06-30")
    assert reasons({**spec, "governance": {"irb_record": expired}}) == ["irb_expired"]
    # The run window: the IRB is judged on the day the run is planned, never on the spec's created_at, so a spec dated
    # synthetic.CREATED planned in 2028 is refused by the IRB that expired in 2027, however it is dated; a future-dated
    # spec is refused; a window that starts earlier (a resume) needs every record dated by that start.
    lasting = synthetic.irb_record(plane / "lasting.json", approval_date="2026-11-01", expiry_date="2027-06-30")
    dated = {**spec, "governance": {"irb_record": lasting}}
    assert reasons(dated) == []
    monkeypatch.setattr(governance, "utc_today", lambda: datetime_module.date(2028, 1, 10))
    assert reasons(dated) == ["irb_expired"]
    assert reasons({**dated, "created_at": "2028-01-10T09:00:00Z"}) == ["irb_expired"]
    monkeypatch.setattr(governance, "utc_today", lambda: datetime_module.date.fromisoformat(synthetic.CREATED[:10]))
    assert reasons({**dated, "created_at": "2026-12-01T00:00:00Z"}) == ["created_at_in_future"]
    early = datetime_module.date(2026, 10, 31)
    assert providers.live_refusal_reasons(dated, package, __import__("os").environ, table, out_dir=out, start=early) == [
        "irb_not_yet_approved", "provider_terms_after_run", "licence_ruling_after_run", "research_use_after_run"]
    # Each record is bound to the run: (b) per provider the run queries, and no record dated after the run's start.
    live = lambda **changes: {**spec, "responder": {"live": {"adapter": "fake-adapter", **changes}}}  # noqa: E731
    assert reasons(live(providers=["SYN-PROVIDER-2"])) == ["provider_terms_missing:SYN-PROVIDER-2"]
    assert reasons(live(providers=["SYN-PROVIDER-1", "SYN-PROVIDER-2"])) == ["provider_terms_missing:SYN-PROVIDER-2"]
    assert reasons(live()) == ["live_providers_unnamed"]
    second = synthetic.provider_terms_record(plane / "terms-2.json", provider_id="SYN-PROVIDER-2")
    both = {**live(providers=["SYN-PROVIDER-1", "SYN-PROVIDER-2"]), "provider_terms": [spec["provider_terms"], second]}
    assert reasons(both) == []
    monkeypatch.setattr(providers.ScriptedProvider, "providers", ("SYN-PROVIDER-1", "SYN-PROVIDER-3"), raising=False)
    assert reasons(spec) == ["live_providers_mismatch", "provider_terms_missing:SYN-PROVIDER-3"]
    monkeypatch.delattr(providers.ScriptedProvider, "providers")
    late = {"recorded_date": "2026-12-01"}
    assert reasons({**spec, "provider_terms": synthetic.provider_terms_record(plane / "late-terms.json", **late)}) == ["provider_terms_after_run"]
    assert reasons({**spec, "licence_ruling": synthetic.licence_ruling_record(plane / "late-ruling.json", ruling_date="2026-12-01")}) == [
        "licence_ruling_after_run"]
    assert reasons({**spec, "research_use_confirmation": synthetic.research_use_record(plane / "late-use.json",
                                                                                     confirmed_date="2026-12-01")}) == ["research_use_after_run"]
    public = REPO_ROOT / "docs" / "evaluation" / "phase10" / "README.md"
    assert "governance_record_public" in reasons({**spec, "provider_terms": {"path": "docs/evaluation/phase10/README.md",
                                                                             "sha256": lf_sha256(public)}})
    assert providers.live_refusal_reasons(spec, package, {}, table, out_dir=out) == ["research_plane_absent"]
    assert providers.live_refusal_reasons(spec, package, {"RESEARCH_PLANE_ROOT": str(REPO_ROOT / "lqs" / "private")}, table,
                                          out_dir=REPO_ROOT / "lqs" / "private" / "out") == ["research_plane_absent"]


def test_plan_i_harness_slis_report_completion_failures_and_cost_per_arm(tmp_path):
    spec = write_spec(tmp_path, _recorded_spec(tmp_path))
    assert run_main(["--spec", spec, "--output-dir", tmp_path / "out"]) == 0
    slis = json.loads((tmp_path / "out" / "run_record.json").read_text(encoding="utf-8"))["slis"]
    responses = read_jsonl(tmp_path / "out" / "responses.jsonl")
    assert slis["planned_requests"] == len(responses) and slis["completed_requests"] == len(responses) - 1
    assert slis["completion_rate"] == (len(responses) - 1) / len(responses)
    assert slis["provider_failures"] == {"server_error": 1} and slis["attempts"] == sum(len(r["attempts"]) for r in responses)
    assert set(slis["cost_units"]) == set(ablation.ARM_IDS) and all(value > 0 for value in slis["cost_units"].values())
    assert "not USD" in slis["cost_unit"]


def test_plan_j_each_seeded_fault_type_is_detected_and_no_clean_control_is_flagged():
    assert script("check_research_harness").main(["--check"]) == 0
    report = seeded_faults.reference_report()
    assert report["all_known_answers_met"] and report["false_alarm_cases"] == [] and report["clean_controls"] == 6
    for finding in seeded_faults.FINDING_TYPES:
        row = report["per_type"][finding]
        assert row["seeded"] == row["detected"] == 3 and row["misattributed"] == [], finding


def test_plan_j_a_provider_outage_resumes_to_the_same_bytes(tmp_path):
    plan = runner.plan_run(stub_spec(tmp_path))
    runner.execute_run(plan, providers.ScriptedProvider(), tmp_path / "reference")
    out = tmp_path / "out"
    with pytest.raises(runner.RunInterrupted):
        runner.execute_run(plan, providers.ScriptedProvider(outage_at=len(plan.requests) // 2), out)
    events = read_jsonl(out / "run_events.jsonl")
    assert events[-1]["event"] == "interrupted" and 0 < events[-1]["completed_requests"] < len(plan.requests)
    with pytest.raises(runner.RunInterrupted):
        runner.execute_run(plan, providers.ScriptedProvider(outage_at=3), out, resume=True)
    runner.execute_run(plan, providers.ScriptedProvider(), out, resume=True)
    assert _outputs(out) == _outputs(tmp_path / "reference")
    assert [event["event"] for event in read_jsonl(out / "run_events.jsonl")] == ["start", "interrupted", "resumed", "interrupted",
                                                                                   "resumed", "completed"]


def _live_stub(tmp_path, monkeypatch):
    live_spec, _package, out = _live_ready(tmp_path, monkeypatch)
    stub = stub_spec(tmp_path, package=synthetic.decided_package(tmp_path))
    live = {**stub, **{key: live_spec[key] for key in ("governance", "provider_terms", "licence_ruling", "research_use_confirmation")},
            "mode": "live", "responder": {"live": {"adapter": "fake-adapter", "providers": ["SYN-PROVIDER-1"]}}}
    return live, out


def test_plan_j_a_live_run_interrupted_by_an_outage_resumes_on_a_later_utc_day_with_the_same_spec(tmp_path, monkeypatch, capsys):
    # Plan J "provider outage resumes": a live run interrupted (exit 5) is resumed on a later UTC day with the same spec.
    # Its run window starts on the day its checkpoint's start event records, so the records must be dated by then, and
    # the IRB must be unexpired on the resume day.
    live, out = _live_stub(tmp_path, monkeypatch)
    day = datetime_module.date.fromisoformat(synthetic.CREATED[:10])
    plan = runner.plan_run(live, out_dir=out)
    assert plan.dated and plan.planned_on == day and plan.checkpoint_start is None
    runner.execute_run(plan, providers.ScriptedProvider(), tmp_path / "reference")
    with pytest.raises(runner.RunInterrupted):
        runner.execute_run(plan, providers.ScriptedProvider(outage_at=len(plan.requests) // 2), out)
    assert read_jsonl(out / "run_events.jsonl")[0]["started_on"] == day.isoformat()
    next_day = day + datetime_module.timedelta(days=1)
    monkeypatch.setattr(governance, "utc_today", lambda: next_day)
    # run_evaluation.py --resume plans the run as a resume: its only refusal is then that no live adapter is wired here.
    spec_path = write_spec(tmp_path, live, "live.json")
    capsys.readouterr()
    assert run_main(["--spec", spec_path, "--output-dir", out, "--resume"]) == 9
    assert capsys.readouterr().err.strip() == "refused (exit 9): no_live_adapter"
    resumed = runner.plan_run(live, out_dir=out, resume=True)
    assert resumed.checkpoint_start == day and resumed.planned_on == next_day
    runner.execute_run(resumed, providers.ScriptedProvider(), out, resume=True)
    assert _outputs(out) == _outputs(tmp_path / "reference")
    assert [event["event"] for event in read_jsonl(out / "run_events.jsonl")] == ["start", "interrupted", "resumed", "completed"]
    # The plan was judged on this checkpoint: it does not run into an output without it, nor a fresh plan into this one.
    fresh = out.parent / "fresh"
    with pytest.raises(runner.RunRefused) as refused:
        runner.execute_run(resumed, providers.ScriptedProvider(), fresh, resume=True)
    assert refused.value.code == 2 and refused.value.reasons == ["checkpoint_mismatch"] and not fresh.exists()
    with pytest.raises(runner.RunRefused) as refused:
        runner.execute_run(runner.plan_run(live, out_dir=fresh), providers.ScriptedProvider(), out, resume=True)
    assert refused.value.reasons == ["checkpoint_mismatch"]
    # A record dated after the checkpoint's start day refuses the resume, though a fresh start that day would pass it.
    late = synthetic.licence_ruling_record(out.parent / "late-ruling.json", ruling_date=next_day.isoformat())
    assert runner.plan_run({**live, "licence_ruling": late}, out_dir=fresh).checkpoint_start is None
    with pytest.raises(runner.RunRefused) as refused:
        runner.plan_run({**live, "licence_ruling": late}, out_dir=out, resume=True)
    assert refused.value.code == 9 and refused.value.reasons == ["licence_ruling_after_run"]
    # The IRB (expiring 2027-11-01) must still be valid on the day the resumed run queries providers.
    monkeypatch.setattr(governance, "utc_today", lambda: datetime_module.date(2027, 12, 1))
    with pytest.raises(runner.RunRefused) as refused:
        runner.plan_run(live, out_dir=out, resume=True)
    assert refused.value.code == 9 and refused.value.reasons == ["irb_expired"]


def test_plan_j_a_checkpoint_s_start_day_can_only_tighten_the_run_window(tmp_path, monkeypatch):
    # A dated run's start event records the UTC day the run was planned (`started_on`). --resume into an output without
    # run events is a fresh start judged on today; with events, the first must be a `start` with an ISO started_on not
    # after today (`run_start_invalid`) and this run's digest (`checkpoint_mismatch`). Whoever writes the output can write
    # a start event (DI-143), but the window starts at the earliest day, so a hand-written one never passes a run that a
    # fresh start today would refuse: an expired IRB refuses it whatever day it states, and an earlier day makes a record
    # dated after it refuse.
    live, out = _live_stub(tmp_path, monkeypatch)
    today = datetime_module.date.fromisoformat(synthetic.CREATED[:10])
    same_day = out.parent / "same-day"
    record = runner.execute_run(runner.plan_run(live, out_dir=same_day, resume=True), providers.ScriptedProvider(), same_day, resume=True)
    events = read_jsonl(same_day / "run_events.jsonl")
    assert record["slis"]["completed_requests"] == record["slis"]["planned_requests"]
    assert [event["event"] for event in events] == ["start", "completed"] and events[0]["started_on"] == today.isoformat()
    exploratory = runner.plan_run(stub_spec(tmp_path))
    runner.execute_run(exploratory, providers.ScriptedProvider(), out.parent / "exploratory")
    assert "started_on" not in read_jsonl(out.parent / "exploratory" / "run_events.jsonl")[0]  # stub outputs stay date-free

    def forged(spec, name, **event):
        directory = out.parent / name
        directory.mkdir(parents=True)
        digest = runner.run_digest(runner.plan_run(spec, out_dir=directory), providers.ScriptedProvider.rule)
        (directory / "run_events.jsonl").write_text(json.dumps({"event": "start", "run_digest": digest, **event}) + "\n", encoding="utf-8")
        return directory

    future = (today + datetime_module.timedelta(days=30)).isoformat()
    for name, event in (("no-day", {}), ("future-day", {"started_on": future}), ("timestamp", {"started_on": synthetic.CREATED}),
                        ("resumed-first", {"event": "resumed", "started_on": today.isoformat()})):
        with pytest.raises(runner.RunRefused) as refused:
            runner.plan_run(live, out_dir=forged(live, name, **event), resume=True)
        assert refused.value.code == 9 and refused.value.reasons == ["run_start_invalid"], name
    # A future-dated spec is refused at once, a checkpoint or not.
    with pytest.raises(runner.RunRefused) as refused:
        runner.plan_run({**live, "created_at": f"{future}T00:00:00Z"}, out_dir=out.parent / "none", resume=True)
    assert refused.value.reasons == ["created_at_in_future"]
    # A start event with another run's digest is refused before anything is touched.
    other = forged({**live, "run_id": "another-run"}, "other-digest", started_on=today.isoformat())
    with pytest.raises(runner.RunRefused) as refused:
        runner.execute_run(runner.plan_run(live, out_dir=other, resume=True), providers.ScriptedProvider(), other, resume=True)
    assert refused.value.reasons == ["checkpoint_mismatch"]
    # Monotone: a forged earlier start day turns records dated today into refusals; it never turns a refusal into a pass.
    past = (today - datetime_module.timedelta(days=10)).isoformat()
    ruled_today = {**live, "licence_ruling": synthetic.licence_ruling_record(out.parent / "today-ruling.json", ruling_date=today.isoformat())}
    assert runner.plan_run(ruled_today, out_dir=out.parent / "fresh-today").checkpoint_start is None
    with pytest.raises(runner.RunRefused) as refused:
        runner.plan_run(ruled_today, out_dir=forged(ruled_today, "backdated", started_on=past), resume=True)
    assert refused.value.reasons == ["licence_ruling_after_run"]
    later = {name: forged(live, name, started_on=start) for name, start in (("old-day", past), ("late-day", "2028-01-10"))}
    monkeypatch.setattr(governance, "utc_today", lambda: datetime_module.date(2028, 1, 10))
    for name, directory in later.items():
        with pytest.raises(runner.RunRefused) as refused:
            runner.plan_run(live, out_dir=directory, resume=True)
        assert refused.value.reasons == ["irb_expired"], name
    with pytest.raises(runner.RunRefused) as refused:
        runner.plan_run(live, out_dir=out.parent / "fresh-2028")
    assert refused.value.reasons == ["irb_expired"]


def test_ac_10_5_a_confirmatory_recorded_run_starts_its_window_on_the_recording_s_live_start(tmp_path, monkeypatch):
    # A confirmatory replay's data began to flow when its live run started: the runner moves the window's start to the
    # recording header's started_on (never later than today) and hands the gate (start, today); a missing or future day
    # is refused (test_governance_records covers recording_start_refusals). A resumed replay starts at the earliest day.
    lines = read_jsonl(synthetic.RECORDED_FIXTURE)
    lines[0] = {**lines[0], "source": "live", "started_on": "2026-11-20"}
    recording = tmp_path / "recording.jsonl"
    write_lf(recording, "".join(dumps_line(line) for line in lines))
    spec = _recorded_spec(tmp_path, purpose="confirmatory", experiment="E1")
    spec["responder"] = {"recorded": {"path": str(recording), "sha256": lf_sha256(recording)}}
    seen = {}
    monkeypatch.setattr(governance, "confirmatory_refusals", lambda spec, **kwargs: seen.update(kwargs) or ["stop"])
    monkeypatch.setattr(governance, "utc_today", lambda: datetime_module.date(2028, 1, 10))
    monkeypatch.setattr(ulqs, "SPLITS", (*ulqs.SPLITS, None))  # the fixture items carry no split
    with pytest.raises(runner.RunRefused) as refused:
        runner.plan_run(spec, resume=True)
    assert refused.value.reasons == ["stop"]
    assert seen["recording_source"] == "live" and seen["start"] == datetime_module.date(2026, 11, 20)
    assert seen["today"] == datetime_module.date(2028, 1, 10)
    # A resumed replay (--resume with its output directory) starts at the earliest of today, its checkpoint's start
    # event's started_on and the recording's started_on; a checkpoint whose first event is not a start with a valid day,
    # or whose run events are not UTF-8, adds run_start_invalid (exit 2 here, the gate's other reason being "stop").
    for checkpoint_day, start in (("2026-11-15", datetime_module.date(2026, 11, 15)), ("2027-03-01", datetime_module.date(2026, 11, 20))):
        out = tmp_path / f"resume-{checkpoint_day}"
        out.mkdir()
        write_lf(out / "run_events.jsonl", dumps_line({"event": "start", "started_on": checkpoint_day}))
        with pytest.raises(runner.RunRefused) as refused:
            runner.plan_run(spec, resume=True, out_dir=out)
        assert refused.value.reasons == ["stop"] and seen["start"] == start, checkpoint_day
    for name, content in (("no-day", b'{"event": "start"}\n'), ("resumed-first", b'{"event": "resumed", "started_on": "2026-11-15"}\n'),
                          ("not-utf8", b"\xff\xfe\n")):
        out = tmp_path / f"resume-{name}"
        out.mkdir()
        (out / "run_events.jsonl").write_bytes(content)
        with pytest.raises(runner.RunRefused) as refused:
            runner.plan_run(spec, resume=True, out_dir=out)
        assert refused.value.code == 2 and refused.value.reasons == ["run_start_invalid", "stop"], name
        assert seen["start"] == datetime_module.date(2026, 11, 20), name
    for started_on, reason in ((None, "recording_started_on_missing"), ("2028-01-11", "recording_after_run")):
        lines[0] = {**lines[0], "started_on": started_on}
        write_lf(recording, "".join(dumps_line(line) for line in lines))
        refused_spec = {**spec, "responder": {"recorded": {"path": str(recording), "sha256": lf_sha256(recording)}}}
        with pytest.raises(runner.RunRefused) as refused:
            runner.plan_run(refused_spec)
        assert refused.value.code == 2 and refused.value.reasons == [reason, "stop"] and seen["start"] == datetime_module.date(2028, 1, 10)
    # Planned past the gate, a confirmatory replay is a dated plan.
    monkeypatch.setattr(governance, "confirmatory_refusals", lambda spec, **kwargs: [])
    lines[0] = {**lines[0], "started_on": "2026-11-20"}
    write_lf(recording, "".join(dumps_line(line) for line in lines))
    plan = runner.plan_run(spec)
    assert plan.dated and plan.planned_on == datetime_module.date(2028, 1, 10) and plan.checkpoint_start is None


def test_ac_10_5_a_confirmatory_run_covers_every_item_and_replicates_the_full_subsample(tmp_path, monkeypatch):
    # Paper Sec. VIII E1 "All ULQS items run through all seven arms" and the registered data "all ULQS items x seven
    # arms": a confirmatory run covers both splits (the calibration split is for thresholds, plan L470), every stratum
    # at its count, and gives the paper's three replicates to all 40 items of the S1 subsample its record pins; a
    # subsample stratum with fewer live items than the size is refused, and items without a split are refused (exit 3).
    # The gate's own records are covered by the AC-10-5 tests; here it is passed so that the runner's part is seen.
    monkeypatch.setattr(governance, "confirmatory_refusals", lambda spec, **kwargs: [])
    items_path, catalog_path, items = synthetic.write_fixture_set(tmp_path, synthetic.PAPER_TARGETS, splits=True)
    spec = synthetic.spec_dict(items_path=items_path, catalog_path=catalog_path, purpose="confirmatory", experiment="E1",
                               run_id="synthetic-confirmatory-split-v1")
    del spec["replicates"]  # the paper's default (harness_parameters_v1.json): three replicates on a 40-item S1 subsample
    plan = runner.plan_run(spec)
    assert {request.item_id for request in plan.requests} == {item["item_id"] for item in items}
    by_stratum = Counter(item["stratum"] for item in items if item["item_id"] in {request.item_id for request in plan.requests})
    assert dict(by_stratum) == synthetic.PAPER_TARGETS
    assert plan.pins["replicates"]["subsample"] == {"stratum": "A", "size": 40, "replicates": 3, "rule": "sha256-order-v1"}
    replicated = {request.item_id for request in plan.requests if request.replicate == 3}
    assert replicated == set(runner.subsample(items, plan.pins["replicates"])) and len(replicated) == 40
    assert {item["split"] for item in items if item["item_id"] in replicated} == {"calibration", "confirmation"}
    exploratory = runner.plan_run({**spec, "purpose": "exploratory", "experiment": "harness-check"})
    assert {request.request_key for request in exploratory.requests} == {request.request_key for request in plan.requests}
    assert plan.dated and plan.checkpoint_start is None
    (tmp_path / "short").mkdir()
    short_path, short_catalog, _short = synthetic.write_fixture_set(tmp_path / "short", _with(synthetic.PAPER_TARGETS, A=39), splits=True)
    short = synthetic.spec_dict(items_path=short_path, catalog_path=short_catalog, purpose="confirmatory", experiment="E1",
                                run_id="synthetic-confirmatory-split-v1")
    del short["replicates"]
    with pytest.raises(runner.RunRefused) as refused:
        runner.plan_run(short)
    assert refused.value.code == 2 and refused.value.reasons == ["replicate_subsample_short"]
    assert len(runner.plan_run({**short, "purpose": "exploratory", "experiment": "harness-check"}).requests) > 0
    (tmp_path / "unsplit").mkdir()
    unsplit_path, unsplit_catalog, _unsplit = synthetic.write_fixture_set(tmp_path / "unsplit", synthetic.PAPER_TARGETS)
    unsplit = synthetic.spec_dict(items_path=unsplit_path, catalog_path=unsplit_catalog, purpose="confirmatory", experiment="E1",
                                  run_id="synthetic-confirmatory-split-v1")
    with pytest.raises(runner.RunRefused) as refused:
        runner.plan_run(unsplit)
    assert refused.value.code == 3 and refused.value.reasons == ["items_split_missing"]


def test_plan_l_each_stop_condition_refuses(tmp_path, monkeypatch):
    # Contamination: the scanner exits 1 on a match, and a confirmatory run needs a passing pre-run scan.
    (tmp_path / "leak").mkdir()
    (tmp_path / "leak" / "log.txt").write_text(fixture_texts()["licensed_passages"][1], encoding="utf-8")
    assert script("scan_research_logs").main(["--synthetic-fixture", str(synthetic.CONTAMINATION_FIXTURE), "--path", str(tmp_path / "leak")]) == 1
    spec = _confirmatory(tmp_path, "both valid")
    with pytest.raises(runner.RunRefused) as refused:
        runner.plan_run(spec)
    assert "pre_run_scan_missing" in refused.value.reasons
    # Negative licence determination.
    spec_live, package, out = _live_ready(tmp_path, monkeypatch)
    negative = {**spec_live, "licence_ruling": synthetic.licence_ruling_record(out.parent / "negative.json", determination="negative")}
    assert providers.live_refusal_reasons(negative, package, __import__("os").environ, ablation.load_arms(), out_dir=out) == ["licence_negative"]
    # Low agreement: a freeze record that failed (alpha below the floor) refuses a confirmatory run.
    items = read_jsonl(Path(spec["items"]["path"]))
    failed = synthetic.freeze_record(tmp_path / "freeze.private.json", dataset_sha256=ulqs.dataset_sha256(items), passed=False)
    with pytest.raises(runner.RunRefused) as refused:
        runner.plan_run({**spec, "freeze_record": failed})
    assert "freeze_record_failed" in refused.value.reasons
    # No IRB: confirmatory and live both refuse.
    with pytest.raises(runner.RunRefused) as refused:
        runner.plan_run(_confirmatory(tmp_path, "OSF only"))
    assert "irb_missing" in refused.value.reasons
    assert providers.live_refusal_reasons({**spec_live, "governance": {}}, package, __import__("os").environ, ablation.load_arms(),
                                          out_dir=out) == ["irb_not_filed"]
    # Unresolved pointers stop a run (exit 3).
    broken = stub_spec(tmp_path)
    catalog = read_jsonl(Path(broken["evidence_catalog"]["path"]))[1:]
    catalog_path = synthetic.write_jsonl(tmp_path / "short-catalog.jsonl", catalog)
    broken["evidence_catalog"] = {"path": str(catalog_path), "sha256": EvidenceCatalog.load(catalog_path).sha256}
    with pytest.raises(runner.RunRefused) as refused:
        runner.plan_run(broken)
    assert refused.value.code == 3 and refused.value.reasons[0] == "unresolved_pointers"


def _keys(value):
    if isinstance(value, dict):
        return set(value) | set().union(*(_keys(v) for v in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(_keys(v) for v in value)) if value else set()
    return set()


def test_plan_p_no_hr_1_to_mr_3_outcome_is_asserted():
    plans = analysis_plans.load_plans()
    for key in ("met", "supported", "result", "p_value"):
        changed = json.loads(json.dumps(plans))
        changed["families"]["E1"][key] = True
        with pytest.raises(analysis_plans.PlanError):
            analysis_plans.validate_plans(changed)
    record = json.loads(SYNTHETIC_RECORD.read_text(encoding="utf-8"))
    assert not _keys(record) & {"met", "supported", "achieved", "passed_criteria"}
    assert "no Table XVII row or HR-1..MR-3 outcome is asserted" in record["evidence_class"]
    for name, status in plans["tests"].items():
        assert status != "implemented" or callable(getattr(__import__("evaluation.qcai_eval.statistics", fromlist=["x"]), name))
    for path in (RECORDS / "README.md", RECORDS / "preregistration-draft.md", REPO_ROOT / "docs" / "evaluation" / "protocol.md"):
        assert "not executed" in path.read_text(encoding="utf-8").lower(), path.name


# ===================================================================================================== docs


def spec_text():
    return SPEC_PATH.read_text(encoding="utf-8")


def test_phase10_docs_section_9_records_the_collected_test_counts():
    # Spec 9 states the size of the two Phase 10 test sets (current-state text, P2-12-D-03): it must be what pytest collects.
    def collected(target):
        result = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", target], cwd=REPO_ROOT,
                                capture_output=True, text=True, timeout=300)
        match = re.search(r"^(\d+) tests? collected", result.stdout, flags=re.MULTILINE)
        assert match, result.stdout[-2000:] + result.stderr[-2000:]
        return int(match.group(1))

    evaluation, acceptance = collected("evaluation/tests"), collected("apps/api/tests/test_phase10_acceptance.py")
    section = " ".join(spec_text().split("\n## 9. CI changes", 1)[1].split("\n## 10.", 1)[0].split())
    assert re.search(rf"`evaluation/tests` about \d+ s \(one job; {evaluation} tests\)", section), evaluation
    assert re.search(rf"`test_phase10_acceptance.py` about \d+ s \({acceptance} tests\)", section), acceptance


def test_phase10_docs_quote_the_plan_and_state_the_current_rules():
    spec = " ".join(spec_text().split())
    for quote in ("AC-10-1 to AC-10-6 passed; OSF DOI and IRB letter filed; no HR-1 to MR-3 outcome asserted.",
                  "Stop: contamination, negative licence determination, low agreement, no IRB.",
                  "[Risk R-10][Risk R-25][Risk R-43][Risk R-45]. Residual: pre-training contamination, reported as limitation.",
                  "H12 | Data plane [Decision D-14] | P10 runs; private spans"):
        assert quote in spec, quote
    adr = " ".join((REPO_ROOT / "docs" / "adr" / "ADR-012-evaluation-and-research-harness.md").read_text(encoding="utf-8").split())
    assert "[Risk R-10][Risk R-25][Risk R-43][Risk R-45]. Residual: pre-training contamination, reported as limitation." in adr
    assert "Stop: contamination, negative licence determination, low agreement, no IRB." in adr
    adr7 = (REPO_ROOT / "docs" / "adr" / "ADR-007-evaluation-harness.md").read_text(encoding="utf-8")
    assert "## Revision 2026-11-24 (Phase 10)" in adr7 and "GATE+SV" in adr7
    # The README's exit codes say what each script's docstring says.
    readme = " ".join((RECORDS / "README.md").read_text(encoding="utf-8").split())
    harness_doc = " ".join(script("check_research_harness").__doc__.split())
    assert "3 a known answer not met or an invalid analysis plan" in harness_doc
    assert ("`check_research_harness.py`: 0; 1 drift (a record that differs, or is missing or unreadable); 2 usage (an unknown "
            "option, `--check` with `--write`, or a path argument holding a NUL) or a `--dir` the records cannot be written to "
            "(`--write`); 3 a known answer not met or an invalid analysis plan; 6 a pin; 7 parity.") in readme
    assert "a path argument holding a NUL" in harness_doc and "a --dir the records cannot be written to" in harness_doc
    # run_evaluation.py's exit 2 names every checkpoint refusal and the unwritable output, in each exit-code statement.
    run_doc = script("run_evaluation").__doc__.split("Exit codes:", 1)[1]
    readme_run = readme.split("- `run_evaluation.py`:", 1)[1].split("- `validate_ulqs.py`:", 1)[0]
    spec_run = next(line for line in spec_text().split("\n## 5. Scripts", 1)[1].splitlines() if line.startswith("| `scripts/run_evaluation.py`"))
    for name, text in (("docstring", run_doc), ("README", readme_run), ("spec 5", spec_run)):
        for reason in ("checkpoint_mismatch", "checkpoint_invalid", "partial_checkpoint", "output_exists", "output_unwritable"):
            assert f"`{reason}`" in text, (name, reason)
        assert "foreign checkpoint" not in text and "or another run's checkpoint refused" not in text, name
    # Spec 4.12 states the current signatures of plan_run and execute_run.
    for function in (runner.plan_run, runner.execute_run):
        parameters = list(inspect.signature(function).parameters)
        positional = [name for name in parameters if inspect.signature(function).parameters[name].kind is not inspect.Parameter.KEYWORD_ONLY]
        keywords = [name for name in parameters if name not in positional]
        assert f"`{function.__name__}({', '.join(positional + [name + '=' for name in keywords])})`" in spec, function.__name__
    assert "when a dated resume is planned, the checkpoint's `run_events.jsonl` (`run_output`" in spec
    protocol =(REPO_ROOT / "docs" / "evaluation" / "protocol.md").read_text(encoding="utf-8")
    for arm in ablation.ARM_IDS:
        assert f"`{arm}`" in protocol, arm
    # GATE is Table XV's "deployed configuration" of the paper's design, never a claim about current production.
    flat = " ".join(protocol.split())
    assert "calls it \"the deployed configuration\" of the paper's design; it is not the current production configuration" in flat
    assert "`GATE` (the deployed configuration)" not in flat
    head = spec_text().split("\n## 14. Review history\n", 1)[0]
    for number in range(60, 75):
        assert f"| PD-{number} |" in head
    for number in range(129, 144):
        assert f"| DI-{number} |" in head
    assert "The exit is not passed (DI-129)." in head


PHASE10_MODULES = ("test_phase10_acceptance.py", "conftest.py", "test_ulqs_schema.py", "test_ulqs_pointers.py", "test_rater_agreement.py",
                   "test_ablation_arms.py", "test_evaluation_runner.py", "test_research_statistics.py", "test_analysis_plans.py",
                   "test_seeded_fault_fixtures.py", "test_contamination_scan.py", "test_payload_log.py", "test_governance_records.py",
                   "test_evaluators.py", "test_phase9_acceptance.py", "test_python_sources.py", "scan_guard.py")


def test_phase10_docs_the_test_strategy_maps_every_test_module_the_phase_added():
    strategy = (REPO_ROOT / "docs" / "testing" / "test-strategy.md").read_text(encoding="utf-8")
    section = strategy.split("## Phase 10 acceptance map (plan Phase 10 K)", 1)[1]
    exit_gate = next(line for line in section.splitlines() if line.startswith("**Exit gate.** The Phase 10 exit"))
    assert exit_gate.endswith("The exit is not passed.")
    # Every module this phase added or changed, and every module of evaluation/tests (a new one must join the map).
    # Each heads its own row of the "Phase 10 test files" or "Phase 10 changes to existing test modules" table, with a
    # statement of what it proves (a mention elsewhere in the section is not enough).
    rows = {cells[1].strip().strip("`").split("/")[-1]: cells[2].strip() for cells in
            (line.split("|") for line in section.split("### Phase 10 test files", 1)[1].splitlines() if line.startswith("| `"))}
    for name in (*PHASE10_MODULES, *(path.name for path in (REPO_ROOT / "evaluation" / "tests").glob("*.py"))):
        assert len(rows.get(name, "")) > 40, name
    for ac in range(1, 7):
        assert f"| AC-10-{ac} |" in section, ac
    names = set()
    for root in (API_ROOT / "tests", REPO_ROOT / "evaluation" / "tests"):
        for path in root.glob("test_*.py"):
            names |= set(re.findall(r"^def (test_\w+)\(", path.read_text(encoding="utf-8"), flags=re.MULTILINE))
    for name in re.findall(r"`(test_[a-z0-9_]+)`", section):
        assert name in names, name
    api = {path.name for path in (API_ROOT / "tests").glob("test_*.py")}
    evaluation = {path.name for path in (REPO_ROOT / "evaluation" / "tests").glob("test_*.py")}
    assert api & evaluation == set()  # pytest's prepend import mode needs unique test basenames across both roots


def test_phase10_docs_the_spec_ends_in_one_review_history_table():
    spec = spec_text()
    head, history = spec.split("\n## 14. Review history\n", 1)
    assert "\n## 15." not in history and history.count("| Round | Commit |") == 1
    assert re.findall(r"^## (\d+)\.", head, flags=re.MULTILINE) == [str(n) for n in range(0, 14)]
    assert SPEC_PATH.read_bytes().count(b"\r\n") == 0
    names = set()
    for root in (API_ROOT / "tests", REPO_ROOT / "evaluation" / "tests"):
        for path in root.glob("test_*.py"):
            names |= set(re.findall(r"^def (test_\w+)\(", path.read_text(encoding="utf-8"), flags=re.MULTILINE))
    for name in re.findall(r"`(test_[a-z0-9_]+)`", spec):
        assert name in names or name.endswith("_"), name


def test_phase10_docs_spec_section_9_is_the_current_ci_block():
    # Spec 9 states the CI changes: its YAML block is the Phase 10 block of ci.yml as it is, comments included.
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8").replace("\r\n", "\n")
    block = ci[ci.index("      # Phase 10 (evaluation and research harness)"):ci.index("      # Phase 2 (corpus, span identity, retrieval integrity).")]
    section = spec_text().split("\n## 9. CI changes", 1)[1].split("\n## 10.", 1)[0]
    assert section.split("```yaml\n", 1)[1].split("```\n", 1)[0] == block


def test_phase10_docs_the_preregistration_is_a_draft_with_holm_alpha_0_05():
    text = (RECORDS / "preregistration-draft.md").read_text(encoding="utf-8")
    assert "**DRAFT - not filed with OSF (DI-131).**" in text and "alpha = 0.05, Holm correction within each family" in text
    assert text == analysis_plans.preregistration_markdown(analysis_plans.load_plans()).replace("\r\n", "\n") or \
        text.replace("\r\n", "\n") == analysis_plans.preregistration_markdown(analysis_plans.load_plans())
    assert (RECORDS / "preregistration-draft.md").read_bytes().count(b"\r\n") == 0


def _provisional_markers(path):
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "PROVISIONAL_DEFAULTS" for t in node.targets):
            return set(ast.literal_eval(node.value))
    return set()


def test_phase10_docs_every_provisional_default_is_marked_where_it_lives():
    # Spec 12.1: each PD row's "Where" column names its files; a data file carries "provisional": true and a code module a
    # PROVISIONAL_DEFAULTS tuple naming the row. No row names only prose.
    section = spec_text().split("### 12.1 Provisional defaults", 1)[1].split("### 12.2", 1)[0]
    rows = re.findall(r"^\| (PD-\d+) \|.*\| ([^|]+) \|$", section, flags=re.MULTILINE)
    assert [key for key, _where in rows] == [f"PD-{n}" for n in range(60, 75)]
    modules = {path.name: path for path in [*Path(ulqs.__file__).resolve().parent.glob("*.py"),
                                            *[REPO_ROOT / "scripts" / name for name in NEW_SCRIPTS]]}
    for key, where in rows:
        names = re.findall(r"`([^`]+)`", where)
        assert names and len(names) == where.count(";") + 1, (key, where)
        for name in names:
            if name.endswith(".json"):
                assert json.loads((REPO_ROOT / name).read_text(encoding="utf-8"))["provisional"] is True, (key, name)
            else:
                assert name.endswith(".py") and key in _provisional_markers(modules[name]), (key, name)
    harness = json.loads(runner.HARNESS_PARAMETERS.read_text(encoding="utf-8"))
    assert harness["replicates"]["subsample"] == {"stratum": "A", "size": 40, "replicates": 3, "rule": "sha256-order-v1"}
    assert harness["retries"] == 3 and "PD-68" in harness["authority"]
    pinned = json.loads((RECORDS / "pinned_configuration_v1.json").read_text(encoding="utf-8"))
    assert pinned["harness_files"]["evaluation/config/harness_parameters_v1.json"] == canonical_sha256(harness)


def test_phase10_no_new_source_literal_starts_with_qcai_():
    prefix = "qcai" + "_"
    sources = [*sorted(Path(ulqs.__file__).resolve().parent.glob("*.py")), *sorted((REPO_ROOT / "evaluation" / "tests").glob("*.py")),
               *[REPO_ROOT / "scripts" / name for name in NEW_SCRIPTS], Path(__file__)]
    offenders = []
    for path in sources:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.startswith(prefix):
                offenders.append(f"{path.name}:{node.lineno}")
            if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Name)) and getattr(node, "name", getattr(node, "id", "")).startswith(prefix):
                offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == []


# ===================================================================================================== exit-code contract
# One table for the six research-plane scripts (spec 5). The codes each script can return are derived from its source
# (`_returnable_codes`) and must equal the table's; the script's docstring, the README and spec 5 must name exactly the
# table's codes, and each of the four Phase 10 CI comments only those; a scenario reaches each code. A code a script can
# return but no document names, or a documented code no scenario reaches, fails here.


def _literal_codes(tree, refusals):
    """The exit codes a module states literally: an int returned (alone, in an `and`/`or`, either arm of a conditional,
    or first in a returned tuple), an int assigned to `code`, and the first argument of a call to one of `refusals`."""
    def ints(node):
        if isinstance(node, ast.Constant) and type(node.value) is int:
            return {node.value}
        if isinstance(node, ast.BoolOp):
            return set().union(*(ints(value) for value in node.values))
        if isinstance(node, ast.IfExp):
            return ints(node.body) | ints(node.orelse)
        if isinstance(node, ast.Tuple) and node.elts:
            return ints(node.elts[0])
        return set()

    codes = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Return) and node.value is not None:
            codes |= ints(node.value)
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "code" for target in node.targets):
            codes |= ints(node.value)
        if isinstance(node, ast.Call) and node.args:
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
            if name in refusals:
                codes |= ints(node.args[0])
    return codes


def _returnable_codes(name):
    """The codes a script can exit with: those its source states, and for run_evaluation.py also every literal
    `RunRefused` code of the harness modules and each class `governance.confirmatory_exit_code` returns."""
    codes = _literal_codes(ast.parse((REPO_ROOT / "scripts" / name).read_text(encoding="utf-8")), {"Refused", "RunRefused"})
    if name == "run_evaluation.py":
        for module in sorted(Path(runner.__file__).parent.glob("*.py")):
            codes |= _literal_codes(ast.parse(module.read_text(encoding="utf-8")), {"RunRefused"})
        codes |= {governance.confirmatory_exit_code([prefix]) for _code, prefixes in governance.CONFIRMATORY_EXIT_CLASSES
                  for prefix in prefixes} | {governance.confirmatory_exit_code(["other"])}
    return codes


def _ci_exit_codes(comment):
    """The codes a CI comment lists: each `N` after "exit ", ", ", "; " or "(" and before a space or a comma."""
    return {int(code) for code in re.findall(r"(?:exit |, |; |\()(\d)(?=[ ,])", " ".join(comment.split()))}


def _exit_codes(text):
    """The codes an exit-code statement lists: each `N` that opens it or follows "; " ("0 ok; 1 drift; 2 usage ...")."""
    return {int(code) for code in re.findall(r"(?:^|; )(\d)(?=[ ;])", " ".join(text.split()) + " ")}


def _documented_exit_codes():
    readme = (RECORDS / "README.md").read_text(encoding="utf-8").split("## Exit codes", 1)[1].split("\n## ", 1)[0]
    bullets = {match[0]: match[1] for match in re.findall(r"^- `([a-z0-9_]+\.py)`: (.*?)(?=^- `|\Z)", readme, flags=re.MULTILINE | re.DOTALL)}
    section = spec_text().split("\n## 5. Scripts", 1)[1].split("\n## 6.", 1)[0]
    rows = {}
    for line in section.splitlines():
        cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", line)]
        if len(cells) == 5 and cells[1].startswith("`scripts/"):
            rows[cells[1].split("`")[1].split("/")[1]] = cells[3]
    documents = {}
    for name in NEW_SCRIPTS:
        doc = script(name[:-3]).__doc__
        documents[name] = {"docstring": _exit_codes(doc.split("Exit codes:", 1)[1]), "README": _exit_codes(bullets[name]),
                           "spec 5": _exit_codes(rows[name])}
    return documents


def _scenario_run_evaluation(tmp_path, monkeypatch, code):
    spec = stub_spec(tmp_path)
    if code == 1:
        changed = tmp_path / "record.json"
        write_lf(changed, SYNTHETIC_RECORD.read_text(encoding="utf-8").replace('"format_version": 1', '"format_version": 2', 1))
        return ["--check", changed, "--spec", SYNTHETIC_SPEC]
    if code == 2:
        return ["--spec", write_spec(tmp_path, spec)]
    if code == 3:
        write_lf(Path(spec["items"]["path"]), dumps_line({"item_id": "SYN-A-001"}))
    if code == 5:
        monkeypatch.setattr(script("run_evaluation"), "_responder", lambda plan: providers.ScriptedProvider(outage_at=1))
    if code == 6:
        spec["package"] = {**spec["package"], "sha256": "0" * 64}
    if code == 7:
        monkeypatch.setattr(runner, "_manifest_hook", lambda manifests: {**manifests, "SEM": {**manifests["SEM"], "top_k": 9}})
    if code == 8:
        spec = _confirmatory(tmp_path, "OSF only")
    if code == 9:
        spec = {**spec, "mode": "live", "responder": {"live": {"adapter": None}}}
    return ["--spec", write_spec(tmp_path, spec, "contract.json"), "--output-dir", tmp_path / "out"]


def _scenario_validate_ulqs(tmp_path, monkeypatch, code):
    items, catalog = synthetic.ITEMS_FIXTURE, synthetic.CATALOG_FIXTURE
    if code == 2:
        return ["--items", tmp_path / "absent.jsonl"]
    if code == 3:
        broken = read_jsonl(items)
        del broken[0]["topic"]
        return ["--items", synthetic.write_jsonl(tmp_path / "bad.jsonl", broken)]
    if code == 4:
        argv, _frozen, _agent = _research_plane_freeze(tmp_path)
        rules = Path(argv[argv.index("--rules") + 1])
        raw = json.loads(rules.read_text(encoding="utf-8"))
        raw["agent_check"]["pinned_models"] = []  # agent_model_not_pinned: the freeze fails
        write_lf(rules, json.dumps(raw) + "\n")
        return argv
    if code == 5:
        return ["--items", items, "--catalog", synthetic.write_jsonl(tmp_path / "short.jsonl", read_jsonl(catalog)[1:])]
    return ["--items", items, "--catalog", catalog]


def _scenario_migrate_ulqs_rc1(tmp_path, monkeypatch, code):
    source = synthetic.write_jsonl(tmp_path / "rc1.jsonl", _rc1(synthetic.synthetic_dataset(synthetic.SMALL)))
    if code == 3:
        source = tmp_path / "rc1-bad.jsonl"
        write_lf(source, "not json\n")
    output = REPO_ROOT / "docs" / "evaluation" / "contract-rc1.jsonl" if code == 2 else tmp_path / "v1.jsonl"
    return ["--input", source, "--output", output, "--author-role", "RL", "--access-log", tmp_path / "access.jsonl"]


def _scenario_build_licensed_fingerprints(tmp_path, monkeypatch, code):
    items_path, _catalog, _items = synthetic.write_fixture_set(tmp_path, synthetic.SMALL)
    if code == 4:
        items_path = synthetic.write_jsonl(tmp_path / "bad.jsonl", [{"item_id": "SYN-A-001"}])
    licensed = tmp_path / "licensed.txt"
    licensed.write_text(fixture_texts()["licensed_passages"][0], encoding="utf-8")
    monkeypatch.setenv("FINGERPRINT_SALT_FOR_TEST", "5a" * (16 if code == 3 else 32))
    argv = ["--licensed-text", licensed, "--ulqs", items_path, "--set-id", "syn-1", "--output-licensed", tmp_path / "l.private.json",
            "--output-ulqs", tmp_path / "u.private.json", "--salt-env", "FINGERPRINT_SALT_FOR_TEST", "--access-log", tmp_path / "access.jsonl"]
    return argv if code == 2 else argv + ["--actor-role", "DS"]


def _scenario_scan_research_logs(tmp_path, monkeypatch, code):
    target = tmp_path / "logs"
    target.mkdir()
    (target / "log.txt").write_text(fixture_texts()["licensed_passages"][0] if code == 1 else "an invented clean log line\n", encoding="utf-8")
    argv = ["--synthetic-fixture", synthetic.CONTAMINATION_FIXTURE, "--path", target, "--require-zero"]
    return argv + ["--ulqs-fingerprints", tmp_path / "u.json"] if code == 2 else argv


def _scenario_check_research_harness(tmp_path, monkeypatch, code):
    copy = tmp_path / "records"
    copy.mkdir()
    for name in script("check_research_harness").RECORDS:
        (copy / name).write_bytes((RECORDS / name).read_bytes())
    if code == 1:
        (copy / "seeded_faults_report_v1.json").write_text("{}\n", encoding="utf-8")
    if code == 3:
        monkeypatch.setattr(seeded_faults, "reference_report", lambda: {"all_known_answers_met": False})
    if code == 6:
        harness = script("check_research_harness")
        monkeypatch.setattr(harness, "canonical_sha256", lambda value: "0" * 64)
    if code == 7:
        def broken():
            raise ablation.ParityError("GATE: declared_mismatch")
        monkeypatch.setattr(ablation, "load_arms", broken)
    if code == 2:
        return ["--check", "--write", "--dir", copy]
    return ["--check", "--dir", copy]


EXIT_CONTRACT = {
    "run_evaluation.py": (_scenario_run_evaluation, (0, 1, 2, 3, 5, 6, 7, 8, 9)),
    "validate_ulqs.py": (_scenario_validate_ulqs, (0, 2, 3, 4, 5)),
    "migrate_ulqs_rc1.py": (_scenario_migrate_ulqs_rc1, (0, 2, 3)),
    "build_licensed_fingerprints.py": (_scenario_build_licensed_fingerprints, (0, 2, 3, 4)),
    "scan_research_logs.py": (_scenario_scan_research_logs, (0, 1, 2)),
    "check_research_harness.py": (_scenario_check_research_harness, (0, 1, 2, 3, 6, 7)),
}


def test_phase10_exit_codes_every_document_names_the_codes_the_contract_reaches():
    documented = _documented_exit_codes()
    assert set(documented) == set(EXIT_CONTRACT) == set(NEW_SCRIPTS)
    for name, (_scenario, codes) in EXIT_CONTRACT.items():
        assert _returnable_codes(name) == set(codes), (name, sorted(_returnable_codes(name)))
        for document, listed in documented[name].items():
            assert listed == set(codes), (name, document, sorted(listed))
    # Each of the four Phase 10 CI comments names only codes its script documents (a subset: a comment names the codes
    # its step can meet), and at least one.
    assert _ci_exit_codes("needs (4, a failed freeze, 2 usage); exit 1 drift, 6 a pin") == {1, 2, 4, 6}
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    comments = {"validate_ulqs.py": "validate_ulqs: exit ", "check_research_harness.py": "check_research_harness: exit ",
                "run_evaluation.py": "# AC-10-3: ", "scan_research_logs.py": "# AC-10-4 (synthetic half): "}
    for name, prefix in comments.items():
        comment = ci.split(prefix, 1)[1].split("- run:", 1)[0].replace("#", " ")
        listed = _ci_exit_codes(prefix + comment if prefix.endswith("exit ") else comment)
        assert listed and listed <= set(EXIT_CONTRACT[name][1]), (name, sorted(listed))


@pytest.mark.parametrize(("name", "code"), [(name, code) for name, (_s, codes) in EXIT_CONTRACT.items() for code in codes])
def test_phase10_exit_codes_each_documented_code_is_reached(tmp_path, monkeypatch, capsys, name, code):
    scenario, _codes = EXIT_CONTRACT[name]
    argv = scenario(tmp_path, monkeypatch, code)
    assert script(name[:-3]).main([str(value) for value in argv]) == code, capsys.readouterr().err
    assert "Traceback" not in capsys.readouterr().err
    assert not (REPO_ROOT / "docs" / "evaluation" / "contract-rc1.jsonl").exists()


# Every output option of each script (a file option given a directory, a directory option given an existing file or a
# path under one) and every access log. An exception a script does not catch exits 1, which the literal-code reading
# of `_returnable_codes` cannot see and which means drift or a match: each `main` refuses an unwritable output or
# access log (`planes.UNWRITABLE`) with exit 2 instead, and a run logs its refused outcome.
UNWRITABLE_OUTPUTS = {
    "run_evaluation.py": ("--output-dir", "--access-log", "--write", "--record-stub"),
    "validate_ulqs.py": ("--agreement-out", "--freeze-out", "--access-log"),
    "migrate_ulqs_rc1.py": ("--output", "--access-log"),
    "build_licensed_fingerprints.py": ("--output-licensed", "--output-ulqs", "--access-log"),
    "scan_research_logs.py": ("--report", "--access-log"),
    "check_research_harness.py": ("--dir",),
}


def _unwritable_argv(tmp_path, monkeypatch, name, option):
    scenario, _codes = EXIT_CONTRACT[name]
    if name == "run_evaluation.py" and option in ("--write", "--record-stub"):
        argv = ["--spec", SYNTHETIC_SPEC, option, None]
    elif name == "run_evaluation.py":
        argv = scenario(tmp_path, monkeypatch, 0) + ["--access-log", tmp_path / "access.jsonl", "--actor-role", "MLE"]
    elif name == "validate_ulqs.py":
        argv = _research_plane_freeze(tmp_path)[0]
    elif name == "scan_research_logs.py":
        argv = scenario(tmp_path, monkeypatch, 0) + ["--report", tmp_path / "scan.json", "--access-log", tmp_path / "access.jsonl",
                                                     "--actor-role", "MLE"]
    elif name == "check_research_harness.py":
        argv = ["--write", "--dir", None]
    else:
        argv = scenario(tmp_path, monkeypatch, 0)
    argv = [str(value) if value is not None else None for value in argv]
    afile = tmp_path / "afile"
    afile.write_text("an existing file\n", encoding="utf-8")
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    bad = {"--output-dir": afile, "--dir": afile / "sub"}.get(option, blocked)
    argv[argv.index(option) + 1] = str(bad)
    return argv, blocked


@pytest.mark.parametrize(("name", "option"), [(name, option) for name, options in UNWRITABLE_OUTPUTS.items() for option in options])
def test_phase10_exit_codes_an_unwritable_output_or_access_log_is_refused_with_exit_2(tmp_path, monkeypatch, capsys, name, option):
    argv, blocked = _unwritable_argv(tmp_path, monkeypatch, name, option)
    capsys.readouterr()
    assert script(name[:-3]).main(argv) == 2, capsys.readouterr().err
    err = capsys.readouterr().err
    assert "refused (exit 2)" in err and ("cannot be written" in err or "output_unwritable" in err), err
    assert "Traceback" not in err and not any(blocked.iterdir())
    if name == "run_evaluation.py" and option == "--output-dir":  # the run's outcome is logged
        assert _access(tmp_path / "access.jsonl")[-2:] == [("run", "run_spec", "started"), ("run", "run_spec", "refused")]
    if name == "run_evaluation.py" and option == "--access-log":
        assert not (tmp_path / "out").exists()  # nothing ran: the spec read could not be logged
    # Each script's `main` is the guard: it returns 2 for `planes.UNWRITABLE`.
    tree = ast.parse((REPO_ROOT / "scripts" / name).read_text(encoding="utf-8"))
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
    handlers = [handler for node in ast.walk(main) if isinstance(node, ast.Try) for handler in node.handlers]
    assert any(ast.unparse(handler.type) == "planes.UNWRITABLE" and _literal_codes(handler, set()) == {2} for handler in handlers)


# Terms of a superseded design that no authoritative document or source may state as current (P2-12-D-03): the run
# window replaced the rule that a run's created_at be today and the start check of a resume (spec 3.13); a dated run's
# start event carries started_on, so only the byte-compared outputs are free of the wall clock (spec 3.9). Only
# `os.path.realpath` maps a NUL path on Windows (open() and os.stat raise on every platform; spec R-a).
RETIRED_TERMS = ("created_at_not_today", "created_at_not_start_date", "start_check", "start_date_refusals", "run_date_refusals",
                 "resuming=", "no output carries the wall clock", "Windows maps it silently", "POSIX path calls raise")


def test_phase10_docs_no_authoritative_text_states_a_retired_rule():
    paths = [*sorted(Path(ulqs.__file__).resolve().parent.glob("*.py")), *[REPO_ROOT / "scripts" / name for name in NEW_SCRIPTS],
             *sorted(RECORDS.glob("*.md")), REPO_ROOT / "docs" / "evaluation" / "protocol.md", REPO_ROOT / "docs" / "testing" / "test-strategy.md",
             REPO_ROOT / "docs" / "adr" / "ADR-012-evaluation-and-research-harness.md", REPO_ROOT / "docs" / "adr" / "ADR-007-evaluation-harness.md",
             REPO_ROOT / "lqs" / "README.md", REPO_ROOT / "evaluation" / "tests" / "conftest.py", REPO_ROOT / ".github" / "workflows" / "ci.yml"]
    texts = {path.name: path.read_text(encoding="utf-8") for path in paths}
    texts["spec sections 0-13"] = spec_text().split("\n## 14. Review history\n", 1)[0]
    for name, text in texts.items():
        for term in RETIRED_TERMS:
            assert term not in text, (name, term)
