"""Phase 3: the invariant 1 fixture tells learners apart by every field it compares (plan 7.8 invariant 1, 12.4(c),
CT-04; AC-3-1).

J2  the fixture compares the ClaimPlans and the whole shadow record (bundle, threshold, sufficiency, abstention reason,
    counts), so a learner-dependent plan or threshold fails it.
K1  a learner-dependent abstention reason, floor, margin, sufficiency score, counts or top_k each fails it, and the
    record it compares keeps every field of the shadow record but its ids.
The fixture itself (observe_three_learners) is in test_phase3_acceptance.py. Each test fails if its defect comes back;
the spec's review history (18.4) names the round behind each group.
"""

from __future__ import annotations

import copy
import dataclasses

import pytest

from app.core.config import Settings
from app.core.config_package import get_config_package
from app.services.tutor_pipeline import contracts
from app.services.tutor_pipeline import pipeline as pipeline_module
from app.services.tutor_pipeline.contracts import ProposedClaim
from app.services.tutor_pipeline.evidential import ExtractiveD19Generator
from app.services.tutor_pipeline.pipeline import TwoPassPipeline

from tutor_fakes import SpyGenerator


def _old_projection(item: dict) -> dict:
    """The five fields the invariant 1 test compared before the ninth round."""
    record = item["record"]
    return {"request": item["retrieve"]["request"], "envelopes": item["envelopes"],
            "bundle": [(span["span_id"], span["score"]) for span in record["retrieval"]["evidence"]],
            "claim_set_hash": record["claim_set_hash"], "decision": record["decision"]}


# =============================================================================================================== J2


_LEAK = {"learner": None}


class _LeakySpy(SpyGenerator):
    """A generator that reads state outside its envelope (a module global) and, for one learner, adds a claim that
    does not bind: the ClaimPlan and the counts differ, while the locked set, its hash and the decision do not."""

    def propose(self, envelope):
        plan = self.inner.propose(envelope)
        if _LEAK["learner"] == 0.5 and envelope.evidence:
            plan = plan.model_copy(update={"claims": (*plan.claims, ProposedClaim(text="No span holds this sentence verbatim.",
                                                                                  span_ids=(envelope.evidence[0].span_id,)))})
        self.envelopes.append(envelope.model_dump(mode="json"))
        self.plans.append(plan.model_dump(mode="json"))
        return plan


def _leaky_assistant_class():
    from test_phase3_acceptance import _SpyAssistant

    class _LeakyAssistant(_SpyAssistant):
        spy = None

        @property
        def pipeline(self):
            if getattr(self, "_spy_pipeline", None) is None:
                type(self).spy = _LeakySpy(ExtractiveD19Generator(get_config_package(self.settings)))
                self._spy_pipeline = TwoPassPipeline(self.retrieval_engine, self.settings, generator=type(self).spy)
            return self._spy_pipeline

    return _LeakyAssistant


def test_j2_a_learner_dependent_claim_plan_fails_the_invariant_1_fixture_though_the_old_comparison_passed(monkeypatch):
    from test_phase3_acceptance import observe_three_learners

    monkeypatch.setitem(_LEAK, "learner", None)
    observed, _, _ = observe_three_learners(monkeypatch, assistant_class=_leaky_assistant_class(), prefix="j2-plan",
                                            on_learner=lambda mastery: _LEAK.__setitem__("learner", mastery))
    # The five fields the test compared until 18.12 J2 are equal: the extra claim never bound.
    assert all([_old_projection(item) for item in learner] == [_old_projection(item) for item in observed[0]] for learner in observed)
    # The whole fixture is not: the 0.5 learner's ClaimPlans and counts differ, as plan 7.8 invariant 1 forbids.
    assert observed[1] != observed[0] and observed[2] == observed[0]
    differing = [index for index, (item, other) in enumerate(zip(observed[1], observed[0])) if item != other]
    assert differing and all(observed[1][index]["plans"] != observed[0][index]["plans"] for index in differing)
    assert all(observed[1][index]["record"]["counts"]["dropped"].get("not_verbatim") == 1 for index in differing)


def test_j2_a_learner_dependent_threshold_fails_the_invariant_1_fixture(monkeypatch):
    from test_phase3_acceptance import _SpyAssistant, observe_three_learners

    learner = {"mastery": None}
    real_retrieve = pipeline_module.retrieve

    def retrieve(engine, request, **kwargs):
        bundle = real_retrieve(engine, request, **kwargs)
        if learner["mastery"] != 0.9:
            return bundle
        # A learner-dependent threshold version that leaves the same results above it (the gap the finding named).
        sufficiency = bundle.sufficiency.model_copy(update={"threshold_version": bundle.sufficiency.threshold_version + "-learner"})
        return bundle.model_copy(update={"sufficiency": sufficiency})

    monkeypatch.setattr(pipeline_module, "retrieve", retrieve)
    observed, _, _ = observe_three_learners(monkeypatch, assistant_class=_SpyAssistant, prefix="j2-threshold",
                                            on_learner=lambda mastery: learner.__setitem__("mastery", mastery))
    assert all([_old_projection(item) for item in each] == [_old_projection(item) for item in observed[0]] for each in observed)
    assert observed[1] == observed[0] and observed[2] != observed[0]
    assert all(item["record"]["retrieval"]["threshold_version"].endswith("-learner") for item in observed[2])


# =============================================================================================================== K1


_LEARNER = {"mastery": None}


def _for_one_learner(mutate):
    """mutate(value) for the 0.9 learner only; the others see the value unchanged."""
    return lambda value: mutate(value) if _LEARNER["mastery"] == 0.9 else value


def _patch_entry(monkeypatch, mutate) -> None:
    # Both record builders: _entry (ledger-entry-v1) and, with V1 running in the shadow (Phase 4), _entry_v2.
    mutate_one = _for_one_learner(mutate)
    for name in ("_entry", "_entry_v2"):
        real = getattr(TwoPassPipeline, name)
        monkeypatch.setattr(TwoPassPipeline, name, lambda self, *args, _real=real, **kwargs: mutate_one(_real(self, *args, **kwargs)))


def _patch_bundle(monkeypatch, mutate) -> None:
    real = pipeline_module.retrieve
    mutate_one = _for_one_learner(mutate)
    monkeypatch.setattr(pipeline_module, "retrieve", lambda engine, request, **kwargs: mutate_one(real(engine, request, **kwargs)))


def _sufficiency(**changes):
    def mutate(bundle):
        sufficiency = bundle.sufficiency
        update = {key: change(getattr(sufficiency, key)) for key, change in changes.items()}
        return bundle.model_copy(update={"sufficiency": sufficiency.model_copy(update=update)})
    return mutate


def _other_reason(entry):
    if entry.decision != "abstain":
        return entry
    other = next(reason for reason in contracts.GATE_ABSTENTION_REASONS if reason != entry.abstention_reason)
    assert other in contracts.ABSTENTION_REASONS
    return entry.model_copy(update={"abstention_reason": other})


def _more_render_attempts(entry):
    return entry.model_copy(update={"counts": entry.counts.model_copy(update={"render_attempts": entry.counts.render_attempts + 1})})


def _learner_dependent_top_k(monkeypatch) -> None:
    """The pipeline asks for one more span for the 0.9 learner, and the retrieval itself still uses the packaged
    top_k: the bundle, the record and the old five fields stay equal, and only the retrieval call differs."""
    real_retrieve = pipeline_module.retrieve
    real_run = TwoPassPipeline.run

    def run(self, item, **kwargs):
        if _LEARNER["mastery"] != 0.9:
            return real_run(self, item, **kwargs)
        params = self.params
        self.params = dataclasses.replace(params, top_k=params.top_k + 1)
        try:
            return real_run(self, item, **kwargs)
        finally:
            self.params = params

    monkeypatch.setattr(TwoPassPipeline, "run", run)
    monkeypatch.setattr(pipeline_module, "retrieve", lambda engine, request, *, top_k, registry: real_retrieve(
        engine, request, top_k=packaged_top_k(), registry=registry))


def packaged_top_k() -> int:
    return get_config_package(Settings()).tutor_pipeline.top_k


LEARNER_DEPENDENT = {
    # A learner-dependent abstention reason: the decision, spans and hash stay equal (finding K1 named it).
    "abstention_reason": lambda monkeypatch: _patch_entry(monkeypatch, _other_reason),
    "counts": lambda monkeypatch: _patch_entry(monkeypatch, _more_render_attempts),
    # A learner-dependent floor, margin or sufficiency score that leaves the same results above it.
    "floor": lambda monkeypatch: _patch_bundle(monkeypatch, _sufficiency(floor=lambda value: value + 0.001)),
    "margin": lambda monkeypatch: _patch_bundle(monkeypatch, _sufficiency(margin=lambda value: value + 0.001)),
    "sufficiency_score": lambda monkeypatch: _patch_bundle(monkeypatch, _sufficiency(score=lambda value: (value or 0.0) + 0.001)),
    # Plan 12.4(c) and CT-04: an identical top-k.
    "top_k": _learner_dependent_top_k,
}


@pytest.mark.parametrize("field", sorted(LEARNER_DEPENDENT))
def test_k1_each_learner_dependent_value_fails_the_invariant_1_fixture(monkeypatch, field):
    from test_phase3_acceptance import observe_three_learners

    monkeypatch.setitem(_LEARNER, "mastery", None)
    LEARNER_DEPENDENT[field](monkeypatch)
    observed, captured, _ = observe_three_learners(monkeypatch, prefix=f"k1-{field.replace('_', '-')}",
                                                   on_learner=lambda mastery: _LEARNER.__setitem__("mastery", mastery))
    # The comparison before the ninth round could not see it: its five fields are equal for all three learners.
    assert all([_old_projection(item) for item in learner] == [_old_projection(item) for item in observed[0]] for learner in observed)
    # The fixture does: the 0.1 and 0.5 learners agree and the 0.9 learner differs.
    assert observed[1] == observed[0] and observed[2] != observed[0]
    differing = [index for index, (item, other) in enumerate(zip(observed[2], observed[0])) if item != other]
    assert differing
    if field == "top_k":
        top_ks = {call["top_k"] for call in captured["requests"]}
        assert len(top_ks) == 2 and all(observed[2][index]["retrieve"] != observed[0][index]["retrieve"] for index in differing)
        assert all(observed[2][index]["record"] == observed[0][index]["record"] for index in range(len(observed[0])))
    else:
        assert all(observed[2][index]["record"] != observed[0][index]["record"] for index in differing)
    if field == "abstention_reason":
        assert any(item["record"]["decision"] == "abstain" for item in observed[2])


def _perturbed(value):
    if isinstance(value, bool):
        return not value
    if isinstance(value, (int, float)):
        return value + 1
    if isinstance(value, str):
        return value + "-other"
    if value is None:
        return "other"
    if isinstance(value, list):
        return [*value, {"other": 1}]
    if isinstance(value, dict):
        return {**value, "other": 1}
    raise AssertionError(type(value))


def _leaves(value, path=()):
    """Every leaf of a JSON value (an empty list or object counts as one), with its path."""
    if isinstance(value, dict) and value:
        for key, item in value.items():
            yield from _leaves(item, (*path, key))
    elif isinstance(value, list) and value:
        for index, item in enumerate(value):
            yield from _leaves(item, (*path, index))
    else:
        yield path, value


def _set(document, path, value):
    target = document
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value


IDS = {("response_id",), ("shadowed_response_id",)}


def _is_id(path) -> bool:
    """The fields that name the response, the turn it shadows and the learner's own turns: learner_independent leaves
    out exactly these."""
    return (path in IDS or path[:2] == ("resolved_question", "source_turn_ids")
            or (len(path) == 3 and path[0] == "claims" and path[2] == "response_id"))


def test_k1_the_compared_record_keeps_every_field_of_the_shadow_record_but_its_ids(monkeypatch):
    from test_phase3_acceptance import entry_of, learner_independent, observe_three_learners, records

    observed, _, _ = observe_three_learners(monkeypatch, prefix="k1-leaves")
    entries = [entry_of(row) for row in records(delivery="shadow")[-len(observed[0]) * 3:]]
    answered = next(entry for entry in entries if entry["decision"] == "answer" and entry["claims"])
    abstained = next(entry for entry in entries if entry["decision"] == "abstain")
    checked = 0
    for entry in (answered, abstained):
        reference = learner_independent(entry)
        for path, value in _leaves(entry):
            changed = copy.deepcopy(entry)
            _set(changed, path, _perturbed(value))
            if _is_id(path):
                assert learner_independent(changed) == reference, path
            else:
                assert learner_independent(changed) != reference, path
                checked += 1
    # The fields plan 7.8 invariant 1, 12.4(c) and CT-04 name are among those compared.
    named = {("abstention_reason",), ("retrieval", "floor"), ("retrieval", "margin"), ("retrieval", "threshold_version"),
             ("retrieval", "sufficiency", "decision"), ("retrieval", "sufficiency", "floor"), ("counts", "render_attempts")}
    assert named <= {path for path, _ in _leaves(abstained)} | {path for path, _ in _leaves(answered)}
    assert checked > 60


def test_k1_the_retrieval_call_the_fixture_records_holds_the_top_k_the_pipeline_passed(monkeypatch):
    from test_phase3_acceptance import observe_three_learners

    observed, captured, _ = observe_three_learners(monkeypatch, prefix="k1-topk")
    assert {call["top_k"] for call in captured["requests"]} == {packaged_top_k()}
    assert all(item["retrieve"]["top_k"] == packaged_top_k() for learner in observed for item in learner)
