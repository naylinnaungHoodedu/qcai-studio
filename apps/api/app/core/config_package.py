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
v1_pipeline flag policy. Next to
each file, <name>.json.sha256 holds the sha256 of its canonical JSON, so a CRLF checkout hashes the same. v2.json and
v1.json stay readable for one release (DI-63, DI-42).

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
    TWO_PASS_DEFAULT_DEVELOPMENT,
    TWO_PASS_DEFAULT_ELSEWHERE,
    V1_PIPELINE_DEFAULT_DEVELOPMENT,
    V1_PIPELINE_DEFAULT_ELSEWHERE,
    Settings,
)
from app.core.structured_logging import FIELDS

LOGGER = logging.getLogger("qcai.config_package")
PACKAGE_DIRECTORY = Path(__file__).resolve().parents[1] / "config_package"
DEFAULT_PACKAGE_PATH = PACKAGE_DIRECTORY / "v3.json"
# Readable for one release after the Phase 4 merge (DI-63) and the Phase 3 merge (DI-42); CI checks both with
# config_package.py --check --path.
V2_PACKAGE_PATH = PACKAGE_DIRECTORY / "v2.json"
V1_PACKAGE_PATH = PACKAGE_DIRECTORY / "v1.json"
PACKAGE_NAME = "qcai-configuration-package"
SPAN_SCHEME = "span-v2"
P1_FLOOR_VERSION = "score-floor-p1-v1"
P1_FLOOR = 6
# D-12 open: no provider generator is wired. Hold H6 blocks the provider interim path (a single pinned provider;
# PD-09) and stays held, so Phase 3 runs the D-19 extractive generator instead (PD-08), which sends no provider payload.
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
    names = TUTOR_SCHEMA_NAMES_V3 if schema_version >= 3 else TUTOR_SCHEMA_NAMES
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
    if schema_version >= 3:
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


def _parse_v1(raw: Mapping[str, Any], *, tutor: TutorPipelineParams, abstention: AbstentionParams) -> V1Params:
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
    x4 = {gate: _number(margin_raw, gate, minimum=0.0) for gate in GATE_IDS}
    _require(x4 == {"bm25f-v1": abstention.margin, "p1-floor": 0.0},
             "v1.v1_5.x4_margin must be the bm25f-v1 gate's abstention.margin and 0.0 for p1-floor (V1.5 maps the gate, spec conflict 19)")
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


def _parse_flag_policy(raw: Mapping[str, Any], *, schema_version: int = 2) -> FlagPolicy:
    policy = _mapping(raw, "flag_policy")
    if schema_version >= 3:
        _parse_v1_pipeline_policy(policy)
    # PD-10 names flag_policy as where its value lives; like every provisional block it says so (DI-37).
    _require(policy.get("provisional") is True, "flag_policy must be marked provisional: true (PD-10)")
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
    return FlagPolicy(phase4_exit_passed=passed, phase4_exit_evidence=evidence)


def parse_config_package(raw: Any, *, path: Path, sha256: str, hash_verified: bool) -> ConfigPackage:
    _require(isinstance(raw, dict), "the file must hold a JSON object")
    _require(raw.get("package") == PACKAGE_NAME, f"'package' must be '{PACKAGE_NAME}'")
    schema_version = raw.get("schema_version")
    _require(schema_version in (1, 2, 3) and not isinstance(schema_version, bool), "'schema_version' must be 1, 2 or 3")
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
    if schema_version >= 2:
        supersedes = _mapping(raw, "supersedes")
        _text(supersedes, "package_version")
        _hex64(supersedes, "sha256")
        tutor_pipeline = _parse_tutor_pipeline(raw, schema_version=int(schema_version))
        flag_policy = _parse_flag_policy(raw, schema_version=int(schema_version))
        if schema_version >= 3:
            v1_params = _parse_v1(raw, tutor=tutor_pipeline, abstention=abstention)
            _v1_owner_decisions(decisions, v1_params)
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
