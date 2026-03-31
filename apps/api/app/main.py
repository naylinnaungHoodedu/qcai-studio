import secrets
import time
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.extension import _rate_limit_exceeded_handler
from sqlalchemy.exc import OperationalError

from app.api.routes import admin, analytics, arena, assets, assistant, auth, builder, content, insights, projects, qa, search, support
from app.core.config import get_settings
from app.core.db import Base, SessionLocal, engine
from app.core.rate_limit import limiter
from app.core.request_protection import protect_guest_mutation_request
from app.core.schema_upgrades import run_schema_upgrades
from app.services.retention import run_retention_cleanup
from app.services.store import get_course_store


settings = get_settings()
IS_PRODUCTION = settings.environment.lower() != "development"

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


def _initialize_database() -> None:
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
    _initialize_database()
    get_course_store()
    yield


app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
    docs_url="/docs" if not IS_PRODUCTION else None,
    redoc_url="/redoc" if not IS_PRODUCTION else None,
    openapi_url="/openapi.json" if not IS_PRODUCTION else None,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(content.router)
app.include_router(assets.router)
app.include_router(search.router)
app.include_router(qa.router)
app.include_router(assistant.router)
app.include_router(analytics.router)
app.include_router(admin.router)
app.include_router(arena.router)
app.include_router(builder.router)
app.include_router(insights.router)
app.include_router(projects.router)
app.include_router(support.router)


@app.middleware("http")
async def enforce_guest_request_protection(request: Request, call_next):
    try:
        protect_guest_mutation_request(request, settings)
    except HTTPException as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=_security_headers_for_request(request),
        )
    response = await call_next(request)
    return response


@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    for key, value in _security_headers_for_request(request).items():
        response.headers.setdefault(key, value)
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content={"error": "internal", "detail": "Unexpected server error."},
        headers=_security_headers_for_request(request),
    )


@app.get("/health")
def healthcheck():
    return {"status": "ok", "app": settings.app_name}


@app.get("/ready")
def readiness_check():
    store = get_course_store()
    if not store.lessons:
        return JSONResponse(status_code=503, content={"status": "building"})
    return {"status": "ready", "lessons": len(store.lessons)}
