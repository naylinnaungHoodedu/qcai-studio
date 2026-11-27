"""Phase 10: the runner's planning, units, keys, checkpoint, refusals and metrics (spec 3.9-3.12, 4.12-4.13; PD-68)."""

from __future__ import annotations

import dataclasses
import inspect
import json
from pathlib import Path
import sys

import pytest

from evaluation.qcai_eval import reporting, runner, synthetic, ulqs
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


def test_a_corrupt_complete_checkpoint_line_is_refused_and_never_truncated(tmp_path):
    # Spec 4.12: only a trailing partial line (the bytes after the last newline) is truncated with --resume. A complete
    # line that is not a response record, anywhere in responses.jsonl, refuses the run (`checkpoint_invalid`) and leaves
    # the file as it was, so the valid responses after it are never deleted and never requested again.
    spec, _ = small_spec(tmp_path)
    plan = runner.plan_run(spec)
    out = tmp_path / "out"
    with pytest.raises(runner.RunInterrupted):
        runner.execute_run(plan, ScriptedProvider(outage_at=7), out)
    lines = (out / "responses.jsonl").read_bytes().splitlines(keepends=True)
    assert len(lines) >= 3
    for corrupt in (b"{broken\n", b"\xff\xfe\n", b"\n"):
        for position in (1, len(lines)):  # in the middle, and as the last complete line
            checkpoint = b"".join(lines[:position]) + corrupt + b"".join(lines[position:])
            for tail in (b"", b'{"request_key": "trunc'):
                (out / "responses.jsonl").write_bytes(checkpoint + tail)
                with pytest.raises(runner.RunRefused) as refused:
                    runner.execute_run(plan, ScriptedProvider(), out, resume=True)
                assert refused.value.code == 2 and refused.value.reasons == ["checkpoint_invalid"], (corrupt, position)
                assert (out / "responses.jsonl").read_bytes() == checkpoint + tail
    # A checkpoint whose run events are not UTF-8 is refused (checkpoint_mismatch), never a traceback.
    (out / "responses.jsonl").write_bytes(b"".join(lines))
    events = (out / "run_events.jsonl").read_bytes()
    (out / "run_events.jsonl").write_bytes(events + b"\xff\xfe\n")
    with pytest.raises(runner.RunRefused) as refused:
        runner.execute_run(plan, ScriptedProvider(), out, resume=True)
    assert refused.value.code == 2 and refused.value.reasons == ["checkpoint_mismatch"]
    assert (out / "responses.jsonl").read_bytes() == b"".join(lines)


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


def _interrupted(tmp_path, spec, at=7):
    plan = runner.plan_run(spec)
    out = tmp_path / "out"
    with pytest.raises(runner.RunInterrupted):
        runner.execute_run(plan, ScriptedProvider(outage_at=at), out)
    return plan, out


def _changed_text(spec, tmp_path):
    items = read_jsonl(Path(spec["items"]["path"]))
    items[0] = {**items[0], "question": "A different invented question about the Quillfen archive?"}
    path = synthetic.write_jsonl(tmp_path / "changed.jsonl", items)
    return {**spec, "items": {**spec["items"], "path": str(path), "sha256": ulqs.dataset_sha256(items)}}


@pytest.mark.parametrize("change", ["another run_id", "changed item text", "another responder"])
def test_resume_refuses_a_checkpoint_of_another_run_and_leaves_it_untouched(tmp_path, change):
    spec, _ = small_spec(tmp_path)
    _plan, out = _interrupted(tmp_path, spec)
    before = {name: (out / name).read_bytes() for name in ("responses.jsonl", "run_events.jsonl")}
    if change == "another run_id":
        other, responder = runner.plan_run({**spec, "run_id": "another-run"}), ScriptedProvider()
    elif change == "changed item text":
        other, responder = runner.plan_run(_changed_text(spec, tmp_path)), ScriptedProvider()
    else:
        other, responder = runner.plan_run(spec), StubResponder()
    with pytest.raises(runner.RunRefused) as refused:
        runner.execute_run(other, responder, out, resume=True)
    assert refused.value.code == 2 and refused.value.reasons == ["checkpoint_mismatch"]
    assert {name: (out / name).read_bytes() for name in before} == before and not (out / "run_record.json").exists()


def test_resume_refuses_a_response_line_whose_seed_or_unit_differs_from_its_request(tmp_path):
    spec, _ = small_spec(tmp_path)
    plan, out = _interrupted(tmp_path, spec)
    lines = (out / "responses.jsonl").read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    for field, value in (("seed_hex", "0" * 16), ("replicate", 9), ("arm", "NR" if first["arm"] != "NR" else "LEX")):
        edited = [json.dumps({**first, field: value}, sort_keys=True)] + lines[1:]
        (out / "responses.jsonl").write_text("\n".join(edited) + "\n", encoding="utf-8", newline="\n")
        with pytest.raises(runner.RunRefused, match="checkpoint_mismatch"):
            runner.execute_run(plan, ScriptedProvider(), out, resume=True)
    stray = {**first, "request_key": "f" * 64}
    (out / "responses.jsonl").write_text("\n".join(lines + [json.dumps(stray)]) + "\n", encoding="utf-8", newline="\n")
    with pytest.raises(runner.RunRefused, match="checkpoint_mismatch"):
        runner.execute_run(plan, ScriptedProvider(), out, resume=True)
    (out / "responses.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    (out / "run_events.jsonl").unlink()
    with pytest.raises(runner.RunRefused, match="checkpoint_mismatch"):  # a checkpoint whose start event is gone
        runner.execute_run(plan, ScriptedProvider(), out, resume=True)


@pytest.mark.parametrize("line", ["[1]", '{"outcome": "answered"}', '{"request_key": "short"}', "7"])
def test_a_checkpoint_line_that_is_not_a_response_record_is_refused(tmp_path, line):
    spec, _ = small_spec(tmp_path)
    plan, out = _interrupted(tmp_path, spec)
    with (out / "responses.jsonl").open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line + "\n")
    for resume in (True, False):
        with pytest.raises(runner.RunRefused) as refused:
            runner.execute_run(plan, ScriptedProvider(), out, resume=resume)
        assert refused.value.code == 2 and refused.value.reasons == ["checkpoint_invalid"]


# A checkpoint response line changed in one field, each a line the metrics or the payload log could not read: refused
# as checkpoint_invalid (exit 2) before any request is sent, never a KeyError or AttributeError after the run.
MALFORMED_CHECKPOINT_LINES = {
    "outcome_missing": lambda line: line.pop("outcome"),
    "outcome_not_a_string": lambda line: line.update(outcome=7),
    "outcome_unknown": lambda line: line.update(outcome="weird"),
    "claims_not_a_list": lambda line: line.update(claims="x"),
    "claim_not_an_object": lambda line: line.update(claims=["x"]),
    "cited_a_string": lambda line: line.update(claims=[{"claim_id": "c-1", "cited": "EV-SYN-001", "label": "supported"}]),
    "claims_missing": lambda line: line.pop("claims"),
    "usage_not_an_object": lambda line: line.update(usage="x"),
    "usage_missing": lambda line: line.pop("usage"),
    "usage_null": lambda line: line.update(usage=None),
    "usage_negative": lambda line: line.update(usage={"input_units": -1, "output_units": 0}),
    "signals_float": lambda line: line.update(signals={"V": 0.5}),
    "latency_first_after_total": lambda line: line.update(latency={"first_token_ms": 5, "total_ms": 1}),
    "text_not_a_string": lambda line: line.update(text=5),
    "attempts_missing": lambda line: line.pop("attempts"),
    "attempt_not_an_object": lambda line: line.update(attempts=["ok"]),
    "failure_reason_on_an_answer": lambda line: line.update(failure_reason="timeout"),
    "provider_failure_without_reason": lambda line: line.update(outcome="provider_failure", failure_reason=None),
}


@pytest.mark.parametrize("case", sorted(MALFORMED_CHECKPOINT_LINES))
def test_a_checkpoint_response_line_the_run_cannot_read_is_refused_before_any_request_is_sent(tmp_path, case):
    # Spec 4.12: "any newline-terminated line that is not a UTF-8 JSON response record" is checkpoint_invalid (exit 2).
    spec, _ = small_spec(tmp_path)
    plan, out = _interrupted(tmp_path, spec)
    lines = (out / "responses.jsonl").read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    assert runner.checkpoint_line_problem(first) is None and first["outcome"] in ("answered", "abstained")
    MALFORMED_CHECKPOINT_LINES[case](first)
    (out / "responses.jsonl").write_text("\n".join([json.dumps(first, sort_keys=True)] + lines[1:]) + "\n", encoding="utf-8",
                                         newline="\n")
    before = (out / "responses.jsonl").read_bytes()
    with pytest.raises(runner.RunRefused) as refused:
        runner.execute_run(plan, ScriptedProvider(), out, resume=True)
    assert refused.value.code == 2 and refused.value.reasons == ["checkpoint_invalid"]
    assert (out / "responses.jsonl").read_bytes() == before and not (out / "run_record.json").exists()


def test_a_well_formed_provider_failure_line_resumes_and_a_malformed_one_is_refused_through_the_cli(tmp_path):
    # A provider_failure line as the runner writes it (attempts, reason, no claims) is a response record and resumes; through
    # the CLI with the access log, a malformed reused line is refused (exit 2) with the refused outcome logged, before the
    # remaining requests are sent.
    if str(REPO_ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import run_evaluation

    spec, _ = small_spec(tmp_path, counts={"A": 1, "B": 0, "C": 0, "D": 0, "E": 0, "F": 0, "G": 0}, selected=["GATE"],
                         replicates={"default": 1})
    record = runner.execute_run(runner.plan_run(spec), Flaky(4), tmp_path / "failed")
    line = read_jsonl(tmp_path / "failed" / "responses.jsonl")[0]
    assert line["outcome"] == "provider_failure" and runner.checkpoint_line_problem(line) is None
    assert runner.checkpoint_line_problem({**line, "attempts": []} | {"failure_reason": "evidential_pass_failed"}) is None
    full_spec, _ = small_spec(tmp_path / "cli")
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(full_spec), encoding="utf-8")
    assert run_evaluation.main(["--spec", str(path), "--output-dir", str(tmp_path / "run1")]) == 0
    events = (tmp_path / "run1" / "run_events.jsonl").read_text(encoding="utf-8").splitlines()
    responses = (tmp_path / "run1" / "responses.jsonl").read_text(encoding="utf-8").splitlines()
    first = json.loads(responses[0])
    first.pop("outcome")
    run2 = tmp_path / "run2"
    run2.mkdir()
    (run2 / "run_events.jsonl").write_text(events[0] + "\n", encoding="utf-8", newline="\n")
    (run2 / "responses.jsonl").write_text("\n".join([json.dumps(first)] + responses[1:10]) + "\n", encoding="utf-8", newline="\n")
    before = (run2 / "responses.jsonl").read_bytes()
    log = tmp_path / "access.jsonl"
    assert run_evaluation.main(["--spec", str(path), "--output-dir", str(run2), "--resume", "--access-log", str(log),
                                "--actor-role", "PI"]) == 2
    assert read_jsonl(log)[-1].get("outcome") == "refused" and (run2 / "responses.jsonl").read_bytes() == before
    assert record["slis"]["provider_failures"] == {"timeout": 1}


MALFORMED = [
    (lambda s: s.update(package="v7.json"), "package.path"),
    (lambda s: s["package"].pop("path"), "package.path"),
    (lambda s: s.update(items=["x"]), "items.path"),
    (lambda s: s["items"].update(count="14"), "items.count"),
    (lambda s: s["items"].update(required_state="frozen-ish"), "items.required_state"),
    (lambda s: s.update(evidence_catalog="catalog.jsonl"), "evidence_catalog.path"),
    (lambda s: s["arms"].update(selected="GATE"), "arms.selected"),
    (lambda s: s["analysis_plan"].update(family=1), "analysis_plan.family"),
    (lambda s: s.update(seeds=None), "seeds"),
    (lambda s: s.update(created_at="garbage"), "created_at"),
    (lambda s: s.update(created_at="2026-13-40T00:00:00Z"), "created_at"),
    (lambda s: s.update(replicates={"default": "x"}), "replicates"),
    (lambda s: s.update(replicates={"default": 0}), "replicates"),
    (lambda s: s.update(replicates={"default": 1, "subsample": {"stratum": "Q", "size": 2, "replicates": 3}}), "replicates.subsample"),
    (lambda s: s.update(replicates={"default": 1, "subsample": {"stratum": "A", "size": 0, "replicates": 3}}), "replicates.subsample"),
    (lambda s: s.update(retries=-5), "retries"),
    (lambda s: s.update(retries="many"), "retries"),
    (lambda s: s.update(retries=True), "retries"),
    (lambda s: s.update(responder="stub"), "responder"),
    (lambda s: s.update(governance=[]), "governance"),
    (lambda s: s.update(bootstrap={"resamples": 0, "level": "0.95"}), "bootstrap"),
    (lambda s: s.update(bootstrap={"resamples": 10, "level": 0.95}), "bootstrap"),
    (lambda s: s.update(pre_run_scan="scan.json"), "pre_run_scan"),
    (lambda s: s.update(mode="recorded", responder={"recorded": "x"}), "responder.recorded"),
    (lambda s: s.update(mode="recorded", responder={"recorded": [1]}), "responder.recorded"),
    (lambda s: s.update(mode="recorded", responder={"recorded": {"path": 1, "sha256": "0" * 64}}), "responder.recorded"),
    (lambda s: s.update(mode="recorded", responder={"recorded": {"path": "r.jsonl", "sha256": None}}), "responder.recorded"),
    (lambda s: s.update(mode="live", responder={"live": "x"}), "responder.live"),
    (lambda s: s.update(mode="live", responder={"live": [1]}), "responder.live"),
    (lambda s: s.update(mode="live", responder={"live": {"adapter": [1]}}), "responder.live"),
    (lambda s: s.update(mode="live", responder={"live": {"adapter": "a", "providers": "SYN-PROVIDER-1"}}), "responder.live"),
    (lambda s: s.update(mode="live", responder={"live": {"adapter": "a", "providers": [1]}}), "responder.live"),
    (lambda s: s.update(responder={"rule": 5}), "responder.rule"),
    (lambda s: s.update(provider_terms="terms.json"), "provider_terms"),
    (lambda s: s.update(provider_terms=[]), "provider_terms"),
    (lambda s: s.update(provider_terms=[{"path": "t.json", "sha256": "0" * 64}, "t2.json"]), "provider_terms"),
    # Labels reach a run only inside its responses: a `labels` value, even one naming a file, is refused, never ignored.
    (lambda s: s.update(labels={"path": "nowhere/labels.jsonl", "sha256": "0" * 64}), "labels"),
    (lambda s: s.update(labels="labels.jsonl"), "labels"),
]


def test_provider_terms_may_be_one_reference_or_one_per_provider(tmp_path):
    # Plan H (b) per provider: the shape check accepts one reference or a non-empty list of references.
    spec, _ = small_spec(tmp_path)
    for terms in ({"path": "t.json", "sha256": "0" * 64}, [{"path": "t.json", "sha256": "0" * 64}, {"path": "u.json", "sha256": "1" * 64}]):
        assert "provider_terms" not in runner._type_problems({**spec, "provider_terms": terms})


def _nodes(value, path=()):
    yield path
    children = value.items() if isinstance(value, dict) else enumerate(value) if isinstance(value, list) else ()
    for key, child in children:
        yield from _nodes(child, path + (key,))


@pytest.mark.parametrize("mode", ["stub", "recorded", "live"])
def test_no_malformed_value_anywhere_in_a_spec_ends_in_a_traceback(tmp_path, mode):
    # Every node of a stub, recorded and live spec replaced in turn by a value of the wrong type, or by a string open()
    # refuses (an embedded NUL): the planner refuses (RunRefused) or plans; any other exception would reach the CLI as a
    # traceback with exit 1, the drift code.
    responder = {"stub": None, "recorded": {"recorded": {"path": "r.jsonl", "sha256": "0" * 64}}, "live": {"live": {"adapter": "none"}}}[mode]
    base, _ = small_spec(tmp_path, mode=mode, responder=responder)
    for path in list(_nodes(base))[1:]:
        for bad in ("x", [1], {"path": 1}, None, "a\x00b.jsonl"):
            spec = json.loads(json.dumps(base))
            target = spec
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = bad
            try:
                runner.plan_run(spec)
            except runner.RunRefused:
                pass


def _response_of(lines):
    return lines[1]["response"]


def _claim_of(lines):
    return lines[1]["response"]["claims"][0]


# Each malformed recording entry (the first entry of the committed synthetic recording, changed in one field): the run
# is refused as recording_invalid (exit 3) when the recording is read, never a KeyError, TypeError, IndexError,
# ValueError or OverflowError after requests were written.
MALFORMED_RECORDINGS = {
    "response_without_outcome": lambda lines: _response_of(lines).pop("outcome"),
    "outcome_outside_the_enumeration": lambda lines: _response_of(lines).update(outcome="weird"),
    "outcome_provider_failure": lambda lines: _response_of(lines).update(outcome="provider_failure"),
    "claims_not_a_list": lambda lines: _response_of(lines).update(claims=5),
    "claim_not_an_object": lambda lines: _response_of(lines).update(claims=[5]),
    "claim_id_not_a_string": lambda lines: _claim_of(lines).update(claim_id=5),
    "cited_not_a_list": lambda lines: _claim_of(lines).update(cited=5),
    "cited_not_strings": lambda lines: _claim_of(lines).update(cited=[1]),
    "label_unknown": lambda lines: _claim_of(lines).update(label="bogus"),
    "ehmf_type_not_a_string": lambda lines: _claim_of(lines).update(ehmf_type=5),
    "text_not_a_string": lambda lines: _response_of(lines).update(text=5),
    "usage_not_an_object": lambda lines: _response_of(lines).update(usage="x"),
    "usage_negative": lambda lines: _response_of(lines).update(usage={"input_units": -1, "output_units": 1}),
    "usage_above_the_bound": lambda lines: _response_of(lines).update(usage={"input_units": 10 ** 6 + 1, "output_units": 1}),
    "usage_huge": lambda lines: _response_of(lines).update(usage={"input_units": 10 ** 400, "output_units": 1}),
    "usage_bool": lambda lines: _response_of(lines).update(usage={"input_units": True, "output_units": 1}),
    "usage_float": lambda lines: _response_of(lines).update(usage={"input_units": 1.5, "output_units": 1}),
    "usage_unknown_key": lambda lines: _response_of(lines).update(usage={"tokens": 1}),
    "model_id_not_an_id": lambda lines: _response_of(lines).update(model_id="Not An Id"),
    "verdict_unknown": lambda lines: _response_of(lines).update(verdict="maybe"),
    "features_not_an_object": lambda lines: _response_of(lines).update(features=5),
    "features_huge_integer": lambda lines: _response_of(lines).update(features={"fk_grade": 10 ** 400}),
    "features_infinite": lambda lines: _response_of(lines).update(features={"fk_grade": float("inf")}),
    "features_string": lambda lines: _response_of(lines).update(features={"fk_grade": "x"}),
    "features_unknown": lambda lines: _response_of(lines).update(features={"colour": 1}),
    "signals_float": lambda lines: _response_of(lines).update(signals={"V": 0.5}),
    "signals_above_one": lambda lines: _response_of(lines).update(signals={"V": "2"}),
    "signals_nan": lambda lines: _response_of(lines).update(signals={"V": "NaN"}),
    "signals_not_decimal": lambda lines: _response_of(lines).update(signals={"V": "high"}),
    "signals_unknown": lambda lines: _response_of(lines).update(signals={"Z": "0.5"}),
    "latency_first_after_total": lambda lines: _response_of(lines).update(latency={"first_token_ms": 5, "total_ms": 1}),
    "latency_missing_key": lambda lines: _response_of(lines).update(latency={"total_ms": 1}),
    "latency_negative": lambda lines: _response_of(lines).update(latency={"first_token_ms": -1, "total_ms": 1}),
    "response_missing": lambda lines: lines[1].pop("response"),
    "response_not_an_object": lambda lines: lines[1].update(response=[1]),
    "attempts_empty": lambda lines: lines[1].update(attempts=[]),
    "attempts_not_a_list": lambda lines: lines[1].update(attempts="ok"),
    "attempt_status_unknown": lambda lines: lines[1].update(attempts=[{"status": "boom"}]),
    "attempt_extra_key": lambda lines: lines[1].update(attempts=[{"status": "ok", "note": "x"}]),
    "attempt_not_an_object": lambda lines: lines[1].update(attempts=["ok"]),
    "request_key_not_a_string": lambda lines: lines[1].update(request_key=5),
    "request_key_repeated": lambda lines: lines.append(json.loads(json.dumps(lines[1]))),
}


def _recording_spec(tmp_path, mutate=None):
    from evaluation.qcai_eval.canonical import lf_sha256

    lines = read_jsonl(synthetic.RECORDED_FIXTURE)
    if mutate is not None:
        mutate(lines)
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "recording.jsonl"
    path.write_bytes("".join(json.dumps(line, sort_keys=True, separators=(",", ":")) + "\n" for line in lines).encode("utf-8"))
    spec = synthetic.spec_dict(items_path="evaluation/fixtures/synthetic_ulqs_v1.jsonl",
                               catalog_path="evaluation/fixtures/synthetic_evidence_catalog_v1.jsonl", run_id="synthetic-recorded-v1",
                               mode="recorded", responder={"recorded": {"path": str(path), "sha256": lf_sha256(path)}})
    return spec


@pytest.mark.parametrize("case", sorted(MALFORMED_RECORDINGS))
def test_a_recording_entry_the_run_cannot_read_is_refused_as_recording_invalid_and_never_a_traceback(tmp_path, case):
    spec = _recording_spec(tmp_path, MALFORMED_RECORDINGS[case])
    with pytest.raises(runner.RunRefused) as refused:
        runner.plan_run(spec)
    assert refused.value.code == 3 and refused.value.reasons == ["recording_invalid"]
    # Through the CLI with the access log: exit 3, and the run's refused outcome is logged after the recording's read.
    if str(REPO_ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import run_evaluation

    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    log = tmp_path / "access.jsonl"
    assert run_evaluation.main(["--spec", str(path), "--output-dir", str(tmp_path / "out"), "--access-log", str(log),
                                "--actor-role", "MLE"]) == 3
    lines = read_jsonl(log)
    assert lines[-1].get("outcome") == "refused" and any(line.get("artifact_kind") == "recording" for line in lines)
    assert not (tmp_path / "out" / "responses.jsonl").exists()


def test_a_well_formed_recording_plans_and_a_tampered_invalid_one_is_a_pin_mismatch_first(tmp_path):
    # The unchanged recording plans; an entry whose attempts all fail needs no response; a file that is not the pinned one
    # is refused as recording_sha256 (exit 6) before its entries are judged.
    from evaluation.qcai_eval.providers import UNITS_MAX

    runner.plan_run(_recording_spec(tmp_path / "plain"))
    failing = _recording_spec(tmp_path / "failing", lambda lines: (lines[1].update(attempts=[{"status": "server_error"}] * 4),
                                                                   lines[1].pop("response")))
    runner.plan_run(failing)
    bounded = _recording_spec(tmp_path / "bounded", lambda lines: _response_of(lines).update(
        usage={"input_units": UNITS_MAX, "output_units": 0}, signals={"V": "1", "S": None, "H": 0}, features={"fk_grade": 8.5},
        latency={"first_token_ms": 1, "total_ms": 1}, verdict="pass"))
    runner.plan_run(bounded)
    spec = _recording_spec(tmp_path / "tampered", MALFORMED_RECORDINGS["response_missing"])
    spec["responder"]["recorded"]["sha256"] = "0" * 64
    with pytest.raises(runner.RunRefused) as refused:
        runner.plan_run(spec)
    assert refused.value.code == 6 and refused.value.reasons == ["recording_sha256"]


@pytest.mark.parametrize("tamper", ["malformed", "well_formed"])
def test_a_recorded_run_replays_the_recording_the_planner_verified_even_when_the_file_changes_after_planning(
        tmp_path, monkeypatch, tamper):
    # The planner checks the recording's sha256, its run pins and every entry; the run replays that same responder
    # (`plan.recorded_responder`), never a second read of the path: a file replaced after planning is neither a traceback
    # (malformed) nor replayed under the pinned sha256 (well formed).
    if str(REPO_ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import run_evaluation

    spec = _recording_spec(tmp_path / "recording")
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    assert run_evaluation.main(["--spec", str(path), "--output-dir", str(tmp_path / "baseline")]) == 0
    recording = Path(spec["responder"]["recorded"]["path"])
    lines = read_jsonl(recording)
    if tamper == "malformed":
        lines[1]["response"]["outcome"] = 7
    else:
        lines[1]["response"]["text"] = "A different invented answer."
    plan_run = runner.plan_run

    def plan_then_replace(*args, **kwargs):
        plan = plan_run(*args, **kwargs)
        recording.write_bytes("".join(json.dumps(line, sort_keys=True, separators=(",", ":")) + "\n" for line in lines).encode("utf-8"))
        return plan

    monkeypatch.setattr(runner, "plan_run", plan_then_replace)
    log = tmp_path / "access.jsonl"
    assert run_evaluation.main(["--spec", str(path), "--output-dir", str(tmp_path / "out"), "--access-log", str(log),
                                "--actor-role", "MLE"]) == 0
    assert read_jsonl(log)[-1].get("outcome") == "completed"
    for name in ("responses.jsonl", "payload_log.jsonl"):
        assert (tmp_path / "out" / name).read_bytes() == (tmp_path / "baseline" / name).read_bytes(), name
    plan = plan_run(_recording_spec(tmp_path / "again"))
    assert run_evaluation._responder(plan) is plan.recorded_responder and plan.recorded_responder is not None


def test_e4_usage_at_the_recording_bound_and_prices_at_price_max_run_to_completion(tmp_path, monkeypatch):
    # The bounds the recording check (UNITS_MAX) and the design check (PRICE_MAX) admit are bounds the computation can
    # use: every response logging UNITS_MAX units of each kind at PRICE_MAX per unit replays without an exception.
    from evaluation.qcai_eval import experiments
    from evaluation.qcai_eval.providers import UNITS_MAX

    price = str(experiments.PRICE_MAX)
    models = [{**entry, "price_per_input_unit": price, "price_per_output_unit": price} for entry in E4_MODELS]
    spec, _items = _e4_spec(tmp_path, monkeypatch, models=models, stream_length=20, streams=2)

    class Heavy(StubResponder):
        def respond(self, request):
            return {**super().respond(request), "usage": {"input_units": UNITS_MAX, "output_units": UNITS_MAX}}

    plan = runner.plan_run(spec)
    record = runner.execute_run(plan, Heavy(), tmp_path / "run")
    assert record["metrics"]["cost"]["model-a"]["input_units"] > 0
    # The controller applies each outcome's cost units (the cost in thousandths): at the bound, with every model eligible.
    cost = 2.0 * UNITS_MAX * float(experiments.PRICE_MAX)
    outcome = experiments.Outcome(y=1, quality=1.0, cost=cost, first_cost=cost)
    population = {("SYN-A-001", None): {"topic": "invented topic a", "outcomes": {model: outcome for model in PRICE}}}
    result = experiments._replay_stream(plan, population, list(population), sorted(PRICE), "s", commission=COMMISSION)["policies"]
    assert result["controller"]["verified_quality"] == 20.0 and result["controller"]["cost"] == pytest.approx(20 * cost)


@pytest.mark.parametrize(("block", "code", "reason"), [("items", 3, "items_unreadable"), ("evidence_catalog", 3, "catalog_invalid"),
                                                     ("recorded", 6, "recording_unreadable")])
def test_an_input_path_open_refuses_is_refused_with_its_own_code_and_never_a_traceback(tmp_path, block, code, reason, capsys):
    # A path with an embedded NUL makes open() raise ValueError. The items, the catalog and the recording are each refused
    # with their own code, with and without an access-log observer, and the CLI exits with that code, not with 1.
    responder = {"recorded": {"path": "r.jsonl", "sha256": "0" * 64}} if block == "recorded" else None
    spec, _ = small_spec(tmp_path, mode="recorded" if block == "recorded" else "stub", responder=responder)
    (spec["responder"]["recorded"] if block == "recorded" else spec[block])["path"] = "a\x00b.jsonl"
    for on_read in (None, lambda kind, sha256: None):
        with pytest.raises(runner.RunRefused) as refused:
            runner.plan_run(spec, on_read=on_read)
        assert refused.value.code == code and refused.value.reasons == [reason]
    if str(REPO_ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import run_evaluation

    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    assert run_evaluation.main(["--spec", str(path), "--output-dir", str(tmp_path / "out")]) == code
    assert "Traceback" not in capsys.readouterr().err


@pytest.mark.parametrize(("edit", "reason"), MALFORMED)
def test_a_malformed_spec_is_refused_with_exit_2_naming_the_field(tmp_path, edit, reason):
    spec, _ = small_spec(tmp_path)
    edit(spec)
    with pytest.raises(runner.RunRefused) as refused:
        runner.plan_run(spec)
    assert refused.value.code == 2 and reason in refused.value.reasons


def test_the_cli_refuses_a_malformed_or_unreadable_spec_with_exit_2(tmp_path, capsys):
    import importlib

    if str(REPO_ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
    run_evaluation = importlib.import_module("run_evaluation")
    spec, _ = small_spec(tmp_path)
    spec["package"] = "v7.json"
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    for argv in (["--spec", str(path), "--output-dir", str(tmp_path / "out")], ["--spec", str(tmp_path / "broken.json"), "--output-dir",
                 str(tmp_path / "out")], ["--check", str(tmp_path / "r.json"), "--spec", str(tmp_path / "broken.json")],
                 ["--write", str(tmp_path / "r.json"), "--spec", str(path)], ["--record-stub", str(tmp_path / "r.jsonl"), "--spec",
                 str(tmp_path / "absent.json")]):
        assert run_evaluation.main(argv) == 2, argv
    assert "Traceback" not in capsys.readouterr().err


def test_omitted_replicates_and_retries_take_the_provisional_harness_parameters(tmp_path):
    parameters = runner.load_harness_parameters()
    assert parameters["provisional"] is True and parameters["retries"] == 3
    assert parameters["replicates"] == {"default": 1, "subsample": {"stratum": "A", "size": 40, "replicates": 3, "rule": "sha256-order-v1"}}
    spec, _ = small_spec(tmp_path)
    del spec["replicates"], spec["retries"]
    plan = runner.plan_run(spec)
    assert plan.pins["replicates"] == parameters["replicates"] and plan.pins["retries"] == 3
    assert plan.pins["harness_parameters"]["used_for"] == ["replicates", "retries"]
    # Both A items (fewer than 40) are in the subsample, each with three replicates.
    assert sorted(r.replicate for r in plan.requests if r.arm == "GATE" and r.item_id.startswith("SYN-A-")) == [1, 1, 2, 2, 3, 3]


@pytest.mark.parametrize("replicates", [{"default": 1}, {"default": 1, "subsample": {"stratum": "A", "size": 2, "replicates": 1}}])
def test_live_and_confirmatory_specs_must_keep_a_replicate_subsample(tmp_path, replicates):
    spec, _ = small_spec(tmp_path, replicates=replicates)
    for changes in ({"mode": "live", "responder": {"live": {"adapter": "none"}}},
                    {"purpose": "confirmatory", "experiment": "E1"}):
        with pytest.raises(runner.RunRefused) as refused:
            runner.plan_run({**spec, **changes})
        assert refused.value.code == 2 and refused.value.reasons == ["replicate_subsample_required"]
    runner.plan_run(spec)  # an exploratory stub run may drop the subsample


def test_the_record_s_code_pins_cover_only_the_harness_and_ignore_crlf_checkouts(tmp_path):
    # The stub record pins the LF sha256 of each harness module and of scripts/run_evaluation.py, nothing else, so an
    # unrelated change elsewhere never drifts the record, and a CRLF (core.autocrlf) checkout pins what an LF one does.
    pins = runner.code_pins()
    assert set(pins) == {path.relative_to(REPO_ROOT).as_posix() for path in Path(runner.__file__).resolve().parent.glob("*.py")} | {
        "scripts/run_evaluation.py"}
    for name in pins:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((REPO_ROOT / name).read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    assert runner.code_pins(tmp_path) == pins


def _scripted(rule):
    """A responder whose answers follow `rule(request) -> (outcome, labels)`: one claim per gold claim (or one invented
    claim for an abstain unit), labelled in turn from `labels`."""

    class Scripted:
        def respond(self, request):
            outcome, labels = rule(request)
            usage = {"input_units": 1, "output_units": 1}
            if outcome == "abstained":
                return {"outcome": "abstained", "claims": [], "text": "stub", "usage": usage, "model_id": None}
            ids = list(request.gold_claims) or [f"{request.item_id}-x1"]
            claims = [{"claim_id": claim_id, "cited": list(request.evidence), "label": labels[index % len(labels)], "ehmf_type": None}
                      for index, claim_id in enumerate(ids)]
            return {"outcome": "answered", "claims": claims, "text": "stub", "usage": usage, "model_id": None}

    Scripted.rule = "scripted-rule"
    return Scripted()


def _gate_passed(monkeypatch):
    # A confirmatory E1-E4 spec cannot pass its gate here (no IRB or OSF record). The gate's own refusals are the AC-10-5
    # tests'; here it is passed so that the design is planned (as in the AC test of a confirmatory run's coverage).
    from evaluation.qcai_eval import governance

    monkeypatch.setattr(governance, "confirmatory_refusals", lambda spec, **kwargs: [])


def _confirmatory(tmp_path, experiment, **extra):
    items_path, catalog_path, items = synthetic.write_fixture_set(tmp_path, synthetic.SMALL, splits=True)
    spec = synthetic.spec_dict(items_path=items_path, catalog_path=catalog_path, purpose="confirmatory", experiment=experiment,
                               family=experiment, run_id=f"synthetic-{experiment.lower()}-v1", **extra)
    return spec, items


ANSWERABLE = ["SYN-A-001", "SYN-A-002", "SYN-B-001", "SYN-B-002", "SYN-D-002", "SYN-F-001", "SYN-F-002", "SYN-G-001", "SYN-G-002"]


def test_an_e1_record_computes_the_registered_e1_family_and_other_records_do_not(tmp_path, monkeypatch):
    # VBT RevB Table I: H1a "VLOOP has a lower item-level error rate than GATE on answerable items", endpoint "Share of
    # answerable items whose response contains at least one fabricated or attribution-error claim (an abstention scores
    # as no error ...)", test "Exact McNemar, paired by item"; H1b "Same as H1a" against GATE+SV. The expected values are
    # written out by hand: one error indicator per answerable item, whatever its turns or levels, and nothing from the
    # gold-abstain units (VLOOP answers every one of them here, which pairing by unit would count as 7 more errors).
    from evaluation.qcai_eval import statistics

    _gate_passed(monkeypatch)
    spec, items = _confirmatory(tmp_path, "E1")
    gate_errors = {"SYN-A-001": None, "SYN-B-001": None, "SYN-G-001": "advanced", "SYN-F-002": None}  # item: its one erring unit
    vloop_errors = {"SYN-G-001": "beginner"}

    def rule(request):
        if request.gold == "abstain":
            return ("answered", ["unsupported_but_true"]) if request.arm == "VLOOP" else ("abstained", [])
        erring = {"GATE": gate_errors, "VLOOP": vloop_errors}.get(request.arm, {})
        if request.item_id in erring and erring[request.item_id] in (None, request.unit):
            return "answered", ["fabricated"]
        return "answered", ["supported"]

    plan = runner.plan_run(spec)
    record = runner.execute_run(plan, _scripted(rule), tmp_path / "e1")
    registered = record["registered_tests"]
    assert registered["family"] == "E1" and set(registered["hypotheses"]) == {"H1a", "H1b", "H1c"}
    assert sorted(item["item_id"] for item in items if any(unit["gold"] == "answer" for unit in runner._units(item))) == ANSWERABLE
    vloop = [item in vloop_errors for item in ANSWERABLE]
    for name, right_arm, right in (("H1a", "GATE", [item in gate_errors for item in ANSWERABLE]), ("H1b", "GATE+SV", [False] * 9)):
        expected = statistics.mcnemar_exact(vloop, right)
        assert registered["hypotheses"][name] == {"endpoint": "item-level error on answerable items, paired by item (Table I; eq. 12)",
                                                  "comparison": ["VLOOP", right_arm], "test": "mcnemar_exact", **expected, "items": 9}, name
    assert registered["hypotheses"]["H1a"]["right_only"] == 3 and registered["hypotheses"]["H1b"]["left_only"] == 1
    # H1c: every answerable unit is answered in both arms, so each item's answer rate is 1 and the difference 0.
    h1c = statistics.paired_bootstrap_one_sided([1.0] * 9, [1.0] * 9, resamples=1000,
                                                seed=hashed_hex(spec["run_id"], "registered", "H1c"), margin="-0.05")
    assert registered["hypotheses"]["H1c"] == {"endpoint": "answer rate (eq. 17)", "comparison": ["VLOOP", "GATE"],
                                              "test": "paired_bootstrap_one_sided", **h1c}
    assert registered["holm"] == statistics.holm({name: value["p_value"] for name, value in registered["hypotheses"].items()})
    assert "GATE-vs-NR" in record["comparisons"]["pairs"]  # the exploratory comparisons stay what they were
    check = runner.plan_run(small_spec(tmp_path / "check")[0])
    assert runner.execute_run(check, StubResponder(), tmp_path / "check-out")["registered_tests"] is None


def _plans_with(tmp_path, edit):
    from evaluation.qcai_eval.canonical import canonical_sha256, dumps_record, write_lf

    raw = json.loads((REPO_ROOT / synthetic.PLANS_PATH).read_text(encoding="utf-8"))
    edit(raw)
    path = tmp_path / "plans.json"
    write_lf(path, dumps_record(raw))
    return {"path": str(path), "sha256": canonical_sha256(raw), "family": "E1"}


def _single_quantity(hypothesis, test, margin="0.03"):
    hypothesis.pop("comparison")
    hypothesis.update(test=test, sided="one", margin=margin)


@pytest.mark.parametrize("edit", [
    lambda raw: _single_quantity(raw["families"]["E1"]["hypotheses"][1], "wilson_upper_bound"),
    lambda raw: raw["families"]["E1"]["hypotheses"][0].update(comparison=["VLOOP", "GATE", "NR"]),
    lambda raw: _single_quantity(raw["families"]["E1"]["hypotheses"][2], "bootstrap_one_sided", "-0.05"),
])
def test_an_e1_family_the_design_does_not_compute_is_refused_before_anything_runs(tmp_path, monkeypatch, edit):
    # The plans file validates (validate_plans), but E1 computes only H1a/H1b exact McNemar and H1c's paired bootstrap,
    # each over two of the selected arms: anything else is refused when planned (exit 2), never a traceback after the run.
    from evaluation.qcai_eval import analysis_plans

    _gate_passed(monkeypatch)
    spec, _ = _confirmatory(tmp_path, "E1")
    plan_block = _plans_with(tmp_path, edit)
    analysis_plans.validate_plans(json.loads(Path(plan_block["path"]).read_text(encoding="utf-8")))
    with pytest.raises(runner.RunRefused) as refused:
        runner.plan_run({**spec, "analysis_plan": plan_block})
    assert refused.value.code == 2 and refused.value.reasons == ["analysis_plan_invalid:E1"]
    runner.plan_run(spec)  # the committed plans pass


def _e2_spec(tmp_path, monkeypatch, **changes):
    from evaluation.qcai_eval.canonical import lf_sha256

    _gate_passed(monkeypatch)
    spec, _items = _confirmatory(tmp_path, "E1")
    runner.execute_run(runner.plan_run(spec), StubResponder(), tmp_path / "e1")
    responses = tmp_path / "e1" / "responses.jsonl"
    design = {"verification_set": {"path": str(responses), "sha256": lf_sha256(responses), "generator_family": "family-g"},
              "verifiers": [{"model_id": "verifier-a", "family": "family-a"}, {"model_id": "verifier-b", "family": "family-b"},
                            {"model_id": "verifier-c", "family": "family-c"}, {"model_id": "verifier-g", "family": "family-g"}],
              "resamples": 400, **changes}
    e2 = {**spec, "experiment": "E2", "run_id": "synthetic-e2-v1", "analysis_plan": {**spec["analysis_plan"], "family": "E2"},
          "design": design}
    return e2, read_jsonl(responses)


def test_e2_verifies_every_labelled_claim_outside_each_verifier_s_family_and_forms_the_panels_by_rule(tmp_path, monkeypatch):
    # VBT RevB Sec. VIII-D E2: "Each model verifies every claim generated outside its own provider family, and panels are
    # formed afterwards by rule, so 1oo3, 2oo3, 3oo3 and Dawid-Skene panels are compared on identical claims"; Table I:
    # H2a the 2oo3 panel's claim-level F1 against the best single verifier's, H2b DR = P_all / (m1 m2 m3).
    from evaluation.qcai_eval import experiments, statistics
    from evaluation.qcai_eval.canonical import canonical_sha256

    spec, source = _e2_spec(tmp_path, monkeypatch)
    plan = runner.plan_run(spec)
    gold = {canonical_sha256({"source": "E1", "request_key": line["request_key"], "claim_id": claim["claim_id"]}):
            claim["label"] in experiments.ERROR_LABELS for line in source if line["replicate"] == 1 and line["outcome"] == "answered"
            for claim in line["claims"]}
    assert {request.cell for request in plan.requests} == {"verifier-a", "verifier-b", "verifier-c"}  # not the generator's family
    assert {request.subject for request in plan.requests} == set(gold) and {request.role for request in plan.requests} == {"verify"}
    item_of = {request.subject: request.item_id for request in plan.requests}

    def flags(subject):  # a objects to every erroneous claim, b to every claim, c to the erroneous claims of items before D
        return (gold[subject], True, gold[subject] and item_of[subject] < "SYN-D")

    class Verifiers:
        rule = "scripted-verifiers"

        def respond(self, request):
            flag = flags(request.subject)[("verifier-a", "verifier-b", "verifier-c").index(request.cell)]
            return {"outcome": "answered", "verdict": "object" if flag else "pass", "claims": [], "text": "v",
                    "usage": {"input_units": 1, "output_units": 1}, "model_id": None}

    record = runner.execute_run(plan, Verifiers(), tmp_path / "e2")
    panel = record["metrics"]["panel"]
    assert panel["members"] == ["verifier-a", "verifier-b", "verifier-c"] and panel["claims"] == len(gold)
    for needed in (1, 2, 3):
        rows = [(gold[subject], sum(flags(subject)) >= needed) for subject in gold]
        counts = (sum(g and f for g, f in rows), sum((not g) and f for g, f in rows), sum(g and not f for g, f in rows))
        rule = panel["rules"][f"{needed}oo3"]
        assert (rule["true_positives"], rule["false_positives"], rule["false_negatives"]) == counts, needed
    # 2oo3 flags exactly the erroneous claims (a and b agree on them; b alone objects to the rest): F1 1, as a's.
    assert panel["rules"]["2oo3"]["F1"] == 1.0 == record["metrics"]["verifiers"]["verifier-a"]["F1"]
    hypotheses = record["registered_tests"]["hypotheses"]
    assert hypotheses["H2b"]["status"] == "undefined"  # a never misses an erroneous claim: m_a = 0
    assert hypotheses["H2c"]["status"] == "awaiting_ratings"
    assert experiments._dr([[(True, (False, False, False)), (True, (True, False, False))], [(True, (False, True, True))]]) == \
        pytest.approx((1 / 3) / ((2 / 3) ** 3))
    assert experiments._dr([[(True, (True, True, True))]]) == float("-inf")
    clusters = [[(True, (True, False, True)), (False, (False, True, False))], [(True, (True, True, False))], [(False, (True, False, False))]]
    assert experiments._f1([(g, flags_[0]) for cluster in clusters for g, flags_ in cluster]) == pytest.approx(2 * 2 / (2 * 2 + 1))
    posterior = experiments.dawid_skene([(True, True, True), (False, False, False), (True, True, False), (False, False, True)], 50)
    assert posterior[0] > 0.5 > posterior[1] and posterior[2] > 0.5 > posterior[3]
    assert record["registered_tests"]["holm"] == statistics.holm(
        {name: value["p_value"] for name, value in hypotheses.items() if "p_value" in value})


@pytest.mark.parametrize(("change", "code", "reason"), [
    ({"verifiers": [{"model_id": "verifier-a", "family": "family-a"}, {"model_id": "verifier-b", "family": "family-a"},
                    {"model_id": "verifier-c", "family": "family-c"}]}, 2, "e2_panel_invalid"),
    ({"verifiers": [{"model_id": "verifier-a", "family": "family-a"}, {"model_id": "verifier-g", "family": "family-g"},
                    {"model_id": "verifier-c", "family": "family-c"}]}, 2, "e2_panel_invalid"),
    ({"verifiers": "panel"}, 2, "design.verifiers"),
    ({"verification_set": {"path": "missing.jsonl", "sha256": "0" * 64, "generator_family": "family-g"}}, 3, "verification_set_unreadable"),
])
def test_e2_refuses_a_panel_that_is_not_three_families_without_the_generator_and_an_input_it_cannot_read(tmp_path, monkeypatch, change,
                                                                                                         code, reason):
    spec, _source = _e2_spec(tmp_path, monkeypatch, **change)
    with pytest.raises(runner.RunRefused) as refused:
        runner.plan_run(spec)
    assert refused.value.code == code and refused.value.reasons == [reason]
    good, _source = _e2_spec(tmp_path / "again", monkeypatch)
    pinned = {**good["design"]["verification_set"], "sha256": "0" * 64}
    with pytest.raises(runner.RunRefused) as refused:
        runner.plan_run({**good, "design": {**good["design"], "verification_set": pinned}})
    assert refused.value.code == 6 and refused.value.reasons == ["verification_set_sha256"]


def test_e3_runs_two_pass_and_single_pass_at_three_levels_and_tests_invariance_paired_by_item(tmp_path, monkeypatch):
    # VBT RevB Sec. VIII-D E3: "Each S7 item runs at three mastery levels ... under two designs: two-pass channel
    # separation, in which the evidential pass runs once per item and its locked claims are reused at every level, and
    # single-pass conditioning"; "Single-pass generation is also repeated three times at one fixed level". H3a exact
    # McNemar on v_q (eq. 18) paired by item; H3b Friedman over the levels.
    from evaluation.qcai_eval import statistics

    _gate_passed(monkeypatch)
    spec, items = _confirmatory(tmp_path, "E3", design={})
    plan = runner.plan_run(spec)
    g_items = sorted(item["item_id"] for item in items if item["stratum"] == "G")
    assert sorted({request.item_id for request in plan.requests}) == g_items
    per_item = [(request.role, request.unit, request.replicate) for request in plan.requests if request.item_id == g_items[0]]
    assert per_item == [("two-pass-evidential", None, 1), ("two-pass", "beginner", 1), ("two-pass", "intermediate", 1),
                        ("two-pass", "advanced", 1), ("single-pass", "beginner", 1), ("single-pass", "intermediate", 1),
                        ("single-pass", "intermediate", 2), ("single-pass", "intermediate", 3), ("single-pass", "advanced", 1)]
    assert plan.pins["design"] == {"experiment": "E3", "arm": "VLOOP", "fixed_level": "intermediate", "repeats": 3, "h3b_feature": "fk_grade",
                                   "resamples": None, "ratings": None, "departures": []}
    grades = {"beginner": 5, "intermediate": 8, "advanced": 12}

    class Generator:
        rule = "scripted-e3"

        def respond(self, request):
            drop = request.role == "single-pass" and request.item_id == g_items[0] and request.unit == "advanced"
            claims = [] if drop else [{"claim_id": claim, "cited": list(request.evidence), "label": "supported", "ehmf_type": None}
                                      for claim in request.gold_claims]
            return {"outcome": "answered", "claims": claims, "text": "g", "usage": {"input_units": 1, "output_units": 1}, "model_id": None,
                    "features": {"fk_grade": grades.get(request.unit, 0) + (1 if request.item_id == g_items[1] else 0),
                                 "guiding_questions": 1, "prerequisite_recaps": 0, "length": 100}}

    record = runner.execute_run(plan, Generator(), tmp_path / "e3")
    tests = record["registered_tests"]["hypotheses"]
    assert tests["H3a"] == {"endpoint": tests["H3a"]["endpoint"], "comparison": ["two-pass", "single-pass"], "test": "mcnemar_exact",
                            **statistics.mcnemar_exact([False, False], [True, False]), "items": 2}
    assert record["metrics"]["IV"]["two-pass"]["rate"] == 0.0 and record["metrics"]["IV"]["single-pass"]["rate"] == 0.5
    friedman = statistics.friedman([[5.0, 8.0, 12.0], [6.0, 9.0, 13.0]])
    assert {key: tests["H3b"][key] for key in friedman} == friedman and tests["H3b"]["feature"] == "fk_grade"
    assert record["metrics"]["two_pass_lock_kept"] == {"items": 2, "kept": 2}
    assert record["replicate_variance"]["single-pass"]["violations"]["successes"] == 0


E4_MODELS = [{"model_id": "model-a", "family": "family-a", "price_per_input_unit": "0.001", "price_per_output_unit": "0.002", "local": False},
             {"model_id": "model-b", "family": "family-b", "price_per_input_unit": "0.0005", "price_per_output_unit": "0.0015", "local": False},
             {"model_id": "model-c", "family": "family-c", "price_per_input_unit": "0.001", "price_per_output_unit": "0.003", "local": False},
             {"model_id": "model-l", "family": "local", "price_per_input_unit": "0.0004", "price_per_output_unit": "0.0006", "local": True}]
LATER_PRICE = {"from": "2099-01-01", "price_per_input_unit": "0.002", "price_per_output_unit": "0.004"}


# A shift the scripted E4 tests can carry: model-b fails the GATE first pass of SYN-G-001 (rule `_fails_g`), not SYN-G-002's.
SHIFT_G = {"model": "model-b", "topic": "invented topic g", "at": 20}


def _fails_g(request) -> bool:
    return request.cell == "model-b" and request.arm == "GATE" and request.item_id == "SYN-G-001"


def _e4_spec(tmp_path, monkeypatch, **changes):
    _gate_passed(monkeypatch)
    items_path, catalog_path, items = synthetic.write_fixture_set(tmp_path, synthetic.SMALL, splits=True)
    # The shift is one the streams' population can carry: under the stub, model-b fails some but not every first pass in
    # this topic among the items left after the commissioning hold-out (`experiments.shift_injection`).
    topic = "invented topic c"
    assert any(item["topic"] == topic for item in items)
    design = {"models": E4_MODELS, "pilot_commercial": "model-b", "streams": 4, "stream_length": 40, "commissioning_items": 4,
              "shift": {"model": "model-b", "topic": topic, "at": 20}, **changes}
    spec = synthetic.spec_dict(items_path=items_path, catalog_path=catalog_path, purpose="confirmatory", experiment="E4", family="E4",
                               run_id="synthetic-e4-v1", design=design)
    return spec, items


def test_e4_answers_every_unit_with_four_models_in_gate_and_vloop_and_tests_h4a_and_h4b(tmp_path, monkeypatch):
    # VBT RevB Sec. VIII-D E4: "All four models answer all items in arms GATE and VLOOP"; "1,000 seeded streams of 2,000
    # requests compare the proposed controller, with and without hysteresis, against static-best, round-robin rotation,
    # cheapest-eligible, epsilon-greedy, a LinUCB-style bandit ... and threshold escalation"; Table I H4b "Exact McNemar"
    # on the local and the pilot-selected commercial model's error rates without verification (GATE).
    from evaluation.qcai_eval import experiments, statistics

    spec, items = _e4_spec(tmp_path, monkeypatch, shift=SHIFT_G)
    plan = runner.plan_run(spec)
    check = runner.plan_run(small_spec(tmp_path / "check")[0])
    units = {(r.item_id, r.unit, r.replicate) for r in check.requests if r.arm == "GATE"}
    for model in ("model-a", "model-b", "model-c", "model-l"):
        for arm in ("GATE", "VLOOP"):
            assert {(r.item_id, r.unit, r.replicate) for r in plan.requests if r.cell == model and r.arm == arm} == units
    assert len(plan.requests) == 8 * len(units) and len({r.request_key for r in plan.requests}) == len(plan.requests)
    errors = {"model-l": {"SYN-A-001", "SYN-B-002", "SYN-G-001"}, "model-b": {"SYN-G-001"}}

    def rule(request):
        if request.gold == "abstain":
            return "abstained", []
        return "answered", ["fabricated" if request.arm == "GATE" and request.item_id in errors.get(request.cell, ()) else "supported"]

    record = runner.execute_run(plan, _scripted(rule), tmp_path / "e4")
    h4b = record["registered_tests"]["hypotheses"]["H4b"]
    expected = statistics.mcnemar_exact([item in errors["model-l"] for item in ANSWERABLE], [item in errors["model-b"] for item in ANSWERABLE])
    assert {key: h4b[key] for key in expected} == expected and h4b["items"] == 9 and h4b["tost"]["status"] == "awaiting_ratings"
    h4a = record["registered_tests"]["hypotheses"]["H4a"]
    assert h4a["streams"] == 4 and h4a["stream_length"] == 40 and 0.0 <= h4a["p_value"] <= 1.0
    # model-b fails SYN-G-001's three GATE units and passes SYN-G-002's: base error 1/2, so the ten points inject at 0.2.
    assert h4a["shift"]["rate"] == pytest.approx(0.2) and h4a["detection"]["shift_rate"] == pytest.approx(0.2)
    # Four commissioning items cannot earn rating B (its 5% trust bound of 0.90 needs 28 clean first passes), so the
    # controller and cheapest-eligible abstain on every request and only the six other policies report a quality per price.
    assert set(h4a["quality_per_price"]) == set(experiments.POLICIES) - {"controller", "controller-no-hysteresis", "cheapest-eligible"}
    assert h4a["commissioning"]["items"] == 4 and set(h4a["commissioning"]["models"]) == set(PRICE)
    assert record["registered_tests"]["holm"] == statistics.holm({"H4a": h4a["p_value"], "H4b": h4b["p_value"]})
    # Every delivered answer is clean and every abstention delivers nothing: the local model, the cheapest, is static-best.
    population, excluded, prices = experiments._replay_population(plan, read_jsonl(tmp_path / "e4" / "responses.jsonl"))
    assert excluded == 0 and len(population) == len({(item, unit) for item, unit, _r in units})
    stream = experiments._replay_stream(plan, population, sorted(population, key=lambda u: (u[0], u[1] or "")), sorted(prices), "unit-test", commission=COMMISSION)
    assert stream["static_best"] == "model-l" and stream["policies"]["static-best"] == stream["policies"]["cheapest-eligible"]
    assert "at_later_prices" not in h4a
    # "at both Gemini prices if runs straddle 1 January 2027": a model's later list price replays H4a again beside it.
    later = [{**entry, "later_price": LATER_PRICE} if entry["model_id"] == "model-b" else entry for entry in E4_MODELS]
    spec_later = {**spec, "design": {**spec["design"], "models": later}}
    plan_later = runner.plan_run(spec_later)
    record_later = runner.execute_run(plan_later, _scripted(rule), tmp_path / "e4-later")
    at_later = record_later["registered_tests"]["hypotheses"]["H4a"]["at_later_prices"]
    assert at_later["later_price"] == {"model-b": LATER_PRICE} and at_later["enters_holm"] is False
    assert experiments._replay_population(plan_later, read_jsonl(tmp_path / "e4-later" / "responses.jsonl"), later=True)[2] == {
        **prices, "model-b": (0.002, 0.004)}
    assert record_later["registered_tests"]["holm"] == record["registered_tests"]["holm"]
    with pytest.raises(runner.RunRefused) as refused:
        runner.plan_run({**spec, "design": {**spec["design"], "models": [{**later[1], "later_price": {"from": "soon", "price_per_input_unit": "1", "price_per_output_unit": "1"}},
                                                                          *E4_MODELS[:1], *E4_MODELS[2:]]}})
    assert refused.value.reasons == ["design.models"]


def test_e4_policies_route_by_their_rules_and_the_shift_resamples_the_degraded_model_s_failures(tmp_path, monkeypatch):
    # "At request 1,000, one model's first-pass error rate in one topic is raised by ten percentage points by resampling
    # its own recorded failed responses": here at request 0 by 50 points over a topic where model-b fails half the time.
    from evaluation.qcai_eval import experiments

    spec, _items = _e4_spec(tmp_path, monkeypatch, stream_length=8,
                            shift={"model": "model-b", "topic": "invented topic a", "at": 0, "points": "0.5"})
    plan = runner.plan_run(spec)
    price = {"model-a": 0.003, "model-b": 0.002, "model-c": 0.004, "model-l": 0.001}
    clean = {model: experiments.Outcome(y=1, quality=1.0, cost=price[model], first_cost=price[model]) for model in price}
    failed = {model: experiments.Outcome(y=0, quality=0.0, cost=price[model], first_cost=price[model]) for model in price}
    population = {("SYN-A-001", None): {"topic": "invented topic a", "outcomes": {**clean, "model-l": failed["model-l"]}},
                  ("SYN-A-002", None): {"topic": "invented topic a", "outcomes": {**clean, "model-b": failed["model-b"]}},
                  ("SYN-B-001", None): {"topic": "invented topic b", "outcomes": clean}}
    result = experiments._replay_stream(plan, population, sorted(population), sorted(price), "policy-test", commission=COMMISSION)
    assert result["shift_rate"] == 1.0  # 0.5 points over a base error of 1/2: every clean model-b outcome in topic a fails
    policies = result["policies"]
    # Over the pool, quality per price: l 2/0.003, a 3/0.009, b 2/0.006, c 3/0.012, so static-best is the local model.
    assert result["static_best"] == "model-l"
    assert policies["cheapest-eligible"]["cost"] == pytest.approx(8 * 0.001)
    assert policies["round-robin"]["cost"] == pytest.approx(2 * sum(price.values()))  # a, b, c, l twice each
    # Escalation pays every first pass that fails on the way up: never less than the cheapest model's cost.
    assert policies["threshold-escalation"]["cost"] >= policies["cheapest-eligible"]["cost"]
    assert policies["threshold-escalation"]["verified_quality"] >= policies["cheapest-eligible"]["verified_quality"]
    for policy in ("controller", "controller-no-hysteresis"):
        assert {"detection_delay", "switches", "alarms"} <= set(policies[policy]), policy
    # Every request on SYN-A-001: l fails its first pass (0.001 paid), b's clean outcome is shifted to a failure (0.002
    # paid), a passes and delivers (0.003): 0.006 and one verified answer per request.
    # Static-best is chosen on the pool before the shift (b: 1/0.002), so after it static-best delivers nothing.
    single = experiments._replay_stream(plan, population, [("SYN-A-001", None)], sorted(price), "policy-test", commission=COMMISSION)
    one = single["policies"]
    assert one["threshold-escalation"]["cost"] == pytest.approx(8 * 0.006) and one["threshold-escalation"]["verified_quality"] == 8.0
    assert single["static_best"] == "model-b" and one["static-best"]["verified_quality"] == 0.0
    assert one["cheapest-eligible"]["verified_quality"] == 0.0


@pytest.mark.parametrize("experiment", ["E2", "E3", "E4"])
def test_each_design_run_repeats_byte_identically(tmp_path, monkeypatch, experiment):
    # AC-10-3 for the E2, E3 and E4 designs: a stub run repeats byte for byte (the run record and the payload log).
    if experiment == "E2":
        spec, _source = _e2_spec(tmp_path, monkeypatch)
    elif experiment == "E3":
        _gate_passed(monkeypatch)
        spec, _items = _confirmatory(tmp_path, "E3", design={})
    else:
        spec, _items = _e4_spec(tmp_path, monkeypatch)
    outputs = []
    for name in ("first", "second"):
        record = runner.execute_run(runner.plan_run(spec), StubResponder(), tmp_path / name)
        outputs.append([(tmp_path / name / file).read_bytes() for file in ("run_record.json", "payload_log.jsonl")])
        assert record["experiment"] == experiment and record["registered_tests"]["family"] == experiment
        assert record["comparisons"] is None and record["bootstrap"] is None
    assert outputs[0] == outputs[1]
    lines = read_jsonl(tmp_path / "first" / "payload_log.jsonl")
    assert {line["role"] for line in lines} <= {"answer", "verify", "two-pass-evidential", "two-pass", "single-pass"}


@pytest.mark.parametrize(("experiment", "change", "reason"), [
    ("E4", {"pilot_commercial": "model-l"}, "e4_models_invalid"),
    ("E4", {"models": E4_MODELS[:3]}, "e4_models_invalid"),
    ("E4", {"shift": {"model": "model-z", "topic": "invented topic a"}}, "e4_shift_invalid"),
    ("E4", {"shift": {"model": "model-b", "topic": "invented topic a", "points": "2"}}, "design.shift"),
    ("E3", {"fixed_level": "expert"}, "design.fixed_level"),
])
def test_a_design_block_that_cannot_run_is_refused_with_exit_2(tmp_path, monkeypatch, experiment, change, reason):
    if experiment == "E4":
        spec, _items = _e4_spec(tmp_path, monkeypatch, **change)
    else:
        _gate_passed(monkeypatch)
        spec, _items = _confirmatory(tmp_path, "E3", design=change)
    with pytest.raises(runner.RunRefused) as refused:
        runner.plan_run(spec)
    assert refused.value.code == 2 and refused.value.reasons == [reason]


@pytest.mark.parametrize("experiment", ["E3", "E4"])
def test_a_design_whose_arms_are_not_selected_is_refused(tmp_path, monkeypatch, experiment):
    # E3 runs in the pinned arm (VLOOP, PD-75) and E4 in GATE and VLOOP; parity covers the selected arms only.
    if experiment == "E4":
        spec, _items = _e4_spec(tmp_path, monkeypatch)
    else:
        _gate_passed(monkeypatch)
        spec, _items = _confirmatory(tmp_path, "E3", design={})
    with pytest.raises(runner.RunRefused) as refused:
        runner.plan_run({**spec, "arms": {**spec["arms"], "selected": ["NR", "LEX", "SEM", "GATE", "GATE+SV", "GATE+V1"]}})
    assert refused.value.code == 2 and refused.value.reasons == ["experiment_requires_arms"]


# ------------------------------------------------------------------------------------------------ the designs' known answers


def _repin(path, lines):
    from evaluation.qcai_eval.canonical import lf_sha256

    synthetic.write_jsonl(path, lines)
    return {"path": str(path), "sha256": lf_sha256(path)}


def test_the_registered_protocol_values_are_the_harness_defaults(tmp_path):
    # VBT RevB Sec. VIII-D: "Single-pass generation is also repeated three times"; "1,000 seeded streams of 2,000 requests
    # ... At request 1,000, one model's first-pass error rate in one topic is raised by ten percentage points".
    # The registered values are the analysis plans' `protocol.design` (review 26: in the plans the OSF record pins).
    from evaluation.qcai_eval import analysis_plans, experiments

    defaults = runner.load_harness_parameters()["designs"]
    families = analysis_plans.load_plans()["families"]
    registered = {name: families[name]["protocol"]["design"] for name in ("E3", "E4")}
    assert all("design" not in families[name]["protocol"] for name in ("E1", "E2"))
    assert registered == {"E3": {"repeats": defaults["E3"]["repeats"]},
                          "E4": {"streams": defaults["E4"]["streams"], "stream_length": defaults["E4"]["stream_length"],
                                 "shift.at": defaults["E4"]["shift_at"], "shift.points": defaults["E4"]["shift_points"]}}
    assert registered["E4"] == {"streams": 1000, "stream_length": 2000, "shift.at": 1000, "shift.points": "0.10"}
    # The runner judges a design against the family's registered protocol, the plans' values.
    design = {"repeats": 2}
    assert experiments.departures("E3", design, families["E3"]) == [{"field": "design.repeats", "registered": 3, "effective": 2}]
    assert experiments.departures("E3", design, {**families["E3"], "protocol": {"execution": {}, "design": {"repeats": 2}}}) == []
    # VBT RevB Sec. VII's "30-item pilot plus the golden set (80 items)" are not ULQS items: the hold-out of 80 run items in
    # their place is a provisional engineering default, not a registered value, and the streams keep at least 120 items
    # (AC-10-1's smallest ULQS, "120-200 items across S1-S7").
    assert (defaults["E4"]["commissioning_items"], defaults["E4"]["min_stream_items"]) == (80, 120)
    # The floor is always the harness parameters': a spec's value (which the shape check refuses) never replaces it.
    design = {"models": E4_MODELS, "pilot_commercial": "model-b", "shift": {"model": "model-b", "topic": "t"}, "min_stream_items": 1}
    assert experiments.effective_design("E4", design, runner.load_harness_parameters())["min_stream_items"] == 120
    # A harness parameters file whose streams' floor is missing or not a positive integer is refused when it is loaded.
    raw = json.loads(runner.HARNESS_PARAMETERS.read_text(encoding="utf-8"))
    for value in (None, 0, "120", True):
        edited = json.loads(json.dumps(raw))
        if value is None:
            edited["designs"]["E4"].pop("min_stream_items")
        else:
            edited["designs"]["E4"]["min_stream_items"] = value
        path = tmp_path / "harness_parameters.json"
        path.write_text(json.dumps(edited), encoding="utf-8")
        with pytest.raises(ValueError, match="min_stream_items"):
            runner.load_harness_parameters(path)


def test_a_design_default_taken_from_the_harness_parameters_is_named_in_the_record_s_used_for(tmp_path, monkeypatch):
    # pins.harness_parameters {sha256, used_for}: `designs` when an E2-E4 design took any value from the file's designs block.
    from evaluation.qcai_eval import experiments

    spec, _items = _e4_spec(tmp_path, monkeypatch)  # epsilon, linucb_alpha and shift.points left to the file
    plan = runner.plan_run(spec)
    assert experiments.defaults_taken("E4", spec["design"]) == ["epsilon", "linucb_alpha", "shift.points"]
    assert plan.pins["harness_parameters"]["used_for"] == ["designs"]
    assert plan.pins["design"]["commissioning_items"] == 4
    assert plan.pins["design"]["epsilon"] == runner.load_harness_parameters()["designs"]["E4"]["epsilon"]
    full = {**spec["design"], "epsilon": "0.1", "linucb_alpha": "1", "shift": {**spec["design"]["shift"], "points": "0.10"}}
    assert experiments.defaults_taken("E4", full) == []
    assert runner.plan_run({**spec, "design": full}).pins["harness_parameters"]["used_for"] == []
    no_replicates = {key: value for key, value in spec.items() if key != "retries"}
    assert runner.plan_run(no_replicates).pins["harness_parameters"]["used_for"] == ["designs", "retries"]


def test_a_design_that_departs_from_the_registered_protocol_is_refused_over_research_data_and_live_and_named_when_synthetic(
        tmp_path, monkeypatch):
    # Analysis plan H2a and H2b "resamples": 10000; E4's 1,000 streams of 2,000 requests and the shift at request 1,000;
    # over research data, E4's streams keep at least 120 items after the commissioning hold-out (a provisional floor).
    from evaluation.qcai_eval import planes

    spec, _items = _e4_spec(tmp_path, monkeypatch)
    record = runner.execute_run(runner.plan_run(spec), StubResponder(), tmp_path / "e4")
    expected = [{"field": "design.streams", "registered": 1000, "effective": 4},
                {"field": "design.stream_length", "registered": 2000, "effective": 40},
                {"field": "design.shift.at", "registered": 1000, "effective": 20}]
    assert record["pins"]["design"]["departures"] == expected
    # The synthetic spec's 2-item subsample departs from the paper's 40 too (E4's `protocol.execution`): the family
    # lists the design's departures, then the execution protocol's.
    execution = [{"field": "replicates.subsample.size", "registered": 40, "effective": 2}]
    assert record["pins"]["execution"]["departures"] == execution
    assert record["registered_tests"]["protocol"] == "departs_from_registration"
    assert record["registered_tests"]["departures"] == expected + execution
    e2, _source = _e2_spec(tmp_path / "e2", monkeypatch)
    assert runner.plan_run(e2).pins["design"]["departures"] == [
        {"field": "design.resamples", "hypothesis": name, "registered": 10000, "effective": 400} for name in ("H2a", "H2b")]
    # A live run departs from nothing: refused before the live checks.
    with pytest.raises(runner.RunRefused) as refused:
        runner.plan_run({**spec, "mode": "live", "responder": {"live": {"adapter": "none"}}})
    assert refused.value.code == 2 and refused.value.reasons == [
        "design_departs_from_registration:design.streams", "design_departs_from_registration:design.stream_length",
        "design_departs_from_registration:design.shift.at", "design_departs_from_registration:replicates.subsample.size"]
    # Over research data the departure is refused, and the registered values pass on to hold H12.
    monkeypatch.setattr(planes, "all_synthetic", lambda items: False)
    with pytest.raises(runner.RunRefused) as refused:
        runner.plan_run(spec)
    assert refused.value.code == 2 and refused.value.reasons[0] == "design_departs_from_registration:design.streams"
    small = spec["replicates"]
    spec = {**spec, "replicates": {**small, "subsample": {**small["subsample"], "size": 40}}}
    registered = {key: value for key, value in spec["design"].items() if key not in ("streams", "stream_length")}
    registered["shift"] = {"model": "model-b", "topic": spec["design"]["shift"]["topic"]}
    # A registered design whose replicate subsample alone departs is refused for that departure alone.
    with pytest.raises(runner.RunRefused) as refused:
        runner.plan_run({**spec, "design": registered, "replicates": small})
    assert refused.value.code == 2 and refused.value.reasons == ["design_departs_from_registration:replicates.subsample.size"]
    # The 14 items less the four commissioning items leave 10 for the streams: below the floor of 120 they are refused;
    # at a floor of 10 the registered values pass on to hold H12, and at 11 they are refused again.
    with pytest.raises(runner.RunRefused) as refused:
        runner.plan_run({**spec, "design": registered})
    assert refused.value.code == 2 and refused.value.reasons == ["e4_stream_items_below_floor"]
    load = runner.load_harness_parameters

    def floor_at(value):
        def patched(*args, **kwargs):
            raw = load(*args, **kwargs)
            raw["designs"]["E4"]["min_stream_items"] = value
            return raw
        return patched

    monkeypatch.setattr(runner, "load_harness_parameters", floor_at(10))
    with pytest.raises(runner.RunRefused) as refused:
        runner.plan_run({**spec, "design": registered})
    assert refused.value.code == 9 and refused.value.reasons == ["hold_h12_data_plane"]
    monkeypatch.setattr(runner, "load_harness_parameters", floor_at(11))
    with pytest.raises(runner.RunRefused) as refused:
        runner.plan_run({**spec, "design": registered})
    assert refused.value.code == 2 and refused.value.reasons == ["e4_stream_items_below_floor"]
    monkeypatch.setattr(runner, "load_harness_parameters", floor_at(10))
    with pytest.raises(runner.RunRefused) as refused:
        runner.plan_run({**spec, "design": {**registered, "shift": {**registered["shift"], "points": "0.2"}}})
    assert refused.value.reasons == ["design_departs_from_registration:design.shift.points"]


def test_e2_h2a_and_h2c_are_the_registered_bootstraps_of_the_hand_built_panel(tmp_path, monkeypatch):
    # Table I H2a: F1 of the 2oo3 panel minus the best single verifier's, a one-sided cluster BCa bootstrap over items;
    # H2c: the paired AUC bootstrap of the panel against the novices' trust (lower trust: more likely erroneous).
    from evaluation.qcai_eval import experiments, statistics
    from evaluation.qcai_eval.canonical import canonical_sha256

    spec, source = _e2_spec(tmp_path, monkeypatch)
    keys = [line["request_key"] for line in source if line["replicate"] == 1 and line["outcome"] == "answered" and line["claims"]]
    gold = {canonical_sha256({"source": "E1", "request_key": line["request_key"], "claim_id": claim["claim_id"]}):
            (line["request_key"], line["item_id"], claim["label"] in experiments.ERROR_LABELS, position) for line in source
            if line["replicate"] == 1 and line["outcome"] == "answered" for position, claim in enumerate(line["claims"])}
    assert any(position for _key, _item, _error, position in gold.values())  # some responses hold more than one claim
    trust = {key: 2.0 if index % 3 == 0 else 4.0 + index % 2 for index, key in enumerate(sorted(keys))}
    ratings = _repin(tmp_path / "trust.jsonl", [{"rating": "novice-trust", "source_request_key": key, "value": value}
                                               for key, value in sorted(trust.items())])
    spec = {**spec, "design": {**spec["design"], "ratings": ratings}}

    def flags(subject):  # a: the erroneous claims of items before D; b: every erroneous claim, every claim of A items and each
        _key, item, error, position = gold[subject]  # response's second claim; c: the erroneous claims of items from B on and
        second = position == 1  # each response's second claim (so a response's largest objecting share is not its smallest)
        return (error and item < "SYN-D", error or item < "SYN-B" or second, (error and item >= "SYN-B") or second)

    class Verifiers:
        rule = "scripted-verifiers"

        def respond(self, request):
            flag = flags(request.subject)[("verifier-a", "verifier-b", "verifier-c").index(request.cell)]
            return {"outcome": "answered", "verdict": "object" if flag else "pass", "claims": [], "text": "v",
                    "usage": {"input_units": 1, "output_units": 1}, "model_id": None}

    record = runner.execute_run(runner.plan_run(spec), Verifiers(), tmp_path / "e2")
    hypotheses = record["registered_tests"]["hypotheses"]

    def f1(rows):
        tp = sum(1 for g, f in rows if g and f)
        wrong = sum(1 for g, f in rows if g != f)
        return 0.0 if tp == 0 else 2 * tp / (2 * tp + wrong)

    def advantage(chosen):
        rows = [row for cluster in chosen for row in cluster]
        return f1([(g, sum(f) >= 2) for g, f in rows]) - max(f1([(g, f[j]) for g, f in rows]) for j in range(3))

    by_item = {}
    for subject, (_key, item, error, _position) in sorted(gold.items()):
        by_item.setdefault(item, []).append((error, flags(subject)))
    clusters = [by_item[item] for item in sorted(by_item)]
    assert advantage(clusters) != 0  # a and c miss errors, b and c object to correct claims: the panel and its best member differ
    expected = statistics.cluster_bootstrap_bca_one_sided(clusters, advantage, resamples=400,
                                                          seed=hashed_hex(spec["run_id"], "registered", "H2a"), margin="0")
    h2a = hypotheses["H2a"]
    assert h2a["estimate"] == pytest.approx(advantage(clusters)) and h2a["margin"] == "0"
    for key, value in expected.items():
        assert h2a[key] == (pytest.approx(value) if isinstance(value, float) else value), key
    # H2c from the pinned trust ratings: per response, the largest share of members objecting to one of its claims.
    by_response = {}
    for subject, (key, _item, error, _position) in gold.items():
        by_response.setdefault(key, []).append((error, sum(flags(subject)) / 3))
    rated = sorted(set(by_response) & set(trust))
    expected = statistics.paired_bootstrap_auc_one_sided([any(g for g, _s in by_response[key]) for key in rated],
                                                         [max(s for _g, s in by_response[key]) for key in rated],
                                                         [-trust[key] for key in rated], resamples=400,
                                                         seed=hashed_hex(spec["run_id"], "registered", "H2c"), margin="0")
    assert hypotheses["H2c"]["responses"] == len(rated)
    for key, value in expected.items():
        assert hypotheses["H2c"][key] == (pytest.approx(value) if isinstance(value, float) else value), key
    assert record["registered_tests"]["pending"] == []


@pytest.mark.parametrize(("experiment", "rows"), [
    ("E2", [{"rating": "eqc", "source_request_key": "k", "value": 3}]),
    ("E2", [{"rating": "novice-trust", "source_request_key": "k", "value": 3, "rater": "r"}]),
    ("E4", [{"rating": "eqc", "source_request_key": "k", "value": True}]),
    ("E4", [{"rating": "novice-trust", "source_request_key": "k", "value": 3}]),
    # A value the statistics cannot read as a finite float: refused here, never an OverflowError after the run.
    ("E4", [{"rating": "eqc", "source_request_key": "k", "value": 10 ** 400}]),
    ("E4", [{"rating": "eqc", "source_request_key": "k", "value": float("inf")}]),
    ("E4", [{"rating": "eqc", "source_request_key": "k", "value": float("nan")}]),
    ("E2", [{"rating": "novice-trust", "source_request_key": "k", "value": 10 ** 400}]),
    ("E2", [{"rating": "novice-trust", "source_request_key": "k", "value": float("-inf")}]),
])
def test_a_ratings_file_that_is_not_the_design_s_ratings_is_refused_with_exit_3(tmp_path, monkeypatch, experiment, rows):
    ratings = _repin(tmp_path / "ratings.jsonl", rows)
    if experiment == "E2":
        spec, _source = _e2_spec(tmp_path, monkeypatch, ratings=ratings)
    else:
        spec, _items = _e4_spec(tmp_path, monkeypatch, ratings=ratings)
    with pytest.raises(runner.RunRefused) as refused:
        runner.plan_run(spec)
    assert refused.value.code == 3 and refused.value.reasons == ["ratings_invalid"]


def _verification_edit(kind, lines):
    labelled = next(line for line in lines if line["replicate"] == 1 and line["outcome"] == "answered" and line["claims"])
    if kind == "cited":
        labelled["claims"][0]["cited"] = 5
    elif kind == "claims":
        labelled["claims"] = "x"
    elif kind == "replicate":
        labelled["replicate"] = "1"
    elif kind == "unit":
        labelled["unit"] = 3
    elif kind == "item":
        labelled["item_id"] = "SYN-A-999"
    elif kind == "item_list":
        labelled["item_id"] = [labelled["item_id"]]  # unhashable: refused, never a TypeError from the set membership test
    elif kind == "unlabelled":
        for line in lines:
            for claim in line["claims"]:
                claim["label"] = None
    return lines


@pytest.mark.parametrize(("kind", "code", "reason"), [
    ("cited", 3, "verification_set_invalid"), ("claims", 3, "verification_set_invalid"), ("replicate", 3, "verification_set_invalid"),
    ("unit", 3, "verification_set_invalid"), ("item", 3, "verification_set_items"), ("item_list", 3, "verification_set_items"),
    ("unlabelled", 2, "verification_set_empty"),
])
def test_e2_refuses_a_verification_set_it_cannot_read_as_labelled_claims(tmp_path, monkeypatch, kind, code, reason):
    spec, source = _e2_spec(tmp_path, monkeypatch)
    pinned = _repin(tmp_path / "edited.jsonl", _verification_edit(kind, source))
    with pytest.raises(runner.RunRefused) as refused:
        runner.plan_run({**spec, "design": {**spec["design"], "verification_set": {**spec["design"]["verification_set"], **pinned}}})
    assert refused.value.code == code and refused.value.reasons == [reason]


VERIFIER_MODELS = [{**E4_MODELS[0], "model_id": "verifier-a"}, {**E4_MODELS[1], "model_id": "verifier-b"},
                   {**E4_MODELS[2], "model_id": "verifier-c"}, {**E4_MODELS[3], "model_id": "verifier-g", "family": "family-g"}]


def _e4_responses_for_e2(tmp_path, monkeypatch):
    """An E4 stub run whose four models are E2's four verifiers (the paper's four models), pinned for E2."""
    spec, items = _e4_spec(tmp_path / "e4in", monkeypatch, models=VERIFIER_MODELS, pilot_commercial="verifier-b")
    spec["design"]["shift"]["model"] = "verifier-b"
    runner.execute_run(runner.plan_run(spec), StubResponder(), tmp_path / "e4out")
    lines = read_jsonl(tmp_path / "e4out" / "responses.jsonl")
    return _repin(tmp_path / "e4.jsonl", lines), lines


def test_e2_verifies_e4_claims_outside_each_generator_s_family_and_refuses_an_unknown_generator(tmp_path, monkeypatch):
    # VBT RevB Sec. VIII-D E2: the verification set takes the human-labelled claims of E1 and E4; "Each model verifies
    # every claim generated outside its own provider family".
    e4, lines = _e4_responses_for_e2(tmp_path, monkeypatch)
    spec, _source = _e2_spec(tmp_path, monkeypatch, e4_responses=e4)
    plan = runner.plan_run(spec)
    claims = [claim for claim in plan.extra["design"]["claims"] if claim.source == "E4"]
    expected = sum(1 for line in lines if line["replicate"] == 1 and line["outcome"] == "answered" for claim in line["claims"]
                   if claim["label"] is not None)
    assert len(claims) == expected > 0
    family = {"verifier-a": "family-a", "verifier-b": "family-b", "verifier-c": "family-c", "verifier-g": "family-g"}
    assert {claim.family for claim in claims} == set(family.values())
    for claim in claims:
        cells = {request.cell for request in plan.requests if request.subject == claim.key}
        assert cells == {verifier for verifier in family if family[verifier] != claim.family}, claim.family
    record = runner.execute_run(plan, StubResponder(), tmp_path / "e2")
    assert record["metrics"]["verification_set"]["by_source"]["E4"] == expected
    unknown = _repin(tmp_path / "unknown.jsonl", [{**line, "cell": "model-z"} for line in lines])
    with pytest.raises(runner.RunRefused) as refused:
        runner.plan_run({**spec, "design": {**spec["design"], "e4_responses": unknown}})
    assert refused.value.code == 3 and refused.value.reasons == ["e4_responses_generator_unknown"]
    broken = _repin(tmp_path / "broken.jsonl", _verification_edit("cited", lines))
    with pytest.raises(runner.RunRefused) as refused:
        runner.plan_run({**spec, "design": {**spec["design"], "e4_responses": broken}})
    assert refused.value.code == 3 and refused.value.reasons == ["e4_responses_invalid"]


def test_e3_with_no_live_s7_item_is_refused_and_e3_needs_no_replicate_subsample(tmp_path, monkeypatch):
    _gate_passed(monkeypatch)
    items_path, catalog_path, _items = synthetic.write_fixture_set(tmp_path, {**synthetic.SMALL, "G": 0}, splits=True)
    spec = synthetic.spec_dict(items_path=items_path, catalog_path=catalog_path, purpose="confirmatory", experiment="E3", family="E3",
                               run_id="synthetic-e3-v1", design={})
    with pytest.raises(runner.RunRefused) as refused:
        runner.plan_run(spec)
    assert refused.value.code == 2 and refused.value.reasons == ["e3_no_s7_items"]
    # E3's replicate variance is its single-pass repeats; it uses no subsample, so a confirmatory E3 run needs none (E1 does).
    e3, _items = _confirmatory(tmp_path / "e3", "E3", design={})
    e1, _items = _confirmatory(tmp_path / "e1", "E1")
    for replicates, reason in (({"default": 1}, "replicate_subsample_required"),
                               ({"default": 1, "subsample": {"stratum": "A", "size": 99, "replicates": 3}}, "replicate_subsample_short")):
        plan = runner.plan_run({**e3, "replicates": replicates})
        assert {request.replicate for request in plan.requests if request.role != "single-pass"} == {1}
        with pytest.raises(runner.RunRefused) as refused:
            runner.plan_run({**e1, "replicates": replicates})
        assert refused.value.reasons == [reason]


def test_e3_two_pass_presentation_requests_are_sent_the_evidential_pass_s_locked_claims(tmp_path, monkeypatch):
    # VBT RevB Sec. VIII-D E3: "the evidential pass runs once per item and its locked claims are reused at every level".
    import hashlib

    from evaluation.qcai_eval.canonical import canonical_json

    _gate_passed(monkeypatch)
    spec, items = _confirmatory(tmp_path, "E3", design={})
    plan = runner.plan_run(spec)
    g_items = sorted(item["item_id"] for item in items if item["stratum"] == "G")
    evidential = {request.item_id: request.request_key for request in plan.requests if request.role == "two-pass-evidential"}
    assert all((request.depends_on == evidential[request.item_id]) == (request.role == "two-pass") for request in plan.requests)
    seen = []

    class Generator:
        rule = "scripted-e3"

        def respond(self, request):
            seen.append(request)
            if request.role == "two-pass-evidential" and request.item_id == g_items[1]:
                raise TransientFailure("timeout")
            if request.role == "two-pass":
                claims = [{"claim_id": claim_id, "cited": list(cited), "label": "supported", "ehmf_type": None}
                          for claim_id, cited in request.locked]
            else:
                claims = [{"claim_id": claim, "cited": list(request.evidence)[:1], "label": "supported", "ehmf_type": None}
                          for claim in request.gold_claims]
            return {"outcome": "answered", "claims": claims, "text": "g", "usage": {"input_units": 1, "output_units": 1}, "model_id": None}

    record = runner.execute_run(plan, Generator(), tmp_path / "e3")
    lines = {line["request_key"]: line for line in read_jsonl(tmp_path / "e3" / "responses.jsonl")}
    sent = [request for request in seen if request.role == "two-pass"]
    assert {request.item_id for request in sent} == {g_items[0]} and len(sent) == 3
    locked = runner.locked_claims(lines[evidential[g_items[0]]])
    assert locked and all(request.locked == locked for request in sent)
    for request in plan.requests:
        if request.role == "two-pass" and request.item_id == g_items[1]:
            line = lines[request.request_key]
            assert (line["outcome"], line["failure_reason"], line["attempts"]) == ("provider_failure", "evidential_pass_failed", [])
    assert record["metrics"]["IV"]["two-pass"]["excluded_items"] == 1
    assert record["slis"]["provider_failures"] == {"evidential_pass_failed": 3, "timeout": 1} and record["slis"]["retries"] == 3
    # The prompt envelope a two-pass request is logged with carries the locked claims.
    log = {line["request_key"]: line for line in read_jsonl(tmp_path / "e3" / "payload_log.jsonl")}
    request = sent[0]
    envelope = canonical_json({"prompt_version": plan.pins["prompt_version"], "item_id": request.item_id, "unit": request.unit,
                               "arm": request.arm, "evidence": list(request.evidence), "role": "two-pass", "cell": None, "subject": None,
                               "locked": [[claim_id, list(cited)] for claim_id, cited in locked]})
    assert log[request.request_key]["prompt_sha256"] == hashlib.sha256(envelope).hexdigest()
    # The stub's presentation pass answers with the locked claims, so its two-pass levels keep the evidential set.
    stub = runner.execute_run(plan, StubResponder(), tmp_path / "stub")
    kept = stub["metrics"]["two_pass_lock_kept"]
    assert kept["kept"] == kept["items"] > 0 and stub["metrics"]["IV"]["two-pass"]["successes"] == 0
    # A recording of the stub records each two-pass request as sent.
    if str(REPO_ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import run_evaluation

    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    assert run_evaluation.main(["--spec", str(spec_path), "--record-stub", str(tmp_path / "recording.jsonl")]) == 0
    recorded = {line["request_key"]: line["response"] for line in read_jsonl(tmp_path / "recording.jsonl")[1:]}
    for request in plan.requests:
        if request.role == "two-pass":
            pairs = runner.locked_claims(recorded[request.depends_on])
            assert [[c["claim_id"], c["cited"]] for c in recorded[request.request_key]["claims"]] == [[i, list(c)] for i, c in pairs]


def test_e3_records_its_exact_set_comparison_as_the_stand_in_for_entailment_and_lists_the_disagreements(tmp_path, monkeypatch):
    # VBT RevB Sec. VIII-D E3: "Claim sets are compared by bidirectional entailment with human checks on disagreements"
    # (PD-75's stand-in: exact claim-id and cited-span sets; DI-148).
    _gate_passed(monkeypatch)
    spec, items = _confirmatory(tmp_path, "E3", design={})
    g_items = sorted(item["item_id"] for item in items if item["stratum"] == "G")

    class Generator:
        rule = "scripted-e3"

        def respond(self, request):
            drop = request.role == "single-pass" and request.item_id == g_items[0] and request.unit == "advanced"
            pairs = request.locked if request.role == "two-pass" else [(claim, tuple(request.evidence)) for claim in request.gold_claims]
            claims = [] if drop else [{"claim_id": claim, "cited": list(cited), "label": "supported", "ehmf_type": None} for claim, cited in pairs]
            return {"outcome": "answered", "claims": claims, "text": "g", "usage": {"input_units": 1, "output_units": 1}, "model_id": None}

    record = runner.execute_run(runner.plan_run(spec), Generator(), tmp_path / "e3")
    comparison = record["metrics"]["claim_set_comparison"]
    assert comparison["rule"] == "claim-or-span-set-differs-v1" and "bidirectional entailment" in comparison["stands_in_for"]
    assert comparison["human_checks"] == "awaiting_human_checks"
    assert comparison["disagreements"] == {"two-pass": [], "single-pass": [g_items[0]]}


@pytest.mark.parametrize(("experiment", "change", "reason"), [
    ("E4", {"epsilon": "abc"}, "design.epsilon"), ("E4", {"epsilon": "2"}, "design.epsilon"), ("E4", {"epsilon": 0.1}, "design.epsilon"),
    ("E4", {"linucb_alpha": [1]}, "design.linucb_alpha"), ("E4", {"linucb_alpha": "-1"}, "design.linucb_alpha"),
    # Fraction-readable but not float-representable: refused here, never an OverflowError in the computation after the run.
    ("E4", {"linucb_alpha": "1e400"}, "design.linucb_alpha"),
    ("E4", {"local_cost": {"energy": "1e400", "amortized_hardware": "1"}}, "design.local_cost"),
    ("E4", {"models": [{**E4_MODELS[0], "price_per_input_unit": "1e400"}, *E4_MODELS[1:]]}, "design.models"),
    # Decimal-readable as the computation reads them: a rational form ("1/2") is refused, never a decimal.InvalidOperation.
    ("E4", {"models": [{**E4_MODELS[0], "price_per_input_unit": "1/2"}, *E4_MODELS[1:]]}, "design.models"),
    ("E4", {"models": [{**E4_MODELS[0], "later_price": {**LATER_PRICE, "price_per_output_unit": "1/3"}}, *E4_MODELS[1:]]},
     "design.models"),
    ("E4", {"local_cost": {"energy": "1/3", "amortized_hardware": "1"}}, "design.local_cost"),
    ("E4", {"local_cost": {"energy": "1", "amortized_hardware": "NaN"}}, "design.local_cost"),
    # Positive as a float too: "1e-400" underflows to 0.0 and is refused, never a division by a zero cost.
    ("E4", {"models": [{**E4_MODELS[0], "price_per_input_unit": "1e-400"}, *E4_MODELS[1:]]}, "design.models"),
    # At most PRICE_MAX: "1e306" would overflow the controller's exact cost-unit arithmetic after the run.
    ("E4", {"models": [{**E4_MODELS[0], "price_per_input_unit": "1e306"}, *E4_MODELS[1:]]}, "design.models"),
    ("E4", {"models": [{**E4_MODELS[0], "price_per_output_unit": "1000000.001"}, *E4_MODELS[1:]]}, "design.models"),
    ("E4", {"local_cost": {"energy": "x", "amortized_hardware": "1"}}, "design.local_cost"),
    ("E4", {"models": [{**E4_MODELS[0], "price_per_input_unit": "0"}, *E4_MODELS[1:]]}, "design.models"),
    ("E4", {"models": [{key: value for key, value in E4_MODELS[0].items() if key != "price_per_output_unit"}, *E4_MODELS[1:]]},
     "design.models"),
    ("E3", {"h3b_feature": ["x"]}, "design.h3b_feature"), ("E3", {"h3b_feature": "nope"}, "design.h3b_feature"),
    ("E3", {"arm": ["VLOOP"]}, "design.arm"), ("E3", {"arm": "XX"}, "design.arm"),
    ("E2", {"dawid_skene_iterations": "x"}, "design.dawid_skene_iterations"),
    ("E2", {"dawid_skene_iterations": 0}, "design.dawid_skene_iterations"),
    # The streams' floor is the harness parameters' (PD-75): a spec cannot lower it.
    ("E4", {"min_stream_items": 1}, "design.min_stream_items"),
])
def test_every_design_value_the_computation_reads_is_shape_checked_with_exit_2(tmp_path, monkeypatch, experiment, change, reason):
    if experiment == "E4":
        spec, _items = _e4_spec(tmp_path, monkeypatch, **change)
    elif experiment == "E2":
        spec, _source = _e2_spec(tmp_path, monkeypatch, **change)
    else:
        _gate_passed(monkeypatch)
        spec, _items = _confirmatory(tmp_path, "E3", design=change)
    with pytest.raises(runner.RunRefused) as refused:
        runner.plan_run(spec)
    assert refused.value.code == 2 and refused.value.reasons == [reason]


def test_e4_prices_at_the_shape_check_s_bounds_run_to_completion(tmp_path, monkeypatch):
    # The bounds the shape check admits are bounds the computation can use: every price at PRICE_MAX, or at the smallest
    # positive float, and a local cost in exponent form, run through the replay and the controller without an exception.
    from evaluation.qcai_eval import experiments

    for name, price in (("max", str(experiments.PRICE_MAX)), ("tiny", "5e-324")):
        models = [{**entry, "price_per_input_unit": price, "price_per_output_unit": price} for entry in E4_MODELS]
        spec, _items = _e4_spec(tmp_path / name, monkeypatch, models=models, epsilon="0.1", linucb_alpha="1", stream_length=20,
                                streams=2, local_cost={"energy": "1e3", "amortized_hardware": "0"})
        record = runner.execute_run(runner.plan_run(spec), StubResponder(), tmp_path / name / "run")
        assert record["metrics"]["local_cost"]["measured"]["total"] == "1000"


@pytest.mark.parametrize("experiment", ["E2", "E3", "E4"])
def test_no_malformed_design_value_ends_in_a_traceback_through_the_run(tmp_path, monkeypatch, experiment):
    # Every node of the design block replaced in turn by a value of the wrong type, or by a string open() refuses: the
    # planner refuses (RunRefused), or the run completes; any other exception would reach the CLI as a traceback.
    if experiment == "E2":
        base, _source = _e2_spec(tmp_path, monkeypatch, dawid_skene_iterations=5)
    elif experiment == "E3":
        _gate_passed(monkeypatch)
        base, _items = _confirmatory(tmp_path, "E3", design={"arm": "VLOOP", "fixed_level": "intermediate", "repeats": 3, "h3b_feature": "fk_grade"})
    else:
        base, _items = _e4_spec(tmp_path, monkeypatch, epsilon="0.1", linucb_alpha="1", stream_length=20, streams=2)
    runner.execute_run(runner.plan_run(base), StubResponder(), tmp_path / "base")
    runs = 0
    for path in list(_nodes(base["design"]))[1:]:
        for bad in ("x", [1], {"path": 1}, None, "a\x00b.jsonl", -1, "1/3", "1e-400", "1e306"):
            spec = json.loads(json.dumps(base))
            target = spec["design"]
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = bad
            try:
                plan = runner.plan_run(spec)
            except runner.RunRefused:
                continue
            runs += 1
            runner.execute_run(plan, StubResponder(), tmp_path / f"run-{runs}")  # a replacement that is a valid value runs


def test_e4_prices_input_and_output_units_at_their_list_prices_and_reports_the_local_cost_separately(tmp_path, monkeypatch):
    # VBT RevB Sec. VIII-D: "Cost is computed from logged tokens at the list prices in force on the run date (Table XIV) ...
    # local cost is reported separately as measured energy plus amortized hardware"; Table XIV prices input and output.
    from evaluation.qcai_eval import experiments

    assert experiments._cost({"usage": {"input_units": 3, "output_units": 5}}, (0.001, 0.002)) == pytest.approx(0.013)
    assert experiments._cost({"usage": {"input_units": 0, "output_units": 0}}, (0.001, 0.002)) == pytest.approx(0.003)
    spec, _items = _e4_spec(tmp_path, monkeypatch, local_cost={"energy": "1.25", "amortized_hardware": "0.75"})
    plan = runner.plan_run(spec)

    class Usage:
        rule = "usage"

        def respond(self, request):
            return {**StubResponder().respond(request), "usage": {"input_units": 10, "output_units": 2}}

    record = runner.execute_run(plan, Usage(), tmp_path / "e4")
    responses = {model: sum(1 for r in plan.requests if r.cell == model and r.replicate == 1) for model in ("model-a", "model-l")}
    cost = record["metrics"]["cost"]["model-a"]
    assert {key: cost[key] for key in ("responses", "input_units", "output_units", "basis")} == {
        "responses": responses["model-a"], "input_units": 10 * responses["model-a"], "output_units": 2 * responses["model-a"],
        "basis": "logged input and output units at the list prices"}
    assert cost["cost"] == pytest.approx(responses["model-a"] * (10 * 0.001 + 2 * 0.002))
    assert set(record["metrics"]["cost"]) == {"model-a", "model-b", "model-c"}
    local = record["metrics"]["local_cost"]
    assert local["model"] == "model-l" and local["measured"] == {"energy": "1.25", "amortized_hardware": "0.75", "total": "2.00"}
    assert local["cost"] == pytest.approx(responses["model-l"] * (10 * 0.0004 + 2 * 0.0006)) and "stand-in" in local["basis"]
    population, _excluded, prices = experiments._replay_population(plan, read_jsonl(tmp_path / "e4" / "responses.jsonl"))
    assert prices["model-a"] == (0.001, 0.002)
    assert all(unit["outcomes"]["model-c"].cost == pytest.approx(10 * 0.001 + 2 * 0.003) for unit in population.values())
    plain = runner.execute_run(runner.plan_run(_e4_spec(tmp_path / "plain", monkeypatch)[0]), StubResponder(), tmp_path / "plain-out")
    assert plain["metrics"]["local_cost"]["measured"]["status"] == "not_measured"
    # The base list price must be in force at the run's start: a later price already in effect is refused.
    past = [{**entry, "later_price": {**LATER_PRICE, "from": "2000-01-01"}} if entry["model_id"] == "model-b" else entry for entry in E4_MODELS]
    with pytest.raises(runner.RunRefused) as refused:
        runner.plan_run({**spec, "design": {**spec["design"], "models": past}})
    assert refused.value.code == 2 and refused.value.reasons == ["e4_later_price_in_force"]


def test_e4_reports_latency_as_median_and_95th_percentile_where_responses_record_it(tmp_path, monkeypatch):
    # VBT RevB Sec. VIII-D: "Latency is recorded as time to first token and total time (median and 95th percentile)."
    from evaluation.qcai_eval import experiments

    spec, _items = _e4_spec(tmp_path, monkeypatch)
    plan = runner.plan_run(spec)

    class Timed:
        rule = "timed"

        def respond(self, request):
            response = StubResponder().respond(request)
            if request.cell == "model-a" and request.arm == "GATE":
                slow = request.item_id == "SYN-A-001"
                response = {**response, "latency": {"first_token_ms": 70 if slow else 50, "total_ms": 900 if slow else 200}}
            return response

    record = runner.execute_run(plan, Timed(), tmp_path / "e4")
    units = sum(1 for r in plan.requests if r.cell == "model-a" and r.arm == "GATE" and r.replicate == 1)
    total = sorted([200] * (units - 1) + [900])
    latency = record["metrics"]["latency"]["model-a|GATE"]
    assert latency["time_to_first_token_ms"]["median"] == 50 and latency["total_time_ms"]["median"] == 200
    assert latency["total_time_ms"]["p95"] == total[-(-95 * units // 100) - 1] and latency["total_time_ms"]["n"] == units
    assert record["metrics"]["latency"]["model-a|VLOOP"]["status"] == "not_recorded"
    assert experiments._percentiles([1, 2, 3, 4]) == {"n": 4, "median": 2.5, "p95": 4, "rule": "median-and-nearest-rank-p95-v1"}
    assert experiments._percentiles(list(range(1, 41)))["p95"] == 38 and experiments._percentiles([7, 1, 3])["median"] == 3


def test_e4_gates_each_hypothesis_on_the_labels_it_reads(tmp_path, monkeypatch):
    # VBT RevB Sec. VIII-D: "Human claim labels for E4 cover at least the GATE responses of the local model and of the
    # pilot-selected commercial model, which H4b's error-rate comparison needs"; H4a's replay reads every cell.
    spec, _items = _e4_spec(tmp_path, monkeypatch, shift=SHIFT_G)
    plan = runner.plan_run(spec)

    def labelled_except(cell, arm):
        def rule(request):
            if request.gold == "abstain":
                return "abstained", []
            return "answered", [None if (request.cell, request.arm) == (cell, arm) else "fabricated" if _fails_g(request) else "supported"]
        return _scripted(rule)

    record = runner.execute_run(plan, labelled_except("model-c", "VLOOP"), tmp_path / "c")
    tests = record["registered_tests"]
    assert tests["hypotheses"]["H4a"]["status"] == "awaiting_labels" and "p_value" in tests["hypotheses"]["H4b"]
    assert tests["pending"] == ["H4a"] and record["metrics"]["cells"]["model-c|VLOOP"]["status"] == "awaiting_labels"
    assert "item_error_answerable" in record["metrics"]["cells"]["model-c|GATE"] and record["metrics"]["replay"]["status"] == "awaiting_labels"
    assert record["replicate_variance"]["model-c|VLOOP"] == {"status": "awaiting_labels"}
    assert "variance" in record["replicate_variance"]["model-c|GATE"]
    record = runner.execute_run(plan, labelled_except("model-l", "GATE"), tmp_path / "l")
    assert {name: value.get("status") for name, value in record["registered_tests"]["hypotheses"].items()} == {
        "H4a": "awaiting_labels", "H4b": "awaiting_labels"}
    record = runner.execute_run(plan, labelled_except("model-z", "GATE"), tmp_path / "all")
    assert record["registered_tests"]["pending"] == [] and "p_value" in record["registered_tests"]["hypotheses"]["H4a"]
    # The metrics read replicate 1 only: claims of replicates 2 and 3 left unlabelled in every cell hold neither hypothesis.
    assert any(request.replicate > 1 for request in plan.requests)

    def labelled_first_replicate(request):
        if request.gold == "abstain":
            return "abstained", []
        return "answered", [("fabricated" if _fails_g(request) else "supported") if request.replicate == 1 else None]

    record = runner.execute_run(plan, _scripted(labelled_first_replicate), tmp_path / "first")
    tests = record["registered_tests"]
    assert tests["pending"] == [] and "p_value" in tests["hypotheses"]["H4a"] and "p_value" in tests["hypotheses"]["H4b"]


def test_e4_h4b_s_tost_is_the_paired_tost_of_the_pinned_eqc_ratings(tmp_path, monkeypatch):
    from evaluation.qcai_eval import statistics

    spec, _items = _e4_spec(tmp_path, monkeypatch)
    plan = runner.plan_run(spec)
    vloop = sorted((r for r in plan.requests if r.arm == "VLOOP" and r.replicate == 1 and r.cell in ("model-l", "model-b")),
                   key=lambda r: (r.item_id, r.unit or "", r.cell))
    score = {r.request_key: 4.0 + (0.3 if r.cell == "model-b" else 0.0) + 0.1 * (index % 4) for index, r in enumerate(vloop)}
    ratings = _repin(tmp_path / "eqc.jsonl", [{"rating": "eqc", "source_request_key": key, "value": value} for key, value in score.items()])
    record = runner.execute_run(runner.plan_run({**spec, "design": {**spec["design"], "ratings": ratings}}), StubResponder(), tmp_path / "e4")
    units = sorted({(r.item_id, r.unit) for r in vloop}, key=lambda unit: (unit[0], unit[1] or ""))
    cell = {(r.item_id, r.unit, r.cell): score[r.request_key] for r in vloop}
    expected = statistics.paired_tost([cell[(i, u, "model-l")] for i, u in units], [cell[(i, u, "model-b")] for i, u in units], margin="0.5")
    tost = record["registered_tests"]["hypotheses"]["H4b"]["tost"]
    assert tost["pairs"] == len(units) and tost["confirmatory"] == "inconclusive" and tost["enters_holm"] is False
    for key, value in expected.items():
        assert tost[key] == (pytest.approx(value) if isinstance(value, float) else value), key


def test_h4a_s_statistic_is_the_controller_minus_the_larger_of_static_best_and_round_robin():
    from evaluation.qcai_eval import experiments

    def result(controller, static_best, round_robin):
        return {"policies": {"controller": {"quality_per_price": controller}, "static-best": {"quality_per_price": static_best},
                             "round-robin": {"quality_per_price": round_robin}}}

    assert experiments._h4a_difference(result(5.0, 3.0, 4.0)) == 1.0
    assert experiments._h4a_difference(result(3.5, 3.0, 4.0)) == -0.5  # beats static-best, loses to round-robin
    assert experiments._h4a_difference(result(3.5, 4.0, 3.0)) == -0.5
    assert experiments._h4a_difference(result(None, 3.0, 4.0)) == float("-inf")


PRICE = {"model-a": 0.003, "model-b": 0.002, "model-c": 0.004, "model-l": 0.001}
# A commissioning record per model as the replay tests set it (experiments.commissioning gives the run's own): 40 clean
# first passes, every model eligible.
COMMISSION = {model: {"clean": 40, "failed": 0, "generated": 40, "mean_q": "0.9"} for model in PRICE}


def _policy_plan(tmp_path, monkeypatch, **design):
    spec, _items = _e4_spec(tmp_path, monkeypatch)
    plan = runner.plan_run(spec)
    plan.extra["design"]["design"].update(design)
    return plan


def _outcomes(failing=()):
    from evaluation.qcai_eval import experiments

    return {model: experiments.Outcome(y=int(model not in failing), quality=float(model not in failing), cost=cost, first_cost=cost)
            for model, cost in PRICE.items()}


def test_the_controller_routes_by_algorithm_1_and_counts_detection_false_alarms_and_switches_by_mr_2_and_mr_3(tmp_path, monkeypatch):
    # The pinned package's ranking block: identical commissioning priors and lambda_u 0, so Algorithm 1's argmax ties
    # break to the smallest adapter id, model-a; the Bernoulli CUSUM adds ln(p1/p0) = ln 3 per error and alarms above
    # h = 4.0, so four consecutive errors alarm (4 ln 3 > 4 > 3 ln 3) on both of the model's streams; a batch closes at 25
    # responses, and 25 failures after the 40-clean commissioning prior demote model-a (a switch, to model-b).
    from evaluation.qcai_eval import experiments

    plan = _policy_plan(tmp_path, monkeypatch, stream_length=8, shift={"model": "model-a", "topic": "invented topic b", "at": 0, "points": "0.5"})
    clean = {("SYN-B-001", None): {"topic": "invented topic b", "outcomes": _outcomes()}}
    result = experiments._replay_stream(plan, clean, list(clean), sorted(PRICE), "s", commission=COMMISSION)["policies"]
    for policy in ("controller", "controller-no-hysteresis"):
        assert {key: result[policy][key] for key in ("verified_quality", "detection_delay", "false_alarms", "switches", "alarms")} == {
            "verified_quality": 8.0, "detection_delay": None, "false_alarms": 0, "switches": 0, "alarms": 0}, policy
        assert result[policy]["cost"] == pytest.approx(8 * 0.003)
    failing = {("SYN-B-001", None): {"topic": "invented topic b", "outcomes": _outcomes({"model-a"})}}
    # Ten drift-free failures: alarms at the 4th and 8th request on both of model-a's streams, all before the shift.
    plan.extra["design"]["design"].update(stream_length=10, shift={"model": "model-a", "topic": "invented topic b", "at": 10, "points": "0.5"})
    run = experiments._replay_stream(plan, failing, list(failing), sorted(PRICE), "s", commission=COMMISSION)["policies"]["controller"]
    assert (run["false_alarms"], run["alarms"], run["detection_delay"], run["switches"]) == (4, 4, None, 0)
    # 30 requests: the demotion at the 25th is one switch; per 1,000 drift-free requests it counts only before the shift.
    plan.extra["design"]["design"].update(stream_length=30, shift={"model": "model-a", "topic": "invented topic b", "at": 30, "points": "0.5"})
    run = experiments._replay_stream(plan, failing, list(failing), sorted(PRICE), "s", commission=COMMISSION)["policies"]["controller"]
    assert run["switches"] == 1 and run["switches_per_1000_drift_free"] == {"unscoped|explanation|2": pytest.approx(1000 / 30)}
    assert run["verified_quality"] == 5.0  # model-b delivers the last five
    plan.extra["design"]["design"]["shift"]["at"] = 20
    run = experiments._replay_stream(plan, failing, list(failing), sorted(PRICE), "s", commission=COMMISSION)["policies"]["controller"]
    assert run["switches"] == 1 and run["switches_per_1000_drift_free"] == {"unscoped|explanation|2": 0.0} and run["false_alarms"] == 10
    # The shift at 26 of 30: the demotion at the 25th is before it, and the denominator is the 26 drift-free requests only.
    plan.extra["design"]["design"]["shift"]["at"] = 26
    run = experiments._replay_stream(plan, failing, list(failing), sorted(PRICE), "s", commission=COMMISSION)["policies"]["controller"]
    assert run["switches"] == 1 and run["switches_per_1000_drift_free"] == {"unscoped|explanation|2": pytest.approx(1000 / 26)}
    # Detection counts the degraded model's responses in the shifted topic up to the first alarm on its stream for that
    # topic's context. Two failures in another topic first (seed s54 draws B, B, then shifted-topic units): model-a's global
    # stream alarms at its fourth error (the second degraded response), the shifted topic's stream at its own fourth.
    units = [("SYN-B-001", None), ("SYN-N-001", None), ("SYN-N-002", None)]
    population = {units[0]: {"topic": "invented topic b", "outcomes": _outcomes({"model-a"})},
                  units[1]: {"topic": "nisq-hybrid-workflows", "outcomes": _outcomes()},
                  units[2]: {"topic": "nisq-hybrid-workflows", "outcomes": _outcomes({"model-a"})}}
    plan.extra["design"]["design"].update(stream_length=6, shift={"model": "model-a", "topic": "nisq-hybrid-workflows", "at": 2, "points": "0.5"})
    assert [units[experiments._index("s54", 3, "request", t)][0] for t in range(6)] == [
        "SYN-B-001", "SYN-B-001", "SYN-N-002", "SYN-N-001", "SYN-N-001", "SYN-N-001"]
    stream = experiments._replay_stream(plan, population, units, sorted(PRICE), "s54", commission=COMMISSION)
    run = stream["policies"]["controller"]
    assert stream["shift_rate"] == 1.0 and run["detection_delay"] == 4 and run["false_alarms"] == 0 and run["alarms"] == 2


def test_epsilon_greedy_and_linucb_route_by_their_rules(tmp_path, monkeypatch):
    # epsilon-greedy: each model once in adapter-id order, then the best mean reward (quality per price) unless a seeded
    # draw below epsilon explores; LinUCB on the topic: the largest mean reward over (1 + pulls) plus alpha sqrt(1 / (1 +
    # pulls)), ties by adapter id.
    from evaluation.qcai_eval import experiments

    plan = _policy_plan(tmp_path, monkeypatch, stream_length=8, epsilon="0", linucb_alpha="0",
                        shift={"model": "model-a", "topic": "invented topic b", "at": 0, "points": "0.5"})
    clean = {("SYN-B-001", None): {"topic": "invented topic b", "outcomes": _outcomes()}}
    result = experiments._replay_stream(plan, clean, list(clean), sorted(PRICE), "s", commission=COMMISSION)["policies"]
    assert result["epsilon-greedy"]["cost"] == pytest.approx(0.003 + 0.002 + 0.004 + 0.001 + 4 * 0.001)  # then always model-l
    assert result["linucb"]["cost"] == pytest.approx(8 * 0.003)  # alpha 0: model-a first, and its reward keeps it ahead
    plan.extra["design"]["design"].update(epsilon="1", linucb_alpha="100000")
    result = experiments._replay_stream(plan, clean, list(clean), sorted(PRICE), "s", commission=COMMISSION)["policies"]
    models = sorted(PRICE)
    explored = [models[experiments._index("s", 4, "epsilon-greedy", "explore", t)] for t in range(4, 8)]
    assert result["epsilon-greedy"]["cost"] == pytest.approx(0.010 + sum(PRICE[model] for model in explored))
    assert result["linucb"]["cost"] == pytest.approx(2 * sum(PRICE.values()))  # the bonus dominates: the least pulled, in turn


def test_e4_commissions_each_model_from_its_own_outcomes_on_held_out_items_and_cheapest_eligible_routes_to_an_eligible_model(
        tmp_path, monkeypatch):
    # VBT RevB Sec. VII: "Posteriors start from commissioning: alpha0 = 1 + clean responses and beta0 = 1 + failed ones";
    # "Commissioning therefore uses the 30-item pilot plus the golden set (80 items)"; "In the replay, commissioning and
    # evaluation use disjoint items"; a model below rating B is "ineligible to generate". Rating B needs the 5% trust
    # bound at 0.90: 30 clean of 30 reach it (0.05 ** (1 / 31) > 0.90), 27 of 30 do not.
    from decimal import Decimal

    from evaluation.qcai_eval import experiments

    plan = _policy_plan(tmp_path, monkeypatch, commissioning_items=30, streams=2, stream_length=10,
                        shift={"model": "model-a", "topic": "invented topic b", "at": 10, "points": "0.5"})
    units = [(f"SYN-A-{index:03d}", None) for index in range(1, 41)]
    population = {unit: {"topic": "invented topic b", "outcomes": _outcomes({"model-l"})} for unit in units}
    held, rest = experiments.commissioning_split(plan, population)
    assert len(held) == 30 and len(rest) == 10 and set(held) | set(rest) == set(units) and not set(held) & set(rest)
    for unit in sorted(held)[:3]:  # model-a fails three commissioning items only: 27 clean, below rating B
        population[unit] = {"topic": "invented topic b", "outcomes": _outcomes({"model-l", "model-a"})}
    held, rest = experiments.commissioning_split(plan, population)
    records = experiments.commissioning(held, sorted(PRICE))
    assert records == {"model-a": {"clean": 27, "failed": 3, "generated": 30, "mean_q": "0.900000"},
                       "model-b": {"clean": 30, "failed": 0, "generated": 30, "mean_q": "1.000000"},
                       "model-c": {"clean": 30, "failed": 0, "generated": 30, "mean_q": "1.000000"},
                       "model-l": {"clean": 0, "failed": 30, "generated": 30, "mean_q": "0.000000"}}
    models = plan.extra["design"]["design"]["models"]
    block = plan.package_raw["ranking"]
    controller = experiments._Controller(block, models, hysteresis=True, commission=records)
    for model, record in records.items():  # the Phase 9 commission input: alpha0 = 1 + clean, beta0 = 1 + failed, qbar = mean_q
        prior = controller.state["models"][model]["prior"]
        assert (Decimal(prior["alpha"]), Decimal(prior["beta"]), Decimal(prior["qbar"])) == (
            1 + record["clean"], 1 + record["failed"], Decimal(record["mean_q"])), model
    assert controller.eligible("invented topic b") == ("model-b", "model-c")
    assert experiments._Controller(block, models, hysteresis=True, commission=COMMISSION).eligible("invented topic b") == tuple(sorted(PRICE))
    # cheapest-eligible: model-l is the cheapest over the pool but ineligible, so every request goes to model-b.
    stream = experiments._replay_stream(plan, rest, sorted(rest), sorted(PRICE), "s", commission=records)["policies"]
    assert stream["cheapest-eligible"]["cost"] == pytest.approx(10 * 0.002) and stream["cheapest-eligible"]["verified_quality"] == 10.0
    everyone = experiments._replay_stream(plan, rest, sorted(rest), sorted(PRICE), "s", commission=COMMISSION)["policies"]
    assert everyone["cheapest-eligible"]["cost"] == pytest.approx(10 * 0.001) and everyone["cheapest-eligible"]["verified_quality"] == 0.0
    # No model eligible: cheapest-eligible abstains, as the controller's fallback does.
    nobody = {model: {"clean": 0, "failed": 30, "generated": 30, "mean_q": "0"} for model in PRICE}
    stream = experiments._replay_stream(plan, rest, sorted(rest), sorted(PRICE), "s", commission=nobody)["policies"]
    assert stream["cheapest-eligible"] == {"verified_quality": 0.0, "cost": 0.0, "quality_per_price": None}
    # H4a commissions from the held-out units and draws its streams only from the others; one of the others fails model-a's
    # first pass, so the shift has a failed outcome to inject.
    population[sorted(rest)[0]] = {"topic": "invented topic b", "outcomes": _outcomes({"model-l", "model-a"})}
    drawn = []
    replay = experiments._replay_stream

    def spy(plan_, population_, units_, models_, seed_, *, commission):
        drawn.extend(units_)
        assert commission == records
        return replay(plan_, population_, units_, models_, seed_, commission=commission)

    monkeypatch.setattr(experiments, "_replay_stream", spy)
    result = experiments._h4a(plan, population, {model: (cost, cost) for model, cost in PRICE.items()}, experiments._hypotheses(plan)["H4a"])
    assert drawn and not set(drawn) & set(held)
    assert result["commissioning"] == {"items": 30, "units": 30, "rule": experiments.COMMISSIONING_RULE,
                                       "stands_in_for": experiments.COMMISSIONING_STAND_IN, "models": records, "stream_items": 10,
                                       "min_stream_items": 120, "below_floor": True, "floor_rule": experiments.STREAM_FLOOR_RULE}
    plan.extra["design"]["design"]["min_stream_items"] = 10  # exactly the floor: not below it
    assert experiments._h4a(plan, population, {model: (cost, cost) for model, cost in PRICE.items()},
                            experiments._hypotheses(plan)["H4a"])["commissioning"]["below_floor"] is False
    plan.extra["design"]["design"]["commissioning_items"] = 40  # nothing left for the streams
    assert experiments._h4a(plan, population, {model: (cost, cost) for model, cost in PRICE.items()},
                            experiments._hypotheses(plan)["H4a"])["status"] == "undefined"


def test_h4a_is_undefined_when_the_streams_population_cannot_carry_the_shift_and_otherwise_reports_its_rate(tmp_path, monkeypatch):
    # VBT RevB Sec. VIII-D: "At request 1,000, one model's first-pass error rate in one topic is raised by ten percentage
    # points". When the commissioning hold-out takes every item of the shift topic, or the shift model has no failed (or
    # no clean) first pass there among the streams' items, no shift can be injected: MR-2's figures would read "detected
    # 0" as if the controller had missed a real shift, so H4a is undefined and names why.
    from evaluation.qcai_eval import experiments

    plan = _policy_plan(tmp_path, monkeypatch, commissioning_items=1, streams=2, stream_length=10,
                        shift={"model": "model-a", "topic": "invented topic b", "at": 5, "points": "0.10"})
    prices = {model: (cost, cost) for model, cost in PRICE.items()}
    hypothesis = experiments._hypotheses(plan)["H4a"]
    items = [f"SYN-A-{index:03d}" for index in range(1, 8)]
    units = [(item, unit) for item in items for unit in ("t1", "t2")]
    held_item = next(iter({unit[0] for unit in experiments.commissioning_split(plan, dict.fromkeys(units))[0]}))
    others = [item for item in items if item != held_item]

    def population(failing_in_topic=(), topic_items=()):
        # The held-out item is always in the shift topic, with model-a failing its t2 unit; `topic_items` put other items
        # in the shift topic too, with model-a failing the units in `failing_in_topic`.
        return {(item, unit): {"topic": "invented topic b" if item == held_item or item in topic_items else "invented topic a",
                               "outcomes": _outcomes({"model-a"} if (item, unit) == (held_item, "t2") or (item, unit) in failing_in_topic else ())}
                for item, unit in units}

    held, rest = experiments.commissioning_split(plan, population())
    assert {unit[0] for unit in held} == {held_item} and all(value["topic"] == "invented topic a" for value in rest.values())
    result = experiments._h4a(plan, population(), prices, hypothesis)
    assert result["status"] == "undefined" and result["shift_not_injected"] == "topic_absent"
    assert result["reason"] == experiments.SHIFT_NOT_INJECTED["topic_absent"] and result["shift"]["rate"] == 0.0
    assert "detection" not in result and result["commissioning"]["items"] == 1
    # The shift topic among the streams' items, but the shift model never fails there (or always does): nothing to inject.
    topic = others[:2]
    assert experiments._h4a(plan, population(topic_items=topic), prices, hypothesis)["shift_not_injected"] == "no_failed_outcome"
    every = [(item, unit) for item in topic for unit in ("t1", "t2")]
    assert experiments._h4a(plan, population(every, topic), prices, hypothesis)["shift_not_injected"] == "no_clean_outcome"
    mixed = population([(topic[0], "t1"), (topic[0], "t2")], topic)
    plan.extra["design"]["design"]["shift"]["points"] = "0"
    assert experiments._h4a(plan, mixed, prices, hypothesis)["shift_not_injected"] == "zero_points"
    # A shift the streams can carry: base error 1/2, so ten points inject at 0.2, and the detection block reports it.
    plan.extra["design"]["design"]["shift"]["points"] = "0.10"
    result = experiments._h4a(plan, mixed, prices, hypothesis)
    assert "status" not in result and result["shift"]["rate"] == pytest.approx(0.2)
    assert result["detection"]["shift_rate"] == pytest.approx(0.2) and result["detection"]["streams"] == 2


def test_the_e4_record_carries_the_h4a_difference_interval_and_the_mr_2_and_mr_3_figures_labelled(tmp_path, monkeypatch):
    spec, _items = _e4_spec(tmp_path, monkeypatch)
    record = runner.execute_run(runner.plan_run(spec), StubResponder(), tmp_path / "e4")
    h4a = record["registered_tests"]["hypotheses"]["H4a"]
    interval = h4a["difference_interval_95"]
    assert interval == h4a["interval_95"] and interval["level"] == "0.95"
    assert interval["lower"] is None or interval["upper"] is None or interval["lower"] <= interval["upper"]
    assert "MR-2" in h4a["detection"]["rule"] and "not its outcome" in h4a["detection"]["criterion"]
    assert h4a["detection"]["shift_rate"] > 0 and h4a["shift"]["rate"] == h4a["detection"]["shift_rate"]
    assert "MR-3" in h4a["switches"]["rule"] and h4a["switches"]["streams"] == 4


def test_a_design_run_logs_its_design_inputs_and_its_outcome_to_the_access_log(tmp_path, monkeypatch, capsys):
    # Spec 3.11: the runner logs each input as the planner reads it and the run's outcome, so a refused run keeps its reads.
    if str(REPO_ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import run_evaluation

    e4, _lines = _e4_responses_for_e2(tmp_path, monkeypatch)
    e2, _source = _e2_spec(tmp_path, monkeypatch, e4_responses=e4)
    rated, _items = _e4_spec(tmp_path / "rated", monkeypatch, ratings=_repin(tmp_path / "eqc.jsonl", []))
    for name, spec, kinds in (("e2", e2, {"verification_set", "e4_responses"}), ("e4", rated, {"ratings"})):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(spec), encoding="utf-8")
        for gate, code, outcome in (("passed", 0, "completed"), ("refused", 8, "refused")):
            if gate == "refused":
                monkeypatch.undo()  # the confirmatory gate as committed: no IRB or OSF record
            access = tmp_path / f"{name}-{gate}-access.jsonl"
            assert run_evaluation.main(["--spec", str(path), "--output-dir", str(tmp_path / f"{name}-{gate}"), "--access-log", str(access),
                                        "--actor-role", "MLE"]) == code
            assert "Traceback" not in capsys.readouterr().err
            lines = read_jsonl(access)
            assert kinds <= {line["artifact_kind"] for line in lines if line["action"] == "read"}, name
            assert [line["outcome"] for line in lines if line["action"] == "run"][-1] == outcome
        _gate_passed(monkeypatch)


# ------------------------------------------------------------------------------- the hostile-value sweep of every input
# One generated sweep (spec 5, the exit-code contract): for each kind of research-plane input, every node of a valid
# fixture is replaced in turn by each hostile value class, written as JSON text (so that NaN, Infinity, 1e400, 1e-400
# and 10**400 reach the decoder as numbers, and their spellings as strings), the input re-pinned where a spec pins it,
# and the script run through its `main`. Each variant must end in a documented refusal or a completed run: never exit 1
# (drift, or a match), never the last-resort exit 10 (`internal_error`: an exception no validator caught), and never a
# traceback.

HOSTILE = {"wrong_type": None, "list": "[1]", "dict": '{"k": 1}', "null": "null", "bool": "true", "rational": '"1/3"',
           "overflow": "1e400", "overflow_text": '"1e400"', "underflow": "1e-400", "underflow_text": '"1e-400"',
           "huge_integer": "1" + "0" * 400, "huge_integer_digits": "1" * 5000, "nan": "NaN", "infinity": "Infinity", "negative": "-1",
           "empty": '""', "lone_surrogate": '"a\\ud800b"', "nul_text": '"a\\u0000b"'}
_MARK = "\u0001hostile\u0001"
SWEEP_CODES = {"run_evaluation": {0, 2, 3, 5, 6, 7, 8, 9}, "validate_ulqs": {0, 2, 3, 4, 5}, "migrate_ulqs_rc1": {0, 2, 3},
               "scan_research_logs": {0, 2}}
SWEEP_COUNTS = {stratum: 1 for stratum in "ABCDEFG"}  # one item per stratum where the input does not concern the items
# Both records valid: a confirmatory run's refusal moves on to the items (items_not_frozen, exit 3); a gate record alone
# leaves the gate's reasons for the records the variant does not supply.
SWEEP_VALID = {"irb_record": 3, "osf_record": 3, "freeze_record": ["irb_missing", "osf_missing", "pre_run_scan_missing"],
               "scan_report": ["irb_missing", "osf_missing", "freeze_record_missing"], "provider_terms": [], "licence_ruling": [],
               "research_use": [], "package_live": 9}


class _Everything:
    """A set holding every package sha256 (the live package kind judges each variant as committed)."""

    def __contains__(self, value):
        return True

    def __or__(self, other):
        return self


def _standard_sha(text):
    """The canonical sha256 of `text` as the standard json module reads it, or a placeholder when it cannot (an integer
    past its digit limit, or a string no hash can encode): the strict decoder refuses those before any pin is compared."""
    from evaluation.qcai_eval.canonical import canonical_sha256

    try:
        return canonical_sha256(json.loads(text))
    except (ValueError, UnicodeEncodeError):
        return "0" * 64


def _hostile_texts(document, root=()):
    """(node path, value class, the JSON text of `document` with that node replaced) for every node under `root`."""
    marker = json.dumps(_MARK)
    start = document
    for key in root:
        start = start[key]
    for relative in list(_nodes(start))[0 if root else 1:]:
        path = tuple(root) + tuple(relative)
        copy = json.loads(json.dumps(document))
        target = copy
        for key in path[:-1]:
            target = target[key]
        original = target[path[-1]]
        target[path[-1]] = _MARK
        text = json.dumps(copy)
        for name, token in HOSTILE.items():
            wrong = '"x"' if not isinstance(original, str) else "7"
            yield path, name, text.replace(marker, token if token is not None else wrong)


def _lines_with(lines, index, text):
    return "".join((text if number == index else json.dumps(line)) + "\n" for number, line in enumerate(lines))


def _sweep_main(name, argv):
    import contextlib
    import importlib
    import io

    if str(REPO_ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
    err, out = io.StringIO(), io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
        code = importlib.import_module(name).main([str(value) for value in argv])
    return code, err.getvalue()


def _pin_file(path, text):
    from evaluation.qcai_eval.canonical import lf_sha256

    Path(path).write_bytes(text.encode("utf-8"))
    return {"path": str(path), "sha256": lf_sha256(path)}


def _spec_argv(tmp_path, spec, number, *extra):
    """The argv of a run of `spec` (a dict, or the JSON text of a variant) into its own output directory."""
    spec_path = tmp_path / f"spec-{number}.json"
    spec_path.write_bytes((spec if isinstance(spec, str) else json.dumps(spec)).encode("utf-8"))
    return ["--spec", spec_path, "--output-dir", tmp_path / f"out-{number}", *extra]


def _labelled_index(lines):
    return next(index for index, line in enumerate(lines) if line["replicate"] == 1 and line["outcome"] == "answered" and line["claims"])


def _sweep_case(kind, tmp_path, monkeypatch):
    """(script, [(document, root, render)]) for one input kind: `render(text, number)` writes the variant (the JSON text
    of the document with one node replaced) where the script reads it, and returns the script's argv."""
    import shutil

    from evaluation.qcai_eval.canonical import lf_sha256

    if kind == "run_spec":
        spec, _items = small_spec(tmp_path)
        return "run_evaluation", [(spec, (), lambda text, n: _spec_argv(tmp_path, text, n))]
    if kind in ("design_e2", "design_e3", "design_e4"):
        if kind == "design_e2":
            spec, _source = _e2_spec(tmp_path, monkeypatch, dawid_skene_iterations=5, resamples=50)
        elif kind == "design_e3":
            _gate_passed(monkeypatch)
            spec, _items = _confirmatory(tmp_path, "E3", design={"arm": "VLOOP", "fixed_level": "intermediate", "repeats": 3,
                                                                "h3b_feature": "fk_grade"})
        else:
            spec, _items = _e4_spec(tmp_path, monkeypatch, epsilon="0.1", linucb_alpha="1", stream_length=20, streams=2)
        return "run_evaluation", [(spec, ("design",), lambda text, n: _spec_argv(tmp_path, text, n))]
    if kind == "recording":
        lines = read_jsonl(synthetic.RECORDED_FIXTURE)
        spec = _recording_spec(tmp_path / "recording")

        def entry(index):
            def write(text, n):
                pinned = _pin_file(tmp_path / f"recording-{n}.jsonl", _lines_with(lines, index, text))
                return _spec_argv(tmp_path, {**spec, "responder": {"recorded": pinned}}, n)
            return write
        return "run_evaluation", [(lines[0], (), entry(0)), (lines[1], (), entry(1))]
    if kind in ("checkpoint_responses", "checkpoint_events"):
        spec, _items = small_spec(tmp_path)
        base = tmp_path / "out-base"
        assert _sweep_main("run_evaluation", _spec_argv(tmp_path, spec, "base"))[0] == 0
        name = runner.RESPONSES if kind == "checkpoint_responses" else runner.RUN_EVENTS
        lines = read_jsonl(base / name)

        def write(text, n):
            out = tmp_path / f"out-{n}"
            shutil.copytree(base, out)
            (out / name).write_bytes(_lines_with(lines, 0, text).encode("utf-8"))
            return ["--spec", tmp_path / "spec-base.json", "--output-dir", out, "--resume"]
        return "run_evaluation", [(lines[0], (), write)]
    if kind in ("verification_set", "e4_responses"):
        if kind == "verification_set":
            spec, lines = _e2_spec(tmp_path, monkeypatch, dawid_skene_iterations=5, resamples=50)
        else:
            e4, lines = _e4_responses_for_e2(tmp_path, monkeypatch)
            spec, _source = _e2_spec(tmp_path, monkeypatch, dawid_skene_iterations=5, resamples=50, e4_responses=e4)
        index = _labelled_index(lines)

        def write(text, n):
            pinned = _pin_file(tmp_path / f"{kind}-{n}.jsonl", _lines_with(lines, index, text))
            return _spec_argv(tmp_path, {**spec, "design": {**spec["design"], kind: {**spec["design"][kind], **pinned}}}, n)
        return "run_evaluation", [(lines[index], (), write)]
    if kind == "design_ratings":
        spec, _items = _e4_spec(tmp_path, monkeypatch, epsilon="0.1", linucb_alpha="1", stream_length=20, streams=2)
        plan = runner.plan_run(spec)
        keys = sorted(r.request_key for r in plan.requests if r.arm == "VLOOP" and r.replicate == 1 and r.cell in ("model-l", "model-b"))
        lines = [{"rating": "eqc", "source_request_key": key, "value": 4.0 + 0.1 * (index % 4)} for index, key in enumerate(keys)]

        def write(text, n):
            pinned = _pin_file(tmp_path / f"ratings-{n}.jsonl", _lines_with(lines, 0, text))
            return _spec_argv(tmp_path, {**spec, "design": {**spec["design"], "ratings": pinned}}, n)
        return "run_evaluation", [(lines[0], (), write)]
    if kind in ("analysis_plans", "arms"):
        # Pinned by the canonical sha256 of the value as the standard json module reads it (NaN and 1e400 included), so
        # that the variant reaches the planner's own read and checks, not only the pin.
        from evaluation.qcai_eval.canonical import canonical_sha256

        spec, _items = small_spec(tmp_path, counts=SWEEP_COUNTS)
        block = "analysis_plan" if kind == "analysis_plans" else "arms"
        document = json.loads((REPO_ROOT / (synthetic.PLANS_PATH if kind == "analysis_plans" else synthetic.ARMS_PATH)).read_text(encoding="utf-8"))

        def write(text, n):
            path = tmp_path / f"{kind}-{n}.json"
            path.write_bytes(text.encode("utf-8"))
            pinned = {"path": str(path), "sha256": _standard_sha(text)}
            return _spec_argv(tmp_path, {**spec, block: {**spec[block], **pinned}}, n)
        return "run_evaluation", [(document, (), write)]
    if kind in ("package", "package_live", "package_e4"):
        # A package holding what the harness reads (its owner decisions, `semantic`, version and the ranking fields E4's
        # replay reads; the rest of a real package is only pinned), pinned by sha256 and sidecar. Stub runs judge it
        # uncommitted; the live kind judges every variant as committed (so its decisions are read as written) and, when
        # valid, is refused by the live checks (9). The E4 kind sweeps the ranking block through a confirmatory E4 stub run
        # (its gate passed), whose replay reads the block only after every request was sent.
        from evaluation.qcai_eval import governance

        real = json.loads((REPO_ROOT / synthetic.PACKAGE_PATH).read_text(encoding="utf-8"))
        ranking = real["ranking"]
        read = ("trust", "quality", "ratings", "tier_permissions", "selection", "promotion", "micro_batch", "cusum", "penalties", "seed")
        document = {"package_version": real["package_version"], "semantic": real["semantic"],
                    "owner_decisions": {name: real["owner_decisions"][name] for name in ("D-07", "D-14")},
                    "ranking": {**{name: ranking[name] for name in read},
                                "recommission": {name: ranking["recommission"][name] for name in ("deflation", "uncommissioned_prior")},
                                "contexts": {"clusters": ranking["contexts"]["clusters"][:2]}}}
        live = kind == "package_live"
        extra = {"mode": "live", "responder": {"live": {"adapter": None}}} if live else {}
        if kind == "package_e4":
            spec, _items = _e4_spec(tmp_path, monkeypatch, epsilon="0.1", linucb_alpha="1", stream_length=20, streams=2)
        else:
            spec, _items = small_spec(tmp_path, counts=SWEEP_COUNTS, **extra)
        if live:
            monkeypatch.setattr(governance, "committed_package_sha256s", lambda: _Everything())

        def write(text, n):
            path = tmp_path / f"package-{n}.json"
            path.write_bytes(text.encode("utf-8"))
            sha = _standard_sha(text)
            (tmp_path / f"package-{n}.json.sha256").write_text(sha + "\n", encoding="utf-8")
            return _spec_argv(tmp_path, {**spec, "package": {**spec["package"], "path": str(path), "sha256": sha}}, n)
        return "run_evaluation", [(document, ("ranking",) if kind == "package_e4" else (), write)]
    if kind == "harness_parameters":
        spec, _items = small_spec(tmp_path, counts=SWEEP_COUNTS)
        document = json.loads(runner.HARNESS_PARAMETERS.read_text(encoding="utf-8"))
        load = runner.load_harness_parameters

        def write(text, n):
            path = tmp_path / f"harness-{n}.json"
            path.write_bytes(text.encode("utf-8"))
            monkeypatch.setattr(runner, "load_harness_parameters", lambda path_=path: load(path_))
            return _spec_argv(tmp_path, spec, n)
        return "run_evaluation", [(document, (), write)]
    if kind == "rc1_mapping":
        source = synthetic.write_jsonl(tmp_path / "rc1.jsonl", synthetic.rc1_items(synthetic.synthetic_dataset(synthetic.SMALL)))
        document = json.loads((REPO_ROOT / "lqs" / "ulqs-rc1-to-v1.0-mapping.json").read_text(encoding="utf-8"))

        def write(text, n):
            path = tmp_path / f"mapping-{n}.json"
            path.write_bytes(text.encode("utf-8"))
            return ["--input", source, "--output", tmp_path / f"v1-{n}.jsonl", "--author-role", "PI",
                    "--access-log", tmp_path / f"access-{n}.jsonl", "--mapping", path]
        return "migrate_ulqs_rc1", [(document, (), write)]
    if kind in ("licensed_fingerprints", "ulqs_fingerprints", "synthetic_fixture"):
        from evaluation.qcai_eval import contamination

        fixture = json.loads(synthetic.CONTAMINATION_FIXTURE.read_text(encoding="utf-8"))
        logs = tmp_path / "logs"
        logs.mkdir()
        (logs / "log.txt").write_text("an invented clean log line\n", encoding="utf-8")
        if kind == "synthetic_fixture":
            def write(text, n):
                path = tmp_path / f"fixture-{n}.json"
                path.write_bytes(text.encode("utf-8"))
                return ["--synthetic-fixture", path, "--path", logs, "--require-zero"]
            return "scan_research_logs", [(fixture, (), write)]
        salt = bytes.fromhex(fixture["salt_hex"])
        sets = {"licensed_fingerprints": contamination.build_licensed(fixture["licensed_passages"][:1], salt, set_id="research-licensed-t1"),
                "ulqs_fingerprints": contamination.build_ulqs([{"question": fixture["ulqs_texts"][0]}], salt, set_id="research-ulqs-t1")}
        other = "ulqs_fingerprints" if kind == "licensed_fingerprints" else "licensed_fingerprints"
        fixed = tmp_path / f"{other}.private.json"
        fixed.write_text(json.dumps(sets[other]), encoding="utf-8")

        def write(text, n):
            path = tmp_path / f"{kind}-{n}.private.json"
            path.write_bytes(text.encode("utf-8"))
            licensed, ulqs_path = (path, fixed) if kind == "licensed_fingerprints" else (fixed, path)
            return ["--fingerprints", licensed, "--ulqs-fingerprints", ulqs_path, "--research-logs", logs, "--require-zero",
                    "--access-log", tmp_path / f"access-{n}.jsonl", "--actor-role", "PI"]
        return "scan_research_logs", [(sets[kind], (), write)]
    if kind == "agent_check":
        # The agent-check record through the checks validate_ulqs.py makes of it (strict decoding and its shape, both
        # refused with exit 2, then the freeze's agent-check codes): each variant must give reasons, never an exception.
        from evaluation.qcai_eval import inputs

        items = read_jsonl(synthetic.ITEMS_FIXTURE)
        raw_rules = json.loads(ulqs.DEFAULT_FREEZE_RULES.read_text(encoding="utf-8"))
        raw_rules["agent_check"]["pinned_models"] = [synthetic.SYNTHETIC_AGENT_MODEL]  # so that a valid record passes
        (tmp_path / "rules.json").write_text(json.dumps(raw_rules), encoding="utf-8")
        rules = ulqs.load_freeze_rules(tmp_path / "rules.json")
        record = synthetic.agent_check(items)

        def write(text, n):
            def reasons():
                try:
                    value = inputs.loads(text)
                except ValueError:
                    return ["agent_check_unreadable"]
                if not ulqs.agent_check_shape_ok(value):
                    return ["agent_check_invalid"]
                return ulqs.agent_check_failures(value, items, rules=rules, previous=items)
            return reasons
        return "governance", [(record, (), write)]
    if kind in ("irb_record", "osf_record"):
        spec, _items = small_spec(tmp_path, purpose="confirmatory", experiment="E1", run_id="synthetic-confirmatory-v1")
        records = {"irb_record": synthetic.irb_record(tmp_path / "irb.private.json"),
                   "osf_record": synthetic.osf_record(tmp_path / "osf.private.json", analysis_plan_sha256=spec["analysis_plan"]["sha256"])}
        record = json.loads(Path(records[kind]["path"]).read_text(encoding="utf-8"))

        def write(text, n):
            pinned = _pin_file(tmp_path / f"{kind}-{n}.private.json", text)
            return _spec_argv(tmp_path, {**spec, "governance": {**records, kind: pinned}}, n)
        return "run_evaluation", [(record, (), write)]
    if kind in ("freeze_record", "scan_report", "provider_terms", "licence_ruling", "research_use"):
        # The records the confirmatory and live gates read, through the gate functions the planner calls: each variant
        # must give reasons (a list of strings), never an exception.
        from evaluation.qcai_eval import governance

        content = "c" * 64
        made = {"freeze_record": lambda path: synthetic.freeze_record(path, dataset_sha256="d" * 64),
                "scan_report": lambda path: synthetic.pass_scan(path, dataset_content_sha256=content),
                "provider_terms": synthetic.provider_terms_record, "licence_ruling": synthetic.licence_ruling_record,
                "research_use": synthetic.research_use_record}[kind](tmp_path / f"{kind}.private.json")
        record = json.loads(Path(made["path"]).read_text(encoding="utf-8"))
        loaders = {"provider_terms": governance.load_provider_terms, "licence_ruling": governance.load_licence_ruling,
                   "research_use": governance.load_research_use}

        def write(text, n):
            pinned = _pin_file(tmp_path / f"{kind}-{n}.private.json", text)
            if kind in loaders:
                return lambda: governance.record_refusals(pinned, loaders[kind], REPO_ROOT, missing="missing", invalid="invalid")[0]
            return lambda: governance.confirmatory_refusals(
                {"created_at": synthetic.CREATED, "mode": "live", "governance": {}, kind if kind == "freeze_record" else "pre_run_scan": pinned},
                analysis_plan_sha256="a" * 64, dataset_sha256="d" * 64, dataset_content_sha256=content, corpus_version=synthetic.CORPUS_VERSION,
                items_states={"frozen": 3}, package_raw={"owner_decisions": {"D-14": {"state": "decided"}}}, repo_root=REPO_ROOT)
        return "governance", [(record, (), write)]
    if kind in ("ulqs_items", "catalog"):
        lines = read_jsonl(synthetic.ITEMS_FIXTURE if kind == "ulqs_items" else synthetic.CATALOG_FIXTURE)
        # Items: the first of strata A (single turn), F (multi-turn) and G (progress-conditioned levels); the catalog's first line.
        indices = [next(i for i, line in enumerate(lines) if line["stratum"] == stratum) for stratum in "AFG"] if kind == "ulqs_items" else [0]
        # The catalog's values reach the --corpus-text reader too (its document_id names the file it opens; review 25).
        corpus = tmp_path / "corpus-text"
        corpus.mkdir(exist_ok=True)
        for document, body in synthetic.corpus_text(read_jsonl(synthetic.ITEMS_FIXTURE)).items():
            (corpus / f"{document}.txt").write_bytes(body.encode("utf-8"))

        def line(index):
            def write(text, n):
                path = tmp_path / f"{kind}-{n}.jsonl"
                path.write_bytes(_lines_with(lines, index, text).encode("utf-8"))
                if kind == "ulqs_items":
                    return ["--items", path, "--catalog", synthetic.CATALOG_FIXTURE]
                return ["--items", synthetic.ITEMS_FIXTURE, "--catalog", path, "--corpus-text", corpus]
            return write
        return "validate_ulqs", [(lines[index], (), line(index)) for index in indices]
    if kind == "previous_items":
        # The set a freeze starts from (--previous), validated as the items are before it is used (exit 2).
        lines = read_jsonl(synthetic.ITEMS_FIXTURE)

        def write(text, n):
            path = tmp_path / f"previous-{n}.jsonl"
            path.write_bytes(_lines_with(lines, 0, text).encode("utf-8"))
            return ["--items", synthetic.ITEMS_FIXTURE, "--catalog", synthetic.CATALOG_FIXTURE, "--previous", path]
        return "validate_ulqs", [(lines[0], (), write)]
    rubric = tmp_path / "rubric.md"
    rubric.write_text("# an invented rubric\n", encoding="utf-8")
    ratings = synthetic.synthetic_ratings(read_jsonl(synthetic.ITEMS_FIXTURE), rubric_sha256=lf_sha256(rubric), share="1/4", disagree=1)
    if kind == "ratings":
        def write(text, n):
            path = tmp_path / f"ratings-{n}.jsonl"
            path.write_bytes(_lines_with(ratings, 0, text).encode("utf-8"))
            return ["--items", synthetic.ITEMS_FIXTURE, "--catalog", synthetic.CATALOG_FIXTURE, "--ratings", path, "--rubric", rubric,
                    "--agreement-out", tmp_path / f"agreement-{n}.json"]
        return "validate_ulqs", [(ratings[0], (), write)]
    assert kind == "freeze_rules", kind
    ratings_path = synthetic.write_jsonl(tmp_path / "ratings.jsonl", ratings)
    rules = json.loads(ulqs.DEFAULT_FREEZE_RULES.read_text(encoding="utf-8"))

    def write(text, n):
        path = tmp_path / f"rules-{n}.json"
        path.write_bytes(text.encode("utf-8"))
        return ["--items", synthetic.ITEMS_FIXTURE, "--catalog", synthetic.CATALOG_FIXTURE, "--ratings", ratings_path, "--rubric", rubric, "--rules", path,
                "--agreement-out", tmp_path / f"agreement-{n}.json"]
    return "validate_ulqs", [(rules, (), write)]


SWEEP_KINDS = ("run_spec", "design_e2", "design_e3", "design_e4", "recording", "checkpoint_responses", "checkpoint_events",
               "verification_set", "e4_responses", "design_ratings", "analysis_plans", "arms", "irb_record", "osf_record", "freeze_record", "scan_report",
               "provider_terms", "licence_ruling", "research_use", "ulqs_items", "previous_items",
               "catalog", "ratings", "freeze_rules", "package", "package_live", "package_e4", "harness_parameters", "rc1_mapping",
               "licensed_fingerprints", "ulqs_fingerprints", "synthetic_fixture", "agent_check")


@pytest.mark.parametrize("kind", SWEEP_KINDS)
def test_no_hostile_value_in_any_research_plane_input_ends_in_a_traceback_exit_1_or_the_last_resort(tmp_path, monkeypatch, kind):
    # Two costs no variant depends on are removed so that the sweep runs in CI time: the per-line fsync of responses.jsonl
    # and the `git rev-parse` of the record's commit.
    import os

    if str(REPO_ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import run_evaluation

    monkeypatch.setattr(os, "fsync", lambda descriptor: None)
    monkeypatch.setattr(run_evaluation, "_commit", lambda: None)
    name, documents = _sweep_case(kind, tmp_path, monkeypatch)
    failures, number = [], 0
    for index, (document, root, render) in enumerate(documents):
        if name == "governance":
            reasons = render(json.dumps(document), f"valid-{index}")()
            assert reasons == SWEEP_VALID.get(kind, []), reasons  # the fixture itself is valid
            for path, value_class, text in _hostile_texts(document, root):
                number += 1
                try:
                    reasons = render(text, number)()
                except Exception as error:  # noqa: BLE001 - the sweep reports every exception a gate raised
                    failures.append((path, value_class, type(error).__name__))
                    continue
                if not (isinstance(reasons, list) and all(isinstance(reason, str) for reason in reasons)):
                    failures.append((path, value_class, reasons))
            continue
        # The fixture itself is valid: unchanged, it runs (or, for a governance record, reaches the refusal after the gate).
        code, err = _sweep_main(name, render(json.dumps(document), f"valid-{index}"))
        assert code == SWEEP_VALID.get(kind, 0) and "Traceback" not in err, (code, err[-500:])
        for path, value_class, text in _hostile_texts(document, root):
            number += 1
            code, err = _sweep_main(name, render(text, number))
            if code not in SWEEP_CODES[name] or "Traceback" in err:
                failures.append((path, value_class, code, err.strip().splitlines()[-1:]))
    assert number and failures == [], (number, len(failures), failures[:20])


@pytest.mark.parametrize(("value", "reason"), [
    ("1" * 5000, "recording_invalid"), ('"a\\ud800b"', "recording_invalid")])
def test_a_recording_value_the_decoder_refuses_is_recording_invalid_before_any_request(tmp_path, value, reason):
    # Review 21: a 5000-digit integer reached Python's own conversion limit (a plain ValueError, read as the pin class
    # `recording_unreadable`, exit 6), and a lone surrogate passed the decoder and crashed the run after it started
    # (exit 10). Both are invalid content of a pinned recording: exit 3 `recording_invalid`, before any request.
    lines = read_jsonl(synthetic.RECORDED_FIXTURE)
    spec = _recording_spec(tmp_path / "recording")
    entry = json.dumps(lines[1]).replace(json.dumps(lines[1]["response"]["claims"][0]["claim_id"]), value, 1)
    pinned = _pin_file(tmp_path / "recording.jsonl", _lines_with(lines, 1, entry))
    code, err = _sweep_main("run_evaluation", _spec_argv(tmp_path, {**spec, "responder": {"recorded": pinned}}, "r"))
    assert (code, err.strip().splitlines()[-1]) == (3, f"refused (exit 3): {reason}")
    assert not (tmp_path / "out-r" / runner.RESPONSES).exists()


@pytest.mark.parametrize(("package", "reason"), [
    ([1], "package_invalid:package"), ("x", "package_invalid:package"), ({"owner_decisions": [1]}, "package_invalid:owner_decisions"),
    ({"owner_decisions": {"D-14": "decided"}}, "package_invalid:owner_decisions"), ({"semantic": [1]}, "package_invalid:semantic"),
    ({"ranking": [1]}, "package_invalid:ranking"), ({"ranking": {"trust": [1]}}, "package_invalid:ranking.trust.gamma")])
def test_a_pinned_package_the_harness_cannot_read_is_refused_as_package_invalid(tmp_path, package, reason):
    # A hand-made package with a matching sha256 and sidecar, but not shaped as the harness reads it (an object; owner
    # decisions an object of objects; `semantic` an object; `ranking` absent, null or shaped as E4's replay reads it,
    # whatever the experiment), is refused with exit 6, never the last-resort exit 10.
    from evaluation.qcai_eval.canonical import canonical_sha256

    spec, _items = small_spec(tmp_path)
    path = tmp_path / "package.json"
    path.write_text(json.dumps(package), encoding="utf-8")
    sha = canonical_sha256(package)
    (tmp_path / "package.json.sha256").write_text(sha + "\n", encoding="utf-8")
    with pytest.raises(runner.RunRefused) as refused:
        runner.plan_run({**spec, "package": {**spec["package"], "path": str(path), "sha256": sha}})
    assert (refused.value.code, refused.value.reasons) == (6, [reason])
    code, err = _sweep_main("run_evaluation", _spec_argv(tmp_path, {**spec, "package": {**spec["package"], "path": str(path), "sha256": sha}}, "p"))
    assert code == 6 and "internal_error" not in err


def test_run_events_holding_a_raw_line_separator_read_back_as_one_event_each(tmp_path):
    # Review 22: the run-events reader split with str.splitlines, which breaks inside a string holding a raw U+2028,
    # U+2029 or U+0085 (as dumps_line writes it); it splits at LF only, as read_jsonl does, and still reads CRLF.
    from evaluation.qcai_eval.canonical import dumps_line

    events = [{"event": "start", "note": f"an invented{separator}note"} for separator in ("\u2028", "\u2029", "\u0085")]
    path = tmp_path / runner.RUN_EVENTS
    path.write_bytes("".join(dumps_line(event) for event in events).encode("utf-8"))
    assert runner._read_events(path) == events
    path.write_bytes("".join(dumps_line(event) for event in events).replace("\n", "\r\n").encode("utf-8"))
    assert runner._read_events(path) == events


def _ranking_with(path, value):
    real = json.loads((REPO_ROOT / synthetic.PACKAGE_PATH).read_text(encoding="utf-8"))["ranking"]
    target = real
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return real


@pytest.mark.parametrize(("ranking", "reason"), [
    ([1], "package_invalid:ranking"), ("x", "package_invalid:ranking"), ({"quality": [1]}, "package_invalid:ranking.trust.gamma"),
    (_ranking_with(("quality",), [1]), "package_invalid:ranking.quality.eta"),
    (_ranking_with(("quality", "weights"), {"V": "0.35"}), "package_invalid:ranking.quality.weights"),
    (_ranking_with(("quality", "eta"), "x"), "package_invalid:ranking.quality.eta"),
    (_ranking_with(("cusum", "p1"), 0.15), "package_invalid:ranking.cusum.p1"),
    (_ranking_with(("promotion", "n_d"), "3"), "package_invalid:ranking.promotion.n_d"),
    (_ranking_with(("selection", "first_incumbent_is_switch"), "false"), "package_invalid:ranking.selection.first_incumbent_is_switch"),
    (_ranking_with(("tier_permissions", "A"), "x"), "package_invalid:ranking.tier_permissions.A"),
    (_ranking_with(("ratings",), {"A": "0.95"}), "package_invalid:ranking.ratings"),
    (_ranking_with(("seed",), 7), "package_invalid:ranking.seed"),
    (_ranking_with(("contexts", "clusters", 5), [None]), "package_invalid:ranking.contexts.clusters"),
    # Shaped as the replay reads it, but refused by the ranking arithmetic (the Beta quantile at 0): the dry run.
    (_ranking_with(("trust", "quantile"), "0"), "package_invalid:ranking"),
    (_ranking_with(("quality", "initial_qbar"), "1e400"), "package_invalid:ranking"),
    # The eq. (8) weights: non-negative with a positive sum, and weights whose sum overflows the 34-digit context once a
    # response carries S and K signals (the dry run computes eq. (8) over every subset of V, S, K and F at 0 and at 1).
    (_ranking_with(("quality", "weights"), {"V": "0.35", "S": "-0.30", "K": "0.15", "F": "0.20"}), "package_invalid:ranking.quality.weights"),
    (_ranking_with(("quality", "weights"), {"V": "0", "S": "0", "K": "0", "F": "0"}), "package_invalid:ranking.quality.weights"),
    (_ranking_with(("quality", "weights"), {"V": "0.35", "S": "9e999999", "K": "9e999999", "F": "0.20"}), "package_invalid:ranking")])
def test_an_e4_run_over_a_package_whose_ranking_block_the_replay_cannot_read_is_refused_before_any_request(
        tmp_path, monkeypatch, ranking, reason):
    # Review 22: E4's replay reads the package's ranking block only after every request was sent, so a malformed block
    # (with a matching sha256 and sidecar) ended in the last-resort exit 10 after 192 responses were written. It is now
    # refused when the run is planned (exit 6): its shape by `package_problem` (`experiments.ranking_problem`), its
    # arithmetic by a dry run of the controller policies (`experiments.ranking_replay_problem`).
    spec, _items = _e4_spec(tmp_path, monkeypatch, shift=SHIFT_G)
    package = synthetic.decided_package(tmp_path, ranking=ranking)
    pinned = {**spec, "package": {**spec["package"], "path": package["path"], "sha256": package["sha256"]}}
    with pytest.raises(runner.RunRefused) as refused:
        runner.plan_run(pinned)
    assert (refused.value.code, refused.value.reasons) == (6, [reason])
    code, err = _sweep_main("run_evaluation", _spec_argv(tmp_path, pinned, "r"))
    assert (code, err.strip().splitlines()[-1]) == (6, f"refused (exit 6): {reason}")
    assert not (tmp_path / "out-r" / runner.RESPONSES).exists()


class _SignalResponder:
    """The stub responder, with eq. (8) signals V, S and K on every response."""

    rule = "stub-responder-v1"

    def respond(self, request):
        return {**StubResponder().respond(request), "signals": {"V": "0.5", "S": "0.5", "K": "0.5", "H": None, "F": None}}


def test_an_e4_run_whose_responses_carry_s_and_k_signals_replays_them_with_the_package_weights(tmp_path, monkeypatch):
    # Review 23: the replay computes eq. (8) over each VLOOP response's own signals (S and K included) after every request
    # was sent; with the package's weights it completes, and the qualities are eq. (8)'s.
    from evaluation.qcai_eval import experiments

    spec, _items = _e4_spec(tmp_path, monkeypatch, shift=SHIFT_G)
    plan = runner.plan_run(spec)
    record = runner.execute_run(plan, _SignalResponder(), tmp_path / "out")
    assert "units" in record["metrics"]["replay"]
    population, _excluded, _prices = experiments._replay_population(plan, read_jsonl(tmp_path / "out" / runner.RESPONSES))
    assert population and {outcome.quality for unit in population.values() for outcome in unit["outcomes"].values()} == {0.5}


def test_an_e4_replay_whose_quality_arithmetic_fails_after_the_run_is_reported_undefined_never_exit_10(tmp_path, monkeypatch):
    # Should eq. (8) still be refused on a response after the run (`ranking_replay_problem` refuses, before any request,
    # every block whose eq. (8) arithmetic fails on signals in [0, 1]), the replay and H4a are reported undefined.
    import decimal

    from evaluation.qcai_eval import experiments

    spec, _items = _e4_spec(tmp_path, monkeypatch, shift=SHIFT_G)
    plan = runner.plan_run(spec)

    def overflow(*_args):
        raise decimal.Overflow

    monkeypatch.setattr(experiments, "_quality", overflow)
    record = runner.execute_run(plan, _SignalResponder(), tmp_path / "out")
    refused = {"status": "undefined", "reason": experiments.REPLAY_REFUSED, "error": "Overflow"}
    assert record["metrics"]["replay"] == refused
    assert {key: record["registered_tests"]["hypotheses"]["H4a"][key] for key in refused} == refused
    assert len(read_jsonl(tmp_path / "out" / runner.RESPONSES)) == len(plan.requests)


def test_an_e4_run_over_a_package_with_a_null_ranking_block_is_not_refused(tmp_path, monkeypatch):
    # An absent or null block is not malformed: the run completes, and the replay's controller policies then report
    # `no_ranking_block` (`experiments`).
    from evaluation.qcai_eval import experiments

    spec, _items = _e4_spec(tmp_path, monkeypatch, shift=SHIFT_G)
    package = synthetic.decided_package(tmp_path, ranking=None)
    plan = runner.plan_run({**spec, "package": {**spec["package"], "path": package["path"], "sha256": package["sha256"]}})
    assert runner.package_problem(plan.package_raw) is None and experiments.ranking_replay_problem(None, []) is None
    record = runner.execute_run(plan, StubResponder(), tmp_path / "out")
    assert record["experiment"] == "E4" and len(read_jsonl(tmp_path / "out" / runner.RESPONSES)) == len(plan.requests)


@pytest.mark.parametrize("text", ["[1]", '"x"', "null", '{"parameters": "harness-parameters-v1", "replicate_variance_required": [1]}'])
def test_harness_parameters_not_shaped_as_an_object_are_refused_as_harness_parameters_invalid(tmp_path, monkeypatch, text):
    # The sweep replaces nodes inside the file; a whole file of another type (or a block that is not an object) is a
    # ValueError of the loader, so the run is refused with exit 6, never the last-resort exit 10.
    path = tmp_path / "harness.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        runner.load_harness_parameters(path)
    load = runner.load_harness_parameters
    monkeypatch.setattr(runner, "load_harness_parameters", lambda: load(path))
    spec, _items = small_spec(tmp_path)
    with pytest.raises(runner.RunRefused) as refused:
        runner.plan_run(spec)
    assert (refused.value.code, refused.value.reasons) == (6, ["harness_parameters_invalid"])


def test_every_research_plane_input_is_decoded_strictly(tmp_path):
    # inputs.loads, the one decoder of every research-plane input: the standard json module would accept each of these
    # and hand a later step a value it cannot compute with (NaN, an infinity, 0.0 for a non-zero number, an integer no
    # float holds, a nesting no decoder can read). Each is refused as InputInvalid, a ValueError, so every reader refuses
    # the input with its own documented code; ordinary values decode unchanged.
    from evaluation.qcai_eval import inputs

    for text in ('{"v": NaN}', '{"v": Infinity}', '{"v": -Infinity}', '{"v": 1e400}', '{"v": -1e400}', '{"v": 1e-400}',
                 '{"v": 0.1e-400}', '{"v": ' + "1" + "0" * 400 + "}", '{"v": -' + "9" * 17 + "}", "[" * 100_000 + "]" * 100_000,
                 # past the interpreter's 4300-digit conversion limit (its own ValueError is not InputInvalid)
                 '{"v": ' + "1" * 5000 + "}", '{"v": -' + "1" * 5000 + "}", '{"v": 90071992547409921}',
                 # an unpaired UTF-16 surrogate, in a value, a key, a nested list and alone
                 '{"v": "\\ud800"}', '{"\\udfff": 1}', '[["a\\udfffb"]]', '"\\ud800"', '{"v": ["ok", {"w": "\\udc00"}]}'):
        with pytest.raises(inputs.InputInvalid):
            inputs.loads(text)
    assert inputs.loads('{"v": "\\ud83d\\ude00"}') == {"v": "\U0001f600"}  # a surrogate pair is one character
    assert inputs.loads('{"a": [1, 2.5, 0.0, 0e5, -0.0, 5e-324, 9007199254740992, -9007199254740992, "NaN", "1e400"]}') == {
        "a": [1, 2.5, 0.0, 0.0, -0.0, 5e-324, 2 ** 53, -(2 ** 53), "NaN", "1e400"]}
    assert inputs.loads(b'{"b": true}') == {"b": True}
    path = tmp_path / "lines.jsonl"
    path.write_text('{"ok": 1}\n{"v": NaN}\n', encoding="utf-8")
    with pytest.raises(ValueError, match=r"^line 2: a non-finite number \(NaN\)$"):
        read_jsonl(path)
    # Through a reader: a run spec holding NaN is refused as unreadable (exit 2), never planned with a NaN in it.
    spec, _items = small_spec(tmp_path)
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps({**spec, "created_at": float("nan")}), encoding="utf-8")
    with pytest.raises(runner.RunRefused) as refused:
        runner.load_spec(spec_path)
    assert refused.value.code == 2 and refused.value.reasons == ["spec_unreadable"]
