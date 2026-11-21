"""Phase 3: no span that is not public reaches a bundle, a span route or a ledger record (plan Phase 3 H; spec 4.3,
7.12).

C1  license_class is derived from the span's plane and the manifest, and a span that is not public is never emitted:
    not by the bundle, either span route or the legacy record.
L8  a bundle the license gate empties abstains at retrieval, and `top` is the first result the gate kept.
Each test fails if its defect comes back; the spec's review history (18.4) names the round behind each group.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from app.api.routes import spans as spans_route
from app.core.config import Settings
from app.core.config_package import get_config_package
from app.core.corpus_governance import CorpusRegistry, get_corpus_registry
from app.main import app
from app.services.contained_answers import contain_answer
from app.services.ledger import build_legacy_entry, legacy_delivery_for
from app.services.provenance import native_citation
from app.services.retrieval_engine import RetrievalEngine
from app.services.store import get_course_store, get_span_resolver
from app.services.tutor_pipeline import pipeline as pipeline_module
from app.services.tutor_pipeline.contracts import PresentationPlan, RetrievalRequest
from app.services.tutor_pipeline.metrics import LEDGER_METRICS, LICENSE_METRICS
from app.services.tutor_pipeline.pipeline import PipelineInput, TwoPassPipeline
from app.services.tutor_pipeline.resolve import LearnerTurn, resolve_turns
from app.services.tutor_pipeline.retrieve import build_request, retrieve


PACKAGE = get_config_package(Settings())
IN_DOMAIN = "Why does routing depth matter?"
client = TestClient(app)
API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parents[1]
SPEC = (REPO_ROOT / "docs" / "architecture" / "phase3-implementation-spec.md").read_text(encoding="utf-8")
PARAMS = PACKAGE.tutor_pipeline
MULTI_CLAIM = "Explain why quantum logistics needs both problem reduction before execution and routing control during compilation."


@pytest.fixture
def clean_metrics():
    LEDGER_METRICS.reset()
    LICENSE_METRICS.reset()
    yield


class ForcedSpans:
    """The course store's span registry with some records replaced: spans that the upstream guards (the span builder
    refuses non-public items, the index takes only indexable files) should never let exist."""

    def __init__(self, base, forced: dict) -> None:
        self.base, self.forced = base, forced

    def get(self, span_id):
        return self.forced.get(span_id) or self.base.get(span_id)

    def __getattr__(self, name):
        return getattr(self.base, name)


def _section(title: str, end: str) -> str:
    return SPEC.split(title, 1)[1].split(end, 1)[0]


def _pipeline_run(pipeline: TwoPassPipeline, query: str, *, record: bool = False):
    resolved = resolve_turns([], LearnerTurn(f"message-{uuid4()}", query), package=pipeline.package)
    return pipeline.run(PipelineInput(resolved=resolved, lesson_slug=None, presentation=PresentationPlan(plan_id="concise", source="request"),
                                      response_id=f"shadow-{uuid4()}", delivery="shadow", shadowed_response_id=f"turn-{uuid4()}"), record=record)


# =============================================================================================================== C1


def test_c1_the_license_class_is_derived_from_the_records_plane_and_the_manifest(monkeypatch):
    registry = get_corpus_registry(Settings())
    record = next(r for r in get_course_store().span_registry.records if r.item_kind == "document")
    assert registry.license_class(plane=record.plane, item_id=record.item_id, source_filename=record.source_filename) == "public"
    for plane in ("private", None, "", "PUBLIC"):
        assert registry.license_class(plane=plane, item_id=record.item_id, source_filename=record.source_filename) is None
    monkeypatch.setattr(registry, "is_private_item", lambda item_id: item_id == record.item_id)
    assert registry.license_class(plane="public", item_id=record.item_id) is None
    monkeypatch.setattr(registry, "is_private_item", lambda item_id: False)
    monkeypatch.setattr(registry, "is_private_plane", lambda filename: filename == record.source_filename)
    assert registry.license_class(plane="public", item_id=record.item_id, source_filename=record.source_filename) is None


def test_c1_a_forced_non_public_record_never_reaches_the_bundle_and_is_counted(monkeypatch, clean_metrics):
    settings = Settings()
    store = get_course_store()
    engine = RetrievalEngine(store, settings)
    registry = get_corpus_registry(settings)
    request = RetrievalRequest(text=IN_DOMAIN, corpus_version=store.corpus_version)
    baseline = retrieve(engine, request, top_k=4, registry=registry)
    assert len(baseline.spans) >= 2 and {span.license_class for span in baseline.spans} == {"public"}
    victim = baseline.spans[0].span_id
    monkeypatch.setattr(store, "span_registry", ForcedSpans(store.span_registry, {victim: dataclasses.replace(store.span_registry.get(victim), plane="private")}))
    bundle = retrieve(engine, request, top_k=4, registry=registry)
    assert [span.span_id for span in bundle.spans] == [span.span_id for span in baseline.spans[1:]]
    assert {span.license_class for span in bundle.spans} == {"public"}
    assert LICENSE_METRICS.snapshot()["two_pass"] == 1
    # Every result forced: nothing quotable is left, so the bundle abstains (never "evidence" with no span).
    everything = {span.span_id: dataclasses.replace(store.span_registry.get(span.span_id), plane="private") for span in baseline.spans}
    monkeypatch.setattr(store, "span_registry", ForcedSpans(store.span_registry.base, everything))
    empty = retrieve(engine, request, top_k=4, registry=registry)
    assert (empty.spans, empty.sufficiency.decision, empty.sufficiency.reason) == ((), "abstain", "no_quotable_evidence")
    # A manifest that moves the item to the private plane excludes it too, whatever the record says.
    monkeypatch.setattr(store, "span_registry", store.span_registry.base)
    item_id = store.span_registry.get(victim).item_id
    monkeypatch.setattr(registry, "is_private_item", lambda candidate: candidate == item_id)
    assert all(store.span_registry.get(span.span_id).item_id != item_id for span in retrieve(engine, request, top_k=4, registry=registry).spans)


def test_c1_the_span_routes_refuse_a_span_whose_class_is_not_public_even_if_the_resolver_returns_it(monkeypatch):
    record = next(r for r in get_course_store().span_registry.records if r.item_kind == "document")
    paths = (f"/spans/{record.span_id}", f"/evidence/spans/{record.span_id}")
    for path in paths:
        served = client.get(path, headers={"x-forwarded-for": f"hardening-{uuid4().hex}"})
        assert served.status_code == 200 and served.json()["license_class"] == "public"
    real = get_span_resolver()

    class LeakyResolver:
        def __init__(self, plane: str) -> None:
            self.plane = plane

        def resolve(self, span_id, db=None):
            resolved = real.resolve(span_id, db)
            return dataclasses.replace(resolved, plane=self.plane) if resolved is not None else None

    monkeypatch.setattr(spans_route, "get_span_resolver", lambda: LeakyResolver("private"))
    for path in paths:
        refused = client.get(path, headers={"x-forwarded-for": f"hardening-{uuid4().hex}"})
        assert (refused.status_code, refused.json(), refused.headers["cache-control"]) == (404, {"detail": "Span not found."}, "no-store")
    # The resolver says public, but the manifest puts the item on the private plane: the route's own gate refuses it.
    monkeypatch.setattr(spans_route, "get_span_resolver", lambda: LeakyResolver("public"))
    monkeypatch.setattr(CorpusRegistry, "is_private_item", lambda self, item_id: item_id == record.item_id)
    for path in paths:
        assert client.get(path, headers={"x-forwarded-for": f"hardening-{uuid4().hex}"}).status_code == 404


def _contained(settings: Settings):
    store = get_course_store()
    hits = [hit for hit in store.search(IN_DOMAIN, top_k=8) if hit.source_kind == "document"]
    citations = [native_citation(hit, corpus_version=store.corpus_version, settings=settings) for hit in hits]
    return contain_answer(citations, get_corpus_registry(settings), store.span_registry, settings=settings)


def test_c1_the_legacy_record_never_labels_or_records_a_non_public_quotation(clean_metrics):
    settings = Settings()
    store = get_course_store()
    registry = get_corpus_registry(settings)
    contained = _contained(settings)
    assert contained.decision == "answer" and len(contained.claims) >= 2
    victim = contained.claims[0].cited_span_ids[0]
    forced = SimpleNamespace(index=store.index, index_version=store.index_version, gate=store.gate,
                             span_registry=ForcedSpans(store.span_registry, {victim: dataclasses.replace(store.span_registry.get(victim), plane="private")}))
    delivery = legacy_delivery_for(response_id=f"turn-{uuid4()}", contained=contained, retrieval=None, store=forced, registry=registry,
                                   retrieval_mode="lexical", provider="none", model="test", policy_version="test", surface="tutor")
    citing = sum(1 for claim in contained.claims if victim in claim.cited_span_ids)
    assert victim not in {span.span_id for span in delivery.quoted} and delivery.dropped_not_public == citing
    entry = build_legacy_entry(delivery, settings=settings, package=PACKAGE, manifest_sha256=None)
    assert entry.counts.dropped == {"not_public": citing}
    assert victim not in entry.span_ids and all(victim not in claim.span_ids for claim in entry.claims)
    assert entry.retrieval.evidence and {span.license_class for span in entry.retrieval.evidence} == {"public"}
    assert LICENSE_METRICS.snapshot()["legacy"] == 1
    # Unforced, the same answer records every quotation.
    plain = legacy_delivery_for(response_id=f"turn-{uuid4()}", contained=contained, retrieval=None, store=store, registry=registry,
                                retrieval_mode="lexical", provider="none", model="test", policy_version="test", surface="tutor")
    assert plain.dropped_not_public == 0 and len(plain.claims) == len(contained.claims)


# =============================================================================================================== L8


def test_l8_a_bundle_the_license_gate_empties_abstains_at_retrieval_and_top_is_the_first_kept_result(monkeypatch):
    settings = Settings()
    engine = RetrievalEngine(get_course_store(), settings)
    pipeline = TwoPassPipeline(engine, settings)
    registry = pipeline.registry
    resolved = resolve_turns([], LearnerTurn(f"message-{uuid4()}", MULTI_CLAIM), package=PACKAGE)
    request = build_request(resolved, lesson_slug=None, corpus_version=engine.store.corpus_version)
    baseline = retrieve(engine, request, top_k=PARAMS.top_k, registry=registry)
    assert baseline.sufficiency.decision != "abstain" and len(baseline.spans) >= 2
    original = registry.license_class
    calls: list[int] = []

    def drop_the_first(**kwargs):
        calls.append(1)
        return None if len(calls) == 1 else original(**kwargs)

    monkeypatch.setattr(registry, "license_class", drop_the_first)
    kept = retrieve(engine, request, top_k=PARAMS.top_k, registry=registry)
    assert [span.span_id for span in kept.spans] == [span.span_id for span in baseline.spans[1:]]
    # The first kept result's gate score (Phase 4 spec 4.6; its display score is that score rounded), not the top-ranked one's.
    gate_scores = engine.evidence(request.text, lesson_slug=request.lesson_slug, top_k=PARAMS.top_k).gate_scores
    assert kept.sufficiency.score == gate_scores[baseline.spans[1].span_id] != baseline.sufficiency.score
    assert round(kept.sufficiency.score, 4) == baseline.spans[1].score
    monkeypatch.setattr(registry, "license_class", lambda **kwargs: None)
    emptied = retrieve(engine, request, top_k=PARAMS.top_k, registry=registry)
    assert emptied.spans == () and (emptied.sufficiency.decision, emptied.sufficiency.reason) == ("abstain", "no_quotable_evidence")

    def no_envelope_step(*args, **kwargs):
        raise AssertionError("the envelope step runs only for a bundle that did not abstain")

    monkeypatch.setattr(pipeline_module, "build_envelope", no_envelope_step)
    result = _pipeline_run(pipeline, MULTI_CLAIM)
    assert (result.decision, result.abstention_reason, result.envelope) == ("abstain", "no_quotable_evidence", None)
    section_4_3 = _section("### 4.3 Retrieve", "### 4.4")
    assert "the license gate dropped every one: `abstain`, reason `no_quotable_evidence`, at this retrieval step" in section_4_3
    assert "`top` = the first result the license gate kept" in section_4_3 and "the top-ranked result unless" in section_4_3
    assert "A bundle the license gate emptied never reaches this step" in _section("### 4.5 Evidential pass", "### 4.6")
    assert "`no_quotable_evidence` when the license gate dropped every result (4.3)" in _section("### 4.10 Pipeline", "### 4.11")
