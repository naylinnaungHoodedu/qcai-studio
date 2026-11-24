"""Evidence pointers: EV-ids through a research-plane evidence catalog, span ids through Phase 2 (spec 3.4, 4.3; PD-62).

An EV-id resolves to a catalog record shaped like a span record (document, volume, page, character offsets, byte length,
content sha256 under the Phase 2 rule `sha256(text.encode("utf-8"))`). A public `span-<hex64>` id resolves through the
Phase 2 SpanResolver, which returns nothing for a private-plane or unknown span. No locator ever holds text: the catalog
loader checks a line's text against its hash and length, then drops it. Only a check against the corpus text itself
(`corpus_text`) verifies an EV pointer character for character; a resolution says whether that check ran (`verified`),
and the freeze requires it for every resolved EV pointer.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from typing import Any, Callable, Mapping, Sequence

from .canonical import canonical_sha256, read_jsonl

PROVISIONAL_DEFAULTS = ("PD-62",)
EV_ID = re.compile(r"^EV-(2025|2026|IND|SYN)-p[0-9]{3}-[0-9]{2}$")
SPAN_ID = re.compile(r"^span-[0-9a-f]{64}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
VOLUMES = ("qcai" + "_2025", "qcai" + "_2026", "industry_use_cases", "synthetic")
CATALOG_KEYS = ("evidence_id", "document_id", "volume", "page", "char_start", "char_end", "byte_length", "content_sha256",
                "corpus_version")
STATUSES = ("resolved", "malformed", "no_catalog", "unknown_pointer", "corpus_version_mismatch", "hash_mismatch", "no_span_lookup")

SpanLookup = Callable[[str], "Mapping[str, Any] | None"]


def content_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class EvidenceRecord:
    evidence_id: str
    document_id: str
    volume: str
    page: int
    char_start: int
    char_end: int
    byte_length: int
    content_sha256: str
    corpus_version: str

    def locator(self) -> dict[str, Any]:
        return {key: getattr(self, key) for key in CATALOG_KEYS}


def _integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


class EvidenceCatalog:
    def __init__(self, records: Mapping[str, EvidenceRecord], sha256: str, corpus_version: str) -> None:
        self.records = dict(records)
        self.sha256 = sha256
        self.corpus_version = corpus_version

    @classmethod
    def load(cls, path: Path) -> "EvidenceCatalog":
        return cls.from_lines(read_jsonl(Path(path)))

    @classmethod
    def from_lines(cls, lines: Sequence[Mapping[str, Any]]) -> "EvidenceCatalog":
        records: dict[str, EvidenceRecord] = {}
        stripped = []
        for number, line in enumerate(lines, start=1):
            for key in CATALOG_KEYS:
                if key not in line:
                    raise ValueError(f"catalog line {number}: {key} missing")
            for key in line:
                if key not in CATALOG_KEYS and key != "text":
                    raise ValueError(f"catalog line {number}: {key} unexpected")
            if not isinstance(line["evidence_id"], str) or not EV_ID.match(line["evidence_id"]):
                raise ValueError(f"catalog line {number}: evidence_id pattern")
            if line["volume"] not in VOLUMES:
                raise ValueError(f"catalog line {number}: volume enum")
            if not isinstance(line["document_id"], str) or not line["document_id"]:
                raise ValueError(f"catalog line {number}: document_id type")
            if not _integer(line["page"]) or line["page"] < 1:
                raise ValueError(f"catalog line {number}: page")
            if not (_integer(line["char_start"]) and _integer(line["char_end"]) and 0 <= line["char_start"] < line["char_end"]):
                raise ValueError(f"catalog line {number}: char offsets")
            if not _integer(line["byte_length"]) or line["byte_length"] < 1:
                raise ValueError(f"catalog line {number}: byte_length")
            if not isinstance(line["content_sha256"], str) or not HEX64.match(line["content_sha256"]):
                raise ValueError(f"catalog line {number}: content_sha256 pattern")
            if "text" in line:
                text = line["text"]
                if not isinstance(text, str) or content_sha256(text) != line["content_sha256"]:
                    raise ValueError(f"catalog line {number}: hash_mismatch")
                if len(text.encode("utf-8")) != line["byte_length"]:
                    raise ValueError(f"catalog line {number}: byte_length mismatch")
            if line["evidence_id"] in records:
                raise ValueError(f"catalog line {number}: duplicate evidence_id")
            kept = {key: line[key] for key in CATALOG_KEYS}
            stripped.append(kept)
            records[line["evidence_id"]] = EvidenceRecord(**kept)
        versions = {record.corpus_version for record in records.values()}
        if len(versions) != 1:
            raise ValueError("catalog: exactly one corpus_version is required")
        sha256 = canonical_sha256(sorted(stripped, key=lambda entry: entry["evidence_id"]))
        return cls(records, sha256, versions.pop())

    def get(self, evidence_id: str) -> EvidenceRecord | None:
        return self.records.get(evidence_id)


@dataclass(frozen=True)
class Resolution:
    pointer: str
    kind: str
    status: str
    locator: Mapping[str, Any] | None
    verified: bool = False  # an EV pointer whose span was checked against the corpus text, character for character


class PointerResolver:
    def __init__(self, *, catalog: EvidenceCatalog | None = None, span_lookup: SpanLookup | None = None,
                 corpus_text: Callable[[str], str | None] | None = None, corpus_version: str | None = None) -> None:
        self.catalog = catalog
        self.span_lookup = span_lookup
        self.corpus_text = corpus_text
        self.corpus_version = corpus_version

    def resolve(self, pointer: str) -> Resolution:
        if isinstance(pointer, str) and EV_ID.match(pointer):
            if self.catalog is None:
                return Resolution(pointer, "evidence", "no_catalog", None)
            record = self.catalog.get(pointer)
            if record is None:
                return Resolution(pointer, "evidence", "unknown_pointer", None)
            if self.corpus_version is not None and record.corpus_version != self.corpus_version:
                return Resolution(pointer, "evidence", "corpus_version_mismatch", None)
            if self.corpus_text is None:
                return Resolution(pointer, "evidence", "resolved", record.locator())
            document = self.corpus_text(record.document_id)
            span = None if document is None else document[record.char_start:record.char_end]
            if span is None or content_sha256(span) != record.content_sha256:
                return Resolution(pointer, "evidence", "hash_mismatch", None)
            return Resolution(pointer, "evidence", "resolved", record.locator(), verified=True)
        if isinstance(pointer, str) and SPAN_ID.match(pointer):
            if self.span_lookup is None:
                return Resolution(pointer, "span", "no_span_lookup", None)
            locator = self.span_lookup(pointer)
            if locator is None:
                return Resolution(pointer, "span", "unknown_pointer", None)
            return Resolution(pointer, "span", "resolved", {key: value for key, value in dict(locator).items() if key != "text"})
        return Resolution(str(pointer), "unknown", "malformed", None)

    def byte_length(self, pointer: str) -> int | None:
        resolution = self.resolve(pointer)
        if resolution.status != "resolved" or resolution.locator is None:
            return None
        return int(resolution.locator["byte_length"])

    def content_hash(self, pointer: str) -> str | None:
        resolution = self.resolve(pointer)
        if resolution.status != "resolved" or resolution.locator is None:
            return None
        locator = resolution.locator
        return str(locator.get("content_sha256") or locator.get("content_hash"))


@dataclass(frozen=True)
class PointerReport:
    total: int
    resolved: int
    problems: tuple[tuple[str, str, str, str], ...]   # (item_id, field path, status, pointer kind)
    evidence_resolved: int = 0   # EV pointers that resolved
    text_verified: int = 0       # of those, the ones checked against the corpus text


def resolve_items(items: Sequence[Mapping[str, Any]], resolver: PointerResolver) -> PointerReport:
    from .ulqs import pointers_of

    total = resolved = evidence_resolved = text_verified = 0
    problems: list[tuple[str, str, str, str]] = []
    for item in items:
        for path, pointer in pointers_of(item):
            total += 1
            resolution = resolver.resolve(pointer)
            if resolution.status == "resolved":
                resolved += 1
                if resolution.kind == "evidence":
                    evidence_resolved += 1
                    text_verified += int(resolution.verified)
            else:
                problems.append((str(item.get("item_id")), path, resolution.status, resolution.kind))
    return PointerReport(total=total, resolved=resolved, problems=tuple(problems), evidence_resolved=evidence_resolved,
                         text_verified=text_verified)


def public_span_lookup() -> SpanLookup:
    """The Phase 2 resolver over the public course store, reduced to a text-free locator."""
    from .planes import _app_on_path

    _app_on_path()
    from app.services.span_resolver import SpanResolver
    from app.services.store import get_course_store

    resolver = SpanResolver(get_course_store())

    def lookup(span_id: str) -> Mapping[str, Any] | None:
        span = resolver.resolve_current(span_id)
        if span is None:
            return None
        byte_length = len(span.text.encode("utf-8")) if span.text is not None else None
        return {"item_id": span.item_id, "item_version": span.item_version, "start": span.start, "end": span.end,
                "byte_length": byte_length, "content_hash": span.content_hash}

    return lookup
