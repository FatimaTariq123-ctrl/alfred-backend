"""
Alpaca Company Universe Provider (§3, Batch Feeder)

Fetches active, tradable US-listed common equities from the Alpaca API.
Provides the company list (ticker + name) to feed into the CLAX Filing Intelligence pipeline.

All filing data remains strictly sourced from SEC EDGAR.
"""

import logging
import re
import requests
from typing import List, Dict, Any, Optional

from config.settings import ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL, MAX_COMPANIES
from config.policy import PolicyConfig, DEFAULT_POLICY

logger = logging.getLogger(__name__)


def get_alpaca_company_universe(
    limit: Optional[int] = None,
    policy: Optional[PolicyConfig] = None
) -> List[Dict[str, str]]:
    """
    Fetches US-listed common equities (ticker and name) from Alpaca Assets API.
    
    Filters for:
    - Active & tradable US equities on major exchanges (NYSE, NASDAQ, AMEX, ARCA, BATS)
    - Excludes ETFs, ETNs, funds, trusts, preferred shares, warrants, rights, unit classes, and OTC assets.
    
    Applies deterministic sorting by ticker before returning up to `limit` companies.
    Fails closed if credentials are missing, API call fails, or no assets match.
    """
    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        raise ValueError(
            "Alpaca API credentials missing! Please configure ALPACA_API_KEY and "
            "ALPACA_SECRET_KEY in your .env file."
        )

    url = f"{ALPACA_BASE_URL}/v2/assets"
    params = {
        "status": "active",
        "asset_class": "us_equity"
    }
    headers = {
        "APCA-API-KEY-ID": ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
        "Accept": "application/json"
    }

    logger.info(f"Fetching US company universe from Alpaca Assets API ({url})...")
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)
    except Exception as e:
        raise RuntimeError(f"Failed to connect to Alpaca API endpoint '{url}': {str(e)}") from e

    if response.status_code != 200:
        raise RuntimeError(
            f"Alpaca API returned HTTP status code {response.status_code}: {response.text}"
        )

    try:
        raw_assets = response.json()
    except Exception as e:
        raise RuntimeError(f"Failed to parse JSON response from Alpaca API: {str(e)}") from e

    if not isinstance(raw_assets, list) or len(raw_assets) == 0:
        raise RuntimeError("Alpaca API returned an empty asset list or invalid payload structure.")

    # Target exchanges for US major listed equities
    allowed_exchanges = {"NYSE", "NASDAQ", "AMEX", "ARCA", "BATS"}
    
    # Keyword patterns to exclude non-common equities (ETFs, Funds, Warrants, Preferreds, etc.)
    exclude_keywords = [
        "ETF", "ETN", "FUND", "TRUST", "PREFERRED", "WARRANT", "RIGHT",
        "UNIT", "ACQUISITION CORP", "DEPOSITARY", "INDEX"
    ]

    # Keyword patterns indicating ADRs, foreign ordinary shares, or depositary receipts (non-US-GAAP)
    adr_keywords = [
        "ADR", "AMERICAN DEPOSITARY", "SPONSORED ADR",
        "ADS", "REPRESENTING", "ORD SHS", "ORDINARY SHARES", "GLOBAL DEPOSITARY", "GDR"
    ]

    filtered_companies: List[Dict[str, str]] = []
    non_us_gaap_filtered_count = 0

    for asset in raw_assets:
        # 1. Active & Tradable check
        if not asset.get("tradable") or asset.get("status") != "active":
            continue

        symbol = str(asset.get("symbol", "")).strip().upper()
        name = str(asset.get("name", "")).strip()
        exchange = str(asset.get("exchange", "")).strip().upper()

        # 2. Exchange check (exclude OTC and unrecognized venues)
        if exchange not in allowed_exchanges:
            continue

        # 3. Ticker format check (US common stocks are 1-5 letters without dots, hyphens, or special chars)
        if not re.match(r"^[A-Z]{1,5}$", symbol):
            continue

        # 4. Check Alpaca asset attributes & country metadata for ADR / non-US filers
        attributes = asset.get("attributes") or []
        if isinstance(attributes, list) and any("adr" in str(attr).lower() or "foreign" in str(attr).lower() for attr in attributes):
            non_us_gaap_filtered_count += 1
            continue

        country = str(asset.get("country", "")).strip().upper()
        if country and country not in {"US", "USA", "UNITED STATES"}:
            non_us_gaap_filtered_count += 1
            continue

        # 5. Name keyword exclusion check (general equity & ADR/foreign checks)
        name_upper = name.upper()
        if any(kw in name_upper for kw in exclude_keywords):
            continue

        if any(kw in name_upper for kw in adr_keywords):
            non_us_gaap_filtered_count += 1
            continue

        filtered_companies.append({
            "ticker": symbol,
            "name": name,
            "exchange": exchange
        })

    if not filtered_companies:
        raise RuntimeError(
            "No valid US common equity assets found after applying exchange and equity filters."
        )

    # Deterministic sorting by ticker to guarantee C10 reproducibility
    filtered_companies.sort(key=lambda c: c["ticker"])

    # Determine effective limit
    effective_limit = limit
    if effective_limit is None:
        if policy is not None and hasattr(policy, "max_companies"):
            effective_limit = policy.max_companies
        else:
            effective_limit = MAX_COMPANIES

    if effective_limit and effective_limit > 0:
        selected_companies = filtered_companies[:effective_limit]
    else:
        selected_companies = filtered_companies

    logger.info(
        f"Filtered {len(filtered_companies)} tradable US common equities from Alpaca "
        f"({non_us_gaap_filtered_count} non-US-GAAP / ADR / foreign assets filtered out). "
        f"Selected top {len(selected_companies)} companies (limit={effective_limit})."
    )

    return selected_companies
