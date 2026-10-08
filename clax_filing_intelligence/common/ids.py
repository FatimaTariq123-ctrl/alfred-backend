import hashlib
import json


def stable_id(prefix: str, *parts) -> str:
    """Deterministic id: prefix + first 16 hex of sha256 over the JSON list of parts."""
    raw = json.dumps([None if p is None else str(p) for p in parts], separators=(",", ":"), ensure_ascii=False)
    return f"{prefix}_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"
