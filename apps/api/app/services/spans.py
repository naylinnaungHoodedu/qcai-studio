"""Span identity (plan Phase 2 task 2.2; Phase 2 spec 2.2 and 3.1-3.3).

A span is a character range of an item's deterministic canonical text: (item_id, item_version, start, end,
content_hash). Its id hashes only (scheme, item_id, start, end, content_hash), never corpus_version, licence or
approval fields, or lesson slugs, so a rebuild yields the same ids (AC-2-1) and a manifest licence edit changes
none (AC-2-2). Offsets are item-global: an edit early in an item rotates the ids of later spans, and the
append-only corpus_spans table keeps the old ids resolvable.

Canonical text "sections-v1":
- a document is parse_docx_sections joined as heading + "\\n\\n" + body, sections separated by "\\n\\n\\n";
- the authored item is the lessons of MODULE_BLUEPRINTS in order, each heading the lesson title and each body the
  authored lesson text exactly as Phase 1 indexed it.
Spans are the RecursiveCharacterTextSplitter chunks of each body, located with LangChain's add_start_index rule.
Span text lives in memory only; the database holds identity and hashes, never text.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import hashlib
import importlib.metadata
from pathlib import Path
import threading
from typing import Any, Literal

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import Settings
from app.core.config_package import ConfigPackage, canonical_json, canonical_sha256, get_config_package
from app.services.docx_parser import SectionRecord, parse_docx_sections
from app.services.text_utils import truncate_display_excerpt

SPAN_SCHEME = "span-v2"
CANONICAL_TEXT_VERSION = "sections-v1"
AUTHORED_ITEM_ID = "authored-curriculum"
SECTION_SEPARATOR = "\n\n\n"
HEADING_SEPARATOR = "\n\n"
DISPLAY_EXCERPT_CHARS = 320


class SpanBuildError(RuntimeError):
    """The canonical text or its spans cannot be built deterministically (a new span scheme would be needed)."""


_CHECKED_VERSIONS: set[tuple[str, str]] = set()
_CHECK_LOCK = threading.Lock()


def check_library_versions(package: ConfigPackage, *, force: bool = False) -> None:
    """The splitter and parser must be the versions the span scheme was defined with (spec 3.2, [R7]).

    Read through importlib.metadata: langchain_text_splitters.__version__ is None in 1.1.2. Checked lazily, on
    the first build in a process, never at import.
    """
    key = (str(package.splitter.get("version")), str(package.parser.get("version")))
    with _CHECK_LOCK:
        if key in _CHECKED_VERSIONS and not force:
            return
        installed = {
            "langchain-text-splitters": importlib.metadata.version("langchain-text-splitters"),
            "python-docx": importlib.metadata.version("python-docx"),
        }
        expected = {"langchain-text-splitters": key[0], "python-docx": key[1]}
        mismatched = {name: (installed[name], expected[name]) for name in expected if installed[name] != expected[name]}
        if mismatched:
            details = ", ".join(f"{name} {have} installed, package pins {want}" for name, (have, want) in mismatched.items())
            raise SpanBuildError(f"Span scheme {SPAN_SCHEME} needs its pinned libraries: {details}")
        _CHECKED_VERSIONS.add(key)


@dataclass(frozen=True)
class SpanRecord:
    span_id: str
    scheme: str
    item_id: str
    item_version: str
    item_kind: Literal["document", "authored"]
    plane: Literal["public"]
    section_ordinal: int
    section_title: str
    source_title: str
    source_filename: str | None
    start: int
    end: int
    content_hash: str
    text: str
    legacy_keys: tuple[str, str]


@dataclass(frozen=True)
class CanonicalSection:
    ordinal: int
    heading: str
    body: str
    body_start: int
    lesson_slug: str | None


@dataclass(frozen=True)
class CanonicalItem:
    item_id: str
    item_version: str
    kind: Literal["document", "authored"]
    plane: Literal["public"]
    source_title: str | None
    source_filename: str | None
    text: str
    sections: tuple[CanonicalSection, ...]


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def content_hash(text: str) -> str:
    return sha256_text(text)


def span_id_for(item_id: str, start: int, end: int, content_hash: str, scheme: str = SPAN_SCHEME) -> str:
    identity = {"scheme": scheme, "item_id": item_id, "start": start, "end": end, "content_hash": content_hash}
    return "span-" + hashlib.sha256(canonical_json(identity)).hexdigest()


def _ws(value: str) -> str:
    return " ".join(value.split())


def excerpt_key(excerpt: str) -> str:
    """The key of a stored citation's excerpt: sha256 of its whitespace-normalised text (spec 3.8)."""
    return sha256_text(_ws(excerpt))


def legacy_excerpt_keys(text: str) -> tuple[str, str]:
    """(lexical, semantic): the excerpt keys a pre-Phase-2 citation of this span text would carry.

    The lexical path displayed truncate_display_excerpt twice (search result, then citation); the semantic path
    once (its result held the full chunk text).
    """
    once = truncate_display_excerpt(text, DISPLAY_EXCERPT_CHARS)
    twice = truncate_display_excerpt(once, DISPLAY_EXCERPT_CHARS)
    return sha256_text(_ws(twice)), sha256_text(_ws(once))


def make_splitter(package: ConfigPackage) -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=int(package.splitter["chunk_size"]), chunk_overlap=int(package.splitter["chunk_overlap"])
    )


def _join_sections(entries: list[tuple[str, str, str | None]]) -> tuple[str, list[CanonicalSection]]:
    parts: list[str] = []
    sections: list[CanonicalSection] = []
    position = 0
    for ordinal, (heading, body, lesson_slug) in enumerate(entries):
        if ordinal:
            parts.append(SECTION_SEPARATOR)
            position += len(SECTION_SEPARATOR)
        parts.append(heading)
        position += len(heading)
        parts.append(HEADING_SEPARATOR)
        position += len(HEADING_SEPARATOR)
        sections.append(CanonicalSection(ordinal=ordinal, heading=heading, body=body, body_start=position, lesson_slug=lesson_slug))
        parts.append(body)
        position += len(body)
    return "".join(parts), sections


def canonical_document(
    path: Path,
    *,
    item_id: str,
    item_version: str,
    source_title: str,
    sections: list[SectionRecord] | None = None,
) -> CanonicalItem:
    records = parse_docx_sections(path) if sections is None else sections
    text, canonical_sections = _join_sections([(record.heading, record.body, None) for record in records])
    return CanonicalItem(
        item_id=item_id,
        item_version=item_version,
        kind="document",
        plane="public",
        source_title=source_title,
        source_filename=path.name,
        text=text,
        sections=tuple(canonical_sections),
    )


def _lessons(blueprints: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    from app.services.content_assembler import _module_lessons

    return [(blueprint, lesson) for blueprint in blueprints for lesson in _module_lessons(blueprint)]


def authored_body(lesson: Mapping[str, Any]) -> str:
    """The authored lesson text, exactly as Phase 1 indexed it (content_assembler._build_authored_lesson_chunks)."""
    parts = [
        lesson["summary"],
        "\n".join(f"Key idea: {idea}" for idea in lesson["key_ideas"]),
        "\n".join(f"Key note: {note}" for note in lesson["key_notes"]),
        "\n".join(f"Formula or diagram prompt: {formula}" for formula in lesson["formulas"]),
        "\n".join(f"Learner question: {question}" for question in lesson["learner_questions"]),
    ]
    return "\n\n".join(part for part in parts if part)


def authored_payload(blueprints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "lesson_slug": lesson["slug"],
            "module_slug": blueprint["slug"],
            "title": lesson["title"],
            "summary": lesson["summary"],
            "key_ideas": list(lesson["key_ideas"]),
            "key_notes": list(lesson["key_notes"]),
            "formulas": list(lesson["formulas"]),
            "learner_questions": list(lesson["learner_questions"]),
        }
        for blueprint, lesson in _lessons(blueprints)
    ]


def authored_canonical_bytes(blueprints: list[dict[str, Any]]) -> bytes:
    return canonical_json(authored_payload(blueprints))


def authored_sha256(blueprints: list[dict[str, Any]]) -> str:
    return canonical_sha256(authored_payload(blueprints))


def canonical_authored(blueprints: list[dict[str, Any]], *, item_version: str) -> CanonicalItem:
    entries = [(lesson["title"], authored_body(lesson), lesson["slug"]) for _, lesson in _lessons(blueprints)]
    text, sections = _join_sections(entries)
    return CanonicalItem(
        item_id=AUTHORED_ITEM_ID,
        item_version=item_version,
        kind="authored",
        plane="public",
        source_title=None,
        source_filename=None,
        text=text,
        sections=tuple(sections),
    )


def build_spans(item: CanonicalItem, splitter: RecursiveCharacterTextSplitter) -> list[SpanRecord]:
    if item.plane != "public":  # pragma: no cover - the type allows only "public"; kept as a fail-closed guard
        raise SpanBuildError(f"{item.item_id}: spans are built for public-plane items only")
    overlap = int(getattr(splitter, "_chunk_overlap", 0))
    records: list[SpanRecord] = []
    seen: set[tuple[str, int, int]] = set()
    for section in item.sections:
        index = 0
        previous = 0
        for chunk in splitter.split_text(section.body):
            offset = index + previous - overlap
            local = section.body.find(chunk, max(0, offset))
            if local < 0:
                raise SpanBuildError(f"{item.item_id}: section {section.ordinal} has a chunk the splitter cannot place")
            start = section.body_start + local
            end = start + len(chunk)
            if item.text[start:end] != chunk:
                raise SpanBuildError(f"{item.item_id}: section {section.ordinal} offsets do not reproduce the chunk")
            index = local
            previous = len(chunk)
            if (item.item_id, start, end) in seen:
                continue
            seen.add((item.item_id, start, end))
            digest = content_hash(chunk)
            source_title = item.source_title if item.source_title is not None else section.heading
            records.append(
                SpanRecord(
                    span_id=span_id_for(item.item_id, start, end, digest),
                    scheme=SPAN_SCHEME,
                    item_id=item.item_id,
                    item_version=item.item_version,
                    item_kind=item.kind,
                    plane="public",
                    section_ordinal=section.ordinal,
                    section_title=section.heading,
                    source_title=source_title,
                    source_filename=item.source_filename,
                    start=start,
                    end=end,
                    content_hash=digest,
                    text=chunk,
                    legacy_keys=legacy_excerpt_keys(chunk),
                )
            )
    return records


def span_set_digest(span_ids: Iterable[str]) -> str:
    return sha256_text("\n".join(sorted(span_ids)))


class SpanRegistry:
    """The spans of the built items, by id and by (item, section)."""

    def __init__(self, records: Iterable[SpanRecord] = ()) -> None:
        all_records = list(records)
        self._all_count = len(all_records)
        self._by_id: dict[str, SpanRecord] = {}
        self._by_section: dict[tuple[str, int], list[SpanRecord]] = {}
        for record in all_records:
            self._by_id.setdefault(record.span_id, record)
            self._by_section.setdefault((record.item_id, record.section_ordinal), []).append(record)
        self._records = tuple(self._by_id.values())

    def get(self, span_id: str | None) -> SpanRecord | None:
        return self._by_id.get(span_id) if span_id else None

    def for_section(self, item_id: str, ordinal: int) -> list[SpanRecord]:
        return list(self._by_section.get((item_id, ordinal), []))

    @property
    def records(self) -> tuple[SpanRecord, ...]:
        return self._records

    @property
    def duplicate_ids(self) -> int:
        """The duplicate-id SLI: spans built minus distinct ids (plan Phase 2 I: 0)."""
        return self._all_count - len(self._by_id)

    @property
    def item_ids(self) -> frozenset[str]:
        return frozenset(record.item_id for record in self._records)

    def __len__(self) -> int:
        return len(self._records)

    def __contains__(self, span_id: object) -> bool:
        return span_id in self._by_id


def build_identity_registry(settings: Settings, *, include_unapproved: bool) -> tuple[SpanRegistry, dict[str, CanonicalItem]]:
    """Span identity for the authored item and every public-plane, bound document on disk.

    Unapproved documents are included only when include_unapproved is true: the register and migration jobs need
    their text-free identity to match legacy citations; nothing serves them (task 2.8; spec conflict 21).
    """
    from app.core.corpus_governance import get_corpus_registry
    from app.core.data_planes import assert_public_plane_path
    from app.services.content_assembler import DOCUMENT_TITLE_MAP, MODULE_BLUEPRINTS

    package = get_config_package(settings)
    check_library_versions(package)
    registry = get_corpus_registry(settings)
    splitter = make_splitter(package)
    items: dict[str, CanonicalItem] = {}
    records: list[SpanRecord] = []
    authored = registry.authored_item
    if authored is None or authored.bound:
        version = "sha256:" + authored_sha256(MODULE_BLUEPRINTS)[:16]
        item = canonical_authored(MODULE_BLUEPRINTS, item_version=version)
        items[item.item_id] = item
        records.extend(build_spans(item, splitter))
    for path in settings.source_documents:
        if registry.is_private_plane(path.name) or not registry.is_bound(path.name):
            continue
        if not include_unapproved and not registry.is_indexable(path.name):
            continue
        assert_public_plane_path(path, settings.project_root, package.boundary)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        item = canonical_document(
            path,
            item_id=registry.span_item_id(path.name),
            item_version="sha256:" + digest[:16],
            source_title=DOCUMENT_TITLE_MAP.get(path.name, path.stem),
        )
        items[item.item_id] = item
        records.extend(build_spans(item, splitter))
    return SpanRegistry(records), items
