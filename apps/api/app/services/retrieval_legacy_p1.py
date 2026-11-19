"""FROZEN copy of the pre-Phase-2 index build and search, as at commit a257dd11. Do not change it.

It is the AC-2-5 baseline: plan Phase 2 K reads "In-domain recall@5 is not below the recall@5 baseline recorded
in BEP-0 by task 0.11 or, if absent, the pre-migration commit in the same CI run". BEP-0 recorded no recall@5
baseline, and CI checks out one commit (fetch-depth 1), so the pre-migration algorithm runs from this module in
the same test or calibration run (Phase 2 spec, conflict 15). tests/data/legacy_p1_baseline.json, recorded from
the unmodified code, proves its fidelity (test_ac_2_5_the_frozen_legacy_search_reproduces_the_pre_migration_snapshot).

Only the AC-2-5 tests and scripts/calibrate_abstention.py import it; an AST test keeps every runtime module off it.
It reproduces the old CourseStore.build chunk loop exactly: colliding chunk ids, video chapter summaries as
chunks, the authored fallback for lessons with no other chunk, module boosts and substring scoring. The 2026
video stays bound here, as it was at a257dd11.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import Settings
from app.core.source_assets import source_asset_id
from app.services.content_assembler import ASSET_TITLE_MAP, DOCUMENT_TITLE_MAP, MODULE_BLUEPRINTS, _module_lessons
from app.services.docx_parser import SectionRecord, parse_docx_sections
from app.services.retrieval_p1 import QUERY_STOPWORDS, SCORE_FLOOR, IndexedChunk, _floor_score, _tokenize
from app.services.text_utils import truncate_display_excerpt
from app.services.transcripts import load_video_chapters

LEGACY_ALGORITHM = "score-floor-p1-v1"


@dataclass(frozen=True)
class LegacyResult:
    chunk_id: str
    lesson_slug: str | None
    score: float
    source_kind: str
    title: str
    excerpt: str


@dataclass(frozen=True)
class _LegacyVideo:
    id: str
    title: str
    filename: str


def _format_timestamp(seconds: int) -> str:
    minutes, secs = divmod(seconds, 60)
    return f"{minutes:02d}:{secs:02d}"


def _load_sections(documents: list[Path]) -> list[SectionRecord]:
    all_sections: list[SectionRecord] = []
    for path in documents:
        if path.exists():
            document_title = DOCUMENT_TITLE_MAP.get(path.name, path.stem)
            sections = parse_docx_sections(path)
            for section in sections:
                section.source_title = document_title
            all_sections.extend(sections)
    return all_sections


def _match_sections(sections: list[SectionRecord], refs: list[str], document_file: str | None = None) -> list[SectionRecord]:
    if not refs:
        return []
    document_source_id = None
    if document_file:
        document_source_id = Path(document_file).stem.lower().replace(" ", "-")
    matched: list[SectionRecord] = []
    used_keys: set[str] = set()
    for ref in refs:
        ref_l = ref.lower()
        for section in sections:
            if document_source_id and section.source_id != document_source_id:
                continue
            key = f"{section.source_title}:{section.heading}"
            if key in used_keys:
                continue
            if ref_l in section.heading.lower():
                matched.append(section)
                used_keys.add(key)
    return matched


def _authored_chunks(splitter, module_index: int, lesson: dict[str, Any]) -> list[IndexedChunk]:
    authored_parts = [
        lesson["summary"],
        "\n".join(f"Key idea: {idea}" for idea in lesson["key_ideas"]),
        "\n".join(f"Key note: {note}" for note in lesson["key_notes"]),
        "\n".join(f"Formula or diagram prompt: {formula}" for formula in lesson["formulas"]),
        "\n".join(f"Learner question: {question}" for question in lesson["learner_questions"]),
    ]
    authored_text = "\n\n".join(part for part in authored_parts if part)
    if not authored_text:
        return []
    return [
        IndexedChunk(
            chunk_id=f"{lesson['slug']}:lesson-authored:{index}",
            title=lesson["title"],
            source_kind="lesson",
            source_title=lesson["title"],
            excerpt=excerpt,
            lesson_slug=lesson["slug"],
            score_boost=float(module_index) + 0.1,
        )
        for index, excerpt in enumerate(splitter.split_text(authored_text), start=1)
    ]


def build_legacy_chunks(settings: Settings, documents: list[Path], videos: list[Path]) -> list[IndexedChunk]:
    """The a257dd11 CourseStore chunk list for the served documents and videos given."""
    splitter = RecursiveCharacterTextSplitter(chunk_size=700, chunk_overlap=120)
    sections = _load_sections(documents)
    video_assets = [
        _LegacyVideo(id=source_asset_id(path.name, "video"), title=ASSET_TITLE_MAP.get(path.name, path.name), filename=path.name)
        for path in videos
    ]
    chunks: list[IndexedChunk] = []
    for module_index, blueprint in enumerate(MODULE_BLUEPRINTS, start=1):
        for lesson in _module_lessons(blueprint):
            matched = _match_sections(sections, lesson["section_refs"], lesson.get("document_file"))
            video_asset = next((asset for asset in video_assets if asset.filename == lesson["video_file"]), None)
            chapters = load_video_chapters(settings.transcripts_dir, video_asset.filename) if video_asset else []
            lesson_chunks: list[IndexedChunk] = []
            for section in matched:
                for index, excerpt in enumerate(splitter.split_text(section.body), start=1):
                    lesson_chunks.append(
                        IndexedChunk(
                            chunk_id=f"{lesson['slug']}:{section.source_id}:{index}",
                            title=section.heading,
                            source_kind="document",
                            source_title=section.source_title,
                            excerpt=excerpt,
                            lesson_slug=lesson["slug"],
                            score_boost=float(module_index),
                            source_filename=section.source_filename or None,
                        )
                    )
            if video_asset:
                for chapter in chapters:
                    lesson_chunks.append(
                        IndexedChunk(
                            chunk_id=f"{lesson['slug']}:{video_asset.id}:{chapter.id}",
                            title=chapter.title,
                            source_kind="video",
                            source_title=video_asset.title,
                            excerpt=chapter.summary,
                            lesson_slug=lesson["slug"],
                            score_boost=float(module_index) + 0.2,
                            timestamp_label=_format_timestamp(chapter.timestamp_start),
                        )
                    )
            if not lesson_chunks:
                lesson_chunks.extend(_authored_chunks(splitter, module_index, lesson))
            chunks.extend(lesson_chunks)
    return chunks


def legacy_search(
    chunks: list[IndexedChunk],
    query: str,
    lesson_slug: str | None = None,
    top_k: int = 8,
    *,
    score_floor: int = SCORE_FLOOR,
) -> list[LegacyResult]:
    """The a257dd11 CourseStore.search, with the floor as a parameter (0 is the ungated Phase 1 comparison)."""
    query_terms = {token for token in _tokenize(query) if token}
    floor_terms = query_terms - QUERY_STOPWORDS
    raw_query = query.strip().lower()
    if not raw_query:
        return []
    results: list[LegacyResult] = []
    for chunk in chunks:
        if lesson_slug and chunk.lesson_slug != lesson_slug:
            continue
        title_text = chunk.title.lower()
        excerpt_text = chunk.excerpt.lower()
        title_overlap = sum(1 for term in query_terms if term in title_text)
        excerpt_overlap = sum(1 for term in query_terms if term in excerpt_text)
        phrase_bonus = 0
        if len(raw_query) >= 3:
            phrase_bonus = 4 if raw_query in title_text else 2 if raw_query in excerpt_text else 0
        if title_overlap == 0 and excerpt_overlap == 0 and phrase_bonus == 0:
            continue
        if _floor_score(floor_terms, chunk, phrase_bonus) < score_floor:
            continue
        score = title_overlap * 3 + excerpt_overlap * 2 + phrase_bonus + chunk.score_boost
        results.append(
            LegacyResult(
                chunk_id=chunk.chunk_id,
                lesson_slug=chunk.lesson_slug,
                score=round(score, 3),
                source_kind=chunk.source_kind,
                title=chunk.title,
                excerpt=truncate_display_excerpt(chunk.excerpt, 320),
            )
        )
    results.sort(key=lambda item: item.score, reverse=True)
    return results[:top_k]
