import io
import json
import uuid
import hashlib
import asyncio
from datetime import datetime, timezone
import logging
import sys
import os

try:
    from google.cloud import storage
except ImportError:
    storage = None

logger = logging.getLogger("audit_logging")
logger.setLevel(logging.INFO)
if not logger.handlers:
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(ch)

class AuditEventBuilder:
    """
    Constructs a compliance snapshot for Category 2 events
    and streams it to GCP WORM storage without using local disk space.
    """
    def __init__(self, gcp_bucket_name: str = None):
        self.gcp_bucket_name = gcp_bucket_name or os.environ.get("WORM_BUCKET_NAME", "clax-compliance-audit-vault-prod")
        self.storage_client = storage.Client() if storage else None

    def build_snapshot(self, 
                       user_context: dict, 
                       investor_dna: dict,
                       user_trigger: dict,
                       ai_reasoning: dict,
                       safety_evals: dict,
                       execution_result: dict,
                       disclosures: dict = None) -> dict:
        """
        Builds the structured JSON payload matching the 8 required blocks.
        """
        snapshot = {
            "audit_event_id": str(uuid.uuid4()),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "user_context": user_context,
            "investor_dna_snapshot": investor_dna,
            "user_trigger": user_trigger,
            "ai_recommendation_and_reasoning": ai_reasoning,
            "safety_and_firewall_evaluations": safety_evals,
            "disclosures_shown_to_user": disclosures or {},
            "execution_result": execution_result
        }
        return snapshot

    async def stream_to_worm_vault(self, snapshot: dict) -> str:
        """
        Streams the dictionary as JSON to GCP Cloud Storage directly from memory.
        Returns the SHA-256 hash of the payload for database linking (Non-Repudiation).
        """
        json_payload = json.dumps(snapshot, indent=2)
        payload_bytes = json_payload.encode('utf-8')
        
        # Calculate SHA-256 for Non-Repudiation
        snapshot_hash = hashlib.sha256(payload_bytes).hexdigest()
        
        # Async execution to avoid blocking the main event loop (e.g. mobile client waits)
        await asyncio.to_thread(self._upload_to_gcp, snapshot, payload_bytes)
        
        return snapshot_hash

    def _upload_to_gcp(self, snapshot: dict, payload_bytes: bytes):
        if not self.storage_client:
            logger.warning("GCP Storage SDK not installed or configured. Mocking WORM upload.")
            return

        user_id = snapshot.get("user_context", {}).get("user_id", "unknown_user")
        event_id = snapshot.get("audit_event_id")
        
        # Immutable artifacts mapped cleanly by user
        cloud_key = f"user_reports/{user_id}/audit_snapshot_{event_id}.json"
        
        try:
            bucket = self.storage_client.bucket(self.gcp_bucket_name)
            blob = bucket.blob(cloud_key)
            
            # Stream directly from in-memory byte buffer (No /tmp file usage)
            file_buffer = io.BytesIO(payload_bytes)
            blob.upload_from_file(file_buffer, content_type="application/json")
            
            logger.info(f"Successfully streamed audit snapshot to GCP WORM vault: {cloud_key}")
        except Exception as e:
            logger.error(f"Failed to upload WORM snapshot to GCP: {e}")
            # Depending on business rules, we might want to raise, or gracefully degrade to local DB.
            # raise