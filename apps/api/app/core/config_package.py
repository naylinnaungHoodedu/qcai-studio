"""Configuration package (plan Phase 2 P: "configuration package v1 published"; Phase 3 P: "schemas in
configuration package v2"; Phase 4 P: "fixture hashes in configuration package v3"; Phase 2 spec 2.5 and 4.2;
Phase 3 spec section 5; Phase 4 spec section 5).

A versioned JSON file shipped in the API image (apps/api/app/config_package/v3.json) that freezes every Phase 2
value: the span-identity scheme, the BM25 parameters and stopword list, the provisional abstention floor and
margin, the near-duplicate thresholds, the D-30 legacy-citation rule, the provisional owner decisions (D-17, D-30,
Q-10) and the boundary policy. Version 2 (Phase 3) copies every v1 block and adds the two-channel tutor: the
sha256 pins of the eight contract schemas (app/config_package/schemas/), the resolver, generator and renderer ids
and prompt hashes, the regeneration limit, the presentation plans, the bound-claim stop baseline, the ids and rule
hash of the legacy contained path that every legacy ledger record stamps (tutor_pipeline.legacy) and the
two_pass_tutor flag policy (phase4_exit_passed). Version 3 (Phase 4) copies every v2 block, pins a ninth schema
(LedgerEntryV2) and adds the V1 checks (`v1`): rule ids and their hash, the lexicon, every V1 threshold and band
(provisional, Q-22), the checker hosting (none, D-21), the misconception library (v0, empty, Q-14), the D-20 interim
rule, the quiz-key disclosure rule (PD-21), the adversarial fixture set's hash and the plan L stop conditions; and the
v1_pipeline flag policy. Version 4 (Phase 5, apps/api/app/config_package/v4.json, the shipped package) copies every v3
block, pins five more schemas (LedgerEntryV3 and the four gateway request and verdict contracts) and adds the model
gateway (`gateway`: the adapter registry per environment, the pinning rule, the D-23 egress opt-in, budgets, the
evidential cache, the payload policy, the stop guards and the retired settings), the V2 panel (`v2`: families, tiers,
the voting matrix, correction, degraded modes, the alignment item), the tool contracts (`tools`) and the model_gateway
flag policy. Next to each file, <name>.json.sha256 holds the sha256 of its canonical JSON, so a CRLF checkout hashes the
same. v3.json, v2.json and v1.json stay readable for one release (DI-84, DI-63, DI-42).

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

from app.core.config import (
    MODEL_GATEWAY_DEFAULT_DEVELOPMENT,
    MODEL_GATEWAY_DEFAULT_ELSEWHERE,
    TWO_PASS_DEFAULT_DEVELOPMENT,
    TWO_PASS_DEFAULT_ELSEWHERE,
    V1_PIPELINE_DEFAULT_DEVELOPMENT,
    V1_PIPELINE_DEFAULT_ELSEWHERE,
    Settings,
)
from app.core.structured_logging import FIELDS

LOGGER = logging.getLogger("qcai.config_package")
PACKAGE_DIRECTORY = Path(__file__).resolve().parents[1] / "config_package"
DEFAULT_PACKAGE_PATH = PACKAGE_DIRECTORY / "v4.json"
# Readable for one release after the Phase 5 merge (DI-84), the Phase 4 merge (DI-63) and the Phase 3 merge (DI-42); CI
# checks each with config_package.py --check --path.
V3_PACKAGE_PATH = PACKAGE_DIRECTORY / "v3.json"
V2_PACKAGE_PATH = PACKAGE_DIRECTORY / "v2.json"
V1_PACKAGE_PATH = PACKAGE_DIRECTORY / "v1.json"
PACKAGE_NAME = "qcai-configuration-package"
SPAN_SCHEME = "span-v2"
P1_FLOOR_VERSION = "score-floor-p1-v1"
P1_FLOOR = 6
# D-12 open: no provider generator is wired. Hold H6 blocks the provider interim path (a single pinned provider;
# PD-09) and stays held, so the pipeline runs the D-19 extractive generator instead (PD-08), which sends no provider
# payload; package v4 names its family (v2.generator_families), which the V2 panel excludes.
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
# Package v3 pins LedgerEntryV2 too (Phase 4 spec 5.2).
TUTOR_SCHEMA_NAMES_V3 = (*TUTOR_SCHEMA_NAMES, "LedgerEntryV2")
REQUIRED_PRESENTATION_PLANS = ("concise", "stepwise", "socratic")
RETRIEVAL_REQUEST_FIELDS = ("text", "lesson_slug", "corpus_version")
UNUSED_PROVENANCE_FIELDS = ("v1_3_checker_model_id", "panel_weights_version", "routing_table_version", "tool_contract_version")
# Package v3: V1.3 records its checker id ("none" while D-21 is open), so three provenance fields stay unused.
UNUSED_PROVENANCE_FIELDS_V3 = ("panel_weights_version", "routing_table_version", "tool_contract_version")
LEDGER_ENTRY_SCHEMAS_V3 = ("ledger-entry-v1", "ledger-entry-v2")
# Package v4 pins LedgerEntryV3 and the gateway's four request and verdict contracts (Phase 5 spec 5.1).
TUTOR_SCHEMA_NAMES_V4 = (*TUTOR_SCHEMA_NAMES_V3, "LedgerEntryV3", "V2VerdictRequest", "V2AlignmentRequest", "V2AdapterVerdict",
                         "V2AlignmentVerdict")
LEDGER_ENTRY_SCHEMAS_V4 = ("ledger-entry-v1", "ledger-entry-v2", "ledger-entry-v3")
V1_FAMILY_LIMIT = 20
# The plan's EHMF types per check (plan Phase 4 D table), which package v3 v1.ehmf must repeat.
V1_EHMF = {"V1.1": ("B",), "V1.2": ("A", "B"), "V1.3": ("A", "B", "C"), "V1.4": ("D", "E"), "V1.5": ("A",),
           "V1.6": ("E",), "V1.7": ("D",), "V1.8": ("C",), "V1.9": ("E",)}
V1_PROVISIONAL_BLOCKS = ("lexicon", "v1_3", "v1_5", "v1_6", "v1_7", "v1_9", "quiz_feedback", "d20_interim", "stop")
V1_COMPOSITION_RULE = "v1-adds-no-in-domain-abstention-v1"
V1_D20_RULE = "withhold-all-flagged-v1"
# PD-21 (plan Phase 4 B "keyed answers outside public payloads"; R-42): no quiz key in any public payload; a saved
# attempt returns the key and explanation of the questions it answered. The only rule the quiz route implements
# (app.services.quiz_keys.FEEDBACK_RULE, which package_check compares); provisional until DI-55 ratifies it.
V1_QUIZ_FEEDBACK_RULE = "keys-after-saved-attempt-answered-only-v1"
MISCONCEPTION_LIBRARY_NAME = "qcai-misconception-library"
GATE_IDS = ("bm25f-v1", "p1-floor")
LEDGER_DELIVERIES = ("legacy", "shadow", "delivered")
# Plan 12.8: "OPEN DECISION. Retention period (Product Owner; Principal Investigator consulted); proposed default
# release life plus 24 months." While it is open the only behaviour the package may name is "retain": no job deletes
# ledger rows (DI-45; the append-only triggers refuse DELETE anyway). owner_decisions.PLAN-12.8 records the
# decision's state, the proposed default and why it is not applied (it is not a default form engineering applies,
# and no release life has ended, so it would retain every record too).
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
    # The content terms a sentence must share with the question to become a claim (spec 18.8 F5; PD-11).
    min_question_overlap_terms: int
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
    # An in-progress claim (no response yet) older than this is abandoned: its request died without releasing it
    # (spec 18.7 E7). Well above a request's worst case: twice Cloud Run's default 300 s request timeout.
    idempotency_lease_seconds: int
    # tutor_pipeline.legacy: the ids and rule hash of the legacy contained path (D-19 containment, task 1.11) that
    # every legacy ledger record stamps; package_check compares them with app.services.ledger, and the provenance
    # audit (ledger.ledger_provenance) compares records with them (DI-49).
    legacy_pipeline_version: str
    legacy_generator_id: str
    legacy_generator_model_id: str
    legacy_containment_rule_hash: str

    @property
    def schemas_sha256(self) -> str:
        """One digest of the sorted schema pins, for /ready."""
        return canonical_sha256({name: [pin.version, pin.path, pin.sha256] for name, pin in sorted(self.schemas.items())})


@dataclass(frozen=True)
class FlagPolicy:
    phase4_exit_passed: bool
    phase4_exit_evidence: str | None
    # Package v4: MODEL_GATEWAY=on is refused outside development while this is false (plan Phase 5 G, P).
    phase5_exit_passed: bool = False
    phase5_exit_evidence: str | None = None


@dataclass(frozen=True)
class V1Lexicon:
    """Package v3 v1.lexicon (PD-20): the negation cues, the negation suffixes, the number words, the closed unit
    list and the shortest alignment term."""

    negation_cues: frozenset[str]
    negation_suffixes: tuple[str, ...]
    number_words: frozenset[str]
    units: frozenset[str]
    min_alignment_term_chars: int


@dataclass(frozen=True)
class MisconceptionEntryParams:
    entry_id: str
    terms: tuple[str, ...]


@dataclass(frozen=True)
class V1Params:
    """Package v3 v1 (Phase 4 spec 5.1): every value the V1 checks read (R-46). Values without plan text are
    provisional (Q-22, D-06: "frozen in versioned configuration before use, never reported as results")."""

    version: str
    status: str
    rules_hash: str
    rule_ids: Mapping[str, str]
    ehmf: Mapping[str, tuple[str, ...]]
    max_generation_regenerations: int
    max_render_regenerations: int
    lexicon: V1Lexicon
    checker_hosting: str
    checker_model_id: str
    support_threshold: float
    checker_timeout_ms: int
    checker_unavailable: str
    x4_margin: Mapping[str, float]
    assessment_threshold: float
    short_key_min_tokens: int
    socratic_plan: str
    assessment_scope: str
    alignment_threshold: float
    min_alignment_terms: int
    on_conflict: str
    # item_id -> version family (v1_7.version_families).
    version_families: Mapping[str, str]
    library_version: str
    library_sha256: str
    library_entries: tuple[MisconceptionEntryParams, ...]
    readability_min: float
    readability_max: float
    d20_rule: str
    d20_replacement: str
    fixtures_path: str
    fixtures_set_sha256: str
    fixtures_cases: int
    # gate -> (answered, in_domain): the Phase 2 answer-rate baseline as counts, never a rounded rate (spec M1).
    answer_rate_floor: Mapping[str, tuple[int, int]]
    composition_rule: str
    p95_budget_ms: int
    # PD-21: the quiz-key disclosure rule the quiz route implements (V1_QUIZ_FEEDBACK_RULE).
    quiz_feedback_rule: str


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
    # Package v3 (Phase 4): the V1 checks. None on a v1 or v2 package.
    v1: V1Params | None = None
    # Package v4 (Phase 5): the model gateway, the V2 panel and the tool contracts. None on a v1, v2 or v3 package.
    gateway: "GatewayParams | None" = None
    v2: "V2Params | None" = None
    tools: "ToolParams | None" = None


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


def _parse_tutor_pipeline(raw: Mapping[str, Any], *, schema_version: int = 2) -> TutorPipelineParams:
    tutor = _mapping(raw, "tutor_pipeline")
    schemas_raw = _mapping(tutor, "schemas")
    names = TUTOR_SCHEMA_NAMES_V4 if schema_version >= 4 else TUTOR_SCHEMA_NAMES_V3 if schema_version >= 3 else TUTOR_SCHEMA_NAMES
    _require(set(schemas_raw) == set(names), f"tutor_pipeline.schemas must name exactly {', '.join(names)}")
    schemas: dict[str, SchemaPin] = {}
    for name in names:
        pin = _mapping(schemas_raw, name)
        schemas[name] = SchemaPin(version=_text(pin, "version"), path=_schema_path(pin.get("path"), name), sha256=_hex64(pin, "sha256"))
    resolver = _mapping(tutor, "resolver")
    retrieval = _mapping(tutor, "retrieval")
    evidential = _mapping(tutor, "evidential")
    pedagogical = _mapping(tutor, "pedagogical")
    ledger = _mapping(tutor, "ledger")
    legacy = _mapping(tutor, "legacy")
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
    ttl_hours = _integer_in(idempotency, "ttl_hours", 1, 168)
    lease_seconds = _integer_in(idempotency, "in_progress_lease_seconds", 60, 3600)
    _require(lease_seconds < ttl_hours * 3600, "tutor_pipeline.idempotency.in_progress_lease_seconds must be shorter than ttl_hours")

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
    min_question_overlap_terms = _integer_in(evidential, "min_question_overlap_terms", 1, 20)

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
    if schema_version >= 4:
        # Package v4 fills every provenance field (plan 7.4), and names the v3 ledger entry too.
        _require(unused == (), "tutor_pipeline.unused_provenance_fields must be empty in package v4 (every provenance field is filled)")
        _require(ledger.get("legacy_entry_schema") == "ledger-entry-v1", "tutor_pipeline.ledger.legacy_entry_schema must be 'ledger-entry-v1'")
        _require(ledger.get("entry_schemas") == list(LEDGER_ENTRY_SCHEMAS_V4),
                 "tutor_pipeline.ledger.entry_schemas must be [ledger-entry-v1, ledger-entry-v2, ledger-entry-v3]")
    elif schema_version >= 3:
        # ledger.entry_schema is compared with the LedgerEntryV2 contract by package_check, as every rule id is.
        _require(unused == UNUSED_PROVENANCE_FIELDS_V3, "tutor_pipeline.unused_provenance_fields must name the three Phase 5 provenance fields")
        _require(ledger.get("legacy_entry_schema") == "ledger-entry-v1", "tutor_pipeline.ledger.legacy_entry_schema must be 'ledger-entry-v1'")
        _require(ledger.get("entry_schemas") == list(LEDGER_ENTRY_SCHEMAS_V3),
                 "tutor_pipeline.ledger.entry_schemas must be [ledger-entry-v1, ledger-entry-v2]")
    else:
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
        min_question_overlap_terms=min_question_overlap_terms,
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
        idempotency_ttl_hours=ttl_hours,
        idempotency_lease_seconds=lease_seconds,
        legacy_pipeline_version=_text(legacy, "pipeline_version"),
        legacy_generator_id=_text(legacy, "generator_id"),
        legacy_generator_model_id=_text(legacy, "generator_model_id"),
        legacy_containment_rule_hash=_hex64(legacy, "containment_rule_hash"),
    )


def _parse_v1_pipeline_policy(policy: Mapping[str, Any]) -> None:
    """Package v3 flag_policy.v1_pipeline (PD-19): the values, the defaults Settings applies and the two refusals."""
    v1 = _mapping(policy, "v1_pipeline")
    _require(v1.get("values") == ["off", "shadow", "enforce"], "flag_policy.v1_pipeline.values must be [off, shadow, enforce]")
    _require(v1.get("default_development") == V1_PIPELINE_DEFAULT_DEVELOPMENT,
             f"flag_policy.v1_pipeline.default_development must be the code's default ({V1_PIPELINE_DEFAULT_DEVELOPMENT!r})")
    _require(v1.get("default_elsewhere") == V1_PIPELINE_DEFAULT_ELSEWHERE,
             f"flag_policy.v1_pipeline.default_elsewhere must be the code's default ({V1_PIPELINE_DEFAULT_ELSEWHERE!r})")
    _require(v1.get("enforce_requires") == "phase4_exit_passed", "flag_policy.v1_pipeline.enforce_requires must be 'phase4_exit_passed'")
    _require(v1.get("off_outside_development") == "refused",
             "flag_policy.v1_pipeline.off_outside_development must be 'refused' (plan 13.6: no flag may disable V1)")


def _provisional(block: Mapping[str, Any], name: str) -> None:
    _require(block.get("provisional") is True, f"v1.{name} must be marked provisional: true (Q-22; plan L795-800)")


def _sorted_lowercase(values: tuple[str, ...], name: str) -> None:
    _require(bool(values), f"v1.lexicon.{name} must not be empty")
    _require(list(values) == sorted(set(values)) and all(value == value.lower() for value in values),
             f"v1.lexicon.{name} must be lowercase, sorted and unique")


def _relative_path(value: Any, name: str) -> str:
    _require(isinstance(value, str) and bool(value), f"{name} must be a non-empty string")
    parts = value.replace("\\", "/").split("/")
    _require(not Path(value).is_absolute() and not value.startswith(("/", "\\")) and ":" not in value and ".." not in parts,
             f"{name} must be a relative path without '..'")
    return value


def misconception_library_sha256(library: Mapping[str, Any]) -> str:
    """The canonical sha256 of an inline misconception library without its own sha256 field (Phase 4 spec 4.9)."""
    return canonical_sha256({key: value for key, value in library.items() if key != "sha256"})


def _parse_library(raw: Any) -> tuple[str, str, tuple[MisconceptionEntryParams, ...]]:
    _require(isinstance(raw, dict), "v1.v1_8.library must be an object")
    _require(raw.get("library") == MISCONCEPTION_LIBRARY_NAME, f"v1.v1_8.library.library must be '{MISCONCEPTION_LIBRARY_NAME}'")
    version = _text(raw, "version")
    entries_raw = raw.get("entries")
    _require(isinstance(entries_raw, list), "v1.v1_8.library.entries must be a list")
    entries = []
    seen: set[str] = set()
    for entry in entries_raw:
        _require(isinstance(entry, dict), "v1.v1_8.library entries must be objects")
        entry_id = _text(entry, "id")
        _require(entry_id not in seen, f"v1.v1_8.library entry {entry_id} is listed twice")
        seen.add(entry_id)
        terms = _strings(entry, "terms")
        _require(len(terms) >= 2, f"v1.v1_8.library entry {entry_id} needs at least two terms")
        _require(list(terms) == sorted(set(terms)) and all(term == term.lower() for term in terms),
                 f"v1.v1_8.library entry {entry_id} terms must be lowercase, sorted and unique")
        entries.append(MisconceptionEntryParams(entry_id=entry_id, terms=terms))
    digest = _hex64(raw, "sha256")
    _require(digest == misconception_library_sha256(raw), "v1.v1_8.library.sha256 does not match the library's canonical sha256")
    return version, digest, tuple(entries)


def _parse_v1(raw: Mapping[str, Any], *, tutor: TutorPipelineParams) -> V1Params:
    """Package v3 v1 (Phase 4 spec 5.2). Every refusal is structural: a malformed block always stops the load."""
    from app.services.v1_checks.rules import WIRED_CHECKERS  # lazy: v1_checks imports this module

    v1 = _mapping(raw, "v1")
    _require(v1.get("provisional") is True, "v1 must be marked provisional: true (Q-22)")
    for name in V1_PROVISIONAL_BLOCKS:
        _provisional(_mapping(v1, name), name)
    rule_ids_raw = _mapping(v1, "rule_ids")
    _require(all(isinstance(value, str) and value for value in rule_ids_raw.values()), "v1.rule_ids values must be non-empty strings")
    ehmf_raw = _mapping(v1, "ehmf")
    _require({key: tuple(value) if isinstance(value, list) else value for key, value in ehmf_raw.items()} == V1_EHMF,
             "v1.ehmf must be the plan's EHMF types per check (plan Phase 4 D)")
    regeneration = _mapping(v1, "regeneration")
    lexicon_raw = _mapping(v1, "lexicon")
    cues = _strings(lexicon_raw, "negation_cues")
    _sorted_lowercase(cues, "negation_cues")
    suffixes = _strings(lexicon_raw, "negation_suffixes")
    _require(bool(suffixes), "v1.lexicon.negation_suffixes must not be empty")
    number_words = _strings(lexicon_raw, "number_words")
    _sorted_lowercase(number_words, "number_words")
    units = _strings(lexicon_raw, "units")
    _sorted_lowercase(units, "units")
    lexicon = V1Lexicon(
        negation_cues=frozenset(cues),
        negation_suffixes=suffixes,
        number_words=frozenset(number_words),
        units=frozenset(units),
        min_alignment_term_chars=_integer_in(lexicon_raw, "min_alignment_term_chars", 1, 10),
    )
    v1_3 = _mapping(v1, "v1_3")
    hosting = _text(v1_3, "hosting")
    _require(hosting in WIRED_CHECKERS, "v1.v1_3.hosting names a checker that is not wired (D-21 open)")
    support = _number(v1_3, "support_threshold", minimum=0.0, maximum=1.0)
    timeout_ms = _integer_in(v1_3, "timeout_ms", 10, 10000)
    _require(timeout_ms < tutor.shadow_budget_ms, "v1.v1_3.timeout_ms must be below tutor_pipeline.budgets.shadow_ms")
    _require(v1_3.get("unavailable") == "abstain", "v1.v1_3.unavailable must be 'abstain' (AC-4-7)")
    v1_5 = _mapping(v1, "v1_5")
    margin_raw = _mapping(v1_5, "x4_margin")
    _require(set(margin_raw) == set(GATE_IDS), "v1.v1_5.x4_margin must name bm25f-v1 and p1-floor")
    # The X4 margin is an operator value per gate (Q-22): V1.5 marks a response whose top score lies below the gate's
    # floor plus it (spec 4.6, conflict 19). Any non-negative number loads; the shipped values are PD-15's.
    x4 = {gate: _number(margin_raw, gate, minimum=0.0) for gate in GATE_IDS}
    v1_6 = _mapping(v1, "v1_6")
    assessment = _number(v1_6, "assessment_threshold", maximum=1.0)
    _require(assessment > 0, "v1.v1_6.assessment_threshold must be in (0, 1]")
    socratic = _text(v1_6, "socratic_plan")
    _require(socratic in tutor.presentation_plans, "v1.v1_6.socratic_plan must be one of the presentation plans")
    _require(v1_6.get("scope") == "all_lessons", "v1.v1_6.scope must be 'all_lessons'")
    v1_7 = _mapping(v1, "v1_7")
    alignment = _number(v1_7, "alignment_threshold", maximum=1.0)
    _require(alignment > 0, "v1.v1_7.alignment_threshold must be in (0, 1]")
    on_conflict = _text(v1_7, "on_conflict")
    _require(on_conflict in ("disclose", "withhold"), "v1.v1_7.on_conflict must be 'disclose' or 'withhold'")
    families_raw = v1_7.get("version_families")
    _require(isinstance(families_raw, list) and len(families_raw) <= V1_FAMILY_LIMIT,
             f"v1.v1_7.version_families must be a list of at most {V1_FAMILY_LIMIT} families")
    families: dict[str, str] = {}
    for family in families_raw:
        _require(isinstance(family, dict), "v1.v1_7.version_families entries must be objects")
        name = _text(family, "family")
        items = _strings(family, "item_ids")
        _require(len(set(items)) >= 2, f"v1.v1_7 family {name} needs at least two distinct items")
        for item in items:
            _require(item not in families, f"v1.v1_7 item {item} is in two families")
            families[item] = name
    v1_8 = _mapping(v1, "v1_8")
    library_version, library_sha256, entries = _parse_library(v1_8.get("library"))
    _require(v1_8.get("on_match") == "flag_withhold_queue_v3", "v1.v1_8.on_match must be 'flag_withhold_queue_v3' (never hard)")
    v1_9 = _mapping(v1, "v1_9")
    readability = _mapping(v1_9, "readability")
    low = _number(readability, "min_grade", minimum=-50.0, maximum=200.0)
    high = _number(readability, "max_grade", minimum=-50.0, maximum=200.0)
    _require(low < high, "v1.v1_9.readability.min_grade must be below max_grade")
    quiz = _mapping(v1, "quiz_feedback")
    _require(quiz.get("rule") == V1_QUIZ_FEEDBACK_RULE, f"v1.quiz_feedback.rule must be '{V1_QUIZ_FEEDBACK_RULE}' (PD-21, the rule the quiz route implements)")
    _require(quiz.get("public_payloads") == "no_keys", "v1.quiz_feedback.public_payloads must be 'no_keys' (plan Phase 4 B: keyed answers outside public payloads)")
    _require(quiz.get("feedback") == "answered_questions_after_a_saved_attempt",
             "v1.quiz_feedback.feedback must be 'answered_questions_after_a_saved_attempt' (PD-21)")
    d20 = _mapping(v1, "d20_interim")
    fixtures = _mapping(v1, "fixtures")
    stop = _mapping(v1, "stop")
    floor_raw = _mapping(stop, "answer_rate_floor")
    floors: dict[str, tuple[int, int]] = {}
    for gate in GATE_IDS:
        entry = _mapping(floor_raw, gate)
        answered, in_domain = entry.get("answered"), entry.get("in_domain")
        _require(
            all(isinstance(value, int) and not isinstance(value, bool) for value in (answered, in_domain)) and 0 < answered <= in_domain,
            f"v1.stop.answer_rate_floor.{gate} must hold integers with 0 < answered <= in_domain",
        )
        floors[gate] = (int(answered), int(in_domain))
    composition = _mapping(stop, "composition")
    _require(composition.get("rule") == V1_COMPOSITION_RULE, f"v1.stop.composition.rule must be '{V1_COMPOSITION_RULE}'")
    return V1Params(
        version=_text(v1, "version"),
        status=_text(v1, "status"),
        rules_hash=_hex64(v1, "rules_hash"),
        rule_ids=dict(rule_ids_raw),
        ehmf=dict(V1_EHMF),
        max_generation_regenerations=_integer_in(regeneration, "max_generation_regenerations", 0, 2),
        max_render_regenerations=_integer_in(regeneration, "max_render_regenerations", 0, 2),
        lexicon=lexicon,
        checker_hosting=hosting,
        checker_model_id=_text(v1_3, "checker_model_id"),
        support_threshold=support,
        checker_timeout_ms=timeout_ms,
        checker_unavailable="abstain",
        x4_margin=x4,
        assessment_threshold=assessment,
        short_key_min_tokens=_integer_in(v1_6, "short_key_min_tokens", 1, 10),
        socratic_plan=socratic,
        assessment_scope="all_lessons",
        alignment_threshold=alignment,
        min_alignment_terms=_integer_in(v1_7, "min_alignment_terms", 1, 20),
        on_conflict=on_conflict,
        version_families=families,
        library_version=library_version,
        library_sha256=library_sha256,
        library_entries=entries,
        readability_min=low,
        readability_max=high,
        d20_rule=_text(d20, "rule"),
        d20_replacement=_text(d20, "replacement"),
        fixtures_path=_relative_path(fixtures.get("path"), "v1.fixtures.path"),
        fixtures_set_sha256=_hex64(fixtures, "set_sha256"),
        fixtures_cases=_integer(fixtures, "cases", minimum=0),
        answer_rate_floor=floors,
        composition_rule=V1_COMPOSITION_RULE,
        p95_budget_ms=_integer_in(stop, "v1_p95_latency_ms", 1, tutor.shadow_budget_ms),
        quiz_feedback_rule=V1_QUIZ_FEEDBACK_RULE,
    )


def _v1_owner_decisions(decisions: Mapping[str, Any], v1: V1Params) -> None:
    """The open owner decisions bound what package v3 may say (Phase 4 spec 5.2)."""
    for name in ("D-20", "D-21", "Q-22", "Q-14", "D-06"):
        _require(isinstance(decisions.get(name), dict), f"owner_decisions.{name} must be an object in package v3")
    if decisions["D-21"].get("state") == "open":
        _require(v1.checker_hosting == "none" and v1.checker_model_id == "none",
                 "owner_decisions.D-21 is open, so V1.3 has no checker: v1.v1_3.hosting and checker_model_id must be 'none'")
    if decisions["Q-14"].get("state") == "unavailable":
        _require(not v1.library_entries, "owner_decisions.Q-14 is unavailable, so the misconception library ships empty (A-18)")
    if decisions["D-20"].get("state") == "open":
        _require(v1.d20_rule == V1_D20_RULE, f"owner_decisions.D-20 is open, so v1.d20_interim.rule must be '{V1_D20_RULE}' (its own text)")


def _q22_provisional_values(raw: Mapping[str, Any], decisions: Mapping[str, Any]) -> None:
    """owner_decisions.Q-22.provisional_values names every value Q-22 sets (Phase 4 spec 5.2): each listed path is a
    value the package holds, and every block whose provisional_until names Q-22 is listed."""
    values = decisions["Q-22"].get("provisional_values")
    _require(isinstance(values, list) and bool(values) and all(isinstance(value, str) and value for value in values),
             "owner_decisions.Q-22.provisional_values must be a non-empty list of package paths")
    for path in values:
        node: Any = raw
        for part in path.split("."):
            _require(isinstance(node, dict) and part in node, f"owner_decisions.Q-22.provisional_values names {path}, which the package does not hold")
            node = node[part]

    def until_q22(node: Any, path: str) -> list[str]:
        if not isinstance(node, dict):
            return []
        found = [path] if isinstance(node.get("provisional_until"), str) and "Q-22" in node["provisional_until"] else []
        return found + [inner for key, value in node.items() for inner in until_q22(value, f"{path}.{key}" if path else key)]

    missing = [path for path in until_q22(raw, "") if path not in values]
    _require(not missing, f"owner_decisions.Q-22.provisional_values must name every block provisional until Q-22 (missing {missing})")


def _parse_flag_policy(raw: Mapping[str, Any], *, schema_version: int = 2) -> FlagPolicy:
    policy = _mapping(raw, "flag_policy")
    if schema_version >= 3:
        _parse_v1_pipeline_policy(policy)
    # PD-10 names flag_policy as where its two_pass_tutor values live (ratified under DI-37), and from schema 3 PD-19
    # its v1_pipeline values (ratified under DI-55); like every provisional block it says so.
    _require(policy.get("provisional") is True,
             "flag_policy must be marked provisional: true (PD-10" + ("; PD-19 for v1_pipeline)" if schema_version >= 3 else ")"))
    if schema_version >= 3:
        authority = policy.get("authority")
        _require(isinstance(authority, str) and all(name in authority for name in ("PD-10", "DI-37", "PD-19", "DI-55")),
                 "flag_policy.authority must name PD-10 (DI-37) and PD-19 (DI-55): it holds the v1_pipeline defaults")
    if schema_version >= 4:
        _require(all(name in str(policy.get("authority")) for name in ("PD-28", "DI-76")),
                 "flag_policy.authority must name PD-28 (DI-76): it holds the model_gateway defaults")
    two_pass = _mapping(policy, "two_pass_tutor")
    _require(two_pass.get("values") == ["off", "shadow", "on"], "flag_policy.two_pass_tutor.values must be [off, shadow, on]")
    _require(two_pass.get("default_elsewhere") == "off", "flag_policy.two_pass_tutor.default_elsewhere must be 'off' (freeze, D-05)")
    # The package records the defaults Settings applies; it may not name others (spec 18.8 F4).
    _require(two_pass.get("default_elsewhere") == TWO_PASS_DEFAULT_ELSEWHERE,
             f"flag_policy.two_pass_tutor.default_elsewhere must be the code's default ({TWO_PASS_DEFAULT_ELSEWHERE!r})")
    _require(two_pass.get("default_development") == TWO_PASS_DEFAULT_DEVELOPMENT,
             f"flag_policy.two_pass_tutor.default_development must be the code's default ({TWO_PASS_DEFAULT_DEVELOPMENT!r}; "
             "Settings applies it, so a package value that differs would describe a default nothing applies)")
    _require(two_pass.get("on_requires") == "phase4_exit_passed", "flag_policy.two_pass_tutor.on_requires must be 'phase4_exit_passed'")
    passed = policy.get("phase4_exit_passed")
    _require(isinstance(passed, bool), "flag_policy.phase4_exit_passed must be a boolean")
    evidence = policy.get("phase4_exit_evidence")
    if passed:
        _require(isinstance(evidence, str) and bool(evidence.strip()), "flag_policy.phase4_exit_passed true needs a phase4_exit_evidence string")
    else:
        _require(evidence is None or isinstance(evidence, str), "flag_policy.phase4_exit_evidence must be null or a string")
    if schema_version < 4:
        return FlagPolicy(phase4_exit_passed=passed, phase4_exit_evidence=evidence)
    gateway = _mapping(policy, "model_gateway")
    _require(gateway.get("values") == ["off", "shadow", "on"], "flag_policy.model_gateway.values must be [off, shadow, on]")
    _require(gateway.get("default_development") == MODEL_GATEWAY_DEFAULT_DEVELOPMENT,
             f"flag_policy.model_gateway.default_development must be the code's default ({MODEL_GATEWAY_DEFAULT_DEVELOPMENT!r})")
    _require(gateway.get("default_elsewhere") == MODEL_GATEWAY_DEFAULT_ELSEWHERE,
             f"flag_policy.model_gateway.default_elsewhere must be the code's default ({MODEL_GATEWAY_DEFAULT_ELSEWHERE!r})")
    _require(gateway.get("on_requires") == "phase5_exit_passed" and gateway.get("on_requires_v1") == "enforce",
             "flag_policy.model_gateway.on_requires must be 'phase5_exit_passed' and on_requires_v1 'enforce'")
    passed5 = policy.get("phase5_exit_passed")
    _require(isinstance(passed5, bool), "flag_policy.phase5_exit_passed must be a boolean")
    evidence5 = policy.get("phase5_exit_evidence")
    if passed5:
        _require(isinstance(evidence5, str) and bool(evidence5.strip()), "flag_policy.phase5_exit_passed true needs a phase5_exit_evidence string")
    else:
        _require(evidence5 is None or isinstance(evidence5, str), "flag_policy.phase5_exit_evidence must be null or a string")
    return FlagPolicy(phase4_exit_passed=passed, phase4_exit_evidence=evidence, phase5_exit_passed=passed5, phase5_exit_evidence=evidence5)


# ------------------------------------------------------------------------------------------------ package v4 (Phase 5)

GATEWAY_STOPS = ("budget_breach", "payload_violation", "secret_in_logs")
TOOL_SERVERS = ("analytics", "citation", "corpus", "learner", "verification")


@dataclass(frozen=True)
class GatewayParams:
    """Package v4 gateway (Phase 5 spec 5.1): the adapter registry per environment and the gateway's rules. Every value
    is provisional (PD-22, PD-24, PD-26, PD-27; DI-76)."""

    version: str
    registries: Mapping[str, tuple[Any, ...]]   # name -> AdapterSpec tuple, registry order
    pin_rule: str
    egress_setting: str
    daily_units: Mapping[str, int]
    alert_share: tuple[int, int]
    cache_key_rule: str
    cache_max_plans: int
    cache_max_verdicts: int
    payload_rule: str
    stop_on: tuple[str, ...]
    retired_settings: tuple[str, ...]


@dataclass(frozen=True)
class V2Params:
    """Package v4 v2 (Phase 5 spec 5.1): the V2 panel's parameters, provisional (PD-23, PD-25, PD-29, PD-30)."""

    version: str
    max_members: int
    generator_families: Mapping[str, str]
    verifier_prompt_id: str
    verifier_prompt_hash: str
    alignment_prompt_id: str
    alignment_prompt_hash: str
    tier_rule: str
    assessment_tier: int
    default_tier: int
    expert_mode: Any
    matrix: Mapping[str, Mapping[int, str]]
    tier3_threshold: tuple[int, int]
    panel_weights_version: str
    routing_table_version: str
    max_cycles: int
    critical_registry: tuple[str, ...]
    pre_verified_source: Any
    banners: Mapping[str, str]
    alignment_rule: str


@dataclass(frozen=True)
class ToolParams:
    version: str
    transport: str
    servers: tuple[str, ...]
    path: str
    sha256: str


def _bool_state(decisions: Mapping[str, Any], name: str, open_states: tuple[str, ...]) -> bool:
    entry = decisions.get(name)
    return isinstance(entry, dict) and entry.get("state") in open_states


def _parse_adapter(raw: Any, registry: str, *, providers_open: bool) -> Any:
    from app.gateway.adapters import WIRED_FAKE_RULES
    from app.gateway.pinning import pin_problem
    from app.gateway.registry import AUTH_HEADERS, CAPABILITIES, IDENTIFIER, MAX_RETRIES, MAX_TOKENS, TIMEOUT_MS, AdapterSpec, Caps

    _require(isinstance(raw, dict), f"gateway.registries.{registry} entries must be objects")
    adapter_id = raw.get("adapter_id")
    _require(isinstance(adapter_id, str) and re.fullmatch(IDENTIFIER, adapter_id) is not None,
             f"gateway.registries.{registry}: adapter_id must match {IDENTIFIER}")
    family = raw.get("family")
    _require(isinstance(family, str) and re.fullmatch(IDENTIFIER, family) is not None, f"gateway adapter {adapter_id}: family must match {IDENTIFIER}")
    model_id = raw.get("model_id")
    _require(isinstance(model_id, str) and bool(model_id.strip()), f"gateway adapter {adapter_id}: model_id must be a non-empty string")
    version = raw.get("model_version")
    problem = pin_problem(model_id, version if isinstance(version, str) else None)
    _require(problem is None, f"gateway adapter {adapter_id} is {problem} (AC-5-10; D-07 option (a), PD-24)")
    provider = raw.get("provider")
    _require(isinstance(provider, str) and re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", provider) is not None,
             f"gateway adapter {adapter_id}: provider must be a lowercase name")
    capabilities = raw.get("capabilities")
    _require(isinstance(capabilities, list) and bool(capabilities) and set(capabilities) <= set(CAPABILITIES) and len(set(capabilities)) == len(capabilities),
             f"gateway adapter {adapter_id}: capabilities must be generate and/or verify")
    caps_raw = _mapping(raw, "caps")
    caps = Caps(max_tokens=_integer_in(caps_raw, "max_tokens", *MAX_TOKENS), timeout_ms=_integer_in(caps_raw, "timeout_ms", *TIMEOUT_MS),
                max_retries=_integer_in(caps_raw, "max_retries", *MAX_RETRIES))
    cost = _integer(raw, "cost_units_per_call", minimum=0)
    fake = raw.get("fake")
    fake_rule = fake.get("rule") if isinstance(fake, dict) else None
    if provider == "fake":
        _require(fake_rule in WIRED_FAKE_RULES, f"gateway adapter {adapter_id}: a fake member names a wired fake rule")
        _require(registry == "development", f"gateway adapter {adapter_id}: fake members are registered in development only")
        _require(all(raw.get(key) is None for key in ("endpoint", "auth_header", "secret_ref")),
                 f"gateway adapter {adapter_id}: a fake member has no endpoint, auth header or secret")
    else:
        _require(fake is None, f"gateway adapter {adapter_id}: only a fake member names a fake rule")
        _require(not providers_open, f"gateway adapter {adapter_id}: no non-fake provider is registered while D-12, D-07 or Q-09 is open")
    endpoint = raw.get("endpoint")
    if endpoint is not None:
        from urllib.parse import urlsplit

        parts = urlsplit(str(endpoint))
        _require(parts.scheme == "https" and bool(parts.hostname) and not parts.query and not parts.fragment
                 and not parts.username and not parts.password and "@" not in parts.netloc,
                 f"gateway adapter {adapter_id}: the endpoint is https with no query, userinfo or fragment")
    auth_header = raw.get("auth_header")
    _require(auth_header is None or auth_header in AUTH_HEADERS, f"gateway adapter {adapter_id}: auth_header must be one of {AUTH_HEADERS}")
    secret_ref = raw.get("secret_ref")
    _require(secret_ref is None or (isinstance(secret_ref, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{1,127}", secret_ref) is not None),
             f"gateway adapter {adapter_id}: secret_ref must be an upper-case environment variable name")
    return AdapterSpec(adapter_id=adapter_id, family=family, provider=provider, model_id=model_id, model_version=str(version),
                       capabilities=tuple(capabilities), caps=caps, cost_units_per_call=cost, fake_rule=fake_rule,
                       endpoint=endpoint, auth_header=auth_header, secret_ref=secret_ref)


def _parse_gateway(raw: Mapping[str, Any], *, decisions: Mapping[str, Any], tutor: TutorPipelineParams) -> GatewayParams:
    """Package v4 gateway (Phase 5 spec 5.2). Every refusal is structural: an unpinned identifier always stops the load,
    and with it start-up (AC-5-10)."""
    from app.gateway.pinning import PIN_RULE
    from app.gateway.registry import REGISTRY_NAMES
    from app.gateway.retired import RETIRED_PROVIDER_SETTINGS

    gateway = _mapping(raw, "gateway")
    _require(gateway.get("provisional") is True, "gateway must be marked provisional: true (PD-22, PD-24, PD-26, PD-27)")
    pinning = _mapping(gateway, "pinning")
    _require(pinning.get("rule") == PIN_RULE, f"gateway.pinning.rule must be '{PIN_RULE}'")
    egress = _mapping(gateway, "egress")
    _require(egress.get("setting") == "MODEL_EGRESS_PROVIDERS" and egress.get("default") == [] and egress.get("provisional") is True,
             "gateway.egress names MODEL_EGRESS_PROVIDERS with default [] and is provisional (D-23, PD-22)")
    providers_open = (_bool_state(decisions, "D-12", ("open",)) or _bool_state(decisions, "D-07", ("open",))
                      or _bool_state(decisions, "Q-09", ("unresolved",)))
    for name in ("D-07", "Q-09", "D-23", "D-29", "D-25", "A-15", "Q-15"):
        _require(isinstance(decisions.get(name), dict), f"owner_decisions.{name} must be an object in package v4")
    registries_raw = _mapping(gateway, "registries")
    _require(set(registries_raw) <= set(REGISTRY_NAMES) and "default" in registries_raw,
             f"gateway.registries names only {', '.join(REGISTRY_NAMES)}, default included")
    registries: dict[str, tuple[Any, ...]] = {}
    seen: set[str] = set()
    for name, members in registries_raw.items():
        _require(isinstance(members, list), f"gateway.registries.{name} must be a list")
        if name != "development":
            _require(not (providers_open and members), f"gateway.registries.{name} must be empty while D-12, D-07 or Q-09 is open")
        specs = []
        for entry in members:
            spec = _parse_adapter(entry, name, providers_open=providers_open)
            _require(spec.adapter_id not in seen, f"gateway adapter {spec.adapter_id} is listed twice")
            seen.add(spec.adapter_id)
            if "verify" in spec.capabilities:
                _require(spec.caps.timeout_ms * (1 + spec.caps.max_retries) <= tutor.shadow_budget_ms,
                         f"gateway adapter {spec.adapter_id}: timeout_ms * (1 + max_retries) must fit tutor_pipeline.budgets.shadow_ms")
            specs.append(spec)
        registries[name] = tuple(specs)
    budgets = _mapping(gateway, "budgets")
    _require(budgets.get("provisional") is True, "gateway.budgets must be marked provisional: true (PD-26)")
    units_raw = _mapping(budgets, "daily_units")
    _require(set(units_raw) == set(registries_raw), "gateway.budgets.daily_units names every registry")
    daily_units = {name: _integer(units_raw, name, minimum=0) for name in units_raw}
    if _bool_state(decisions, "A-15", ("open",)):
        _require(all(units == 0 for name, units in daily_units.items() if name != "development"),
                 "gateway.budgets.daily_units outside development must be 0 while A-15 is open (hold H9)")
    share = _mapping(budgets, "alert_share")
    _require(share.get("numerator") == 4 and share.get("denominator") == 5, "gateway.budgets.alert_share must be 4/5 (plan Phase 5 I: alert at 80%)")
    cache = _mapping(gateway, "cache")
    _require(cache.get("provisional") is True and cache.get("scope") == "process", "gateway.cache is per process and provisional (PD-27)")
    bounds = _mapping(cache, "max_entries")
    policy = _mapping(gateway, "payload_policy")
    _require(policy.get("on_violation") == "stop", "gateway.payload_policy.on_violation must be 'stop' (plan Phase 5 L)")
    stop = _mapping(gateway, "stop")
    _require(sorted(stop.get("on") or []) == list(GATEWAY_STOPS), "gateway.stop.on must name budget_breach, payload_violation and secret_in_logs")
    retired = tuple(gateway.get("retired_settings") or ())
    _require(retired == RETIRED_PROVIDER_SETTINGS, "gateway.retired_settings must be the code's RETIRED_PROVIDER_SETTINGS")
    if _bool_state(decisions, "Q-09", ("unresolved",)):
        _require(gateway.get("terms", "missing") is None, "gateway.terms must be null while Q-09 is unresolved (no terms are recorded)")
    return GatewayParams(
        version=_text(gateway, "version"), registries=registries, pin_rule=PIN_RULE, egress_setting="MODEL_EGRESS_PROVIDERS",
        daily_units=daily_units, alert_share=(4, 5), cache_key_rule=_text(cache, "key_rule"),
        cache_max_plans=_integer_in(bounds, "claim_plan", 1, 100000), cache_max_verdicts=_integer_in(bounds, "verdict", 1, 100000),
        payload_rule=_text(policy, "rule"), stop_on=GATEWAY_STOPS, retired_settings=retired,
    )


def _parse_v2(raw: Mapping[str, Any], *, decisions: Mapping[str, Any], gateway: GatewayParams) -> V2Params:
    """Package v4 v2 (Phase 5 spec 5.2). Every refusal is structural."""
    from app.services.v2_panel.rules import BANNER_IDS, MAX_CORRECTION_CYCLES, MAX_MEMBERS, ROUTING_TABLE_VERSION, ROUTING_TABLES, matrix_from_package

    v2 = _mapping(raw, "v2")
    _require(v2.get("provisional") is True, "v2 must be marked provisional: true (PD-23, PD-25, PD-29, PD-30)")
    panel = _mapping(v2, "panel")
    _require(panel.get("max_members") == MAX_MEMBERS, f"v2.panel.max_members must be {MAX_MEMBERS} (E-81 N = 3)")
    families_raw = _mapping(v2, "generator_families")
    _require(set(WIRED_GENERATORS) <= set(families_raw), "v2.generator_families must name every wired generator")
    registered = {spec.family for specs in gateway.registries.values() for spec in specs}
    for generator, family in families_raw.items():
        _require(isinstance(family, str) and bool(family) and family not in registered,
                 f"v2.generator_families.{generator} names a family no registry member has")
    prompt = _mapping(v2, "prompt")
    tiers = _mapping(v2, "tiers")
    _require(tiers.get("provisional") is True, "v2.tiers must be marked provisional: true (PD-25)")
    _require(tiers.get("assessment_context") == 1, "v2.tiers.assessment_context must be 1")
    default_tier = _integer_in(tiers, "default", 1, 3)
    voting = _mapping(v2, "voting")
    _require(voting.get("provisional") is True, "v2.voting must be marked provisional: true (PD-23, PD-25)")
    version = _text(v2, "routing_table_version")
    _require(version in ROUTING_TABLES, "v2.routing_table_version names no routing table the code holds")
    if _bool_state(decisions, "D-29", ("open",)):
        _require(version == ROUTING_TABLE_VERSION, f"v2.routing_table_version must be '{ROUTING_TABLE_VERSION}' while D-29 is open (option (a), PD-23)")
    matrix_raw = _mapping(voting, "matrix")
    try:
        matrix = matrix_from_package(matrix_raw)
    except (TypeError, ValueError, AttributeError):
        matrix = None
    _require(matrix == ROUTING_TABLES[version], "v2.voting.matrix must be the routing table its routing_table_version names")
    threshold = _mapping(voting, "tier3_threshold")
    numerator, denominator = threshold.get("numerator"), threshold.get("denominator")
    _require(all(isinstance(value, int) and not isinstance(value, bool) for value in (numerator, denominator)) and 0 < numerator <= denominator,
             "v2.voting.tier3_threshold must hold integers with 0 < numerator <= denominator")
    correction = _mapping(v2, "correction")
    _require(correction.get("max_cycles") == MAX_CORRECTION_CYCLES, f"v2.correction.max_cycles must be {MAX_CORRECTION_CYCLES} (plan 5.8)")
    critical = tuple(correction.get("critical_registry") or ())
    if _bool_state(decisions, "D-25", ("open",)):
        _require(not critical, "v2.correction.critical_registry must be empty while D-25 is open (PD-29)")
    degraded = _mapping(v2, "degraded")
    _require(degraded.get("pre_verified_source", "missing") is None, "v2.degraded.pre_verified_source must be null: no pre-verified store exists (DI-83)")
    banners = _mapping(degraded, "banners")
    _require(tuple(sorted(banners)) == tuple(sorted(BANNER_IDS)) and all(isinstance(text, str) and text.strip() for text in banners.values()),
             "v2.degraded.banners must hold a text for each banner id")
    alignment = _mapping(v2, "alignment")
    return V2Params(
        version=_text(v2, "version"), max_members=MAX_MEMBERS, generator_families=dict(families_raw),
        verifier_prompt_id=_text(prompt, "verifier_prompt_id"), verifier_prompt_hash=_hex64(prompt, "verifier_prompt_hash"),
        alignment_prompt_id=_text(prompt, "alignment_prompt_id"), alignment_prompt_hash=_hex64(prompt, "alignment_prompt_hash"),
        tier_rule=_text(tiers, "rule"), assessment_tier=1, default_tier=default_tier, expert_mode=tiers.get("expert_mode"),
        matrix=matrix, tier3_threshold=(int(numerator), int(denominator)), panel_weights_version=_text(v2, "panel_weights_version"),
        routing_table_version=version, max_cycles=MAX_CORRECTION_CYCLES, critical_registry=critical, pre_verified_source=None,
        banners=dict(banners), alignment_rule=_text(alignment, "rule"),
    )


def _parse_tools(raw: Mapping[str, Any]) -> ToolParams:
    tools = _mapping(raw, "tools")
    _require(tools.get("version") == "mcp-tools-v1", "tools.version must be 'mcp-tools-v1'")
    _require(tuple(tools.get("servers") or ()) == TOOL_SERVERS, f"tools.servers must be {', '.join(TOOL_SERVERS)}")
    _require(tools.get("transport") == "in-process", "tools.transport must be 'in-process'")
    return ToolParams(version="mcp-tools-v1", transport="in-process", servers=TOOL_SERVERS,
                      path=_relative_path(tools.get("path"), "tools.path"), sha256=_hex64(tools, "sha256"))




def parse_config_package(raw: Any, *, path: Path, sha256: str, hash_verified: bool) -> ConfigPackage:
    _require(isinstance(raw, dict), "the file must hold a JSON object")
    _require(raw.get("package") == PACKAGE_NAME, f"'package' must be '{PACKAGE_NAME}'")
    schema_version = raw.get("schema_version")
    _require(schema_version in (1, 2, 3, 4) and not isinstance(schema_version, bool), "'schema_version' must be 1, 2, 3 or 4")
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
    v1_params: V1Params | None = None
    gateway_params: GatewayParams | None = None
    v2_params: V2Params | None = None
    tool_params: ToolParams | None = None
    if schema_version >= 2:
        supersedes = _mapping(raw, "supersedes")
        _text(supersedes, "package_version")
        _hex64(supersedes, "sha256")
        tutor_pipeline = _parse_tutor_pipeline(raw, schema_version=int(schema_version))
        flag_policy = _parse_flag_policy(raw, schema_version=int(schema_version))
        if schema_version >= 3:
            v1_params = _parse_v1(raw, tutor=tutor_pipeline)
            _v1_owner_decisions(decisions, v1_params)
            _q22_provisional_values(raw, decisions)
        if schema_version >= 4:
            gateway_params = _parse_gateway(raw, decisions=decisions, tutor=tutor_pipeline)
            v2_params = _parse_v2(raw, decisions=decisions, gateway=gateway_params)
            tool_params = _parse_tools(raw)
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
        v1=v1_params,
        gateway=gateway_params,
        v2=v2_params,
        tools=tool_params,
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
