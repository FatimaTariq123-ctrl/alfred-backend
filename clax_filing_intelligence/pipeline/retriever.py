"""
Stage 3: Retriever & Source Document Package Manager (§4.2-4.3, §17)

Fetches original HTML/XBRL/PDF assets from SEC EDGAR.
Enforces SEC rate limits (~10 req/sec) with exponential backoff retry on HTTP 403, 429, 5xx.
Computes SHA-256 hash on retrieval for duplicate suppression and provenance tracking.
Persists raw assets to immutable ObjectStore.
Fails closed on download failure — no mock/synthetic fallbacks allowed (§17).
"""

import time
import uuid
import logging
import requests
from requests.adapters import HTTPAdapter
from typing import List, Optional, Tuple
from datetime import datetime, timezone

from config.settings import EDGAR_IDENTITY
from schema.models import Filing, FilingAsset
from storage.object_store import ObjectStore
from storage.db import DatabaseManager
from common.rate_limiter import SEC_LIMITER
from common.ids import stable_id

logger = logging.getLogger(__name__)


class FilingRetriever:
    def __init__(self, object_store: Optional[ObjectStore] = None, db_manager: Optional[DatabaseManager] = None):
        self.store = object_store or ObjectStore()
        self.db = db_manager or DatabaseManager()
        self.max_retries = 3
        self.base_backoff = 1.0  # seconds
        self.max_single_wait = 8.0  # seconds
        self.conflicts: List[dict] = []

        # Persistent HTTP session for connection reuse across filings
        self.session = requests.Session()
        adapter = HTTPAdapter(pool_connections=20, pool_maxsize=40)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def fetch_missing_assets(self, filings: List[Filing]) -> List[FilingAsset]:
        """
        Downloads missing assets for selected filings, computes SHA-256 hashes,
        and saves raw payloads to immutable storage.
        Fails closed if download fails after retries (§17).
        """
        downloaded_assets: List[FilingAsset] = []
        self.conflicts = []

        for filing in filings:
            # 1. Check existing asset rows in DB
            existing_assets = self.db.get_filing_assets(filing.filing_id)
            reused = False
            for asset in existing_assets:
                if self.store.exists(asset.storage_uri):
                    raw_bytes = self.store.fetch_asset(asset.storage_uri)
                    if raw_bytes is not None and ObjectStore.compute_hash(raw_bytes) == asset.hash:
                        stored_hash = self.db.get_filing_hash(filing.filing_id)
                        if not stored_hash:
                            filing.source_hash = asset.hash
                            self.db.save_filing(filing)
                        elif stored_hash != asset.hash:
                            self.conflicts.append({
                                "accession": filing.accession_number,
                                "filing_id": filing.filing_id,
                                "stored_hash": stored_hash,
                                "new_hash": asset.hash
                            })
                        downloaded_assets.append(asset)
                        reused = True
                        logger.info(f"Reused existing valid asset for filing {filing.accession_number}")
                        break
                    else:
                        logger.warning(f"Asset file missing or hash mismatch for filing {filing.accession_number} at {asset.storage_uri}")

            if reused:
                continue

            logger.info(f"Retrieving source asset for filing {filing.form_type} {filing.accession_number}...")
            
            # Fetch raw content payload from SEC EDGAR with rate-limiting and bounded retry
            content_bytes, mime_type, asset_ext = self._download_filing_payload_with_retry(filing)
            asset_filename = f"{filing.accession_number}.{asset_ext}"
            
            # Store in local swappable ObjectStore
            storage_uri, sha256_hash = self.store.store_asset(
                issuer_id=filing.issuer_id,
                filing_id=filing.filing_id,
                asset_name=asset_filename,
                data=content_bytes
            )

            # Check stored filing hash
            stored_hash = self.db.get_filing_hash(filing.filing_id)
            if stored_hash and stored_hash.strip() and stored_hash != sha256_hash:
                self.conflicts.append({
                    "accession": filing.accession_number,
                    "filing_id": filing.filing_id,
                    "stored_hash": stored_hash,
                    "new_hash": sha256_hash
                })
            else:
                filing.source_hash = sha256_hash
                self.db.save_filing(filing)

            # Record FilingAsset metadata with deterministic ID
            asset_type = "IXBRL" if asset_ext in ["htm", "html", "xml"] else "HTML"
            asset_record = FilingAsset(
                asset_id=stable_id("asset", filing.filing_id, asset_type, sha256_hash),
                filing_id=filing.filing_id,
                asset_type=asset_type,
                storage_uri=storage_uri,
                mime_type=mime_type,
                hash=sha256_hash,
                retrieved_at=datetime.now(timezone.utc)
            )

            self.db.save_filing_asset(asset_record)
            downloaded_assets.append(asset_record)

        logger.info(f"Retrieved and stored {len(downloaded_assets)} raw filing assets with SHA-256 validation.")
        return downloaded_assets

    def _download_filing_payload_with_retry(self, filing: Filing) -> Tuple[bytes, str, str]:
        """
        Downloads filing content from SEC EDGAR with global rate limiting, (5, 30) timeouts, and bounded retries.
        Method 1 (edgartools) and Method 2 (direct SEC HTTP GET) are fallbacks.
        Implements bounded exponential backoff (max 3 attempts, max 8.0s wait) on transient network/throttling errors.
        Fail-fast on 404 permanent errors.
        """
        last_error = None
        for attempt in range(1, self.max_retries + 1):
            # Acquire global SEC TokenBucket rate limit token before network request
            SEC_LIMITER.acquire(tag=f"retriever:{filing.accession_number}")

            try:
                # 1. Try edgartools retriever (isolated inner try/except)
                try:
                    from edgar import get_by_accession_number
                    edgar_f = get_by_accession_number(filing.accession_number)
                    if edgar_f:
                        html_text = edgar_f.html() or edgar_f.text() or ""
                        if html_text and html_text.strip():
                            return html_text.encode("utf-8"), "text/html", "htm"
                except Exception as edgar_err:
                    logger.debug(f"edgartools download unavailable for {filing.accession_number}: {edgar_err}. Falling through to direct SEC HTTP GET.")

                # 2. Try direct SEC HTTP GET using declared User-Agent with explicit (5s connect, 30s read) timeout
                headers = {"User-Agent": EDGAR_IDENTITY}
                resp = self.session.get(filing.source_uri, headers=headers, timeout=(5, 30))

                if resp.status_code == 200 and resp.content:
                    ext = "txt" if filing.source_uri.endswith(".txt") else "htm"
                    mime = "text/plain" if ext == "txt" else "text/html"
                    return resp.content, mime, ext

                # Permanent error 404 -> fail fast without retry
                if resp.status_code == 404:
                    raise RuntimeError(f"Filing asset HTTP 404 Not Found at {filing.source_uri}")

                # Transient throttling or server error
                if resp.status_code in [403, 429, 500, 502, 503, 504]:
                    last_error = f"HTTP {resp.status_code}"
                    if attempt < self.max_retries:
                        wait_time = min(self.max_single_wait, self.base_backoff * (2 ** (attempt - 1)))
                        logger.warning(f"attempt {attempt}/{self.max_retries} failed ({last_error}): retrying in {wait_time:.1f}s...")
                        time.sleep(wait_time)
                        continue

                last_error = f"HTTP status {resp.status_code}"

            except (requests.exceptions.RequestException, RuntimeError, TimeoutError) as e:
                last_error = str(e)
                if "404" in last_error:
                    raise

                if attempt < self.max_retries:
                    wait_time = min(self.max_single_wait, self.base_backoff * (2 ** (attempt - 1)))
                    logger.warning(f"attempt {attempt}/{self.max_retries} failed ({type(e).__name__}: {e}): retrying in {wait_time:.1f}s...")
                    time.sleep(wait_time)
                else:
                    break

        raise RuntimeError(f"Failed to download raw filing asset from SEC EDGAR for accession {filing.accession_number} after {self.max_retries} attempts. Last error: {last_error}.")
