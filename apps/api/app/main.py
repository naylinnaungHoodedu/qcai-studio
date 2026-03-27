from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import admin, analytics, arena, assets, auth, builder, content, qa, search
from app.core.config import get_settings
from app.core.db import Base, engine
from app.services.store import get_course_store


settings = get_settings()
app = FastAPI(title=settings.app_name)

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; connect-src 'self' http://127.0.0.1:* http://localhost:*;",
}

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Base.metadata.create_all(bind=engine)
get_course_store()

app.include_router(auth.router)
app.include_router(content.router)
app.include_router(assets.router)
app.include_router(search.router)
app.include_router(qa.router)
app.include_router(analytics.router)
app.include_router(admin.router)
app.include_router(arena.router)
app.include_router(builder.router)


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
