"""
Environment & Global Settings Manager (§17)

Handles environment variables, SEC EDGAR compliance user-agent configuration,
database connections, and local object storage paths.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Base directories
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env if present
load_dotenv(BASE_DIR / ".env")

DEFAULT_DATA_DIR = BASE_DIR / "data" / "raw_object_store"

# Secrets & Config
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
EDGAR_IDENTITY = os.getenv("EDGAR_IDENTITY", "").strip()
RAW_OBJECT_STORE_PATH = Path(os.getenv("RAW_OBJECT_STORE_PATH", str(DEFAULT_DATA_DIR))).resolve()

# Alpaca API Credentials & Batch Config
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "").strip()
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "").strip()
ALPACA_BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets").strip().rstrip("/")
MAX_COMPANIES = int(os.getenv("MAX_COMPANIES", "5"))

# Ensure raw object store directory exists
RAW_OBJECT_STORE_PATH.mkdir(parents=True, exist_ok=True)


def init_edgar_identity():
    """
    Mandatory compliance setup before making any SEC EDGAR API call (§17).
    Requires declared User-Agent with contact info.
    """
    if not EDGAR_IDENTITY:
        raise ValueError(
            "EDGAR_IDENTITY environment variable must be set with contact info "
            "(e.g. EDGAR_IDENTITY='Name email@domain.com') per SEC EDGAR compliance requirements."
        )
    try:
        from edgar import set_identity
        set_identity(EDGAR_IDENTITY)
    except ImportError:
        # edgartools may not be installed in lightweight unit testing environments
        pass
