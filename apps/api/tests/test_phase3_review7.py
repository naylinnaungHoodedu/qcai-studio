"""Phase 3, seventh review round (2026-11-19; Phase 3 spec 18.10). Each test fails if its defect comes back.

H1  binding locks only whole document sentences: a span-edge fragment of a longer sentence never binds
    (partial_sentence), the envelope carries only whole sentences, and every locked claim of the public replay is a
    sentences-v2 sentence of its document section lying wholly inside each span it cites.
H2  the stepwise plan's "in source order" holds for two sentences of one span (source_order is the sentence's place).
H3  the package's pipeline version, resolver and renderer ids, Idempotency-Key header, presentation plans and default
    plan are compared with the code, and /ready reports the code's values.
H4  the AC-3-2 record test and the committed-record check run no process (in test_phase3_acceptance.py; the scan here).
H5  POST /tutor/turns and POST /assistant/chat share one rate-limit window.
H6, H7  the ledger records (spec 4.12, conflict 29, 7.16, 8.1, 8.2, the model comment, the migration and guard
    comments) say what the code does.
H8  spec 7.17 says the record names its code by `inputs`, and its report shape has the block.
H9  STATUS.md's Phase 3 row counts the review rounds the phase record holds (where the evidence package is present).
"""

from __future__ import annotations

import ast
import copy
from functools import lru_cache
import json
from pathlib import Path
import re
from types import SimpleNamespace
from typing import get_args
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.routes import assistant as assistant_route
from app.core.config import Settings
from app.core.config_package import DEFAULT_PACKAGE_PATH, get_config_package, parse_config_package
from app.main import app
from app.services.retrieval_engine import RetrievalEngine
from app.services.span_resolver import SpanResolver
from app.services.store import get_course_store
from app.services.tutor_pipeline import contracts
from app.services.tutor_pipeline.bind import BINDING_RULE, bind, claim_id_for, whole_sentence_text, whole_sentences
from app.services.tutor_pipeline.contracts import (
    ClaimPlan,
    EvidenceBundle,
    EvidenceSpan,
    GeneratorRef,
    PresentationPlan,
    ProposedClaim,
    ResolverRef,
    Sufficiency,
)
from app.services.tutor_pipeline.evidential import ExtractiveD19Generator
from app.services.tutor_pipeline.lock import lock
from app.services.tutor_pipeline.package_check import check_tutor_pipeline_package
from app.services.tutor_pipeline.pipeline import PIPELINE_VERSION, PipelineInput, TwoPassPipeline
from app.services.tutor_pipeline.render import PLANS_LAYOUT, RENDERER_ID, TEMPLATES, TemplateRenderer
from app.services.tutor_pipeline.resolve import RESOLVER_ID, LearnerTurn, resolve_turns
from app.services.tutor_pipeline.text import content_terms, sentence_bounds, sentences, split_sentences, whitespace
from app.services.turn_idempotency import IDEMPOTENCY_HEADER

API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parents[1]
BEP_ROOT = REPO_ROOT.parent / "BEP-2-12"
SPEC = (REPO_ROOT / "docs" / "architecture" / "phase3-implementation-spec.md").read_text(encoding="utf-8")
ADR = (REPO_ROOT / "docs" / "adr" / "ADR-001-grounding-separation.md").read_text(encoding="utf-8")
README = (REPO_ROOT / "docs" / "evaluation" / "phase3" / "README.md").read_text(encoding="utf-8")
DATA = Path(__file__).parent / "data"
RAW = json.loads(DEFAULT_PACKAGE_PATH.read_text(encoding="utf-8"))
PACKAGE = get_config_package(Settings())
PARAMS = PACKAGE.tutor_pipeline
IN_DOMAIN = [item["query"] for item in json.loads((DATA / "score_floor_queries.json").read_text(encoding="utf-8"))["in_domain"]]
REF = GeneratorRef(generator_id="scripted-test", model_id="scripted-test", kind="generative", prompt_hash="1" * 64)
RESOLVER = ResolverRef(model_id="thread-resolver-v1", prompt_hash=PARAMS.resolver_prompt_hash)
WORDS = {"min_words": PARAMS.min_sentence_words, "max_chars": PARAMS.max_sentence_chars}


def _section(store, record):
    return next(section for section in store.items[record.item_id].sections if section.ordinal == record.section_ordinal)


def _span(record) -> EvidenceSpan:
    return EvidenceSpan(span_id=record.span_id, item_id=record.item_id, item_version=record.item_version, kind=record.item_kind,
                        char_start=record.start, char_end=record.end, content_hash=record.content_hash, score=5.0, near_floor=False,
                        license_class="public", quotable=True)


def _bundle(store, records) -> EvidenceBundle:
    floor, margin, version = store.index.thresholds
    return EvidenceBundle(corpus_version=store.corpus_version, index_version=store.index_version, retrieval_mode="lexical",
                          spans=tuple(_span(record) for record in records),
                          sufficiency=Sufficiency(score=5.0, gate=store.gate, threshold_version=version, floor=floor, margin=margin,
                                                  decision="answer", reason="evidence"))


def _edge_fragments(store):
    """(record, piece, edge) for each quotable document span whose first or last piece of its own text, cut under
    sentences-v2, is not a sentence of its section: the span starts or ends inside a longer document sentence."""
    registry = SpanResolver(store).registry
    from app.services.contained_answers import span_is_quotable

    found = []
    for record in store.span_registry.records:
        if record.item_kind != "document" or not span_is_quotable(record, registry):
            continue
        section_sentences = set(split_sentences(_section(store, record).body))
        pieces = split_sentences(record.text)
        for piece, edge in ((pieces[0], "start"), (pieces[-1], "end")):
            if piece not in section_sentences and sentences(piece, **WORDS) == [piece]:
                found.append((record, piece, edge))
    return found


@lru_cache(maxsize=1)
def _replay():
    """The two-pass pipeline over the public in-domain fixture (development store, bm25f-v1), stepwise plan: the same
    run the committed replay record makes for that configuration, minus its other plans (the lock precedes them)."""
    settings = Settings()
    store = get_course_store()
    pipeline = TwoPassPipeline(RetrievalEngine(store, settings), settings)
    results = []
    for index, query in enumerate(IN_DOMAIN):
        resolved = resolve_turns([], LearnerTurn(f"h1-{index}", query), package=pipeline.package)
        results.append((query, pipeline.run(PipelineInput(resolved=resolved, lesson_slug=None, presentation=PresentationPlan(plan_id="stepwise", source="request"),
                                                          response_id=f"shadow-{uuid4()}", delivery="shadow", shadowed_response_id=f"turn-{uuid4()}"),
                                            record=False)))
    return store, results


# ============================================================================================================ H1


def test_h1_sentence_bounds_cut_exactly_where_split_sentences_does():
    store = get_course_store()
    texts = [section.body for item in store.items.values() for section in item.sections]
    texts += ["", "   ", "One two three four.  Five six seven eight!", "\n  Lead text here. Next one is here?\tLast words",
              "See e.g. this case. Then Fig. 3 shows it. J. Preskill wrote it. Done.", "No boundary at all"]
    assert len(texts) > 100
    for text in texts:
        bounds = sentence_bounds(text)
        assert split_sentences(text) == [whitespace(text[begin:end]) for begin, end in bounds]
        assert all(text[begin:end] == text[begin:end].strip() and begin < end for begin, end in bounds)
        assert list(bounds) == sorted(bounds) and all(a[1] <= b[0] for a, b in zip(bounds, bounds[1:]))


def test_h1_a_span_edge_fragment_never_binds_and_a_whole_sentence_of_the_same_span_does():
    store = get_course_store()
    resolver = SpanResolver(store)
    fragments = _edge_fragments(store)
    # Not vacuous: spans are splitter chunks, so hundreds start or end inside a document sentence.
    assert sum(edge == "start" for _, _, edge in fragments) > 50 and sum(edge == "end" for _, _, edge in fragments) > 50
    start = next((record, piece) for record, piece, edge in fragments if edge == "start" and _whole(store, record))
    end = next((record, piece) for record, piece, edge in fragments if edge == "end" and record.span_id != start[0].span_id)
    whole = _whole(store, start[0])[0]
    plan = ClaimPlan(generator=REF, claims=(
        ProposedClaim(text=start[1], span_ids=(start[0].span_id,)),  # its opening words are in the previous span only
        ProposedClaim(text=end[1], span_ids=(end[0].span_id,)),  # its end is in the next span only
        ProposedClaim(text=whole.text, span_ids=(start[0].span_id,)),  # binds
        ProposedClaim(text=start[1].split(" ", 1)[1], span_ids=(start[0].span_id,)),  # a cut of a fragment: no piece at all
    ))
    result = bind(plan, _bundle(store, [start[0], end[0]]), resolver=resolver, store=store, registry=resolver.registry, params=PARAMS)
    assert [draft.text for draft in result.bound] == [whole.text]
    assert dict(result.dropped) == {"partial_sentence": 2, "not_verbatim": 1}
    assert result.bound[0].source_order == (start[0].item_id, whole.position)
    assert contracts.PARTIAL_SENTENCE in contracts.BINDING_FAILURES  # a binding failure: it lowers the bound-claim ratio


def _whole(store, record):
    return whole_sentences(record, store, **WORDS)


def test_h1_the_reported_negation_drop_no_longer_binds():
    # The finding's example: a span that starts at "preserve the underlying structural feasibility", cut from "...these
    # classical heuristics often fail to | preserve ...". Under resolver-bundle-sentence-v1 that piece locked, without
    # its "fail to".
    store = get_course_store()
    resolver = SpanResolver(store)
    record = next(r for r in store.span_registry.records if r.item_kind == "document" and r.text.startswith("preserve the underlying structural feasibility"))
    section = _section(store, record)
    assert section.body[: record.start - section.body_start].rstrip().endswith("fail to")
    piece = split_sentences(record.text)[0]
    result = bind(ClaimPlan(generator=REF, claims=(ProposedClaim(text=piece, span_ids=(record.span_id,)),)), _bundle(store, [record]),
                  resolver=resolver, store=store, registry=resolver.registry, params=PARAMS)
    assert result.bound == () and dict(result.dropped) == {"partial_sentence": 1}
    window = whole_sentence_text(record, store)
    assert window is None or not window.startswith("preserve")


def test_h1_the_envelope_carries_only_whole_sentences_and_every_locked_claim_is_one():
    store, results = _replay()
    answered = 0
    old_rule_fragments = 0
    for query, result in results:
        question = content_terms(query, PACKAGE.retrieval)
        for span in result.bundle.spans:
            record = store.span_registry.get(span.span_id)
            if not span.quotable:
                continue
            # What the extractive generator proposed from this span under the old envelope (the span's whole text).
            old = [s for s in sentences(record.text, **WORDS) if len(content_terms(s, PACKAGE.retrieval) & question) >= PARAMS.min_question_overlap_terms]
            section_sentences = set(split_sentences(_section(store, record).body))
            old_rule_fragments += sum(s not in section_sentences for s in old[: PARAMS.max_claims_per_span])
        if result.envelope is not None:
            for evidence in result.envelope.evidence:
                record = store.span_registry.get(evidence.span_id)
                assert evidence.text in record.text and evidence.text == whole_sentence_text(record, store)
                assert sentences(evidence.text, **WORDS) == [s.text for s in _whole(store, record)]
            quotable_with_sentences = [s.span_id for s in result.bundle.spans if s.quotable and whole_sentence_text(store.span_registry.get(s.span_id), store)]
            assert [evidence.span_id for evidence in result.envelope.evidence] == quotable_with_sentences
        if result.decision != "answer":
            continue
        answered += 1
        assert result.entry.counts.dropped == {} or set(result.entry.counts.dropped) <= {"merged", "duplicate"}
        for claim in result.locked.claims:
            for span_id in claim.span_ids:
                record = store.span_registry.get(span_id)
                section = _section(store, record)
                assert claim.text in set(split_sentences(section.body)), claim.text[:80]
                held = [s for s in _whole(store, record) if s.text == claim.text]
                assert held and all(record.start <= s.position < record.end for s in held)
            assert claim.source_order[1] == min(s.position for span_id in claim.span_ids
                                                for s in _whole(store, store.span_registry.get(span_id)) if s.text == claim.text)
    assert answered > 100
    # The fixture exercises the defect: the old envelope made the generator propose span-edge fragments.
    assert old_rule_fragments > 10


def test_h1_the_extractive_generator_proposes_only_what_binds():
    store, results = _replay()
    proposed = bound = 0
    for _, result in results:
        proposed += result.entry.counts.proposed_claims
        bound += result.entry.counts.bound_claims + result.entry.counts.dropped.get("merged", 0)
        assert "partial_sentence" not in result.entry.counts.dropped and "not_verbatim" not in result.entry.counts.dropped
    assert proposed > 200 and bound == proposed  # the bound-claim ratio stays 1.0, the Phase 2 baseline (plan L)


def test_h1_a_store_without_the_section_text_binds_nothing():
    store = get_course_store()
    resolver = SpanResolver(store)
    record = next(r for r in store.span_registry.records if r.item_kind == "document" and _whole(store, r))
    sentence = _whole(store, record)[0].text
    blind = SimpleNamespace(span_registry=store.span_registry, items={})
    assert whole_sentences(record, blind, **WORDS) == () and whole_sentence_text(record, blind) is None
    result = bind(ClaimPlan(generator=REF, claims=(ProposedClaim(text=sentence, span_ids=(record.span_id,)),)), _bundle(store, [record]),
                  resolver=resolver, store=blind, registry=resolver.registry, params=PARAMS)
    assert result.bound == ()


def test_h1_the_records_say_binding_refuses_span_edge_fragments():
    assert BINDING_RULE == RAW["tutor_pipeline"]["evidential"]["binding_rule"] == "resolver-bundle-sentence-v2"
    conflict_32 = SPEC.split("**32. D-19", 1)[1].split("**33.", 1)[0]
    assert "resolver-bundle-sentence-v2" in conflict_32 and "partial_sentence" in conflict_32 and "Corrected in 18.10 H1" in conflict_32
    bind_section = SPEC.split("### 4.6 Bind", 1)[1].split("### 4.7", 1)[0]
    assert "`partial_sentence`" in bind_section and "section text" in bind_section
    assert "resolver-bundle-sentence-v2" in ADR and "partial_sentence" in ADR and "Corrected in spec 18.10 H1" in ADR
    assert "span's edge" in ADR.split("**Residual risks.**", 1)[1] or "span's edge" in ADR
    applied = RAW["owner_decisions"]["PLAN-3.3"]["deviations"][0]["applied"]
    assert "partial_sentence" in applied and "wholly inside the span" in applied
    bind_doc = ast.get_docstring(ast.parse((API_ROOT / "app" / "services" / "tutor_pipeline" / "bind.py").read_text(encoding="utf-8")))
    assert "section text" in bind_doc and "partial_sentence" in bind_doc
    assert "binding `resolver-bundle-sentence-v2`" in README
    record = json.loads((REPO_ROOT / "docs" / "evaluation" / "phase3" / "three_plan_replay_v1.json").read_text(encoding="utf-8"))
    assert record["tutor_pipeline"]["binding_rule"] == "resolver-bundle-sentence-v2"


# ============================================================================================================ H2


def test_h2_stepwise_keeps_two_sentences_of_one_span_in_their_source_order():
    store = get_course_store()
    resolver = SpanResolver(store)
    # A span with two whole sentences whose claim ids sort the later one first: the old key (span start, claim id)
    # rendered them later-first under the "in source order" lead.
    record, earlier, later = next(
        (r, a, b) for r in store.span_registry.records if r.item_kind == "document"
        for a, b in zip(_whole(store, r), _whole(store, r)[1:])
        if claim_id_for(b.text, [r.span_id]) < claim_id_for(a.text, [r.span_id])
    )
    bundle = _bundle(store, [record])
    drafts = bind(ClaimPlan(generator=REF, claims=(ProposedClaim(text=later.text, span_ids=(record.span_id,)),
                                                   ProposedClaim(text=earlier.text, span_ids=(record.span_id,)))),
                  bundle, resolver=resolver, store=store, registry=resolver.registry, params=PARAMS).bound
    locked = lock(drafts, bundle=bundle, generator=REF, evidential_prompt_hash=REF.prompt_hash, pedagogical_prompt_hash=PARAMS.pedagogical_prompt_hash,
                  resolver=RESOLVER, package=PACKAGE)
    assert [claim.text for claim in locked.claims] == [later.text, earlier.text]  # the locked order is the proposal order
    assert [claim.source_order for claim in locked.claims] == [(record.item_id, later.position), (record.item_id, earlier.position)]
    assert earlier.position < later.position
    renderer = TemplateRenderer()
    stepwise = renderer.render(locked, PresentationPlan(plan_id="stepwise", source="request"), attempt=1)
    assert [s.text for s in stepwise.segments if s.kind == "claim"] == [earlier.text, later.text]
    assert TEMPLATES["stepwise.lead"][1].endswith("in source order:")
    concise = renderer.render(locked, PresentationPlan(plan_id="concise", source="request"), attempt=1)
    assert [s.text for s in concise.segments if s.kind == "claim"] == [later.text, earlier.text]


def test_h2_every_stepwise_rendering_of_the_replay_is_in_source_order():
    store, results = _replay()
    pairs = same_span = 0
    for _, result in results:
        if result.decision != "answer":
            continue
        by_id = {claim.claim_id: claim for claim in result.locked.claims}
        order = [by_id[s.claim_id] for s in result.rendered.segments if s.kind == "claim"]
        for a, b in zip(order, order[1:]):
            pairs += 1
            same_span += a.span_ids[0] == b.span_ids[0]
            assert tuple(a.source_order) <= tuple(b.source_order)
            if a.source_order[0] == b.source_order[0]:
                item = store.items[a.source_order[0]]
                for claim in (a, b):
                    position = claim.source_order[1]
                    assert whitespace(item.text[position : position + 4 * len(claim.text) + 50]).startswith(claim.text)
    assert pairs > 100 and same_span > 30  # the measured defect: 59 of 111 same-span pairs were out of order


# ============================================================================================================ H3


def parsed(raw: dict):
    return parse_config_package(raw, path=DEFAULT_PACKAGE_PATH, sha256="", hash_verified=False)


def _edited(edit) -> list[str]:
    raw = copy.deepcopy(RAW)
    edit(raw["tutor_pipeline"])
    package = parsed(raw)
    return check_tutor_pipeline_package(package, structural=False)


@pytest.mark.parametrize(
    ("name", "edit", "expected"),
    [
        ("resolver id", lambda t: t["resolver"].update(id="thread-resolver-v9"), "tutor_pipeline.resolver.id"),
        ("renderer", lambda t: t["pedagogical"].update(renderer="model-renderer-v2"), "tutor_pipeline.pedagogical.renderer"),
        ("idempotency header", lambda t: t["idempotency"].update(header="X-Request-Key"), "tutor_pipeline.idempotency.header"),
        ("pipeline version", lambda t: t.update(version="two-pass-v7"), "tutor_pipeline.version"),
        ("a fourth plan", lambda t: t["pedagogical"]["presentation_plans"].append("worked_example"), "presentation_plans"),
        ("a repeated plan", lambda t: t["pedagogical"]["presentation_plans"].append("concise"), "presentation_plans"),
        ("an unknown default plan", lambda t: (t["pedagogical"]["presentation_plans"].append("worked_example"),
                                               t["pedagogical"].update(default_plan="worked_example")), "default_plan"),
    ],
)
def test_h3_every_component_id_and_plan_the_package_names_is_compared_with_the_code(name, edit, expected):
    assert check_tutor_pipeline_package(PACKAGE, structural=False) == [] == check_tutor_pipeline_package(PACKAGE, structural=True)
    problems = _edited(edit)
    assert any(expected in problem for problem in problems), (name, problems)


def test_h3_the_code_values_the_package_must_match():
    tutor = RAW["tutor_pipeline"]
    assert (tutor["version"], tutor["resolver"]["id"], tutor["pedagogical"]["renderer"]) == (PIPELINE_VERSION, RESOLVER_ID, RENDERER_ID)
    assert tutor["idempotency"]["header"] == IDEMPOTENCY_HEADER == "Idempotency-Key"
    assert set(tutor["pedagogical"]["presentation_plans"]) == set(PLANS_LAYOUT) == set(get_args(PresentationPlan.model_fields["plan_id"].annotation))
    # The route reads the key from the header the package names.
    parameters = app.openapi()["paths"]["/tutor/turns"]["post"]["parameters"]
    headers = [p["name"] for p in parameters if p["in"] == "header"]
    assert IDEMPOTENCY_HEADER in headers and not [name for name in headers if "idempotency" in name.lower() and name != IDEMPOTENCY_HEADER]
    route_source = (API_ROOT / "app" / "api" / "routes" / "tutor.py").read_text(encoding="utf-8")
    assert "alias=turn_idempotency.IDEMPOTENCY_HEADER" in route_source and 'alias="Idempotency-Key"' not in route_source
    # /ready reports these values, so they are the code's.
    pipeline = TestClient(app).get("/ready").json()["tutor_pipeline"]
    assert (pipeline["version"], pipeline["resolver"], pipeline["renderer"]) == (PIPELINE_VERSION, RESOLVER_ID, RENDERER_ID)
    assert pipeline["presentation_plans"] == list(PLANS_LAYOUT)


# ============================================================================================================ H4


def test_h4_the_ac_3_2_record_test_supplies_its_commit_and_refuses_processes():
    acceptance = (API_ROOT / "tests" / "test_phase3_acceptance.py").read_text(encoding="utf-8")
    tree = ast.parse(acceptance)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    record_test = functions["test_ac_3_2_the_replay_finds_no_mismatch_and_is_labelled_not_e3_or_lq1"]
    calls = [node for node in ast.walk(record_test) if isinstance(node, ast.Call)]
    assert any(isinstance(call.func, ast.Name) and call.func.id == "refuse_processes" for call in calls)
    compute = next(call for call in calls if isinstance(call.func, ast.Attribute) and call.func.attr == "compute")
    assert "commit_source" in {keyword.arg for keyword in compute.keywords}
    # The run-time proof is in the acceptance file: a replay with its own commit and the record check run with every
    # process refused, and the default commit is the only process the replay starts.
    assert "test_ac_3_2_the_record_check_and_a_replay_with_its_own_commit_run_no_process" in functions
    review6 = (API_ROOT / "tests" / "test_phase3_review6.py").read_text(encoding="utf-8")
    assert "Corrected in 18.10 H4" in review6
    g1 = SPEC.split("### 18.9 Sixth review round", 1)[1].split("### 18.10", 1)[0]
    assert "Corrected in 18.10 H4" in g1


# ============================================================================================================ H5


def test_h5_the_two_tutor_turn_paths_share_one_rate_limit_window(monkeypatch):
    limited = Settings(assistant_chat_rate_limit="2/minute")
    monkeypatch.setattr(assistant_route, "get_settings", lambda: limited)
    client = TestClient(app)
    user = {"x-demo-user": f"h5-{uuid4().hex[:12]}", "x-demo-role": "learner"}

    def send(path: str) -> int:
        return client.post(path, headers={**user, "x-forwarded-for": f"h5-{uuid4().hex}"}, json={"message": "Why does routing depth matter?"}).status_code

    assert [send("/assistant/chat"), send("/tutor/turns")] == [200, 200]
    # The budget is spent whichever path asks next: alternating the two no longer doubles it.
    assert [send("/assistant/chat"), send("/tutor/turns")] == [429, 429]
    other = {"x-demo-user": f"h5-{uuid4().hex[:12]}", "x-demo-role": "learner", "x-forwarded-for": f"h5-{uuid4().hex}"}
    assert client.post("/tutor/turns", headers=other, json={"message": "Why does routing depth matter?"}).status_code == 200
    assert not hasattr(Settings(), "tutor_turns_rate_limit")
    for module in ("assistant", "tutor"):
        source = (API_ROOT / "app" / "api" / "routes" / f"{module}.py").read_text(encoding="utf-8")
        assert "@limiter.shared_limit(tutor_turn_rate_limit, scope=TUTOR_TURN_RATE_LIMIT_SCOPE)" in source
        assert "@limiter.limit(" not in source


# ============================================================================================================ H6, H7


def test_h6_the_ledger_records_say_what_the_code_does():
    models = (API_ROOT / "app" / "db_models.py").read_text(encoding="utf-8")
    head_comment = models.split("class ResponseLedgerHead", 1)[1].split("started_at: Mapped", 1)[0]
    assert "start-up while TUTOR_LEDGER_ENABLED" not in head_comment and "ledger_record_expected" in head_comment
    append = SPEC.split("**Append**", 1)[1].split("**`record_legacy_delivery`**", 1)[0]
    step_3 = next(line for line in append.splitlines() if line.startswith("3. "))
    assert "Start-up writes no head" in step_3 and step_3.count("mark_ledger_started") == 1 and "Corrected in 18.10 H6" in step_3
    step_7 = next(line for line in append.splitlines() if line.startswith("7. "))
    assert "40P01" in step_7 and "40001" in step_7 and "Corrected in 18.10 H6" in step_7
    conflict_29 = SPEC.split("**29. E1", 1)[1].split("**30.", 1)[0]
    assert "40P01" in conflict_29 and "Corrected in 18.10 H6" in conflict_29
    orm = SPEC.split("### 8.1 ORM", 1)[1].split("### 8.2", 1)[0]
    started = next(line for line in orm.splitlines() if line.startswith("`started_at` (18.7 E6)"))
    assert "informational" in started and "ledger_record_expected" in started and "Corrected in 18.10 H6" in started
    triggers = SPEC.split("### 8.2 Triggers", 1)[1].split("**PostgreSQL**", 1)[0]
    assert "re-created only when" in triggers and "Corrected in 18.10 H6" in triggers
    for path in (API_ROOT / "app" / "core" / "schema_upgrades.py", API_ROOT / "alembic" / "versions" / "20261119_phase3_response_ledger.py",
                 API_ROOT / "alembic" / "versions" / "20261119_phase2_corpus_spans.py"):
        text = path.read_text(encoding="utf-8")
        assert "Re-created on every start" not in text
        assert all("18.10 H6" in line or "until Phase 3" in line for line in text.splitlines() if "re-created on every" in line.lower()), path


def test_h7_the_verify_script_section_names_the_split_coverage_counts():
    section = SPEC.split("### 7.16 NEW `scripts/verify_ledger.py`", 1)[1].split("### 7.17", 1)[0]
    for key in ("turns_since", "unrecorded", "not_expected_earlier_image", "ledger_disabled", "qa_records_since"):
        assert f"`{key}`" in section, key
    assert "Corrected in 18.10 H7" in section


# ============================================================================================================ H8


def test_h8_spec_7_17_says_the_record_names_its_code_by_inputs():
    section = SPEC.split("### 7.17 NEW `scripts/replay_tutor_plans.py`", 1)[1].split("### 7.18", 1)[0]
    assert '"inputs": {"rule": "imported-repository-modules-sha256-lf-v1"' in section
    assert "**`inputs`**" in section and "**`commit`** is informational" in section
    stale = [line for line in SPEC.splitlines() if "names the commit that holds the code" in line and "Corrected in 18.10 H8" not in line]
    assert stale == [], stale


# ============================================================================================================ H9


def test_h9_status_counts_the_review_rounds_the_phase_record_holds():
    # The evidence package lives beside the repository, not in it (CI has none): checked where present.
    record_path = BEP_ROOT / "phase03" / "PHASE_RECORD.md"
    if not record_path.exists():
        return
    record = record_path.read_text(encoding="utf-8")
    rounds = 1 + len(re.findall(r"^## \w+ review round \(", record, flags=re.MULTILINE))  # "## Review fixes" was the first
    assert re.search(r"^## Review fixes \(", record, flags=re.MULTILINE)
    status = (BEP_ROOT / "00_meta" / "STATUS.md").read_text(encoding="utf-8")
    row = next(line for line in status.splitlines() if line.startswith("| 3 |"))
    words = {"five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
    stated = re.findall(r"\b(\w+) review rounds\b", row)
    assert stated, row
    assert all(words.get(word, -1) == rounds for word in stated), (stated, rounds)
