import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, WebSocket, status

from app.core.arena_tickets import (
    ARENA_PROTOCOL,
    ARENA_TICKET_TTL_SECONDS,
    ARENA_TICKET_VERSION,
    ArenaTicket,
    issue_arena_ticket,
    redeem_arena_ticket,
)
from app.core.auth import AuthUser, get_current_user
from app.core.config import Settings, get_settings
from app.core.db import SessionLocal
from app.core.rate_limit import SlidingWindowLimiter, limiter
from app.core.request_protection import websocket_origin_is_trusted
from app.schemas import ArenaProfileRead, ArenaStatusRead, ArenaTicketRead
from app.services.arena_engine import DEFAULT_DISPLAY_NAME, get_arena_service
from app.services.guest_sessions import is_guest_revoked
from app.services.security_log import record_security_event_async
from app.services.text_utils import sanitize_user_text

router = APIRouter(prefix="/arena", tags=["arena"])

ARENA_DISPLAY_NAME_MAX_LENGTH = 40
ARENA_MAX_MESSAGE_BYTES = 2048
# Per-principal socket limits (task 1.4). In-process, as the Arena's queue and matches are.
ARENA_CONNECTIONS_PER_MINUTE = 10
ARENA_MESSAGES_PER_10_SECONDS = 20
_connection_attempts = SlidingWindowLimiter(limit=ARENA_CONNECTIONS_PER_MINUTE, window_seconds=60)
_messages = SlidingWindowLimiter(limit=ARENA_MESSAGES_PER_10_SECONDS, window_seconds=10)


@router.get("/leaderboard")
def read_arena_leaderboard(limit: int = Query(default=12, ge=1, le=50)):
    return get_arena_service().leaderboard(limit=limit)


@router.get("/me", response_model=ArenaProfileRead | None)
def read_own_arena_profile(user: AuthUser = Depends(get_current_user)):
    # null until the learner's first authenticated socket creates the profile.
    return get_arena_service().profile(user.user_id, create_missing=False)


@router.get("/profiles/{player_id}", response_model=ArenaProfileRead)
def read_arena_profile(player_id: str):
    # Read-only: profiles are created only by an authenticated socket, for its own principal.
    profile = get_arena_service().profile(player_id, create_missing=False)
    if profile is None:
        raise HTTPException(status_code=404, detail="Arena profile not found.")
    return profile


@router.get("/status", response_model=ArenaStatusRead)
def read_arena_status():
    return {**get_arena_service().status(), "enabled": bool(get_settings().arena_enabled)}


@router.post("/ticket", response_model=ArenaTicketRead)
@limiter.limit(lambda: get_settings().arena_ticket_rate_limit)
def issue_arena_socket_ticket(request: Request, response: Response, user: AuthUser = Depends(get_current_user)):
    settings = get_settings()
    if not settings.arena_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Arena is disabled.")
    if not settings.guest_token_secret:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Arena tickets are not configured.")
    ticket, _ = issue_arena_ticket(settings.guest_token_secret, user.user_id, user.provider)
    response.headers["Cache-Control"] = "no-store"
    return ArenaTicketRead(ticket=ticket, protocol=ARENA_PROTOCOL, expires_in=ARENA_TICKET_TTL_SECONDS)


def _socket_principal(offered_protocols: list[str], settings: Settings) -> ArenaTicket | None:
    tickets = [protocol for protocol in offered_protocols if protocol.startswith(f"{ARENA_TICKET_VERSION}.")]
    if ARENA_PROTOCOL not in offered_protocols or len(tickets) != 1:
        return None
    ticket = redeem_arena_ticket(tickets[0], settings)
    if ticket is None:
        return None
    if ticket.provider == "guest":
        with SessionLocal() as db:
            if is_guest_revoked(db, ticket.user_id):
                return None
    return ticket


def _display_name(value: str | None) -> str:
    cleaned = sanitize_user_text(value or "", preserve_newlines=False)[:ARENA_DISPLAY_NAME_MAX_LENGTH].strip()
    return cleaned or DEFAULT_DISPLAY_NAME


async def _reject(websocket: WebSocket, code: int, reason: str, subject: str | None = None) -> None:
    await record_security_event_async(
        "arena.socket_rejected",
        "denied",
        connection=websocket,
        subject=subject,
        details={"close_code": code, "reason": reason},
    )
    await websocket.close(code=code, reason=reason)


@router.websocket("/ws")
async def arena_socket(websocket: WebSocket):
    settings = get_settings()
    offered = list(websocket.scope.get("subprotocols") or [])
    # Accept, then close with the reason: a close before accept reaches a real client only as HTTP 403, so
    # 4401 and 4403 (AC-1-4) would never be seen. Nothing is read or sent until every check has passed.
    await websocket.accept(subprotocol=ARENA_PROTOCOL if ARENA_PROTOCOL in offered else None)
    if not settings.arena_enabled:
        await websocket.close(code=4403, reason="Arena is disabled.")
        return
    if not websocket_origin_is_trusted(websocket, settings):
        await _reject(websocket, 4403, "Untrusted origin.")
        return
    principal = _socket_principal(offered, settings)
    if principal is None:
        await _reject(websocket, 4401, "A valid Arena ticket is required.")
        return
    if not _connection_attempts.allow(principal.user_id):
        await _reject(websocket, 4429, "Too many Arena connections.", subject=principal.user_id)
        return
    # Any player_id in the query is ignored: the player is the ticket's principal.
    mode = websocket.query_params.get("mode", "ranked").strip().lower() or "ranked"
    if mode not in {"ranked", "bot"}:
        await websocket.close(code=4400, reason="Unsupported mode")
        return

    service = get_arena_service()
    try:
        await service.connect(websocket, principal.user_id, _display_name(websocket.query_params.get("display_name")), mode)
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            text = message.get("text")
            if text is None:
                await websocket.close(code=1003, reason="Arena messages must be text.")
                break
            if len(text.encode("utf-8")) > ARENA_MAX_MESSAGE_BYTES:
                await websocket.close(code=1009, reason="Arena messages are limited to 2 KiB.")
                break
            if not _messages.allow(principal.user_id):
                await _reject(websocket, 4429, "Too many Arena messages.", subject=principal.user_id)
                break
            try:
                payload = json.loads(text)
            except ValueError:
                payload = None
            if not isinstance(payload, dict):
                await websocket.close(code=1003, reason="Arena messages must be JSON objects.")
                break
            await service.handle_message(principal.user_id, payload)
    finally:
        await service.disconnect(principal.user_id, websocket)
