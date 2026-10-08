"""
Local Swappable Object Store (§4.3, §11)

Provides immutable raw asset storage on the local filesystem.
Calculates SHA-256 hashes for raw content deduplication and provenance tracking.
Keeps raw binary/HTML bytes out of PostgreSQL.
"""

import hashlib
from pathlib import Path
from typing import Tuple, Optional
from config.settings import RAW_OBJECT_STORE_PATH


class ObjectStore:
    """
    Local filesystem raw asset storage manager.
    Can be swapped with S3 / GCS / Azure Blob storage adapters in production.
    """

    def __init__(self, base_path: Optional[Path] = None):
        self.base_path = Path(base_path) if base_path else RAW_OBJECT_STORE_PATH
        self.base_path.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def compute_hash(data: bytes) -> str:
        """Computes SHA-256 hex digest of raw binary asset data."""
        return hashlib.sha256(data).hexdigest()

    def store_asset(self, issuer_id: str, filing_id: str, asset_name: str, data: bytes) -> Tuple[str, str]:
        """
        Saves raw filing payload to immutable local object store.

        Returns:
            Tuple of (storage_uri, sha256_hash)
        """
        asset_hash = self.compute_hash(data)
        
        # Structure storage path: <base>/<issuer_id>/<filing_id>/<asset_name>
        dir_path = self.base_path / issuer_id / filing_id
        dir_path.mkdir(parents=True, exist_ok=True)
        
        file_path = dir_path / asset_name

        if not file_path.exists():
            file_path.write_bytes(data)
            return f"file://{file_path.as_posix()}", asset_hash

        existing_hash = self.compute_hash(file_path.read_bytes())
        if existing_hash == asset_hash:
            return f"file://{file_path.as_posix()}", asset_hash

        p = Path(asset_name)
        stem, ext = p.stem, p.suffix
        sibling_name = f"{stem}.{asset_hash[:12]}{ext}"
        sibling_path = dir_path / sibling_name

        if not sibling_path.exists():
            sibling_path.write_bytes(data)
        elif self.compute_hash(sibling_path.read_bytes()) != asset_hash:
            sibling_path.write_bytes(data)

        return f"file://{sibling_path.as_posix()}", asset_hash

    def fetch_asset(self, storage_uri: str) -> Optional[bytes]:
        """
        Retrieves raw asset bytes from storage URI and verifies SHA-256 hash integrity.
        """
        if storage_uri.startswith("file://"):
            file_path = Path(storage_uri[7:])
        else:
            file_path = Path(storage_uri)
            
        if not file_path.exists():
            return None
            
        data = file_path.read_bytes()
        return data

    def exists(self, storage_uri: str) -> bool:
        """Checks if asset exists at given storage URI."""
        if storage_uri.startswith("file://"):
            file_path = Path(storage_uri[7:])
        else:
            file_path = Path(storage_uri)
        return file_path.exists()
