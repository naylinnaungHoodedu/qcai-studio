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
                                   "resamples": None, "ratings": None}
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


E4_MODELS = [{"model_id": "model-a", "family": "family-a", "price_per_unit": "0.003", "local": False},
             {"model_id": "model-b", "family": "family-b", "price_per_unit": "0.002", "local": False},
             {"model_id": "model-c", "family": "family-c", "price_per_unit": "0.004", "local": False},
             {"model_id": "model-l", "family": "local", "price_per_unit": "0.001", "local": True}]


def _e4_spec(tmp_path, monkeypatch, **changes):
    _gate_passed(monkeypatch)
    items_path, catalog_path, items = synthetic.write_fixture_set(tmp_path, synthetic.SMALL, splits=True)
    design = {"models": E4_MODELS, "pilot_commercial": "model-b", "streams": 4, "stream_length": 40,
              "shift": {"model": "model-b", "topic": items[0]["topic"], "at": 20}, **changes}
    spec = synthetic.spec_dict(items_path=items_path, catalog_path=catalog_path, purpose="confirmatory", experiment="E4", family="E4",
                               run_id="synthetic-e4-v1", design=design)
    return spec, items


def test_e4_answers_every_unit_with_four_models_in_gate_and_vloop_and_tests_h4a_and_h4b(tmp_path, monkeypatch):
    # VBT RevB Sec. VIII-D E4: "All four models answer all items in arms GATE and VLOOP"; "1,000 seeded streams of 2,000
    # requests compare the proposed controller, with and without hysteresis, against static-best, round-robin rotation,
    # cheapest-eligible, epsilon-greedy, a LinUCB-style bandit ... and threshold escalation"; Table I H4b "Exact McNemar"
    # on the local and the pilot-selected commercial model's error rates without verification (GATE).
    from evaluation.qcai_eval import experiments, statistics

    spec, items = _e4_spec(tmp_path, monkeypatch)
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
    assert set(h4a["quality_per_price"]) == set(experiments.POLICIES)
    assert record["registered_tests"]["holm"] == statistics.holm({"H4a": h4a["p_value"], "H4b": h4b["p_value"]})
    # Every delivered answer is clean and every abstention delivers nothing: the local model, the cheapest, is static-best.
    population, excluded, prices = experiments._replay_population(plan, read_jsonl(tmp_path / "e4" / "responses.jsonl"))
    assert excluded == 0 and len(population) == len({(item, unit) for item, unit, _r in units})
    stream = experiments._replay_stream(plan, population, sorted(population, key=lambda u: (u[0], u[1] or "")), prices, "unit-test")
    assert stream["static_best"] == "model-l" and stream["policies"]["static-best"] == stream["policies"]["cheapest-eligible"]
    assert "at_later_prices" not in h4a
    # "at both Gemini prices if runs straddle 1 January 2027": a model's later list price replays H4a again beside it.
    later = [{**entry, "later_price": {"from": "2027-01-01", "price_per_unit": "0.006"}} if entry["model_id"] == "model-b" else entry
             for entry in E4_MODELS]
    spec_later = {**spec, "design": {**spec["design"], "models": later}}
    plan_later = runner.plan_run(spec_later)
    record_later = runner.execute_run(plan_later, _scripted(rule), tmp_path / "e4-later")
    at_later = record_later["registered_tests"]["hypotheses"]["H4a"]["at_later_prices"]
    assert at_later["later_price"] == {"model-b": {"from": "2027-01-01", "price_per_unit": "0.006"}} and at_later["enters_holm"] is False
    assert experiments._replay_population(plan_later, read_jsonl(tmp_path / "e4-later" / "responses.jsonl"), later=True)[2] == {
        **prices, "model-b": 0.006}
    assert record_later["registered_tests"]["holm"] == record["registered_tests"]["holm"]
    with pytest.raises(runner.RunRefused) as refused:
        runner.plan_run({**spec, "design": {**spec["design"], "models": [{**later[1], "later_price": {"from": "soon", "price_per_unit": "1"}},
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
    result = experiments._replay_stream(plan, population, sorted(population), price, "policy-test")
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
    single = experiments._replay_stream(plan, population, [("SYN-A-001", None)], price, "policy-test")
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
