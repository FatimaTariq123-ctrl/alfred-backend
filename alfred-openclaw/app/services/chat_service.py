import logging

from app.backend_services.openclaw_gateway import GatewayClient
from app.schemas.chat_schema import ChatRequest, ChatResponse

logger = logging.getLogger(__name__)


class ChatService:
    """Orchestrates a chat request by forwarding it to the OpenClaw Gateway.

    Contains NO LLM, orchestration, routing, or agent logic — it is a
    thin pass-through from the HTTP route to the Gateway client.
    """

    def __init__(self, gateway_client: GatewayClient) -> None:
        self._gateway = gateway_client

    async def handle_chat(self, request: ChatRequest) -> ChatResponse:
        response = await self._gateway.send_chat(
            message=request.message,
            session_key=request.session_key,
            stream=request.stream,
        )
        return ChatResponse(
            response=response,
            session_key=request.session_key,
        )
