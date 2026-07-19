import logging
import json
from redis.asyncio import Redis

logger = logging.getLogger(__name__)

class IdempotencyEngine:
    """
    Implements Task A5: Redis Atomic Lock Engine.
    """
    def __init__(self, redis_client: Redis):
        self.redis = redis_client

    def _get_key(self, user_id: str, idempotency_key: str) -> str:
        return f"idempotency:{user_id}:{idempotency_key}"

    async def acquire_lock(self, user_id: str, idempotency_key: str) -> bool:
        """Attempt to acquire a SET NX EX 86400 lock."""
        if not self.redis:
            logger.warning("Redis unavailable. Bypassing lock acquisition (graceful fallback).")
            return True

        key = self._get_key(user_id, idempotency_key)
        try:
            # SET NX EX 86400
            acquired = await self.redis.set(key, "PROCESSING", nx=True, ex=86400)
            return bool(acquired)
        except Exception as e:
            logger.error(f"Redis error during acquire_lock: {e}")
            return True # Graceful fallback fail-open

    async def get_status(self, user_id: str, idempotency_key: str) -> str:
        """Fetch the current state of the key (PROCESSING or cached payload)."""
        if not self.redis:
            return None

        key = self._get_key(user_id, idempotency_key)
        try:
            status = await self.redis.get(key)
            return status
        except Exception as e:
            logger.error(f"Redis error during get_status: {e}")
            return None

    async def set_success(self, user_id: str, idempotency_key: str, payload: dict):
        """Update the lock with the final successful JSON response payload."""
        if not self.redis:
            logger.warning("Redis unavailable. Bypassing set_success.")
            return

        key = self._get_key(user_id, idempotency_key)
        try:
            payload_str = json.dumps(payload)
            # Retain the TTL when overwriting
            ttl = await self.redis.ttl(key)
            if ttl > 0:
                await self.redis.set(key, payload_str, ex=ttl)
            else:
                await self.redis.set(key, payload_str, ex=86400)
        except Exception as e:
            logger.error(f"Redis error during set_success: {e}")

    async def release_lock(self, user_id: str, idempotency_key: str):
        """Delete the lock (used for rollbacks/vetoes)."""
        if not self.redis:
            return

        key = self._get_key(user_id, idempotency_key)
        try:
            await self.redis.delete(key)
        except Exception as e:
            logger.error(f"Redis error during release_lock: {e}")
