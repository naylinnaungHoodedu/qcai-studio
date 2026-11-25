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


def test_an_e1_record_computes_the_registered_e1_family_and_other_records_do_not(tmp_path):
    # The analysis plan's E1 family: H1a exact McNemar VLOOP vs GATE, H1b VLOOP vs GATE+SV (item-level error, eq. 12), H1c
    # the one-sided paired bootstrap of the item answer rate VLOOP - GATE against the margin -0.05 (eq. 17), then Holm over
    # the three. A confirmatory E1 spec cannot run here (its gate), so the planned harness-check is relabelled E1.
    from evaluation.qcai_eval import statistics

    spec, _ = small_spec(tmp_path)
    plan = runner.plan_run(spec)
    record = runner.execute_run(plan, StubResponder(), tmp_path / "check")
    assert record["registered_tests"] is None
    e1 = dataclasses.replace(plan, spec={**plan.spec, "experiment": "E1"})
    record = runner.execute_run(e1, StubResponder(), tmp_path / "e1")
    registered = record["registered_tests"]
    responses = read_jsonl(tmp_path / "e1" / "responses.jsonl")
    assert registered["family"] == "E1" and set(registered["hypotheses"]) == {"H1a", "H1b", "H1c"}

    def errors(arm):
        return runner._paired_errors(e1, responses, arm)

    for name, (left, right) in (("H1a", ("VLOOP", "GATE")), ("H1b", ("VLOOP", "GATE+SV"))):
        a, b = errors(left), errors(right)
        keys = sorted(set(a) & set(b), key=lambda key: (key[0], key[1] or ""))
        expected = statistics.mcnemar_exact([bool(a[key]) for key in keys], [bool(b[key]) for key in keys])
        assert registered["hypotheses"][name] == {"endpoint": "item-level error (eq. 12)", "comparison": [left, right],
                                                  "test": "mcnemar_exact", **expected}, name
    answered = {arm: {} for arm in ("VLOOP", "GATE")}
    for request, response in zip(e1.requests, responses):
        if request.arm in answered and request.replicate == 1 and request.gold == "answer" and response["outcome"] != "provider_failure":
            answered[request.arm].setdefault(request.item_id, []).append(int(response["outcome"] == "answered"))
    items = sorted(set(answered["VLOOP"]) & set(answered["GATE"]))
    rate = lambda arm, item: sum(answered[arm][item]) / len(answered[arm][item])  # noqa: E731
    h1c = statistics.paired_bootstrap_one_sided([rate("VLOOP", item) for item in items], [rate("GATE", item) for item in items],
                                                resamples=1000, seed=hashed_hex(spec["run_id"], "registered", "H1c"), margin="-0.05")
    assert registered["hypotheses"]["H1c"] == {"endpoint": "answer rate (eq. 17)", "comparison": ["VLOOP", "GATE"],
                                              "test": "paired_bootstrap_one_sided", **h1c}
    assert registered["holm"] == statistics.holm({name: value["p_value"] for name, value in registered["hypotheses"].items()})
    assert "GATE-vs-NR" in record["comparisons"]["pairs"]  # the exploratory comparisons stay what they were
