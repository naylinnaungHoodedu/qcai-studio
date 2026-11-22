"""Fakes for the Phase 4 V1 tests (Phase 4 spec 13.1): scripted entailment checkers, a V2 hook that counts its calls,
a fixture keyed-item source, a fixture misconception library, a renderer that adds an unmapped sentence on chosen
attempts, and a package copy with edited v1 values. No learner data."""

from __future__ import annotations

from collections.abc import Sequence
import copy
import json
from pathlib import Path
import shutil

from app.core.config_package import DEFAULT_PACKAGE_PATH, canonical_sha256, misconception_library_sha256
from app.services.tutor_pipeline.contracts import Segment
from app.services.tutor_pipeline.render import layout_text
from app.services.v1_checks.v1_3_entailment import EntailmentResult
from app.services.v1_checks.v1_6_keyed_answers import KeyedItem
from app.services.v1_checks.v1_8_misconceptions import MisconceptionEntry, MisconceptionLibrary


class AlwaysSupportedChecker:
    checker_model_id = "fixture-always-supported"

    def check(self, claim, spans):
        return EntailmentResult("SUPPORTED", 1.0)


class AlwaysContradictedChecker:
    checker_model_id = "fixture-always-contradicted"

    def check(self, claim, spans):
        return EntailmentResult("CONTRADICTED", 0.9)


class RaisingChecker:
    checker_model_id = "fixture-raising"

    def check(self, claim, spans):
        raise RuntimeError("checker unavailable (test)")


class WrongTypeChecker:
    checker_model_id = "fixture-wrong-type"

    def check(self, claim, spans):
        return {"label": "SUPPORTED"}


class InjectedClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class LateChecker:
    """Answers SUPPORTED after advancing an injected clock by clock_step_ms (no sleeping)."""

    checker_model_id = "fixture-late"

    def __init__(self, clock: InjectedClock, clock_step_ms: float) -> None:
        self.clock = clock
        self.clock_step_ms = clock_step_ms

    def check(self, claim, spans):
        self.clock.now += self.clock_step_ms / 1000.0
        return EntailmentResult("SUPPORTED", 1.0)


class ScriptedChecker:
    """Returns the next scripted (label, score) per call, repeating the last."""

    checker_model_id = "fixture-scripted"

    def __init__(self, labels: Sequence[tuple[str, float | None]]) -> None:
        self.labels = list(labels)
        self.calls = 0

    def check(self, claim, spans):
        label, score = self.labels[min(self.calls, len(self.labels) - 1)]
        self.calls += 1
        return EntailmentResult(label, score)


class SupportedVoter:
    """A V2 hook that would vote SUPPORTED on everything; it counts the decisions it is shown."""

    def __init__(self) -> None:
        self.calls = 0
        self.seen: list = []

    def consult(self, passed):
        self.calls += 1
        self.seen.append(passed)
        return "SUPPORTED"


class FixtureKeys:
    def __init__(self, items: Sequence[KeyedItem]) -> None:
        self._items = tuple(items)

    def items(self):
        return self._items


def keyed_item(item_id: str, prompt: str, answer: str, choices: Sequence[str] = ()) -> KeyedItem:
    return KeyedItem(item_id=item_id, lesson_slug="fixture-lesson", prompt=prompt, choices=tuple(choices), answer=answer)


def fixture_library(entries: Sequence[tuple[str, Sequence[str]]], version: str = "fixture") -> MisconceptionLibrary:
    payload = [{"id": entry_id, "terms": sorted(terms)} for entry_id, terms in entries]
    return MisconceptionLibrary(version=version, sha256=canonical_sha256(payload),
                                entries=tuple(MisconceptionEntry(entry_id=item["id"], terms=tuple(item["terms"])) for item in payload))


class UnmappedRenderer:
    """Adds an unmapped factual sentence on the given attempts (every attempt when fail_attempts is None)."""

    def __init__(self, inner, fail_attempts: Sequence[int] | None, sentence: str = "Quantum hardware will be error free within one year.") -> None:
        self.inner = inner
        self.renderer_id = inner.renderer_id
        self.fail_attempts = None if fail_attempts is None else tuple(fail_attempts)
        self.sentence = sentence
        self.attempts: list[int] = []

    def render(self, locked, plan, *, attempt: int, **options):
        self.attempts.append(attempt)
        rendered = self.inner.render(locked, plan, attempt=attempt, **options)
        if self.fail_attempts is not None and attempt not in self.fail_attempts:
            return rendered
        segments = list(rendered.segments)
        line = next(segment.line for segment in segments if segment.kind == "claim")
        segments.append(Segment(kind="claim", line=line, text=self.sentence, claim_id="claim-" + "0" * 32))
        segments.sort(key=lambda segment: segment.line)
        return rendered.model_copy(update={"segments": tuple(segments), "text": layout_text(segments)})


def temp_package(tmp_path: Path, edit=None, **v1_overrides) -> Path:
    """A copy of package v3 (with schemas/) whose v1 block is edited, rehashed where a hash pins it, with a sidecar."""
    from app.services.v1_checks.rules import v1_rules_hash
    from app.core.config_package import parse_config_package

    raw = copy.deepcopy(json.loads(DEFAULT_PACKAGE_PATH.read_text(encoding="utf-8")))
    for dotted, value in v1_overrides.items():
        target = raw["v1"]
        keys = dotted.split("__")
        for key in keys[:-1]:
            target = target[key]
        target[keys[-1]] = value
    if edit is not None:
        edit(raw)
    library = raw["v1"]["v1_8"]["library"]
    library["sha256"] = misconception_library_sha256(library)
    path = tmp_path / "package" / "v3.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not (path.parent / "schemas").exists():
        shutil.copytree(DEFAULT_PACKAGE_PATH.parent / "schemas", path.parent / "schemas")
    raw["v1"]["rules_hash"] = v1_rules_hash(parse_config_package(raw, path=path, sha256="", hash_verified=False))
    path.write_text(json.dumps(raw), encoding="utf-8")
    path.with_name("v3.json.sha256").write_text(canonical_sha256(raw) + "\n", encoding="utf-8")
    return path


# --------------------------------------------------------------------------------------------------- pipelines

MULTI_CLAIM = "Explain why quantum logistics needs both problem reduction before execution and routing control during compilation."


def dev_pipeline(settings=None, **kwargs):
    """A two-pass pipeline over the dev store (V1_PIPELINE=enforce, the development default, unless settings say else)."""
    from app.core.config import Settings
    from app.services.retrieval_engine import RetrievalEngine
    from app.services.store import get_course_store
    from app.services.tutor_pipeline.pipeline import TwoPassPipeline

    settings = settings or Settings()
    return TwoPassPipeline(RetrievalEngine(get_course_store(), settings), settings, **kwargs)


def run(pipeline, query: str, plan_id: str = "concise", *, legacy_decision=None, record: bool = False, budget_ms=None, lesson_slug=None):
    from uuid import uuid4

    from app.services.tutor_pipeline.contracts import PresentationPlan
    from app.services.tutor_pipeline.pipeline import PipelineInput
    from app.services.tutor_pipeline.resolve import LearnerTurn, resolve_turns

    resolved = resolve_turns([], LearnerTurn(f"message-{uuid4()}", query), package=pipeline.package)
    return pipeline.run(PipelineInput(resolved=resolved, lesson_slug=lesson_slug, presentation=PresentationPlan(plan_id=plan_id, source="request"),
                                      response_id=f"shadow-{uuid4()}", delivery="shadow", shadowed_response_id=f"turn-{uuid4()}",
                                      legacy_decision=legacy_decision), record=record, budget_ms=budget_ms)
