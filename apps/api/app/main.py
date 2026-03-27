import time
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from app.api.routes import admin, analytics, arena, assets, auth, builder, content, insights, projects, qa, search
from app.core.config import get_settings
from app.core.db import Base, engine
from app.core.schema_upgrades import run_schema_upgrades
from app.services.store import get_course_store


settings = get_settings()

def _build_content_security_policy() -> str:
    connect_sources = {"'self'", "http://127.0.0.1:*", "http://localhost:*"}
    for origin in settings.allowed_origins:
        connect_sources.add(origin.rstrip("/"))
    if settings.api_base_url:
        parsed = urlsplit(settings.api_base_url)
        if parsed.scheme and parsed.netloc:
            connect_sources.add(f"{parsed.scheme}://{parsed.netloc}")
            websocket_scheme = "wss" if parsed.scheme == "https" else "ws"
            connect_sources.add(f"{websocket_scheme}://{parsed.netloc}")
    return (
        "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
        f"connect-src {' '.join(sorted(connect_sources))};"
    )


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Content-Security-Policy": _build_content_security_policy(),
}


def _initialize_database() -> None:
    database_url = settings.database_url.lower()
    max_attempts = 8 if database_url.startswith(("postgresql", "postgres")) else 1
    last_error: OperationalError | None = None
    for attempt in range(max_attempts):
        try:
            Base.metadata.create_all(bind=engine)
            run_schema_upgrades(engine)
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


app = FastAPI(title=settings.app_name, lifespan=lifespan)

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
app.include_router(analytics.router)
app.include_router(admin.router)
app.include_router(arena.router)
app.include_router(builder.router)
app.include_router(insights.router)
app.include_router(projects.router)


@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    for key, value in SECURITY_HEADERS.items():
        response.headers.setdefault(key, value)
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content={"error": "internal", "detail": "Unexpected server error."},
        headers=SECURITY_HEADERS,
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
