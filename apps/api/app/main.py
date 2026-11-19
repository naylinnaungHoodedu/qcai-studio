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

from app.api.routes import admin, analytics, arena, assets, assistant, auth, builder, content, insights, learner_record, ledger, projects, qa, search, spans, support, tutor
from app.core.config_package import ConfigPackageError, get_config_package
from app.core.corpus_governance import CorpusGovernanceError, DriftReport, get_corpus_registry, p1_floor_recall_stop
from app.core.config import get_settings
from app.core.db import Base, SessionLocal, engine
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
        settings.vertex_ai_api_key,
        settings.openai_api_key,
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
    """Package v2's schema pins and prompt hashes against the code (Phase 3 spec 5.4, conflict 30).

    A problem stops a governed build only when the pipeline is requested (TWO_PASS_TUTOR not off); otherwise the
    pipeline is reported unavailable (/ready tutor_pipeline.available false) and its effective mode stays off."""
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


def _initialize_database() -> None:
    # Before the schema step, so a missing or invalid manifest stops start-up without creating or altering a table.
    _check_corpus_before_any_table()
    database_url = settings.database_url.lower()
    max_attempts = 8 if database_url.startswith(("postgresql", "postgres")) else 1
    last_error: OperationalError | None = None
    for attempt in range(max_attempts):
        try:
            Base.metadata.create_all(bind=engine)
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


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Before the database step, so a missing secret stops start-up without touching the schema.
    require_guest_token_secret(settings)
    _initialize_database()
    _record_configuration_overrides()
    get_course_store()
    if settings.semantic_retrieval_enabled and not get_retrieval_engine().semantic_enabled:
        # The setting alone never enables hybrid retrieval: only a process that aligned the span-id vectors does
        # (workers/rag.py). The API process stays lexical, and /ready reports semantic_enabled false.
        LOGGER.warning(
            "Semantic retrieval is enabled by setting but not aligned in this process; retrieval stays lexical",
            extra={FIELDS: {"event": "semantic.inactive"}},
        )
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
        # margin are the package's calibrated values, provisional until Phase 4 and reported below either way.
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
        "available": tutor_shadow.PIPELINE_UNAVAILABLE_REASON is None,
    }


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
    """The response ledger's head: a read that never changes readiness, since the ledger fails open."""
    from app.services.ledger import CHAIN, chain_head

    try:
        with SessionLocal() as db:
            head = chain_head(db)
        return {"chain": CHAIN, "head_seq": head[0] if head else 0}
    except Exception:
        LOGGER.warning("Readiness ledger head read failed", exc_info=True)
        return {"chain": CHAIN, "head_seq": None, "status": "unavailable"}


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
