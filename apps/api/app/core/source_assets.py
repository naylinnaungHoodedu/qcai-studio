from collections import Counter
from pathlib import Path

from app.core.config import SOURCE_DOCUMENT_NAMES, SOURCE_VIDEO_NAMES


def legacy_source_asset_id(filename: str) -> str:
    return Path(filename).stem.lower().replace(" ", "-")


def source_asset_kind(filename: str) -> str:
    return "video" if Path(filename).suffix.lower() == ".mp4" else "document"


_DUPLICATE_LEGACY_IDS = Counter(
    legacy_source_asset_id(name) for name in [*SOURCE_DOCUMENT_NAMES, *SOURCE_VIDEO_NAMES]
)


def source_asset_id(filename: str, kind: str | None = None) -> str:
    resolved_kind = kind or source_asset_kind(filename)
    asset_id = legacy_source_asset_id(filename)
    if _DUPLICATE_LEGACY_IDS[asset_id] > 1:
        return f"{asset_id}-{resolved_kind}"
    return asset_id


def source_asset_lookup_ids(filename: str, kind: str | None = None) -> list[str]:
    resolved_kind = kind or source_asset_kind(filename)
    canonical = source_asset_id(filename, resolved_kind)
    legacy = legacy_source_asset_id(filename)
    return [canonical] if canonical == legacy else [canonical, legacy]
