import logging
import secrets
import time
from contextlib import asynccontextmanager
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.extension import _rate_limit_exceeded_handler
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.api.routes import admin, analytics, arena, assets, assistant, auth, builder, content, insights, learner_record, projects, qa, search, support
from app.core.corpus_governance import get_corpus_registry
from app.core.config import SOURCE_DOCUMENT_NAMES, SOURCE_VIDEO_NAMES, get_settings
from app.core.db import Base, SessionLocal, engine
from app.core.rate_limit import limiter
from app.core.guest_tokens import require_guest_token_secret
from app.core.log_redaction import install_log_redaction
from app.core.request_protection import protect_guest_mutation_request
from app.core.schema_upgrades import run_schema_upgrades
from app.core.structured_logging import FIELDS, configure_logging
from app.services.retention import run_retention_cleanup
from app.services.security_log import record_security_event, record_security_event_async, route_template
from app.services.store import get_course_store


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


def _initialize_database() -> None:
    # Before the schema step, so an unapproved corpus stops start-up without creating or altering a table.
    get_corpus_registry(settings).assert_public_assets_ready([*SOURCE_DOCUMENT_NAMES, *SOURCE_VIDEO_NAMES])
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
    overrides = {
        name: True
        for name, active in (
            ("demo_auth_enabled", settings.enable_demo_auth),
            ("corpus_governance_disabled", not settings.enforce_corpus_governance),
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
    assistant.router,
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


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc):
    LOGGER.exception("Unhandled server error on %s %s [%s]", request.method, request.url.path, _request_id(request))
    return JSONResponse(
        status_code=500,
        content={"error": "internal", "detail": "Unexpected server error."},
        headers=_response_headers_for_request(request),
    )


@app.get("/health")
def healthcheck():
    # `commit` lets a deployment record be checked against what actually serves (AC-1-7).
    return {"status": "ok", "app": settings.app_name, "environment": settings.environment, "commit": settings.git_sha}


def _build_fields() -> dict:
    # Plan L2324-2325: /ready exposes governance_enforced, corpus_version and the build SHA (R-50).
    return {
        "governance_enforced": bool(settings.enforce_corpus_governance),
        "corpus_version": get_corpus_registry(settings).corpus_version,
        "commit": settings.git_sha,
    }


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
    }
