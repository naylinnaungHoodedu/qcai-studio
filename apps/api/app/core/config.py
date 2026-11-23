from datetime import datetime
import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


SOURCE_DOCUMENT_NAMES = [
    "Quantum Computing AI Research Synthesis 2026.docx",
    "Analyzing Quantum Computing and AI Paper 2025.docx",
    "Quantum Computing and Artificial Intelligence Industry Use Cases.docx",
    "Module2_Routing, Graph Shrinking, and Logistics under Hardware Constraints.docx",
    "Module3_Quantum Vision, GNN, and Few-Shot Hybrid Architectures.docx",
    "Module4_Expressive Bottlenecks Compression, Language, and Explanation.docx",
    "Module6_From Algorithmic Novelty to Sustainable Hybrid Systems.docx",
    "Introduction_to_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.docx",
    "Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence_Models.docx",
    "Intermediate_Quantum_Programming_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.docx",
    "Advanced_Programming_and_Software_Development_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.docx",
    "Quantum_Finance_Programming_and_Optimization_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.docx",
]

SOURCE_VIDEO_NAMES = [
    "Quantum Computing and Artificial Intelligence 2025.mp4",
    "Quantum Computing and Artificial Intelligence 2026.mp4",
    "Industry Use Cases.mp4",
    "Module2_Routing, Graph Shrinking, and Logistics under Hardware Constraints.mp4",
    "Module3_Quantum Vision, GNN, and Few-Shot Hybrid Architectures.mp4",
    "Module4_Expressive Bottlenecks Compression, Language, and Explanation.mp4",
    "Module6_From Algorithmic Novelty to Sustainable Hybrid Systems.mp4",
    "Introduction_to_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4",
    "The Hardware-First Imperative in Quantum Machine LearningHardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence_Models.mp4",
    "Intermediate_Quantum_Programming_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4",
    "Advanced_Programming_and_Software_Development_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4",
    "Quantum_Finance_Programming_and_Optimization_for_Hardware-Constrained_Learning_for_Quantum_Computing_and_Artificial_Intelligence.mp4",
]
SQLITE_URL_PREFIX = "sqlite:///"
# Signs guest tokens in development and tests only; every other environment must set GUEST_TOKEN_SECRET.
# The frontend's guest-session.ts falls back to the same value outside production.
DEVELOPMENT_GUEST_TOKEN_SECRET = "qcai-development-only-guest-token-secret"
API_ROOT = Path(__file__).resolve().parents[2]


def normalize_sqlite_database_url(database_url: str) -> str:
    if not database_url.startswith(SQLITE_URL_PREFIX):
        return database_url

    sqlite_path = database_url[len(SQLITE_URL_PREFIX) :]
    if sqlite_path in {"", ":memory:"}:
        return database_url
    if sqlite_path.startswith("/") or (len(sqlite_path) >= 2 and sqlite_path[1] == ":"):
        return database_url

    normalized_path = (API_ROOT / sqlite_path).resolve()
    return f"{SQLITE_URL_PREFIX}{normalized_path.as_posix()}"

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "QC+AI Learning API"
    # The commit the running image was built from (Dockerfile ARG GIT_SHA); "unknown" outside a built image.
    git_sha: str = "unknown"
    environment: str = "development"
    site_url: str | None = None
    database_url: str = "sqlite:///./qcai_dev.db"
    enable_demo_auth: bool | None = None
    cloud_sql_connection_name: str | None = None
    cloud_sql_ip_type: str = "PUBLIC"
    # No provider setting exists. The Phase 2 semantic backend's embedding model, its pinned version, caps and cost are
    # package v4's gateway.embeddings (app.gateway.embeddings; Phase 5 spec 4.19), and its key, OPENAI_API_KEY, is no
    # setting: the gateway's secret store reads it from the process environment per call (plan 7.1: the gateway is the
    # sole holder of provider credentials). The retired chat-provider settings (app.gateway.retired.
    # RETIRED_PROVIDER_SETTINGS) are ignored and named at start-up; OPENAI_EMBEDDING_MODEL and
    # OPENAI_EMBEDDING_MODEL_VERSION are no settings either (Settings ignore unknown keys).
    auth0_domain: str | None = None
    auth0_audience: str | None = None
    pinecone_api_key: str | None = None
    pinecone_index: str | None = None
    pinecone_namespace: str = "qcai-course"
    pinecone_upsert_batch_size: int = 32
    auth_register_rate_limit: str = "5/minute"
    auth_login_rate_limit: str = "10/minute"
    qa_ask_rate_limit: str = "5/minute"
    assistant_chat_rate_limit: str = "8/minute"
    search_rate_limit: str = "10/minute"
    support_request_rate_limit: str = "5/hour"
    public_web_vitals_rate_limit: str = "120/minute"
    # Rate-limit counters (task 1.6, Decision P1-D-06): "database" shares them across API instances; "memory"
    # keeps them per process, the rollback.
    rate_limit_storage: Literal["database", "memory"] = "database"
    # How many X-Forwarded-For entries, counted from the right, the platform's own front end appends.
    client_address_hops: int = Field(default=1, ge=1, le=5)
    # Sign-in lockout: this many failed sign-ins for one email within the window lock it for the rest of it.
    auth_lockout_failures: int = Field(default=5, ge=1)
    auth_lockout_window_seconds: int = Field(default=900, ge=60)
    api_base_url: str | None = None
    source_assets_root: str | None = None
    corpus_manifest_path: str | None = None
    enforce_corpus_governance: bool | None = None
    grounding_policy_version: str = "cs595-v1"
    arena_enabled: bool | None = None
    arena_ticket_rate_limit: str = "10/minute"
    guest_token_secret: str | None = None
    guest_token_previous_secret: str | None = None
    # Legacy guest-id migration window (plan L1108-1110): closed unless an end time is set.
    guest_legacy_upgrade_until: datetime | None = None
    guest_legacy_upgrade_rate_limit: str = "5/hour"
    allowed_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:3000"])
    # Phase 2 (corpus, span identity, retrieval integrity). Every learner-visible change defaults to today's
    # behaviour outside development while the D-05 freeze holds (Phase 2 spec section 7).
    # The configuration package v1 (app/config_package/v1.json) unless a test names another one.
    config_package_path: str | None = None
    # "p1-floor": the approved P1-D-04 floor over the span index (today's results); "bm25f-v1": the Phase 2 BM25F
    # gate with the provisional calibrated floor and margin. None = bm25f-v1 in development, p1-floor elsewhere;
    # switching production is a D-05 remediation release (R-15) and logs a config.override event.
    retrieval_gate: Literal["p1-floor", "bm25f-v1"] | None = None
    # Phase 2 spec conflict 29 (plan Phase 2 L stop): outside development, a build that indexes document spans under
    # the p1-floor gate loses in-domain recall@5, so start-up and validate_corpus --check-recall-stop refuse it.
    # Setting this lets it start anyway (an owner decision); it logs a config.override event.
    allow_p1_floor_with_documents: bool = False
    # Task 2.5: the semantic backend stays off, whatever keys are set, until its vector ids are span ids. It embeds only
    # through the gateway, which also needs the D-23 opt-in (openai-embeddings in MODEL_EGRESS_PROVIDERS, PD-22), closed
    # provider decisions (D-07, D-12, Q-09) and the Q-15 payload review, a pinned embedding model and a budget (Phase 5
    # spec 4.19), and it runs only in a process that has aligned the index (sync_semantic_index); /ready reports the
    # effective state.
    semantic_retrieval_enabled: bool = False
    # GET /spans/{span_id}: None = on in development, off elsewhere (it is a new public route under the freeze).
    span_resolver_route_enabled: bool | None = None
    # Plan G "provisional marker lifted for resolved citations": off until AC-2-3 is green in a cited CI run and
    # D-05 approves; enabling it outside development logs a config.override event.
    citation_provisional_lift_enabled: bool = False
    # Kill switch for the one new request-path write: cited span identity (no text) into corpus_spans.
    span_registry_write_through: bool = True
    # Start-up manifest drift check (D11): "fast" hashes documents and the authored item and checks videos by
    # size or LFS pointer; "full" also hashes video content.
    manifest_drift_check: Literal["off", "fast", "full"] = "fast"
    spans_rate_limit: str = "30/minute"
    # Phase 3 (provenance-first two-channel tutor; docs/architecture/phase3-implementation-spec.md section 6). Every
    # learner-visible change keeps today's behaviour outside development while the D-05 freeze holds.
    # Plan Phase 3 G: "two_pass_tutor MUST run shadow-only until the Phase 4 exit; zero outputs reach learners".
    # None = "shadow" in development, "off" elsewhere (TWO_PASS_DEFAULT_DEVELOPMENT, TWO_PASS_DEFAULT_ELSEWHERE, which
    # the configuration package's flag_policy must name: the loader refuses a package that says otherwise, spec 18.8
    # F4). "on" is refused while the package says flag_policy.phase4_exit_passed is false (AC-3-6); "shadow" outside
    # development logs a config.override event.
    two_pass_tutor: Literal["off", "shadow", "on"] | None = None
    # How long a shadow run may hold its worker after the response is sent (E1 "bounded budget"). None = the
    # configuration package's tutor_pipeline.budgets.shadow_ms (2000; PD-11); set only to override it.
    two_pass_shadow_budget_ms: int | None = Field(default=None, ge=100, le=30000)
    # (Either budget override, when set outside development, logs a config.override event and is stamped on every
    # ledger record it applies to: versions.budgets.)
    # Kill switch for the response-ledger write of every tutor delivery (not learner-visible; plan 3.8, R-22).
    # Disabling it outside development relaxes an audit control and logs a config.override event.
    tutor_ledger_enabled: bool = True
    # Total deadline of the synchronous legacy ledger append (spec conflict 29); also each PostgreSQL attempt's
    # lock_timeout and statement_timeout. The learner waits at most this plus the package's ledger_wait_grace_ms
    # (250), pool checkout included; an append still running then finishes in the background and is counted.
    # None = the configuration package's tutor_pipeline.budgets.ledger_append_ms (1500; PD-11); set only to override.
    tutor_ledger_append_budget_ms: int | None = Field(default=None, ge=100, le=5000)
    # GET /ledger/responses/{response_id}: None = on in development, off elsewhere (a new route under the freeze).
    ledger_route_enabled: bool | None = None
    # The evidence panel field on tutor and Q&A responses (task 3.8): None = on in development, off elsewhere (E9). It
    # is also the legacy guard's disclosure_shown (Phase 4 spec 4.15, AC-4-6): off, the guard withholds a contained
    # answer whose quotations V1.7 finds in conflict (today's abstention); on, the panel labels the conflict when the
    # package's conflict policy (v1.v1_7.on_conflict) is disclose, and the thread, Q&A-history and ledger reads label it
    # again on the stored answer. Under the policy withhold the guard withholds it whatever this setting says.
    evidence_panel_enabled: bool | None = None
    # Rate limit of the new Phase 3 ledger route: an engineering parameter with no plan value, provisional (PD-11; it
    # copies the existing spans_rate_limit), ratified with the rest of PD-11 (DI-37). POST /tutor/turns has no limit of
    # its own: it shares POST /assistant/chat's window and assistant_chat_rate_limit (scope "tutor-turn"), so
    # alternating the two routes never doubles a client's tutor-turn budget. Unknown environment keys are ignored
    # (extra="ignore").
    ledger_rate_limit: str = "30/minute"
    # Phase 4 (V1 deterministic validation; docs/architecture/phase4-implementation-spec.md section 6). Plan Phase 4 G:
    # "flag v1_pipeline shadows the legacy gate, logging disagreements, then enforces". It acts on the two-pass shadow
    # pipeline only, so no learner sees a change. None = "enforce" in development and "shadow" elsewhere
    # (V1_PIPELINE_DEFAULT_DEVELOPMENT, V1_PIPELINE_DEFAULT_ELSEWHERE, which package v3 flag_policy.v1_pipeline must
    # name). "off" is refused outside development (plan 13.6: no flag may disable V1); "enforce" is refused outside
    # development while the package says flag_policy.phase4_exit_passed is false. The legacy guard on every delivery
    # path has no flag: V1.1 and V1.2 always, and V1.7 whenever no evidence panel shows the conflict
    # (EVIDENCE_PANEL_ENABLED off) or the package's conflict policy (v1.v1_7.on_conflict) is withhold.
    v1_pipeline: Literal["off", "shadow", "enforce"] | None = None
    # Phase 5 (provider-neutral gateway and V2; docs/architecture/phase5-implementation-spec.md section 6). Plan Phase 5 G:
    # "One release of shadow dual-run, then flag cutover"; L: "Flag off returns to Phase 4". It acts on the two-pass
    # shadow pipeline only, so no learner sees a change. None = "shadow" in development and "off" elsewhere
    # (MODEL_GATEWAY_DEFAULT_DEVELOPMENT, MODEL_GATEWAY_DEFAULT_ELSEWHERE, which package v4 flag_policy.model_gateway
    # must name). "on" needs V1_PIPELINE=enforce, and outside development is refused while the package says
    # flag_policy.phase5_exit_passed is false. A runtime stop of the gateway turns the effective mode off for the rest
    # of the process's life: an operator clears the registry's shared stop (python -m app.workers.gateway_stop --clear)
    # and replaces the stopped instances (a new revision), whose new processes start open.
    model_gateway: Literal["off", "shadow", "on"] | None = None
    # D-23 (PD-22): the providers this environment opts in to model egress, a comma or JSON list. Empty everywhere,
    # development included: the development fakes need none, and no non-fake provider is registered anywhere.
    model_egress_providers: Annotated[list[str], NoDecode] = Field(default_factory=list)
    # Plan 13.6 "kill switches per provider": these adapter ids are never eligible (strictly more conservative).
    model_gateway_disabled_adapters: Annotated[list[str], NoDecode] = Field(default_factory=list)
    # Plan 13.6 "abstain-only, pre-verified-only": either makes every adapter ineligible, so V2 makes no call and every
    # claim is in ZERO; under MODEL_GATEWAY=on the record abstains and queues every claim V2 withheld (pre-verified-only
    # abstains too while no pre-verified source exists, DI-83). Like MODEL_GATEWAY it acts on the two-pass shadow
    # pipeline only: no delivered answer reads it (strictly more conservative; delivery is DI-85).
    model_gateway_kill_switch: Literal["none", "abstain_only", "pre_verified_only"] = "none"
    # Phase 6 (V3 audit and adjudication; docs/architecture/phase6-implementation-spec.md section 6). Plan Phase 6 L:
    # "Disabling V3 MUST NOT release withheld items." None = "shadow" in development and "off" elsewhere
    # (V3_QUEUE_DEFAULT_DEVELOPMENT, V3_QUEUE_DEFAULT_ELSEWHERE, which package v5 flag_policy.v3_queue must name). Off
    # runs no scan, no draw, no item and no flag intake: the flag route answers an authenticated caller 404, and the
    # reviewer routes answer 404 to an admitted reviewer (development) after their role and pool checks, which refuse
    # every other authenticated caller with 403 (outside development every authenticated caller while D-18 is open; a
    # caller without a credential gets 401 first where demo auth is off); the holds and the stop are
    # computed from the records and the stored queue whatever it says, so switching it off releases nothing. "on" is
    # refused outside development while the package says flag_policy.phase6_exit_passed is false, and runs as shadow:
    # nothing in Phase 6 reaches a learner (DI-97). Shadow outside development is a recorded override that changes no
    # learner path: the flag route stays 404 there and no reviewer is admitted while D-18 is open (PD-38).
    v3_queue: Literal["off", "shadow", "on"] | None = None
    # The learner flag route's rate limit (POST /v3/flags, development only): an engineering parameter like PD-11's
    # limits, provisional with PD-38 (DI-98).
    v3_flag_rate_limit: str = "10/minute"

    @field_validator("model_egress_providers", "model_gateway_disabled_adapters", mode="before")
    @classmethod
    def parse_name_list(cls, value: Any) -> Any:
        if isinstance(value, str):
            raw_value = value.strip()
            if not raw_value:
                return []
            if raw_value.startswith("["):
                try:
                    parsed = json.loads(raw_value)
                except ValueError as exc:
                    raise ValueError("the list is not valid JSON") from exc
                if not isinstance(parsed, list):
                    raise ValueError("the list is not a JSON list")
                return [str(item).strip() for item in parsed if str(item).strip()]
            return [item.strip() for item in raw_value.split(",") if item.strip()]
        return value

    @field_validator("model_egress_providers", "model_gateway_disabled_adapters")
    @classmethod
    def check_names(cls, value: list[str]) -> list[str]:
        import re

        for item in value:
            if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", item):
                raise ValueError(f"{item!r} is not a provider or adapter name ([a-z0-9][a-z0-9-]{{0,63}})")
        return value

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def parse_allowed_origins(cls, value: Any) -> Any:
        if isinstance(value, str):
            raw_value = value.strip()
            if not raw_value:
                return ["http://localhost:3000"]
            if raw_value.startswith("["):
                try:
                    parsed = json.loads(raw_value)
                except ValueError:
                    parsed = None
                if isinstance(parsed, list):
                    return [item for item in parsed if isinstance(item, str) and item.strip()]
            return [item.strip() for item in raw_value.split(",") if item.strip()]
        return value

    @model_validator(mode="after")
    def validate_allowed_origins(self) -> "Settings":
        if self.enable_demo_auth is None:
            self.enable_demo_auth = self.environment.lower() == "development"
        if self.enforce_corpus_governance is None:
            # Development fixtures intentionally remain usable while every non-development
            # deployment fails closed until its corpus manifest has been reviewed.
            self.enforce_corpus_governance = self.environment.lower() != "development"
        if self.arena_enabled is None:
            # Decision D-03 chose "disable": the Arena stays offline outside development. The socket now checks
            # the principal and the Origin (task 1.4); switching it on elsewhere needs a new D-03 decision.
            self.arena_enabled = self.environment.lower() == "development"
        if self.retrieval_gate is None:
            self.retrieval_gate = "bm25f-v1" if self.environment.lower() == "development" else "p1-floor"
        if self.span_resolver_route_enabled is None:
            self.span_resolver_route_enabled = self.environment.lower() == "development"
        development = self.environment.lower() == "development"
        if self.two_pass_tutor is None:
            self.two_pass_tutor = TWO_PASS_DEFAULT_DEVELOPMENT if development else TWO_PASS_DEFAULT_ELSEWHERE
        if self.ledger_route_enabled is None:
            self.ledger_route_enabled = development
        if self.evidence_panel_enabled is None:
            self.evidence_panel_enabled = development
        if self.two_pass_tutor == "on":
            self._refuse_two_pass_on_before_phase_4_exit(development)
        if self.v1_pipeline is None:
            self.v1_pipeline = V1_PIPELINE_DEFAULT_DEVELOPMENT if development else V1_PIPELINE_DEFAULT_ELSEWHERE
        if not development and self.v1_pipeline == "off":
            # The package is not read: off is refused whatever it says.
            raise ValueError("V1_PIPELINE=off is refused outside development (plan 13.6: no flag may disable V1). Use shadow.")
        if not development and self.v1_pipeline == "enforce":
            self._refuse_v1_enforce_before_phase_4_exit()
        if self.model_gateway is None:
            self.model_gateway = MODEL_GATEWAY_DEFAULT_DEVELOPMENT if development else MODEL_GATEWAY_DEFAULT_ELSEWHERE
        if self.model_gateway == "on" and self.v1_pipeline != "enforce":
            raise ValueError("MODEL_GATEWAY=on needs V1_PIPELINE=enforce (V2 consults only the V1 track's own V1Passed)")
        if not development and self.model_gateway == "on":
            self._refuse_model_gateway_on_before_phase_5_exit()
        if self.v3_queue is None:
            self.v3_queue = V3_QUEUE_DEFAULT_DEVELOPMENT if development else V3_QUEUE_DEFAULT_ELSEWHERE
        if not development and self.v3_queue == "on":
            self._refuse_v3_queue_on_before_phase_6_exit()
        if self.arena_enabled and self.environment.lower() != "development":
            raise ValueError("ARENA_ENABLED is not permitted outside development (Decision D-03).")
        if self.guest_token_secret is None and self.environment.lower() == "development":
            self.guest_token_secret = DEVELOPMENT_GUEST_TOKEN_SECRET
        if self.guest_legacy_upgrade_until is not None and self.guest_legacy_upgrade_until.tzinfo is None:
            raise ValueError("GUEST_LEGACY_UPGRADE_UNTIL must include a timezone, for example 2026-11-30T00:00:00Z.")
        if self.environment.lower() != "development" and any(origin.strip() == "*" for origin in self.allowed_origins):
            raise ValueError("Wildcard ALLOWED_ORIGINS is not permitted outside development.")
        self.database_url = normalize_sqlite_database_url(self.database_url)
        return self

    def _refuse_two_pass_on_before_phase_4_exit(self, development: bool) -> None:
        # The package is read only when "on" is asked for, so no other construction of Settings depends on it.
        from app.core.config_package import ConfigPackageError, get_config_package  # lazy: avoids an import cycle

        try:
            package = get_config_package(self)
        except ConfigPackageError as exc:
            raise ValueError(f"TWO_PASS_TUTOR=on needs a valid configuration package: {exc}") from exc
        if not package.flag_policy.phase4_exit_passed:
            raise ValueError(
                "TWO_PASS_TUTOR=on is refused before the Phase 4 exit (configuration package flag_policy.phase4_exit_passed "
                "is false; plan Phase 3 G, AC-3-6). Use off or shadow."
            )
        if not development and not (package.is_default_path and package.hash_verified):
            raise ValueError("TWO_PASS_TUTOR=on outside development needs the shipped, hash-verified configuration package.")

    def _refuse_v1_enforce_before_phase_4_exit(self) -> None:
        # Read lazily, as for TWO_PASS_TUTOR=on: no other construction of Settings depends on the package.
        from app.core.config_package import ConfigPackageError, get_config_package  # lazy: avoids an import cycle

        try:
            package = get_config_package(self)
        except ConfigPackageError as exc:
            raise ValueError(f"V1_PIPELINE=enforce needs a valid configuration package: {exc}") from exc
        if not package.flag_policy.phase4_exit_passed:
            raise ValueError(
                "V1_PIPELINE=enforce is refused outside development before the Phase 4 exit (configuration package "
                "flag_policy.phase4_exit_passed is false; plan Phase 4 G). Use shadow."
            )
        if not (package.is_default_path and package.hash_verified):
            raise ValueError("V1_PIPELINE=enforce outside development needs the shipped, hash-verified configuration package.")

    def _refuse_model_gateway_on_before_phase_5_exit(self) -> None:
        # Read lazily, as for TWO_PASS_TUTOR=on: no other construction of Settings depends on the package.
        from app.core.config_package import ConfigPackageError, get_config_package  # lazy: avoids an import cycle

        try:
            package = get_config_package(self)
        except ConfigPackageError as exc:
            raise ValueError(f"MODEL_GATEWAY=on needs a valid configuration package: {exc}") from exc
        if not package.flag_policy.phase5_exit_passed:
            raise ValueError(
                "MODEL_GATEWAY=on is refused outside development before the Phase 5 exit (configuration package "
                "flag_policy.phase5_exit_passed is false; plan Phase 5 G, P). Use off or shadow."
            )
        if not (package.is_default_path and package.hash_verified):
            raise ValueError("MODEL_GATEWAY=on outside development needs the shipped, hash-verified configuration package.")

    def _refuse_v3_queue_on_before_phase_6_exit(self) -> None:
        # Read lazily, as for TWO_PASS_TUTOR=on: no other construction of Settings depends on the package.
        from app.core.config_package import ConfigPackageError, get_config_package  # lazy: avoids an import cycle

        try:
            package = get_config_package(self)
        except ConfigPackageError as exc:
            raise ValueError(f"V3_QUEUE=on needs a valid configuration package: {exc}") from exc
        if not package.flag_policy.phase6_exit_passed:
            raise ValueError(
                "V3_QUEUE=on is refused outside development before the Phase 6 exit (configuration package "
                "flag_policy.phase6_exit_passed is false; plan Phase 6 L, P). Use off or shadow."
            )
        if not (package.is_default_path and package.hash_verified):
            raise ValueError("V3_QUEUE=on outside development needs the shipped, hash-verified configuration package.")

    @property
    def tutor_turns_route_enabled(self) -> bool:
        """POST /tutor/turns: development, or two_pass_tutor on (which settings refuse before the Phase 4 exit)."""
        return self.environment.lower() == "development" or self.two_pass_tutor == "on"

    @property
    def project_root(self) -> Path:
        if self.source_assets_root:
            return Path(self.source_assets_root).resolve()

        config_path = Path(__file__).resolve()
        candidates = [parent for parent in config_path.parents]
        candidates.append(Path("/app/source-assets"))

        for candidate in candidates:
            if all((candidate / name).exists() for name in SOURCE_DOCUMENT_NAMES[:2]):
                return candidate

        for candidate in candidates:
            if all((candidate / name).exists() for name in SOURCE_VIDEO_NAMES):
                return candidate

        return config_path.parents[min(3, len(config_path.parents) - 1)]

    @property
    def source_documents(self) -> list[Path]:
        return self._resolve_source_assets(SOURCE_DOCUMENT_NAMES)

    @property
    def source_videos(self) -> list[Path]:
        return self._resolve_source_assets(SOURCE_VIDEO_NAMES)

    @property
    def transcripts_dir(self) -> Path:
        return self.project_root / "transcripts"

    @property
    def source_assets_dir(self) -> Path:
        return self.project_root

    @property
    def source_asset_search_roots(self) -> list[Path]:
        root = self.project_root
        search_roots = [root]
        update_root = root / "update_data"
        if update_root.exists():
            search_roots.append(update_root)
        return search_roots

    def _resolve_source_assets(self, filenames: list[str]) -> list[Path]:
        resolved_paths: list[Path] = []
        for name in filenames:
            for root in self.source_asset_search_roots:
                candidate = root / name
                if candidate.exists():
                    resolved_paths.append(candidate)
                    break
        return resolved_paths


# The two_pass_tutor defaults (PD-10). Configuration package v2 records them as flag_policy.two_pass_tutor.
# default_development and default_elsewhere, and parse_config_package refuses a package whose values differ, so the
# package can never say one default while the code applies another (spec 18.8 F4).
TWO_PASS_DEFAULT_DEVELOPMENT = "shadow"
TWO_PASS_DEFAULT_ELSEWHERE = "off"
# The v1_pipeline defaults (PD-19). Configuration package v3 records them as flag_policy.v1_pipeline.
# default_development and default_elsewhere, and the loader refuses a package whose values differ.
V1_PIPELINE_DEFAULT_DEVELOPMENT = "enforce"
V1_PIPELINE_DEFAULT_ELSEWHERE = "shadow"
# The model_gateway defaults (PD-28). Configuration package v4 records them as flag_policy.model_gateway.
# default_development and default_elsewhere, and the loader refuses a package whose values differ.
MODEL_GATEWAY_DEFAULT_DEVELOPMENT = "shadow"
MODEL_GATEWAY_DEFAULT_ELSEWHERE = "off"
# The v3_queue defaults (PD-38). Configuration package v5 records them as flag_policy.v3_queue.default_development and
# default_elsewhere, and the loader refuses a package whose values differ.
V3_QUEUE_DEFAULT_DEVELOPMENT = "shadow"
V3_QUEUE_DEFAULT_ELSEWHERE = "off"


@lru_cache
def get_settings() -> Settings:
    return Settings()
