import mimetypes
from pathlib import Path
from typing import Iterator

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.core.auth import AuthUser, get_current_user
from app.core.config import Settings, get_settings
from app.core.db import get_db
from app.services.local_accounts import AUTH_SESSION_COOKIE_NAME
from app.core.source_assets import source_asset_lookup_ids

router = APIRouter(prefix="/source-assets", tags=["source-assets"])
VIDEO_OPEN_ENDED_RANGE_CHUNK_SIZE = 8 * 1024 * 1024
MEDIA_TYPE_OVERRIDES = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def _require_asset_access(
    authorization: str | None = Header(default=None),
    x_demo_user: str | None = Header(default=None),
    x_demo_role: str | None = Header(default=None),
    qcai_session_token: str | None = Cookie(default=None, alias=AUTH_SESSION_COOKIE_NAME),
    qcai_guest_id: str | None = Cookie(default=None),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> AuthUser:
    if not authorization and not x_demo_user and not x_demo_role and not qcai_session_token and not qcai_guest_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required for source assets.")
    user = get_current_user(
        authorization=authorization,
        x_demo_user=x_demo_user,
        x_demo_role=x_demo_role,
        qcai_session_token=qcai_session_token,
        qcai_guest_id=qcai_guest_id,
        settings=settings,
        db=db,
    )
    if user.role not in {"learner", "admin"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role for source assets.")
    return user


def _resolve_asset_path(filename: str) -> Path:
    settings = get_settings()
    allowed_paths = settings.source_documents + settings.source_videos
    for path in allowed_paths:
        if path.name == filename and path.exists():
            return path
    raise HTTPException(status_code=404, detail="Source asset not found.")


def _resolve_asset_path_by_id(asset_id: str) -> Path:
    settings = get_settings()
    allowed_paths = settings.source_documents + settings.source_videos
    for path in allowed_paths:
        if asset_id in source_asset_lookup_ids(path.name) and path.exists():
            return path
    raise HTTPException(status_code=404, detail="Source asset not found.")


def _iter_file_range(path: Path, start: int, end: int, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
    with path.open("rb") as stream:
        stream.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            data = stream.read(min(chunk_size, remaining))
            if not data:
                break
            remaining -= len(data)
            yield data


def _parse_range(range_header: str, file_size: int) -> tuple[int, int]:
    if not range_header.startswith("bytes="):
        raise HTTPException(status_code=416, detail="Unsupported range unit.")
    raw_range = range_header.removeprefix("bytes=").strip()
    if "," in raw_range:
        raise HTTPException(status_code=416, detail="Multiple byte ranges are not supported.")
    start_text, _, end_text = raw_range.partition("-")

    if not start_text and not end_text:
        raise HTTPException(status_code=416, detail="Invalid byte range.")

    try:
        if start_text:
            start = int(start_text)
            end = int(end_text) if end_text else file_size - 1
        else:
            suffix_length = int(end_text)
            if suffix_length <= 0:
                raise HTTPException(status_code=416, detail="Invalid suffix byte range.")
            start = max(file_size - suffix_length, 0)
            end = file_size - 1
    except ValueError as exc:
        raise HTTPException(status_code=416, detail="Invalid byte range.") from exc

    if start < 0 or start >= file_size or end < start:
        raise HTTPException(status_code=416, detail="Requested range is not satisfiable.")

    return start, min(end, file_size - 1)


def _is_open_ended_byte_range(range_header: str) -> bool:
    if not range_header.startswith("bytes="):
        return False
    raw_range = range_header.removeprefix("bytes=").strip()
    if "," in raw_range:
        return False
    start_text, _, end_text = raw_range.partition("-")
    return bool(start_text) and not end_text


def _resolve_media_type(path: Path) -> str:
    return MEDIA_TYPE_OVERRIDES.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def _serve_source_asset(
    path: Path,
    request: Request,
) -> Response:
    file_size = path.stat().st_size
    media_type = _resolve_media_type(path)
    headers = {"Accept-Ranges": "bytes", "Content-Length": str(file_size)}
    range_header = request.headers.get("range")

    if range_header:
        start, end = _parse_range(range_header, file_size)
        if media_type.startswith("video/") and _is_open_ended_byte_range(range_header):
            end = min(start + VIDEO_OPEN_ENDED_RANGE_CHUNK_SIZE - 1, file_size - 1)
        content_length = end - start + 1
        headers.update(
            {
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Content-Length": str(content_length),
            }
        )
        if request.method == "HEAD":
            return Response(status_code=206, media_type=media_type, headers=headers)
        return StreamingResponse(
            _iter_file_range(path, start, end),
            status_code=206,
            media_type=media_type,
            headers=headers,
        )

    if request.method == "HEAD":
        return Response(status_code=200, media_type=media_type, headers=headers)

    if media_type.startswith("video/"):
        headers = {"Accept-Ranges": "bytes"}
        return StreamingResponse(
            _iter_file_range(path, 0, file_size - 1),
            status_code=200,
            media_type=media_type,
            headers=headers,
        )

    return FileResponse(path, media_type=media_type, headers=headers)


@router.api_route("/by-id/{asset_id}", methods=["GET", "HEAD"])
def get_source_asset_by_id(
    asset_id: str,
    request: Request,
    _: AuthUser = Depends(_require_asset_access),
):
    return _serve_source_asset(_resolve_asset_path_by_id(asset_id), request)


@router.api_route("/{filename}", methods=["GET", "HEAD"])
def get_source_asset(
    filename: str,
    request: Request,
    _: AuthUser = Depends(_require_asset_access),
):
    return _serve_source_asset(_resolve_asset_path(filename), request)
