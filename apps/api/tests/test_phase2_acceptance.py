"""Phase 2 acceptance: corpus, span identity and retrieval integrity (plan Phase 2 K, G, H, L; spec section 8.1).

Configurations (spec 8): "dev" is CourseStore(Settings()); "governed_empty" is a production, governed build with
the committed manifest (D-31: nothing approved, so authored spans only); "all_public_approved" is the same with a
temporary manifest approving every public-plane, bound item. Governed tests without an explicit gate exercise the
shipped default, p1-floor.

AC-2-3 reading (spec 0.3): every citation the Phase 2 pipeline stores or returns resolves (resolution "resolved",
found by the resolver, equal content_hash); every migrated citation resolves; a legacy_unresolved citation is
never returned as resolved: it is withheld (pre-containment rows, R1.2; in governed builds, citations of items the
manifest does not approve) or labelled resolution="legacy_unresolved", provisional=true and "unverified historical
reference".

corpus_version (plan 11.1): the sorted (item_id, item_version, sha256) of the built items plus the span scheme, so
partial approval yields a new version and a licence-field edit does not; the manifest records the governed value.

AC-2-5 and the plan L stop: both gates are measured in both configurations. p1-floor over an index that holds
document spans falls below the baseline (spec conflict 29); that case is a strict xfail, and the stop is enforced
in code (start-up and validate_corpus --check-recall-stop refuse it), which the Plan L tests prove.

AC-2-7: the path half is proven here and in CI; the licensed-passage half needs the private-plane fingerprints
(D-14) and a built image and release, so a CI report says ac_2_7 "partial" and never "met".
"""

from __future__ import annotations

import ast
import copy
from datetime import UTC, datetime
import hashlib
import importlib.util
import inspect
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect as sa_inspect, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.api.routes import assistant as assistant_route
from app.api.routes import qa as qa_route
from app.api.routes import search as search_route
from app.api.routes import spans as spans_route
from app.core.config import DEVELOPMENT_GUEST_TOKEN_SECRET, Settings, get_settings
from app.core.config_package import (
    V1_PACKAGE_PATH,
    V2_PACKAGE_PATH,
    ConfigPackageError,
    canonical_sha256,
    clear_config_package_cache,
    get_config_package,
    load_config_package,
)
from app.core.corpus_governance import CorpusGovernanceError, CorpusRegistry, get_corpus_registry, p1_floor_recall_stop
from app.core.data_planes import PrivatePlaneAccessError, assert_public_plane_path
from app.core.db import Base, SessionLocal
from app.core.guest_tokens import GUEST_TOKEN_COOKIE, guest_csrf_for, issue_guest_token
from app.core.manifest_v2 import compute_corpus_version, with_all_public_approved
from app.core.near_duplicates import Candidate, candidates_from_manifest, near_duplicate_pairs
from app.core.schema_upgrades import run_schema_upgrades
from app.core.source_assets import source_asset_id
from app.db_models import CorpusSpan, Note, QAInteraction, QuizAttempt, TutorTurn
from app.main import app
from app.schemas import Citation, LearnerRecordOperationInput
from app.services import retrieval_metrics
from app.services.citation_migration import EXIT_STOP, migrate
from app.services.contained_answers import ABSTENTION, contain_answer
from app.services.content_assembler import CourseStore
from app.services.learner_record import apply_learner_record_operations
from app.services.lexical_index import ScoredEntry
from app.services.provenance import UNRESOLVED_LABEL, label_stored_citation, native_citation, provisional_flag
from app.services.qa_engine import QAEngine
from app.services.retrieval_engine import RetrievalEngine
from app.services.retrieval_legacy_p1 import build_legacy_chunks, legacy_search
from app.services.span_resolver import SpanResolver
from app.services.span_store import persist_spans
from app.services.spans import (
    authored_sha256,
    build_identity_registry,
    build_spans,
    canonical_authored,
    canonical_document,
    make_splitter,
    span_set_digest,
)
from app.services.store import get_course_store, get_span_resolver
from app.services.teaching_assistant import TeachingAssistantService
from app.services.text_utils import truncate_display_excerpt
from app.services.tutor_orchestrator import TutorOrchestrator
from evaluation.qcai_eval.invariance import invariance_violations

API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parents[1]
DATA = Path(__file__).parent / "data"
REPO_MANIFEST = REPO_ROOT / "corpus" / "public" / "manifest.json"
AC = json.loads((DATA / "score_floor_queries.json").read_text(encoding="utf-8"))
CALIBRATION = json.loads((DATA / "phase2_calibration_queries.json").read_text(encoding="utf-8"))
BASELINE = json.loads((DATA / "legacy_p1_baseline.json").read_text(encoding="utf-8"))
OOS = AC["off_topic"] + AC["stopword_only"]
IN_DOMAIN = AC["in_domain"]
VIDEO_2026 = "Quantum Computing and Artificial Intelligence 2026.mp4"
ROUTING_DOCUMENT = "Module2_Routing, Graph Shrinking, and Logistics under Hardware Constraints.docx"
CLINICAL_LESSON = "clinical-and-kernel-qcai-systems"
TRUSTED_ORIGIN = "http://localhost:3000"
GATES = ("p1-floor", "bm25f-v1")
client = TestClient(app)
_TMP = tempfile.TemporaryDirectory(prefix="qcai-phase2-")
APPROVED_MANIFEST = Path(_TMP.name) / "all_public_approved" / "manifest.json"
APPROVED_MANIFEST.parent.mkdir(parents=True)
APPROVED_MANIFEST.write_text(json.dumps(with_all_public_approved(json.loads(REPO_MANIFEST.read_text(encoding="utf-8")))), encoding="utf-8")


def learner_questions() -> list[dict]:
    store = get_course_store()
    return [{"query": q, "expected_lessons": [slug]} for slug, lesson in store.lessons.items() for q in lesson.learner_questions]


def settings_for(config: str, gate: str | None = None, manifest: Path | None = None) -> Settings:
    extra = {"retrieval_gate": gate} if gate else {}
    if config == "dev":
        return Settings(**extra)
    path = manifest or (REPO_MANIFEST if config == "governed_empty" else APPROVED_MANIFEST)
    return Settings(environment="production", enforce_corpus_governance=True, corpus_manifest_path=str(path), **extra)


_STORES: dict[tuple[str, str | None], CourseStore] = {}


def store_for(config: str, gate: str | None = None) -> CourseStore:
    key = (config, gate)
    if key not in _STORES:
        _STORES[key] = CourseStore(settings_for(config, gate))
    return _STORES[key]


def lessons_of(results) -> set[str]:
    return {slug for result in results for slug in (result.lesson_slugs or [result.lesson_slug])}


def recall_at_5(store: CourseStore, items: list[dict]) -> int:
    return sum(bool(set(item["expected_lessons"]) & lessons_of(store.search(item["query"], top_k=5))) for item in items)


def legacy_chunks_for(config: str):
    """The pre-migration (a257dd11) chunks: no asset when governed under D-31, otherwise all 24, the 2026 video
    included, as the pre-migration code served them when every asset was approved (it had no Q-10 binding)."""
    settings = settings_for(config)
    if config == "governed_empty":
        return build_legacy_chunks(settings, [], [])
    return build_legacy_chunks(settings, settings.source_documents, settings.source_videos)


def demo(prefix: str) -> dict[str, str]:
    # uuid4-based demo ids; a distinct client address keeps per-address limits apart.
    return {"x-demo-user": f"{prefix}-{uuid4().hex[:12]}", "x-demo-role": "learner", "x-forwarded-for": f"phase2-{uuid4().hex}"}


def anonymous() -> dict[str, str]:
    return {"x-forwarded-for": f"phase2-{uuid4().hex}"}


def edited_manifest(tmp_path: Path, edit, *, base: Path = REPO_MANIFEST) -> Path:
    payload = json.loads(base.read_text(encoding="utf-8"))
    edit(payload)
    payload["corpus_version"] = compute_corpus_version(payload["items"])
    path = tmp_path / f"manifest-{uuid4().hex[:8]}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def fresh_sessions(database_url: str) -> tuple[sessionmaker, object]:
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    run_schema_upgrades(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False), engine


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(f"phase2_{name}", REPO_ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ======================================================================================================== AC-2-1


@pytest.mark.parametrize("gate", GATES)
@pytest.mark.parametrize("config", ["dev", "governed_empty", "all_public_approved"])
def test_ac_2_1_unique_span_ids_equal_total_chunks_and_are_identical_across_two_rebuilds(config, gate):
    first = CourseStore(settings_for(config, gate))
    second = CourseStore(settings_for(config, gate))  # a genuinely fresh rebuild, nothing cached between them

    assert len({entry.chunk_id for entry in first.chunks}) == len(first.chunks) > 0
    assert first.duplicate_span_ids == 0 and first.span_registry.duplicate_ids == 0
    assert [(e.span_id, e.lesson_slugs) for e in first.chunks] == [(e.span_id, e.lesson_slugs) for e in second.chunks]
    assert [r.span_id for r in first.span_registry.records] == [r.span_id for r in second.span_registry.records]
    assert first.index_version == second.index_version


def test_ac_2_1_a_section_used_by_two_lessons_is_one_index_entry():
    store = store_for("dev")
    shared = [entry for entry in store.chunks if len(entry.lesson_slugs) >= 2]
    assert shared, "the corpus has sections that two lessons use"
    legacy = [chunk for chunk in legacy_chunks_for("dev") if chunk.source_kind == "document"]
    for entry in shared[:10]:
        rows = [chunk for chunk in legacy if (chunk.source_filename, chunk.excerpt) == (entry.source_filename, entry.excerpt)]
        assert {chunk.lesson_slug for chunk in rows} == set(entry.lesson_slugs)  # Phase 1 repeated it per lesson
        assert sum(1 for other in store.chunks if other.span_id == entry.span_id) == 1
    # Phase 1's document rows hold exactly the spans the index now holds once each.
    assert {(c.source_filename, c.excerpt) for c in legacy} == {(e.source_filename, e.excerpt) for e in store.chunks if e.source_kind == "document"}
    assert len(legacy) > len({e.span_id for e in store.chunks if e.source_kind == "document"})


def test_ac_2_1_the_rebuild_route_reports_no_duplicate_span_ids():
    response = client.post("/admin/rebuild-content", headers={"x-demo-user": f"staff-{uuid4().hex[:8]}", "x-demo-role": "instructor"})
    assert response.status_code == 200
    body = response.json()
    assert body["duplicate_span_ids"] == 0
    assert body["unique_chunk_ids"] == body["chunk_count"] > 0
    assert body["span_count"] >= body["chunk_count"]
    assert body["index_version"].startswith("index-") and body["gate"] == "bm25f-v1"


def test_ac_2_1_manifest_span_digests_match_a_fresh_build():
    manifest = json.loads(REPO_MANIFEST.read_text(encoding="utf-8"))
    settings = Settings()
    splitter = make_splitter(get_config_package(settings))
    checked = 0
    for item in manifest["items"]:
        if not item.get("spans"):
            continue
        if item["kind"] == "authored":
            from app.services.content_assembler import MODULE_BLUEPRINTS

            canonical = canonical_authored(MODULE_BLUEPRINTS, item_version=item["version"])
        else:
            path = settings._resolve_source_assets(item["asset_filenames"])[0]
            canonical = canonical_document(path, item_id=item["id"], item_version=item["version"], source_title="x")
        ids = [record.span_id for record in build_spans(canonical, splitter)]
        assert (len(ids), span_set_digest(ids)) == (item["spans"]["count"], item["spans"]["set_sha256"]), item["id"]
        checked += 1
    assert checked == 13  # 12 documents and the authored item


# ======================================================================================================== AC-2-2


@pytest.mark.parametrize("config", ["governed_empty", "all_public_approved"])
def test_ac_2_2_a_manifest_licence_field_edit_changes_no_span_id(config, tmp_path):
    base = REPO_MANIFEST if config == "governed_empty" else APPROVED_MANIFEST

    def relicense(payload):
        for item in payload["items"]:
            item["source"] = "Edited source attribution"
            item["license"] = "CC-BY-4.0 (edited for the test)"
            item["permitted_use"] = "edited permitted use"

    edited = edited_manifest(tmp_path, relicense, base=base)
    before = store_for(config)
    after = CourseStore(settings_for(config, manifest=edited))

    assert CorpusRegistry(settings_for(config, manifest=edited)).items  # the edited manifest validates
    assert [e.span_id for e in after.chunks] == [e.span_id for e in before.chunks]
    assert [r.span_id for r in after.span_registry.records] == [r.span_id for r in before.span_registry.records]
    assert (after.corpus_version, after.index_version) == (before.corpus_version, before.index_version)
    if config == "all_public_approved":
        assert any(entry.source_kind == "document" for entry in after.chunks)  # document spans are covered


def test_ac_2_2_an_approval_edit_changes_membership_not_identity(tmp_path):
    document = "Module2_Routing, Graph Shrinking, and Logistics under Hardware Constraints.docx"

    def approve(payload):
        for item in payload["items"]:
            if document in item["asset_filenames"]:
                item["public_service"] = True

    approved = CourseStore(settings_for("governed_empty", manifest=edited_manifest(tmp_path, approve)))
    empty = store_for("governed_empty")
    full = store_for("all_public_approved")

    # Plan 11.1: "any content or membership change, including partial approval, yields a new version".
    assert approved.corpus_version != empty.corpus_version
    assert approved.index_version != empty.index_version
    full_ids = {record.span_id for record in full.span_registry.records}
    assert {r.span_id for r in approved.span_registry.records if r.item_kind == "document"} <= full_ids
    assert {r.span_id for r in approved.span_registry.records if r.item_kind == "authored"} == {
        r.span_id for r in empty.span_registry.records
    }


def test_ac_2_2_corpus_version_hashes_the_built_items_and_ignores_licence_fields(tmp_path):
    # Plan 11.1: "corpus_version MUST hash the sorted (item_id, item_version, sha256) of built items plus the
    # span-scheme version, so any content or membership change, including partial approval, yields a new version;
    # membership-neutral licence edits do not."
    manifest = json.loads(REPO_MANIFEST.read_text(encoding="utf-8"))
    governed = CorpusRegistry(settings_for("governed_empty"))
    assert governed.corpus_version == manifest["corpus_version"]  # the manifest records the governed value
    assert [item.item_id for item in governed.built_items] == ["authored-curriculum"]  # D-31: nothing approved
    development = get_corpus_registry(Settings())
    assert len(development.built_items) == 24  # every public-plane, bound item: 25 less the unbound 2026 video
    assert development.corpus_version != governed.corpus_version
    approved = CorpusRegistry(settings_for("all_public_approved"))
    assert approved.corpus_version == development.corpus_version  # the same built set gives the same version
    assert store_for("governed_empty").corpus_version == governed.corpus_version

    def relicense(payload):
        for item in payload["items"]:
            item["license"] = "CC-BY-4.0 (edited for the test)"

    assert CorpusRegistry(settings_for("governed_empty", manifest=edited_manifest(tmp_path, relicense))).corpus_version == governed.corpus_version

    def edit_unbuilt_content(payload):  # an unapproved document is not built in a governed build
        for item in payload["items"]:
            if ROUTING_DOCUMENT in item["asset_filenames"]:
                item["sha256"] = "1" * 64
                item["version"] = "sha256:" + "1" * 16

    edited = edited_manifest(tmp_path, edit_unbuilt_content)
    assert CorpusRegistry(settings_for("governed_empty", manifest=edited)).corpus_version == governed.corpus_version
    edited_dev = CorpusRegistry(Settings(corpus_manifest_path=str(edited)))
    assert edited_dev.corpus_version != development.corpus_version  # development builds it, so its version moves


def test_ac_2_2_span_ids_do_not_depend_on_the_manifest_id_or_schema(tmp_path):
    document = "Module2_Routing, Graph Shrinking, and Logistics under Hardware Constraints.docx"
    legacy = tmp_path / "legacy.json"
    legacy.write_text(json.dumps({"schema_version": "1.0", "items": [{
        "id": "routing-brief", "version": "v1", "source": "Course author", "license": "CC-BY-4.0",
        "permitted_use": "public course material", "public_service": True, "asset_filenames": [document]}]}), encoding="utf-8")

    def approve(payload):
        for item in payload["items"]:
            if document in item["asset_filenames"]:
                item["public_service"] = True

    v1 = CourseStore(settings_for("governed_empty", manifest=legacy))
    v2 = CourseStore(settings_for("governed_empty", manifest=edited_manifest(tmp_path, approve)))
    documents_v1 = [r.span_id for r in v1.span_registry.records if r.item_kind == "document"]
    documents_v2 = [r.span_id for r in v2.span_registry.records if r.item_kind == "document"]
    assert documents_v1 and documents_v1 == documents_v2
    assert {r.item_id for r in v1.span_registry.records if r.item_kind == "document"} == {source_asset_id(document, "document")}

    def rename(payload):
        for item in payload["items"]:
            if document in item["asset_filenames"]:
                item["id"] = "routing-brief"

    with pytest.raises(CorpusGovernanceError, match="source_asset_id"):
        CorpusRegistry(settings_for("governed_empty", manifest=edited_manifest(tmp_path, rename)))


# ======================================================================================================== AC-2-3


def _assert_resolves(citation: Citation, db: Session | None = None) -> None:
    assert citation.resolution == "resolved" and citation.citation_schema == 2, citation
    assert citation.chunk_id == citation.span_id
    assert get_span_resolver().verify(citation, db) is not None, citation.span_id


def test_ac_2_3_every_returned_citation_resolves():
    store = get_course_store()
    settings = Settings()
    engine = RetrievalEngine(store, settings)
    queries = [item["query"] for item in IN_DOMAIN[:30]]
    seen = 0
    for query in queries:
        for response in (QAEngine(engine, settings).ask(query), TeachingAssistantService(engine, settings).chat(query)):
            for citation in response.citations:
                _assert_resolves(citation)
                seen += 1
    with SessionLocal() as db:
        for query in queries[:10]:
            for path, body in (("/qa/ask", {"question": query}), ("/assistant/chat", {"message": query})):
                response = client.post(path, headers=demo("ac23"), json=body)
                assert response.status_code == 200, response.text
                for raw in response.json()["citations"]:
                    _assert_resolves(Citation.model_validate(raw), db)
                    seen += 1
    assert seen > 0


def test_ac_2_3_every_stored_citation_resolves():
    headers = demo("ac23-stored")
    for query in ("Why does routing depth matter?", "QUBO logistics under hardware constraints", "quantum kernels in finance"):
        assert client.post("/qa/ask", headers=headers, json={"question": query}).status_code == 200
        assert client.post("/assistant/chat", headers=headers, json={"message": query}).status_code == 200
    user_id = headers["x-demo-user"]
    with SessionLocal() as db:
        rows = db.scalars(select(QAInteraction).where(QAInteraction.user_id == user_id)).all()
        turns = db.scalars(select(TutorTurn).where(TutorTurn.user_id == user_id)).all()
        stored = [Citation.model_validate(raw) for row in rows for raw in row.citations]
        assert stored, "the routing questions are answered from document spans in development"
        for citation in stored:
            _assert_resolves(citation, db)
            # Write-through registered its text-free identity, so it resolves after the corpus changes too.
            assert db.scalars(select(CorpusSpan).where(CorpusSpan.span_id == citation.span_id)).first() is not None
        # tutor_turns is the other stored citation column (the migration's TABLES): each of its citations resolves.
        assert turns, "every /assistant/chat message stores a tutor turn"
        turn_citations = [Citation.model_validate(raw) for turn in turns for raw in turn.citations]
        assert turn_citations, "the routing questions are answered from document spans in development"
        for citation in turn_citations:
            _assert_resolves(citation, db)
        for turn in turns:
            cited = {raw["span_id"] for raw in turn.citations}
            assert all(set(claim["cited_span_ids"]) <= cited for claim in turn.claims)


def _legacy_citations() -> list[dict]:
    """v0 and v1 citations as the pre-Phase-2 builds wrote them, built from the frozen legacy search."""
    dev = legacy_chunks_for("dev")
    governed = legacy_chunks_for("governed_empty")
    document = next(r for r in legacy_search(dev, "Why does routing depth matter?", top_k=8) if r.source_kind == "document")
    authored = legacy_search(governed, "What is the difference between QAI and AI4QC?", top_k=1)[0]
    video = next(r for r in legacy_search(dev, "nested routing", top_k=8) if r.source_kind == "video")
    full_chunk = next(c for c in dev if c.source_kind == "document" and c.chunk_id == document.chunk_id and
                      truncate_display_excerpt(c.excerpt, 320) == document.excerpt)

    def v0(result, *, excerpt=None, filename=None):
        return {"chunk_id": result.chunk_id, "source_title": "Legacy title", "source_kind": result.source_kind,
                "section_title": result.title, "excerpt": excerpt if excerpt is not None else truncate_display_excerpt(result.excerpt, 320),
                "timestamp_label": None, **({"source_filename": filename} if filename else {})}

    lexical_v1 = {**v0(document), "span_id": "span-" + "a" * 64, "corpus_version": "manifest:0000000000000000",
                  "content_hash": hashlib.sha256(" ".join(document.excerpt.split()).encode()).hexdigest(),
                  "source_filename": full_chunk.source_filename, "provisional": True}
    # The semantic path displayed the full chunk truncated once; pick a chunk where once and twice differ.
    semantic_chunk = next(c for c in dev if c.source_kind == "document"
                          and truncate_display_excerpt(c.excerpt, 320) != truncate_display_excerpt(truncate_display_excerpt(c.excerpt, 320), 320))
    semantic_v0 = {"chunk_id": semantic_chunk.chunk_id, "source_title": "Legacy title", "source_kind": "document",
                   "section_title": semantic_chunk.title, "excerpt": truncate_display_excerpt(semantic_chunk.excerpt, 320), "timestamp_label": None}
    return [v0(document), lexical_v1, v0(authored), v0(video), {**v0(document), "excerpt": "   "}, semantic_v0]


def test_ac_2_3_every_migrated_citation_resolves_and_the_rest_are_labelled_legacy_unresolved(fresh_database_url):
    sessions, engine = fresh_sessions(fresh_database_url)
    try:
        citations = _legacy_citations()
        with sessions() as db:
            db.add(QAInteraction(user_id=f"legacy-{uuid4().hex[:8]}", lesson_slug=None, question="q", answer="a", citations=citations))
            db.commit()
        settings = Settings()
        memory, _ = build_identity_registry(settings, include_unapproved=True)
        report = migrate(sessions, mode="apply", memory=memory, settings=settings, package=get_config_package(settings),
                         corpus_version="corpus-test", tables=["qa_interactions"])
        counts = report["tables"]["qa_interactions"]["citations"]
        assert (counts["migrated"], counts["legacy_unresolved"]) == (4, 2)
        assert counts["by_reason"]["chapter_summary_excluded"] == 1 and counts["by_reason"]["missing_excerpt"] == 1
        assert counts["diagnostics"]["key_semantic"] >= 1 and counts["diagnostics"]["key_lexical"] >= 1
        assert report["threshold"]["result"] == "pass" and report["totals"]["exact_match_regressions"] == 0
        resolver = SpanResolver(CourseStore(Settings()))
        with sessions() as db:
            stored = db.scalars(select(QAInteraction)).one().citations
            for raw in stored:
                citation = Citation.model_validate(raw)
                if raw["migration_status"] == "migrated":
                    assert resolver.verify(citation, db) is not None
                    assert raw["legacy_chunk_id"] == raw["legacy_original"]["chunk_id"]
                else:
                    assert (citation.resolution, citation.label, citation.provisional) == ("legacy_unresolved", UNRESOLVED_LABEL, True)
            assert db.scalar(select(CorpusSpan.id).where(CorpusSpan.registered_by == "migration").limit(1)) is not None
    finally:
        engine.dispose()


def test_ac_2_3_a_legacy_unresolved_citation_is_never_returned_as_resolved():
    store = get_course_store()
    real = native_citation(store.search("Why does routing depth matter?", top_k=1)[0], corpus_version=store.corpus_version, settings=Settings())
    v0 = {"chunk_id": "lesson:doc:1", "source_title": "S", "source_kind": "document", "section_title": "T", "excerpt": "An old excerpt.", "timestamp_label": None}
    v1 = {**v0, "span_id": "span-" + "b" * 64, "corpus_version": "manifest:x", "content_hash": "c" * 64, "provisional": True}
    forged = {**real.model_dump(), "span_id": "span-" + "d" * 64, "chunk_id": "span-" + "d" * 64}
    headers = demo("ac23-history")
    with SessionLocal() as db:
        db.add(QAInteraction(user_id=headers["x-demo-user"], lesson_slug=None, question="q", answer="a",
                             citations=[v0, v1, forged, real.model_dump()], created_at=datetime.now(UTC)))
        db.commit()
    response = client.get("/qa/history", headers=headers)
    assert response.status_code == 200
    (item,) = response.json()
    by_id = {citation["chunk_id"]: citation for citation in item["citations"]}
    for chunk_id in (v0["chunk_id"], forged["chunk_id"]):
        assert by_id[chunk_id]["resolution"] == "legacy_unresolved"
        assert by_id[chunk_id]["label"] == UNRESOLVED_LABEL and by_id[chunk_id]["provisional"] is True
    assert by_id[forged["chunk_id"]]["unresolved_reason"] == "not_resolvable_on_read"
    assert by_id[real.chunk_id]["resolution"] == "resolved" and by_id[real.chunk_id]["label"] is None
    assert sum(1 for c in item["citations"] if c["resolution"] == "resolved") == 1


def test_ac_2_3_a_citation_that_does_not_resolve_is_never_quoted():
    store = get_course_store()
    registry = get_corpus_registry(Settings())
    hit = next(r for r in store.search("Why does routing depth matter?", top_k=8) if r.source_kind == "document")
    real = native_citation(hit, corpus_version=store.corpus_version, settings=Settings())

    forged_id = real.model_copy(update={"span_id": "span-" + "e" * 64, "chunk_id": "span-" + "e" * 64})
    wrong_hash = real.model_copy(update={"content_hash": "0" * 64})
    tampered = real.model_copy(update={"excerpt": "Quantum computers have already replaced every classical computer."})
    for citation in (forged_id, wrong_hash):
        contained = contain_answer([citation], registry, store.span_registry)
        assert (contained.decision, contained.answer, contained.dropped_unresolved) == ("abstain", ABSTENTION, 1)
    contained = contain_answer([tampered], registry, store.span_registry)
    assert contained.decision == "answer"
    assert "replaced every classical computer" not in contained.answer
    assert " ".join(real.excerpt.split()) in contained.answer


def test_ac_2_3_governed_history_withholds_citations_of_unapproved_items(monkeypatch):
    governed = settings_for("governed_empty")
    dev = store_for("dev")
    record = next(r for r in dev.span_registry.records if r.item_kind == "document")
    entry = next(e for e in dev.chunks if e.item_kind == "document")
    citation = native_citation(dev.to_search_result(ScoredEntry(entry, 9.0, 2, False), None), corpus_version=dev.corpus_version, settings=governed)
    with SessionLocal() as db:
        persist_spans(db, [record, dev.span_registry.get(entry.span_id)], corpus_version=dev.corpus_version, registered_by="register-job")
        row = QAInteraction(user_id=f"withheld-{uuid4().hex[:8]}", lesson_slug=None, question="q", answer="a",
                            citations=[citation.model_dump()], created_at=datetime.now(UTC))
        db.add(row)
        db.commit()
        monkeypatch.setattr(qa_route, "get_settings", lambda: governed)
        monkeypatch.setattr(qa_route, "get_span_resolver", lambda: SpanResolver(store_for("governed_empty")))
        before = retrieval_metrics.snapshot()["citation_resolution"]["withheld_unapproved"]
        item = qa_route._history_item(row, db)
        assert item.citations == []  # the item is not approved in the governed build ([R13])
        assert retrieval_metrics.snapshot()["citation_resolution"]["withheld_unapproved"] == before + 1
        # In development the same stored citation reads back resolved.
        monkeypatch.setattr(qa_route, "get_settings", lambda: Settings())
        monkeypatch.setattr(qa_route, "get_span_resolver", lambda: SpanResolver(dev))
        assert [c.resolution for c in qa_route._history_item(row, db).citations] == ["resolved"]


# ======================================================================================================== AC-2-4


@pytest.mark.parametrize("gate", GATES)
@pytest.mark.parametrize("config", ["governed_empty", "all_public_approved"])
def test_ac_2_4_the_out_of_scope_fixture_abstains_with_zero_results_above_the_floor(config, gate):
    store = store_for(config, gate)
    settings = settings_for(config, gate)
    engine = RetrievalEngine(store, settings)
    qa = QAEngine(engine, settings)
    assert len(OOS) == 124
    leaked = []
    for query in OOS:
        decision = store.evaluate(query, top_k=20)
        if decision.results or not decision.abstained or engine.search(query).results or qa.ask(query).decision != "abstain":
            leaked.append(query)
    assert leaked == []


def test_ac_2_4_an_out_of_scope_route_sample_abstains():
    for query in OOS[::12]:
        response = client.get("/search", params={"query": query}, headers=anonymous())
        assert response.status_code == 200 and response.json() == []
        assert response.headers["x-retrieval-decision"] == "abstain"
        assert response.headers["x-retrieval-gate"] == "bm25f-v1"
    for query in OOS[:3]:
        data = client.post("/qa/ask", headers=demo("ac24"), json={"question": query}).json()
        assert (data["decision"], data["citations"]) == ("abstain", [])


# ======================================================================================================== AC-2-5


def _slot_equal_recall(store: CourseStore, items: list[dict]) -> int:
    order = list(store.lessons)
    hits = 0
    for item in items:
        lessons: list[str] = []
        for result in store.search(item["query"], top_k=5):
            lessons.extend(sorted(result.lesson_slugs, key=order.index))
        hits += bool(set(item["expected_lessons"]) & set(lessons[:5]))
    return hits


P1_FLOOR_WITH_DOCUMENTS = pytest.mark.xfail(
    strict=True,
    reason=(
        "Phase 2 spec conflict 29: p1-floor over an index with document spans falls below the pre-migration recall@5 "
        "(118 against 129; learner questions 22 against 28) once chapter summaries are excluded (task 2.7). The plan L "
        "stop is enforced in code: governed start-up and validate_corpus --check-recall-stop refuse this configuration."
    ),
)


@pytest.mark.parametrize(
    ("config", "gate"),
    [
        ("governed_empty", "bm25f-v1"),
        ("governed_empty", "p1-floor"),  # the shipped configuration (D-31, default gate outside development)
        ("all_public_approved", "bm25f-v1"),
        pytest.param("all_public_approved", "p1-floor", marks=P1_FLOOR_WITH_DOCUMENTS),
    ],
)
def test_ac_2_5_in_domain_recall_at_5_is_not_below_the_pre_migration_baseline(config, gate):
    # Baseline: BEP-0 recorded no recall@5, so the pre-migration search runs in the same run (frozen module).
    store = store_for(config, gate)
    chunks = legacy_chunks_for(config)
    lq = learner_questions()
    for name, items in (("fixture", IN_DOMAIN), ("learner_questions", lq)):
        new = recall_at_5(store, items)
        legacy = sum(bool(set(i["expected_lessons"]) & {r.lesson_slug for r in legacy_search(chunks, i["query"], top_k=5)}) for i in items)
        slot_equal = _slot_equal_recall(store, items)
        note = f"{config} {name}: {gate} {new} (slot-equal {slot_equal}) vs legacy {legacy}" + (" [zero slack]" if new == legacy else "")
        assert new >= legacy, note


def test_ac_2_5_the_frozen_legacy_search_reproduces_the_pre_migration_snapshot():
    snapshot = BASELINE["configurations"]
    queries = {hashlib.sha256(q.encode()).hexdigest(): q for q in
               {*(i["query"] for i in IN_DOMAIN), *OOS, *(i["query"] for i in CALIBRATION["items"]), *(i["query"] for i in learner_questions())}}
    for config, name in (("governed_empty", "governed_empty"), ("all_public_approved", "all_public_approved")):
        chunks = legacy_chunks_for(config)
        assert len(chunks) == snapshot[name]["chunks"] and len({c.chunk_id for c in chunks}) == snapshot[name]["unique_chunk_ids"]
        for row in snapshot[name]["per_query"]:
            top = [[r.chunk_id, r.lesson_slug, r.score] for r in legacy_search(chunks, queries[row["q"]], top_k=5)]
            assert top == row["top5"], (name, row["q"])
        recall = sum(bool(set(i["expected_lessons"]) & {r.lesson_slug for r in legacy_search(chunks, i["query"], top_k=5)}) for i in IN_DOMAIN)
        assert recall == snapshot[name]["recall_at_5"]
    assert (snapshot["governed_empty"]["recall_at_5"], snapshot["all_public_approved"]["recall_at_5"]) == (131, 129)


def test_ac_2_5_the_p1_floor_gate_on_the_governed_index_equals_todays_search():
    store = store_for("governed_empty", "p1-floor")
    chunks = build_legacy_chunks(settings_for("governed_empty"), [], [])
    queries = [*(i["query"] for i in IN_DOMAIN), *OOS, *(i["query"] for i in CALIBRATION["items"]), *(i["query"] for i in learner_questions())]
    for query in queries:
        new = [(r.lesson_slug, r.score, r.excerpt) for r in store.search(query, top_k=8)]
        old = [(r.lesson_slug, r.score, r.excerpt) for r in legacy_search(chunks, query, top_k=8)]
        assert new == old, query
    assert recall_at_5(store, IN_DOMAIN) == 131
    assert recall_at_5(store, learner_questions()) == 36


# ======================================================================================================== AC-2-6


def test_ac_2_6_every_manifest_hash_matches_disk():
    completed = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "validate_corpus.py"), "--check-hashes", "--video-hash", "size"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, env={**os.environ, "DATABASE_URL": "sqlite:///:memory:"},
    )
    assert completed.returncode == 0, completed.stderr
    assert "Every manifest hash matches disk (AC-2-6): 25 items" in completed.stdout


@pytest.fixture(scope="module")
def pointer_root(tmp_path_factory) -> Path:
    """The documents, and an LFS pointer for each video, as a CI checkout without LFS content has them."""
    root = tmp_path_factory.mktemp("pointer-root")
    (root / "update_data").mkdir()
    manifest = json.loads(REPO_MANIFEST.read_text(encoding="utf-8"))
    for item in manifest["items"]:
        for rel in item["asset_paths"]:
            target = root / rel
            if item["kind"] == "document":
                target.write_bytes((REPO_ROOT / rel).read_bytes())
            else:
                target.write_text(f"version https://git-lfs.github.com/spec/v1\noid sha256:{item['sha256']}\nsize {item['size_bytes']}\n",
                                  encoding="utf-8", newline="\n")
    return root


def _check_hashes(root: Path, video_hash: str = "full") -> list[str]:
    module = load_script("validate_corpus")
    registry = CorpusRegistry(settings_for("governed_empty"))
    problems, _ = module.check_hashes(registry, root, video_hash)
    return problems


def test_ac_2_6_a_changed_byte_or_wrong_pointer_oid_fails_the_hash_check(pointer_root, tmp_path):
    import shutil

    root = tmp_path / "root"
    shutil.copytree(pointer_root, root)
    document = next(p for p in root.glob("*.docx"))
    data = bytearray(document.read_bytes())
    data[len(data) // 2] ^= 0x01
    document.write_bytes(bytes(data))
    pointer = next(p for p in root.glob("*.mp4"))
    pointer.write_text("version https://git-lfs.github.com/spec/v1\noid sha256:" + "f" * 64 + "\nsize 1\n", encoding="utf-8", newline="\n")
    problems = _check_hashes(root)
    assert any("sha256 differs" in problem for problem in problems)
    assert len({problem.split(":")[0] for problem in problems}) >= 2


def test_ac_2_6_an_lfs_pointer_oid_is_accepted_as_the_content_hash(pointer_root):
    assert _check_hashes(pointer_root) == []
    assert _check_hashes(pointer_root, "size") == []


# ======================================================================================================== AC-2-7


def test_ac_2_7_the_source_asset_route_refuses_a_file_on_the_private_plane(tmp_path, monkeypatch):
    # The guard itself is driven: the same file is served from a public root and refused from corpus/private/.
    import shutil
    from urllib.parse import quote

    from app.api.routes import assets as assets_route

    headers = {"x-demo-user": f"reader-{uuid4().hex[:8]}", "x-demo-role": "learner"}
    for path in ("/source-assets/..%2Fcorpus%2Fprivate%2FREADME.md", "/source-assets/by-id/..%2Fcorpus%2Fprivate%2FREADME.md"):
        assert client.get(path, headers=headers).status_code == 404
    source = Settings()._resolve_source_assets([ROUTING_DOCUMENT])[0]
    public_root, private_root = tmp_path / "public-root", tmp_path / "corpus" / "private"
    for root in (public_root, private_root):
        root.mkdir(parents=True)
        shutil.copyfile(source, root / ROUTING_DOCUMENT)
    guarded: list[Path] = []
    real_guard = assets_route._public_plane
    monkeypatch.setattr(assets_route, "_public_plane", lambda path, settings: guarded.append(path) or real_guard(path, settings))
    urls = (f"/source-assets/{quote(ROUTING_DOCUMENT)}", f"/source-assets/by-id/{source_asset_id(ROUTING_DOCUMENT, 'document')}")
    for root, expected in ((public_root, 200), (private_root, 404)):
        monkeypatch.setattr(assets_route, "get_settings", lambda root=root: Settings(source_assets_root=str(root)))
        for url in urls:
            assert client.get(url, headers=headers).status_code == expected, (root, url)
    assert len(guarded) == 4 and all(path.name == ROUTING_DOCUMENT for path in guarded)  # the guard decided each


def test_ac_2_7_no_index_resolver_or_span_route_reaches_a_private_plane_item(tmp_path, monkeypatch, fresh_database_url):
    def privatise(payload):
        for item in payload["items"]:
            if ROUTING_DOCUMENT in item["asset_filenames"]:
                item["plane"] = "private"
                item["public_service"] = True

    private = settings_for("governed_empty", manifest=edited_manifest(tmp_path, privatise))
    registry = CorpusRegistry(private)
    assert not registry.is_public_asset(ROUTING_DOCUMENT) and not registry.is_indexable(ROUTING_DOCUMENT)
    assert registry.is_private_item(source_asset_id(ROUTING_DOCUMENT, "document"))
    store = CourseStore(private)
    assert not any(entry.source_filename == ROUTING_DOCUMENT for entry in store.chunks)
    assert source_asset_id(ROUTING_DOCUMENT, "document") not in store.span_registry.item_ids

    dev = store_for("dev")
    span = next(record for record in dev.span_registry.records if record.source_filename == ROUTING_DOCUMENT)
    assert SpanResolver(dev).resolve(span.span_id) is not None  # control: the public build resolves this span
    assert SpanResolver(store).resolve(span.span_id) is None
    sessions, engine = fresh_sessions(fresh_database_url)
    try:
        with sessions() as db:
            persist_spans(db, [span], corpus_version="corpus-test", registered_by="register-job")
            db.commit()
            assert SpanResolver(dev).resolve(span.span_id, db) is not None
            # A row registered while the item was public stops resolving once the manifest moves it to the private plane.
            assert SpanResolver(store).resolve(span.span_id, db) is None
    finally:
        engine.dispose()

    monkeypatch.setattr(spans_route, "get_settings", lambda: Settings(span_resolver_route_enabled=True))
    monkeypatch.setattr(spans_route, "get_span_resolver", lambda: SpanResolver(dev))
    assert client.get(f"/spans/{span.span_id}", headers=anonymous()).status_code == 200  # control
    monkeypatch.setattr(spans_route, "get_settings", lambda: private.model_copy(update={"span_resolver_route_enabled": True}))
    monkeypatch.setattr(spans_route, "get_span_resolver", lambda: SpanResolver(store))
    response = client.get(f"/spans/{span.span_id}", headers=anonymous())
    assert (response.status_code, response.headers["cache-control"]) == (404, "no-store")


def test_ac_2_7_private_plane_paths_fail_closed():
    root = Path("/")
    for path in ("corpus/private/x", "lqs/private/x", "volumes/book.pdf", "/app/corpus/private/x"):
        with pytest.raises(PrivatePlaneAccessError):
            assert_public_plane_path(Path(path) if path.startswith("/") else REPO_ROOT / path, root)
    with pytest.raises(PrivatePlaneAccessError):
        assert_public_plane_path("/app/corpus/private/x", Path("/"))
    assert_public_plane_path(REPO_ROOT / "corpus" / "private" / "README.md", REPO_ROOT)  # the one public exception


def test_ac_2_7_the_boundary_scans_find_zero_private_plane_paths(tmp_path):
    report_path = tmp_path / "boundary.json"
    completed = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "scan_boundary.py"), "--repo", "--docker-context", "apps/api/Dockerfile:.",
         "--docker-context", "apps/frontend/Dockerfile:apps/frontend", "--report", str(report_path)],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, env={**os.environ, "DATABASE_URL": "sqlite:///:memory:"},
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["path_scan_result"] == "pass"
    assert report["passage_scan"] == {"status": "not_run", "reason": "no licensed-passage fingerprint file was supplied; passage scanning was not run"}
    assert report["passage_scan_result"] == "not_run"
    # This run evidences the path half only: the report never calls AC-2-7 met (passage scan, image and release missing).
    assert report["ac_2_7"]["status"] == "partial" and report["ac_2_7"]["path_scan"] == "pass"
    assert len(report["ac_2_7"]["missing"]) == 3 and any("D-14" in reason for reason in report["ac_2_7"]["missing"])
    contexts = {scan["dockerfile"]: scan for scan in report["scans"] if scan["target"] == "docker-context"}
    assert contexts["apps/frontend/Dockerfile"]["ignore_file"] == "apps/frontend/.dockerignore"
    assert contexts["apps/api/Dockerfile"]["ignore_file"] == ".dockerignore"
    for scan in report["scans"]:
        assert scan["private_plane_paths"] == [] and scan["licensed_volume_paths"] == []
        if scan["target"] == "docker-context":
            assert scan["secret_like_paths"] == [] and scan["image_source_files"] > 0


def test_ac_2_7_the_scanners_detect_a_planted_private_path_a_secret_like_name_and_a_planted_licensed_passage(tmp_path):
    scanner = load_script("scan_boundary")
    passage = " ".join(f"licensedword{index}" for index in range(30))
    context = tmp_path / "ctx"
    (context / "corpus" / "private").mkdir(parents=True)
    (context / "corpus" / "private" / "volume.txt").write_text("private", encoding="utf-8")
    (context / ".env").write_text("NAME=value", encoding="utf-8")
    (context / "notes.md").write_text(f"Intro. {passage} Outro.", encoding="utf-8")
    (context / "book.pdf").write_bytes(b"%PDF-1.4")
    (context / "Dockerfile").write_text("FROM scratch\nCOPY . .\n", encoding="utf-8")
    (context / ".dockerignore").write_text("node_modules/\n", encoding="utf-8")
    bundle = tmp_path / "release.zip"
    import zipfile

    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("lqs/private/items.jsonl", "{}")
        archive.writestr("app/.env.local", "NAME=value")
        archive.writestr("docs/readme.md", f"Intro. {passage}")
    salt = bytes(range(32))
    fingerprints = tmp_path / "fingerprints.json"
    fingerprints.write_text(json.dumps({
        "format": "qcai-licensed-fingerprints/1", "fingerprint_set_id": "synthetic-test", "normalization": "nfkc-casefold-alnum-v1",
        "shingle_words": 12, "hash": "hmac-sha256-trunc32", "salt_hex": salt.hex(),
        "fingerprints": sorted(scanner.fingerprint_shingles(passage, salt, 12))}), encoding="utf-8")
    args = SimpleNamespace(root=str(tmp_path), repo=False, working_tree=False, docker_context=["ctx/Dockerfile:ctx"],
                           release_zip=[str(bundle)], fingerprints=str(fingerprints))
    report = scanner.run(args)
    context_scan, zip_scan = report["scans"]
    assert context_scan["private_plane_paths"] == ["ctx/corpus/private/volume.txt"]
    assert context_scan["secret_like_paths"] == ["ctx/.env"] and context_scan["licensed_volume_paths"] == ["ctx/book.pdf"]
    assert zip_scan["private_plane_paths"] == ["lqs/private/items.jsonl"] and zip_scan["secret_like_paths"] == ["app/.env.local"]
    assert report["path_scan_result"] == "fail" and report["passage_scan_result"] == "fail"
    assert {hit["path"] for hit in report["passage_scan"]["files_with_hits"]} == {"ctx/notes.md", "docs/readme.md"}
    assert report["passage_scan"]["skipped_secret_like_files"] == 2  # never opened
    assert "licensedword" not in json.dumps(report)  # paths only, never content
    with pytest.raises(scanner.DockerIgnoreError):
        (context / ".dockerignore").write_text("*.md\n!notes.md\n", encoding="utf-8")
        scanner.run(SimpleNamespace(root=str(tmp_path), repo=False, working_tree=False, docker_context=["ctx/Dockerfile:ctx"], release_zip=[], fingerprints=None))


# ======================================================================================================== AC-2-8


def test_ac_2_8_a_near_duplicate_fixture_pair_fails_the_gate_and_the_configured_set_passes():
    params = get_config_package(Settings()).near_duplicate
    base = " ".join(f"routing constraint number {index} shapes the hybrid workflow" for index in range(60))
    near = base.replace("number 7 ", "number seven ")
    fixture = [Candidate("doc-a", "document", text=base), Candidate("doc-b", "document", text=near),
               Candidate("doc-c", "document", text="An unrelated text about thermodynamic limits of computation. " * 20)]
    pairs = near_duplicate_pairs(fixture, params)
    assert [(pair.a, pair.b) for pair in pairs] == [("doc-a", "doc-b")]

    manifest = json.loads(REPO_MANIFEST.read_text(encoding="utf-8"))
    package = get_config_package(Settings())
    assert near_duplicate_pairs(candidates_from_manifest(manifest, REPO_ROOT, package), params) == []
    # With the 2026 re-encode bound, the gate catches it (same duration, sizes 0.07% apart).
    rebound = copy.deepcopy(manifest)
    unbound_package = SimpleNamespace(q10_unbound_item_ids=frozenset(), q10_unbound_filenames=frozenset())
    for item in rebound["items"]:
        if VIDEO_2026 in item["asset_filenames"]:
            item["bound"], item["unbound_reason"] = True, None
    video_pairs = [pair for pair in near_duplicate_pairs(candidates_from_manifest(rebound, REPO_ROOT, unbound_package), params) if pair.kind == "video"]
    assert [(pair.a, pair.b) for pair in video_pairs] == [("quantum-computing-and-artificial-intelligence-2025", "quantum-computing-and-artificial-intelligence-2026")]
    assert any("mp4-mvhd-v1" in reason for reason in video_pairs[0].reasons)


def test_ac_2_8_the_ci_gate_exits_1_on_a_bound_near_duplicate_pair_and_passes_the_configured_set(tmp_path, monkeypatch, capsys):
    module = load_script("validate_corpus")
    assert module.main(["--check-near-duplicates"]) == 0  # the configured set passes (the CI step)
    capsys.readouterr()
    package = json.loads(get_config_package(Settings()).path.read_text(encoding="utf-8"))
    package["owner_decisions"]["Q-10"] = {**package["owner_decisions"]["Q-10"], "state": "resolved-for-this-test", "unbound_items": []}
    package_path = tmp_path / "v1.json"
    package_path.write_text(json.dumps(package), encoding="utf-8")
    (tmp_path / "v1.json.sha256").write_text(canonical_sha256(package) + "\n", encoding="utf-8")

    def rebind(payload):
        for item in payload["items"]:
            if VIDEO_2026 in item["asset_filenames"]:
                item["bound"], item["unbound_reason"] = True, None

    monkeypatch.setenv("CORPUS_MANIFEST_PATH", str(edited_manifest(tmp_path, rebind)))
    monkeypatch.setenv("CONFIG_PACKAGE_PATH", str(package_path))
    assert module.main(["--check-near-duplicates"]) == 1
    err = capsys.readouterr().err
    assert "quantum-computing-and-artificial-intelligence-2025 ~ quantum-computing-and-artificial-intelligence-2026" in err
    assert "mp4-mvhd-v1" in err


def test_ac_2_8_the_2026_video_stays_unbound_even_when_approved(tmp_path):
    for config in ("all_public_approved", "dev"):
        store = store_for(config)
        lesson = store.lessons[CLINICAL_LESSON]
        assert (lesson.video_asset, lesson.chapters) == (None, []), config
        assert not any(asset.filename == VIDEO_2026 for item in store.lessons.values() for asset in item.source_assets), config

    def approve_2026(payload):
        for item in payload["items"]:
            if VIDEO_2026 in item["asset_filenames"]:
                item["public_service"] = True

    registry = CorpusRegistry(settings_for("governed_empty", manifest=edited_manifest(tmp_path, approve_2026)))
    assert registry.is_public_asset(VIDEO_2026) is False and registry.is_bound(VIDEO_2026) is False
    assert get_corpus_registry(Settings()).is_public_asset(VIDEO_2026) is True  # development still lists and serves it


# ======================================================================================================== AC-2-9


def _seed_learner(user_id: str, mastery: float) -> None:
    with SessionLocal() as db:
        apply_learner_record_operations(db, user_id, [LearnerRecordOperationInput(
            operation_id=f"op-{uuid4().hex[:12]}", replica_id=f"replica-{uuid4().hex[:8]}", logical_counter=1,
            operation_type="mastery_set", payload={"skill_id": "routing", "value": mastery})])
        db.add(Note(user_id=user_id, lesson_slug="ai4qc-routing-and-optimization", body=f"My note at mastery {mastery}"))
        db.add(QuizAttempt(user_id=user_id, lesson_slug="ai4qc-routing-and-optimization", score=int(mastery * 10), responses={}))
        db.add(QAInteraction(user_id=user_id, lesson_slug=None, question="Earlier question", answer="Earlier answer", citations=[]))
        db.commit()


def _guest_client() -> tuple[TestClient, dict[str, str]]:
    guest_id = f"guest-{uuid4().hex}"
    issued = int(time.time())
    browser = TestClient(app)
    browser.cookies.set(GUEST_TOKEN_COOKIE, issue_guest_token(DEVELOPMENT_GUEST_TOKEN_SECRET, guest_id, issued))
    return browser, {"origin": TRUSTED_ORIGIN, "x-qcai-csrf": guest_csrf_for(DEVELOPMENT_GUEST_TOKEN_SECRET, guest_id, issued),
                     "x-forwarded-for": f"phase2-{uuid4().hex}"}


@pytest.mark.parametrize("gate", GATES)
def test_ac_2_9_one_query_under_different_learner_contexts_returns_identical_spans_scores_and_abstention(gate, monkeypatch):
    settings = Settings(retrieval_gate=gate)
    store = store_for("dev", gate)
    engine = RetrievalEngine(store, settings)
    monkeypatch.setattr(search_route, "get_retrieval_engine", lambda: engine)
    monkeypatch.setattr(qa_route, "get_qa_engine", lambda: QAEngine(engine, settings))
    monkeypatch.setattr(assistant_route, "get_tutor_orchestrator", lambda: TutorOrchestrator(TeachingAssistantService(engine, settings), settings))
    learners = []
    for mastery in (0.1, 0.5, 0.9):
        headers = demo(f"inv{int(mastery * 10)}")
        _seed_learner(headers["x-demo-user"], mastery)
        learners.append(headers)
    queries = ["Why does routing depth matter?", "QUBO logistics", "What is the capital of France?", "quantum kernels for finance"]
    replays: dict[str, list[dict]] = {}
    for query in queries:
        observed = []
        for headers in learners:
            search = client.get("/search", params={"query": query}, headers={**headers, "x-forwarded-for": f"phase2-{uuid4().hex}"}).json()
            asked = client.post("/qa/ask", headers=headers, json={"question": query}).json()
            chat = client.post("/assistant/chat", headers=headers, json={"message": query, "page_path": f"/lessons/{uuid4().hex[:6]}",
                                                                         "history": [{"role": "user", "content": "unrelated earlier text"}]}).json()
            observed.append((
                [(r["span_id"], r["score"]) for r in search],
                (asked["decision"], [c["span_id"] for c in asked["citations"]]),
                (chat["decision"], [c["span_id"] for c in chat["citations"]]),
            ))
            replays.setdefault(query, []).append({"factual_claims": [claim["text"] for claim in chat["claims"]],
                                                  "cited_span_ids": [c["span_id"] for c in asked["citations"]]})
        guest, guest_headers = _guest_client()
        guest_search = guest.get("/search", params={"query": query}, headers=guest_headers).json()
        guest_asked = guest.post("/qa/ask", headers=guest_headers, json={"question": query}).json()
        anonymous_search = client.get("/search", params={"query": query}, headers=anonymous()).json()
        assert all(entry == observed[0] for entry in observed), query
        assert [(r["span_id"], r["score"]) for r in guest_search] == observed[0][0] == [(r["span_id"], r["score"]) for r in anonymous_search]
        assert (guest_asked["decision"], [c["span_id"] for c in guest_asked["citations"]]) == observed[0][1]
    assert invariance_violations(replays)["violating_item_ids"] == []


def test_ac_2_9_retrieval_abstention_and_resolver_take_no_learner_state_input():
    from app.services import contained_answers, lexical_index, retrieval_engine, span_resolver, spans

    allowed = {"self", "query", "lesson_slug", "top_k", "surface", "terms", "entry", "scored", "span_id", "db", "citation",
               "citations", "registry", "spans", "settings", "refresh", "store", "entries", "params", "abstention", "gate", "text"}
    callables = [
        lexical_index.LexicalIndex.__init__, lexical_index.LexicalIndex.evaluate, lexical_index.LexicalIndex.query_terms,
        lexical_index.LexicalIndex.score_entry, lexical_index.LexicalIndex.p1_score_entry, lexical_index.LexicalIndex.p1_scores,
        lexical_index.LexicalIndex.gate_entry,
        lexical_index.LexicalIndex.eligible_unfloored, lexical_index.tokenize, CourseStore.evaluate, CourseStore.search,
        CourseStore.to_search_result, CourseStore.entry, retrieval_engine.RetrievalEngine.search, span_resolver.SpanResolver.__init__,
        span_resolver.SpanResolver.resolve, span_resolver.SpanResolver.resolve_current, span_resolver.SpanResolver.verify,
        contained_answers.contain_answer,
    ]
    for function in callables:
        names = set(inspect.signature(function).parameters)
        assert names <= allowed, (function.__qualname__, names - allowed)
    forbidden_modules = {"app.services.learner_record", "app.services.learner_progress", "app.services.learning_intelligence",
                         "app.core.auth", "app.services.answer_history", "app.services.retrieval_legacy_p1"}
    for module in (lexical_index, retrieval_engine, span_resolver, spans, contained_answers):
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
        imported |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        assert not (imported & forbidden_modules), (module.__name__, imported & forbidden_modules)
    # The frozen baseline serves no request: no runtime module imports it.
    for path in (API_ROOT / "app").rglob("*.py"):
        if path.name == "retrieval_legacy_p1.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        modules = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
        assert "app.services.retrieval_legacy_p1" not in modules, path


def test_ac_2_9_invariance_over_seeded_random_queries():
    rng = random.Random(20261119)
    vocabulary = sorted({word for item in IN_DOMAIN for word in item["query"].split()} | {"France", "dog", "weather", "noise"})
    queries = [" ".join(rng.sample(vocabulary, rng.randint(1, 5))) for _ in range(40)] + rng.sample([i["query"] for i in IN_DOMAIN], 20)
    for gate in GATES:
        first, second = CourseStore(Settings(retrieval_gate=gate)), store_for("dev", gate)
        before = {q: first.evaluate(q, top_k=8) for q in queries}
        user = f"inv-random-{uuid4().hex[:8]}"
        _seed_learner(user, 0.7)  # learner state changes between the two passes; nothing reads it
        for query in queries:
            again = second.evaluate(query, top_k=8)
            assert (again.abstained, again.reason) == (before[query].abstained, before[query].reason), query
            assert [(r.entry.span_id, r.score) for r in again.results] == [(r.entry.span_id, r.score) for r in before[query].results], query


# ======================================================================================================== Plan G


def _seed_rows(sessions, citations: list, claims: list) -> tuple[int, str]:
    with sessions() as db:
        row = QAInteraction(user_id=f"mig-{uuid4().hex[:8]}", lesson_slug=None, question="q", answer="a", citations=citations)
        turn_id = f"turn-{uuid4().hex[:12]}"
        db.add(row)
        from app.db_models import TutorThread

        thread = TutorThread(id=f"thread-{uuid4().hex[:12]}", user_id=row.user_id, title="t")
        db.add(thread)
        db.flush()
        db.add(TutorTurn(id=turn_id, thread_id=thread.id, user_id=row.user_id, resolved_query="q", retrieval_mode="lexical",
                         provider="none", model="m", decision="answer", decision_reason="r", citations=citations, claims=claims,
                         corpus_version="manifest:x", policy_version="cs595-v1"))
        db.commit()
        return row.id, turn_id


def _texts(sessions) -> dict:
    with sessions() as db:
        qa_rows = db.execute(text("SELECT id, CAST(citations AS TEXT) FROM qa_interactions ORDER BY id")).all()
        turns = db.execute(text("SELECT id, CAST(citations AS TEXT), CAST(claims AS TEXT) FROM tutor_turns ORDER BY id")).all()
    return {"qa": [tuple(r) for r in qa_rows], "turns": [tuple(r) for r in turns]}


def test_plan_g_the_migration_is_reversible_byte_for_byte(fresh_database_url):
    sessions, engine = fresh_sessions(fresh_database_url)
    try:
        citations = _legacy_citations()
        claims = [{"text": "x", "cited_span_ids": [citations[1]["span_id"], citations[0]["chunk_id"]], "supported": True}]
        _seed_rows(sessions, citations, claims)
        non_canonical = json.dumps([citations[0]], separators=(",", ":"))
        with sessions() as db:
            value = "CAST(:c AS json)" if db.get_bind().dialect.name == "postgresql" else ":c"
            db.execute(text(f"INSERT INTO qa_interactions (user_id, question, answer, citations) VALUES (:u, 'q', 'a', {value})"),
                       {"u": f"mig-{uuid4().hex[:8]}", "c": non_canonical})
            db.commit()
        original = _texts(sessions)
        settings = Settings()
        memory, _ = build_identity_registry(settings, include_unapproved=True)
        run = lambda mode: migrate(sessions, mode=mode, memory=memory, settings=settings, package=get_config_package(settings),  # noqa: E731
                                   corpus_version="corpus-test")
        dry = run("dry-run")
        assert _texts(sessions) == original  # a dry run writes nothing
        with sessions() as db:
            assert db.scalar(select(CorpusSpan.id).where(CorpusSpan.registered_by == "migration").limit(1)) is None
        applied = run("apply")
        assert applied["tables"]["qa_interactions"]["rows_skipped_non_canonical"] == 1
        assert applied["threshold"]["result"] == "stop" and dry["threshold"]["result"] == "pass"
        assert applied["tables"]["tutor_turns"]["claims"]["remapped"] == 1
        migrated_texts = _texts(sessions)
        assert migrated_texts != original
        assert non_canonical in [row[1] for row in migrated_texts["qa"]]  # never rewritten
        again = run("apply")
        assert again["tables"]["qa_interactions"]["rows_changed"] == 0 and _texts(sessions) == migrated_texts  # idempotent
        run("downgrade")
        assert _texts(sessions) == original  # byte for byte
    finally:
        engine.dispose()


def test_plan_g_readers_dual_read_v0_v1_and_v2_citation_shapes():
    store = get_course_store()
    settings = Settings()
    registry = get_corpus_registry(settings)
    resolver = get_span_resolver()
    native = native_citation(store.search("QUBO logistics", top_k=1)[0], corpus_version=store.corpus_version, settings=settings)
    v0 = {"chunk_id": "l:d:1", "source_title": "S", "source_kind": "document", "section_title": "T", "excerpt": "E", "timestamp_label": None}
    v1 = {**v0, "span_id": "span-" + "1" * 64, "corpus_version": "manifest:x", "content_hash": "2" * 64, "source_filename": "x.docx", "provisional": True}
    unresolved_v2 = {**v0, "citation_schema": 2, "resolution": "legacy_unresolved", "migration_status": "legacy_unresolved",
                     "unresolved_reason": "excerpt_no_match", "label": UNRESOLVED_LABEL, "legacy_chunk_id": "l:d:1", "legacy_original": v0}
    read = lambda raw: label_stored_citation(raw, resolver=resolver, db=None, settings=settings, registry=registry)  # noqa: E731
    for raw in (v0, v1, unresolved_v2):
        citation = read(raw)
        assert (citation.resolution, citation.label, citation.provisional) == ("legacy_unresolved", UNRESOLVED_LABEL, True)
    assert read(unresolved_v2).unresolved_reason == "excerpt_no_match"
    assert read(native.model_dump()).resolution == "resolved"
    assert read("not a citation") is None and read({"chunk_id": "x"}) is None
    assert Citation.model_validate(v0).resolution == "legacy_unresolved"  # conservative defaults


def test_plan_g_provisional_is_lifted_only_for_resolved_citations_and_only_when_enabled(monkeypatch):
    lifted = Settings(citation_provisional_lift_enabled=True)
    assert provisional_flag("resolved", lifted) is False and provisional_flag("legacy_unresolved", lifted) is True
    assert provisional_flag("resolved", Settings()) is True
    store = get_course_store()
    hit = next(r for r in store.search("Why does routing depth matter?", top_k=8) if r.source_kind == "document")
    assert native_citation(hit, corpus_version=store.corpus_version, settings=lifted).provisional is False
    assert native_citation(hit, corpus_version=store.corpus_version, settings=Settings()).provisional is True
    contained = contain_answer([native_citation(hit, corpus_version=store.corpus_version, settings=lifted)],
                               get_corpus_registry(lifted), store.span_registry, settings=lifted)
    assert [c.provisional for c in contained.citations] == [False]

    production = Settings(environment="production", citation_provisional_lift_enabled=True)  # constructs: no refusal
    from app import main as main_module

    recorded = []
    monkeypatch.setattr(main_module, "IS_PRODUCTION", True)
    monkeypatch.setattr(main_module, "settings", production)
    monkeypatch.setattr(main_module, "record_security_event", lambda *args, **kwargs: recorded.append((args, kwargs)))
    main_module._record_configuration_overrides()
    (args, kwargs), = recorded
    assert args[0] == "config.override" and kwargs["details"].get("citation_provisional_lift_enabled") is True


# ======================================================================================================== Plan H


class _StubIndex:
    def __init__(self, *, extra: int = 0):
        self.vectors: dict[str, dict] = {}
        self.extra = extra
        self.matches: list[dict] = []

    def describe_index_stats(self):
        return {"namespaces": {"qcai-course": {"vector_count": len(self.vectors) + self.extra}}} if self.vectors or self.extra else {"namespaces": {}}

    def delete(self, **_):
        self.vectors.clear()

    def upsert(self, vectors, namespace):
        for vector in vectors:
            self.vectors[vector["id"]] = vector

    def query(self, **_):
        return {"matches": self.matches}


class _StubEmbeddings:
    def embed_documents(self, texts):
        return [[0.0] for _ in texts]

    def embed_query(self, _):
        return [0.0]


def _semantic_engine(store: CourseStore, *, enabled: bool, extra: int = 0) -> RetrievalEngine:
    settings = Settings(semantic_retrieval_enabled=enabled, openai_api_key="test-openai-key", pinecone_api_key="test-pinecone-key",
                        pinecone_index="test-index", retrieval_gate=store.gate)
    engine = RetrievalEngine(store, settings)
    engine._semantic_backend.__dict__["_index"] = _StubIndex(extra=extra)
    engine._semantic_backend.__dict__["_embeddings"] = _StubEmbeddings()
    return engine


def test_plan_h_the_semantic_backend_is_off_by_default_and_needs_span_ids():
    store = store_for("dev", "bm25f-v1")
    off = _semantic_engine(store, enabled=False)
    assert off.semantic_enabled is False and off._semantic_backend.enabled is False and off.sync_semantic_index() is False
    assert off.search("QUBO logistics").mode == "lexical"

    on = _semantic_engine(store, enabled=True)
    assert on.semantic_enabled is False  # not aligned until synced
    assert on.sync_semantic_index(refresh=True) is True and on.semantic_enabled is True
    index = on._semantic_backend._index
    assert set(index.vectors) == {entry.span_id for entry in store.chunks}
    assert all(set(v["metadata"]) == {"span_id", "span_scheme", "item_id", "item_version", "lesson_slugs"} for v in index.vectors.values())
    top = store.search("QUBO logistics", top_k=1)[0]
    index.matches = [{"id": "lesson:doc:1", "score": 0.9, "metadata": {"span_scheme": "span-v2"}},
                     {"id": top.span_id, "score": 0.8, "metadata": {"span_scheme": "legacy"}},
                     {"id": top.span_id, "score": 0.7, "metadata": {"span_scheme": "span-v2"}}]
    assert [r.span_id for r in on._semantic_backend.search("QUBO logistics")] == [top.span_id]

    mismatched = _semantic_engine(store, enabled=True, extra=3)
    assert mismatched.sync_semantic_index() is False and mismatched.search("QUBO logistics").mode == "lexical"


@pytest.mark.parametrize("gate", GATES)
def test_plan_h_every_hybrid_result_passes_the_active_gate(gate):
    store = store_for("dev", gate)
    engine = _semantic_engine(store, enabled=True)
    assert engine.sync_semantic_index(refresh=True)
    index = engine._semantic_backend._index
    index.matches = [{"id": entry.span_id, "score": 0.9, "metadata": {"span_scheme": "span-v2"}} for entry in store.chunks[:40]]
    modes = set()
    for query in ("QUBO logistics", "Why does routing depth matter?"):
        response = engine.search(query, top_k=5)
        modes.add(response.mode)
        for result in response.results:
            gated = store.index.gate_entry(query, store.entry(result.chunk_id), None)
            assert gated is not None, (gate, query)
            # Every fused result, a semantic-only one included, carries the score the gate compared with its floor
            # (the sufficiency records it; Phase 4 spec 4.6).
            assert response.gate_scores[result.chunk_id] == gated.gate_score is not None, (gate, query)
    assert "hybrid-pinecone" in modes, gate
    # A semantic-only result (it passes the gate but is outside the lexical results fusion starts from) carries the
    # gate's score too: semantic matches outside the lexical top rank first in the fusion.
    query, passing = next((item["query"], decision.results) for item in IN_DOMAIN
                          if len((decision := store.index.evaluate(item["query"], top_k=len(store.chunks))).results) > 10)
    lexical_top = {item.entry.span_id for item in passing[:10]}
    beyond = [item for item in passing if item.entry.span_id not in lexical_top]
    assert beyond, gate
    index.matches = [{"id": item.entry.span_id, "score": 0.9, "metadata": {"span_scheme": "span-v2"}} for item in beyond[:5]]
    response = engine.search(query, top_k=5)
    semantic_only = [result for result in response.results if result.chunk_id not in lexical_top]
    assert response.mode == "hybrid-pinecone" and semantic_only, gate
    for result in response.results:
        gated = store.index.gate_entry(query, store.entry(result.chunk_id), None)
        assert response.gate_scores[result.chunk_id] == gated.gate_score is not None, gate
    for query in OOS[:20]:
        response = engine.search(query, top_k=5)
        assert response.results == [] and response.abstained, (gate, query)


def test_plan_h_thresholds_are_provisional_until_phase_4(monkeypatch):
    package = get_config_package(Settings())
    record_path = REPO_ROOT / package.abstention.calibration_record
    record = json.loads(record_path.read_text(encoding="utf-8"))
    # Phase 2 made them provisional until Phase 4 (packages v1 and v2, and the record, say so); Phase 4 did not lift
    # that, so package v3 keeps them provisional until Q-22 sets them (DI-52).
    assert package.abstention.provisional is True and package.abstention.provisional_until == "Q-22 (DI-52)"
    for older in (V1_PACKAGE_PATH, V2_PACKAGE_PATH):
        abstention = load_config_package(older, governed=True).abstention
        assert abstention.provisional is True and abstention.provisional_until == record["provisional_until"] == "Phase 4"
    assert package.abstention.calibration_record_sha256 == canonical_sha256(record)
    assert (record["selection"]["floor"], record["selection"]["margin"]) == (package.abstention.floor, package.abstention.margin)
    assert record["public_corpus_only"] is True and record["provisional"] is True and record["result"] == "pass"
    assert "E1 freeze" in record["not_final_before"]

    original_read = Path.read_text
    original_open = open

    def guarded_read(self, *args, **kwargs):
        assert self.name != record_path.name, "the loader must never open the calibration record"
        return original_read(self, *args, **kwargs)

    def guarded_open(file, *args, **kwargs):
        assert Path(str(file)).name != record_path.name, "the loader must never open the calibration record"
        return original_open(file, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read)
    monkeypatch.setattr("builtins.open", guarded_open)
    assert load_config_package(package.path, governed=True).abstention.floor == package.abstention.floor


# ======================================================================================================== Plan L


def test_plan_l_the_migration_report_stops_on_an_unresolved_native_citation(fresh_database_url):
    # The exact-match regression stop has its own test (test_plan_l_an_exact_match_regression_stops_the_migration).
    from app.services.spans import SpanRecord, SpanRegistry, content_hash, legacy_excerpt_keys, span_id_for

    def record(item_id: str, text_value: str, start: int) -> SpanRecord:
        digest = content_hash(text_value)
        return SpanRecord(span_id_for(item_id, start, start + len(text_value), digest), "span-v2", item_id, "sha256:" + "0" * 16,
                          "document", "public", 0, "Section", "Source", f"{item_id}.docx", start, start + len(text_value), digest,
                          text_value, legacy_excerpt_keys(text_value))

    inner = record("doc-a", "Routing adds SWAP gates and increases depth.", 0)
    outer = record("doc-b", "Before. Routing adds SWAP gates and increases depth. After.", 0)
    memory = SpanRegistry([inner, outer])
    sessions, engine = fresh_sessions(fresh_database_url)
    try:
        legacy = {"chunk_id": "l:d:1", "source_title": "Source", "source_kind": "document", "section_title": "Section",
                  "excerpt": "Routing adds SWAP gates and increases depth.", "timestamp_label": None}
        native = {**legacy, "chunk_id": "span-" + "9" * 64, "span_id": "span-" + "9" * 64, "content_hash": "8" * 64,
                  "citation_schema": 2, "resolution": "resolved", "migration_status": "native"}
        with sessions() as db:
            db.add(QAInteraction(user_id=f"plan-l-{uuid4().hex[:8]}", question="q", answer="a", citations=[legacy]))
            db.commit()
        settings = Settings()
        report = migrate(sessions, mode="dry-run", memory=memory, settings=settings, package=get_config_package(settings),
                         corpus_version="corpus-test", tables=["qa_interactions"])
        counts = report["tables"]["qa_interactions"]["citations"]
        assert counts["migrated"] == 1 and counts["diagnostics"]["containment_also_in_other_span"] == 1
        assert report["threshold"]["result"] == "pass"
        with sessions() as db:
            db.add(QAInteraction(user_id=f"plan-l-{uuid4().hex[:8]}", question="q", answer="a", citations=[native]))
            db.commit()
        stopped = migrate(sessions, mode="dry-run", memory=memory, settings=settings, package=get_config_package(settings),
                          corpus_version="corpus-test", tables=["qa_interactions"])
        assert stopped["totals"]["native_unresolved"] == 1 and stopped["threshold"]["result"] == "stop"
        assert any("does not resolve" in reason for reason in stopped["threshold"]["stop_reasons"])
    finally:
        engine.dispose()


def _span_record(item_id: str, text_value: str, start: int, version: str = "0" * 16):
    from app.services.spans import SpanRecord, content_hash, legacy_excerpt_keys, span_id_for

    digest = content_hash(text_value)
    return SpanRecord(span_id_for(item_id, start, start + len(text_value), digest), "span-v2", item_id, "sha256:" + version,
                      "document", "public", 0, "Section", "Source", f"{item_id}.docx", start, start + len(text_value), digest,
                      text_value, legacy_excerpt_keys(text_value))


def test_plan_l_an_exact_match_regression_stops_the_migration(fresh_database_url):
    from app.services.spans import SpanRegistry

    text_value = "Routing adds SWAP gates and increases depth."
    older = _span_record("doc-a", text_value, 0)  # registered before an edit shifted the item's offsets
    current = _span_record("doc-a", text_value, 40, version="1" * 16)
    sessions, engine = fresh_sessions(fresh_database_url)
    try:
        with sessions() as db:
            db.add(QAInteraction(user_id=f"plan-l-{uuid4().hex[:8]}", question="q", answer="a", citations=[
                {"chunk_id": "l:d:1", "source_title": "Source", "source_kind": "document", "section_title": "Section",
                 "excerpt": text_value, "timestamp_label": None}]))
            db.commit()
        settings = Settings()
        run = lambda: migrate(sessions, mode="dry-run", memory=SpanRegistry([current]), settings=settings,  # noqa: E731
                              package=get_config_package(settings), corpus_version="corpus-test", tables=["qa_interactions"])
        control = run()  # unique in the current build, nothing older registered: it migrates and the run passes
        assert control["tables"]["qa_interactions"]["citations"]["migrated"] == 1 and control["threshold"]["result"] == "pass"
        with sessions() as db:
            persist_spans(db, [older], corpus_version="corpus-old", registered_by="register-job")
            db.commit()
        report = run()
        counts = report["tables"]["qa_interactions"]["citations"]
        # Unique in the current build, ambiguous only through the older registered span: D10's regression.
        assert counts["by_reason"]["excerpt_ambiguous"] == 1 and report["totals"]["exact_match_regressions"] == 1
        assert report["threshold"]["result"] == "stop"
        assert any("exact-match" in reason for reason in report["threshold"]["stop_reasons"])


        # A migrated citation whose span no longer resolves anywhere is the other regression (AC-2-3: migrated resolves).
        with sessions() as db:
            db.execute(text("DELETE FROM qa_interactions"))
            db.add(QAInteraction(user_id=f"plan-l-{uuid4().hex[:8]}", question="q", answer="a", citations=[
                {"chunk_id": "span-" + "7" * 64, "span_id": "span-" + "7" * 64, "content_hash": "6" * 64, "excerpt": text_value,
                 "source_title": "Source", "source_kind": "document", "section_title": "Section", "timestamp_label": None,
                 "citation_schema": 2, "resolution": "resolved", "migration_status": "migrated"}]))
            db.commit()
        stale = run()
        assert stale["tables"]["qa_interactions"]["citations"]["already_migrated"] == 1
        assert stale["totals"]["exact_match_regressions"] == 1 and stale["threshold"]["result"] == "stop"
    finally:
        engine.dispose()


def _package_with_legacy_rule(**rule):
    from dataclasses import replace

    package = get_config_package(Settings())
    return replace(package, legacy_citations={**package.legacy_citations, **rule})


def test_plan_l_the_d30_legacy_threshold_is_enforced_from_the_configuration_package(fresh_database_url, tmp_path, monkeypatch):
    from app.services.spans import SpanRegistry

    memory = SpanRegistry([_span_record("doc-a", "Routing adds SWAP gates.", 0)])
    sessions, engine = fresh_sessions(fresh_database_url)
    try:
        legacy = {"chunk_id": "l:d:1", "source_title": "Source", "source_kind": "document", "section_title": "Section", "timestamp_label": None}
        with sessions() as db:  # one citation migrates, one stays legacy_unresolved: share 0.5
            db.add(QAInteraction(user_id=f"plan-l-{uuid4().hex[:8]}", question="q", answer="a", citations=[
                {**legacy, "excerpt": "Routing adds SWAP gates."}, {**legacy, "excerpt": "Nothing in the corpus says this."}]))
            db.commit()
        settings = Settings()

        def run(package):
            return migrate(sessions, mode="dry-run", memory=memory, settings=settings, package=package, corpus_version="corpus-test",
                           tables=["qa_interactions"])

        shipped = run(get_config_package(settings))  # D-30 open: null, reported and labelled, not gated
        assert shipped["totals"]["unresolved_share"] == 0.5 and shipped["threshold"]["legacy_gated"] is False
        assert shipped["threshold"]["result"] == "pass"
        stopped = run(_package_with_legacy_rule(max_unresolved_share_legacy=0.2))
        assert stopped["threshold"]["result"] == "stop" and stopped["threshold"]["legacy_share_observed"] == 0.5
        assert any("exceeds the D-30 legacy threshold 0.2" in reason for reason in stopped["threshold"]["stop_reasons"])
        assert run(_package_with_legacy_rule(max_unresolved_share_legacy=0.6))["threshold"]["result"] == "pass"
        # The Wilson upper bound of 1 of 2 is about 0.91, so the same limit stops under that statistic.
        upper = run(_package_with_legacy_rule(max_unresolved_share_legacy=0.6, legacy_share_statistic="wilson95_upper"))
        assert upper["threshold"]["result"] == "stop" and upper["threshold"]["legacy_share_observed"] > 0.6

        # The job's exit code follows the comparison: 3 is a stop (plan Phase 2 L).
        from app.workers import migrate_citations as worker

        monkeypatch.setattr(worker, "SessionLocal", sessions)
        monkeypatch.setattr(worker, "build_identity_registry", lambda *_args, **_kwargs: (memory, None))
        monkeypatch.setattr(worker, "get_config_package", lambda _settings: _package_with_legacy_rule(max_unresolved_share_legacy=0.2))
        assert worker.main(["--dry-run", "--tables", "qa_interactions", "--report", str(tmp_path / "report.json")]) == EXIT_STOP
        monkeypatch.setattr(worker, "get_config_package", lambda _settings: get_config_package(settings))
        assert worker.main(["--dry-run", "--tables", "qa_interactions"]) == 0
    finally:
        engine.dispose()


def _approved_document_settings(tmp_path: Path, **extra) -> Settings:
    def approve(payload):
        for item in payload["items"]:
            if ROUTING_DOCUMENT in item["asset_filenames"]:
                item["public_service"] = True

    return Settings(environment="production", enforce_corpus_governance=True, manifest_drift_check="off",
                    corpus_manifest_path=str(edited_manifest(tmp_path, approve)), **extra)


def test_plan_l_the_p1_floor_recall_stop_refuses_governed_start_up_with_an_approved_document(tmp_path, monkeypatch):
    from app import main as main_module

    monkeypatch.setattr(main_module, "STARTUP_DRIFT", main_module.STARTUP_DRIFT)  # restored after the test
    stopped = _approved_document_settings(tmp_path)
    assert stopped.retrieval_gate == "p1-floor"  # the shipped default outside development
    assert p1_floor_recall_stop(CorpusRegistry(stopped), stopped) == [source_asset_id(ROUTING_DOCUMENT, "document")]
    monkeypatch.setattr(main_module, "settings", stopped)
    with pytest.raises(CorpusGovernanceError, match="recall stop \\(Phase 2 spec conflict 29\\)"):
        main_module._check_corpus_before_any_table()
    # The D-05 switch to bm25f-v1 lifts it; the committed D-31 manifest never triggers it.
    for allowed in (stopped.model_copy(update={"retrieval_gate": "bm25f-v1"}),
                    settings_for("governed_empty").model_copy(update={"manifest_drift_check": "off"})):
        monkeypatch.setattr(main_module, "settings", allowed)
        main_module._check_corpus_before_any_table()
    # The owner override starts, and outside development it is reported as a config.override event.
    overridden = stopped.model_copy(update={"allow_p1_floor_with_documents": True})
    monkeypatch.setattr(main_module, "settings", overridden)
    main_module._check_corpus_before_any_table()
    recorded = []
    monkeypatch.setattr(main_module, "IS_PRODUCTION", True)
    monkeypatch.setattr(main_module, "record_security_event", lambda *args, **kwargs: recorded.append((args, kwargs)))
    main_module._record_configuration_overrides()
    (args, kwargs), = recorded
    assert args[0] == "config.override" and kwargs["details"]["p1_floor_recall_stop_overridden"] is True
    # Development measures any gate freely (its default is bm25f-v1).
    development = Settings(retrieval_gate="p1-floor")
    assert p1_floor_recall_stop(get_corpus_registry(development), development) == []


def test_plan_l_validate_corpus_refuses_an_approved_document_under_the_p1_floor_gate(tmp_path, monkeypatch, capsys):
    module = load_script("validate_corpus")
    for name in ("RETRIEVAL_GATE", "ALLOW_P1_FLOOR_WITH_DOCUMENTS"):
        monkeypatch.delenv(name, raising=False)
    assert module.main(["--check-recall-stop"]) == 0  # the committed manifest (the CI step)
    assert "Recall stop (spec conflict 29) clear" in capsys.readouterr().out
    monkeypatch.setenv("CORPUS_MANIFEST_PATH", _approved_document_settings(tmp_path).corpus_manifest_path)
    assert module.main(["--check-recall-stop"]) == 1
    assert "Recall stop (Phase 2 spec conflict 29)" in capsys.readouterr().err
    monkeypatch.setenv("RETRIEVAL_GATE", "bm25f-v1")  # the D-05 switch lifts it
    assert module.main(["--check-recall-stop"]) == 0
    monkeypatch.delenv("RETRIEVAL_GATE")
    monkeypatch.setenv("ALLOW_P1_FLOOR_WITH_DOCUMENTS", "true")  # the owner override passes, and says so
    assert module.main(["--check-recall-stop"]) == 0
    assert "recall stop overridden" in capsys.readouterr().err


# ======================================================================================================== Tasks and D9


def test_task_2_7_chapter_summaries_are_never_evidence():
    store = store_for("dev")
    assert not [entry for entry in store.chunks if entry.source_kind not in {"document", "lesson"}]
    assert any(lesson.chapters for lesson in store.lessons.values()), "chapters stay as lesson presentation"
    assert {chapter.transcript_status for lesson in store.lessons.values() for chapter in lesson.chapters} == {"curated_chapter_summary"}
    chapter_texts = {chapter.summary for lesson in store.lessons.values() for chapter in lesson.chapters}
    assert not ({entry.excerpt for entry in store.chunks} & chapter_texts)
    for query in ("nested routing", "Why does routing depth matter?", "industry use cases"):
        assert all(result.source_kind != "video" and result.timestamp_label is None for result in store.search(query, top_k=20))


def test_task_2_1_the_committed_manifest_is_generated_from_disk(tmp_path):
    env = {**os.environ, "DATABASE_URL": "sqlite:///:memory:"}
    script = str(REPO_ROOT / "scripts" / "generate_manifest.py")
    completed = subprocess.run([sys.executable, script, "--check", "--video-hash", "size"], cwd=REPO_ROOT, capture_output=True,
                               text=True, timeout=300, env=env)
    assert completed.returncode == 0, completed.stderr
    outputs = []
    for run in range(2):
        target = tmp_path / f"run{run}.json"
        done = subprocess.run([sys.executable, script, "--video-hash", "size", "--existing", str(REPO_MANIFEST), "--output", str(target)],
                              cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, env=env)
        assert done.returncode == 0, done.stderr
        outputs.append(target.read_bytes())
    assert outputs[0] == outputs[1]  # stable: two runs give an identical file
    assert json.loads(outputs[0]) == json.loads(REPO_MANIFEST.read_text(encoding="utf-8"))
    refused = subprocess.run([sys.executable, script, "--all-public-approved", "--video-hash", "size"], cwd=REPO_ROOT,
                             capture_output=True, text=True, timeout=300, env=env)
    assert refused.returncode == 2 and "refused" in refused.stderr


def test_d9_ready_reports_the_configuration_package_corpus_gate_and_slis():
    package = get_config_package(Settings())
    body = client.get("/ready").json()
    assert body["status"] == "ready"
    # Phase 3: /ready reports the package in force (2.0.0 since configuration package v2), not a fixed version.
    assert (body["config_package_version"], body["config_package_sha256"]) == (package.package_version, package.sha256)
    assert body["span_scheme"] == "span-v2" and body["index_version"] == get_course_store().index_version
    assert body["corpus_version"] == get_corpus_registry(Settings()).corpus_version
    assert (body["retrieval_gate"], body["duplicate_span_ids"], body["manifest_drift"]) == ("bm25f-v1", 0, 0)
    # The thresholds in force are the active gate's (bm25f-v1 in development); the calibrated block is always there.
    assert (body["abstention_floor"], body["abstention_margin"], body["thresholds_provisional"]) == (package.abstention.floor, package.abstention.margin, True)
    assert body["threshold_version"] == package.abstention.version
    assert body["bm25f_v1_calibrated"] == {"version": package.abstention.version, "floor": package.abstention.floor,
                                           "margin": package.abstention.margin, "provisional": True, "provisional_until": "Q-22 (DI-52)"}
    assert (body["semantic_enabled"], body["semantic_setting"]) == (False, False)
    slis = body["slis"]
    # Still an exact set: Phase 3 adds exactly the ledger and the two-pass shadow SLIs (plan Phase 3 I).
    assert set(slis) == {"citation_resolution", "abstention", "search_latency_ms", "manifest_drift"} | {"tutor_ledger", "two_pass_shadow"}
    assert slis["manifest_drift"]["drifted"] == 0 and slis["manifest_drift"]["checked"] >= 13


def test_d9_ready_reports_the_p1_floor_threshold_in_force_and_the_effective_semantic_state(monkeypatch):
    from app import main as main_module

    package = get_config_package(Settings())
    governed = store_for("governed_empty")  # p1-floor, the gate outside development
    monkeypatch.setattr(main_module, "get_course_store", lambda: governed)
    monkeypatch.setattr(main_module, "settings", settings_for("governed_empty"))
    monkeypatch.setattr(main_module, "get_retrieval_engine", lambda: RetrievalEngine(governed, settings_for("governed_empty")))
    fields = main_module._build_fields()
    assert (fields["retrieval_gate"], fields["threshold_version"], fields["abstention_floor"], fields["abstention_margin"]) == (
        "p1-floor", "score-floor-p1-v1", 6.0, 0.0)
    assert (fields["thresholds_provisional"], fields["threshold_authority"]) == (False, "P1-D-04")
    assert fields["bm25f_v1_calibrated"]["floor"] == package.abstention.floor  # reported, but not in force
    # The setting alone never enables hybrid retrieval: this process has not aligned span-id vectors.
    switched = Settings(semantic_retrieval_enabled=True, openai_api_key="test-openai-key", pinecone_api_key="test-pinecone-key",
                        pinecone_index="test-index")
    monkeypatch.setattr(main_module, "settings", switched)
    monkeypatch.setattr(main_module, "get_retrieval_engine", lambda: RetrievalEngine(governed, switched))
    fields = main_module._build_fields()
    assert (fields["semantic_setting"], fields["semantic_enabled"]) == (True, False)


def _startup(database_url: str, extra_env: dict[str, str]) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": database_url, "ENVIRONMENT": "development", "PYTHONUNBUFFERED": "1", **extra_env}
    return subprocess.run([sys.executable, "-c", "from app.main import _initialize_database; _initialize_database()"],
                          cwd=API_ROOT, env=env, capture_output=True, text=True, timeout=180)


@pytest.mark.parametrize("damage", ["tampered", "invalid"])
def test_d9_an_invalid_or_tampered_configuration_package_stops_governed_start_up_before_any_table_exists(fresh_database_url, tmp_path, damage):
    package_path = tmp_path / "v1.json"
    payload = json.loads(get_config_package(Settings()).path.read_text(encoding="utf-8"))
    sidecar = canonical_sha256(payload)
    if damage == "tampered":
        payload["abstention"]["floor"] = 0.0  # a valid package that no longer matches its recorded hash
    else:
        payload["retrieval"]["k1"] = -1
    package_path.write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "v1.json.sha256").write_text(sidecar + "\r\n", encoding="utf-8")
    completed = _startup(fresh_database_url, {"CONFIG_PACKAGE_PATH": str(package_path), "ENFORCE_CORPUS_GOVERNANCE": "true",
                                              "CORPUS_MANIFEST_PATH": str(REPO_MANIFEST)})
    assert completed.returncode != 0
    assert "ConfigPackageError" in completed.stderr
    probe = create_engine(fresh_database_url)
    try:
        assert set(sa_inspect(probe).get_table_names()) == set()
    finally:
        probe.dispose()
    clear_config_package_cache()
    with pytest.raises(ConfigPackageError):
        load_config_package(package_path, governed=True)
    if damage == "tampered":
        assert load_config_package(package_path, governed=False).hash_verified is False  # development only warns


def test_spans_route_resolves_metadata_and_never_an_excerpt_under_d31(monkeypatch):
    store = get_course_store()
    authored = next(r for r in store.span_registry.records if r.item_kind == "authored")
    document = next(e for e in store.chunks if e.item_kind == "document")
    for span_id in (authored.span_id, document.span_id):
        response = client.get(f"/spans/{span_id}", headers=anonymous())
        assert response.status_code == 200, response.text
        body = response.json()
        assert (body["span_id"], body["current"], body["servable"], body["excerpt"]) == (span_id, True, False, None)
        assert body["plane"] == "public" and body["end"] > body["start"]
        assert response.headers["cache-control"] == spans_route.SPAN_CACHE_CONTROL
    for missing in ("not-a-span", "span-" + "0" * 64, "span-" + "A" * 64):
        response = client.get(f"/spans/{missing}", headers=anonymous())
        assert (response.status_code, response.json(), response.headers["cache-control"]) == (404, {"detail": "Span not found."}, "no-store")
    governed = settings_for("governed_empty")
    monkeypatch.setattr(spans_route, "get_settings", lambda: governed.model_copy(update={"span_resolver_route_enabled": True}))
    monkeypatch.setattr(spans_route, "get_span_resolver", lambda: SpanResolver(store))
    assert client.get(f"/spans/{document.span_id}", headers=anonymous()).status_code == 404  # not approved under D-31
    assert client.get(f"/spans/{authored.span_id}", headers=anonymous()).status_code == 200  # authored spans resolve
    monkeypatch.setattr(spans_route, "get_settings", lambda: Settings(span_resolver_route_enabled=False))
    disabled = client.get(f"/spans/{authored.span_id}", headers=anonymous())
    assert disabled.status_code == 404 and disabled.headers["cache-control"] == "no-store"


def test_the_shipped_gate_outside_development_is_p1_floor_and_bm25_is_an_override(monkeypatch):
    assert Settings(environment="production").retrieval_gate == "p1-floor"
    assert Settings(environment="production").span_resolver_route_enabled is False
    assert Settings().retrieval_gate == "bm25f-v1" and Settings().span_resolver_route_enabled is True
    assert store_for("governed_empty").gate == "p1-floor"
    from app import main as main_module

    recorded = []
    monkeypatch.setenv("RETRIEVAL_GATE", "bm25f-v1")
    monkeypatch.setattr(main_module, "IS_PRODUCTION", True)
    monkeypatch.setattr(main_module, "settings", Settings(environment="production"))
    monkeypatch.setattr(main_module, "record_security_event", lambda *args, **kwargs: recorded.append((args, kwargs)))
    main_module._record_configuration_overrides()
    (args, kwargs), = recorded
    assert args[0] == "config.override" and kwargs["details"]["retrieval_gate_bm25"] is True
