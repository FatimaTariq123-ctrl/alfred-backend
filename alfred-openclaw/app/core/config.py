import os

settings = {
    "JWT_SECRET": os.environ.get("JWT_SECRET", "")
}

# OpenClaw Gateway configuration (read from environment variables)
OPENCLAW_GATEWAY_URL: str = os.environ.get(
    "OPENCLAW_GATEWAY_URL", "http://localhost:18789"
)
OPENCLAW_GATEWAY_TOKEN: str | None = os.environ.get("OPENCLAW_GATEWAY_TOKEN")
OPENCLAW_MODEL: str | None = os.environ.get("OPENCLAW_MODEL")
OPENCLAW_AGENT_ID: str = os.environ.get("OPENCLAW_AGENT_ID", "main")
OPENCLAW_REQUEST_TIMEOUT: float = float(
    os.environ.get("OPENCLAW_REQUEST_TIMEOUT", "120")
)
