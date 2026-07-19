import redis.asyncio as redis
import logging
from app.core.config import settings

logger = logging.getLogger(__name__)

try:
    redis_pool = redis.ConnectionPool.from_url(settings["REDIS_URL"], decode_responses=True)
    redis_client = redis.Redis(connection_pool=redis_pool)
except Exception as e:
    logger.error(f"Failed to initialize Redis pool: {e}")
    redis_client = None

async def get_redis():
    """Dependency to inject Redis client into routes/services."""
    if not redis_client:
        logger.warning("Redis client is unavailable. Proceeding with degraded state.")
    return redis_client
