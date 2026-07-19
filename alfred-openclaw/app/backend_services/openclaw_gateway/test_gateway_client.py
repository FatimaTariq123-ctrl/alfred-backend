"""Integration tests for GatewayClient.

All Gateway HTTP calls are mocked via ``respx`` — no running OpenClaw
instance is required.
"""

import json

import httpx
import pytest
import respx

from app.backend_services.openclaw_gateway.gateway_client import (
    GatewayClient,
    GatewayConnectionError,
    GatewayResponseError,
    GatewayUnexpectedResponseError,
)

GATEWAY_URL = "http://test-gateway:18789"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(**overrides) -> GatewayClient:
    """Build a ``GatewayClient`` with deterministic config values."""
    defaults = dict(
        base_url=GATEWAY_URL,
        token="test-token",
        agent_id="main",
        default_model=None,
        timeout=5.0,
    )
    defaults.update(overrides)

    client = GatewayClient.__new__(GatewayClient)
    client._base_url = defaults["base_url"].rstrip("/")
    client._token = defaults["token"]
    client._agent_id = defaults["agent_id"]
    client._default_model = defaults["default_model"]
    client._timeout = defaults["timeout"]
    client._client = None
    return client


def _responses_payload(text: str, *, status: str = "completed") -> dict:
    """Return a well-formed OpenResponses result body."""
    return {
        "id": "resp_001",
        "status": status,
        "output": [
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": text},
                ],
            }
        ],
    }


# ---------------------------------------------------------------------------
# connect() tests
# ---------------------------------------------------------------------------

class TestConnect:
    """Verify connect() health-check behaviour."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_success_via_health_endpoint(self):
        """Successful connection when /health returns 200."""
        respx.get(f"{GATEWAY_URL}/health").mock(
            return_value=httpx.Response(200, json={"status": "ok"})
        )
        client = _make_client()
        await client.connect()
        assert client._client is not None
        await client.disconnect()

    @respx.mock
    @pytest.mark.asyncio
    async def test_success_via_models_fallback(self):
        """Connection succeeds via /v1/models when /health returns 404."""
        respx.get(f"{GATEWAY_URL}/health").mock(
            return_value=httpx.Response(404)
        )
        respx.get(f"{GATEWAY_URL}/v1/models").mock(
            return_value=httpx.Response(200, json={"data": []})
        )
        client = _make_client()
        await client.connect()
        assert client._client is not None
        await client.disconnect()

    @respx.mock
    @pytest.mark.asyncio
    async def test_gateway_unavailable(self):
        """GatewayConnectionError when the host is unreachable."""
        respx.get(f"{GATEWAY_URL}/health").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )
        client = _make_client()
        with pytest.raises(GatewayConnectionError, match="Cannot reach"):
            await client.connect()
        assert client._client is None

    @respx.mock
    @pytest.mark.asyncio
    async def test_timeout_on_connect(self):
        """GatewayConnectionError when the health probe times out."""
        respx.get(f"{GATEWAY_URL}/health").mock(
            side_effect=httpx.TimeoutException("timed out")
        )
        client = _make_client()
        with pytest.raises(GatewayConnectionError, match="Timeout"):
            await client.connect()
        assert client._client is None

    @respx.mock
    @pytest.mark.asyncio
    async def test_health_returns_server_error(self):
        """GatewayConnectionError when /health returns 500."""
        respx.get(f"{GATEWAY_URL}/health").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        client = _make_client()
        with pytest.raises(GatewayConnectionError, match="unexpected status 500"):
            await client.connect()
        assert client._client is None

    @respx.mock
    @pytest.mark.asyncio
    async def test_models_fallback_also_fails(self):
        """GatewayConnectionError when both /health and /v1/models fail."""
        respx.get(f"{GATEWAY_URL}/health").mock(
            return_value=httpx.Response(404)
        )
        respx.get(f"{GATEWAY_URL}/v1/models").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )
        client = _make_client()
        with pytest.raises(GatewayConnectionError, match="Cannot reach"):
            await client.connect()
        assert client._client is None

    @respx.mock
    @pytest.mark.asyncio
    async def test_connect_is_idempotent(self):
        """Calling connect() twice does not create a second client."""
        respx.get(f"{GATEWAY_URL}/health").mock(
            return_value=httpx.Response(200, json={"status": "ok"})
        )
        client = _make_client()
        await client.connect()
        first = client._client
        await client.connect()
        assert client._client is first
        await client.disconnect()


# ---------------------------------------------------------------------------
# send_chat() tests — successful responses
# ---------------------------------------------------------------------------

class TestSendChatSuccess:
    """Verify send_chat() parses well-formed Gateway responses."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_simple_message(self):
        """Single output_text block is returned as a string."""
        respx.get(f"{GATEWAY_URL}/health").mock(
            return_value=httpx.Response(200, json={"status": "ok"})
        )
        respx.post(f"{GATEWAY_URL}/v1/responses").mock(
            return_value=httpx.Response(
                200,
                json=_responses_payload("Hello, world!"),
            )
        )
        client = _make_client()
        result = await client.send_chat("hi")
        assert result == "Hello, world!"
        await client.disconnect()

    @respx.mock
    @pytest.mark.asyncio
    async def test_multiple_output_text_items(self):
        """All output_text blocks are concatenated in order."""
        respx.get(f"{GATEWAY_URL}/health").mock(
            return_value=httpx.Response(200, json={"status": "ok"})
        )
        respx.post(f"{GATEWAY_URL}/v1/responses").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "resp_002",
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {"type": "output_text", "text": "First part. "},
                                {"type": "output_text", "text": "Second part."},
                            ],
                        }
                    ],
                },
            )
        )
        client = _make_client()
        result = await client.send_chat("tell me more")
        assert result == "First part. Second part."
        await client.disconnect()

    @respx.mock
    @pytest.mark.asyncio
    async def test_multiple_message_items(self):
        """Text from multiple message output items is concatenated."""
        respx.get(f"{GATEWAY_URL}/health").mock(
            return_value=httpx.Response(200, json={"status": "ok"})
        )
        respx.post(f"{GATEWAY_URL}/v1/responses").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "resp_003",
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {"type": "output_text", "text": "Alpha "},
                            ],
                        },
                        {
                            "type": "message",
                            "content": [
                                {"type": "output_text", "text": "Beta"},
                            ],
                        },
                    ],
                },
            )
        )
        client = _make_client()
        result = await client.send_chat("go")
        assert result == "Alpha Beta"
        await client.disconnect()

    @respx.mock
    @pytest.mark.asyncio
    async def test_session_key_sent_as_header(self):
        """session_key is forwarded via x-openclaw-session-key."""
        respx.get(f"{GATEWAY_URL}/health").mock(
            return_value=httpx.Response(200, json={"status": "ok"})
        )
        route = respx.post(f"{GATEWAY_URL}/v1/responses").mock(
            return_value=httpx.Response(
                200, json=_responses_payload("ok")
            )
        )
        client = _make_client()
        await client.send_chat("hi", session_key="sess-42")
        req = route.calls[0].request
        assert req.headers["x-openclaw-session-key"] == "sess-42"
        await client.disconnect()

    @respx.mock
    @pytest.mark.asyncio
    async def test_custom_model_forwarded(self):
        """An explicit model overrides the default."""
        respx.get(f"{GATEWAY_URL}/health").mock(
            return_value=httpx.Response(200, json={"status": "ok"})
        )
        route = respx.post(f"{GATEWAY_URL}/v1/responses").mock(
            return_value=httpx.Response(
                200, json=_responses_payload("ok")
            )
        )
        client = _make_client()
        await client.send_chat("go", model="openclaw:custom-agent")
        body = json.loads(route.calls[0].request.content)
        assert body["model"] == "openclaw:custom-agent"
        await client.disconnect()


# ---------------------------------------------------------------------------
# send_chat() tests — error / edge-case responses
# ---------------------------------------------------------------------------

class TestSendChatErrors:
    """Verify send_chat() raises on malformed or error Gateway responses."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_http_error_status(self):
        """GatewayResponseError on non-200 HTTP status."""
        respx.get(f"{GATEWAY_URL}/health").mock(
            return_value=httpx.Response(200, json={"status": "ok"})
        )
        respx.post(f"{GATEWAY_URL}/v1/responses").mock(
            return_value=httpx.Response(
                401,
                json={"error": {"message": "unauthorized", "type": "auth_error"}},
            )
        )
        client = _make_client()
        with pytest.raises(GatewayResponseError, match="401"):
            await client.send_chat("secret")
        await client.disconnect()

    @respx.mock
    @pytest.mark.asyncio
    async def test_non_json_response_body(self):
        """GatewayUnexpectedResponseError when response is not JSON."""
        respx.get(f"{GATEWAY_URL}/health").mock(
            return_value=httpx.Response(200, json={"status": "ok"})
        )
        respx.post(f"{GATEWAY_URL}/v1/responses").mock(
            return_value=httpx.Response(200, text="not json at all")
        )
        client = _make_client()
        with pytest.raises(GatewayUnexpectedResponseError, match="Invalid JSON"):
            await client.send_chat("hi")
        await client.disconnect()

    @respx.mock
    @pytest.mark.asyncio
    async def test_completed_with_no_output(self):
        """GatewayUnexpectedResponseError when output text is missing."""
        respx.get(f"{GATEWAY_URL}/health").mock(
            return_value=httpx.Response(200, json={"status": "ok"})
        )
        respx.post(f"{GATEWAY_URL}/v1/responses").mock(
            return_value=httpx.Response(
                200,
                json={"id": "resp_x", "status": "completed", "output": []},
            )
        )
        client = _make_client()
        with pytest.raises(GatewayUnexpectedResponseError, match="no assistant text"):
            await client.send_chat("hi")
        await client.disconnect()

    @respx.mock
    @pytest.mark.asyncio
    async def test_failed_status(self):
        """GatewayResponseError when status is 'failed'."""
        respx.get(f"{GATEWAY_URL}/health").mock(
            return_value=httpx.Response(200, json={"status": "ok"})
        )
        respx.post(f"{GATEWAY_URL}/v1/responses").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "resp_f",
                    "status": "failed",
                    "error": {"message": "agent crashed", "type": "server_error"},
                },
            )
        )
        client = _make_client()
        with pytest.raises(GatewayResponseError, match="agent crashed"):
            await client.send_chat("hi")
        await client.disconnect()

    @respx.mock
    @pytest.mark.asyncio
    async def test_unexpected_status_value(self):
        """GatewayUnexpectedResponseError on an unknown status string."""
        respx.get(f"{GATEWAY_URL}/health").mock(
            return_value=httpx.Response(200, json={"status": "ok"})
        )
        respx.post(f"{GATEWAY_URL}/v1/responses").mock(
            return_value=httpx.Response(
                200,
                json={"id": "resp_u", "status": "in_progress"},
            )
        )
        client = _make_client()
        with pytest.raises(GatewayUnexpectedResponseError, match="in_progress"):
            await client.send_chat("hi")
        await client.disconnect()

    @respx.mock
    @pytest.mark.asyncio
    async def test_send_chat_timeout(self):
        """GatewayConnectionError when the chat request times out."""
        respx.get(f"{GATEWAY_URL}/health").mock(
            return_value=httpx.Response(200, json={"status": "ok"})
        )
        respx.post(f"{GATEWAY_URL}/v1/responses").mock(
            side_effect=httpx.TimeoutException("read timed out")
        )
        client = _make_client()
        with pytest.raises(GatewayConnectionError, match="Timeout"):
            await client.send_chat("hi")
        await client.disconnect()

    @respx.mock
    @pytest.mark.asyncio
    async def test_send_chat_connection_error(self):
        """GatewayConnectionError when the connection drops mid-request."""
        respx.get(f"{GATEWAY_URL}/health").mock(
            return_value=httpx.Response(200, json={"status": "ok"})
        )
        respx.post(f"{GATEWAY_URL}/v1/responses").mock(
            side_effect=httpx.ConnectError("connection reset")
        )
        client = _make_client()
        with pytest.raises(GatewayConnectionError, match="Cannot reach"):
            await client.send_chat("hi")
        await client.disconnect()

    @respx.mock
    @pytest.mark.asyncio
    async def test_output_text_with_missing_text_field(self):
        """Blocks without a 'text' field are silently skipped."""
        respx.get(f"{GATEWAY_URL}/health").mock(
            return_value=httpx.Response(200, json={"status": "ok"})
        )
        respx.post(f"{GATEWAY_URL}/v1/responses").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "resp_m",
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {"type": "output_text"},  # no text
                                {"type": "output_text", "text": "valid"},
                            ],
                        }
                    ],
                },
            )
        )
        client = _make_client()
        result = await client.send_chat("hi")
        assert result == "valid"
        await client.disconnect()

    @respx.mock
    @pytest.mark.asyncio
    async def test_output_with_non_message_items(self):
        """Non-'message' output items are ignored without error."""
        respx.get(f"{GATEWAY_URL}/health").mock(
            return_value=httpx.Response(200, json={"status": "ok"})
        )
        respx.post(f"{GATEWAY_URL}/v1/responses").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "resp_nm",
                    "status": "completed",
                    "output": [
                        {"type": "function_call", "name": "tool", "arguments": "{}"},
                        {
                            "type": "message",
                            "content": [
                                {"type": "output_text", "text": "after tool"},
                            ],
                        },
                    ],
                },
            )
        )
        client = _make_client()
        result = await client.send_chat("use tool")
        assert result == "after tool"
        await client.disconnect()


# ---------------------------------------------------------------------------
# disconnect() / ensure_connected() tests
# ---------------------------------------------------------------------------

class TestLifecycle:
    """Verify disconnect and reconnect behaviour."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_disconnect_cleans_up(self):
        """After disconnect(), _client is None."""
        respx.get(f"{GATEWAY_URL}/health").mock(
            return_value=httpx.Response(200, json={"status": "ok"})
        )
        client = _make_client()
        await client.connect()
        await client.disconnect()
        assert client._client is None

    @respx.mock
    @pytest.mark.asyncio
    async def test_ensure_connected_recreates_client(self):
        """ensure_connected() reconnects when _client is None."""
        respx.get(f"{GATEWAY_URL}/health").mock(
            return_value=httpx.Response(200, json={"status": "ok"})
        )
        client = _make_client()
        assert client._client is None
        await client.ensure_connected()
        assert client._client is not None
        await client.disconnect()

    @respx.mock
    @pytest.mark.asyncio
    async def test_ensure_connected_noop_when_healthy(self):
        """ensure_connected() does nothing when already connected."""
        respx.get(f"{GATEWAY_URL}/health").mock(
            return_value=httpx.Response(200, json={"status": "ok"})
        )
        client = _make_client()
        await client.connect()
        first = client._client
        await client.ensure_connected()
        assert client._client is first
        await client.disconnect()
