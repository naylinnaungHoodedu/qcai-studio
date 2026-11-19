"""Corpus licensing and public-serving policy for the CS595 evaluation boundary.

The runtime never infers a license from a filename.  In non-development deployments,
every served source asset must be explicitly declared public in the reviewed manifest.
Private evaluation material is deliberately not represented as a public runtime asset.

The served catalogue is the manifest (plan task 1.8; Decision P1-D-07, D-31): a governed build serves exactly
the approved assets, possibly none, and nothing derived from an unapproved one. A missing or invalid manifest
still stops start-up. Each approved item also needs a reviewed row in corpus/license-register.csv, which
scripts/validate_corpus.py --check-public-assets enforces in CI and before packaging.

Phase 2 (task 2.1): the manifest is generated from disk (scripts/generate_manifest.py, schema 2.0) with per-item
sha256, plane and binding; schema 1.0 stays readable for one release (dual-read). A private-plane item is never
served or indexed whatever its public_service, and an unbound item (Q-10) is never bound to a lesson, and never
served by a governed build, even if it is approved. Span item ids are always source_asset_id(filename, kind) or
"authored-curriculum", never a free-form manifest id.
"""

from __future__ import annotations

import csv
import json
import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status

from app.core.config import Settings
from app.core.config_package import ConfigPackage, canonical_sha256, get_config_package
from app.core.source_assets import source_asset_id, source_asset_kind

SUPPORTED_SCHEMAS = ("1.0", "2.0")
ITEM_KINDS = ("document", "video", "authored")
PLANES = ("public", "private")
AUTHORED_ITEM_ID = "authored-curriculum"


class CorpusGovernanceError(RuntimeError):
    """Raised when a production corpus has not passed the public-serving gate."""


@dataclass(frozen=True)
class CorpusItem:
    item_id: str
    version: str
    source: str
    license: str
    permitted_use: str
    public_service: bool
    asset_filenames: tuple[str, ...]
    # Schema 2.0 fields; a 1.0 item gets these defaults (its kind from its first file).
    kind: str = "document"
    plane: str = "public"
    sha256: str = ""
    size_bytes: int = 0
    hash_basis: str = ""
    asset_paths: tuple[str, ...] = ()
    bound: bool = True
    unbound_reason: str | None = None
    storage: str = ""
    spans_count: int | None = None
    spans_set_sha256: str | None = None
    media_duration_s: float | None = None


@dataclass(frozen=True)
class DriftReport:
    mode: str
    checked: int
    absent: int
    drifted: tuple[tuple[str, str], ...]
    basis: dict = field(default_factory=dict)

    @property
    def drift_count(self) -> int:
        return len(self.drifted)


def _hex64(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(ch in "0123456789abcdef" for ch in value)


def compute_corpus_version_v2(built_items: Iterable[CorpusItem], span_scheme: str = "span-v2") -> str:
    """corpus_version of a manifest 2.0 build: (item_id, item_version, sha256) of the built items (plan 11.1).

    The caller passes the built items (CorpusRegistry.built_items), so partial approval changes the version and a
    licence edit does not. The formula is app.core.manifest_v2.corpus_version_of, which the generator also uses.
    """
    from app.core.manifest_v2 import corpus_version_of

    return corpus_version_of([[item.item_id, item.version, item.sha256] for item in built_items], span_scheme)


def _candidate_manifest_paths(settings: Settings) -> list[Path]:
    if settings.corpus_manifest_path:
        explicit = Path(settings.corpus_manifest_path)
        return [explicit if explicit.is_absolute() else (Path.cwd() / explicit).resolve()]

    config_path = Path(__file__).resolve()
    relative = Path("corpus") / "public" / "manifest.json"
    candidates = [
        (Path.cwd() / relative).resolve(),
        (settings.project_root.parent / relative).resolve(),
    ]
    # Local development: .../apps/api/app/core -> repository root is parents[4].
    if len(config_path.parents) > 4:
        candidates.append((config_path.parents[4] / relative).resolve())
    # Container development: app source is copied to /app/app and the manifest to /app/corpus.
    candidates.append((config_path.parents[2] / relative).resolve())
    return list(dict.fromkeys(candidates))


class CorpusRegistry:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.schema_version: str | None = None
        self.recorded_corpus_version: str | None = None
        self.span_scheme = "span-v2"
        self.manifest_path = next((path for path in _candidate_manifest_paths(settings) if path.exists()), None)
        self.items = self._load_items()

    def _load_items(self) -> tuple[CorpusItem, ...]:
        if self.manifest_path is None:
            if self.settings.enforce_corpus_governance:
                raise CorpusGovernanceError("No reviewed public corpus manifest is available.")
            return ()
        try:
            payload: Any = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CorpusGovernanceError(f"Could not load corpus manifest: {exc}") from exc
        if not isinstance(payload, dict) or payload.get("schema_version") not in SUPPORTED_SCHEMAS:
            raise CorpusGovernanceError("Corpus manifest must declare schema_version 1.0 or 2.0.")
        self.schema_version = payload["schema_version"]
        raw_items = payload.get("items", [])
        if not isinstance(raw_items, list):
            raise CorpusGovernanceError("Corpus manifest items must be an array.")
        if self.schema_version == "2.0":
            return self._load_v2(payload, raw_items)

        parsed: list[CorpusItem] = []
        for index, raw in enumerate(raw_items):
            if not isinstance(raw, dict):
                raise CorpusGovernanceError(f"Corpus manifest item {index} is invalid.")
            filenames = raw.get("asset_filenames", [])
            required = ("id", "version", "source", "license", "permitted_use", "public_service")
            if any(not isinstance(raw.get(field), (str, bool)) or raw.get(field) in {"", None} for field in required):
                raise CorpusGovernanceError(f"Corpus manifest item {index} is incomplete.")
            if not isinstance(raw["public_service"], bool) or not isinstance(filenames, list) or not all(
                isinstance(name, str) and name for name in filenames
            ):
                raise CorpusGovernanceError(f"Corpus manifest item {index} has invalid access metadata.")
            parsed.append(
                CorpusItem(
                    item_id=str(raw["id"]),
                    version=str(raw["version"]),
                    source=str(raw["source"]),
                    license=str(raw["license"]),
                    permitted_use=str(raw["permitted_use"]),
                    public_service=raw["public_service"],
                    asset_filenames=tuple(filenames),
                    kind=source_asset_kind(filenames[0]) if filenames else "document",
                )
            )
        return tuple(parsed)

    def _load_v2(self, payload: dict, raw_items: list) -> tuple[CorpusItem, ...]:
        def fail(index: int, problem: str) -> CorpusGovernanceError:
            return CorpusGovernanceError(f"Corpus manifest item {index} {problem}.")

        parsed: list[CorpusItem] = []
        seen_ids: set[str] = set()
        seen_files: set[str] = set()
        for index, raw in enumerate(raw_items):
            if not isinstance(raw, dict):
                raise fail(index, "is invalid")
            item_id, kind, plane = raw.get("id"), raw.get("kind"), raw.get("plane")
            if not isinstance(item_id, str) or not item_id:
                raise fail(index, "has no id")
            if item_id in seen_ids:
                raise fail(index, f"repeats the id {item_id}")
            seen_ids.add(item_id)
            if kind not in ITEM_KINDS or plane not in PLANES:
                raise fail(index, "has an unknown kind or plane")
            filenames = raw.get("asset_filenames", [])
            if not isinstance(filenames, list) or not all(isinstance(name, str) and name for name in filenames):
                raise fail(index, "has invalid asset_filenames")
            for name in filenames:
                if name in seen_files:
                    raise fail(index, f"lists {name}, which another item already lists")
                seen_files.add(name)
            if kind == "authored":
                if item_id != AUTHORED_ITEM_ID or filenames:
                    raise fail(index, f"must be the single {AUTHORED_ITEM_ID} item with no files")
            elif not filenames or item_id != source_asset_id(filenames[0], kind):
                # Span item ids come from source_asset_id, so a free-form id could diverge from them ([R9]).
                raise fail(index, "must have id == source_asset_id(asset_filenames[0], kind)")
            sha256, version = raw.get("sha256"), raw.get("version")
            if not _hex64(sha256) or version != f"sha256:{sha256[:16]}":
                raise fail(index, "needs a sha256 of 64 hex characters and version sha256:<first 16>")
            size = raw.get("size_bytes")
            if not isinstance(size, int) or isinstance(size, bool) or size < 0:
                raise fail(index, "needs size_bytes, an integer >= 0")
            bound, reason = raw.get("bound"), raw.get("unbound_reason")
            if not isinstance(bound, bool) or (not bound) != bool(isinstance(reason, str) and reason.strip()):
                raise fail(index, "needs bound (a boolean) and an unbound_reason exactly when unbound")
            for name in ("source", "license", "permitted_use"):
                if not isinstance(raw.get(name), str) or not raw[name].strip():
                    raise fail(index, f"needs a non-empty {name}")
            if not isinstance(raw.get("public_service"), bool):
                raise fail(index, "needs public_service, a boolean")
            spans = raw.get("spans") if isinstance(raw.get("spans"), dict) else {}
            media = raw.get("media") if isinstance(raw.get("media"), dict) else {}
            parsed.append(
                CorpusItem(
                    item_id=item_id,
                    version=version,
                    source=raw["source"],
                    license=raw["license"],
                    permitted_use=raw["permitted_use"],
                    public_service=raw["public_service"],
                    asset_filenames=tuple(filenames),
                    kind=kind,
                    plane=plane,
                    sha256=sha256,
                    size_bytes=size,
                    hash_basis=str(raw.get("hash_basis") or ""),
                    asset_paths=tuple(raw.get("asset_paths") or ()),
                    bound=bound,
                    unbound_reason=reason if not bound else None,
                    storage=str(raw.get("storage") or ""),
                    spans_count=spans.get("count"),
                    spans_set_sha256=spans.get("set_sha256"),
                    media_duration_s=media.get("duration_s"),
                )
            )
        if sum(1 for item in parsed if item.kind == "authored") != 1:
            raise CorpusGovernanceError("Corpus manifest 2.0 must hold exactly one authored item.")
        self.span_scheme = str(payload.get("span_scheme") or "span-v2")
        self.recorded_corpus_version = payload.get("corpus_version")
        # The manifest records the governed value: the authored item plus the approved items (plan 11.1).
        computed = compute_corpus_version_v2(self._built(parsed, governed=True), self.span_scheme)
        if self.recorded_corpus_version != computed:
            raise CorpusGovernanceError(
                f"Corpus manifest corpus_version {self.recorded_corpus_version} does not match its items ({computed})."
            )
        return tuple(parsed)

    def _built(self, items: Iterable[CorpusItem], *, governed: bool) -> list[CorpusItem]:
        """Plan 11.1 "built items": public-plane, bound items the build admits. A governed build admits the authored
        item and the approved items (D-31); development admits every public-plane, bound item."""
        return [
            item
            for item in items
            if item.plane == "public" and self._item_bound(item) and (item.kind == "authored" or item.public_service or not governed)
        ]

    @property
    def built_items(self) -> tuple[CorpusItem, ...]:
        return tuple(self._built(self.items, governed=bool(self.settings.enforce_corpus_governance)))

    @property
    def corpus_version(self) -> str:
        """The corpus this deployment builds (plan 11.1): content and membership, partial approval included.

        A governed build reports the value the manifest records; development, which builds every public-plane,
        bound item, reports its own (different) value. Licence fields never change it.
        """
        if self.manifest_path is None:
            return "development-unreviewed"
        if self.schema_version == "2.0":
            return compute_corpus_version_v2(self.built_items, self.span_scheme)
        manifest_hash = hashlib.sha256(self.manifest_path.read_bytes()).hexdigest()[:16]
        return f"manifest:{manifest_hash}"

    @property
    def package(self) -> ConfigPackage:
        return get_config_package(self.settings)

    @cached_property
    def manifest_sha256(self) -> str | None:
        """The sha256 of the manifest's canonical JSON (a CRLF checkout hashes the same), or None without one.

        Stamped on every tutor ledger record (Phase 3 spec 7.6; plan 13.5 "corpus manifest hash")."""
        if self.manifest_path is None:
            return None
        return canonical_sha256(json.loads(self.manifest_path.read_text(encoding="utf-8")))

    def _item_bound(self, item: CorpusItem) -> bool:
        package = self.package
        return (
            item.bound
            and item.item_id not in package.q10_unbound_item_ids
            and not (set(item.asset_filenames) & package.q10_unbound_filenames)
        )

    @property
    def approved_items(self) -> tuple[CorpusItem, ...]:
        # Approved = public_service on a public-plane, bound item: a private-plane item is never served or indexed
        # whatever its public_service, and an unbound one waits on Q-10 (tasks 2.8 and 2.9).
        return tuple(item for item in self.items if item.public_service and item.plane == "public" and self._item_bound(item))

    @property
    def authored_item(self) -> CorpusItem | None:
        return next((item for item in self.items if item.kind == "authored"), None)

    def item_for_filename(self, filename: str) -> CorpusItem | None:
        return next((item for item in self.items if filename in item.asset_filenames), None)

    @staticmethod
    def span_item_id(filename: str) -> str:
        # Always the canonical asset id, never a free-form 1.0 manifest id ([R9]).
        return source_asset_id(filename, source_asset_kind(filename))

    def is_private_item(self, item_id: str) -> bool:
        """True when the manifest puts this span item id on a non-public plane (task 2.8: no API path to it)."""
        return any(
            item.plane != "public" and (item.item_id == item_id or any(self.span_item_id(name) == item_id for name in item.asset_filenames))
            for item in self.items
        )

    def is_private_plane(self, filename: str) -> bool:
        item = self.item_for_filename(filename)
        return item is not None and item.plane != "public"

    def is_bound(self, filename: str) -> bool:
        package = self.package
        if filename in package.q10_unbound_filenames or self.span_item_id(filename) in package.q10_unbound_item_ids:
            return False
        item = self.item_for_filename(filename)
        return item is None or self._item_bound(item)

    def is_public_asset(self, filename: str) -> bool:
        if self.is_private_plane(filename):
            return False
        if not self.settings.enforce_corpus_governance:
            return True
        return any(filename in item.asset_filenames for item in self.approved_items)

    def is_indexable(self, filename: str) -> bool:
        """May this file feed lessons, the index and quotations: public, bound and on the public plane."""
        return self.is_public_asset(filename) and self.is_bound(filename) and not self.is_private_plane(filename)

    def is_servable_item(self, item_id: str) -> bool:
        """An approved document or video item, by canonical span item id; the authored item never is."""
        return any(
            item.kind in {"document", "video"}
            and (item.item_id == item_id or any(self.span_item_id(name) == item_id for name in item.asset_filenames))
            for item in self.approved_items
        )

    def served(self, paths: Iterable[Path]) -> list[Path]:
        """The catalogue: the given source files this deployment may serve or derive content from."""
        return [path for path in paths if self.is_public_asset(path.name)]

    def drift_report(self, root: Path, mode: str, *, settings: Settings) -> DriftReport:
        """Compare manifest 2.0 hashes with the files present (D11). Absent files are counted, never drift."""
        from app.core.manifest_v2 import file_sha256_and_size, read_lfs_pointer

        if mode == "off" or self.schema_version != "2.0":
            return DriftReport(mode=mode, checked=0, absent=0, drifted=())
        resolver = settings.model_copy(update={"source_assets_root": str(root)})
        checked = absent = 0
        drifted: list[tuple[str, str]] = []
        basis: dict[str, str] = {}
        for item in self.items:
            if item.kind == "authored":
                from app.services.content_assembler import MODULE_BLUEPRINTS
                from app.services.spans import authored_sha256

                checked += 1
                basis[item.item_id] = "canonical-json-authored-v1"
                if authored_sha256(MODULE_BLUEPRINTS) != item.sha256:
                    drifted.append((item.item_id, "the authored curriculum differs from the manifest (regenerate it)"))
                continue
            paths = resolver._resolve_source_assets(list(item.asset_filenames[:1]))
            if not paths:
                absent += 1
                continue
            path = paths[0]
            checked += 1
            pointer = read_lfs_pointer(path)
            if pointer is not None:
                basis[item.item_id] = "lfs-pointer"
                if (pointer["oid"], pointer["size"]) != (item.sha256, item.size_bytes):
                    drifted.append((item.item_id, "LFS pointer oid or size differs"))
                continue
            if item.kind == "video" and mode == "fast":
                basis[item.item_id] = "size"
                if path.stat().st_size != item.size_bytes:
                    drifted.append((item.item_id, "size differs"))
                continue
            basis[item.item_id] = "content"
            sha, size, _ = file_sha256_and_size(path)
            if (sha, size) != (item.sha256, item.size_bytes):
                drifted.append((item.item_id, "content sha256 or size differs"))
        return DriftReport(mode=mode, checked=checked, absent=absent, drifted=tuple(drifted), basis=basis)

    def assert_ready_to_serve(self) -> None:
        # Loading already failed closed on a missing or invalid manifest; an empty one serves nothing (D-31).
        if self.settings.enforce_corpus_governance and self.manifest_path is None:
            raise CorpusGovernanceError("No reviewed public corpus manifest is available.")

    def require_public_asset(self, filename: str) -> None:
        if self.is_public_asset(filename):
            return
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source asset is not approved for public service.")

    def assert_public_assets_ready(self, filenames: list[str]) -> None:
        if not self.settings.enforce_corpus_governance:
            return
        if self.manifest_path is None:
            raise CorpusGovernanceError("No reviewed public corpus manifest is available.")
        unapproved = sorted({filename for filename in filenames if not self.is_public_asset(filename)})
        if unapproved:
            raise CorpusGovernanceError(
                "Public corpus contains unapproved assets: " + ", ".join(unapproved[:3]) + ("..." if len(unapproved) > 3 else "")
            )


def get_corpus_registry(settings: Settings) -> CorpusRegistry:
    return CorpusRegistry(settings)


def p1_floor_recall_stop(registry: CorpusRegistry, settings: Settings) -> list[str]:
    """Phase 2 spec conflict 29, enforced in code (plan Phase 2 L: "stop if ... recall@5 falls below baseline").

    Over the span index, which no longer holds video chapter summaries (task 2.7), the approved P1 floor lowers
    in-domain recall@5 as soon as document spans are indexed: against the same index unfloored (the Action 27
    "recall drops" stop) and, with every public item approved, below the pre-migration baseline (118 against 129).
    Returns the document items whose indexing triggers the stop under the p1-floor gate outside development, or
    an empty list when it does not apply. Under D-31 no document is approved, so it is empty today.
    """
    if settings.retrieval_gate != "p1-floor" or settings.environment.lower() == "development":
        return []
    if settings.enforce_corpus_governance:
        return sorted(item.item_id for item in registry.approved_items if item.kind == "document")
    return sorted({registry.span_item_id(path.name) for path in settings.source_documents if registry.is_indexable(path.name)})


REGISTER_REVIEW_FIELDS = ("library_confirmation", "reviewed_by", "reviewed_at")


def load_license_register(path: Path) -> list[dict[str, str]]:
    """Rows of corpus/license-register.csv; `asset_filenames` lists files separated by ";"."""
    with path.open(encoding="utf-8", newline="") as handle:
        return [{key: (value or "").strip() for key, value in row.items() if key} for row in csv.DictReader(handle)]


def review_problems(registry: CorpusRegistry, register: list[dict[str, str]], known_filenames: Iterable[str]) -> list[str]:
    """Why the approved catalogue is not ready to serve; empty when every approved item is reviewed (AC-1-5)."""
    known = set(known_filenames)
    problems: list[str] = []
    for item in registry.items:
        # Never served whatever public_service says, so the approval itself is a mistake to fix ([R15]).
        if item.public_service and item.plane != "public":
            problems.append(f"{item.item_id}: private-plane item must not be approved for public service")
        elif item.public_service and not registry._item_bound(item):
            problems.append(f"{item.item_id}: unbound item must not be approved for public service (Q-10)")
    for item in registry.approved_items:
        rows = [row for row in register if row.get("item_id") == item.item_id and row.get("version") == item.version]
        if len(rows) != 1:
            problems.append(f"{item.item_id} {item.version}: needs exactly one license-register row, found {len(rows)}")
            continue
        row = rows[0]
        missing = [field for field in REGISTER_REVIEW_FIELDS if not row.get(field)]
        if missing:
            problems.append(f"{item.item_id}: register row is not reviewed ({', '.join(missing)} empty)")
        if row.get("public_service", "").lower() != "true":
            problems.append(f"{item.item_id}: register row does not approve public service")
        for field_name, value in (("license", item.license), ("permitted_use", item.permitted_use)):
            if row.get(field_name) != value:
                problems.append(f"{item.item_id}: register {field_name} differs from the manifest")
        registered = {name.strip() for name in row.get("asset_filenames", "").split(";") if name.strip()}
        for filename in item.asset_filenames:
            if filename not in registered:
                problems.append(f"{item.item_id}: {filename} is approved in the manifest but not in its register row")
            if filename not in known:
                problems.append(f"{item.item_id}: {filename} is not a source asset this application serves")
    return problems
