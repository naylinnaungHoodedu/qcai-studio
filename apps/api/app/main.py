import json
import logging
import secrets
import time
from contextlib import asynccontextmanager
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from slowapi.errors import RateLimitExceeded
from slowapi.extension import _rate_limit_exceeded_handler
from sqlalchemy import text
from sqlalchemy.exc import DataError, DBAPIError, OperationalError

from app.api.routes import admin, analytics, arena, assets, assistant, auth, builder, content, insights, learner_record, ledger, projects, qa, search, spans, support, tutor, v3
from app.core.config_package import ConfigPackageError, get_config_package
from app.core.corpus_governance import CorpusGovernanceError, DriftReport, get_corpus_registry, p1_floor_recall_stop
from app.core.config import get_settings
from app.core.db import Base, SessionLocal, engine
from app.gateway.retired import retired_secret_values, retired_settings_present
from app.gateway.secrets import provider_secret_values
from app.core.rate_limit import limiter
from app.core.guest_tokens import require_guest_token_secret
from app.core.log_redaction import install_log_redaction
from app.core.request_protection import protect_guest_mutation_request
from app.core.schema_upgrades import run_schema_upgrades
from app.core.structured_logging import FIELDS, configure_logging
from app.services.retention import run_retention_cleanup
from app.services.retrieval_metrics import snapshot as retrieval_slis
from app.services.security_log import record_security_event, record_security_event_async, route_template
from app.services.store import get_course_store, get_retrieval_engine
from app.services.tutor_pipeline import shadow as tutor_shadow
from app.services.tutor_pipeline.metrics import snapshot as tutor_slis


settings = get_settings()
IS_PRODUCTION = settings.environment.lower() != "development"
install_log_redaction(
    [
        # A retired provider key (VERTEX_AI_API_KEY) that a deployment still sets in the process environment stays masked
        # (Phase 5 spec 4.18), and so does the embedding key the gateway reads (OPENAI_API_KEY; spec 4.19).
        *retired_secret_values(),
        *provider_secret_values(),
        settings.pinecone_api_key,
        settings.guest_token_secret,
        settings.guest_token_previous_secret,
    ]
)
configure_logging()
LOGGER = logging.getLogger("qcai.api")
TUTOR_LOGGER = logging.getLogger("qcai.tutor")

def _build_content_security_policy(app_settings = settings, nonce: str | None = None) -> str:
    is_production = app_settings.environment.lower() != "development"
    connect_sources = {"'self'"}
    if not is_production:
        connect_sources.update({"http://127.0.0.1:*", "http://localhost:*"})
    for origin in app_settings.allowed_origins:
        connect_sources.add(origin.rstrip("/"))
    if app_settings.site_url:
        parsed_site_url = urlsplit(app_settings.site_url)
        if (
            parsed_site_url.scheme
            and parsed_site_url.netloc
            and not (is_production and parsed_site_url.hostname in {"0.0.0.0", "127.0.0.1", "localhost"})
        ):
            connect_sources.add(f"{parsed_site_url.scheme}://{parsed_site_url.netloc}")
    if app_settings.api_base_url:
        parsed = urlsplit(app_settings.api_base_url)
        if (
            parsed.scheme
            and parsed.netloc
            and not (is_production and parsed.hostname in {"0.0.0.0", "127.0.0.1", "localhost"})
        ):
            connect_sources.add(f"{parsed.scheme}://{parsed.netloc}")
            websocket_scheme = "wss" if parsed.scheme == "https" else "ws"
            connect_sources.add(f"{websocket_scheme}://{parsed.netloc}")
    script_sources = ["'self'"]
    if nonce:
        script_sources.append(f"'nonce-{nonce}'")
    if not is_production:
        script_sources.append("'unsafe-eval'")
    return (
        "default-src 'self'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'; object-src 'none'; "
        "img-src 'self' data: blob:; media-src 'self' blob:; "
        "style-src 'self'; style-src-elem 'self'; style-src-attr 'unsafe-inline'; "
        f"script-src {' '.join(script_sources)}; "
        f"connect-src {' '.join(sorted(connect_sources))};"
    )


def _build_security_headers(app_settings = settings, nonce: str | None = None) -> dict[str, str]:
    security_headers = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "X-XSS-Protection": "1; mode=block",
        "Referrer-Policy": "same-origin",
        "Cross-Origin-Opener-Policy": "same-origin",
        "Cross-Origin-Resource-Policy": "same-site",
        "Permissions-Policy": "accelerometer=(), camera=(), geolocation=(), gyroscope=(), microphone=(), payment=(), usb=()",
        "Content-Security-Policy": _build_content_security_policy(app_settings, nonce=nonce),
    }
    if app_settings.environment.lower() != "development":
        security_headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
    return security_headers


def _request_nonce(request: Request) -> str:
    nonce = getattr(request.state, "csp_nonce", None)
    if nonce:
        return nonce
    nonce = secrets.token_urlsafe(16)
    request.state.csp_nonce = nonce
    return nonce


def _security_headers_for_request(request: Request) -> dict[str, str]:
    return _build_security_headers(settings, nonce=_request_nonce(request))


def _request_id(request: Request) -> str:
    request_id = getattr(request.state, "request_id", None)
    if request_id:
        return request_id
    inbound_request_id = request.headers.get("x-request-id", "").strip()
    request_id = inbound_request_id or uuid4().hex
    request.state.request_id = request_id
    return request_id


def _response_headers_for_request(request: Request) -> dict[str, str]:
    headers = _security_headers_for_request(request)
    headers["X-Request-ID"] = _request_id(request)
    return headers


# The start-up manifest drift report (plan Phase 2 I, "manifest drift (0)"); /ready and the start-up line report it.
STARTUP_DRIFT: DriftReport | None = None


def _check_corpus_before_any_table() -> None:
    """Configuration package, manifest and drift: all fail closed before any database work (Phase 2 spec 6.1)."""
    global STARTUP_DRIFT
    # The configuration package: a structural error always stops start-up, a hash mismatch in a governed build.
    package = get_config_package(settings)
    _check_tutor_pipeline_package(package)
    # The served catalogue is the manifest (Decision P1-D-07, D-31): an empty one starts and serves no asset.
    registry = get_corpus_registry(settings)
    registry.assert_ready_to_serve()
    # Only the files present are checked: the image holds none, so there it checks the authored item alone.
    report = registry.drift_report(settings.project_root, settings.manifest_drift_check, settings=settings)
    STARTUP_DRIFT = report
    if report.drifted:
        details = "; ".join(f"{item_id}: {reason}" for item_id, reason in report.drifted)
        if settings.enforce_corpus_governance:
            raise CorpusGovernanceError(f"manifest drift: {details}")
        LOGGER.warning("Manifest drift in development", extra={FIELDS: {"event": "corpus.drift", "drifted": len(report.drifted), "details": details}})
    # Plan Phase 2 L, "stop if ... recall@5 falls below baseline", as spec conflict 29 records it: document spans under
    # the p1-floor gate lose recall, so such a build does not start unless the owner override is set (and logged).
    stopped = p1_floor_recall_stop(registry, settings)
    if stopped:
        details = f"{len(stopped)} document item(s) would be indexed under the p1-floor gate, for example {stopped[0]}"
        if not settings.allow_p1_floor_with_documents:
            raise CorpusGovernanceError(
                f"recall stop (Phase 2 spec conflict 29): {details}; switch RETRIEVAL_GATE under D-05 or recalibrate first"
            )
        LOGGER.warning("Recall stop overridden", extra={FIELDS: {"event": "retrieval.recall_stop_overridden", "items": len(stopped)}})


def _check_tutor_pipeline_package(package) -> None:
    """The package's V1 block, then its tutor-pipeline schema pins and prompt hashes, against the code.

    First _check_v1_package (Phase 4 spec 10.1): any problem with the v1 block, a package without one included, stops
    every governed build and every build outside development, whatever TWO_PASS_TUTOR says; only a development build
    with governance off goes on, with the two-pass V1 mode off. Then _check_gateway_package (Phase 5 spec 4.17): a
    problem with package v4's gateway, v2 or tools block stops a governed build only when the gateway is requested
    (MODEL_GATEWAY not off), else the V2 mode stays off. Then the tutor pipeline (Phase 3 spec 5.4, conflict 30): one
    of its problems stops a governed build only when the pipeline is requested (TWO_PASS_TUTOR not off); otherwise the
    pipeline is reported unavailable (/ready tutor_pipeline.available false) and its effective mode stays off. Between
    the gateway and the pipeline, _check_v3_package (Phase 6 spec 4.15, 10.1)."""
    _check_v1_package(package)
    _check_gateway_package(package)
    _check_v3_package(package)
    _check_ehmf_package(package)
    if package.tutor_pipeline is None:
        tutor_shadow.PIPELINE_UNAVAILABLE_REASON = None
        return
    from app.services.tutor_pipeline.package_check import check_tutor_pipeline_package

    problems = check_tutor_pipeline_package(package, structural=False)
    if not problems:
        tutor_shadow.PIPELINE_UNAVAILABLE_REASON = None
        return
    reason = "; ".join(problems)[:500]
    if settings.enforce_corpus_governance and settings.two_pass_tutor != "off":
        raise ConfigPackageError(f"tutor pipeline: {reason}")
    tutor_shadow.PIPELINE_UNAVAILABLE_REASON = reason
    TUTOR_LOGGER.warning(
        "The two-pass tutor pipeline is unavailable; it stays off",
        extra={FIELDS: {"event": "tutor.two_pass.unavailable", "reason": reason}},
    )


def _check_gateway_package(package) -> None:
    """Package v4's gateway, v2 and tools blocks against the code (Phase 5 spec 4.17, 10.1). A pinning problem never
    reaches this check: the loader refuses an unpinned identifier in every build, so start-up has already stopped
    (AC-5-10). Without a gateway block (a v1 to v3 package) the V2 mode is off. Any other problem stops a governed build
    when the gateway is requested (MODEL_GATEWAY not off); otherwise the gateway is reported unavailable (/ready
    gateway.available false), the V2 mode stays off and tutor.v2.unavailable is logged. Outside development
    MODEL_GATEWAY is off, so such a problem never stops a production start-up. Reads only the package, the committed
    files beside it and code values; writes nothing."""
    import app.gateway as gateway

    if package.gateway is None:
        gateway.GATEWAY_UNAVAILABLE_REASON = None
        return
    from app.gateway.package_check import check_gateway_package

    problems = check_gateway_package(package, structural=False)
    if not problems:
        gateway.GATEWAY_UNAVAILABLE_REASON = None
        return
    reason = "; ".join(problems)[:500]
    if settings.enforce_corpus_governance and settings.model_gateway != "off":
        raise ConfigPackageError(f"gateway: {reason}")
    gateway.GATEWAY_UNAVAILABLE_REASON = reason
    TUTOR_LOGGER.warning("The model gateway is unavailable; the V2 mode stays off", extra={FIELDS: {"event": "tutor.v2.unavailable", "reason": reason}})


def _check_v3_package(package) -> None:
    """Package v5's v3 block against the V3 code (Phase 6 spec 4.15, 10.1). Without a v3 block (a v1 to v4 package) the V3
    mode is off. A problem stops a governed build when V3 is requested (V3_QUEUE not off); otherwise V3 is reported
    unavailable (/ready v3.available false), its mode stays off and v3.unavailable is logged. Outside development
    V3_QUEUE is off, so such a problem never stops a production start-up. Reads only the package, the committed files
    beside it and code values (never apps/api/tests/, which the image does not hold); writes nothing."""
    from app.services import v3 as v3_service

    if package.v3 is None:
        v3_service.V3_UNAVAILABLE_REASON = None
        return
    from app.services.v3.package_check import check_v3_package

    problems = check_v3_package(package, structural=False)
    if not problems:
        v3_service.V3_UNAVAILABLE_REASON = None
        return
    reason = "; ".join(problems)[:500]
    if settings.enforce_corpus_governance and settings.v3_queue != "off":
        raise ConfigPackageError(f"v3: {reason}")
    v3_service.V3_UNAVAILABLE_REASON = reason
    logging.getLogger("qcai.v3").warning("The V3 audit is unavailable; the V3 mode stays off", extra={FIELDS: {"event": "v3.unavailable", "reason": reason}})


def _check_ehmf_package(package) -> None:
    """Package v6's ehmf block against the EHMF code (Phase 7 spec 4.13, 10.1). Without an ehmf block (a v1 to v5 package)
    EHMF is off. A problem stops a governed build when EHMF is requested (EHMF not off); otherwise EHMF is reported
    unavailable (/ready ehmf.available false), its mode stays off and ehmf.unavailable is logged. Outside development the
    default (EHMF off) never stops a start-up; a recorded EHMF=shadow override (config.override ehmf_shadow) does stop a
    governed start-up when the package has a problem. Reads only the package and the committed files beside it (never docs/
    or apps/api/tests/, which the image does not hold); writes nothing."""
    from app.services import ehmf as ehmf_service

    if package.ehmf is None:
        ehmf_service.EHMF_UNAVAILABLE_REASON = None
        return
    from app.services.ehmf.package_check import check_ehmf_package

    problems = check_ehmf_package(package, structural=False)
    if not problems:
        ehmf_service.EHMF_UNAVAILABLE_REASON = None
        return
    reason = "; ".join(problems)[:500]
    if settings.enforce_corpus_governance and settings.ehmf != "off":
        raise ConfigPackageError(f"ehmf: {reason}")
    ehmf_service.EHMF_UNAVAILABLE_REASON = reason
    logging.getLogger("qcai.ehmf").warning("EHMF is unavailable; its mode stays off", extra={FIELDS: {"event": "ehmf.unavailable", "reason": reason}})


def _warn_retired_provider_settings() -> None:
    """Names (never values) of retired provider variables the deployment still sets (Phase 5 spec 4.18)."""
    names = retired_settings_present()
    if names:
        logging.getLogger("qcai.gateway").warning(
            "Retired provider settings are set and ignored", extra={FIELDS: {"event": "gateway.retired_setting", "names": list(names)}}
        )


def _check_v1_package(package) -> None:
    """Package v3's v1 block against the V1 code (Phase 4 spec 10.1). The legacy guard runs on every delivery path,
    so a build stops on any problem, and on a package without a v1 block (the guard needs its lexicon), when it is
    governed or outside development, whatever its governance setting (plan 13.6: no flag, setting or governance
    override may disable V1). Only in development with governance off does the two-pass V1 mode become off, the
    guard running without its polarity rule. Reads only the package and in-memory code values; writes nothing."""
    from app.services import v1_checks

    if package.v1 is None:
        problems = ["the configuration package has no v1 block (package v3 is required: the legacy guard needs its lexicon)"]
    else:
        from app.services.v1_checks.package_check import check_v1_package

        problems = check_v1_package(package, structural=False)
    if not problems:
        v1_checks.V1_UNAVAILABLE_REASON = None
        return
    reason = "; ".join(problems)[:500]
    if settings.enforce_corpus_governance or settings.environment.lower() != "development":
        raise ConfigPackageError(f"v1 checks: {reason}")
    v1_checks.V1_UNAVAILABLE_REASON = reason
    TUTOR_LOGGER.warning("The V1 checks are unavailable; the two-pass V1 mode stays off", extra={FIELDS: {"event": "tutor.v1.unavailable", "reason": reason}})


def _initialize_database() -> None:
    # Before the schema step, so a missing or invalid manifest stops start-up without creating or altering a table.
    _check_corpus_before_any_table()
    database_url = settings.database_url.lower()
    max_attempts = 8 if database_url.startswith(("postgresql", "postgres")) else 1
    last_error: OperationalError | None = None
    for attempt in range(max_attempts):
        try:
            Base.metadata.create_all(bind=engine)
            # No ledger start marker (spec 18.8 F10): a revision deployed with no traffic starts while the earlier
            # image still serves every learner. Each tutor turn records whether it expects a ledger record instead
            # (TutorTurn.ledger_record_expected; spec 18.8 F12), and the first append creates the chain head.
            run_schema_upgrades(engine)
            with SessionLocal() as db:
                run_retention_cleanup(db)
            return
        except OperationalError as exc:
            last_error = exc
            if attempt == max_attempts - 1:
                raise
            time.sleep(min(2**attempt, 10))
    if last_error:
        raise last_error


# Why SEMANTIC_RETRIEVAL_ENABLED is on and retrieval still lexical (RetrievalEngine.semantic_inactive_reason).
SEMANTIC_INACTIVE_MESSAGES = {
    "egress_not_opted_in": "Semantic retrieval is enabled by setting but its embedding egress is not opted in (openai-embeddings in MODEL_EGRESS_PROVIDERS, D-23); retrieval stays lexical",
    "provider_open": "Semantic retrieval is enabled by setting but the gateway gives no embedder while D-07, D-12 or Q-09 is open or the Q-15 payload review is pending; retrieval stays lexical",
    "unpinned": "Semantic retrieval is enabled by setting but package v4 gateway.embeddings names no pinned embedding model (pinned-version-v1); retrieval stays lexical",
    "no_budget": "Semantic retrieval is enabled by setting but the gateway's daily budget for this environment is 0; retrieval stays lexical",
    "gateway_stopped": "Semantic retrieval is enabled by setting but the model gateway is stopped; retrieval stays lexical",
    "not_configured": "Semantic retrieval is enabled by setting but its keys, SDK or index are missing; retrieval stays lexical",
    "learner_text": "Semantic retrieval is enabled by setting but a query embedding would send the learner's query text, and only public-corpus spans leave the platform (plan Phase 5 H); retrieval stays lexical",
    "not_aligned": "Semantic retrieval is enabled by setting but not aligned in this process; retrieval stays lexical",
}


def _warn_semantic_inactive() -> str | None:
    """The start-up semantic.inactive warning: the setting alone never enables hybrid retrieval. It also needs an embedder
    from the gateway, which names the first check that fails (the D-23 opt-in, closed provider decisions and the Q-15
    review, a pinned model in package v4, a budget, an open gateway, the key, and plan H's bar on the learner's query
    text, which no configuration lifts), the vector index's key and name, and a process that aligned the span-id
    vectors (workers/rag.py). The API process stays lexical, and /ready reports semantic_enabled false. Returns the
    reason."""
    inactive = get_retrieval_engine().semantic_inactive_reason
    if inactive is not None:
        LOGGER.warning(SEMANTIC_INACTIVE_MESSAGES[inactive], extra={FIELDS: {"event": "semantic.inactive", "reason": inactive}})
    return inactive


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Before the database step, so a missing secret stops start-up without touching the schema.
    require_guest_token_secret(settings)
    _initialize_database()
    _warn_retired_provider_settings()
    _record_configuration_overrides()
    get_course_store()
    _warn_semantic_inactive()
    # The governance_enforced SLI (plan Phase 1, item I): each instance says what it started with.
    LOGGER.info("API started", extra={FIELDS: {"event": "startup", "environment": settings.environment, **_build_fields()}})
    yield


app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
    docs_url="/docs" if not IS_PRODUCTION else None,
    redoc_url="/redoc" if not IS_PRODUCTION else None,
    openapi_url="/openapi.json" if not IS_PRODUCTION else None,
)
def _record_configuration_overrides() -> None:
    # "Alert on overrides" (plan Phase 1, item I): a deployment that relaxes a fail-safe default says so in the log.
    if not IS_PRODUCTION:
        return
    package = get_config_package(settings)
    overrides = {
        name: True
        for name, active in (
            ("demo_auth_enabled", settings.enable_demo_auth),
            ("corpus_governance_disabled", not settings.enforce_corpus_governance),
            # Phase 2 switches that change what learners see; each needs a D-05 approval outside development.
            ("retrieval_gate_bm25", settings.retrieval_gate == "bm25f-v1"),
            ("p1_floor_recall_stop_overridden", settings.allow_p1_floor_with_documents),
            ("semantic_retrieval_enabled", settings.semantic_retrieval_enabled),
            ("span_resolver_route_enabled", settings.span_resolver_route_enabled),
            ("citation_provisional_lift_enabled", settings.citation_provisional_lift_enabled),
            ("config_package_path_overridden", not package.is_default_path),
            ("config_package_hash_unverified", not package.hash_verified),
            # Phase 3: the two-pass shadow outside development (DI-32), a relaxed audit control (the ledger), and the
            # new learner-visible switches; each needs a D-05 approval outside development.
            ("two_pass_tutor_shadow", settings.two_pass_tutor == "shadow"),
            ("tutor_ledger_disabled", not settings.tutor_ledger_enabled),
            ("ledger_route_enabled", settings.ledger_route_enabled),
            ("evidence_panel_enabled", settings.evidence_panel_enabled),
            # The PD-11 budgets are package values; an environment override changes outcomes (budget abstentions,
            # deferred appends) under the same package hash, so it is alerted on and stamped on every record (D5).
            ("shadow_budget_overridden", settings.two_pass_shadow_budget_ms is not None),
            ("ledger_append_budget_overridden", settings.tutor_ledger_append_budget_ms is not None),
            # Phase 4: V1 enforcing the shadow record outside development (refused before the Phase 4 exit).
            ("v1_pipeline_enforce", settings.v1_pipeline == "enforce"),
            # Phase 5: the V2 panel outside development (on is refused before the Phase 5 exit) and a provider egress
            # opt-in (D-23).
            ("model_gateway_shadow", settings.model_gateway == "shadow"),
            ("model_gateway_on", settings.model_gateway == "on"),
            ("model_egress_opt_in", bool(settings.model_egress_providers)),
            # Phase 6: the V3 queue outside development (on is refused before the Phase 6 exit; shadow changes no learner
            # path, and no reviewer is admitted there while D-18 is open).
            ("v3_queue_shadow", settings.v3_queue == "shadow"),
            ("v3_queue_on", settings.v3_queue == "on"),
            # Phase 7: EHMF outside development (on is refused before the Phase 7 exit; shadow changes no learner path,
            # since the two-pass pipeline and V2 are off there).
            ("ehmf_shadow", settings.ehmf == "shadow"),
            ("ehmf_on", settings.ehmf == "on"),
            ("learner_sync_on", settings.learner_sync == "on"),
            ("learner_identity_on", settings.learner_identity == "on"),
            ("learner_privacy_on", settings.learner_privacy == "on"),
            ("learner_planner_shadow", settings.learner_planner == "shadow"),
            ("learner_planner_on", settings.learner_planner == "on"),
        )
        if active
    }
    if overrides:
        record_security_event("config.override", "warning", actor_role="system", details=overrides)


def _rate_limit_exceeded(request: Request, exc: RateLimitExceeded):
    record_security_event(
        "rate_limit.exceeded",
        "denied",
        connection=request,
        details={"route": route_template(request), "limit": str(exc.detail)},
    )
    return _rate_limit_exceeded_handler(request, exc)


app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ROUTERS = (
    auth.router,
    content.router,
    assets.router,
    search.router,
    qa.router,
    spans.router,
    spans.evidence_router,
    assistant.router,
    tutor.router,
    ledger.router,
    v3.router,
    analytics.router,
    admin.router,
    arena.router,
    builder.router,
    insights.router,
    learner_record.router,
    projects.router,
    support.router,
)
for router in ROUTERS:
    app.include_router(router)
# Middleware runs before routing, so it finds a request's route template by matching these.
ROUTE_INDEX = tuple(route for router in ROUTERS for route in router.routes)


@app.middleware("http")
async def enforce_guest_request_protection(request: Request, call_next):
    try:
        protect_guest_mutation_request(request, settings)
    except HTTPException as exc:
        await record_security_event_async(
            "request.forbidden",
            "denied",
            connection=request,
            details={"route": route_template(request, ROUTE_INDEX), "method": request.method, "reason": exc.detail},
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=_response_headers_for_request(request),
        )
    response = await call_next(request)
    return response


@app.middleware("http")
async def attach_request_id(request: Request, call_next):
    request_id = _request_id(request)
    response = await call_next(request)
    response.headers.setdefault("X-Request-ID", request_id)
    return response


@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    for key, value in _security_headers_for_request(request).items():
        response.headers.setdefault(key, value)
    return response


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(request: Request, exc: RequestValidationError):
    # FastAPI's default 422 echoes each rejected value back ("input", "ctx"). A lone UTF-16 surrogate in a JSON
    # string cannot be encoded, and a deeply nested body overflows the encoder, so the refusal itself became a 500
    # (Release R1.1). Echoing input also returned passwords to the caller. Keep only what clients read: type, loc
    # and msg, rendered as ASCII JSON so no value can fail to encode.
    detail = [
        {"type": str(error.get("type", "")), "loc": [str(part) for part in error.get("loc", ())], "msg": str(error.get("msg", ""))}
        for error in exc.errors()
    ]
    return Response(
        content=json.dumps({"detail": detail}, ensure_ascii=True),
        status_code=422,
        media_type="application/json",
        headers=_response_headers_for_request(request),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc):
    LOGGER.exception("Unhandled server error on %s %s [%s]", request.method, request.url.path, _request_id(request))
    return JSONResponse(
        status_code=500,
        content={"error": "internal", "detail": "Unexpected server error."},
        headers=_response_headers_for_request(request),
    )


def _sqlstate(exc: DBAPIError) -> str | None:
    """The PostgreSQL SQLSTATE of a driver error: psycopg's `sqlstate`/`pgcode`, or pg8000's field "C"."""
    original = exc.orig
    for attribute in ("sqlstate", "pgcode"):
        code = getattr(original, attribute, None)
        if isinstance(code, str):
            return code
    arguments = getattr(original, "args", ())
    if arguments and isinstance(arguments[0], dict):
        code = arguments[0].get("C")
        return code if isinstance(code, str) else None
    return None


@app.exception_handler(DBAPIError)
async def database_error_handler(request: Request, exc: DBAPIError):
    # SQLSTATE class 22, "data exception": a client value the database cannot store or compare (a NUL character,
    # a string longer than its column, NaN in a json column, an integer out of range). SQLite accepts these, so
    # they surfaced only in production as HTTP 500 (Release R1.1). Refuse them; anything else stays a server error.
    # psycopg refuses some values (a NUL byte) before sending them, as a DBAPI DataError with no SQLSTATE; pg8000
    # sends them and reports the server's class-22 error.
    code = _sqlstate(exc)
    if isinstance(exc, DataError) or (code is not None and code.startswith("22")):
        LOGGER.warning(
            "Refused a value the database cannot store on %s %s [%s]: SQLSTATE %s",
            request.method,
            request.url.path,
            _request_id(request),
            code or type(exc.orig).__name__,
        )
        return JSONResponse(
            status_code=422,
            content={"detail": "The request contains a value that cannot be stored."},
            headers=_response_headers_for_request(request),
        )
    return await unhandled_exception_handler(request, exc)


@app.get("/health")
def healthcheck():
    # `commit` lets a deployment record be checked against what actually serves (AC-1-7).
    return {"status": "ok", "app": settings.app_name, "environment": settings.environment, "commit": settings.git_sha}


def _build_fields() -> dict:
    # Plan L2324-2325: /ready exposes governance_enforced, corpus_version and the build SHA (R-50). Phase 2 adds the
    # configuration package, the span scheme, the index and gate, and the provisional thresholds (D9, D11).
    # Deterministic: every value is fixed for the life of the process.
    package = get_config_package(settings)
    store = get_course_store()
    gate = store.gate
    floor, margin, threshold_version = store.index.thresholds
    return {
        "governance_enforced": bool(settings.enforce_corpus_governance),
        "corpus_version": get_corpus_registry(settings).corpus_version,
        "commit": settings.git_sha,
        "config_package_version": package.package_version,
        "config_package_sha256": package.sha256,
        "span_scheme": package.span_scheme,
        "index_version": store.index_version,
        "retrieval_gate": gate,
        "duplicate_span_ids": store.duplicate_span_ids,
        "manifest_drift": STARTUP_DRIFT.drift_count if STARTUP_DRIFT else 0,
        # The thresholds in force: the active gate's. p1-floor is P1-D-04's approved floor; bm25f-v1's floor and
        # margin are the package's calibrated values, provisional until Q-22 (DI-52) in package v3 (its
        # abstention.provisional_until, reported below) and reported below either way.
        "threshold_version": threshold_version,
        "abstention_floor": floor,
        "abstention_margin": margin,
        "thresholds_provisional": bool(package.abstention.provisional) if gate == "bm25f-v1" else False,
        "threshold_authority": "P1-D-04" if gate == "p1-floor" else package.abstention.calibration_record,
        "bm25f_v1_calibrated": {
            "version": package.abstention.version,
            "floor": package.abstention.floor,
            "margin": package.abstention.margin,
            "provisional": bool(package.abstention.provisional),
            "provisional_until": package.abstention.provisional_until,
        },
        # Effective state: on only when the setting is on and this process aligned span-id vectors (task 2.5).
        "semantic_enabled": bool(get_retrieval_engine().semantic_enabled),
        "semantic_setting": bool(settings.semantic_retrieval_enabled),
        # Phase 3 (plan I: "/ready reports versions"): the two-pass mode in force, the pipeline's ids and hashes,
        # and the switches. two_pass_tutor is the effective mode, never "on" before the Phase 4 exit (AC-3-6).
        "two_pass_tutor": tutor_shadow.effective_mode(settings, package),
        "two_pass_tutor_setting": settings.two_pass_tutor,
        "phase4_exit_passed": bool(package.flag_policy.phase4_exit_passed),
        "tutor_pipeline": _tutor_pipeline_fields(package),
        "tutor_ledger_enabled": bool(settings.tutor_ledger_enabled),
        "ledger_route_enabled": bool(settings.ledger_route_enabled),
        "evidence_panel_enabled": bool(settings.evidence_panel_enabled),
        "tutor_turns_route_enabled": bool(settings.tutor_turns_route_enabled),
        # Phase 4 (plan I; spec 10.2): the V1 mode in force and the package's static V1 values. No per-run V1 outcome
        # and no legacy-guard count is public (AC-3-6).
        "v1_pipeline": _v1_mode(package),
        "v1_pipeline_setting": settings.v1_pipeline,
        "v1": _v1_fields(package),
        # Phase 5 (plan 7.7: "/ready MUST report build SHA, corpus_version, threshold_set_version and gateway state";
        # spec 10.2): the V2 mode in force, the setting, and the gateway's static values and state. No call, spend,
        # per-run outcome, stop reason or operator switch is public.
        "model_gateway": _v2_mode(package),
        "model_gateway_setting": settings.model_gateway,
        "phase5_exit_passed": bool(package.flag_policy.phase5_exit_passed),
        "gateway": _gateway_fields(package),
        # Phase 6 (plan Phase 6 I; spec 10.2): the V3 mode in force, the setting, and the package's static V3 values. No
        # count, queue depth, stop state, seed or gold head is public (the SLIs are on the reviewer-only /v3/metrics).
        "v3_queue": _v3_mode(package),
        "v3_queue_setting": settings.v3_queue,
        "phase6_exit_passed": bool(package.flag_policy.phase6_exit_passed),
        "v3": _v3_fields(package),
        # Phase 7 (plan Phase 7 I; spec 10.2): config_version (the package version from v6 on, "pre-phase-7" before it),
        # the EHMF mode in force, the setting and the package's static EHMF values. The one read beside the gateway state
        # is the cached EHMF stop row ("revert required"), only when EHMF is not off: no count, rate, window or seq.
        "config_version": _config_version(package),
        "ehmf_mode": _ehmf_mode(package),
        "ehmf_setting": settings.ehmf,
        "phase7_exit_passed": bool(package.flag_policy.phase7_exit_passed),
        "ehmf": _ehmf_fields(package, store),
        **_phase8_fields(package),
    }


def _phase8_fields(package) -> dict:
    from app.core.phase8_settings import PHASE8_FLAGS
    from app.services.learner_record_metrics import planner_stop_observed, snapshot

    phase8 = {"phase8_exit_passed": package.raw.get("flag_policy", {}).get("phase8_exit_passed") is True}
    for key in PHASE8_FLAGS:
        phase8[f"{key}_setting"] = phase8[key] = getattr(settings, key)
    development = settings.environment.lower() == "development"
    phase8["learner_slis"] = snapshot() if development else {}
    if development:
        phase8["learner_slis"]["planner_stop_observed"] = planner_stop_observed()
    return phase8


def _config_version(package) -> str:
    from app.services.ledger import config_version_of

    return config_version_of({"config_package_version": package.package_version})


def _ehmf_mode(package) -> str:
    from app.services import ehmf as ehmf_service

    return ehmf_service.mode(settings, package)


def _ehmf_fields(package, store) -> dict | None:
    from app.services import ehmf as ehmf_service
    from app.services.ehmf.stop import process_stop_state

    params = package.ehmf
    if params is None:
        return None
    environment = settings.environment.lower()
    registry = environment if environment in params.penalty_registries else "default"
    factor, spans = params.penalty_registries[registry]
    stop = process_stop_state(settings, package)
    return {
        "version": params.version, "routing": params.routing_version, "routing_sha256": params.routing_sha256,
        "weights": params.weight_strings(), "weights_provisional": params.weights_provisional, "precedence": params.precedence,
        "disclosure_template": params.disclosure_template_id,
        "library": {"version": package.v1.library_version, "entries": len(package.v1.library_entries), "sha256": package.v1.library_sha256},
        "golden_set": {"version": params.golden_set_version, "items": params.golden_set_items}, "max_cycles": params.max_cycles,
        # active: what the shared index applies (fixed when the store was built), not the mode recomputed now: a gateway
        # that stops later turns the mode off but leaves the index as built.
        "retrieval_penalty": {"environment": registry, "factor": str(factor), "spans": len(spans), "active": bool(store.penalty_active)},
        "stop": {"revert_required": stop.revert_required}, "available": ehmf_service.EHMF_UNAVAILABLE_REASON is None,
    }


def _v3_mode(package) -> str:
    from app.services import v3 as v3_service

    return v3_service.mode(settings, package)


def _v3_fields(package) -> dict | None:
    params = package.v3
    if params is None:
        return None
    from app.services import v3 as v3_service

    environment = settings.environment.lower()
    registry = environment if environment in params.critical_registries else "default"
    return {
        "version": params.version, "trigger_registry": params.trigger_registry_version, "triggers": sorted(params.trigger_rules),
        "draw": {"rule": params.draw_rule, "rate": f"{params.draw_rate.numerator}/{params.draw_rate.denominator}",
                 "x5_rate": f"{params.x5_rate.numerator}/{params.x5_rate.denominator}", "x5_window_deliveries": params.x5_window_deliveries},
        "double_review": f"{params.double_review_rate.numerator}/{params.double_review_rate.denominator}",
        "queue_age_slo_s": params.queue_age_slo_s, "stop_window_s": params.stop_window_s, "stop_measure": params.stop_measure,
        "critical_registry": {"environment": registry, "entries": len(params.critical_registry_for(environment))},
        "reviewer_pool": params.reviewer_pool, "gold_schema": params.gold_schema, "provisional": True,
        "available": v3_service.V3_UNAVAILABLE_REASON is None,
    }


def _v2_mode(package) -> str:
    from app.services import v2_panel

    return v2_panel.mode(settings, package)


def _gateway_fields(package) -> dict | None:
    gateway, v2 = package.gateway, package.v2
    if gateway is None or v2 is None:
        return None
    import app.gateway as gateway_package
    from app.gateway.gateway import process_gateway_state
    from app.gateway.registry import registry_for

    registry = registry_for(package, settings)
    # The state only: the stop's reason (which may say a credential reached the logs, or name a spend outcome) and the
    # operator's switches (egress opt-ins, kill switch, disabled adapters) stay off this unauthenticated route. The
    # reason is in the gateway.stopped log line and the operator's status command (python -m app.workers.gateway_stop).
    state, _ = process_gateway_state()
    return {
        "version": gateway.version,
        "registry": registry.name,
        "members": [spec.public() for spec in registry.members],
        "embeddings": gateway.embeddings.public() if gateway.embeddings is not None else None,
        "state": state,
        "budget_daily_units": gateway.daily_units.get(registry.name, 0),
        "tool_contract_version": package.tools.version if package.tools is not None else None,
        "panel": {"max_members": v2.max_members, "weights": v2.panel_weights_version, "routing_table": v2.routing_table_version,
                  "tier_rule": v2.tier_rule},
        "provisional": True,
        "available": gateway_package.GATEWAY_UNAVAILABLE_REASON is None,
    }


def _v1_mode(package) -> str:
    from app.services import v1_checks

    return v1_checks.mode(settings, package)


def _v1_fields(package) -> dict | None:
    v1 = package.v1
    if v1 is None:
        return None
    from app.services import v1_checks

    return {
        "version": v1.version,
        "rules_hash": v1.rules_hash,
        "checker": {"hosting": v1.checker_hosting, "model_id": v1.checker_model_id},
        "misconception_library": {"version": v1.library_version, "entries": len(v1.library_entries), "sha256": v1.library_sha256},
        "fixtures_set_sha256": v1.fixtures_set_sha256,
        "regeneration": {"generation": v1.max_generation_regenerations, "render": v1.max_render_regenerations},
        "readability_band": [v1.readability_min, v1.readability_max],
        "x4_margin": dict(v1.x4_margin),
        "stop": {
            "answer_rate_floor": {gate: f"{answered}/{in_domain}" for gate, (answered, in_domain) in v1.answer_rate_floor.items()},
            "v1_p95_latency_ms": v1.p95_budget_ms,
        },
        "quiz_feedback": {"rule": v1.quiz_feedback_rule, "provisional": True},
        "provisional": True,
        "available": v1_checks.V1_UNAVAILABLE_REASON is None,
        "legacy_guard": "on",
    }


def _tutor_pipeline_fields(package) -> dict | None:
    params = package.tutor_pipeline
    if params is None:
        return None
    return {
        "version": params.version,
        "resolver": params.resolver_id,
        "generator": params.generator_default,
        "renderer": params.renderer_id,
        "presentation_plans": list(params.presentation_plans),
        "max_regenerations": params.max_regenerations,
        "schemas_sha256": params.schemas_sha256,
        "prompt_hashes": {
            "resolver": params.resolver_prompt_hash,
            "evidential": params.evidential_prompt_hash,
            "pedagogical": params.pedagogical_prompt_hash,
        },
        "subset_check": params.subset_check,
        # The legacy contained path's pinned ids and rule hash, which every legacy ledger record stamps: the values
        # the provenance audit compares records with (DI-49).
        "legacy": {
            "pipeline_version": params.legacy_pipeline_version,
            "generator_id": params.legacy_generator_id,
            "generator_model_id": params.legacy_generator_model_id,
            "containment_rule_hash": params.legacy_containment_rule_hash,
        },
        # The budgets in force (PD-11) and which of them an environment override changed (R-46; spec 18.6 D5).
        "budgets": _budget_fields(package),
        "available": tutor_shadow.PIPELINE_UNAVAILABLE_REASON is None,
    }


def _budget_fields(package) -> dict:
    from app.services.ledger import budget_stamp

    stamp = budget_stamp(settings, package, shadow_ms=tutor_shadow.shadow_budget_ms(settings, package))
    return {"shadow_ms": stamp.shadow_ms, "ledger_append_ms": stamp.ledger_append_ms, "overridden": list(stamp.overridden)}


def _slis() -> dict:
    drift = STARTUP_DRIFT
    params = get_config_package(settings).tutor_pipeline
    return {
        **retrieval_slis(),
        "manifest_drift": {
            "mode": drift.mode if drift else settings.manifest_drift_check,
            "checked": drift.checked if drift else 0,
            "absent": drift.absent if drift else 0,
            "drifted": drift.drift_count if drift else 0,
        },
        # Plan Phase 3 I: "Ledger writes 100% of deliveries; bound-claim ratio; abstention by reason".
        **tutor_slis(params.phase2_bound_claim_ratio if params else None),
    }


def _ledger_head() -> dict:
    """Whether the response ledger's head is readable: a read that never changes readiness (the ledger fails open).

    /ready is public, so it reports a status only, never the head's sequence number: that is the all-time count of
    tutor responses (traffic volume), which the ledger route shows to reviewers only. The head itself is in the
    verification job's log line (app.workers.response_ledger) and in every tutor.ledger.appended line.
    """
    from app.services.ledger import CHAIN, chain_head

    try:
        with SessionLocal() as db:
            chain_head(db)
        return {"chain": CHAIN, "status": "ok"}
    except Exception:
        LOGGER.warning("Readiness ledger head read failed", exc_info=True)
        return {"chain": CHAIN, "status": "unavailable"}


@app.get("/ready")
def readiness_check():
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
    except Exception:
        LOGGER.warning("Readiness database check failed", exc_info=True)
        return JSONResponse(status_code=503, content={"status": "degraded", "database": "unavailable", **_build_fields()})

    store = get_course_store()
    if not store.lessons:
        return JSONResponse(status_code=503, content={"status": "building", "database": "ok", **_build_fields()})
    return {
        "status": "ready",
        "database": "ok",
        "lessons": len(store.lessons),
        "source_assets": len(store.overview.source_assets) if store.overview else 0,
        **_build_fields(),
        "ledger": _ledger_head(),
        "slis": _slis(),
    }
