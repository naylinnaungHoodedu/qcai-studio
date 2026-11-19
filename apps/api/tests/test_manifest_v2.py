"""Manifest v2 parsing, hashing and drift (plan Phase 2 task 2.1; spec 2.1, 3.4, 3.11, 3.12)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import struct

import pytest

from app.core.config import Settings
from app.core.corpus_governance import CorpusGovernanceError, CorpusRegistry
from app.core.manifest_v2 import (
    compute_corpus_version,
    file_sha256_and_size,
    lfs_tracked,
    mp4_duration_seconds,
    read_lfs_pointer,
    with_all_public_approved,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST = json.loads((REPO_ROOT / "corpus" / "public" / "manifest.json").read_text(encoding="utf-8"))
DOCUMENT = "Module2_Routing, Graph Shrinking, and Logistics under Hardware Constraints.docx"
VIDEO_2026 = "Quantum Computing and Artificial Intelligence 2026.mp4"


def write(tmp_path: Path, payload: dict, *, recompute: bool = True) -> Settings:
    if recompute:
        payload["corpus_version"] = compute_corpus_version(payload["items"])
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return Settings(environment="production", enforce_corpus_governance=True, corpus_manifest_path=str(path))


def item(payload: dict, filename: str) -> dict:
    return next(entry for entry in payload["items"] if filename in entry["asset_filenames"])


def test_the_committed_manifest_is_schema_2_with_25_items_and_nothing_approved():
    registry = CorpusRegistry(Settings(environment="production", enforce_corpus_governance=True))
    assert registry.schema_version == "2.0" and len(registry.items) == 25
    assert registry.approved_items == () and registry.corpus_version == MANIFEST["corpus_version"]
    assert sum(1 for entry in registry.items if entry.kind == "authored") == 1
    unbound = [entry for entry in registry.items if not entry.bound]
    assert [entry.asset_filenames for entry in unbound] == [(VIDEO_2026,)]
    assert "Q-10 unresolved" in unbound[0].unbound_reason


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (lambda p: item(p, DOCUMENT).update(id="free-form-id"), "source_asset_id"),
        (lambda p: item(p, DOCUMENT).update(version="sha256:0000000000000000"), "version sha256"),
        (lambda p: item(p, DOCUMENT).update(sha256="xyz"), "64 hex"),
        (lambda p: item(p, DOCUMENT).update(bound=False), "unbound_reason"),
        (lambda p: item(p, VIDEO_2026).update(unbound_reason=None), "unbound_reason"),
        (lambda p: item(p, DOCUMENT).update(plane="secret"), "kind or plane"),
        (lambda p: item(p, DOCUMENT).update(size_bytes=-1), "size_bytes"),
        (lambda p: item(p, DOCUMENT).update(license=""), "license"),
        (lambda p: p["items"].append(copy.deepcopy(item(p, DOCUMENT))), "repeats the id"),
        (lambda p: p["items"].remove(next(e for e in p["items"] if e["kind"] == "authored")), "exactly one authored"),
    ],
)
def test_manifest_2_0_validation_fails_closed(tmp_path, edit, message):
    payload = copy.deepcopy(MANIFEST)
    edit(payload)
    with pytest.raises(CorpusGovernanceError, match=message):
        CorpusRegistry(write(tmp_path, payload))


def test_a_recorded_corpus_version_that_does_not_match_the_items_fails(tmp_path):
    payload = copy.deepcopy(MANIFEST)
    item(payload, DOCUMENT)["public_service"] = True  # approval changes the built membership, so corpus_version must change
    with pytest.raises(CorpusGovernanceError, match="does not match its items"):
        CorpusRegistry(write(tmp_path, payload, recompute=False))


def test_corpus_version_hashes_built_items_so_approval_counts_and_licence_edits_do_not():
    # Plan 11.1: "corpus_version MUST hash the sorted (item_id, item_version, sha256) of built items plus the
    # span-scheme version, so any content or membership change, including partial approval, yields a new version;
    # membership-neutral licence edits do not."
    licence = copy.deepcopy(MANIFEST)
    for entry in licence["items"]:
        entry["source"], entry["license"], entry["permitted_use"] = "edited", "edited", "edited"
    assert compute_corpus_version(licence["items"]) == MANIFEST["corpus_version"]
    approved = copy.deepcopy(MANIFEST)
    item(approved, DOCUMENT)["public_service"] = True  # partial approval
    assert compute_corpus_version(approved["items"]) != MANIFEST["corpus_version"]
    # Content: a built item's change moves it; an unapproved document is not built in a governed build.
    authored = copy.deepcopy(MANIFEST)
    next(entry for entry in authored["items"] if entry["kind"] == "authored")["sha256"] = "1" * 64
    assert compute_corpus_version(authored["items"]) != MANIFEST["corpus_version"]
    content = copy.deepcopy(MANIFEST)
    item(content, DOCUMENT)["version"] = "sha256:" + "1" * 16
    assert compute_corpus_version(content["items"]) == MANIFEST["corpus_version"]
    assert compute_corpus_version(content["items"], governed=False) != compute_corpus_version(MANIFEST["items"], governed=False)
    approved_content = copy.deepcopy(approved)
    item(approved_content, DOCUMENT)["version"] = "sha256:" + "1" * 16
    assert compute_corpus_version(approved_content["items"]) != compute_corpus_version(approved["items"])
    # Private-plane and unbound items are never built, approved or not.
    hidden = copy.deepcopy(MANIFEST)
    item(hidden, DOCUMENT).update(plane="private", public_service=True)
    item(hidden, VIDEO_2026)["public_service"] = True
    assert compute_corpus_version(hidden["items"]) == MANIFEST["corpus_version"]


def test_approved_items_exclude_private_and_unbound_items(tmp_path):
    payload = with_all_public_approved(copy.deepcopy(MANIFEST))
    item(payload, VIDEO_2026)["public_service"] = True
    item(payload, DOCUMENT)["plane"] = "private"
    item(payload, DOCUMENT)["public_service"] = True
    registry = CorpusRegistry(write(tmp_path, payload))
    approved = {name for entry in registry.approved_items for name in entry.asset_filenames}
    assert VIDEO_2026 not in approved and DOCUMENT not in approved
    assert len(approved) == 22
    assert registry.is_servable_item("authored-curriculum") is False


def _mp4(version: int, timescale: int, duration: int, *, large_ftyp: bool = False) -> bytes:
    if version == 1:
        mvhd_body = bytes([1, 0, 0, 0]) + b"\0" * 16 + struct.pack(">IQ", timescale, duration) + b"\0" * 80
    else:
        mvhd_body = bytes([0, 0, 0, 0]) + b"\0" * 8 + struct.pack(">II", timescale, duration) + b"\0" * 80
    mvhd = struct.pack(">I4s", 8 + len(mvhd_body), b"mvhd") + mvhd_body
    moov = struct.pack(">I4s", 8 + len(mvhd), b"moov") + mvhd
    ftyp_body = b"isom\0\0\0\0isomiso2"
    ftyp = (struct.pack(">I4sQ", 1, b"ftyp", 16 + len(ftyp_body)) if large_ftyp else struct.pack(">I4s", 8 + len(ftyp_body), b"ftyp")) + ftyp_body
    return ftyp + struct.pack(">I4s", 16, b"free") + b"\0" * 8 + moov


def test_mp4_mvhd_durations_for_version_0_and_1(tmp_path):
    v0 = tmp_path / "v0.mp4"
    v0.write_bytes(_mp4(0, 1000, 575176))
    v1 = tmp_path / "v1.mp4"
    v1.write_bytes(_mp4(1, 90000, 90000 * 600 + 4500, large_ftyp=True))
    assert mp4_duration_seconds(v0) == 575.176
    assert mp4_duration_seconds(v1) == 600.05
    broken = tmp_path / "broken.mp4"
    broken.write_bytes(b"not a movie at all")
    assert mp4_duration_seconds(broken) is None


def test_lfs_pointers_hash_as_their_oid(tmp_path):
    oid = "ab" * 32
    pointer = tmp_path / "video.mp4"
    pointer.write_text(f"version https://git-lfs.github.com/spec/v1\noid sha256:{oid}\nsize 1234\n", encoding="utf-8", newline="\n")
    assert read_lfs_pointer(pointer) == {"oid": oid, "size": 1234}
    assert file_sha256_and_size(pointer) == (oid, 1234, "lfs-pointer")
    assert mp4_duration_seconds(pointer) is None
    content = tmp_path / "real.mp4"
    content.write_bytes(b"x" * 2048)
    assert read_lfs_pointer(content) is None
    assert file_sha256_and_size(content, video_hash="size") == (None, 2048, "size-only")
    assert file_sha256_and_size(content)[2] == "content"
    assert lfs_tracked("update_data/a.mp4", REPO_ROOT) and not lfs_tracked("a.docx", REPO_ROOT)


def test_the_drift_report_counts_absent_files_and_flags_changed_ones(tmp_path):
    root = tmp_path / "root"
    (root / "update_data").mkdir(parents=True)
    source = REPO_ROOT / item(MANIFEST, DOCUMENT)["asset_paths"][0]
    (root / item(MANIFEST, DOCUMENT)["asset_paths"][0]).write_bytes(source.read_bytes())
    video = item(MANIFEST, VIDEO_2026)
    (root / video["asset_paths"][0]).write_text(
        f"version https://git-lfs.github.com/spec/v1\noid sha256:{video['sha256']}\nsize {video['size_bytes']}\n", encoding="utf-8", newline="\n"
    )
    settings = Settings(environment="production", enforce_corpus_governance=True)
    registry = CorpusRegistry(settings)
    report = registry.drift_report(root, "fast", settings=settings)
    assert (report.checked, report.absent, report.drifted) == (3, 22, ())  # the document, the pointer, the authored item
    assert report.basis[video["id"]] == "lfs-pointer"
    assert registry.drift_report(root, "off", settings=settings).checked == 0
    target = root / item(MANIFEST, DOCUMENT)["asset_paths"][0]
    target.write_bytes(target.read_bytes() + b"\0")
    drifted = registry.drift_report(root, "fast", settings=settings).drifted
    assert [entry_id for entry_id, _ in drifted] == [item(MANIFEST, DOCUMENT)["id"]]
