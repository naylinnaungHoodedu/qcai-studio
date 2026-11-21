"""Phase 3, eighth review round (2026-11-19; Phase 3 spec 18.11). Each test fails if its defect comes back.

I1  an empty evidential envelope says why: no_quotable_evidence when no bundle span is quotable, no_whole_sentence when
    the quotable spans hold no whole document sentence; a record never says no_quotable_evidence beside quotable spans.
I2  the pipeline-level fault tests run on a several-claim answer, and each fault is placed as itself and refused by its
    own rule (tutor_fakes.FAULT_SIGNATURES, FaultyRenderer(exact=True)).
I3  spec section 3's EnvelopeSpan.text and LockedClaim.source_order comments, 4.5's prompt-hash listing and propose rule,
    and 5.4's structural check say what the code does.
I4  spec 3.4's LedgerResponseRead listing and 7.13's no-record rule say what the ledger route does.
I5  the PD-08 and PD-11 register rows, spec section 6's env-example bullet and section 16's revision notes are current.
I6  spec section 12 lists every production frontend change (the proxy's span-route patterns included).
I7  the phase record and the closure notes point at the latest run and the current pin, and list every drop reason.
I8  the test strategy maps every review round and names only tests that exist.
The evidence package lives beside the repository, not in it (CI has none): its checks run where it is present.
"""

from __future__ import annotations

import ast
from collections import Counter
import json
from pathlib import Path
import random
import re
from typing import get_args
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.core.config_package import get_config_package
from app.schemas import LedgerResponseRead
from app.services import claim_gate
from app.services.claim_gate import check_subset
from app.services.contained_answers import span_is_quotable
from app.services.retrieval_engine import RetrievalEngine
from app.services.span_resolver import SpanResolver
from app.services.store import get_course_store
from app.services.tutor_pipeline import contracts
from app.services.tutor_pipeline import pipeline as pipeline_module
from app.services.tutor_pipeline.bind import whole_sentence_text, whole_sentences
from app.services.tutor_pipeline.contracts import (
    NO_QUOTABLE_EVIDENCE,
    NO_WHOLE_SENTENCE,
    EvidenceBundle,
    EvidenceSpan,
    LedgerEntry,
    PresentationPlan,
    Sufficiency,
)
from app.services.tutor_pipeline.evidential import build_envelope, no_envelope_reason
from app.services.tutor_pipeline.package_check import LEAF_KEYWORDS
from app.services.tutor_pipeline.pipeline import PipelineInput, TwoPassPipeline
from app.services.tutor_pipeline.render import TemplateRenderer
from app.services.tutor_pipeline.resolve import LearnerTurn, resolve_turns
from app.services.tutor_pipeline.retrieve import build_request
from tutor_fakes import FAULT_MODES, FAULT_SIGNATURES, FaultNotPlaced, FaultyRenderer, ScriptedGenerator, inject, place_fault

API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parents[1]
BEP_ROOT = REPO_ROOT.parent / "BEP-2-12"
FRONTEND = REPO_ROOT / "apps" / "frontend"
SPEC = (REPO_ROOT / "docs" / "architecture" / "phase3-implementation-spec.md").read_text(encoding="utf-8")
ADR_005 = (REPO_ROOT / "docs" / "adr" / "ADR-005-abstention-gate.md").read_text(encoding="utf-8")
README = (REPO_ROOT / "docs" / "evaluation" / "phase3" / "README.md").read_text(encoding="utf-8")
STRATEGY = (REPO_ROOT / "docs" / "testing" / "test-strategy.md").read_text(encoding="utf-8")
RECORD = json.loads((REPO_ROOT / "docs" / "evaluation" / "phase3" / "three_plan_replay_v1.json").read_text(encoding="utf-8"))
DATA = Path(__file__).parent / "data"
IN_DOMAIN = [item["query"] for item in json.loads((DATA / "score_floor_queries.json").read_text(encoding="utf-8"))["in_domain"]]
# A query whose two-pass answer locks several claims on several spans (spec 18.10 H1, 18.11 I2).
MULTI_CLAIM = "Explain why quantum logistics needs both problem reduction before execution and routing control during compilation."
PACKAGE = get_config_package(Settings())
PARAMS = PACKAGE.tutor_pipeline
OUTSIDE_SPAN = "span-" + "9" * 64


def _section(title: str, end: str) -> str:
    return SPEC.split(title, 1)[1].split(end, 1)[0]


def _run(pipeline: TwoPassPipeline, query: str, plan_id: str = "concise"):
    resolved = resolve_turns([], LearnerTurn(f"message-{uuid4()}", query), package=pipeline.package)
    return pipeline.run(PipelineInput(resolved=resolved, lesson_slug=None, presentation=PresentationPlan(plan_id=plan_id, source="request"),
                                      response_id=f"shadow-{uuid4()}", delivery="shadow", shadowed_response_id=f"turn-{uuid4()}"), record=False)


def _span(record, *, quotable: bool) -> EvidenceSpan:
    return EvidenceSpan(span_id=record.span_id, item_id=record.item_id, item_version=record.item_version, kind=record.item_kind,
                        char_start=record.start, char_end=record.end, content_hash=record.content_hash, score=5.0, near_floor=False,
                        license_class="public", quotable=quotable)


def _bundle(store, records, *, quotable: bool = True) -> EvidenceBundle:
    floor, margin, version = store.index.thresholds
    return EvidenceBundle(corpus_version=store.corpus_version, index_version=store.index_version, retrieval_mode="lexical",
                          spans=tuple(_span(record, quotable=quotable) for record in records),
                          sufficiency=Sufficiency(score=5.0, gate=store.gate, threshold_version=version, floor=floor, margin=margin,
                                                  decision="answer", reason="evidence"))


def _quotable_documents(store):
    registry = SpanResolver(store).registry
    return [record for record in store.span_registry.records if record.item_kind == "document" and span_is_quotable(record, registry)]


def _bep(relative: str) -> str | None:
    path = BEP_ROOT / relative
    return path.read_text(encoding="utf-8") if path.exists() else None


# ============================================================================================================ I1


def test_i1_quotable_spans_with_no_whole_sentence_abstain_as_no_whole_sentence_never_no_quotable_evidence(monkeypatch):
    settings = Settings()
    store = get_course_store()
    quotable = _quotable_documents(store)
    fragments = [record for record in quotable if whole_sentence_text(record, store) is None][:4]
    whole = next(record for record in quotable if whole_sentence_text(record, store) is not None)
    assert len(fragments) >= 2, "the dev corpus no longer has quotable spans without a whole sentence"
    resolved = resolve_turns([], LearnerTurn(f"message-{uuid4()}", MULTI_CLAIM), package=PACKAGE)
    request = build_request(resolved, lesson_slug=None, corpus_version=store.corpus_version)
    bundle = _bundle(store, fragments)
    assert build_envelope(request, bundle, store=store, params=PARAMS) is None
    assert no_envelope_reason(bundle, store=store) == NO_WHOLE_SENTENCE == "no_whole_sentence"
    # Nothing quotable (D-31: not approved), or nothing left at all (the license gate): the other reason.
    assert no_envelope_reason(_bundle(store, fragments, quotable=False), store=store) == NO_QUOTABLE_EVIDENCE == "no_quotable_evidence"
    assert no_envelope_reason(bundle.model_copy(update={"spans": ()}), store=store) == NO_QUOTABLE_EVIDENCE
    # The control: one quotable span with a whole sentence makes an envelope.
    assert build_envelope(request, _bundle(store, [*fragments, whole]), store=store, params=PARAMS) is not None
    # Through the pipeline, the record's reason agrees with its own per-span flags and sufficiency.
    monkeypatch.setattr(pipeline_module, "retrieve", lambda engine, request, **kwargs: bundle)
    result = _run(TwoPassPipeline(RetrievalEngine(store, settings), settings), MULTI_CLAIM)
    assert (result.decision, result.abstention_reason, result.envelope) == ("abstain", "no_whole_sentence", None)
    entry = result.entry
    assert entry.abstention_reason == "no_whole_sentence" and entry.retrieval.sufficiency.decision == "answer"
    assert entry.retrieval.evidence and all(span.quotable for span in entry.retrieval.evidence)
    # A valid ledger entry of its own schema (a two-pass record is ledger-entry-v2 since Phase 4).
    assert contracts.ENTRY_SCHEMAS[entry.entry_schema].model_validate(entry.model_dump(mode="json")) == entry
    assert "no_whole_sentence" in contracts.ABSTENTION_REASONS and "no_quotable_evidence" in contracts.ABSTENTION_REASONS


def test_i1_over_the_in_domain_fixture_each_empty_envelope_reason_matches_its_own_record():
    settings = Settings()
    store = get_course_store()
    pipeline = TwoPassPipeline(RetrievalEngine(store, settings), settings)
    reasons: Counter = Counter()
    for query in IN_DOMAIN:
        result = _run(pipeline, query)
        if result.abstention_reason not in (NO_QUOTABLE_EVIDENCE, NO_WHOLE_SENTENCE):
            continue
        assert result.envelope is None
        reasons[result.abstention_reason] += 1
        quotable = [span for span in result.entry.retrieval.evidence if span.quotable]
        if result.abstention_reason == NO_QUOTABLE_EVIDENCE:
            assert not quotable, query
        else:
            assert quotable and all(whole_sentence_text(store.span_registry.get(span.span_id), store) is None for span in quotable), query
    # The measured residual of 18.10 H1 (11 items under bm25f-v1 in the committed replay) now has its own reason.
    assert reasons[NO_WHOLE_SENTENCE] >= 1, reasons


def test_i1_the_records_name_both_reasons():
    listing = re.search(r"^ABSTENTION_REASONS = (\(.*?\))", SPEC, flags=re.MULTILINE | re.DOTALL)
    names = {"NO_QUOTABLE_EVIDENCE": contracts.NO_QUOTABLE_EVIDENCE, "NO_WHOLE_SENTENCE": contracts.NO_WHOLE_SENTENCE, "RENDER_FAILED": contracts.RENDER_FAILED}
    assert listing and eval(listing.group(1), {}, names) == contracts.ABSTENTION_REASONS  # noqa: S307 - the spec's listing of the code
    revision = ADR_005.split("## Revision 2026-11-19 (Phase 3)", 1)[1]
    for reason in set(contracts.ABSTENTION_REASONS) - set(contracts.GATE_ABSTENTION_REASONS):
        assert f"`{reason}`" in revision, reason
    envelope = _section("**`build_envelope`**", "**`ExtractiveD19Generator.propose`**")
    assert "`no_quotable_evidence`" in envelope and "`no_whole_sentence`" in envelope
    assert "the pipeline gave that reason for both causes" not in envelope
    step_3 = next(line for line in _section("### 4.10 Pipeline", "### 4.11").splitlines() if line.startswith("3. "))
    assert "`no_quotable_evidence`" in step_3 and "`no_whole_sentence`" in step_3
    assert "`no_whole_sentence` (11 under `bm25f-v1`, 13 under `p1-floor`)" in README
    observability = (REPO_ROOT / "infra" / "cloudrun" / "observability.md").read_text(encoding="utf-8")
    shadow_row = next(line for line in observability.splitlines() if line.startswith("| Shadow abstention by reason |"))
    assert "`no_quotable_evidence`" in shadow_row and "`no_whole_sentence`" in shadow_row
    by_name = {(config["name"], config["gate"]): config["abstention_by_reason"] for config in RECORD["configurations"]}
    assert by_name[("governed_empty", "p1-floor")].get("no_quotable_evidence", 0) > 0 and "no_whole_sentence" not in by_name[("governed_empty", "p1-floor")]
    for gate, count in (("bm25f-v1", 11), ("p1-floor", 13)):
        reasons = by_name[("all_public_approved", gate)]
        assert reasons.get("no_whole_sentence") == count and "no_quotable_evidence" not in reasons, (gate, reasons)
    # The superseded counts survive in no current text.
    texts = {"spec": SPEC.split("### 18.4 Review history", 1)[0], "README": README}
    for name in ("phase03/PHASE_RECORD.md", "phase03/CLOSURE_EVIDENCE_NOTES.md"):
        if (text := _bep(name)) is not None:
            texts[name] = text.split("## History", 1)[0]
    for name, text in texts.items():
        for line in text.splitlines():
            assert not re.search(r"`no_quotable_evidence` \(?11\b|extra abstentions are `no_quotable_evidence`", line), (name, line[:160])


# ============================================================================================================ I2


def _outside_sentence(store, locked) -> str:
    texts = {claim.text for claim in locked.claims}
    for record in _quotable_documents(store):
        if record.span_id in locked.span_ids:
            continue
        for sentence in whole_sentences(record, store, min_words=PARAMS.min_sentence_words, max_chars=PARAMS.max_sentence_chars):
            if sentence.text not in texts:
                return sentence.text
    raise AssertionError("no outside sentence")


@pytest.mark.parametrize("plan_id", ("concise", "stepwise", "socratic"))
def test_i2_every_fault_mode_is_placed_as_itself_and_raises_its_own_problem_under_every_plan(plan_id):
    assert set(FAULT_SIGNATURES) == set(FAULT_MODES) and set(FAULT_SIGNATURES.values()) <= set(claim_gate.PROBLEM_CODES)
    settings = Settings()
    store = get_course_store()
    result = _run(TwoPassPipeline(RetrievalEngine(store, settings), settings), MULTI_CLAIM, plan_id)
    assert result.decision == "answer" and len(result.locked.claims) >= 2 and len(result.locked.span_ids) >= 2
    claim_lines = {segment.line for segment in result.rendered.segments if segment.kind == "claim"}
    assert len(claim_lines) >= 2
    outside = _outside_sentence(store, result.locked)
    for mode in FAULT_MODES:
        faulty = inject(result.rendered, mode, outside_sentence=outside, outside_span_id=OUTSIDE_SPAN, exact=True)
        problems = check_subset(faulty, result.locked).problems
        assert FAULT_SIGNATURES[mode] in problems, (plan_id, mode, problems)
        if mode == "wrong_citation":  # a citation moved onto another claim, not the invented claim of the fallback
            assert "unmapped_factual_sentence" not in problems, problems
            assert faulty != inject(result.rendered, "invented", outside_sentence=outside, outside_span_id=OUTSIDE_SPAN)
        if mode == "undisplayed_citation":  # a claim line is gone, its span still listed: that rule alone
            assert problems == ("citation_list_mismatch",)
            assert len({segment.line for segment in faulty.segments if segment.kind == "claim"}) == len(claim_lines) - 1


def test_i2_an_exact_injection_refuses_a_fault_a_one_claim_answer_cannot_hold():
    settings = Settings()
    engine = RetrievalEngine(get_course_store(), settings)
    full = _run(TwoPassPipeline(engine, settings), MULTI_CLAIM)
    first = full.locked.claims[0]
    one = _run(TwoPassPipeline(engine, settings, generator=ScriptedGenerator([[(first.text, first.span_ids)]])), MULTI_CLAIM)
    assert one.decision == "answer" and len(one.locked.claims) == 1
    for mode, fallback in (("wrong_citation", "invented"), ("undisplayed_citation", "listed_twice")):
        _, placed = place_fault(one.rendered, mode, outside_sentence="x", outside_span_id=OUTSIDE_SPAN)
        assert placed == fallback  # what the seventh round's tests silently ran on the one-claim query
        with pytest.raises(FaultNotPlaced):
            inject(one.rendered, mode, outside_sentence="x", outside_span_id=OUTSIDE_SPAN, exact=True)
        renderer = FaultyRenderer(TemplateRenderer(), [True, True, True], random.Random(1), modes=(mode,), outside_sentence="x",
                                  outside_span_id=OUTSIDE_SPAN, exact=True)
        refused = _run(TwoPassPipeline(engine, settings, generator=ScriptedGenerator([[(first.text, first.span_ids)]]), renderer=renderer), MULTI_CLAIM)
        # Every attempt raised FaultNotPlaced: since spec 18.12 J3 the pipeline records render_failed, never
        # subset_check_failed, so a refused (unplaced) fault can no longer pass as a refused rendering.
        assert refused.abstention_reason == contracts.RENDER_FAILED and renderer.placed == [f"not_placed:{mode}"] * 3


def test_i2_the_fault_tests_run_on_the_several_claim_query_and_the_records_say_so():
    acceptance = (API_ROOT / "tests" / "test_phase3_acceptance.py").read_text(encoding="utf-8")
    fault_test = acceptance.split("def test_ac_3_3_a_renderer_that_adds_a_claim_a_citation_or_a_fact_in_a_connective_is_caught", 1)[1].split("\ndef ", 1)[0]
    assert "query = MULTI_CLAIM" in fault_test and "exact=True" in fault_test and "FAULT_SIGNATURES[mode]" in fault_test
    review4 = (API_ROOT / "tests" / "test_phase3_review4.py").read_text(encoding="utf-8")
    for name in ("test_e1_a_rendering_that_lists_a_span_it_never_shows_never_answers", "test_e1_the_rule_id_names_the_new_behaviour_and_the_fault_modes_include_it"):
        body = review4.split(f"def {name}", 1)[1].split("\ndef ", 1)[0]
        assert "IN_DOMAIN)" not in body and 'seen == [("citation_list_mismatch",)] * 3' in body, name
    eighth = next(line for line in SPEC.split("### 18.4 Review history", 1)[1].splitlines() if line.startswith("| 8, I1-I8 "))
    assert "I2 every fault mode is placed as itself on a several-claim answer: `test_i2_*`" in eighth
    item_9 = next(line for line in SPEC.splitlines() if line.startswith("9. `test_ac_3_3_a_renderer_that_adds"))
    assert "FAULT_SIGNATURES" in item_9 and "several-claim" in item_9


# ============================================================================================================ I3


def test_i3_the_contract_listing_and_the_evidential_pass_say_what_the_code_does():
    listing = _section("### 3.1 Evidential channel", "### 3.2")
    envelope_span = listing.split("class EnvelopeSpan(Contract):", 1)[1].split("\nclass ", 1)[0]
    assert "whole_sentence_text" in envelope_span
    assert "the span's own text from the span registry" not in envelope_span
    locked_claim = listing.split("class LockedClaim(Contract):", 1)[1].split("\nclass ", 1)[0]
    assert "source_order: tuple[str, int]" in locked_claim
    assert "(item_id, char_start) of the first span id in sorted order" not in locked_claim
    rule = _section("### 4.7 Lock", "### 4.8")
    assert "item offset of the sentence's first character" in rule
    # 4.5's prompt-hash listing holds exactly the keys the code hashes.
    source = (API_ROOT / "app" / "services" / "tutor_pipeline" / "evidential.py").read_text(encoding="utf-8")
    function = next(node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.FunctionDef) and node.name == "evidential_prompt_hash")
    hashed = {key.value for node in ast.walk(function) if isinstance(node, ast.Dict) for key in node.keys}
    assert "min_question_overlap_terms" in hashed
    evidential = _section("### 4.5 Evidential pass", "### 4.6")
    block = evidential.split("def evidential_prompt_hash(params) -> str:", 1)[1].split("```", 1)[0]
    assert set(re.findall(r'"(\w+)":', block)) == hashed, block
    propose = next(line for line in evidential.splitlines() if line.startswith("- For each envelope span"))
    assert "`min_question_overlap_terms`" in propose and "the intersection is non-empty" not in propose
    # 5.4 names the leaf comparison the structural check makes.
    structural = next(line for line in _section("### 5.4 Pipeline/package", "### 5.5").splitlines() if line.startswith("With `structural=True`"))
    assert "LEAF_KEYWORDS" in structural and "`$ref`" in structural
    named = {"type", "enum", "const", "pattern", "format", "multipleOf", "uniqueItems", "default"}
    assert all(f"`{key}`" in structural for key in named)
    assert all(re.match(r"(min|max|exclusive)", key) for key in set(LEAF_KEYWORDS) - named) and "bounds" in structural


# ============================================================================================================ I4


def test_i4_the_ledger_route_listing_and_its_no_record_rule_say_what_the_code_does():
    listing = _section("### 3.4 API additions", "### 4.").split("class LedgerResponseRead(BaseModel):", 1)[1].split("```", 1)[0]
    fields = re.findall(r"^    (\w+): ", listing, flags=re.MULTILINE)
    assert fields == list(LedgerResponseRead.model_fields), fields
    literal = re.search(r'unrecorded_reason: Literal\[(.*?)\]', listing)
    assert literal and set(ast.literal_eval(f"({literal.group(1)},)")) == set(get_args(get_args(LedgerResponseRead.model_fields["unrecorded_reason"].annotation)[0]))
    assert "ledger_record_expected" in listing and "ledger_started_at" not in listing
    step_3 = next(line for line in _section("### 7.13 Routes", "### 7.14").splitlines() if line.startswith("3. **Everyone else:**"))
    for needed in ("ledger_record_expected", "unrecorded_reason", "`earlier_image`", "`ledger_disabled`", "`missing`", "`ledger_started_at` decides nothing"):
        assert needed in step_3, needed
    stale = [line for line in SPEC.split("### 18.4 Review history", 1)[0].splitlines() if "created before `ledger.ledger_started_at" in line]
    assert stale == [], stale
    route = (API_ROOT / "app" / "api" / "routes" / "ledger.py").read_text(encoding="utf-8")
    assert "turn.ledger_record_expected" in route and "ledger_started_at" not in route


# ============================================================================================================ I5


def test_i5_the_registers_and_spec_sections_6_and_16_say_what_the_code_does():
    settings = Settings()
    assert hasattr(settings, "ledger_rate_limit") and not hasattr(settings, "tutor_turns_rate_limit")
    section_6 = _section("## 6. Settings", "## 7. File-by-file changes")
    table_settings = set(re.findall(r"^\| `([A-Z_]+)` \|", section_6, flags=re.MULTILINE))
    example = (REPO_ROOT / "infra" / "cloudrun" / "api-production.env.example.yaml").read_text(encoding="utf-8")
    set_keys = dict(re.findall(r'^([A-Z_]+): "([^"]*)"', example, flags=re.MULTILINE))
    phase3_set = {key: value for key, value in set_keys.items() if key in table_settings}
    bullet = next(line for line in section_6.splitlines() if line.startswith("- `infra/cloudrun/api-production.env.example.yaml`"))
    named = dict(re.findall(r'`([A-Z_]+): "([^"]*)"`', bullet))
    assert named == phase3_set and len(named) == 5, (named, phase3_set)
    for budget in ("TWO_PASS_SHADOW_BUDGET_MS", "TUTOR_LEDGER_APPEND_BUDGET_MS"):
        assert budget not in set_keys and f"`{budget}`" in bullet
    assert "TUTOR_TURNS_RATE_LIMIT" not in section_6 and not any("gains the eight settings" in line for line in SPEC.splitlines())
    section_16 = _section("## 16. Provisional defaults", "## 17.")
    from app.services.tutor_pipeline.bind import BINDING_RULE

    pd_08_copy = next(line for line in section_16.splitlines() if line.startswith("| PD-08 |"))
    assert f"`{BINDING_RULE}`" in pd_08_copy and "resolver-bundle-sentence-v1" not in pd_08_copy
    assert "Revised in" not in section_16
    register = _bep("00_meta/PROVISIONAL_DEFAULTS_REGISTER.md")
    if register is None:
        return
    pd_08 = next(line for line in register.splitlines() if line.startswith("| PD-08 |"))
    assert f"bound by `{BINDING_RULE}`" in pd_08 and "`partial_sentence`" in pd_08 and "resolver-bundle-sentence-v1" not in pd_08
    pd_11 = next(line for line in register.splitlines() if line.startswith("| PD-11 |"))
    where = pd_11.rstrip(" |").rsplit(" | ", 2)[1]
    text = pd_11.rstrip(" |").rsplit(" | ", 2)[0]
    assert "`LEDGER_RATE_LIMIT`" in text and "`ASSISTANT_CHAT_RATE_LIMIT`" in text and "TUTOR_TURNS_RATE_LIMIT" not in pd_11
    assert "config.py" in where


# ============================================================================================================ I6


def test_i6_spec_12_lists_every_production_frontend_change():
    proxy = (FRONTEND / "src" / "lib" / "guest-session.ts").read_text(encoding="utf-8")
    assert "/^\\/spans\\/span-[0-9a-f]{64}$/" in proxy and "/^\\/evidence\\/spans\\/span-[0-9a-f]{64}$/" in proxy
    section_12 = _section("## 12. Frontend", "## 13. Tests")
    rows = [line for line in section_12.splitlines() if line.startswith("| ") and not line.startswith("| File") and not line.startswith("|---")]
    for path in ("src/lib/types.ts", "src/lib/evidence-panel.ts", "src/components/evidence-panel.tsx", "src/components/teaching-assistant-chat.tsx",
                 "src/components/qa-panel.tsx", "src/app/globals.css", "src/lib/privacy-disclosures.ts", "src/lib/guest-session.ts"):
        assert (FRONTEND / path).exists(), path
        assert any(f"`{path}`" in row.split(" | ", 1)[0] for row in rows), path
    production = next(line for line in section_12.splitlines() if line.startswith("**Production.**"))
    assert "`guest-session.ts`" in production and "Two frontend changes ship to production" in production
    assert not any("the privacy row is the only production frontend change" in line for line in SPEC.splitlines())
    second = next(line for line in SPEC.split("### 18.4 Review history", 1)[1].splitlines() if line.startswith("| 2, C1-C12 "))
    assert "C11 a span link never mints a guest session in the proxy" in second


# ============================================================================================================ I7


def _round_section(text: str, word: str) -> str:
    return text.split(f"## {word} review round (", 1)[1].split("\n## ", 1)[0]


def test_i7_the_phase_record_and_closure_notes_point_at_the_latest_run_and_the_current_pin():
    record = _bep("phase03/PHASE_RECORD.md")
    notes = _bep("phase03/CLOSURE_EVIDENCE_NOTES.md")
    if record is None or notes is None:
        return
    current = record.split("## History", 1)[0]
    # The current-state section holds the latest run; the history table holds one row per round, the latest last.
    latest = current.split("### Latest verification", 1)[1]
    assert "SQLite" in latest and "PostgreSQL" in latest and "__SUITE__" not in latest
    rows = [line for line in record.split("## History", 1)[1].splitlines() if re.match(r"\| \d+, ", line)]
    # The latest round is the last row, and it holds no placeholder (rows are numbered 1..n, one per round).
    assert rows[-1].startswith(f"| {len(rows)}, ") and "__" not in rows[-1] and "PENDING" not in rows[-1]
    r_13 = notes.split("### R-13", 1)[1].split("\n### ", 1)[0]
    tests = next(line for line in r_13.splitlines() if line.startswith("- **Tests:**"))
    for reason in contracts.BINDING_FAILURES:
        assert f"`{reason}`" in tests, reason
    pin = (API_ROOT / "app" / "config_package" / "v2.json.sha256").read_text(encoding="utf-8").strip()
    r_46 = notes.split("### R-46", 1)[1].split("\n### ", 1)[0]
    assert "v2.json.sha256" in r_46
    for text in (current, notes):
        for match in re.finditer(r"sha256 `([0-9a-f]{8,64})", text):
            assert pin.startswith(match.group(1).rstrip("…")), match.group(0)


# ============================================================================================================ I8


def _test_functions() -> set[str]:
    names = set()
    for path in (API_ROOT / "tests").glob("test_*.py"):
        names |= set(re.findall(r"^(?:async )?def (test_\w+)\(", path.read_text(encoding="utf-8"), flags=re.MULTILINE))
    return names


def test_i8_the_test_strategy_maps_every_review_round_and_names_only_tests_that_exist():
    phase_3 = STRATEGY.split("## Phase 3 acceptance map", 1)[1].split("**Exit gate.**", 1)[0]
    functions = _test_functions()
    rows = [line for line in phase_3.splitlines() if line.startswith("| ") and not line.startswith("| AC |") and not line.startswith("| File |") and not line.startswith("|---")]
    for row in rows:
        ac = re.match(r"\| AC-3-(\d)", row)
        prefix = f"test_ac_3_{ac.group(1)}" if ac else None
        for match in re.finditer(r"`(test_[a-z0-9_]+)`", row):
            assert match.group(1) in functions, match.group(1)
        for match in re.finditer(r"`\.\.\.(_[a-z0-9_]+)`", row):
            assert prefix and prefix + match.group(1) in functions, (prefix, match.group(1))
        for match in re.finditer(r"`(test_[a-z0-9_]+?)_?\*`", row):
            assert any(name.startswith(match.group(1)) for name in functions), match.group(1)
    for path in sorted((API_ROOT / "tests").glob("test_phase3_review*.py")):
        assert f"`{path.name}`" in phase_3, path.name
    for module in ("test_phase3_review7.py", "test_phase3_review8.py"):
        row = next((line for line in rows if line.startswith(f"| `{module}` |")), None)
        assert row, module
        source = (API_ROOT / "tests" / module).read_text(encoding="utf-8")
        for name in re.findall(r"^def (test_\w+)\(", source, flags=re.MULTILINE):
            group = re.match(r"(test_[a-z]\d+)_", name).group(1)
            assert f"`{group}_*`" in row, (module, name)
    ac_3_2 = next(line for line in rows if line.startswith("| AC-3-2"))
    assert "`..._the_record_check_and_a_replay_with_its_own_commit_run_no_process`" in ac_3_2
    ac_3_3 = next(line for line in rows if line.startswith("| AC-3-3"))
    assert "`partial_sentence`" in ac_3_3 and "several-claim answer" in ac_3_3
