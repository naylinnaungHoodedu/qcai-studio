"""Phase 10: the runner's planning, units, keys, checkpoint, refusals and metrics (spec 3.9-3.12, 4.12-4.13; PD-68)."""

from __future__ import annotations

import dataclasses
import inspect
import json
from pathlib import Path

import pytest

from evaluation.qcai_eval import reporting, runner, synthetic
from evaluation.qcai_eval.canonical import hashed_hex, read_jsonl
from evaluation.qcai_eval.providers import ScriptedProvider, StubResponder, TransientFailure

REPO_ROOT = Path(__file__).resolve().parents[2]


def small_spec(tmp_path, counts=synthetic.SMALL, **kwargs):
    items_path, catalog_path, items = synthetic.write_fixture_set(tmp_path, counts, **{k: v for k, v in kwargs.items() if k in ("status",)})
    spec = synthetic.spec_dict(items_path=items_path, catalog_path=catalog_path, **{k: v for k, v in kwargs.items() if k != "status"})
    return spec, items


def test_request_keys_do_not_depend_on_run_id_and_seeds_do(tmp_path):
    spec, _ = small_spec(tmp_path)
    first = runner.plan_run(spec)
    second = runner.plan_run({**spec, "run_id": "another-run"})
    assert [r.request_key for r in first.requests] == [r.request_key for r in second.requests]
    assert [r.seed_hex for r in first.requests] != [r.seed_hex for r in second.requests]
    assert len({r.request_key for r in first.requests}) == len(first.requests)
    request = first.requests[0]
    assert request.seed_hex == hashed_hex(spec["run_id"], request.arm, request.item_id, str(request.replicate))[:16]


def test_units_expand_f_turns_and_g_levels_and_the_subsample_is_in_hash_order(tmp_path):
    spec, items = small_spec(tmp_path)
    plan = runner.plan_run(spec)
    gate = [r for r in plan.requests if r.arm == "GATE"]
    f_units = [(r.unit, r.turn_depth) for r in gate if r.item_id == "SYN-F-001"]
    assert f_units == [("SYN-F-001-t1", 1), ("SYN-F-001-t2", 2)]
    g_units = [r for r in gate if r.item_id == "SYN-G-001"]
    assert [r.unit for r in g_units] == ["beginner", "intermediate", "advanced"]
    assert len({r.evidence for r in g_units}) == 1
    ordered = sorted(["SYN-A-001", "SYN-A-002"], key=lambda item_id: hashed_hex("sha256-order-v1", item_id))
    assert runner.subsample(items, spec["replicates"]) == ordered
    assert [r.replicate for r in gate if r.item_id == "SYN-A-001"] == [1, 2, 3]
    assert [r.replicate for r in gate if r.item_id == "SYN-B-001"] == [1]
    one = runner.subsample(items, {"default": 1, "subsample": {"stratum": "A", "size": 1, "replicates": 3}})
    assert one == ordered[:1]


def test_nr_sends_no_evidence(tmp_path):
    plan = runner.plan_run(small_spec(tmp_path)[0])
    assert all(r.evidence == () for r in plan.requests if r.arm == "NR")
    assert any(r.evidence for r in plan.requests if r.arm == "LEX")


class Flaky:
    rule = "flaky"

    def __init__(self, failures):
        self.failures = failures
        self.calls = 0

    def respond(self, request):
        self.calls += 1
        if self.calls <= self.failures:
            raise TransientFailure("timeout")
        return StubResponder().respond(request)


def test_a_request_gets_four_attempts_then_a_provider_failure(tmp_path):
    spec, _ = small_spec(tmp_path, counts={"A": 1, "B": 0, "C": 0, "D": 0, "E": 0, "F": 0, "G": 0}, selected=["GATE"],
                         replicates={"default": 1})
    plan = runner.plan_run(spec)
    record = runner.execute_run(plan, Flaky(4), tmp_path / "out")
    line = read_jsonl(tmp_path / "out" / "responses.jsonl")[0]
    assert line["outcome"] == "provider_failure" and len(line["attempts"]) == 4 and line["failure_reason"] == "timeout"
    assert record["slis"]["provider_failures"] == {"timeout": 1} and record["slis"]["retries"] == 3
    record = runner.execute_run(plan, Flaky(3), tmp_path / "out2")
    assert read_jsonl(tmp_path / "out2" / "responses.jsonl")[0]["outcome"] != "provider_failure"


def test_a_partial_checkpoint_is_truncated_on_resume_and_refused_without_it(tmp_path):
    spec, _ = small_spec(tmp_path)
    plan = runner.plan_run(spec)
    reference = tmp_path / "reference"
    runner.execute_run(plan, StubResponder(), reference)
    out = tmp_path / "out"
    with pytest.raises(runner.RunInterrupted):
        runner.execute_run(plan, ScriptedProvider(outage_at=7), out)
    with (out / "responses.jsonl").open("a", encoding="utf-8", newline="\n") as handle:
        handle.write('{"request_key": "trunc')
    with pytest.raises(runner.RunRefused) as refused:
        runner.execute_run(plan, ScriptedProvider(), out)
    assert refused.value.reasons == ["partial_checkpoint"]
    runner.execute_run(plan, ScriptedProvider(), out, resume=True)
    scripted = tmp_path / "scripted"
    runner.execute_run(plan, ScriptedProvider(), scripted)
    for name in ("responses.jsonl", "payload_log.jsonl", "run_record.json"):
        assert (out / name).read_bytes() == (scripted / name).read_bytes(), name
    with pytest.raises(runner.RunRefused, match="output_exists"):
        runner.execute_run(plan, StubResponder(), reference)


def test_unlabelled_claims_put_an_arm_in_awaiting_labels(tmp_path):
    plan = runner.plan_run(small_spec(tmp_path)[0])

    class Unlabelled:
        rule = "unlabelled"

        def respond(self, request):
            response = StubResponder().respond(request)
            for claim in response["claims"]:
                claim["label"] = None
            return response

    record = runner.execute_run(plan, Unlabelled(), tmp_path / "out")
    assert all(value["status"] == "awaiting_labels" for value in record["metrics"].values())
    assert record["comparisons"] == {"status": "awaiting_labels"}


@pytest.mark.parametrize(("edit", "code", "reason"), [
    (lambda s: s["package"].update(sha256="0" * 64), 6, "package_sha256"),
    (lambda s: s["items"].update(count=99), 6, "items_sha256"),
    (lambda s: s["evidence_catalog"].update(sha256="0" * 64), 6, "catalog_sha256"),
    (lambda s: s["arms"].update(sha256="0" * 64), 6, "arms_sha256"),
    (lambda s: s["analysis_plan"].update(sha256="0" * 64), 6, "analysis_plan_sha256"),
    (lambda s: s.update(experiment="E1"), 2, "experiment_requires_confirmatory"),
    (lambda s: s.update(purpose="confirmatory"), 2, "harness_check_not_confirmatory"),
    (lambda s: s["arms"].update(selected=["NR", "SEM"]), 7, "arms.selected"),
    (lambda s: s["items"].update(required_state="frozen"), 3, "items_not_frozen"),
])
def test_each_pin_and_shape_refusal_has_its_exit_code(tmp_path, edit, code, reason):
    spec, _ = small_spec(tmp_path)
    edit(spec)
    with pytest.raises(runner.RunRefused) as refused:
        runner.plan_run(spec)
    assert refused.value.code == code and any(reason in r for r in refused.value.reasons)


def test_hold_h12_refuses_non_synthetic_items_while_d14_is_open(tmp_path):
    items = [{**item, "item_id": item["item_id"].replace("SYN-", "ULQS-"), "license_class": "private_eval_full_span"}
             for item in synthetic.synthetic_dataset({"C": 2})]
    spec = synthetic.spec_dict(items_path=synthetic.write_jsonl(tmp_path / "items.jsonl", items), catalog_path=None)
    with pytest.raises(runner.RunRefused) as refused:
        runner.plan_run(spec)
    assert refused.value.code == 9 and refused.value.reasons == ["hold_h12_data_plane"]


def test_iv_excludes_g_items_with_a_failed_level(tmp_path):
    spec, _ = small_spec(tmp_path, selected=["GATE"], replicates={"default": 1})
    plan = runner.plan_run(spec)
    failing = next(r.request_key for r in plan.requests if r.item_id == "SYN-G-001" and r.unit == "advanced")
    record = runner.execute_run(plan, ScriptedProvider(transient={failing: ["server_error"] * 4}), tmp_path / "out")
    iv = record["metrics"]["GATE"]["IV"]
    assert iv["items"] == 1 and iv["excluded_items"] == 1


def test_build_report_takes_the_time_as_an_input():
    assert "generated_at" in inspect.signature(reporting.build_report).parameters
    report = reporting.build_report(run_manifest={}, metrics={}, generated_at="2026-11-24T00:00:00Z")
    assert report["generated_at"] == "2026-11-24T00:00:00Z"
    assert "datetime" not in inspect.getsource(reporting)


def test_the_plan_is_frozen_and_the_responder_is_never_told_the_run_id(tmp_path):
    plan = runner.plan_run(small_spec(tmp_path)[0])
    assert dataclasses.is_dataclass(plan) and not any(f.name == "run_id" for f in dataclasses.fields(runner.Request))
