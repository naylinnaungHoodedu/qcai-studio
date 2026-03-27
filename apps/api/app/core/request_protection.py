import hmac
import re
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, status

from app.core.config import Settings


GUEST_ID_COOKIE = "qcai_guest_id"
GUEST_CSRF_COOKIE = "qcai_guest_csrf"
GUEST_CSRF_HEADER = "x-qcai-csrf"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

_GUEST_ID_PATTERN = re.compile(r"^guest-[0-9a-f-]{8,64}$")
_GUEST_CSRF_PATTERN = re.compile(r"^[0-9a-f-]{16,128}$")


def _origin_from_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def trusted_request_origins(settings: Settings) -> set[str]:
    origins = {origin.rstrip("/") for origin in settings.allowed_origins if origin.strip()}
    if settings.api_base_url:
        api_origin = _origin_from_url(settings.api_base_url)
        if api_origin:
            origins.add(api_origin)
    if settings.site_url:
        site_origin = _origin_from_url(settings.site_url)
        if site_origin:
            origins.add(site_origin)
    return origins


def protect_guest_mutation_request(request: Request, settings: Settings) -> None:
    if request.method.upper() in SAFE_METHODS:
        return

    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return

    if settings.enable_demo_auth and (
        request.headers.get("x-demo-user") or request.headers.get("x-demo-role")
    ):
        return

    guest_id = (request.cookies.get(GUEST_ID_COOKIE) or "").strip().lower()
    if not guest_id:
        return
    if not _GUEST_ID_PATTERN.fullmatch(guest_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid guest session.")

    csrf_cookie = (request.cookies.get(GUEST_CSRF_COOKIE) or "").strip().lower()
    csrf_header = (request.headers.get(GUEST_CSRF_HEADER) or "").strip().lower()
    if not csrf_cookie or not csrf_header:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing CSRF protection.")
    if not _GUEST_CSRF_PATTERN.fullmatch(csrf_cookie):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token.")
    if not hmac.compare_digest(csrf_cookie, csrf_header):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed.")

    request_origin = _origin_from_url(request.headers.get("origin")) or _origin_from_url(request.headers.get("referer"))
    if not request_origin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing trusted request origin.")
    if request_origin not in trusted_request_origins(settings):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Untrusted request origin.")
