import os

class Settings:
    DUPLICATE_TRADE_WINDOW_SECONDS: int = int(os.environ.get("DUPLICATE_TRADE_WINDOW_SECONDS", 60))
    AGENT_TEMPERATURE: float = float(os.environ.get("AGENT_TEMPERATURE", 0.7))
    AGENT_SYSTEM_PROMPT: str = os.environ.get("AGENT_SYSTEM_PROMPT", "You are an intelligent trading assistant.")
    DUPLICATE_TRADE_PROMPT: str = os.environ.get(
        "DUPLICATE_TRADE_PROMPT",
        "You just placed an identical order. Are you sure you want to place another?"
    )

    JWT_SECRET: str = os.environ.get("JWT_SECRET", "")

    # OpenClaw Gateway configuration
    OPENCLAW_GATEWAY_URL: str = os.environ.get("OPENCLAW_GATEWAY_URL", "http://localhost:18789")
    OPENCLAW_GATEWAY_TOKEN: str | None = os.environ.get("OPENCLAW_GATEWAY_TOKEN")
    OPENCLAW_MODEL: str | None = os.environ.get("OPENCLAW_MODEL")
    OPENCLAW_AGENT_ID: str = os.environ.get("OPENCLAW_AGENT_ID", "main")
    OPENCLAW_REQUEST_TIMEOUT: float = float(os.environ.get("OPENCLAW_REQUEST_TIMEOUT", "120"))

    def __getitem__(self, item):
        return getattr(self, item)

settings = Settings()

# Backwards compatibility globals
OPENCLAW_GATEWAY_URL = settings.OPENCLAW_GATEWAY_URL
OPENCLAW_GATEWAY_TOKEN = settings.OPENCLAW_GATEWAY_TOKEN
OPENCLAW_MODEL = settings.OPENCLAW_MODEL
OPENCLAW_AGENT_ID = settings.OPENCLAW_AGENT_ID
OPENCLAW_REQUEST_TIMEOUT = settings.OPENCLAW_REQUEST_TIMEOUT
