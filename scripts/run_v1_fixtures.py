"""V1 adversarial fixtures and their report (plan Phase 4 F "hashed adversarial fixtures; report with Wilson
intervals", H, K AC-4-2 and AC-4-3, L stop conditions; Phase 4 spec section 12).

Run: python scripts/run_v1_fixtures.py --write docs/evaluation/phase4/v1_fixture_report_v1.json [--allow-dirty]
     python scripts/run_v1_fixtures.py --check docs/evaluation/phase4/v1_fixture_report_v1.json

The fixture file (docs/evaluation/phase4/v1_adversarial_fixtures_v1.json) holds public-corpus cases only, never ULQS
(plan H, E-95: anything under lqs/ is refused); it holds no corpus text: the sentences an attack changes are taken from
the store at run time, and its own sentences are synthetic. Each case is hashed (canonical sha256) and the set hash is
pinned in the shipped configuration package (v1.fixtures). The runner builds the all-public-approved store (a temporary
manifest approving every public-plane, bound item) in development with V1_PIPELINE=enforce and MODEL_GATEWAY=off (the
report measures V1 alone; scripts/run_v2_fixtures.py measures V2), and runs every case in
two checker configurations:
  production          the NullChecker (D-21 none): V1.3 flags every claim, so nothing is delivered (D-20)
  deterministic_only  a fake always-SUPPORTED checker: what the deterministic checks catch alone
A case's own checker (raising, late) replaces either. The fixture overlay (a test-only version family over two
document items, and a 50 ms checker timeout) is applied to V1Params in memory; no package is ever written.

The report: per check the hard-fail results, the runs with a hard fail and the hard-fail rate per run (spec 10.3, as
V1_METRICS counts it), the V1.3 flag rate, the resolution of delivered citations, the finals, the catch rate of each
class with its Wilson 95% interval, the residual class (paraphrased contradiction, an implementation-defined case of
plan M's "checker error": only an entailment checker could catch it, so it is withheld under production and delivered
under deterministic_only), the V1 p95 latency (measured; compared with the package budget only), the in-domain answer
rate under V1.5 for each gate against the Phase 2 baseline (AC-4-3) and the composition counts, and the readability
envelope. It is labelled "fixture measurements, not research results" (plan H). `commit` is informational: the HEAD
the record was written on, + "-dirty" when the tree differed from it (--allow-dirty); `inputs` (the LF sha256 of every
imported repository module) is the provenance --check compares.

Exit codes: 0 pass; 1 drift (--check: the record differs from a fresh run, created_at, commit and latency values
aside) or an unrealisable case; 3 a plan L stop (an answer rate below its floor, V1 adding an in-domain abstention under
deterministic_only, or the p95 above its budget); 4 a dirty tree on --write; 5 a non-residual case delivered in either
configuration, or a residual delivered under production.
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Callable
import dataclasses
from datetime import UTC, datetime
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
for path in (REPO_ROOT, API_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import os  # noqa: E402

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.core.config import Settings  # noqa: E402
from app.core.config_package import ConfigPackage, canonical_sha256, get_config_package  # noqa: E402
from app.core.manifest_v2 import with_all_public_approved  # noqa: E402
from app.services.content_assembler import CourseStore  # noqa: E402
from app.services.retrieval_engine import RetrievalEngine  # noqa: E402
from app.services.tutor_pipeline.bind import LockedClaimDraft, claim_id_for, whole_sentences  # noqa: E402
from app.services.tutor_pipeline.contracts import (  # noqa: E402
    ClaimPlan,
    EvidenceBundle,
    EvidenceSpan,
    GeneratorRef,
    PresentationPlan,
    ProposedClaim,
    RenderedResponse,
    Segment,
    Sufficiency,
)
from app.services.tutor_pipeline.evidential import ExtractiveD19Generator  # noqa: E402
from app.services.tutor_pipeline.lock import lock  # noqa: E402
from app.services.tutor_pipeline.pipeline import PipelineInput, TwoPassPipeline  # noqa: E402
from app.services.tutor_pipeline.render import TEMPLATES, TemplateRenderer, layout_text  # noqa: E402
from app.services.tutor_pipeline.resolve import LearnerTurn, resolve_turns  # noqa: E402
from app.services.tutor_pipeline.text import normalise, sentences  # noqa: E402
from app.services.v1_checks.lexicon import alignment_terms, knorm, negation_cues, numbers, quantities  # noqa: E402
from app.services.v1_checks.metrics import checks_run, hard_failed_checks  # noqa: E402
from app.services.v1_checks.package_check import fixture_set_sha256  # noqa: E402
from app.services.v1_checks.v1_1_resolution import resolution_problem  # noqa: E402
from app.services.v1_checks.v1_3_entailment import EntailmentResult, NullChecker, check_v1_3  # noqa: E402
from app.services.v1_checks.v1_6_keyed_answers import KeyedItem  # noqa: E402
from app.services.v1_checks.v1_7_conflicts import check_v1_7  # noqa: E402
from app.services.v1_checks.v1_8_misconceptions import MisconceptionEntry, MisconceptionLibrary  # noqa: E402
from app.services.v1_checks.v1_9_schema_readability import syllables  # noqa: E402
from app.services.v1_checks.rules import ALPHA_PATTERN, FK  # noqa: E402

DEFAULT_FIXTURES = REPO_ROOT / "docs" / "evaluation" / "phase4" / "v1_adversarial_fixtures_v1.json"
DEFAULT_REPORT = REPO_ROOT / "docs" / "evaluation" / "phase4" / "v1_fixture_report_v1.json"
SCORE_FLOOR_FIXTURE = API_ROOT / "tests" / "data" / "score_floor_queries.json"
REPO_MANIFEST = REPO_ROOT / "corpus" / "public" / "manifest.json"
EVIDENCE_CLASS = "fixture measurements, not research results (plan Phase 4 H)"
CLASSES = (
    "stripped_negation", "inserted_negation", "number_swap", "unit_swap", "fabricated_sentence_generator", "fabricated_sentence_renderer",
    "unresolvable_span_id", "conflict_version", "conflict_number", "conflict_negation", "keyed_answer_leak", "out_of_scope",
    "checker_unavailable", "invalid_schema", "misconception", "residual_paraphrased_contradiction",
)
MIN_CASES = {"stripped_negation": 5, "inserted_negation": 5, "number_swap": 5, "unit_swap": 5, "fabricated_sentence_generator": 5,
             "fabricated_sentence_renderer": 3, "unresolvable_span_id": 5, "conflict_version": 3, "conflict_number": 3,
             "conflict_negation": 3, "keyed_answer_leak": 3, "out_of_scope": 10, "checker_unavailable": 2, "invalid_schema": 3,
             "misconception": 3, "residual_paraphrased_contradiction": 3}
RESIDUAL_CLASSES = ("residual_paraphrased_contradiction",)
CONFIGURATIONS = ("production", "deterministic_only")
GATES = ("bm25f-v1", "p1-floor")
CASE_GATE = "bm25f-v1"
PHASE2_BASELINE_KEYS = {"bm25f-v1": "bm25", "p1-floor": "p1_floor_span_index"}
CALIBRATION_RECORD = REPO_ROOT / "docs" / "evaluation" / "phase2" / "calibration_record_v1.json"
Z95 = 1.959964
EXIT_DRIFT = 1
EXIT_STOP = 3
EXIT_DIRTY = 4
EXIT_DELIVERED = 5
INPUTS_RULE = "imported-repository-modules-sha256-lf-v1"
INPUT_PREFIXES = ("apps/api/app/", "scripts/")
SELF = "scripts/run_v1_fixtures.py"
NEGATION_STRIP = (
    (re.compile(r"\bcannot\b", re.IGNORECASE), "can"),
    (re.compile(r"(\w)n['’]t\b", re.IGNORECASE), r"\1"),
    (re.compile(r"\b(?:not|never|no|without|none|nothing|nobody|nowhere|neither|nor)\s+", re.IGNORECASE), ""),
)
NEGATION_INSERT = re.compile(r"\b(is|are|was|were|can|will|does|do|should|could|may|must|has|have)\b", re.IGNORECASE)
# A fixed unit table over lexicon units (and %): each unit maps to another of a different kind.
UNIT_SWAPS = {"%": "x", "x": "%", "qubit": "bit", "qubits": "bits", "bit": "qubit", "bits": "qubits", "k": "x", "kb": "mb", "mb": "kb",
              "ms": "ns", "ns": "ms", "us": "ms", "µs": "ms", "μs": "ms", "s": "ms", "sec": "ms", "seconds": "ms", "ghz": "mhz", "mhz": "ghz",
              "khz": "hz", "hz": "khz", "cm": "nm", "nm": "cm", "db": "w", "w": "db", "mw": "w", "mk": "k"}
_TEMP = tempfile.TemporaryDirectory(prefix="qcai-v1-fixtures-")
TEMP_ROOT = Path(_TEMP.name)


class Unrealisable(RuntimeError):
    """A case whose query does not hold the feature its attack needs (exit 1, naming the case)."""


def _refuse_lqs(path: Path) -> None:
    resolved = Path(path).resolve()
    parts = resolved.relative_to(REPO_ROOT.resolve()).parts if resolved.is_relative_to(REPO_ROOT.resolve()) else resolved.parts
    if "lqs" in parts:
        raise SystemExit(f"refused: {path} is under lqs/; ULQS items MUST NOT be used by the V1 fixtures (plan Phase 4 H)")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def wilson95(successes: int, total: int) -> list[float] | None:
    if total == 0:
        return None
    rate = successes / total
    denominator = 1 + Z95 ** 2 / total
    centre = (rate + Z95 ** 2 / (2 * total)) / denominator
    half = Z95 * math.sqrt(rate * (1 - rate) / total + Z95 ** 2 / (4 * total ** 2)) / denominator
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]


def nearest_rank_p95(samples: list[float]) -> float | None:
    ordered = sorted(samples)
    if not ordered:
        return None
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


# ------------------------------------------------------------------------------------------------------ fakes


class AlwaysSupportedChecker:
    checker_model_id = "fixture-always-supported"

    def check(self, claim: str, spans: tuple[str, ...]) -> EntailmentResult:
        return EntailmentResult("SUPPORTED", 1.0)


class RaisingChecker:
    checker_model_id = "fixture-raising"

    def check(self, claim: str, spans: tuple[str, ...]) -> EntailmentResult:
        raise RuntimeError("checker unavailable (fixture)")


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class LateChecker:
    """Answers SUPPORTED, but only after its injected clock passed the timeout (no sleeping)."""

    checker_model_id = "fixture-late"

    def __init__(self, clock: FakeClock, step_ms: float) -> None:
        self.clock = clock
        self.step_ms = step_ms

    def check(self, claim: str, spans: tuple[str, ...]) -> EntailmentResult:
        self.clock.now += self.step_ms / 1000.0
        return EntailmentResult("SUPPORTED", 1.0)


class FixtureKeys:
    def __init__(self, items: tuple[KeyedItem, ...]) -> None:
        self._items = items

    def items(self) -> tuple[KeyedItem, ...]:
        return self._items


def strip_negation(text: str, lexicon) -> str | None:
    if not sum(negation_cues(text, lexicon).values()):
        return None
    for pattern, replacement in NEGATION_STRIP:
        changed = pattern.sub(replacement, text, count=1)
        if changed != text and sum(negation_cues(changed, lexicon).values()) < sum(negation_cues(text, lexicon).values()):
            return changed
    return None


def insert_negation(text: str, lexicon) -> str | None:
    match = NEGATION_INSERT.search(text)
    if match is None:
        return None
    return text[: match.end()] + " not" + text[match.end():]


def swap_number(text: str, lexicon) -> str | None:
    match = re.search(r"(?<![\w.])(\d+)", text)
    if match is None:
        return None
    return text[: match.start()] + str(int(match.group(1)) + 1) + text[match.end():]


def swap_unit(text: str, lexicon) -> str | None:
    pattern = re.compile(r"(?<![\w.])(\d+(?:[.,]\d+)*)(\s*)(%|[A-Za-zµμ]+)")
    for match in pattern.finditer(text):
        unit = match.group(3)
        target = UNIT_SWAPS.get(unit.casefold())
        if target is not None and (unit == "%" or unit.casefold() in lexicon.units):
            spacer = "" if target == "%" else (match.group(2) or " ")
            return text[: match.start(3) - len(match.group(2))] + spacer + target + text[match.end(3):]
    return None


TRANSFORMS: dict[str, Callable] = {"strip_negation": strip_negation, "insert_negation": insert_negation, "number_swap": swap_number, "unit_swap": swap_unit}


class FixtureGenerator:
    """Wraps the D-19 extractive generator and applies one case's attack to its plan, the same on every call."""

    def __init__(self, inner: ExtractiveD19Generator, attack: dict, *, lexicon, families: dict[str, str]) -> None:
        self.inner = inner
        self.ref = inner.ref
        self.attack = attack
        self.lexicon = lexicon
        self.families = families
        self.attacked: tuple[str, tuple[str, ...]] | None = None
        self.bad_span_id: str | None = None
        self.calls = 0

    def propose(self, envelope):
        self.calls += 1
        plan = self.inner.propose(envelope)
        kind = self.attack["kind"]
        claims = list(plan.claims)
        if kind == "claim_transform":
            transform = TRANSFORMS[self.attack["transform"]]
            for index, claim in enumerate(claims):
                changed = transform(claim.text, self.lexicon)
                if changed is not None and normalise(changed) != normalise(claim.text):
                    claims[index] = ProposedClaim(text=changed, span_ids=claim.span_ids)
                    self.attacked = (changed, tuple(claim.span_ids))
                    break
        elif kind == "generator_fabrication":
            if envelope.evidence:
                span_id = envelope.evidence[0].span_id
                claims.append(ProposedClaim(text=self.attack["sentence"], span_ids=(span_id,)))
                self.attacked = (self.attack["sentence"], (span_id,))
        elif kind == "span_id" and claims:
            original = claims[0].span_ids[0]
            form = self.attack["form"]
            bad = {"nonexistent": "span-" + _sha(f"fixture-nonexistent-{self.attack.get('seed', '')}"),
                   "malformed": "span-not-a-span-id", "uppercase": original.upper()}[form]
            claims[0] = ProposedClaim(text=claims[0].text, span_ids=(bad, *claims[0].span_ids[1:]))
            self.bad_span_id = bad
        elif kind == "compose_from_items":
            item_of = {span.span_id: span.item_id for span in self._bundle_spans}
            composed = []
            for item in self.attack["items"]:
                span = next((span for span in envelope.evidence if item_of.get(span.span_id) == item), None)
                if span is None:
                    return ClaimPlan(generator=self.ref, claims=())
                params = self.inner.params
                piece = next(iter(sentences(span.text, min_words=params.min_sentence_words, max_chars=params.max_sentence_chars)), None)
                if piece is None:
                    return ClaimPlan(generator=self.ref, claims=())
                composed.append(ProposedClaim(text=" ".join(piece.split()), span_ids=(span.span_id,)))
            self.attacked = ("composed", ())
            return ClaimPlan(generator=self.ref, claims=tuple(composed))
        elif kind == "schema":
            form = self.attack["form"]
            if form == "extra_field":
                self.attacked = ("schema", ())
                return {**plan.model_dump(mode="json"), "extra_field": True}
            if form == "other_generator":
                self.attacked = ("schema", ())
                other = GeneratorRef(generator_id="fixture-other-generator", model_id="fixture-other-generator", kind="extractive",
                                     prompt_hash=self.ref.prompt_hash)
                return ClaimPlan(generator=other, claims=plan.claims)
        return ClaimPlan(generator=self.ref, claims=tuple(claims))

    _bundle_spans: tuple = ()


class UnmappedRenderer:
    """Adds an unmapped factual sentence to the template rendering on the given attempts (all when None)."""

    renderer_id = TemplateRenderer.renderer_id

    def __init__(self, inner: TemplateRenderer, sentence: str, fail_attempts: tuple[int, ...] | None = None) -> None:
        self.inner = inner
        self.sentence = sentence
        self.fail_attempts = fail_attempts

    def render(self, locked, plan, *, attempt: int, **options):
        rendered = self.inner.render(locked, plan, attempt=attempt, **options)
        if self.fail_attempts is not None and attempt not in self.fail_attempts:
            return rendered
        segments = list(rendered.segments)
        line = next(segment.line for segment in segments if segment.kind == "claim")
        segments.append(Segment(kind="claim", line=line, text=self.sentence, claim_id="claim-" + "0" * 32))
        segments.sort(key=lambda segment: segment.line)
        return rendered.model_copy(update={"segments": tuple(segments), "text": layout_text(segments)})


class InvalidEnvelopeRenderer:
    """Returns a rendering that no RenderedResponse validates (built with model_construct)."""

    renderer_id = TemplateRenderer.renderer_id

    def render(self, locked, plan, *, attempt: int, **options):
        return RenderedResponse.model_construct(renderer_id=self.renderer_id, plan_id=plan.plan_id, attempt=0, segments=(), citations=(), text="")


# ------------------------------------------------------------------------------------------------ environment


class Gate:
    """One gate's all-approved store, with the enforce and the V1-off settings over it (no dataclass: the script is
    also loaded by file path, without a sys.modules entry)."""

    def __init__(self, gate: str, settings: Settings, off_settings: Settings, store: CourseStore) -> None:
        self.gate, self.settings, self.off_settings, self.store = gate, settings, off_settings, store


_STORES: dict[str, CourseStore] = {}


def _approved_manifest() -> Path:
    target = TEMP_ROOT / "manifest.json"
    if not target.exists():
        target.write_text(json.dumps(with_all_public_approved(json.loads(REPO_MANIFEST.read_text(encoding="utf-8")))), encoding="utf-8")
    return target


def gate_environment(gate: str) -> Gate:
    manifest = _approved_manifest()
    settings = Settings(environment="development", enforce_corpus_governance=True, corpus_manifest_path=str(manifest), retrieval_gate=gate,
                        two_pass_tutor="shadow", v1_pipeline="enforce", model_gateway="off", ehmf="off", ranking="off")
    off = Settings(environment="development", enforce_corpus_governance=True, corpus_manifest_path=str(manifest), retrieval_gate=gate,
                   two_pass_tutor="shadow", v1_pipeline="off", model_gateway="off", ehmf="off", ranking="off")
    if gate not in _STORES:
        _STORES[gate] = CourseStore(settings)
    return Gate(gate=gate, settings=settings, off_settings=off, store=_STORES[gate])


def overlay_v1(package: ConfigPackage, overlay: dict):
    """The package's V1Params with the fixture overlay (test-only families, the checker timeout), in memory only."""
    families = dict(package.v1.version_families)
    for family in overlay.get("v1_7.version_families", []):
        for item in family["item_ids"]:
            families[item] = family["family"]
    return dataclasses.replace(package.v1, version_families=families, checker_timeout_ms=int(overlay.get("v1_3.timeout_ms", package.v1.checker_timeout_ms)))


def _input(pipeline: TwoPassPipeline, query: str) -> PipelineInput:
    resolved = resolve_turns([], LearnerTurn(f"message-{uuid4()}", query), package=pipeline.package)
    return PipelineInput(resolved=resolved, lesson_slug=None, presentation=PresentationPlan(plan_id="concise", source="request"),
                         response_id=f"shadow-{uuid4()}", delivery="shadow", shadowed_response_id=f"turn-{uuid4()}")


def _pipeline(env: Gate, v1, *, off: bool = False, generator=None, renderer=None, checker=None, keyed=None, library=None,
              clock=None, settings: Settings | None = None, pipeline_options: dict | None = None) -> TwoPassPipeline:
    """settings and pipeline_options (a gateway, an adapter registry, a cache, a session factory) let the Phase 7
    golden-set runner realise a case with MODEL_GATEWAY and EHMF on; the defaults are this report's own run."""
    settings = settings if settings is not None else (env.off_settings if off else env.settings)
    pipeline = TwoPassPipeline(RetrievalEngine(env.store, settings), settings, generator=generator, renderer=renderer, checker=checker,
                               keyed_items=keyed, misconceptions=library, **(pipeline_options or {}))
    pipeline.v1_params = v1
    if clock is not None:
        pipeline.v1_clock = clock
    return pipeline


def _checker(configuration: str):
    return NullChecker() if configuration == "production" else AlwaysSupportedChecker()


def _empty_keys() -> FixtureKeys:
    return FixtureKeys(())


def _library(entries, *, version: str = "fixture") -> MisconceptionLibrary:
    payload = [{"id": entry["id"], "terms": sorted(entry["terms"])} for entry in entries]
    return MisconceptionLibrary(version=version, sha256=canonical_sha256(payload),
                                entries=tuple(MisconceptionEntry(entry_id=entry["id"], terms=tuple(entry["terms"])) for entry in payload))


EMPTY_LIBRARY = _library([], version="fixture-empty")


# -------------------------------------------------------------------------------------------------- the cases


def _delivered_claim_texts(result) -> list[str]:
    record = result.entry.verification
    finals = {verdict.claim_id: verdict.final for verdict in record.verdicts}
    return [claim.text for claim in result.v1.locked.claims if finals.get(claim.claim_id) == "deliver"]


def _caught_on_claim(record, claim_id: str) -> list[str]:
    return sorted({result.check_id for result in record.checks if result.claim_id == claim_id and result.outcome != "pass"})


def _non_pass_checks(record, *, outcomes=("hard_fail", "abstain", "flag", "mark")) -> list[str]:
    return sorted({result.check_id for result in record.checks if result.outcome in outcomes})


def _base_locked(env: Gate, v1, query: str):
    """The locked claims of a plain V1-off run of the query (the claims an attack is applied to)."""
    return _pipeline(env, v1, off=True).run(_input(_pipeline(env, v1, off=True), query), record=False)


def run_pipeline_case(case: dict, env: Gate, v1, configuration: str, fixtures: dict, *, settings: Settings | None = None,
                      pipeline_options: dict | None = None) -> tuple[dict, object]:
    attack = case["attack"]
    kind = attack["kind"]
    package = get_config_package(env.settings)
    lexicon = v1.lexicon
    base = ExtractiveD19Generator(package)
    generator = FixtureGenerator(base, attack, lexicon=lexicon, families=dict(v1.version_families))
    renderer = None
    checker = _checker(configuration)
    keyed = _empty_keys()
    library = EMPTY_LIBRARY
    clock = None
    if kind == "renderer_fabrication":
        renderer = UnmappedRenderer(TemplateRenderer(package), attack["sentence"])
    if kind == "schema" and attack["form"] == "invalid_envelope":
        renderer = InvalidEnvelopeRenderer()
    if kind == "checker":
        if attack["checker"] == "raising":
            checker = RaisingChecker()
        else:
            clock = FakeClock()
            checker = LateChecker(clock, v1.checker_timeout_ms + 1)
    key_text = None
    if kind == "keyed":
        spec = next(item for item in fixtures["fixture_keys"] if item["item_id"] == attack["key"])
        base_run = _base_locked(env, v1, spec["key"]["from_query"])
        claims = base_run.locked.claims
        if len(claims) <= spec["key"]["claim"] or len(claims) < 2:
            raise Unrealisable(case["id"])
        key_text = claims[spec["key"]["claim"]].text
        keyed = FixtureKeys((KeyedItem(item_id=spec["item_id"], lesson_slug="fixture-lesson", prompt=spec["prompt"], choices=(), answer=key_text),))
    if kind == "misconception":
        library = _library([entry for entry in fixtures["fixture_library"] if entry["id"] == attack["entry"]])
    pipeline = _pipeline(env, v1, generator=generator, renderer=renderer, checker=checker, keyed=keyed, library=library, clock=clock,
                         settings=settings, pipeline_options=pipeline_options)
    item = _input(pipeline, case["query"])
    if kind == "compose_from_items":
        # The generator needs the bundle's item ids; the pipeline retrieves exactly this bundle.
        from app.services.tutor_pipeline.retrieve import build_request, retrieve

        request = build_request(item.resolved, lesson_slug=None, corpus_version=env.store.corpus_version)
        generator._bundle_spans = retrieve(pipeline.engine, request, top_k=pipeline.params.top_k, registry=pipeline.registry).spans
    result = pipeline.run(item, record=False)
    record = result.entry.verification
    final = record.final
    realised: dict = {"query_sha256": _sha(case["query"])}
    if kind in ("claim_transform", "generator_fabrication"):
        if generator.attacked is None:
            raise Unrealisable(case["id"])
        text, spans = generator.attacked
        realised["claim_sha256"] = _sha(text)
        claim_id = claim_id_for(text, spans)
        caught_by = _caught_on_claim(record, claim_id)
        delivered = any(normalise(delivered_text) == normalise(text) for delivered_text in _delivered_claim_texts(result))
    elif kind == "renderer_fabrication":
        caught_by = sorted({r.check_id for r in record.checks if r.stage == "post_render" and r.outcome == "hard_fail"})
        delivered = final == "deliver" and result.v1.rendered is not None and attack["sentence"] in result.v1.rendered.text
        realised["sentence_sha256"] = _sha(attack["sentence"])
    elif kind == "span_id":
        if generator.bad_span_id is None:
            raise Unrealisable(case["id"])
        realised["span_id_sha256"] = _sha(generator.bad_span_id)
        caught_by = sorted({r.check_id for r in record.checks if r.check_id == "V1.1" and r.outcome == "hard_fail"})
        delivering = {v.claim_id for v in record.verdicts if v.final == "deliver"}
        delivered = final != "abstain" and any(generator.bad_span_id in claim.span_ids for claim in result.v1.locked.claims if claim.claim_id in delivering)
    elif kind == "compose_from_items":
        item_of = {span.span_id: span.item_id for span in result.bundle.spans}
        locked_items = {item_of.get(span_id) for span_id in result.v1.locked.span_ids}
        if generator.attacked is None or not set(attack["items"]) <= locked_items:
            raise Unrealisable(case["id"])
        involved = {claim_id for pair in (record.disclosure.conflicts if record.disclosure else ()) for claim_id in pair.claim_ids}
        caught_by = sorted({r.check_id for r in record.checks if r.check_id == "V1.7" and r.outcome == "flag"})
        withheld_policy = record.disclosure is not None and record.disclosure.policy == "withhold"
        delivered = (final == "deliver" and record.disclosure is None) or (
            withheld_policy and any(v.final == "deliver" and v.claim_id in involved for v in record.verdicts))
    elif kind == "keyed":
        realised["key_sha256"] = _sha(key_text)
        caught_by = sorted({r.check_id for r in record.checks if r.check_id == "V1.6" and r.outcome == "hard_fail"})
        if not caught_by:
            raise Unrealisable(case["id"])
        delivered = result.v1.rendered is not None and knorm(key_text) in knorm(result.v1.rendered.text)
    elif kind == "none":
        caught_by = sorted({r.check_id for r in record.checks if r.check_id == "V1.5" and r.outcome == "abstain"})
        delivered = final != "abstain"
    elif kind == "checker":
        caught_by = sorted({r.check_id for r in record.checks if r.check_id == "V1.3" and r.outcome == "abstain"})
        if not result.v1.locked.claims:
            raise Unrealisable(case["id"])
        delivered = final != "abstain"
    elif kind == "schema":
        caught_by = sorted({r.check_id for r in record.checks if r.check_id == "V1.9" and r.outcome == "hard_fail"})
        if attack["form"] != "invalid_envelope" and generator.attacked is None:
            raise Unrealisable(case["id"])
        delivered = final != "abstain"
    elif kind == "misconception":
        matched = {r.claim_id for r in record.checks if r.check_id == "V1.8" and r.outcome == "flag"}
        if not matched:
            raise Unrealisable(case["id"])
        caught_by = sorted({r.check_id for r in record.checks if r.claim_id in matched and r.outcome != "pass"})
        delivered = any(v.final == "deliver" and v.claim_id in matched for v in record.verdicts)
    else:  # pragma: no cover - the fixture loader refuses unknown kinds
        raise ValueError(kind)
    return {
        "id": case["id"],
        "case_sha256": canonical_sha256(case),
        "final": final,
        "final_reason": record.final_reason,
        "caught_by": caught_by,
        "delivered": bool(delivered),
        "realised": realised,
    }, result


def run_check_case(case: dict, env: Gate, v1, configuration: str) -> dict:
    """A conflict case at check level: a real claim of the query and a twin sentence on a synthetic second item."""
    attack = case["attack"]
    package = get_config_package(env.settings)
    lexicon = v1.lexicon
    stopwords = package.retrieval.stopwords
    base = _base_locked(env, v1, case["query"])
    change = attack["change"]

    def suitable(text: str) -> bool:
        terms = alignment_terms(text, lexicon, stopwords)
        return len(terms) >= v1.min_alignment_terms and (change != "number" or (bool(numbers(text, lexicon)) and swap_number(text, lexicon) is not None))

    claim = next((claim for claim in base.locked.claims if suitable(claim.text)), None)
    if claim is None:
        raise Unrealisable(case["id"])
    if change == "number":
        twin = swap_number(claim.text, lexicon)
    elif change == "negation":
        twin = strip_negation(claim.text, lexicon) if sum(negation_cues(claim.text, lexicon).values()) else insert_negation(claim.text, lexicon)
        twin = twin or "It is not the case that " + claim.text[:1].lower() + claim.text[1:]
    else:
        terms = sorted(alignment_terms(claim.text, lexicon, stopwords))[:2]
        twin = f"Contrary to some accounts, it is not true that {terms[0]} or {terms[1]} matter much here, according to a different source."
    if twin is None:
        raise Unrealisable(case["id"])
    twin_span = "span-" + _sha(f"fixture-twin-{case['id']}")
    item_of = {span.span_id: span for span in base.bundle.spans}
    spans = [item_of[span_id] for span_id in claim.span_ids if span_id in item_of]
    twin_evidence = EvidenceSpan(span_id=twin_span, item_id="fixture-item-twin", item_version="fixture", kind="document", char_start=0,
                                 char_end=len(twin), content_hash=_sha(twin), score=None, near_floor=False, license_class="public", quotable=True)
    bundle = EvidenceBundle(corpus_version=base.bundle.corpus_version, index_version=base.bundle.index_version, retrieval_mode="lexical",
                            spans=(*spans, twin_evidence), sufficiency=base.bundle.sufficiency)
    drafts = [LockedClaimDraft(claim_id=claim.claim_id, text=claim.text, span_ids=claim.span_ids, source_order=tuple(claim.source_order)),
              LockedClaimDraft(claim_id=claim_id_for(twin, [twin_span]), text=twin, span_ids=(twin_span,), source_order=("fixture-item-twin", 0))]
    pipeline = _pipeline(env, v1)
    locked = lock(drafts, bundle=bundle, generator=pipeline.generator.ref, evidential_prompt_hash=pipeline.generator.ref.prompt_hash,
                  pedagogical_prompt_hash=pipeline.params.pedagogical_prompt_hash, resolver=base.locked.resolver, package=package)

    def sentences_of(span_id: str) -> tuple[str, ...]:
        if span_id == twin_span:
            return (twin,)
        record = env.store.span_registry.get(span_id)
        params = pipeline.params
        return tuple(s.text for s in whole_sentences(record, env.store, min_words=params.min_sentence_words, max_chars=params.max_sentence_chars)) if record else ()

    conflict, block = check_v1_7(locked, bundle, sentences_of=sentences_of, v1=v1, stopwords=stopwords, attempt=1)
    entailment = check_v1_3(locked, {}, checker=_checker(configuration), v1=v1, attempt=1)
    flagged = {result.claim_id for result in entailment if result.outcome == "flag"}
    caught_by = sorted({*(["V1.7"] if block is not None else []), *(["V1.3"] if claim.claim_id in flagged else [])})
    return {
        "id": case["id"],
        "case_sha256": canonical_sha256(case),
        "final": "disclose" if block is not None else ("withhold" if claim.claim_id in flagged else "deliver"),
        "final_reason": conflict.reason_code,
        "caught_by": caught_by,
        "delivered": block is None and claim.claim_id not in flagged,
        "realised": {"query_sha256": _sha(case["query"]), "claim_sha256": _sha(claim.text), "twin_sha256": _sha(twin)},
    }


# ------------------------------------------------------------------------------------------------- the report


def load_fixtures(path: Path) -> dict:
    _refuse_lqs(path)
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = payload.get("cases") or []
    unknown = sorted({case.get("class") for case in cases} - set(CLASSES))
    if unknown:
        raise SystemExit(f"refused: unknown fixture classes {unknown}")
    return payload


def _per_check(records) -> dict:
    """Per check: the runs it ran in, its results by outcome (hard_fail, flag, abstain, mark count results), and the
    hard-fail rate as V1_METRICS and the runbook define it (spec 10.3): the runs in which it hard-failed at least once
    (hard_fail_runs) over the runs in which it ran."""
    block = {}
    for check in ("V1.1", "V1.2", "V1.3", "V1.4", "V1.5", "V1.6", "V1.7", "V1.8", "V1.9"):
        runs = sum(1 for record in records if check in checks_run(record))
        hard_fail_runs = sum(1 for record in records if check in hard_failed_checks(record))
        outcomes = Counter(result.outcome for record in records for result in record.checks if result.check_id == check)
        block[check] = {"runs": runs, "hard_fail": outcomes.get("hard_fail", 0), "hard_fail_runs": hard_fail_runs,
                        "hard_fail_rate": round(hard_fail_runs / runs, 6) if runs else None,
                        "flag": outcomes.get("flag", 0), "abstain": outcomes.get("abstain", 0), "mark": outcomes.get("mark", 0)}
    return block


def _resolution(results, env: Gate) -> dict:
    """V-1 over the fixture runs: the span ids of delivered claims, and how many resolve in the current corpus."""
    resolver = _resolver(env)
    span_ids = resolved = 0
    for result in results:
        record = result.entry.verification
        delivering = {verdict.claim_id for verdict in record.verdicts if verdict.final == "deliver"}
        for claim in result.v1.locked.claims:
            if claim.claim_id in delivering:
                for span_id in claim.span_ids:
                    span_ids += 1
                    resolved += int(resolution_problem(span_id, result.bundle, resolver) is None)
    return {"span_ids": span_ids, "resolved": resolved, "rate": round(resolved / span_ids, 6) if span_ids else None}


def _resolver(env: Gate):
    from app.services.span_resolver import SpanResolver

    return SpanResolver(env.store)


def run_configuration(name: str, fixtures: dict, env: Gate, v1, budget_ms: int, latencies: list[float]) -> dict:
    case_rows = []
    pipeline_results = []
    for case in fixtures["cases"]:
        if case["level"] == "check":
            case_rows.append({**run_check_case(case, env, v1, name), "class": case["class"], "expected": case["expect"]["caught_by"]})
            continue
        row, result = run_pipeline_case(case, env, v1, name, fixtures)
        case_rows.append({**row, "class": case["class"], "expected": case["expect"]["caught_by"]})
        pipeline_results.append(result)
        latencies.append(result.v1.latency_ms)
    records = [result.entry.verification for result in pipeline_results]
    classes = {}
    for class_name in CLASSES:
        rows = [row for row in case_rows if row["class"] == class_name]
        caught = sum(1 for row in rows if not row["delivered"])
        by = Counter(check for row in rows for check in row["caught_by"])
        classes[class_name] = {"cases": len(rows), "caught": caught, "catch_rate": round(caught / len(rows), 6) if rows else None,
                               "wilson95": wilson95(caught, len(rows)), "caught_by": dict(sorted(by.items())),
                               "delivered": sum(1 for row in rows if row["delivered"])}
    v1_3 = [result for record in records for result in record.checks if result.check_id == "V1.3" and result.claim_id is not None]
    flagged = sum(1 for result in v1_3 if result.outcome == "flag")
    p95 = nearest_rank_p95(latencies)
    return {
        "name": name,
        "checker_model_id": _checker(name).checker_model_id,
        "per_check": _per_check(records),
        "v1_3_flag_rate": {"checked": len(v1_3), "flagged": flagged, "rate": round(flagged / len(v1_3), 6) if v1_3 else None},
        "citation_resolution_delivered": _resolution(pipeline_results, env),
        "finals": {final: sum(1 for record in records if record.final == final) for final in ("deliver", "withhold", "abstain")},
        "classes": classes,
        "residual": list(RESIDUAL_CLASSES),
        "cases": [{key: row[key] for key in ("id", "case_sha256", "final", "final_reason", "caught_by", "delivered", "realised")} for row in case_rows],
        "expected_missing": sorted(row["id"] for row in case_rows if not set(row["expected"]) <= set(row["caught_by"])),
        "latency": {"p95_ms": None if p95 is None else round(p95, 3), "budget_ms": budget_ms, "within_budget": p95 is None or p95 <= budget_ms},
    }


def _has_document_span(bundle) -> bool:
    return any(span.kind == "document" for span in bundle.spans)


def answer_rate_block(env: Gate, v1, latencies: list[float], track_hook: Callable | None = None) -> dict:
    """AC-4-3 for one gate: the Phase 2 answer-rate definition over V1.5's decision on the 174 in-domain items, the
    out-of-scope abstentions, and the composition counts with V1 off, under deterministic_only and under production."""
    fixture = json.loads(SCORE_FLOOR_FIXTURE.read_text(encoding="utf-8"))
    in_domain = [item["query"] for item in fixture["in_domain"]]
    off_topic = list(fixture["off_topic"]) + list(fixture["stopword_only"])
    off = _pipeline(env, v1, off=True)
    deterministic = _pipeline(env, v1, checker=AlwaysSupportedChecker(), keyed=_empty_keys(), library=EMPTY_LIBRARY)
    production = _pipeline(env, v1, checker=NullChecker(), keyed=_empty_keys(), library=EMPTY_LIBRARY)
    if track_hook is not None:
        track_hook(deterministic)
    v1_5 = composition_off = composition_b = composition_a = identical = 0
    for query in in_domain:
        plain = off.run(_input(off, query), record=False)
        checked = deterministic.run(_input(deterministic, query), record=False)
        withheld = production.run(_input(production, query), record=False)
        latencies.extend([checked.v1.latency_ms, withheld.v1.latency_ms])
        record = checked.entry.verification
        if any(r.check_id == "V1.5" and r.outcome != "abstain" for r in record.checks) and _has_document_span(checked.bundle):
            v1_5 += 1
        composition_off += int(plain.decision == "answer")
        composition_b += int(checked.decision == "answer")
        composition_a += int(withheld.entry.verification.final != "abstain")
        same = (plain.decision == checked.decision and plain.locked.claim_set_hash == checked.locked.claim_set_hash
                and plain.entry.rendered_text_sha256 == checked.entry.rendered_text_sha256)
        identical += int(same)
    abstained_off = 0
    for query in off_topic:
        checked = deterministic.run(_input(deterministic, query), record=False)
        abstained_off += int(any(r.check_id == "V1.5" and r.outcome == "abstain" for r in checked.entry.verification.checks)
                             and checked.entry.verification.final == "abstain")
    floor_answered, floor_in_domain = v1.answer_rate_floor[env.gate]
    calibration = json.loads(CALIBRATION_RECORD.read_text(encoding="utf-8"))
    return {
        "gate": env.gate,
        "in_domain": len(in_domain),
        "v1_5_answered": v1_5,
        "rate": f"{v1_5}/{len(in_domain)}",
        "wilson95": wilson95(v1_5, len(in_domain)),
        "floor": f"{floor_answered}/{floor_in_domain}",
        "phase2_baseline": calibration["answer_rate"][PHASE2_BASELINE_KEYS[env.gate]],
        "off_topic": len(off_topic),
        "off_topic_v1_5_abstained": abstained_off,
        "composition_answered_v1_off": composition_off,
        "composition_answered_v1_b": composition_b,
        "composition_answered_v1_a_not_abstain": composition_a,
        "composition_identical_b": identical,
    }


def readability_envelope(env: Gate, v1) -> dict:
    alpha = re.compile(ALPHA_PATTERN)
    params = get_config_package(env.settings).tutor_pipeline
    texts = set()
    for record in env.store.span_registry.records:
        if record.item_kind == "document":
            texts.update(s.text for s in whole_sentences(record, env.store, min_words=params.min_sentence_words, max_chars=params.max_sentence_chars))
    texts.update(text.format(1) for kind, text in TEMPLATES.values() if kind != "citation")
    per_sentence, per_word = [], []
    for text in texts:
        words = alpha.findall(text)
        if words:
            per_sentence.append(len(words))
            per_word.append(sum(syllables(word) for word in words) / len(words))
    low = round(FK[0] * min(per_sentence) + FK[1] * min(per_word) - FK[-1], 2)
    high = round(FK[0] * max(per_sentence) + FK[1] * max(per_word) - FK[-1], 2)
    band = [v1.readability_min, v1.readability_max]
    return {"min_grade": low, "max_grade": high, "band": band, "contained": band[0] <= low and high <= band[1]}


def text_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def run_inputs() -> dict:
    """The code the run used, by content (the replay's rule, imported-repository-modules-sha256-lf-v1)."""
    root = REPO_ROOT.resolve()
    files: dict[str, str] = {}
    for module in list(sys.modules.values()):
        location = getattr(module, "__file__", None)
        if not location or not str(location).endswith(".py"):
            continue
        path = Path(location).resolve()
        if not path.is_relative_to(root):
            continue
        relative = path.relative_to(root).as_posix()
        if relative.startswith(INPUT_PREFIXES):
            files[relative] = text_sha256(path)
    files[SELF] = text_sha256(Path(__file__).resolve())
    ordered = dict(sorted(files.items()))
    return {"rule": INPUTS_RULE, "files": ordered, "sha256": canonical_sha256(ordered)}


def input_problems(inputs: dict, root: Path = REPO_ROOT) -> list[str]:
    problems = []
    if inputs.get("rule") != INPUTS_RULE:
        problems.append(f"unknown inputs rule {inputs.get('rule')!r}")
    files = inputs.get("files") or {}
    if canonical_sha256(dict(sorted(files.items()))) != inputs.get("sha256"):
        problems.append("the inputs digest does not match its file map")
    for relative, digest in sorted(files.items()):
        path = Path(root) / relative
        if not path.is_file():
            problems.append(f"{relative} is listed but missing")
        elif text_sha256(path) != digest:
            problems.append(f"{relative} differs from the code the record ran")
    return problems


def compute(*, fixtures_path: Path = DEFAULT_FIXTURES, package: ConfigPackage | None = None, gates=GATES, answer_rate: bool = True,
            commit_source: Callable[[], str] | None = None, track_hook: Callable | None = None) -> dict:
    fixtures = load_fixtures(fixtures_path)
    case_env = gate_environment(CASE_GATE)
    package = package or get_config_package(case_env.settings)
    v1 = overlay_v1(package, fixtures.get("fixture_package") or {})
    budget = package.v1.p95_budget_ms
    configurations = []
    latencies: dict[str, list[float]] = {}
    for name in CONFIGURATIONS:
        latencies[name] = []
        configurations.append(run_configuration(name, fixtures, case_env, v1, budget, latencies[name]))
    answer_rates = []
    if answer_rate:
        shared: list[float] = []
        for gate in gates:
            answer_rates.append(answer_rate_block(gate_environment(gate), dataclasses.replace(package.v1), shared, track_hook=track_hook))
        p95 = nearest_rank_p95(shared + [value for values in latencies.values() for value in values])
    else:
        p95 = nearest_rank_p95([value for values in latencies.values() for value in values])
    cases = fixtures["cases"]
    report = {
        "report": "qcai-v1-fixture-report",
        "format_version": 1,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "commit": (commit_source or _commit)(),
        "evidence_class": EVIDENCE_CLASS,
        "public_corpus_only": True,
        "fixtures": {"path": _relative(fixtures_path), "set_sha256": fixture_set_sha256(cases), "cases": len(cases)},
        "config_package": {"version": package.package_version, "sha256": package.sha256},
        "fixture_overlay_sha256": canonical_sha256(fixtures.get("fixture_package") or {}),
        "configurations": configurations,
        "answer_rate": answer_rates,
        "readability_envelope": readability_envelope(case_env, package.v1),
        "latency": {"p95_ms": None if p95 is None else round(p95, 3), "budget_ms": budget, "within_budget": p95 is None or p95 <= budget},
    }
    report["result"], report["problems"] = evaluate(report, package)
    report["inputs"] = run_inputs()
    return report


def _relative(path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return Path(path).name


def evaluate(report: dict, package: ConfigPackage) -> tuple[str, list[str]]:
    """("pass" | "delivered" | "stop", problems) of a report against a package's stop conditions (plan Phase 4 L)."""
    v1 = package.v1
    delivered, stops = [], []
    for configuration in report["configurations"]:
        for name, block in configuration["classes"].items():
            residual = name in RESIDUAL_CLASSES
            if block["delivered"] and (not residual or configuration["name"] == "production"):
                delivered.append(f"{configuration['name']}: {block['delivered']} {name} case(s) delivered")
        if configuration["name"] == "production" and configuration["finals"]["deliver"]:
            delivered.append("production: a response was delivered with no checker (D-20)")
        if configuration["name"] == "deterministic_only" and configuration["expected_missing"]:
            delivered.append(f"deterministic_only: expected checks missed {configuration['expected_missing']}")
    for block in report["answer_rate"]:
        floor_answered, floor_in_domain = v1.answer_rate_floor[block["gate"]]
        if block["v1_5_answered"] * floor_in_domain < floor_answered * block["in_domain"]:
            stops.append(f"{block['gate']}: the V1.5 answer rate {block['rate']} is below its floor {floor_answered}/{floor_in_domain}")
        if block["composition_answered_v1_b"] < block["composition_answered_v1_off"]:
            stops.append(f"{block['gate']}: V1 adds in-domain abstentions under deterministic_only "
                         f"({block['composition_answered_v1_b']} < {block['composition_answered_v1_off']})")
    latency = report["latency"]
    if latency["p95_ms"] is not None and latency["p95_ms"] > v1.p95_budget_ms:
        stops.append(f"the V1 p95 latency {latency['p95_ms']} ms is above its budget {v1.p95_budget_ms} ms")
    if delivered:
        return "delivered", delivered + stops
    if stops:
        return "stop", stops
    return "pass", []


def exit_code(report: dict) -> int:
    return {"pass": 0, "stop": EXIT_STOP, "delivered": EXIT_DELIVERED}[report["result"]]


def _strip_volatile(value):
    """The report without created_at, commit and every latency value (--check compares the rest)."""
    if isinstance(value, dict):
        return {key: _strip_volatile(item) for key, item in value.items() if key not in {"created_at", "commit", "latency"}}
    if isinstance(value, list):
        return [_strip_volatile(item) for item in value]
    return value


DIRTY_SUFFIX = "-dirty"


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, timeout=30)


def _commit() -> str:
    try:
        head = _git("rev-parse", "HEAD").stdout.strip()
        if not head:
            return "unknown"
        status = _git("status", "--porcelain")
        return head + (DIRTY_SUFFIX if status.returncode != 0 or status.stdout.strip() else "")
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _is_commit(value: str) -> bool:
    return len(value) == 40 and not set(value) - set("0123456789abcdef")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", type=Path)
    mode.add_argument("--check", type=Path)
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--allow-dirty", action="store_true", help="--write from a working tree that differs from HEAD")
    args = parser.parse_args(argv)
    target = args.write or args.check
    _refuse_lqs(args.fixtures)
    _refuse_lqs(target)
    if args.write and not args.allow_dirty and not _is_commit(_commit()):
        print("refused: the working tree differs from HEAD; commit first, or pass --allow-dirty", file=sys.stderr)
        return EXIT_DIRTY
    try:
        fresh = compute(fixtures_path=args.fixtures)
    except Unrealisable as exc:
        print(f"V1 fixtures failed: case {exc} does not realise its attack (choose another query)", file=sys.stderr)
        return EXIT_DRIFT
    if args.write:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        args.write.write_text(json.dumps(fresh, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {args.write}: result {fresh['result']}")
    else:
        committed = json.loads(args.check.read_text(encoding="utf-8"))
        if _strip_volatile(committed) != _strip_volatile(fresh):
            differing = sorted(key for key in set(committed) | set(fresh)
                               if key not in {"created_at", "commit", "latency"} and _strip_volatile(committed.get(key)) != _strip_volatile(fresh.get(key)))
            print(f"V1 fixture check failed: the record differs from a fresh run in: {', '.join(differing)}", file=sys.stderr)
            return EXIT_DRIFT
        print(f"V1 fixture record is current: result {fresh['result']}")
    for configuration in fresh["configurations"]:
        caught = sum(block["caught"] for block in configuration["classes"].values())
        total = sum(block["cases"] for block in configuration["classes"].values())
        print(f"  {configuration['name']}: {caught}/{total} cases caught; finals {configuration['finals']}")
    for block in fresh["answer_rate"]:
        print(f"  {block['gate']}: V1.5 answer rate {block['rate']} (floor {block['floor']}, Phase 2 {block['phase2_baseline']}); "
              f"composition {block['composition_answered_v1_b']} with V1, {block['composition_answered_v1_off']} without")
    print(f"  V1 p95 {fresh['latency']['p95_ms']} ms (budget {fresh['latency']['budget_ms']} ms); {EVIDENCE_CLASS}")
    for problem in fresh["problems"]:
        print(f"  {problem}", file=sys.stderr)
    return exit_code(fresh)


if __name__ == "__main__":
    sys.exit(main())
