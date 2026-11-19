"""Near-duplicate fingerprint gate (plan Phase 2 task 2.9; Phase 2 spec 3.10; package `near_duplicate`).

Plan: "Fingerprint gate fails on near-duplicates; the duplicate stays unbound until Q-10 [Evidence E-21]". The
gate looks at bound, public-plane items only, approved or not, and fails when two of them are near-duplicates:
- documents and the authored item: word-shingle Jaccard >= the threshold, or containment >= its threshold;
- videos: equal sha256, equal size, both durations known and within the tolerance with sizes within the size
  ratio (mp4-mvhd-v1: the 2025/2026 re-encode), or curated-chapter shingle Jaccard >= the chapter threshold.
A decoded-audio fingerprint needs ffmpeg, which CI lacks; it is deferred (spec section 12).
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
import re
import unicodedata
from typing import Any

from app.core.config import Settings
from app.core.config_package import ConfigPackage, NearDuplicateParams

WORD_PATTERN = re.compile(r"[^\W_]+")


@dataclass(frozen=True)
class Candidate:
    item_id: str
    kind: str
    text: str | None = None
    sha256: str | None = None
    size_bytes: int | None = None
    duration_s: float | None = None
    chapter_text: str | None = None


@dataclass(frozen=True)
class NearDuplicatePair:
    a: str
    b: str
    kind: str
    reasons: tuple[str, ...]
    jaccard: float | None = None
    containment: float | None = None


def words(text: str) -> list[str]:
    return WORD_PATTERN.findall(unicodedata.normalize("NFKC", text).casefold())


def word_shingles(text: str, size: int) -> set[str]:
    tokens = words(text)
    if len(tokens) < size:
        return {" ".join(tokens)} if tokens else set()
    return {" ".join(tokens[index : index + size]) for index in range(len(tokens) - size + 1)}


def jaccard(a: set[str], b: set[str]) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def containment(a: set[str], b: set[str]) -> float:
    smaller = min(len(a), len(b))
    return len(a & b) / smaller if smaller else 0.0


def text_pair(a: Candidate, b: Candidate, params: NearDuplicateParams) -> NearDuplicatePair | None:
    shingles_a = word_shingles(a.text or "", params.shingle_words)
    shingles_b = word_shingles(b.text or "", params.shingle_words)
    j, c = jaccard(shingles_a, shingles_b), containment(shingles_a, shingles_b)
    reasons = []
    if j >= params.jaccard:
        reasons.append(f"shingle Jaccard {j:.4f} >= {params.jaccard}")
    if c >= params.containment:
        reasons.append(f"shingle containment {c:.4f} >= {params.containment}")
    if not reasons:
        return None
    return NearDuplicatePair(a.item_id, b.item_id, "text", tuple(reasons), round(j, 6), round(c, 6))


def video_pair(a: Candidate, b: Candidate, params: NearDuplicateParams) -> NearDuplicatePair | None:
    reasons = []
    if a.sha256 and a.sha256 == b.sha256:
        reasons.append("equal sha256")
    if a.size_bytes is not None and a.size_bytes == b.size_bytes:
        reasons.append("equal size")
    if a.duration_s is not None and b.duration_s is not None and a.size_bytes and b.size_bytes:
        duration_gap = abs(a.duration_s - b.duration_s)
        size_ratio = abs(a.size_bytes - b.size_bytes) / max(a.size_bytes, b.size_bytes)
        if duration_gap <= params.video_duration_tolerance_s and size_ratio <= params.video_size_ratio_tolerance:
            reasons.append(f"mp4-mvhd-v1: duration within {duration_gap:.3f} s and size within {size_ratio:.4%}")
    j = None
    if a.chapter_text and b.chapter_text:
        j = jaccard(word_shingles(a.chapter_text, params.chapter_shingle_words), word_shingles(b.chapter_text, params.chapter_shingle_words))
        if j >= params.chapter_jaccard:
            reasons.append(f"curated chapter Jaccard {j:.4f} >= {params.chapter_jaccard}")
    if not reasons:
        return None
    return NearDuplicatePair(a.item_id, b.item_id, "video", tuple(reasons), None if j is None else round(j, 6), None)


def near_duplicate_pairs(candidates: list[Candidate], params: NearDuplicateParams) -> list[NearDuplicatePair]:
    pairs: list[NearDuplicatePair] = []
    texts = [candidate for candidate in candidates if candidate.kind in {"document", "authored"}]
    videos = [candidate for candidate in candidates if candidate.kind == "video"]
    for a, b in combinations(texts, 2):
        pair = text_pair(a, b, params)
        if pair:
            pairs.append(pair)
    for a, b in combinations(videos, 2):
        pair = video_pair(a, b, params)
        if pair:
            pairs.append(pair)
    return pairs


def chapter_text(settings: Settings, filename: str) -> str:
    from app.services.transcripts import load_video_chapters

    return "\n".join(f"{chapter.title}\n{chapter.summary}" for chapter in load_video_chapters(settings.transcripts_dir, filename))


def candidates_from_manifest(manifest: dict[str, Any], root: Path, package: ConfigPackage) -> list[Candidate]:
    """The bound, public-plane items of a 2.0 manifest, approved or not, with their fingerprint inputs."""
    from app.services.content_assembler import DOCUMENT_TITLE_MAP, MODULE_BLUEPRINTS
    from app.services.spans import canonical_authored, canonical_document

    settings = Settings(source_assets_root=str(root))
    out: list[Candidate] = []
    for item in manifest.get("items", []):
        filenames = item.get("asset_filenames") or []
        if item.get("plane") != "public" or not item.get("bound", True):
            continue
        if item["id"] in package.q10_unbound_item_ids or set(filenames) & package.q10_unbound_filenames:
            continue
        kind = item.get("kind")
        if kind == "authored":
            out.append(Candidate(item["id"], "authored", text=canonical_authored(MODULE_BLUEPRINTS, item_version=item["version"]).text))
        elif kind == "document":
            paths = settings._resolve_source_assets(filenames[:1])
            text = canonical_document(paths[0], item_id=item["id"], item_version=item["version"],
                                      source_title=DOCUMENT_TITLE_MAP.get(filenames[0], filenames[0])).text if paths else ""
            out.append(Candidate(item["id"], "document", text=text, sha256=item.get("sha256"), size_bytes=item.get("size_bytes")))
        elif kind == "video":
            media = item.get("media") or {}
            out.append(
                Candidate(
                    item["id"],
                    "video",
                    sha256=item.get("sha256"),
                    size_bytes=item.get("size_bytes"),
                    duration_s=media.get("duration_s"),
                    chapter_text=chapter_text(settings, filenames[0]) if filenames else None,
                )
            )
    return out
