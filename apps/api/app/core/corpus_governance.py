"""Corpus licensing and public-serving policy for the CS595 evaluation boundary.

The runtime never infers a license from a filename.  In non-development deployments,
every served source asset must be explicitly declared public in the reviewed manifest.
Private evaluation material is deliberately not represented as a public runtime asset.
"""

from __future__ import annotations

import json
import hashlib
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

    def is_public_asset(self, filename: str) -> bool:
        if not self.settings.enforce_corpus_governance:
            return True
        return any(item.public_service and filename in item.asset_filenames for item in self.items)

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
