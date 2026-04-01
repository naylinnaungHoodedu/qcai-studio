from collections import Counter
from pathlib import Path
import re

from app.core.config import SOURCE_DOCUMENT_NAMES, SOURCE_VIDEO_NAMES


def legacy_source_asset_id(filename: str) -> str:
    return Path(filename).stem.lower().replace(" ", "-")


def canonical_source_asset_stem(filename: str) -> str:
    legacy_id = legacy_source_asset_id(filename)
    sanitized = re.sub(r"[^a-z0-9_-]+", "-", legacy_id).strip("-")
    sanitized = re.sub(r"-{2,}", "-", sanitized)
    return sanitized


def source_asset_kind(filename: str) -> str:
    return "video" if Path(filename).suffix.lower() == ".mp4" else "document"


_DUPLICATE_CANONICAL_IDS = Counter(
    canonical_source_asset_stem(name) for name in [*SOURCE_DOCUMENT_NAMES, *SOURCE_VIDEO_NAMES]
)


def source_asset_id(filename: str, kind: str | None = None) -> str:
    resolved_kind = kind or source_asset_kind(filename)
    asset_id = canonical_source_asset_stem(filename)
    if _DUPLICATE_CANONICAL_IDS[asset_id] > 1:
        return f"{asset_id}-{resolved_kind}"
    return asset_id


def source_asset_lookup_ids(filename: str, kind: str | None = None) -> list[str]:
    resolved_kind = kind or source_asset_kind(filename)
    canonical = source_asset_id(filename, resolved_kind)
    legacy = legacy_source_asset_id(filename)
    if canonical == legacy:
        return [canonical]
    return [canonical, legacy]
