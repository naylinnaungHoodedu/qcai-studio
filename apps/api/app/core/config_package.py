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
v1_pipeline flag policy. Version 4 (Phase 5, apps/api/app/config_package/v4.json) copies every v3 block, pins five more
schemas (LedgerEntryV3 and the four gateway request and verdict contracts) and adds the model gateway (`gateway`: the
adapter registry per environment, the pinning rule, the D-23 egress opt-in, budgets, the evidential cache, the payload
policy, the stop guards and the retired settings), the V2 panel (`v2`: families, tiers, the voting matrix, correction,
degraded modes, the alignment item), the tool contracts (`tools`) and the model_gateway flag policy. Version 5 (Phase 6,
apps/api/app/config_package/v5.json, the shipped package) copies every v4 block and adds the V3 audit (`v3`: the trigger
registry x-triggers-v1, the queue priority and its EHMF weights, the seeded audit draw, the adjudication workflow, the
gold store, the critical-claim registry per environment, the queue-age SLO and the stop, the residual statistic, the
reviewer gate and the two pinned V3 schemas), the v3_queue flag policy and the D-08, D-14 and D-18 owner decisions.
Next to each file, <name>.json.sha256 holds the sha256 of its canonical JSON, so a CRLF checkout hashes the same.
v4.json, v3.json, v2.json and v1.json stay readable for one release (DI-100, DI-84, DI-63, DI-42).

Start-up loads and validates it before any database work. A structural error always stops start-up; a hash
mismatch stops a governed build and is a logged warning in development. The loader never opens the calibration
record, which is not in the image, nor the schema files (tutor_pipeline.package_check verifies those).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
import logging
from pathlib import Path
import re
import threading
from typing import Any

from app.core.config import (
    EHMF_DEFAULT_DEVELOPMENT,
    EHMF_DEFAULT_ELSEWHERE,
    MODEL_GATEWAY_DEFAULT_DEVELOPMENT,
    MODEL_GATEWAY_DEFAULT_ELSEWHERE,
    TWO_PASS_DEFAULT_DEVELOPMENT,
    TWO_PASS_DEFAULT_ELSEWHERE,
    V1_PIPELINE_DEFAULT_DEVELOPMENT,
    V1_PIPELINE_DEFAULT_ELSEWHERE,
    V3_QUEUE_DEFAULT_DEVELOPMENT,
    V3_QUEUE_DEFAULT_ELSEWHERE,
    Settings,
)
from app.core.structured_logging import FIELDS

LOGGER = logging.getLogger("qcai.config_package")
PACKAGE_DIRECTORY = Path(__file__).resolve().parents[1] / "config_package"
DEFAULT_PACKAGE_PATH = PACKAGE_DIRECTORY / "v6.json"
# Package v5 stays readable for one release after the Phase 7 merge (DI-112; its own CI step).
V5_PACKAGE_PATH = PACKAGE_DIRECTORY / "v5.json"
# Readable for one release after the Phase 6 merge (DI-100), the Phase 5 merge (DI-84), the Phase 4 merge (DI-63) and
# the Phase 3 merge (DI-42); CI checks each with config_package.py --check --path.
V4_PACKAGE_PATH = PACKAGE_DIRECTORY / "v4.json"
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
# Package v6 (Phase 7): the EHMF record (ledger-entry-v4) and its schema.
TUTOR_SCHEMA_NAMES_V6 = (*TUTOR_SCHEMA_NAMES_V4, "LedgerEntryV4")
LEDGER_ENTRY_SCHEMAS_V6 = (*LEDGER_ENTRY_SCHEMAS_V4, "ledger-entry-v4")
V1_FAMILY_LIMIT = 20
# The plan's EHMF types per check (plan Phase 4 D table), which package v3 v1.ehmf must repeat.
from app.services.ehmf.vocabulary import PLAN_TYPES_BY_CHECK as V1_EHMF  # noqa: E402 - the one definition (Phase 7 spec 3.1)
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
    # Package v5: V3_QUEUE=on is refused outside development while this is false (plan Phase 6 L, P).
    phase6_exit_passed: bool = False
    phase6_exit_evidence: str | None = None
    # Package v6: EHMF=on is refused outside development while this is false (plan Phase 7 L, P).
    phase7_exit_passed: bool = False
    phase7_exit_evidence: str | None = None


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
    # Package v5 (Phase 6): the V3 audit and adjudication. None on a v1 to v4 package.
    v3: "V3Params | None" = None
    # Package v6 (Phase 7): the EHMF block (ehmf.*), None before v6.
    ehmf: "EhmfParams | None" = None


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
    names = (TUTOR_SCHEMA_NAMES_V6 if schema_version >= 6 else TUTOR_SCHEMA_NAMES_V4 if schema_version >= 4
             else TUTOR_SCHEMA_NAMES_V3 if schema_version >= 3 else TUTOR_SCHEMA_NAMES)
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
        # The list describes the package's entry schema (tutor_pipeline.ledger.entry_schema), as in v1 to v3: package v4's,
        # ledger-entry-v3, fills every provenance field (plan 7.4). A ledger-entry-v2 record written under v4 with
        # MODEL_GATEWAY off keeps the three Phase 5 fields null, as a v1 record under v3 kept v1_3_checker_model_id null.
        _require(unused == (), "tutor_pipeline.unused_provenance_fields must be empty in package v4 (its entry schema, ledger-entry-v3, fills every provenance field)")
        _require(ledger.get("legacy_entry_schema") == "ledger-entry-v1", "tutor_pipeline.ledger.legacy_entry_schema must be 'ledger-entry-v1'")
        expected = LEDGER_ENTRY_SCHEMAS_V6 if schema_version >= 6 else LEDGER_ENTRY_SCHEMAS_V4
        _require(ledger.get("entry_schemas") == list(expected), f"tutor_pipeline.ledger.entry_schemas must be [{', '.join(expected)}]")
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


def _parse_library_pin(raw: Any, *, path: Path | None) -> tuple[str, str, tuple[MisconceptionEntryParams, ...]]:
    """Package v6 v1.v1_8.library: the pin of the library v1 file (Phase 7 spec 3.5, 5.2). The file is resolved next to the
    loaded package file, so a copied package directory carries its own library; a package file copied alone (without a
    misconceptions/ folder beside it) reads the shipped library, which the pin's sha256 must still match. Its canonical
    sha256 must equal the pin and its sidecar, and it must keep every library rule (ehmf.library.library_problems). A
    missing or unreadable file is a structural error: start-up stops in every build (fail-closed)."""
    from app.services.ehmf.library import read_library_file
    from app.services.ehmf.vocabulary import LIBRARY_SCHEMA

    _require(isinstance(raw, dict), "v1.v1_8.library must be an object")
    relative = _relative_path(raw.get("path"), "v1.v1_8.library.path")
    _require(raw.get("schema") == LIBRARY_SCHEMA, f"v1.v1_8.library.schema must be '{LIBRARY_SCHEMA}'")
    version = _text(raw, "version")
    pin = _hex64(raw, "sha256")
    _require(path is not None, "v1.v1_8.library is a file pin: the package must be loaded from a file")
    target = Path(path).resolve().parent / relative
    if not target.parent.is_dir():
        target = PACKAGE_DIRECTORY / relative
    shipped = target.resolve().parent == (DEFAULT_PACKAGE_PATH.parent / "misconceptions").resolve()
    library, problems = read_library_file(target, expected_sha256=pin, shipped=shipped)
    _require(library is not None, "v1.v1_8.library: " + "; ".join(problems))
    _require(library.version == version, "v1.v1_8.library.version must be the library file's version")
    return version, pin, tuple(MisconceptionEntryParams(entry_id=entry_id, terms=terms) for entry_id, terms in library.entries)


def _parse_v1(raw: Mapping[str, Any], *, tutor: TutorPipelineParams, schema_version: int = 5, path: Path | None = None) -> V1Params:
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
    if schema_version >= 6:
        library_version, library_sha256, entries = _parse_library_pin(v1_8.get("library"), path=path)
    else:
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
    if schema_version < 5:
        return FlagPolicy(phase4_exit_passed=passed, phase4_exit_evidence=evidence, phase5_exit_passed=passed5, phase5_exit_evidence=evidence5)
    _require(all(name in str(policy.get("authority")) for name in ("PD-38", "DI-98")),
             "flag_policy.authority must name PD-38 (DI-98): it holds the v3_queue defaults")
    queue = _mapping(policy, "v3_queue")
    _require(queue.get("values") == ["off", "shadow", "on"], "flag_policy.v3_queue.values must be [off, shadow, on]")
    _require(queue.get("default_development") == V3_QUEUE_DEFAULT_DEVELOPMENT,
             f"flag_policy.v3_queue.default_development must be the code's default ({V3_QUEUE_DEFAULT_DEVELOPMENT!r})")
    _require(queue.get("default_elsewhere") == V3_QUEUE_DEFAULT_ELSEWHERE,
             f"flag_policy.v3_queue.default_elsewhere must be the code's default ({V3_QUEUE_DEFAULT_ELSEWHERE!r})")
    _require(queue.get("on_requires") == "phase6_exit_passed", "flag_policy.v3_queue.on_requires must be 'phase6_exit_passed'")
    _require(queue.get("disable") == "releases_nothing", "flag_policy.v3_queue.disable must be 'releases_nothing' (plan Phase 6 L)")
    passed6 = policy.get("phase6_exit_passed")
    _require(isinstance(passed6, bool), "flag_policy.phase6_exit_passed must be a boolean")
    evidence6 = policy.get("phase6_exit_evidence")
    if passed6:
        _require(isinstance(evidence6, str) and bool(evidence6.strip()), "flag_policy.phase6_exit_passed true needs a phase6_exit_evidence string")
    else:
        _require(evidence6 is None or isinstance(evidence6, str), "flag_policy.phase6_exit_evidence must be null or a string")
    if schema_version < 6:
        return FlagPolicy(phase4_exit_passed=passed, phase4_exit_evidence=evidence, phase5_exit_passed=passed5, phase5_exit_evidence=evidence5,
                          phase6_exit_passed=passed6, phase6_exit_evidence=evidence6)
    _require(all(name in str(policy.get("authority")) for name in ("PD-48", "DI-109")),
             "flag_policy.authority must name PD-48 (DI-109): it holds the ehmf defaults")
    ehmf = _mapping(policy, "ehmf")
    _require(ehmf.get("values") == ["off", "shadow", "on"], "flag_policy.ehmf.values must be [off, shadow, on]")
    _require(ehmf.get("default_development") == EHMF_DEFAULT_DEVELOPMENT,
             f"flag_policy.ehmf.default_development must be the code's default ({EHMF_DEFAULT_DEVELOPMENT!r})")
    _require(ehmf.get("default_elsewhere") == EHMF_DEFAULT_ELSEWHERE,
             f"flag_policy.ehmf.default_elsewhere must be the code's default ({EHMF_DEFAULT_ELSEWHERE!r})")
    _require(ehmf.get("on_requires") == "phase7_exit_passed" and ehmf.get("requires") == "model_gateway_not_off",
             "flag_policy.ehmf.on_requires must be 'phase7_exit_passed' and requires 'model_gateway_not_off'")
    passed7 = policy.get("phase7_exit_passed")
    _require(isinstance(passed7, bool), "flag_policy.phase7_exit_passed must be a boolean")
    evidence7 = policy.get("phase7_exit_evidence")
    if passed7:
        _require(isinstance(evidence7, str) and bool(evidence7.strip()), "flag_policy.phase7_exit_passed true needs a phase7_exit_evidence string")
    else:
        _require(evidence7 is None or isinstance(evidence7, str), "flag_policy.phase7_exit_evidence must be null or a string")
    return FlagPolicy(phase4_exit_passed=passed, phase4_exit_evidence=evidence, phase5_exit_passed=passed5, phase5_exit_evidence=evidence5,
                      phase6_exit_passed=passed6, phase6_exit_evidence=evidence6, phase7_exit_passed=passed7, phase7_exit_evidence=evidence7)


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
    # Where the daily budget, the stop and the evidential cache live: "database", shared by every instance
    # (app.gateway.controls, v2_panel.cache.DatabaseEvidentialCache; plan 5.7, 5.10, L, 7.5).
    budget_scope: str = "database"
    stop_scope: str = "database"
    cache_scope: str = "database"
    # The embedding egress's parameters (gateway.embeddings, app.gateway.registry.EmbeddingSpec; PD-26).
    embeddings: Any = None


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
        _require(not providers_open, f"gateway adapter {adapter_id}: no non-fake provider is registered while D-12, D-07 or Q-09 is open "
                                     "or the Q-15 payload review is pending")
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


def _parse_embeddings(gateway: Mapping[str, Any], *, providers_open: bool) -> Any:
    """Package v4 gateway.embeddings (Phase 5 spec 4.19, 5.2; PD-26): the embedding egress's model, caps and cost. A
    model is named only as a pinned pair, and an unpinned one stops the load and with it start-up (AC-5-10); none is
    named while D-12, D-07 or Q-09 is open or the Q-15 review is pending."""
    from app.gateway.embeddings import EMBEDDINGS_PROVIDER, EMBEDDINGS_SECRET_REF
    from app.gateway.pinning import pin_problem
    from app.gateway.registry import EMBEDDING_MAX_INPUT_CHARS, EMBEDDING_MAX_ITEMS, MAX_RETRIES, TIMEOUT_MS, EmbeddingCaps, EmbeddingSpec

    raw = _mapping(gateway, "embeddings")
    _require(raw.get("provisional") is True and raw.get("record") == "PD-26", "gateway.embeddings must be marked provisional: true, record PD-26")
    _require(raw.get("provider") == EMBEDDINGS_PROVIDER and raw.get("secret_ref") == EMBEDDINGS_SECRET_REF,
             f"gateway.embeddings names provider {EMBEDDINGS_PROVIDER} and secret_ref {EMBEDDINGS_SECRET_REF}")
    _require("model_id" in raw and "model_version" in raw, "gateway.embeddings names model_id and model_version (null when no model is chosen)")
    model_id, version = raw["model_id"], raw["model_version"]
    if model_id is not None or version is not None:
        _require(isinstance(model_id, str) and bool(model_id.strip()), "gateway.embeddings.model_id must be a non-empty string or null")
        problem = pin_problem(model_id, version if isinstance(version, str) else None)
        _require(problem is None, f"gateway.embeddings is {problem} (AC-5-10; D-07 option (a), PD-24)")
        _require(not providers_open, "gateway.embeddings names no model while D-12, D-07 or Q-09 is open or the Q-15 payload review is pending")
    caps = _mapping(raw, "caps")
    return EmbeddingSpec(
        provider=EMBEDDINGS_PROVIDER, secret_ref=EMBEDDINGS_SECRET_REF, model_id=model_id, model_version=version,
        caps=EmbeddingCaps(max_items=_integer_in(caps, "max_items", *EMBEDDING_MAX_ITEMS),
                           max_input_chars=_integer_in(caps, "max_input_chars", *EMBEDDING_MAX_INPUT_CHARS),
                           timeout_ms=_integer_in(caps, "timeout_ms", *TIMEOUT_MS), max_retries=_integer_in(caps, "max_retries", *MAX_RETRIES)),
        cost_units_per_item=_integer(raw, "cost_units_per_item", minimum=1),
    )


def _parse_gateway(raw: Mapping[str, Any], *, decisions: Mapping[str, Any], tutor: TutorPipelineParams) -> GatewayParams:
    """Package v4 gateway (Phase 5 spec 5.2). Every refusal is structural: an unpinned identifier always stops the load,
    and with it start-up (AC-5-10)."""
    from app.gateway.pinning import PIN_RULE, PINNED_VERSION_TEXT, REFUSED_TOKENS_TEXT, REFUSED_WITHIN_TOKEN_TEXT
    from app.gateway.registry import REGISTRY_NAMES
    from app.gateway.registry import providers_open as gates_open
    from app.gateway.retired import RETIRED_PROVIDER_SETTINGS

    gateway = _mapping(raw, "gateway")
    _require(gateway.get("provisional") is True, "gateway must be marked provisional: true (PD-22, PD-24, PD-26, PD-27)")
    pinning = _mapping(gateway, "pinning")
    _require(pinning.get("rule") == PIN_RULE, f"gateway.pinning.rule must be '{PIN_RULE}'")
    for name, code in (("refused_tokens", REFUSED_TOKENS_TEXT), ("refused_within_token", REFUSED_WITHIN_TOKEN_TEXT),
                       ("version_pattern", PINNED_VERSION_TEXT)):
        _require(pinning.get(name) == code, f"gateway.pinning.{name} must be the code's pinning rule text (pinned-version-v1)")
    egress = _mapping(gateway, "egress")
    _require(egress.get("setting") == "MODEL_EGRESS_PROVIDERS" and egress.get("default") == [] and egress.get("provisional") is True,
             "gateway.egress names MODEL_EGRESS_PROVIDERS with default [] and is provisional (D-23, PD-22)")
    # One rule for every non-fake member and the embedding egress (app.gateway.registry.providers_open).
    providers_open = gates_open(decisions)
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
            _require(not (providers_open and members),
                     f"gateway.registries.{name} must be empty while D-12, D-07 or Q-09 is open or the Q-15 payload review is pending")
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
    _require(budgets.get("scope") == "database",
             "gateway.budgets.scope must be 'database': every instance spends from one daily budget (plan Phase 5 task 5.10, a hard stop)")
    cache = _mapping(gateway, "cache")
    _require(cache.get("provisional") is True and cache.get("scope") == "database",
             "gateway.cache is shared through the application database and provisional (plan 5.7, 7.5; PD-27)")
    bounds = _mapping(cache, "max_entries")
    policy = _mapping(gateway, "payload_policy")
    _require(policy.get("on_violation") == "stop", "gateway.payload_policy.on_violation must be 'stop' (plan Phase 5 L)")
    stop = _mapping(gateway, "stop")
    _require(sorted(stop.get("on") or []) == list(GATEWAY_STOPS), "gateway.stop.on must name budget_breach, payload_violation and secret_in_logs")
    _require(stop.get("scope") == "database" and stop.get("clear") == "operator",
             "gateway.stop is shared through the application database and cleared by an operator only (plan Phase 5 L; PD-28)")
    retired = tuple(gateway.get("retired_settings") or ())
    _require(retired == RETIRED_PROVIDER_SETTINGS, "gateway.retired_settings must be the code's RETIRED_PROVIDER_SETTINGS")
    if _bool_state(decisions, "Q-09", ("unresolved",)):
        _require(gateway.get("terms", "missing") is None, "gateway.terms must be null while Q-09 is unresolved (no terms are recorded)")
    return GatewayParams(
        version=_text(gateway, "version"), registries=registries, pin_rule=PIN_RULE, egress_setting="MODEL_EGRESS_PROVIDERS",
        daily_units=daily_units, alert_share=(4, 5), cache_key_rule=_text(cache, "key_rule"),
        cache_max_plans=_integer_in(bounds, "claim_plan", 1, 100000), cache_max_verdicts=_integer_in(bounds, "verdict", 1, 100000),
        payload_rule=_text(policy, "rule"), stop_on=GATEWAY_STOPS, retired_settings=retired,
        budget_scope="database", stop_scope="database", cache_scope="database",
        embeddings=_parse_embeddings(gateway, providers_open=providers_open),
    )


def _parse_v2(raw: Mapping[str, Any], *, decisions: Mapping[str, Any], gateway: GatewayParams) -> V2Params:
    """Package v4 v2 (Phase 5 spec 5.2). Every refusal is structural."""
    from app.services.v2_panel.rules import (
        BANNER_IDS,
        CORRECTION_RULES,
        MAX_CORRECTION_CYCLES,
        MAX_MEMBERS,
        ROUTING_TABLE_VERSION,
        ROUTING_TABLES,
        TIER3_THRESHOLD,
        matrix_from_package,
    )

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
    if _bool_state(decisions, "Q-22", ("unresolved",)):
        # The record rule re-tallies every recorded claim with this value (PD-25), so the package cannot hold another.
        _require((numerator, denominator) == TIER3_THRESHOLD,
                 f"v2.voting.tier3_threshold must be {TIER3_THRESHOLD[0]}/{TIER3_THRESHOLD[1]} while Q-22 is unresolved (PD-25)")
    correction = _mapping(v2, "correction")
    _require(correction.get("provisional") is True, "v2.correction must be marked provisional: true (PD-29)")
    _require(correction.get("max_cycles") == MAX_CORRECTION_CYCLES, f"v2.correction.max_cycles must be {MAX_CORRECTION_CYCLES} (plan 5.8)")
    for name, rule in CORRECTION_RULES.items():
        _require(correction.get(name) == rule, f"v2.correction.{name} must be '{rule}', the code's correction rule (plan 5.8)")
    critical = tuple(correction.get("critical_registry") or ())
    if _bool_state(decisions, "D-25", ("open",)):
        _require(not critical, "v2.correction.critical_registry must be empty while D-25 is open (PD-29)")
    degraded = _mapping(v2, "degraded")
    _require(degraded.get("provisional") is True, "v2.degraded must be marked provisional: true (PD-30)")
    _require(degraded.get("pre_verified_source", "missing") is None, "v2.degraded.pre_verified_source must be null: no pre-verified store exists (DI-83)")
    banners = _mapping(degraded, "banners")
    _require(tuple(sorted(banners)) == tuple(sorted(BANNER_IDS)) and all(isinstance(text, str) and text.strip() for text in banners.values()),
             "v2.degraded.banners must hold a text for each banner id")
    alignment = _mapping(v2, "alignment")
    _require(alignment.get("provisional") is True, "v2.alignment must be marked provisional: true (PD-25)")
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
    # Plan 7.4: "tool names are UNVERIFIED / REQUIRES ACCESS [Assumption A-18]": the names and the transport are this
    # phase's own (PD-31; the paper's names are DI-86).
    _require(tools.get("provisional") is True, "tools must be marked provisional: true (A-18: the tool names are UNVERIFIED; PD-31)")
    _require(tools.get("version") == "mcp-tools-v1", "tools.version must be 'mcp-tools-v1'")
    _require(tuple(tools.get("servers") or ()) == TOOL_SERVERS, f"tools.servers must be {', '.join(TOOL_SERVERS)}")
    _require(tools.get("transport") == "in-process", "tools.transport must be 'in-process'")
    return ToolParams(version="mcp-tools-v1", transport="in-process", servers=TOOL_SERVERS,
                      path=_relative_path(tools.get("path"), "tools.path"), sha256=_hex64(tools, "sha256"))


# ------------------------------------------------------------------------------------------------ package v5 (Phase 6)

V3_CRITICAL_REGISTRIES = ("development", "staging", "production", "default")
V3_PROVISIONAL_BLOCKS = ("triggers", "priority", "draw", "workflow", "critical_claims", "slo", "reviewers")
V3_BLIND_TO = ("finals", "other_rounds", "votes", "objection_types", "support_share", "severity", "priority")
V3_RESIDUAL = {"statistic": "wilson95_upper", "population": "x6_audited_answer_deliveries", "period": "utc_month", "report_only": True}
V3_OWNER_DECISIONS = ("D-06", "D-08", "D-14", "D-18", "D-25")
V3_SEED = r"^[a-z0-9][a-z0-9-]{0,63}$"


@dataclass(frozen=True)
class V3Params:
    """Package v5 v3 (Phase 6 spec 5.1, 5.2): the V3 audit's parameters, provisional (PD-32 to PD-39, DI-98). Rates and
    weights are exact Fractions, so no float takes part in a draw or an ordering."""

    version: str
    trigger_registry_version: str
    trigger_rules: Mapping[str, str]
    counted: tuple[str, ...]
    queue_reasons: tuple[str, ...]
    x1_tiers: tuple[int, ...]
    x1_withhold_tier: int
    x2_types: tuple[str, ...] | None          # x-triggers-v1 (v5): (A, B); x-triggers-v2 (v6): None, every X2 escalation
    x5_rate: Fraction
    x5_window_deliveries: int
    severity: Mapping[str, Fraction]
    priority_rule: str
    exposure_rule: str
    claim_set_key_rule: str
    k_rule: str
    tie_break: tuple[str, ...]
    draw_rule: str
    draw_seed: str
    draw_rate: Fraction
    population: tuple[str, ...]
    lease_s: int
    double_review_rate: Fraction
    max_rounds: int
    gold_chain: str
    gold_schema: str
    gold_record_hash_rule: str
    critical_registries: Mapping[str, tuple[str, ...]]
    critical_fixture: str
    queue_age_slo_s: int
    stop_measure: str
    stop_window_s: int
    stop_sample_s: int
    stop_refresh_s: int
    stop_tier1: str
    escalation_share_max: Fraction
    window_days: int
    reviewer_pool: str
    schemas: Mapping[str, SchemaPin]

    def critical_registry_for(self, environment: str) -> tuple[str, ...]:
        """The critical-claim registry of an environment: its own when the package names it, else default."""
        name = environment.lower()
        return tuple(self.critical_registries.get(name, self.critical_registries["default"]))


def _fraction(raw: Mapping[str, Any], key: str) -> Fraction:
    value = _mapping(raw, key)
    numerator, denominator = value.get("numerator"), value.get("denominator")
    _require(all(isinstance(item, int) and not isinstance(item, bool) for item in (numerator, denominator)) and 0 <= numerator <= denominator
             and denominator > 0, f"'{key}' must hold integers with 0 <= numerator <= denominator")
    return Fraction(numerator, denominator)


def _parse_v3(raw: Mapping[str, Any], *, decisions: Mapping[str, Any], v2: "V2Params | None", schema_version: int = 5,
              ehmf_weights: Mapping[str, Fraction] | None = None) -> V3Params:
    """Package v5 v3 (Phase 6 spec 5.2). Every refusal is structural: a package that names other trigger rules, weights,
    rates or a non-empty registry outside development never loads."""
    from app.services.tutor_pipeline.contracts import CLAIM_ID
    from app.services.v3.contracts import V3_SCHEMA_MODELS
    from app.services.v3.rules import (
        CLAIM_SET_KEY_RULE,
        DRAW_RULE,
        EXPOSURE_RULE,
        GOLD_CHAIN,
        GOLD_RECORD_HASH_RULE,
        GOLD_SCHEMA,
        K_RULE,
        MAX_ROUNDS,
        PRIORITY_RULE,
        QUEUE_REASONS,
        REVIEWER_ROLE,
        TIE_BREAK,
        TRIGGER_REGISTRY_VERSION,
        TRIGGER_REGISTRY_VERSION_V2,
        TRIGGER_RULES,
        TRIGGER_RULES_V2,
        V3_COUNTED,
        V3_VERSION,
        WORKFLOW_STATES,
        X1_TIERS,
        X1_WITHHOLD_TIER,
        X2_TYPES,
    )

    for name in V3_OWNER_DECISIONS:
        _require(isinstance(decisions.get(name), dict), f"owner_decisions.{name} must be an object in package v5")
    d06_open = _bool_state(decisions, "D-06", ("open",))
    d18_open = _bool_state(decisions, "D-18", ("open",))
    d25_open = _bool_state(decisions, "D-25", ("open",))
    v3 = _mapping(raw, "v3")
    _require(v3.get("provisional") is True, "v3 must be marked provisional: true (PD-32 to PD-39; DI-98)")
    for name in V3_PROVISIONAL_BLOCKS:
        _require(_mapping(v3, name).get("provisional") is True, f"v3.{name} must be marked provisional: true")
    _require(v3.get("version") == V3_VERSION, f"v3.version must be '{V3_VERSION}'")

    from app.services.ehmf.vocabulary import EHMF_TYPES, PLAN_WEIGHTS

    triggers = _mapping(v3, "triggers")
    registry_version, registry_rules = ((TRIGGER_REGISTRY_VERSION_V2, TRIGGER_RULES_V2) if schema_version >= 6
                                        else (TRIGGER_REGISTRY_VERSION, TRIGGER_RULES))
    _require(triggers.get("version") == registry_version and triggers.get("rules") == registry_rules,
             f"v3.triggers must be the code's trigger registry {registry_version} and its rules")
    x1 = _mapping(triggers, "x1")
    _require(x1 == {"tiers": list(X1_TIERS), "min_objections": 1, "withhold_tier": X1_WITHHOLD_TIER, "withholds": True, "revision": "never",
                    "hold": "sticky_for_the_response"},
             "v3.triggers.x1 must fire at tiers [1, 2, 3] with min_objections 1 (AC-5-4: critical claims follow X1) and withhold at tier 1:"
             " withhold_tier 1, withholds true, revision never, hold sticky_for_the_response (task 1 \"withheld at tier 1\"; AC-6-1)")
    if schema_version >= 6:
        # Phase 7 spec conflict 3 (PD-44): X2 fires on every X2 escalation the correction engine emits (AC-7-5).
        _require(_mapping(triggers, "x2") == {"fires_on": "every_x2_escalation", "emitted_by": "ehmf.correction"},
                 "v3.triggers.x2 must fire on every_x2_escalation emitted by ehmf.correction (x-triggers-v2; AC-7-5)")
        x2_types: tuple[str, ...] | None = None
    else:
        _require(_mapping(triggers, "x2").get("ehmf_types") == list(X2_TYPES), "v3.triggers.x2.ehmf_types must be [A, B] (plan task 1 \"Type A/B\")")
        x2_types = X2_TYPES
    _require(_mapping(triggers, "x4").get("margin_source") == "v1.v1_5.x4_margin", "v3.triggers.x4.margin_source must be v1.v1_5.x4_margin")
    x5 = _mapping(triggers, "x5")
    x5_rate = _fraction(x5, "audit_rate")
    _require(x5_rate == Fraction(1, 5), "v3.triggers.x5.audit_rate must be 1/5 (plan task 1 \"audit 20%\")")
    window = _integer_in(x5, "window_deliveries", 1, 1_000_000)
    _require(x5.get("sources") == ["cusum_alarm", "model_change"], "v3.triggers.x5.sources must be [cusum_alarm, model_change]")
    counted = tuple(triggers.get("counted") or ())
    if d06_open:
        _require(counted == V3_COUNTED, "v3.triggers.counted must be X1-X4 while D-06 is open (plan 15.3; PD-37)")
    _require(set(counted) <= set(TRIGGER_RULES), "v3.triggers.counted names a trigger the registry does not hold")
    _require(tuple(triggers.get("queue_reasons") or ()) == QUEUE_REASONS, "v3.triggers.queue_reasons must be the code's queue reasons")

    priority = _mapping(v3, "priority")
    for key, code in (("rule", PRIORITY_RULE), ("exposure_rule", EXPOSURE_RULE), ("claim_set_key_rule", CLAIM_SET_KEY_RULE), ("k_rule", K_RULE)):
        _require(priority.get(key) == code, f"v3.priority.{key} must be '{code}'")
    weights = _mapping(priority, "severity")
    if schema_version >= 6:
        # Package v6: V3 severity is built from ehmf.weights (A-E, disclosed_conflict = D_disclosed; PD-41).
        _require(dict(weights) == {"source": "ehmf.weights", "unknown": 1.0},
                 "v3.priority.severity must be {source: ehmf.weights, unknown: 1.0} in package v6")
        _require(ehmf_weights is not None, "v3.priority.severity reads ehmf.weights, which the package lacks")
        weights = {**{key: ehmf_weights[key] for key in EHMF_TYPES}, "unknown": ehmf_weights["unknown"],
                   "disclosed_conflict": ehmf_weights["D_disclosed"]}
    _require(set(weights) == {*EHMF_TYPES, "unknown", "disclosed_conflict"},
             "v3.priority.severity must name A-E, unknown and disclosed_conflict")
    severity: dict[str, Fraction] = {}
    for key, value in weights.items():
        _require(isinstance(value, (int, float, Fraction)) and not isinstance(value, bool) and 0 <= value <= 1, f"v3.priority.severity.{key} must be in [0, 1]")
        severity[key] = value if isinstance(value, Fraction) else Fraction(str(value))
    if d06_open:
        _require(all(severity[key] == Fraction(PLAN_WEIGHTS[key]) for key in EHMF_TYPES),
                 "v3.priority.severity must hold the plan's 6.3 weights while D-06 is open (PD-34)")
        _require(severity["disclosed_conflict"] == 0, "v3.priority.severity.disclosed_conflict must be 0 while D-06 is open (plan Phase 7 A)")
    _require(tuple(priority.get("tie_break") or ()) == TIE_BREAK, "v3.priority.tie_break must be [enqueued_at, item_id]")

    draw = _mapping(v3, "draw")
    _require(draw.get("rule") == DRAW_RULE, f"v3.draw.rule must be '{DRAW_RULE}'")
    seed = draw.get("seed")
    _require(isinstance(seed, str) and re.fullmatch(V3_SEED, seed) is not None, f"v3.draw.seed must match {V3_SEED}")
    draw_rate = _fraction(draw, "rate")
    _require(draw_rate == Fraction(1, 20), "v3.draw.rate must be 1/20 (plan 6.3 \"X6 = 5%\")")
    _require(draw.get("population") == ["delivered", "legacy"], "v3.draw.population must be [delivered, legacy]")

    workflow = _mapping(v3, "workflow")
    _require(tuple(workflow.get("states") or ()) == WORKFLOW_STATES, "v3.workflow.states must be queued, claimed, adjudicated, applied")
    lease_s = _integer_in(workflow, "lease_s", 60, 86400)
    double = _mapping(workflow, "double_review")
    double_rate = _fraction(double, "rate")
    if d06_open:
        _require(double_rate == Fraction(1, 10), "v3.workflow.double_review.rate must be 1/10 while D-06 is open (plan task 3; PD-36)")
    _require(double.get("rule") == DRAW_RULE, f"v3.workflow.double_review.rule must be '{DRAW_RULE}'")
    _require(workflow.get("max_rounds") == MAX_ROUNDS, f"v3.workflow.max_rounds must be {MAX_ROUNDS}")
    for key, value in (("self_review", "refused"), ("apply_by", "another_reviewer"), ("independence", "user_keyed_round_records"),
                       ("unreviewable", "stays_queued"), ("applies_to_ledger", False), ("releases_withheld", False),
                       ("recalibration", "phase7_change_control")):
        _require(workflow.get(key) == value, f"v3.workflow.{key} must be {value!r} (PD-36)")
    blind = workflow.get("blind_to")
    _require(isinstance(blind, list) and set(V3_BLIND_TO) <= set(blind), f"v3.workflow.blind_to must name {', '.join(V3_BLIND_TO)}")

    gold = _mapping(v3, "gold_store")
    _require(gold.get("chain") == GOLD_CHAIN and gold.get("schema") == GOLD_SCHEMA and gold.get("record_hash_rule") == GOLD_RECORD_HASH_RULE,
             "v3.gold_store must name the code's chain, schema and record-hash rule")
    _require(gold.get("append_only") is True and gold.get("restore") == "none", "v3.gold_store is append_only with restore none")

    critical = _mapping(v3, "critical_claims")
    registries_raw = _mapping(critical, "registries")
    _require(tuple(sorted(registries_raw)) == tuple(sorted(V3_CRITICAL_REGISTRIES)),
             f"v3.critical_claims.registries must name {', '.join(V3_CRITICAL_REGISTRIES)}")
    registries: dict[str, tuple[str, ...]] = {}
    for name in V3_CRITICAL_REGISTRIES:
        registry = _mapping(registries_raw, name)
        entries = registry.get("claims")
        _require(isinstance(entries, list), f"v3.critical_claims.registries.{name}.claims must be a list")
        ids = []
        for entry in entries:
            _require(isinstance(entry, dict) and isinstance(entry.get("claim_id"), str) and re.fullmatch(CLAIM_ID, entry["claim_id"]) is not None,
                     f"v3.critical_claims.registries.{name}: every entry names a claim id")
            index = entry.get("query_index")
            _require(isinstance(index, int) and not isinstance(index, bool) and index >= 0,
                     f"v3.critical_claims.registries.{name}: every entry names its fixture query_index")
            ids.append(entry["claim_id"])
        _require(len(ids) == len(set(ids)), f"v3.critical_claims.registries.{name} lists a claim twice")
        if name != "development" and d25_open:
            _require(not ids, f"v3.critical_claims.registries.{name} must be empty while D-25 is open (PD-33)")
        if name == "development" and ids:
            _require(registry.get("synthetic") is True, "v3.critical_claims.registries.development must be marked synthetic: true (PD-33)")
        registries[name] = tuple(ids)
    fixture = _relative_path(critical.get("fixture"), "v3.critical_claims.fixture")
    if v2 is not None:
        _require(not v2.critical_registry, "v2.correction.critical_registry must be empty in package v5: v3.critical_claims supersedes it")

    slo = _mapping(v3, "slo")
    queue_age_slo_s = _integer_in(slo, "queue_age_slo_s", 3600, 2_592_000)
    _require(slo.get("stop_measure") == "oldest_open_item_age" and slo.get("alert_measure") == "queue_age_p90",
             "v3.slo.stop_measure must be oldest_open_item_age and alert_measure queue_age_p90 (PD-37)")
    stop_window_s = _integer_in(slo, "stop_window_s", 1, 10**9)
    _require(stop_window_s == 172800, "v3.slo.stop_window_s must be 172800 (plan Phase 6 L \"for two days\")")
    stop_sample_s = _integer_in(slo, "stop_sample_s", 60, 86400)
    _require(stop_window_s % stop_sample_s == 0, "v3.slo.stop_sample_s must divide the stop window")
    _require(slo.get("stop_tier1") == "pre_verified_only", "v3.slo.stop_tier1 must be pre_verified_only (plan Phase 6 L)")
    stop_refresh_s = _integer_in(slo, "stop_refresh_s", 1, 3600)
    _require(slo.get("unreadable") == "stop", "v3.slo.unreadable must be 'stop'")
    share = _fraction(slo, "escalation_share_max")
    _require(share == Fraction(1, 10), "v3.slo.escalation_share_max must be 1/10 (plan Phase 6 I \"V-3 <= 10%\")")
    window_days = _integer_in(slo, "window_days", 1, 90)
    _require(slo.get("report_only") is True, "v3.slo.report_only must be true (plan 13.7)")

    residual = _mapping(v3, "residual")
    _require(dict(residual) == V3_RESIDUAL, "v3.residual must be the Wilson 95% upper bound over X6-audited answer deliveries per UTC month")

    reviewers = _mapping(v3, "reviewers")
    _require(reviewers.get("role") == REVIEWER_ROLE, f"v3.reviewers.role must be '{REVIEWER_ROLE}'")
    _require(reviewers.get("flag_intake") == "development_only", "v3.reviewers.flag_intake must be development_only while the D-05 freeze holds")
    pool = reviewers.get("pool")
    _require(isinstance(pool, str) and bool(pool), "v3.reviewers.pool must be a string")
    if d18_open:
        _require(pool == "unstaffed" and reviewers.get("outside_development") == "refused_while_d18_open",
                 "v3.reviewers.pool must be unstaffed and outside_development refused_while_d18_open while D-18 is open (PD-38)")

    schemas_raw = _mapping(v3, "schemas")
    _require(set(schemas_raw) == set(V3_SCHEMA_MODELS), f"v3.schemas must name exactly {', '.join(sorted(V3_SCHEMA_MODELS))}")
    schemas = {}
    for name in sorted(V3_SCHEMA_MODELS):
        pin = _mapping(schemas_raw, name)
        schemas[name] = SchemaPin(version=_text(pin, "version"), path=_schema_path(pin.get("path"), name), sha256=_hex64(pin, "sha256"))
    return V3Params(
        version=V3_VERSION, trigger_registry_version=registry_version, trigger_rules=dict(registry_rules), counted=counted,
        queue_reasons=QUEUE_REASONS, x1_tiers=X1_TIERS, x1_withhold_tier=X1_WITHHOLD_TIER, x2_types=x2_types, x5_rate=x5_rate, x5_window_deliveries=window, severity=severity,
        priority_rule=PRIORITY_RULE, exposure_rule=EXPOSURE_RULE, claim_set_key_rule=CLAIM_SET_KEY_RULE, k_rule=K_RULE, tie_break=TIE_BREAK,
        draw_rule=DRAW_RULE, draw_seed=seed, draw_rate=draw_rate, population=("delivered", "legacy"), lease_s=lease_s,
        double_review_rate=double_rate, max_rounds=MAX_ROUNDS, gold_chain=GOLD_CHAIN, gold_schema=GOLD_SCHEMA,
        gold_record_hash_rule=GOLD_RECORD_HASH_RULE, critical_registries=registries, critical_fixture=fixture,
        queue_age_slo_s=queue_age_slo_s, stop_measure="oldest_open_item_age", stop_window_s=stop_window_s, stop_sample_s=stop_sample_s,
        stop_refresh_s=stop_refresh_s, stop_tier1="pre_verified_only", escalation_share_max=share, window_days=window_days,
        reviewer_pool=pool, schemas=schemas,
    )




# ------------------------------------------------------------------------------------------------ package v6 (Phase 7)

EHMF_OWNER_DECISIONS = ("EHMF-WEIGHTS", "D-16", "Q-11", "EHMF-SOURCE-METADATA")
EHMF_PROVISIONAL_BLOCKS = ("routing", "weights", "conflicts", "correction", "retrieval_penalty", "stop")
EHMF_PENALTY_REGISTRIES = ("default", "development", "production", "staging")
EHMF_CONFLICT_RULES = ["newer_peer_reviewed_over_older", "primary_over_secondary"]
EHMF_METADATA_FIELDS = ["source_year", "peer_reviewed", "source_role"]
EHMF_DISCLOSURE_TEXT = ("These course sources disagree ({kinds}) between {items}. Both passages are shown; neither is preferred unless a "
                        "precedence basis is named: {basis}.")
_GOLD_SOURCE = re.compile(r"^(v3:[0-9a-f]{64}|synthetic)$")


@dataclass(frozen=True)
class EhmfParams:
    """Package v6 ehmf (Phase 7 spec 5.1, 5.2): the EHMF parameters, provisional (PD-40 to PD-49, DI-109). Weights,
    factors and the rise are exact Fractions."""

    version: str
    routing_version: str
    routing_sha256: str
    routing_table: Mapping[str, Any]
    weights: Mapping[str, Fraction]
    precedence: str
    disclosure_template_id: str
    disclosure_template_text: str
    disclosure_template_sha256: str
    max_cycles: int
    penalty_registries: Mapping[str, tuple[Fraction, Mapping[str, Fraction]]]
    stop_window_claims: int
    stop_min_claims: int
    stop_min_ab: int
    stop_rise: Fraction
    stop_scan_records: int
    stop_refresh_s: int
    golden_set_path: str
    golden_set_sha256: str
    golden_set_items: int
    library_paraphrase_max_chars: int
    library_paraphrase_max_shared_words: int

    def penalties_for(self, environment: str) -> Mapping[str, Fraction]:
        """span id -> factor of an environment's registry (its own when the package names it, else default)."""
        name = environment.lower()
        factor, spans = self.penalty_registries.get(name, self.penalty_registries["default"])
        return {span_id: factor for span_id in spans}

    def penalty_factor(self, environment: str) -> Fraction:
        return self.penalty_registries.get(environment.lower(), self.penalty_registries["default"])[0]

    def weight(self, name: str) -> Fraction:
        from app.services.ehmf.vocabulary import TYPE_OF

        return self.weights[TYPE_OF.get(name, name)]

    def weight_strings(self) -> dict[str, str]:
        return {key: str(self.weights[key]) for key in ("A", "B", "C", "D", "D_disclosed", "E")}


def disclosure_template_sha256(template_id: str, text: str) -> str:
    return canonical_sha256({"id": template_id, "text": text})


def _penalty_factor(raw: Mapping[str, Any], name: str) -> Fraction:
    value = raw.get("factor")
    _require(isinstance(value, dict) and all(isinstance(value.get(key), int) and not isinstance(value.get(key), bool)
                                             for key in ("numerator", "denominator")), f"ehmf.retrieval_penalty.registries.{name}.factor is a fraction")
    numerator, denominator = value["numerator"], value["denominator"]
    _require(0 < numerator <= denominator, f"ehmf.retrieval_penalty.registries.{name}.factor must be in (0, 1]")
    return Fraction(numerator, denominator)


def _parse_ehmf(raw: Mapping[str, Any], *, decisions: Mapping[str, Any], v2: "V2Params | None", package_version: str) -> EhmfParams:
    """Package v6 ehmf (Phase 7 spec 5.2). Every refusal is structural: a package whose routing table, weights, rules,
    bounds or registries differ from what the code and the plan fix never loads."""
    from app.services.ehmf.routing import routing_sha256, routing_table
    from app.services.ehmf.vocabulary import (
        DISCLOSURE_TEMPLATE,
        EHMF_FIRST_MAJOR,
        EHMF_TYPES,
        EHMF_VERSION,
        GOLDEN_SET_VERSION,
        MITIGATIONS,
        PENALTY_RULE,
        PLAN_WEIGHTS,
        PRE_PHASE_7,
        PRECEDENCE_RULE,
        ROUTING_VERSION,
        STOP_RULE,
        SUBTYPES,
    )

    for name in EHMF_OWNER_DECISIONS:
        _require(isinstance(decisions.get(name), dict), f"owner_decisions.{name} must be an object in package v6")
    weights_open = _bool_state(decisions, "EHMF-WEIGHTS", ("open",))
    d06_open = _bool_state(decisions, "D-06", ("open",))
    ehmf = _mapping(raw, "ehmf")
    _require(ehmf.get("provisional") is True, "ehmf must be marked provisional: true (PD-40 to PD-49; DI-109)")
    for name in EHMF_PROVISIONAL_BLOCKS:
        _require(_mapping(ehmf, name).get("provisional") is True, f"ehmf.{name} must be marked provisional: true")
    _require(ehmf.get("version") == EHMF_VERSION, f"ehmf.version must be '{EHMF_VERSION}'")
    _require(ehmf.get("types") == list(EHMF_TYPES), "ehmf.types must be [A, B, C, D, E] (plan E-87)")
    _require(ehmf.get("subtypes") == {key: list(value) for key, value in SUBTYPES.items()}, "ehmf.subtypes must be {B: [B1, B2]}")

    routing = _mapping(ehmf, "routing")
    _require(routing.get("version") == ROUTING_VERSION, f"ehmf.routing.version must be '{ROUTING_VERSION}'")
    _require(routing.get("table") == routing_table(), "ehmf.routing.table must be the code's routing table (ehmf.routing.routing_table)")
    _require(routing.get("sha256") == routing_sha256(), "ehmf.routing.sha256 must be the routing table's canonical sha256")

    weights_raw = _mapping(ehmf, "weights")
    keys = {"A", "B", "C", "D", "D_disclosed", "E", "unknown"}
    values = {key: value for key, value in weights_raw.items() if key in keys}
    _require(set(values) == keys, "ehmf.weights must name A, B, C, D, D_disclosed, E and unknown")
    weights: dict[str, Fraction] = {}
    for key, value in values.items():
        _require(isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 1, f"ehmf.weights.{key} must be in [0, 1]")
        weights[key] = Fraction(str(value))
    if weights_open:
        _require(all(weights[key] == Fraction(PLAN_WEIGHTS[key]) for key in EHMF_TYPES),
                 "ehmf.weights must hold the plan's 6.3 weights while EHMF-WEIGHTS is open (PD-41)")
    _require(weights["D_disclosed"] == 0, "ehmf.weights.D_disclosed must be 0 (plan Phase 7 A \"D 0.6 (0 when disclosed)\")")
    _require(weights["unknown"] == 1, "ehmf.weights.unknown must be 1")

    conflicts = _mapping(ehmf, "conflicts")
    _require(conflicts.get("precedence") == PRECEDENCE_RULE and conflicts.get("applies") == "recorded_only",
             f"ehmf.conflicts.precedence must be '{PRECEDENCE_RULE}', applied recorded_only (spec conflict 24)")
    _require(conflicts.get("rules") == EHMF_CONFLICT_RULES and conflicts.get("metadata_fields") == EHMF_METADATA_FIELDS,
             "ehmf.conflicts.rules and metadata_fields must be the code's")
    for key, value in (("incomplete_metadata", "no_winner_disclose_both"), ("rules_disagree", "no_winner_disclose_both"),
                       ("undisclosed", "v1_7_fail"), ("outside_corpus", "not_detected")):
        _require(conflicts.get(key) == value, f"ehmf.conflicts.{key} must be '{value}'")
    template = _mapping(conflicts, "disclosure_template")
    _require(template.get("id") == DISCLOSURE_TEMPLATE, f"ehmf.conflicts.disclosure_template.id must be '{DISCLOSURE_TEMPLATE}'")
    template_text = _text(template, "text")
    _require(template_text == EHMF_DISCLOSURE_TEXT, "ehmf.conflicts.disclosure_template.text must be the code's template")
    template_sha = _hex64(template, "sha256")
    _require(template_sha == disclosure_template_sha256(DISCLOSURE_TEMPLATE, template_text),
             "ehmf.conflicts.disclosure_template.sha256 does not match its text")

    library = _mapping(ehmf, "library")
    _require(library.get("pin") == "v1.v1_8.library" and library.get("editors") == ["content_owner", "v3"]
             and library.get("v3_proposals") == "exported_never_applied",
             "ehmf.library must pin v1.v1_8.library, name the editors content_owner and v3, and export V3 proposals never applied")
    max_chars = _integer_in(library, "paraphrase_max_chars", 1, 2000)
    max_shared = _integer_in(library, "paraphrase_max_shared_words", 1, 100)

    correction = _mapping(ehmf, "correction")
    _require(correction.get("max_cycles_source") == "v2.correction.max_cycles", "ehmf.correction.max_cycles_source must be v2.correction.max_cycles")
    _require(v2 is not None and v2.max_cycles == 2, "v2.correction.max_cycles must be 2 (plan Phase 7 D task 4 \"at most two cycles\")")
    for key, value in (("third_cycle", "refused"), ("exhausted", "abstain_emit_x2_every_claim"), ("type_e", "re_render_keep_claim_and_span_sets"),
                       ("set_changed", "refuse_abstain_response")):
        _require(correction.get(key) == value, f"ehmf.correction.{key} must be '{value}'")
    _require(correction.get("mitigations") == MITIGATIONS, "ehmf.correction.mitigations must be the plan's mitigations (plan task 1)")

    penalty = _mapping(ehmf, "retrieval_penalty")
    _require(penalty.get("rule") == PENALTY_RULE and penalty.get("applies_to") == "ranking_only" and penalty.get("applies_when") == "ehmf_on",
             f"ehmf.retrieval_penalty must be rule '{PENALTY_RULE}', ranking_only, applied only when EHMF is on")
    registries_raw = _mapping(penalty, "registries")
    _require(tuple(sorted(registries_raw)) == EHMF_PENALTY_REGISTRIES,
             "ehmf.retrieval_penalty.registries must name development, staging, production and default")
    registries: dict[str, tuple[Fraction, Mapping[str, Fraction]]] = {}
    for name in EHMF_PENALTY_REGISTRIES:
        registry = _mapping(registries_raw, name)
        factor = _penalty_factor(registry, name)
        spans_raw = registry.get("spans")
        _require(isinstance(spans_raw, list), f"ehmf.retrieval_penalty.registries.{name}.spans must be a list")
        spans: dict[str, Fraction] = {}
        for entry in spans_raw:
            _require(isinstance(entry, dict) and set(entry) == {"span_id", "reason", "gold"}
                     and isinstance(entry.get("span_id"), str) and re.fullmatch(r"span-[0-9a-f]{64}", entry["span_id"]) is not None
                     and entry.get("reason") in ("B2", "D") and isinstance(entry.get("gold"), str) and _GOLD_SOURCE.match(entry["gold"]) is not None,
                     f"ehmf.retrieval_penalty.registries.{name}: every span names its span_id, reason B2 or D and its gold source")
            _require(entry["gold"] != "synthetic" or name == "development",
                     f"ehmf.retrieval_penalty.registries.{name}: a synthetic span is development only")
            spans[entry["span_id"]] = factor
        if name != "development" and d06_open:
            _require(factor == 1 and not spans, f"ehmf.retrieval_penalty.registries.{name} must have factor 1/1 and no span while D-06 is open (PD-45)")
        registries[name] = (factor, spans)

    stop = _mapping(ehmf, "stop")
    _require(stop.get("rule") == STOP_RULE, f"ehmf.stop.rule must be '{STOP_RULE}'")
    window_claims = _integer_in(stop, "window_claims", 1, 100_000)
    min_claims = _integer_in(stop, "min_claims", 1, 100_000)
    min_ab = _integer_in(stop, "min_ab_findings", 1, 100_000)
    scan_records = _integer_in(stop, "scan_records", 1, 100_000)
    _require(min_claims <= window_claims, "ehmf.stop.min_claims must be at most window_claims")
    _require(scan_records >= 2 * window_claims, "ehmf.stop.scan_records must be at least twice window_claims")
    rise_raw = _mapping(stop, "rise")
    numerator, denominator = rise_raw.get("numerator"), rise_raw.get("denominator")
    _require(all(isinstance(item, int) and not isinstance(item, bool) for item in (numerator, denominator)) and denominator > 0
             and numerator > denominator, "ehmf.stop.rise must be a fraction above 1")
    _require(stop.get("audit_rate_source") == "v3.triggers.x5.audit_rate" and stop.get("window_deliveries_source") == "v3.triggers.x5.window_deliveries",
             "ehmf.stop reads its audit rate and window from v3.triggers.x5 (plan Phase 7 L \"sets audit to 20%\")")
    _require(stop.get("revert") == "operator_reloads_prior_package", "ehmf.stop.revert must be operator_reloads_prior_package (D-05)")
    refresh_s = _integer_in(stop, "refresh_s", 1, 3600)

    golden = _mapping(ehmf, "golden_set")
    _require(golden.get("version") == GOLDEN_SET_VERSION, f"ehmf.golden_set.version must be '{GOLDEN_SET_VERSION}'")
    golden_path = _relative_path(golden.get("path"), "ehmf.golden_set.path")
    golden_sha = _hex64(golden, "sha256")
    golden_items = _integer_in(golden, "items", 1, 100_000)
    _relative_path(golden.get("run_record"), "ehmf.golden_set.run_record")
    _require(golden.get("drift") == "blocks_promotion", "ehmf.golden_set.drift must be blocks_promotion (plan 12.5)")

    config_version = _mapping(ehmf, "config_version")
    _require(config_version.get("earlier") == PRE_PHASE_7 and config_version.get("first_package") == f"{EHMF_FIRST_MAJOR}.0.0"
             and config_version.get("rule") == "package-version-v1",
             f"ehmf.config_version must name rule package-version-v1, earlier '{PRE_PHASE_7}' and first_package '{EHMF_FIRST_MAJOR}.0.0' (plan G)")
    try:
        major = int(package_version.split(".")[0])
    except ValueError:
        major = 0
    _require(major >= EHMF_FIRST_MAJOR, f"a package with an ehmf block has a package_version of major {EHMF_FIRST_MAJOR} or later")
    return EhmfParams(
        version=EHMF_VERSION, routing_version=ROUTING_VERSION, routing_sha256=routing["sha256"], routing_table=routing["table"],
        weights=weights, precedence=PRECEDENCE_RULE, disclosure_template_id=DISCLOSURE_TEMPLATE, disclosure_template_text=template_text,
        disclosure_template_sha256=template_sha, max_cycles=v2.max_cycles, penalty_registries=registries,
        stop_window_claims=window_claims, stop_min_claims=min_claims, stop_min_ab=min_ab, stop_rise=Fraction(numerator, denominator),
        stop_scan_records=scan_records, stop_refresh_s=refresh_s, golden_set_path=golden_path, golden_set_sha256=golden_sha,
        golden_set_items=golden_items, library_paraphrase_max_chars=max_chars, library_paraphrase_max_shared_words=max_shared,
    )


def parse_config_package(raw: Any, *, path: Path, sha256: str, hash_verified: bool) -> ConfigPackage:
    _require(isinstance(raw, dict), "the file must hold a JSON object")
    _require(raw.get("package") == PACKAGE_NAME, f"'package' must be '{PACKAGE_NAME}'")
    schema_version = raw.get("schema_version")
    _require(schema_version in (1, 2, 3, 4, 5, 6) and not isinstance(schema_version, bool), "'schema_version' must be 1, 2, 3, 4, 5 or 6")
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
    v3_params: V3Params | None = None
    ehmf_params: "EhmfParams | None" = None
    if schema_version >= 2:
        supersedes = _mapping(raw, "supersedes")
        _text(supersedes, "package_version")
        _hex64(supersedes, "sha256")
        tutor_pipeline = _parse_tutor_pipeline(raw, schema_version=int(schema_version))
        flag_policy = _parse_flag_policy(raw, schema_version=int(schema_version))
        if schema_version >= 3:
            v1_params = _parse_v1(raw, tutor=tutor_pipeline, schema_version=int(schema_version), path=path)
            _v1_owner_decisions(decisions, v1_params)
            _q22_provisional_values(raw, decisions)
        if schema_version >= 4:
            gateway_params = _parse_gateway(raw, decisions=decisions, tutor=tutor_pipeline)
            v2_params = _parse_v2(raw, decisions=decisions, gateway=gateway_params)
            tool_params = _parse_tools(raw)
        if schema_version >= 6:
            ehmf_params = _parse_ehmf(raw, decisions=decisions, v2=v2_params, package_version=package_version)
        if schema_version >= 5:
            v3_params = _parse_v3(raw, decisions=decisions, v2=v2_params, schema_version=int(schema_version),
                                  ehmf_weights=ehmf_params.weights if ehmf_params is not None else None)
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
        v3=v3_params,
        ehmf=ehmf_params,
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
