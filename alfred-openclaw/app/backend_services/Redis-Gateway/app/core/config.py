import os
import sys
import logging

# Twelve-Factor App: logs to stdout
logging.basicConfig(stream=sys.stdout, level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()]
)

def get_settings():
    """Fetches configuration details directly from the running OS environment."""
    jwt_secret = os.environ.get("JWT_SECRET")
    if not jwt_secret:
        raise RuntimeError("JWT_SECRET environment variable is required")

    return {
        "REDIS_URL": os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
        "JWT_SECRET": jwt_secret,
        "DATABASE_URL": os.environ.get("DATABASE_URL", "")
    }

settings = get_settings()