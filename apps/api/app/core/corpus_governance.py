"""Corpus licensing and public-serving policy for the CS595 evaluation boundary.

The runtime never infers a license from a filename.  In non-development deployments,
every served source asset must be explicitly declared public in the reviewed manifest.
Private evaluation material is deliberately not represented as a public runtime asset.

The served catalogue is the manifest (plan task 1.8; Decision P1-D-07, D-31): a governed build serves exactly
the approved assets, possibly none, and nothing derived from an unapproved one. A missing or invalid manifest
still stops start-up. Each approved item also needs a reviewed row in corpus/license-register.csv, which
scripts/validate_corpus.py --check-public-assets enforces in CI and before packaging.
"""

from __future__ import annotations

import csv
import json
import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status

from app.core.config import Settings


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
        if not isinstance(payload, dict) or payload.get("schema_version") != "1.0":
            raise CorpusGovernanceError("Corpus manifest must declare schema_version 1.0.")
        raw_items = payload.get("items", [])
        if not isinstance(raw_items, list):
            raise CorpusGovernanceError("Corpus manifest items must be an array.")

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
                )
            )
        return tuple(parsed)

    @property
    def corpus_version(self) -> str:
        if self.manifest_path is None:
            return "development-unreviewed"
        manifest_hash = hashlib.sha256(self.manifest_path.read_bytes()).hexdigest()[:16]
        return f"manifest:{manifest_hash}"

    @property
    def approved_items(self) -> tuple[CorpusItem, ...]:
        return tuple(item for item in self.items if item.public_service)

    def is_public_asset(self, filename: str) -> bool:
        if not self.settings.enforce_corpus_governance:
            return True
        return any(filename in item.asset_filenames for item in self.approved_items)

    def served(self, paths: Iterable[Path]) -> list[Path]:
        """The catalogue: the given source files this deployment may serve or derive content from."""
        return [path for path in paths if self.is_public_asset(path.name)]

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


REGISTER_REVIEW_FIELDS = ("library_confirmation", "reviewed_by", "reviewed_at")


def load_license_register(path: Path) -> list[dict[str, str]]:
    """Rows of corpus/license-register.csv; `asset_filenames` lists files separated by ";"."""
    with path.open(encoding="utf-8", newline="") as handle:
        return [{key: (value or "").strip() for key, value in row.items() if key} for row in csv.DictReader(handle)]


def review_problems(registry: CorpusRegistry, register: list[dict[str, str]], known_filenames: Iterable[str]) -> list[str]:
    """Why the approved catalogue is not ready to serve; empty when every approved item is reviewed (AC-1-5)."""
    known = set(known_filenames)
    problems: list[str] = []
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
        for field, value in (("license", item.license), ("permitted_use", item.permitted_use)):
            if row.get(field) != value:
                problems.append(f"{item.item_id}: register {field} differs from the manifest")
        registered = {name.strip() for name in row.get("asset_filenames", "").split(";") if name.strip()}
        for filename in item.asset_filenames:
            if filename not in registered:
                problems.append(f"{item.item_id}: {filename} is approved in the manifest but not in its register row")
            if filename not in known:
                problems.append(f"{item.item_id}: {filename} is not a source asset this application serves")
    return problems
