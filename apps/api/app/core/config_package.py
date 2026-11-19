"""Configuration package (plan Phase 2 P: "configuration package v1 published"; Phase 3 P: "schemas in
configuration package v2"; Phase 2 spec 2.5 and 4.2; Phase 3 spec section 5).

A versioned JSON file shipped in the API image (apps/api/app/config_package/v2.json) that freezes every Phase 2
value: the span-identity scheme, the BM25 parameters and stopword list, the provisional abstention floor and
margin, the near-duplicate thresholds, the D-30 legacy-citation rule, the provisional owner decisions (D-17, D-30,
Q-10) and the boundary policy. Version 2 (Phase 3) copies every v1 block and adds the two-channel tutor: the
sha256 pins of the eight contract schemas (app/config_package/schemas/), the resolver, generator and renderer ids
and prompt hashes, the regeneration limit, the presentation plans, the bound-claim stop baseline and the
two_pass_tutor flag policy (phase4_exit_passed). Next to each file, <name>.json.sha256 holds the sha256 of its
canonical JSON, so a CRLF checkout hashes the same. v1.json stays readable for one release (DI-42).

Start-up loads and validates it before any database work. A structural error always stops start-up; a hash
mismatch stops a governed build and is a logged warning in development. The loader never opens the calibration
record, which is not in the image, nor the schema files (tutor_pipeline.package_check verifies those).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
import logging
from pathlib import Path
import re
import threading
from typing import Any

from app.core.config import Settings
from app.core.structured_logging import FIELDS

LOGGER = logging.getLogger("qcai.config_package")
PACKAGE_DIRECTORY = Path(__file__).resolve().parents[1] / "config_package"
DEFAULT_PACKAGE_PATH = PACKAGE_DIRECTORY / "v2.json"
# Readable for one release after the Phase 3 merge (DI-42); CI checks it with config_package.py --check --path.
V1_PACKAGE_PATH = PACKAGE_DIRECTORY / "v1.json"
PACKAGE_NAME = "qcai-configuration-package"
SPAN_SCHEME = "span-v2"
P1_FLOOR_VERSION = "score-floor-p1-v1"
P1_FLOOR = 6
# D-12 open: no provider generator is wired (hold H6, PD-09); the D-19 extractive generator is the interim path.
WIRED_GENERATORS = frozenset({"extractive-d19-v1"})
TUTOR_SCHEMA_NAMES = (
    "ResolvedQuestion",
    "RetrievalRequest",
    "EvidenceBundle",
    "EvidentialEnvelope",
    "ClaimPlan",
    "LockedClaimSet",
    "PresentationPlan",
    "LedgerEntry",
)
REQUIRED_PRESENTATION_PLANS = ("concise", "stepwise", "socratic")
RETRIEVAL_REQUEST_FIELDS = ("text", "lesson_slug", "corpus_version")
UNUSED_PROVENANCE_FIELDS = ("v1_3_checker_model_id", "panel_weights_version", "routing_table_version", "tool_contract_version")
LEDGER_DELIVERIES = ("legacy", "shadow", "delivered")
# Plan 12.8: "OPEN DECISION. Retention period (Product Owner; Principal Investigator consulted)". While it is open the
# only behaviour the package may name is "retain": no job deletes ledger rows (DI-45; the append-only triggers refuse
# DELETE anyway). owner_decisions.PLAN-12.8 records the decision's state.
LEDGER_RETENTION_WHILE_OPEN = "retain"
_HEX64_CHARS = frozenset("0123456789abcdef")


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
    # Package v2: the package version the committed calibration record was computed with (spec 5.3, M10).
    calibrated_with_package_version: str | None = None


@dataclass(frozen=True)
class SchemaPin:
    version: str
    path: str
    sha256: str


@dataclass(frozen=True)
class TutorPipelineParams:
    """Package v2 tutor_pipeline (Phase 3 spec 5.1); every value is provisional (PD-11) unless the plan gives it."""

    version: str
    status: str
    schemas: Mapping[str, SchemaPin]
    resolver_id: str
    resolver_prompt_hash: str
    min_content_terms: int
    continuation_cues: tuple[str, ...]
    max_lookback: int
    request_fields: tuple[str, ...]
    top_k: int
    retrieval_mode: str
    near_miss_rule: str
    generator_default: str
    generators_allowed: tuple[str, ...]
    evidential_prompt_hash: str
    max_claims: int
    max_claims_per_span: int
    min_sentence_words: int
    max_sentence_chars: int
    sentence_rule: str
    binding_rule: str
    renderer_id: str
    pedagogical_prompt_hash: str
    presentation_plans: tuple[str, ...]
    default_plan: str
    max_regenerations: int
    subset_check: str
    ledger_chain: str
    ledger_entry_schema: str
    record_hash_rule: str
    genesis: str
    deliveries: tuple[str, ...]
    phase2_bound_claim_ratio: float
    unused_provenance_fields: tuple[str, ...]
    # tutor_pipeline.budgets (PD-11: engineering parameters with no plan value). TWO_PASS_SHADOW_BUDGET_MS and
    # TUTOR_LEDGER_APPEND_BUDGET_MS override the first two when set; nothing else does.
    shadow_budget_ms: int
    ledger_append_budget_ms: int
    ledger_append_attempts: int
    ledger_wait_grace_ms: int
    ledger_append_workers: int
    ledger_append_max_in_flight: int
    # tutor_pipeline.ledger.retention: "retain" while plan 12.8 is open (owner_decisions.PLAN-12.8).
    ledger_retention: str
    # tutor_pipeline.idempotency: the POST /tutor/turns Idempotency-Key (plan 7.3 "mutations carry client keys").
    idempotency_header: str
    idempotency_key_pattern: str
    idempotency_ttl_hours: int

    @property
    def schemas_sha256(self) -> str:
        """One digest of the sorted schema pins, for /ready."""
        return canonical_sha256({name: [pin.version, pin.path, pin.sha256] for name, pin in sorted(self.schemas.items())})


@dataclass(frozen=True)
class FlagPolicy:
    phase4_exit_passed: bool
    phase4_exit_evidence: str | None


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
    # Package v2 (Phase 3). A v1 package has schema_version 1, no tutor_pipeline and phase4_exit_passed false.
    schema_version: int = 1
    tutor_pipeline: TutorPipelineParams | None = None
    flag_policy: FlagPolicy = FlagPolicy(False, None)
    supersedes: Mapping[str, Any] | None = None


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


def _hex64(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    _require(isinstance(value, str) and len(value) == 64 and set(value) <= _HEX64_CHARS, f"'{key}' must be 64 lowercase hex characters")
    return value


def _integer_in(raw: Mapping[str, Any], key: str, minimum: int, maximum: int) -> int:
    value = raw.get(key)
    _require(
        isinstance(value, int) and not isinstance(value, bool) and minimum <= value <= maximum,
        f"'{key}' must be an integer in [{minimum}, {maximum}]",
    )
    return int(value)


def _schema_path(value: Any, name: str) -> str:
    _require(isinstance(value, str) and bool(value), f"tutor_pipeline.schemas.{name}.path must be a non-empty string")
    pure = Path(value)
    parts = value.replace("\\", "/").split("/")
    _require(
        not pure.is_absolute() and not value.startswith(("/", "\\")) and ":" not in value and ".." not in parts and parts[0] == "schemas",
        f"tutor_pipeline.schemas.{name}.path must be a relative path under schemas/",
    )
    return value


def _parse_tutor_pipeline(raw: Mapping[str, Any]) -> TutorPipelineParams:
    tutor = _mapping(raw, "tutor_pipeline")
    schemas_raw = _mapping(tutor, "schemas")
    _require(set(schemas_raw) == set(TUTOR_SCHEMA_NAMES), f"tutor_pipeline.schemas must name exactly {', '.join(TUTOR_SCHEMA_NAMES)}")
    schemas: dict[str, SchemaPin] = {}
    for name in TUTOR_SCHEMA_NAMES:
        pin = _mapping(schemas_raw, name)
        schemas[name] = SchemaPin(version=_text(pin, "version"), path=_schema_path(pin.get("path"), name), sha256=_hex64(pin, "sha256"))
    resolver = _mapping(tutor, "resolver")
    retrieval = _mapping(tutor, "retrieval")
    evidential = _mapping(tutor, "evidential")
    pedagogical = _mapping(tutor, "pedagogical")
    ledger = _mapping(tutor, "ledger")
    stop = _mapping(tutor, "stop")
    budgets = _mapping(tutor, "budgets")
    _require(budgets.get("provisional") is True, "tutor_pipeline.budgets must be marked provisional: true (PD-11)")
    workers = _integer_in(budgets, "ledger_append_workers", 1, 16)
    idempotency = _mapping(tutor, "idempotency")
    _require(idempotency.get("provisional") is True, "tutor_pipeline.idempotency must be marked provisional: true (PD-11)")
    key_pattern = _text(idempotency, "key_pattern")
    try:
        compiled_key = re.compile(key_pattern)
    except re.error as exc:
        raise ConfigPackageError(f"Configuration package: tutor_pipeline.idempotency.key_pattern does not compile: {exc}") from exc
    _require(
        key_pattern.startswith("^") and key_pattern.endswith("$") and not compiled_key.fullmatch("a" * 257) and not compiled_key.fullmatch(""),
        "tutor_pipeline.idempotency.key_pattern must be anchored and bounded (no empty key, nothing over 256 characters)",
    )

    cues = _strings(resolver, "continuation_cues")
    _require(all(cue == cue.lower() for cue in cues), "tutor_pipeline.resolver.continuation_cues must be lowercase")
    request_fields = tuple(retrieval.get("request_fields") or ())
    _require(request_fields == RETRIEVAL_REQUEST_FIELDS, "tutor_pipeline.retrieval.request_fields must be [text, lesson_slug, corpus_version] (plan 3.2)")
    _require(retrieval.get("mode") == "lexical", "tutor_pipeline.retrieval.mode must be 'lexical' in Phase 3 (spec conflict 33)")

    allowed = _strings(evidential, "generators_allowed")
    default_generator = _text(evidential, "generator_default")
    _require(set(allowed) <= WIRED_GENERATORS, "tutor_pipeline.evidential.generators_allowed names a generator that is not wired (D-12 open, hold H6)")
    _require(default_generator in allowed, "tutor_pipeline.evidential.generator_default must be one of generators_allowed")
    max_claims = _integer_in(evidential, "max_claims", 1, 10)
    max_claims_per_span = _integer_in(evidential, "max_claims_per_span", 1, max_claims)
    min_sentence_words = _integer_in(evidential, "min_sentence_words", 1, 50)
    max_sentence_chars = _integer_in(evidential, "max_sentence_chars", 50, 100000)

    plans = _strings(pedagogical, "presentation_plans")
    _require(set(REQUIRED_PRESENTATION_PLANS) <= set(plans), "tutor_pipeline.pedagogical.presentation_plans must include concise, stepwise and socratic")
    default_plan = _text(pedagogical, "default_plan")
    _require(default_plan in plans, "tutor_pipeline.pedagogical.default_plan must be one of presentation_plans")
    # Plan 3.7: "render regeneration (at most two)".
    max_regenerations = _integer_in(pedagogical, "max_regenerations", 0, 2)

    deliveries = _strings(ledger, "deliveries")
    _require(set(deliveries) == set(LEDGER_DELIVERIES), "tutor_pipeline.ledger.deliveries must be legacy, shadow and delivered")
    genesis = _hex64(ledger, "genesis")
    _require(genesis == "0" * 64, "tutor_pipeline.ledger.genesis must be 64 zeros")
    ratio = _number(stop, "phase2_bound_claim_ratio", maximum=1.0)
    _require(ratio > 0, "tutor_pipeline.stop.phase2_bound_claim_ratio must be in (0, 1]")
    unused = tuple(tutor.get("unused_provenance_fields") or ())
    _require(unused == UNUSED_PROVENANCE_FIELDS, "tutor_pipeline.unused_provenance_fields must name the four Phase 4-5 provenance fields")
    retention = _text(ledger, "retention")
    return TutorPipelineParams(
        version=_text(tutor, "version"),
        status=_text(tutor, "status"),
        schemas=schemas,
        resolver_id=_text(resolver, "id"),
        resolver_prompt_hash=_hex64(resolver, "prompt_hash"),
        min_content_terms=_integer_in(resolver, "min_content_terms", 1, 20),
        continuation_cues=cues,
        max_lookback=_integer_in(resolver, "max_lookback", 1, 20),
        request_fields=request_fields,
        top_k=_integer_in(retrieval, "top_k", 1, 12),
        retrieval_mode="lexical",
        near_miss_rule=_text(retrieval, "near_miss_rule"),
        generator_default=default_generator,
        generators_allowed=allowed,
        evidential_prompt_hash=_hex64(evidential, "prompt_hash"),
        max_claims=max_claims,
        max_claims_per_span=max_claims_per_span,
        min_sentence_words=min_sentence_words,
        max_sentence_chars=max_sentence_chars,
        sentence_rule=_text(evidential, "sentence_rule"),
        binding_rule=_text(evidential, "binding_rule"),
        renderer_id=_text(pedagogical, "renderer"),
        pedagogical_prompt_hash=_hex64(pedagogical, "prompt_hash"),
        presentation_plans=plans,
        default_plan=default_plan,
        max_regenerations=max_regenerations,
        subset_check=_text(pedagogical, "subset_check"),
        ledger_chain=_text(ledger, "chain"),
        ledger_entry_schema=_text(ledger, "entry_schema"),
        record_hash_rule=_text(ledger, "record_hash_rule"),
        genesis=genesis,
        deliveries=deliveries,
        phase2_bound_claim_ratio=ratio,
        unused_provenance_fields=unused,
        shadow_budget_ms=_integer_in(budgets, "shadow_ms", 100, 30000),
        ledger_append_budget_ms=_integer_in(budgets, "ledger_append_ms", 100, 5000),
        ledger_append_attempts=_integer_in(budgets, "ledger_append_attempts", 1, 5),
        ledger_wait_grace_ms=_integer_in(budgets, "ledger_wait_grace_ms", 0, 1000),
        ledger_append_workers=workers,
        ledger_append_max_in_flight=_integer_in(budgets, "ledger_append_max_in_flight", workers, 256),
        ledger_retention=retention,
        idempotency_header=_text(idempotency, "header"),
        idempotency_key_pattern=key_pattern,
        idempotency_ttl_hours=_integer_in(idempotency, "ttl_hours", 1, 168),
    )


def _parse_flag_policy(raw: Mapping[str, Any]) -> FlagPolicy:
    policy = _mapping(raw, "flag_policy")
    two_pass = _mapping(policy, "two_pass_tutor")
    _require(two_pass.get("values") == ["off", "shadow", "on"], "flag_policy.two_pass_tutor.values must be [off, shadow, on]")
    _require(two_pass.get("default_elsewhere") == "off", "flag_policy.two_pass_tutor.default_elsewhere must be 'off' (freeze, D-05)")
    _require(two_pass.get("on_requires") == "phase4_exit_passed", "flag_policy.two_pass_tutor.on_requires must be 'phase4_exit_passed'")
    passed = policy.get("phase4_exit_passed")
    _require(isinstance(passed, bool), "flag_policy.phase4_exit_passed must be a boolean")
    evidence = policy.get("phase4_exit_evidence")
    if passed:
        _require(isinstance(evidence, str) and bool(evidence.strip()), "flag_policy.phase4_exit_passed true needs a phase4_exit_evidence string")
    else:
        _require(evidence is None or isinstance(evidence, str), "flag_policy.phase4_exit_evidence must be null or a string")
    return FlagPolicy(phase4_exit_passed=passed, phase4_exit_evidence=evidence)


def parse_config_package(raw: Any, *, path: Path, sha256: str, hash_verified: bool) -> ConfigPackage:
    _require(isinstance(raw, dict), "the file must hold a JSON object")
    _require(raw.get("package") == PACKAGE_NAME, f"'package' must be '{PACKAGE_NAME}'")
    schema_version = raw.get("schema_version")
    _require(schema_version in (1, 2) and not isinstance(schema_version, bool), "'schema_version' must be 1 or 2")
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
    calibrated_with = abstention_raw.get("calibrated_with_package_version")
    _require(
        calibrated_with is None or (isinstance(calibrated_with, str) and bool(calibrated_with.strip())),
        "abstention.calibrated_with_package_version must be null or a non-empty string",
    )
    abstention = AbstentionParams(
        version=_text(abstention_raw, "version"),
        floor=_number(abstention_raw, "floor", minimum=0.0),
        margin=_number(abstention_raw, "margin", minimum=0.0),
        provisional=abstention_raw["provisional"],
        provisional_until=_text(abstention_raw, "provisional_until"),
        calibration_record=_text(abstention_raw, "calibration_record"),
        calibration_record_sha256=_text(abstention_raw, "calibration_record_sha256"),
        calibrated_with_package_version=calibrated_with,
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

    tutor_pipeline: TutorPipelineParams | None = None
    flag_policy = FlagPolicy(False, None)
    supersedes: Mapping[str, Any] | None = None
    if schema_version == 2:
        supersedes = _mapping(raw, "supersedes")
        _text(supersedes, "package_version")
        _hex64(supersedes, "sha256")
        tutor_pipeline = _parse_tutor_pipeline(raw)
        flag_policy = _parse_flag_policy(raw)
        d12 = decisions.get("D-12")
        _require(isinstance(d12, dict), "owner_decisions.D-12 must be an object in package v2")
        if d12.get("state") == "open":
            _require(
                list(tutor_pipeline.generators_allowed) == ["extractive-d19-v1"],
                "owner_decisions.D-12 is open, so only the extractive-d19-v1 generator may be allowed (hold H6)",
            )
        _require(isinstance(decisions.get("D-19"), dict), "owner_decisions.D-19 must be an object in package v2")
        retention = decisions.get("PLAN-12.8")
        _require(isinstance(retention, dict), "owner_decisions.PLAN-12.8 (the ledger retention period) must be an object in package v2")
        # A decided period needs a retention job that prunes the chain, which does not exist (DI-45): until then the
        # package can only say the decision is open and the ledger is retained.
        _require(retention.get("state") == "open", "owner_decisions.PLAN-12.8.state must be 'open': no ledger retention job exists (DI-45)")
        _require(
            tutor_pipeline.ledger_retention == LEDGER_RETENTION_WHILE_OPEN and retention.get("behaviour") == LEDGER_RETENTION_WHILE_OPEN,
            "owner_decisions.PLAN-12.8 is open, so the ledger is retained: tutor_pipeline.ledger.retention and its behaviour must be 'retain'",
        )

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
        schema_version=int(schema_version),
        tutor_pipeline=tutor_pipeline,
        flag_policy=flag_policy,
        supersedes=supersedes,
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
