"""Phase 10 acceptance tests: the evaluation and research harness (plan L1680-1742; Phase 10 spec 8.1).

Every input is synthetic and built in the test's own tmp_path; scripts run in-process through main(argv). AC-10-1, AC-10-4,
AC-10-5 and AC-10-6 are proven on synthetic data and the live half of AC-10-3 with a scripted fake provider (spec R-e);
their real-data halves are deferred (DI-129..DI-141). No test reads a private file, and none writes into the checkout.
"""

from __future__ import annotations

import ast
import dataclasses
import datetime as datetime_module
from fractions import Fraction
import importlib
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
                 share="1/4", require_licensed=False, frozen=True, previous_edit=None, corpus_check=True):
    """One freeze case built from its own dataset: items, catalog, corpus text, ratings, the agreement record and the review
    set the freeze starts from (every candidate moved to review, then to frozen)."""
    items = synthetic.synthetic_dataset(counts, human_reviewed=True)
    catalog = EvidenceCatalog.from_lines(synthetic.synthetic_catalog(items))
    corpus = synthetic.corpus_text(items)
    if mutate:
        mutate(items)
    if corpus_edit:
        corpus_edit(corpus)
    rules = rules or ulqs.load_freeze_rules()
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
    result = ulqs.freeze_check(items, rules=rules, pointer_report=report, agreement=record, previous=previous,
                               require_licensed=require_licensed)
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
            "mode": "live", "responder": {"live": {"adapter": "fake-adapter"}}}
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
        "IRB approved after created_at": (synthetic.irb_record(tmp_path / "late.private.json", approval_date="2026-12-01", expiry_date=None), osf),
        "an expired IRB": (synthetic.irb_record(tmp_path / "old.private.json", approval_date="2025-01-01", expiry_date="2026-06-30"), osf),
        "an OSF plan sha mismatch": (irb, synthetic.osf_record(tmp_path / "mm.private.json", analysis_plan_sha256="e" * 64)),
        "OSF registered after the run": (irb, synthetic.osf_record(tmp_path / "after.private.json", analysis_plan_sha256=plan_sha,
                                                                    registered_date="2026-11-30")),
        "both valid": (irb, osf),
    }[case]
    spec["governance"] = {"irb_record": records[0], "osf_record": records[1]}
    return spec


IRB_OSF_CASES = {"no records": {"irb_missing", "osf_missing"}, "IRB only": {"osf_missing"}, "OSF only": {"irb_missing"},
                 "a bad DOI": {"osf_invalid:doi"}, "IRB approved after created_at": {"irb_not_yet_approved"},
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
    assert reasons == ["D-14 open", "items_not_frozen", "freeze_record_missing", "pre_run_scan_missing", "stub_not_confirmatory"]
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


def test_plan_f_the_access_log_records_every_read_and_each_run_s_outcome(tmp_path, monkeypatch):
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
    # Resumed by the same responder (the stub would not match the checkpoint: checkpoint_mismatch).
    monkeypatch.setattr(run_evaluation, "_responder", lambda plan: providers.ScriptedProvider())
    assert run_main(["--spec", spec_path, "--output-dir", out, "--resume", "--access-log", access, "--actor-role", "MLE"]) == 0
    assert _access(access)[5:] == reads + [("run", "run_spec", "started"), ("run", "run_output", "completed")]
    record = json.loads((out / "run_record.json").read_text(encoding="utf-8"))
    assert read_jsonl(access)[-1]["artifact_sha256"] == record["outputs"]["payload_log_sha256"]
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
    spec = {"created_at": synthetic.CREATED, "responder": {"live": {"adapter": "fake-adapter"}},
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
    assert "`check_research_harness.py`: 0; 1 drift; 3 a known answer not met or an invalid analysis plan; 6 a pin; 7 parity." in readme
    protocol = (REPO_ROOT / "docs" / "evaluation" / "protocol.md").read_text(encoding="utf-8")
    for arm in ablation.ARM_IDS:
        assert f"`{arm}`" in protocol, arm
    # GATE is Table XV's "deployed configuration" of the paper's design, never a claim about current production.
    flat = " ".join(protocol.split())
    assert "calls it \"the deployed configuration\" of the paper's design; it is not the current production configuration" in flat
    assert "`GATE` (the deployed configuration)" not in flat
    head = spec_text().split("\n## 14. Review history\n", 1)[0]
    for number in range(60, 75):
        assert f"| PD-{number} |" in head
    for number in range(129, 142):
        assert f"| DI-{number} |" in head
    assert "The exit is not passed (DI-129)." in head


PHASE10_MODULES = ("test_phase10_acceptance.py", "test_ulqs_schema.py", "test_ulqs_pointers.py", "test_rater_agreement.py",
                   "test_ablation_arms.py", "test_evaluation_runner.py", "test_research_statistics.py", "test_analysis_plans.py",
                   "test_seeded_fault_fixtures.py", "test_contamination_scan.py", "test_payload_log.py", "test_governance_records.py")


def test_phase10_docs_the_test_strategy_maps_every_test_module_the_phase_added():
    strategy = (REPO_ROOT / "docs" / "testing" / "test-strategy.md").read_text(encoding="utf-8")
    section = strategy.split("## Phase 10 acceptance map (plan Phase 10 K)", 1)[1]
    exit_gate = next(line for line in section.splitlines() if line.startswith("**Exit gate.** The Phase 10 exit"))
    assert exit_gate.endswith("The exit is not passed.")
    for name in PHASE10_MODULES:
        assert f"`{name}`" in section, name
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
