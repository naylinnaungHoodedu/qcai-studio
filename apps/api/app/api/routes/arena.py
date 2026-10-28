from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect

from app.core.config import get_settings
from app.schemas import ArenaStatusRead
from app.services.arena_engine import get_arena_service

router = APIRouter(prefix="/arena", tags=["arena"])


@router.get("/leaderboard")
def read_arena_leaderboard(limit: int = Query(default=12, ge=1, le=50)):
    return get_arena_service().leaderboard(limit=limit)


@router.get("/profiles/{player_id}")
def read_arena_profile(player_id: str):
    # Creating a missing profile is a leaderboard write, so it is off whenever the Arena is off.
    profile = get_arena_service().profile(player_id, create_missing=bool(get_settings().arena_enabled))
    if profile is None:
        raise HTTPException(status_code=404, detail="Arena profile not found.")
    return profile


@router.get("/status", response_model=ArenaStatusRead)
def read_arena_status():
    return {**get_arena_service().status(), "enabled": bool(get_settings().arena_enabled)}


@router.websocket("/ws")
async def arena_socket(websocket: WebSocket):
    if not get_settings().arena_enabled:
        await websocket.close(code=4403, reason="Arena is disabled.")
        return
    player_id = websocket.query_params.get("player_id", "").strip()
    display_name = websocket.query_params.get("display_name", "").strip() or player_id
    mode = websocket.query_params.get("mode", "ranked").strip().lower() or "ranked"
    if not player_id:
        await websocket.close(code=4400, reason="player_id is required")
        return
    if mode not in {"ranked", "bot"}:
        await websocket.close(code=4400, reason="Unsupported mode")
        return

    service = get_arena_service()
    await service.connect(websocket, player_id, display_name, mode)
    try:
        while True:
            payload = await websocket.receive_json()
            if not isinstance(payload, dict):
                raise HTTPException(status_code=400, detail="Arena payloads must be JSON objects.")
            await service.handle_message(player_id, payload)
    except WebSocketDisconnect:
        await service.disconnect(player_id)
