"""Manifest v2, generated from disk (plan Phase 2 task 2.1; section 11.1; Phase 2 spec 2.1, 3.4, 3.11, 3.12).

One item per source asset the application knows (config SOURCE_DOCUMENT_NAMES and SOURCE_VIDEO_NAMES, in the
root or update_data/) plus one "authored-curriculum" item for the lesson text in MODULE_BLUEPRINTS. Each item
carries the sha256 of its content (for a Git LFS pointer, the pointer's oid, which is the content hash), its
size, a content-derived version, its plane, whether it is bound to lessons, and the licence fields carried over
from the existing manifest. corpus_version (plan 11.1) hashes the sorted (item_id, item_version, sha256) of the
built items plus the span scheme, so a content or membership change, partial approval included, yields a new
version and a membership-neutral licence edit does not. The manifest records the governed value.
"""

from __future__ import annotations

import copy
import fnmatch
import hashlib
import json
from pathlib import Path
import re
import struct
from typing import Any

from app.core.config import SOURCE_DOCUMENT_NAMES, SOURCE_VIDEO_NAMES
from app.core.config_package import ConfigPackage, canonical_json
from app.core.source_assets import source_asset_id

SCHEMA_VERSION = "2.0"
GENERATOR = "manifest-gen-v1"
MANIFEST_STATUS = "generated_pending_rights_review"
CORPUS_VERSION_SCHEME = "corpus-version-v3"
LFS_POINTER_PREFIX = b"version https://git-lfs.github.com/spec/v1\n"
LFS_POINTER_MAX_BYTES = 1024
HASH_BLOCK = 1024 * 1024
AUTHORED_SOURCE_MODULE = "apps/api/app/services/content_assembler.py:MODULE_BLUEPRINTS"
Q10_UNBOUND_REASON = "Q-10 unresolved: 2025 asset only (plan Action 25); re-encode of the 2025 lecture [Evidence E-21]"
DEFAULT_LICENCE = {
    "source": "QC+AI Studio repository asset (rights review pending, Decision D-02)",
    "license": "UNDETERMINED",
    "permitted_use": "none until rights review (Decision D-31)",
    "public_service": False,
}
AUTHORED_LICENCE = {
    "source": "QC+AI Studio authored curriculum",
    "license": "UNDETERMINED",
    "permitted_use": "platform curriculum text; indexed by kind, not a D-31 source asset",
    "public_service": False,
}
LICENCE_FIELDS = ("source", "license", "permitted_use", "public_service")


class ManifestError(RuntimeError):
    """The manifest cannot be generated or checked from what is on disk."""


def read_lfs_pointer(path: Path) -> dict[str, Any] | None:
    """{"oid", "size"} when the file is a Git LFS pointer, else None (spec 3.11)."""
    try:
        if path.stat().st_size >= LFS_POINTER_MAX_BYTES:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if not data.startswith(LFS_POINTER_PREFIX):
        return None
    text = data.decode("utf-8", errors="replace")
    oid = re.search(r"^oid sha256:([0-9a-f]{64})$", text, re.MULTILINE)
    size = re.search(r"^size (\d+)$", text, re.MULTILINE)
    if not oid or not size:
        return None
    return {"oid": oid.group(1), "size": int(size.group(1))}


def is_lfs_pointer(path: Path) -> bool:
    return read_lfs_pointer(path) is not None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(HASH_BLOCK), b""):
            digest.update(block)
    return digest.hexdigest()


def file_sha256_and_size(path: Path, *, video_hash: str = "full") -> tuple[str | None, int, str]:
    """(sha256, size, basis). basis is "lfs-pointer", "content" or "size-only" (sha256 None: not hashed)."""
    pointer = read_lfs_pointer(path)
    if pointer is not None:
        return pointer["oid"], pointer["size"], "lfs-pointer"
    size = path.stat().st_size
    if video_hash == "size":
        return None, size, "size-only"
    return sha256_file(path), size, "content"


def _boxes(stream, start: int, end: int):
    position = start
    while position + 8 <= end:
        stream.seek(position)
        header = stream.read(8)
        if len(header) < 8:
            return
        size, box_type = struct.unpack(">I4s", header)
        header_length = 8
        if size == 1:
            large = stream.read(8)
            if len(large) < 8:
                return
            size = struct.unpack(">Q", large)[0]
            header_length = 16
        elif size == 0:
            size = end - position
        if size < header_length:
            return
        yield box_type, position, header_length, size
        position += size


def mp4_duration_seconds(path: Path) -> float | None:
    """Movie duration from the moov/mvhd box (mp4-mvhd-v1); None for a pointer, a missing box or a bad file."""
    if is_lfs_pointer(path):
        return None
    try:
        end = path.stat().st_size
        with path.open("rb") as stream:
            for box_type, position, header_length, size in _boxes(stream, 0, end):
                if box_type != b"moov":
                    continue
                for inner_type, inner_position, inner_header, _ in _boxes(stream, position + header_length, position + size):
                    if inner_type != b"mvhd":
                        continue
                    stream.seek(inner_position + inner_header)
                    version = stream.read(1)[0]
                    stream.read(3)
                    if version == 1:
                        stream.read(16)
                        timescale, duration = struct.unpack(">IQ", stream.read(12))
                    else:
                        stream.read(8)
                        timescale, duration = struct.unpack(">II", stream.read(8))
                    return round(duration / timescale, 3) if timescale else None
    except (OSError, struct.error, IndexError):
        return None
    return None


def lfs_patterns(root: Path) -> list[str]:
    attributes = root / ".gitattributes"
    if not attributes.exists():
        return []
    patterns = []
    for line in attributes.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if len(fields) >= 2 and not fields[0].startswith("#") and "filter=lfs" in fields[1:]:
            patterns.append(fields[0])
    return patterns


def lfs_tracked(rel_path: str, root: Path) -> bool:
    name = rel_path.rsplit("/", 1)[-1]
    for pattern in lfs_patterns(root):
        target = rel_path if "/" in pattern.strip("/") else name
        if fnmatch.fnmatchcase(target, pattern.lstrip("/")):
            return True
    return False


def is_built_item(item: dict[str, Any], *, governed: bool = True) -> bool:
    """Plan 11.1 "built items": a public-plane, bound item the build admits. A governed build admits the authored
    item and the approved items (Decision D-31); development admits every public-plane, bound item."""
    if item.get("plane") != "public" or not item.get("bound", True):
        return False
    return item.get("kind") == "authored" or item.get("public_service") is True or not governed


def corpus_version_of(rows: list[list[str]], span_scheme: str) -> str:
    """corpus-version-v3 over (item_id, item_version, sha256) rows of the built items (plan 11.1; spec 3.4)."""
    payload = {"scheme": CORPUS_VERSION_SCHEME, "span_scheme": span_scheme, "items": sorted(rows)}
    return "corpus-" + hashlib.sha256(canonical_json(payload)).hexdigest()[:16]


def compute_corpus_version(items: list[dict[str, Any]], span_scheme: str = "span-v2", *, governed: bool = True) -> str:
    """The corpus_version of the items a build admits (governed by default, the value the manifest records).

    Licence fields never enter it; approval does, because it changes membership ("including partial approval").
    """
    return corpus_version_of([[item["id"], item["version"], item["sha256"]] for item in items if is_built_item(item, governed=governed)], span_scheme)


def _existing_licence(existing: dict[str, Any] | None, item_id: str, filenames: list[str], defaults: dict[str, Any]) -> dict[str, Any]:
    if not existing:
        return dict(defaults)
    for raw in existing.get("items", []) or []:
        if not isinstance(raw, dict):
            continue
        same = raw.get("id") == item_id if existing.get("schema_version") == SCHEMA_VERSION else bool(
            filenames and set(filenames) & set(raw.get("asset_filenames", []))
        )
        if same:
            return {field: raw.get(field, defaults[field]) for field in LICENCE_FIELDS}
    return dict(defaults)


def _existing_item(existing: dict[str, Any] | None, item_id: str) -> dict[str, Any] | None:
    if not existing or existing.get("schema_version") != SCHEMA_VERSION:
        return None
    return next((raw for raw in existing.get("items", []) if isinstance(raw, dict) and raw.get("id") == item_id), None)


def _resolve(root: Path, name: str) -> Path | None:
    for candidate_root in (root, root / "update_data"):
        candidate = candidate_root / name
        if candidate.exists():
            return candidate
    return None


def build_manifest(root: Path, existing: dict[str, Any] | None, package: ConfigPackage, *, video_hash: str = "full",
                   warnings: list[str] | None = None) -> dict[str, Any]:
    """The manifest for the assets under root (files resolved as Settings._resolve_source_assets does)."""
    from app.services.content_assembler import MODULE_BLUEPRINTS
    from app.services.spans import (
        AUTHORED_ITEM_ID,
        CANONICAL_TEXT_VERSION,
        SPAN_SCHEME,
        authored_canonical_bytes,
        authored_sha256,
        build_spans,
        canonical_authored,
        canonical_document,
        check_library_versions,
        make_splitter,
        span_set_digest,
    )
    from app.services.content_assembler import DOCUMENT_TITLE_MAP

    warnings = warnings if warnings is not None else []
    check_library_versions(package)
    splitter = make_splitter(package)
    root = Path(root).resolve()
    items: list[dict[str, Any]] = []
    for kind, names in (("document", SOURCE_DOCUMENT_NAMES), ("video", SOURCE_VIDEO_NAMES)):
        for name in names:
            path = _resolve(root, name)
            if path is None:
                raise ManifestError(f"{name}: not found under {root} or its update_data/")
            item_id = source_asset_id(name, kind)
            previous = _existing_item(existing, item_id)
            rel = path.relative_to(root).as_posix()
            sha, size, basis = file_sha256_and_size(path, video_hash=video_hash if kind == "video" else "full")
            if sha is None:
                if previous and previous.get("size_bytes") == size and previous.get("sha256"):
                    sha = previous["sha256"]
                else:
                    raise ManifestError(f"{name}: size changed and --video-hash size cannot hash it; use --video-hash full")
            bound = item_id not in package.q10_unbound_item_ids and name not in package.q10_unbound_filenames
            spans = None
            media = None
            if kind == "document":
                version = "sha256:" + sha[:16]
                canonical = canonical_document(path, item_id=item_id, item_version=version, source_title=DOCUMENT_TITLE_MAP.get(name, path.stem))
                span_ids = [record.span_id for record in build_spans(canonical, splitter)]
                spans = {"scheme": SPAN_SCHEME, "canonical_text": CANONICAL_TEXT_VERSION, "count": len(span_ids), "set_sha256": span_set_digest(span_ids)}
            else:
                duration = mp4_duration_seconds(path) if basis == "content" or basis == "size-only" else None
                if duration is not None:
                    media = {"duration_s": duration, "basis": "mp4-mvhd-v1"}
                elif previous and previous.get("sha256") == sha and previous.get("media"):
                    media = previous["media"]
                else:
                    warnings.append(f"{name}: duration unknown (LFS pointer with no earlier manifest entry)")
            item = {
                "id": item_id,
                "kind": kind,
                "plane": "public",
                "asset_filenames": [name],
                "asset_paths": [rel],
                "storage": "git-lfs" if lfs_tracked(rel, root) else "git",
                "sha256": sha,
                "hash_basis": "content-sha256",
                "size_bytes": size,
                "version": "sha256:" + sha[:16],
                "bound": bound,
                "unbound_reason": None if bound else Q10_UNBOUND_REASON,
                "spans": spans,
                "media": media,
            }
            item.update(_existing_licence(existing, item_id, [name], DEFAULT_LICENCE))
            items.append(item)
    authored_hash = authored_sha256(MODULE_BLUEPRINTS)
    authored_version = "sha256:" + authored_hash[:16]
    authored_spans = [record.span_id for record in build_spans(canonical_authored(MODULE_BLUEPRINTS, item_version=authored_version), splitter)]
    authored = {
        "id": AUTHORED_ITEM_ID,
        "kind": "authored",
        "plane": "public",
        "asset_filenames": [],
        "asset_paths": [],
        "storage": "code",
        "source_module": AUTHORED_SOURCE_MODULE,
        "sha256": authored_hash,
        "hash_basis": "canonical-json-authored-v1",
        "size_bytes": len(authored_canonical_bytes(MODULE_BLUEPRINTS)),
        "version": authored_version,
        "bound": True,
        "unbound_reason": None,
        "spans": {"scheme": SPAN_SCHEME, "canonical_text": CANONICAL_TEXT_VERSION, "count": len(authored_spans), "set_sha256": span_set_digest(authored_spans)},
        "media": None,
    }
    authored.update(_existing_licence(existing, AUTHORED_ITEM_ID, [], AUTHORED_LICENCE))
    items.append(authored)
    items.sort(key=lambda item: item["id"])
    return {
        "schema_version": SCHEMA_VERSION,
        "manifest_status": MANIFEST_STATUS,
        "generator": GENERATOR,
        "span_scheme": SPAN_SCHEME,
        "corpus_version": compute_corpus_version(items, SPAN_SCHEME),
        "items": items,
    }


def with_all_public_approved(manifest: dict[str, Any]) -> dict[str, Any]:
    """A temporary manifest approving every public-plane, bound item (tests and calibration only, never committed)."""
    approved = copy.deepcopy(manifest)
    for item in approved.get("items", []):
        if item.get("plane") == "public" and item.get("bound", True):
            item["public_service"] = True
    approved["manifest_status"] = "temporary_all_public_approved_never_commit"
    # Approval changes the built membership, so the recorded corpus_version changes with it (plan 11.1).
    approved["corpus_version"] = compute_corpus_version(approved.get("items", []), str(approved.get("span_scheme") or "span-v2"))
    return approved


def dumps_manifest(manifest: dict[str, Any]) -> str:
    return json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"


def repository_root() -> Path:
    """The repository checkout this module runs from (scripts only; the image has no repository)."""
    parents = Path(__file__).resolve().parents
    return parents[4] if len(parents) > 4 else parents[-1]
