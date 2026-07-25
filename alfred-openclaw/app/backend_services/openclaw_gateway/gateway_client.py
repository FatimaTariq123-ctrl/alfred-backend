import logging
from typing import Any

import httpx

from app.config.config import (
    OPENCLAW_AGENT_ID,
    OPENCLAW_GATEWAY_TOKEN,
    OPENCLAW_GATEWAY_URL,
    OPENCLAW_MODEL,
    OPENCLAW_REQUEST_TIMEOUT,
)

logger = logging.getLogger(__name__)


class GatewayConnectionError(Exception):
    """Raised when the Gateway is unreachable during connect or health check."""


class GatewayResponseError(Exception):
    """Raised when the Gateway returns a non-2xx HTTP response."""


class GatewayUnexpectedResponseError(Exception):
    """Raised when the Gateway response body cannot be parsed."""


class GatewayClient:
    """HTTP client for the OpenClaw Gateway OpenResponses API.

    Communicates exclusively through the documented ``POST /v1/responses``
    endpoint.  Contains NO LLM, orchestration, routing, or agent logic.
    """

    def __init__(self) -> None:
        self._base_url: str = OPENCLAW_GATEWAY_URL.rstrip("/")
        self._token: str | None = OPENCLAW_GATEWAY_TOKEN
        self._agent_id: str = OPENCLAW_AGENT_ID
        self._default_model: str | None = OPENCLAW_MODEL
        self._timeout: float = OPENCLAW_REQUEST_TIMEOUT
        self._client: httpx.AsyncClient | None = None

    def _build_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {
            "x-openclaw-agent-id": self._agent_id,
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def connect(self) -> None:
        """Create the HTTP client and verify the Gateway is healthy.

        Probes ``/health`` first; falls back to ``GET /v1/models`` when the
        Gateway does not expose a ``/health`` endpoint (404).  Raises
        ``GatewayConnectionError`` on any transport, timeout, or unexpected
        status so that callers never silently start with a broken client.
        """
        if self._client is not None:
            return

        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers=self._build_headers(),
            timeout=httpx.Timeout(self._timeout, connect=10.0),
        )

        logger.info(
            "Connecting to OpenClaw Gateway at %s", self._base_url
        )

        try:
            healthy = await self._check_health()
        except Exception:
            self._client = None
            raise

        if not healthy:
            self._client = None
            raise GatewayConnectionError(
                f"OpenClaw Gateway at {self._base_url} is not healthy"
            )

        logger.info("Connected to OpenClaw Gateway")

    async def _check_health(self) -> bool:
        """Return ``True`` when the Gateway responds to a health probe.

        Tries ``GET /health`` first.  If the Gateway returns 404 (no such
        endpoint) the method falls back to ``GET /v1/models`` and considers
        any 2xx response proof of liveness.
        """
        assert self._client is not None

        # --- primary probe: /health ---
        try:
            resp = await self._client.get("/health")
        except httpx.TimeoutException as exc:
            raise GatewayConnectionError(
                f"Timeout waiting for OpenClaw Gateway at {self._base_url}: {exc}"
            ) from exc
        except httpx.RequestError as exc:
            raise GatewayConnectionError(
                f"Cannot reach OpenClaw Gateway at {self._base_url}: {exc}"
            ) from exc

        if resp.is_success:
            logger.debug("/health returned %s", resp.status_code)
            return True

        if resp.status_code != 404:
            raise GatewayConnectionError(
                f"OpenClaw Gateway /health returned unexpected status "
                f"{resp.status_code}: {resp.text[:300]}"
            )

        # --- fallback probe: /v1/models ---
        logger.debug("/health not found; falling back to /v1/models")
        try:
            resp = await self._client.get("/v1/models")
        except httpx.TimeoutException as exc:
            raise GatewayConnectionError(
                f"Timeout waiting for OpenClaw Gateway at {self._base_url}: {exc}"
            ) from exc
        except httpx.RequestError as exc:
            raise GatewayConnectionError(
                f"Cannot reach OpenClaw Gateway at {self._base_url}: {exc}"
            ) from exc

        if not resp.is_success:
            raise GatewayConnectionError(
                f"OpenClaw Gateway /v1/models returned unexpected status "
                f"{resp.status_code}: {resp.text[:300]}"
            )

        logger.debug("/v1/models returned %s", resp.status_code)
        return True

    async def disconnect(self) -> None:
        """Close the HTTP client cleanly."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            logger.info("Disconnected from OpenClaw Gateway")

    async def ensure_connected(self) -> None:
        """Recreate the client if it has been closed."""
        if self._client is None or self._client.is_closed:
            logger.warning("HTTP client not available; reconnecting")
            await self.connect()

    async def send_chat(
        self,
        message: str,
        session_key: str | None = None,
        model: str | None = None,
        stream: bool = False,
    ) -> str:
        """Send a chat message via ``POST /v1/responses``.

        Args:
            message: The user's chat message text.
            session_key: Optional session identifier for continuity.
            model: Optional model override (e.g. ``"openclaw:main"``).
            stream: Whether to request SSE streaming (default ``False``).

        Returns:
            The assistant's final text response.

        Raises:
            GatewayConnectionError: If the Gateway is unreachable.
            GatewayResponseError: On non-2xx HTTP status.
            GatewayUnexpectedResponseError: If the response cannot be parsed.
        """
        await self.ensure_connected()
        assert self._client is not None

        request_model = model or self._default_model or "openclaw"

        headers: dict[str, str] = {}
        if session_key:
            headers["x-openclaw-session-key"] = session_key

        body: dict[str, Any] = {
            "model": request_model,
            "input": message,
            "stream": stream,
        }

        logger.info(
            "POST /v1/responses  model=%s stream=%s session_key=%s",
            request_model,
            stream,
            session_key,
        )

        try:
            resp = await self._client.post(
                "/v1/responses",
                json=body,
                headers=headers,
            )
        except httpx.ConnectError as exc:
            raise GatewayConnectionError(
                f"Cannot reach OpenClaw Gateway at {self._base_url}: {exc}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise GatewayConnectionError(
                f"Timeout waiting for OpenClaw Gateway response: {exc}"
            ) from exc

        if resp.status_code != 200:
            error_detail = ""
            try:
                payload = resp.json()
                error_detail = payload.get("error", {}).get("message", "")
            except Exception:
                error_detail = resp.text[:500]
            msg = (
                f"OpenClaw Gateway returned {resp.status_code}"
                + (f": {error_detail}" if error_detail else "")
            )
            if resp.status_code == 404:
                msg += (
                    ". The /v1/responses endpoint may be disabled; "
                    "enable it with "
                    "gateway.http.endpoints.responses.enabled=true "
                    "in openclaw.json"
                )
            raise GatewayResponseError(msg)

        try:
            data = resp.json()
        except Exception as exc:
            raise GatewayUnexpectedResponseError(
                f"Invalid JSON in Gateway response: {exc}"
            ) from exc

        status = data.get("status")
        if status == "completed":
            text = self._extract_text(data)
            if text is None:
                raise GatewayUnexpectedResponseError(
                    "Gateway response contained no assistant text"
                )
            return text
        elif status == "failed":
            error_msg = (
                data.get("error", {}).get("message")
                or "Unknown Gateway error"
            )
            raise GatewayResponseError(f"Gateway agent run failed: {error_msg}")
        else:
            text = self._extract_text(data)
            if text is not None:
                return text
            raise GatewayUnexpectedResponseError(
                f"Unexpected Gateway response status: {status}"
            )

    @staticmethod
    def _extract_text(data: dict[str, Any]) -> str | None:
        """Extract every assistant text fragment from an OpenResponses result.

        Walks the ``output`` array in order, and for every ``message`` item
        collects each ``output_text`` content block.  All fragments are
        concatenated and returned as a single string.

        Returns ``None`` when no ``output_text`` content is found, or when
        ``output`` is missing / not a list.
        """
        output = data.get("output")
        if not isinstance(output, list):
            return None

        fragments: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            if item.get("type") != "message":
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") != "output_text":
                    continue
                text = block.get("text")
                if isinstance(text, str):
                    fragments.append(text)

        return "".join(fragments) if fragments else None
