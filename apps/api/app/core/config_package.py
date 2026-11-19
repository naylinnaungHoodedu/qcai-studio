"""Configuration package v1 (plan Phase 2 P: "configuration package v1 published"; Phase 2 spec 2.5 and 4.2).

A versioned JSON file shipped in the API image (apps/api/app/config_package/v1.json) that freezes every Phase 2
value: the span-identity scheme, the BM25 parameters and stopword list, the provisional abstention floor and
margin, the near-duplicate thresholds, the D-30 legacy-citation rule, the provisional owner decisions (D-17, D-30,
Q-10) and the boundary policy. Next to it, v1.json.sha256 holds the sha256 of its canonical JSON, so a CRLF
checkout hashes the same.

Start-up loads and validates it before any database work. A structural error always stops start-up; a hash
mismatch stops a governed build and is a logged warning in development. The loader never opens the calibration
record, which is not in the image.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
import logging
from pathlib import Path
import threading
from typing import Any

from app.core.config import Settings
from app.core.structured_logging import FIELDS

LOGGER = logging.getLogger("qcai.config_package")
DEFAULT_PACKAGE_PATH = Path(__file__).resolve().parents[1] / "config_package" / "v1.json"
PACKAGE_NAME = "qcai-configuration-package"
SPAN_SCHEME = "span-v2"
P1_FLOOR_VERSION = "score-floor-p1-v1"
P1_FLOOR = 6


class ConfigPackageError(RuntimeError):
    """The configuration package is missing, malformed or (in a governed build) does not match its hash."""


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def stopwords_sha256(words: list[str] | tuple[str, ...]) -> str:
    return hashlib.sha256("\n".join(sorted(words)).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RetrievalParams:
    algorithm: str
    k1: float
    b: float
    title_weight: float
    min_token_length: int
    stemmer: str
    tokenizer_version: str
    stopwords: frozenset[str]
    stopwords_version: str
    stopwords_sha256: str
    coverage_rule: str


@dataclass(frozen=True)
class AbstentionParams:
    version: str
    floor: float
    margin: float
    provisional: bool
    provisional_until: str
    calibration_record: str
    calibration_record_sha256: str


@dataclass(frozen=True)
class NearDuplicateParams:
    shingle_words: int
    jaccard: float
    containment: float
    video_duration_tolerance_s: float
    video_size_ratio_tolerance: float
    chapter_shingle_words: int
    chapter_jaccard: float


@dataclass(frozen=True)
class BoundaryPolicy:
    private_plane_globs: tuple[str, ...]
    public_exceptions: tuple[str, ...]
    licensed_volume_globs: tuple[str, ...]
    secret_like_name_globs: tuple[str, ...]
    passage_shingle_words: int
    passage_min_hits: int


@dataclass(frozen=True)
class ConfigPackage:
    package_version: str
    sha256: str
    hash_verified: bool
    path: Path
    is_default_path: bool
    raw: Mapping[str, Any]
    span_scheme: str
    splitter: Mapping[str, Any]
    parser: Mapping[str, Any]
    retrieval: RetrievalParams
    retrieval_sha256: str
    p1_floor: Mapping[str, Any]
    abstention: AbstentionParams
    near_duplicate: NearDuplicateParams
    boundary: BoundaryPolicy
    legacy_citations: Mapping[str, Any]
    owner_decisions: Mapping[str, Any]
    q10_unbound_filenames: frozenset[str]
    q10_unbound_item_ids: frozenset[str]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ConfigPackageError(f"Configuration package: {message}")


def _mapping(raw: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = raw.get(key)
    _require(isinstance(value, dict), f"'{key}' must be an object")
    return value


def _number(raw: Mapping[str, Any], key: str, *, minimum: float | None = None, maximum: float | None = None) -> float:
    value = raw.get(key)
    _require(isinstance(value, (int, float)) and not isinstance(value, bool), f"'{key}' must be a number")
    if minimum is not None:
        _require(value >= minimum, f"'{key}' must be >= {minimum}")
    if maximum is not None:
        _require(value <= maximum, f"'{key}' must be <= {maximum}")
    return float(value)


def _integer(raw: Mapping[str, Any], key: str, *, minimum: int = 0) -> int:
    value = raw.get(key)
    _require(isinstance(value, int) and not isinstance(value, bool) and value >= minimum, f"'{key}' must be an integer >= {minimum}")
    return int(value)


def _text(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    _require(isinstance(value, str) and bool(value.strip()), f"'{key}' must be a non-empty string")
    return value


def _strings(raw: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = raw.get(key)
    _require(isinstance(value, list) and all(isinstance(item, str) and item for item in value), f"'{key}' must be a list of strings")
    return tuple(value)


def recorded_sha256(path: Path) -> str | None:
    sidecar = path.with_name(path.name + ".sha256")
    if not sidecar.exists():
        return None
    # Whitespace (and a CRLF line end from a Windows checkout) is not part of the hash.
    return sidecar.read_text(encoding="utf-8").strip() or None


def parse_config_package(raw: Any, *, path: Path, sha256: str, hash_verified: bool) -> ConfigPackage:
    _require(isinstance(raw, dict), "the file must hold a JSON object")
    _require(raw.get("package") == PACKAGE_NAME, f"'package' must be '{PACKAGE_NAME}'")
    _require(raw.get("schema_version") == 1, "'schema_version' must be 1")
    package_version = _text(raw, "package_version")

    identity = _mapping(raw, "span_identity")
    _require(identity.get("scheme") == SPAN_SCHEME, f"span_identity.scheme must be '{SPAN_SCHEME}'")
    _require(
        identity.get("id_inputs") == ["scheme", "item_id", "start", "end", "content_hash"],
        "span_identity.id_inputs must be [scheme, item_id, start, end, content_hash]",
    )
    splitter = _mapping(identity, "splitter")
    for key in ("library", "version", "class"):
        _text(splitter, key)
    _integer(splitter, "chunk_size", minimum=1)
    _integer(splitter, "chunk_overlap", minimum=0)
    parser = _mapping(identity, "parser")
    for key in ("library", "version", "function"):
        _text(parser, key)

    gates = _mapping(raw, "gates")
    p1 = _mapping(gates, "p1-floor")
    _require(p1.get("version") == P1_FLOOR_VERSION and p1.get("floor") == P1_FLOOR, "gates.p1-floor must be the approved P1-D-04 floor")

    retrieval_raw = _mapping(raw, "retrieval")
    tokenizer = _mapping(retrieval_raw, "tokenizer")
    stopwords = _mapping(retrieval_raw, "stopwords")
    words = _strings(stopwords, "words")
    _require(list(words) == sorted(set(words)), "retrieval.stopwords.words must be sorted and unique")
    _require(all(word == word.lower() for word in words), "retrieval.stopwords.words must be lowercase")
    _require(stopwords.get("sha256") == stopwords_sha256(words), "retrieval.stopwords.sha256 does not match the word list")
    _require(tokenizer.get("stemmer") == "none", "retrieval.tokenizer.stemmer must be 'none' in package v1")
    retrieval = RetrievalParams(
        algorithm=_text(retrieval_raw, "algorithm"),
        k1=_number(retrieval_raw, "k1", minimum=1e-9),
        b=_number(retrieval_raw, "b", minimum=0.0, maximum=1.0),
        title_weight=_number(retrieval_raw, "title_weight", minimum=0.0),
        min_token_length=_integer(tokenizer, "min_token_length", minimum=1),
        stemmer=_text(tokenizer, "stemmer"),
        tokenizer_version=_text(tokenizer, "version"),
        stopwords=frozenset(words),
        stopwords_version=_text(stopwords, "version"),
        stopwords_sha256=_text(stopwords, "sha256"),
        coverage_rule=_text(retrieval_raw, "coverage_rule"),
    )
    _require(retrieval.coverage_rule == "coverage-v1", "retrieval.coverage_rule must be 'coverage-v1'")

    abstention_raw = _mapping(raw, "abstention")
    _require(isinstance(abstention_raw.get("provisional"), bool), "abstention.provisional must be a boolean")
    abstention = AbstentionParams(
        version=_text(abstention_raw, "version"),
        floor=_number(abstention_raw, "floor", minimum=0.0),
        margin=_number(abstention_raw, "margin", minimum=0.0),
        provisional=abstention_raw["provisional"],
        provisional_until=_text(abstention_raw, "provisional_until"),
        calibration_record=_text(abstention_raw, "calibration_record"),
        calibration_record_sha256=_text(abstention_raw, "calibration_record_sha256"),
    )

    near_raw = _mapping(raw, "near_duplicate")
    near = NearDuplicateParams(
        shingle_words=_integer(near_raw, "document_shingle_words", minimum=1),
        jaccard=_number(near_raw, "document_jaccard_threshold", minimum=0.0, maximum=1.0),
        containment=_number(near_raw, "document_containment_threshold", minimum=0.0, maximum=1.0),
        video_duration_tolerance_s=_number(near_raw, "video_duration_tolerance_s", minimum=0.0),
        video_size_ratio_tolerance=_number(near_raw, "video_size_ratio_tolerance", minimum=0.0),
        chapter_shingle_words=_integer(near_raw, "chapter_shingle_words", minimum=1),
        chapter_jaccard=_number(near_raw, "chapter_jaccard_threshold", minimum=0.0, maximum=1.0),
    )

    boundary_raw = _mapping(raw, "boundary")
    boundary = BoundaryPolicy(
        private_plane_globs=_strings(boundary_raw, "private_plane_globs"),
        public_exceptions=_strings(boundary_raw, "public_exceptions"),
        licensed_volume_globs=_strings(boundary_raw, "licensed_volume_globs"),
        secret_like_name_globs=_strings(boundary_raw, "secret_like_name_globs"),
        passage_shingle_words=_integer(boundary_raw, "passage_shingle_words", minimum=1),
        passage_min_hits=_integer(boundary_raw, "passage_min_hits_per_file", minimum=1),
    )

    legacy = _mapping(raw, "legacy_citations")
    _text(legacy, "unresolved_label")
    _require(legacy.get("max_unresolved_share_native") == 0.0, "legacy_citations.max_unresolved_share_native must be 0.0")
    # D-30 (plan Phase 2 L): the legacy threshold is null while the decision is open, or a share the migration
    # enforces (citation_migration._threshold); the loader never accepts a value the migration would not apply.
    legacy_limit = legacy.get("max_unresolved_share_legacy")
    _require(
        legacy_limit is None
        or (isinstance(legacy_limit, (int, float)) and not isinstance(legacy_limit, bool) and 0.0 <= float(legacy_limit) <= 1.0),
        "legacy_citations.max_unresolved_share_legacy must be null or a number in [0, 1]",
    )
    _require(
        legacy.get("legacy_share_statistic") in {"point", "wilson95_upper"},
        "legacy_citations.legacy_share_statistic must be 'point' or 'wilson95_upper'",
    )
    decisions = _mapping(raw, "owner_decisions")
    q10 = _mapping(decisions, "Q-10")
    unbound = q10.get("unbound_items", [])
    _require(isinstance(unbound, list), "owner_decisions.Q-10.unbound_items must be a list")
    if q10.get("state") == "unresolved":
        _require(bool(unbound), "Q-10 is unresolved, so at least one item must stay unbound")
    for entry in unbound:
        _require(isinstance(entry, dict), "owner_decisions.Q-10.unbound_items entries must be objects")
        _text(entry, "item_id")
        _text(entry, "asset_filename")

    return ConfigPackage(
        package_version=package_version,
        sha256=sha256,
        hash_verified=hash_verified,
        path=path,
        is_default_path=path.resolve() == DEFAULT_PACKAGE_PATH.resolve(),
        raw=raw,
        span_scheme=identity["scheme"],
        splitter=splitter,
        parser=parser,
        retrieval=retrieval,
        retrieval_sha256=canonical_sha256(retrieval_raw),
        p1_floor=p1,
        abstention=abstention,
        near_duplicate=near,
        boundary=boundary,
        legacy_citations=legacy,
        owner_decisions=decisions,
        q10_unbound_filenames=frozenset(entry["asset_filename"] for entry in unbound),
        q10_unbound_item_ids=frozenset(entry["item_id"] for entry in unbound),
    )


def load_config_package(path: Path, *, governed: bool) -> ConfigPackage:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigPackageError(f"Could not load the configuration package at {path}: {exc}") from exc
    sha256 = canonical_sha256(raw)
    recorded = recorded_sha256(Path(path))
    hash_verified = recorded == sha256
    package = parse_config_package(raw, path=Path(path), sha256=sha256, hash_verified=hash_verified)
    if not hash_verified:
        if governed:
            raise ConfigPackageError(
                f"Configuration package {path} does not match its recorded sha256 (recorded {recorded}, computed {sha256})."
            )
        LOGGER.warning(
            "Configuration package hash does not match its sidecar; continuing in development",
            extra={FIELDS: {"event": "config_package.hash_mismatch", "path": str(path), "sha256": sha256}},
        )
    return package


def resolve_package_path(settings: Settings) -> Path:
    if settings.config_package_path:
        explicit = Path(settings.config_package_path)
        return explicit if explicit.is_absolute() else (Path.cwd() / explicit).resolve()
    return DEFAULT_PACKAGE_PATH


_CACHE: dict[tuple[str, bool], ConfigPackage] = {}
_LOCK = threading.Lock()


def get_config_package(settings: Settings | None = None) -> ConfigPackage:
    """The package for these settings, loaded once per resolved path and governance mode."""
    if settings is None:
        from app.core.config import get_settings

        settings = get_settings()
    path = resolve_package_path(settings)
    key = (str(path), bool(settings.enforce_corpus_governance))
    with _LOCK:
        cached = _CACHE.get(key)
        if cached is None:
            cached = load_config_package(path, governed=bool(settings.enforce_corpus_governance))
            _CACHE[key] = cached
        return cached


def clear_config_package_cache() -> None:
    with _LOCK:
        _CACHE.clear()
