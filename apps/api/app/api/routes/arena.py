from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect

from app.services.arena_engine import get_arena_service

router = APIRouter(prefix="/arena", tags=["arena"])


@router.get("/leaderboard")
def read_arena_leaderboard(limit: int = Query(default=12, ge=1, le=50)):
    return get_arena_service().leaderboard(limit=limit)


@router.get("/profiles/{player_id}")
def read_arena_profile(player_id: str):
    return get_arena_service().profile(player_id)


@router.websocket("/ws")
async def arena_socket(websocket: WebSocket):
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
