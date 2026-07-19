import json
import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.schemas.chat_schema import ChatRequest, ChatResponse
from app.services.chat_service import ChatService
from app.backend_services.openclaw_gateway import GatewayClient
from app.backend_services.jwt_auth.security import get_current_user

chat_router = APIRouter()


def get_gateway_client(request: Request) -> GatewayClient:
    """Retrieve the singleton GatewayClient from application state."""
    return request.app.state.gateway_client


# ==========================================
# POST /chat — OpenClaw Gateway chat
# ==========================================
@chat_router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    gateway: GatewayClient = Depends(get_gateway_client),
) -> ChatResponse:
    service = ChatService(gateway_client=gateway)
    return await service.handle_chat(request)


# ==========================================
# E3: Cursor-Based Chat History API
# ==========================================
@chat_router.get("/chat/history")
def get_chat_history(
    room_id: str,
    limit: int = Query(20, le=50),
    cursor: str = None,
    user_id: str = Depends(get_current_user),
):
    """Delta-fetch via timestamp cursor; deprecating full-history endpoints."""
    from sqlalchemy import text
    from app.backend_services.database_service.database_pool import engine

    if cursor:
        query = text("""
            SELECT id, room_id, role, content, created_at
            FROM clax_messages
            WHERE room_id = :room_id AND created_at < :cursor
            ORDER BY created_at DESC
            LIMIT :limit
        """)
        params = {"room_id": room_id, "cursor": cursor, "limit": limit}
    else:
        query = text("""
            SELECT id, room_id, role, content, created_at
            FROM clax_messages
            WHERE room_id = :room_id
            ORDER BY created_at DESC
            LIMIT :limit
        """)
        params = {"room_id": room_id, "limit": limit}

    try:
        with engine.connect() as conn:
            results = conn.execute(query, params).fetchall()

        messages = [dict(row._mapping) for row in results]

        next_cursor = None
        if len(messages) == limit:
            last_dt = messages[-1]["created_at"]
            next_cursor = last_dt.isoformat() if isinstance(last_dt, datetime) else str(last_dt)

        return {
            "messages": messages,
            "next_cursor": next_cursor,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


# ==========================================
# Message Submit (202 Accepted Workflow)
# ==========================================
class MessageSubmit(BaseModel):
    room_id: str
    content: str


@chat_router.post("/chat/messages", status_code=202)
def submit_message(msg: MessageSubmit, user_id: str = Depends(get_current_user)):
    """
    Instead of a blocking response, return 202 Accepted.
    Mobile connects to the SSE stream using the returned message_id.
    """
    reply_message_id = f"msg_ai_{datetime.utcnow().timestamp()}"

    return {
        "status": "Accepted",
        "message_id": reply_message_id,
        "detail": "Connect to /api/v1/chat/stream?message_id=<id> for token stream",
    }


# ==========================================
# E1: Build SSE Gateway (Real-Time Streaming)
# ==========================================
@chat_router.get("/chat/stream")
async def chat_stream(message_id: str, user_id: str = Depends(get_current_user)):
    """
    Emits agent milestones + token chunks for mobile Shimmer UI.
    Listens to Redis-like event broker channels.
    """
    from app.services.openclaw_router import event_broker, execute_agent_step, AgentInstance

    async def event_generator():
        channel = f"updates:{user_id}"
        queue = event_broker.subscribe(channel)

        try:
            macro_agent = AgentInstance(
                name="Macro Context",
                status_msg="Macro Context is scanning energy feeds...",
            )
            asyncio.create_task(execute_agent_step(macro_agent, user_id))

            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=5.0)

                    payload = {
                        "event": "agent_state_change",
                        "data": {
                            "current_agent": msg["agent"],
                            "display_text": msg["text"],
                        },
                    }
                    yield f"data: {json.dumps(payload)}\n\n"

                    await asyncio.sleep(2.5)

                    tokens = ["This", " is", " the", " final", " computed", " answer."]
                    for token in tokens:
                        yield f"data: {json.dumps({'event': 'token', 'data': {'token': token}})}\n\n"
                        await asyncio.sleep(0.1)

                    yield f"data: {json.dumps({'event': 'complete', 'data': {'status': 'success'}})}\n\n"
                    break

                except asyncio.TimeoutError:
                    break

        finally:
            if queue in event_broker.subscribers.get(channel, []):
                event_broker.subscribers[channel].remove(queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
