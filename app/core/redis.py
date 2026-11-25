"""
Redis Cache Connection and Management
Handles async Redis operations for caching and session management
"""

import logging
import asyncio
from typing import Optional, Any
import redis.asyncio as aioredis

from .config import REDIS_HOST, REDIS_PORT, REDIS_PASSWORD, REDIS_DB, REDIS_URL, log

_redis_client: Optional[aioredis.Redis] = None

async def init_redis():
    """Initialize the Redis connection"""
    global _redis_client
    try:
        _redis_client = await aioredis.from_url(REDIS_URL)
        await _redis_client.ping()
        log.info(f"[REDIS] Connected: {REDIS_HOST}:{REDIS_PORT} db={REDIS_DB}")
        return _redis_client
    except Exception as e:
        log.warning(f"[REDIS] Connection failed: {e}")
        log.warning("[REDIS] Running in offline mode - caching and session features will be unavailable")
        _redis_client = None
        return None

async def close_redis():
    """Close the Redis connection"""
    global _redis_client
    if _redis_client:
        await _redis_client.close()
        log.info("[REDIS] Connection closed")
        _redis_client = None

def get_redis_client() -> Optional[aioredis.Redis]:
    """Get the global Redis client"""
    return _redis_client

async def get_session(key: str) -> Optional[dict]:
    """Get a session from Redis
    
    RESILIENT: Retries on failure and ensures session TTL is refreshed
    """
    if not _redis_client:
        return None

    max_retries = 3
    retry_delay = 0.05

    for attempt in range(max_retries):
        try:
            data = await _redis_client.get(key)
            if data:
                import json
                session = json.loads(data)

                if key.startswith("call:"):
                    await _redis_client.expire(key, 3600)

                return session
            return None
        except Exception as e:
            if attempt < max_retries - 1:
                log.debug(f"[REDIS] Get error for key {key} (attempt {attempt + 1}/{max_retries}): {e}, retrying...")
                await asyncio.sleep(retry_delay)
                continue
            else:
                log.error(f"[REDIS] Get failed after {max_retries} attempts for key {key}: {e}")
                return None

    return None

async def set_session(key: str, value: dict, ttl: int = 3600) -> bool:
    """Set a session in Redis with TTL
    
    RESILIENT: Retries on failure and logs all operations
    """
    if not _redis_client:
        return False

    max_retries = 3
    retry_delay = 0.05

    for attempt in range(max_retries):
        try:
            import json
            await _redis_client.setex(key, ttl, json.dumps(value))

            verify_data = await _redis_client.get(key)
            if not verify_data:
                if attempt < max_retries - 1:
                    log.debug(f"[REDIS] Verification failed for key {key} (attempt {attempt + 1}/{max_retries}), retrying...")
                    await asyncio.sleep(retry_delay)
                    continue
                else:
                    log.error(f"[REDIS] Verification failed after {max_retries} attempts for key {key}")
                    return False

            return True
        except Exception as e:
            if attempt < max_retries - 1:
                log.debug(f"[REDIS] Set error for key {key} (attempt {attempt + 1}/{max_retries}): {e}, retrying...")
                await asyncio.sleep(retry_delay)
                continue
            else:
                log.error(f"[REDIS] Set failed after {max_retries} attempts for key {key}: {e}")
                return False

    return False

async def delete_session(key: str) -> bool:
    """Delete a session from Redis"""
    if not _redis_client:
        return False

    try:
        await _redis_client.delete(key)
        return True
    except Exception as e:
        log.error(f"[REDIS] Delete error for key {key}: {e}")
        return False

async def get_value(key: str) -> Optional[str]:
    """Get a value from Redis"""
    if not _redis_client:
        return None

    try:
        return await _redis_client.get(key)
    except Exception as e:
        log.error(f"[REDIS] Get error for key {key}: {e}")
        return None

async def set_value(key: str, value: str, ttl: int = 3600) -> bool:
    """Set a value in Redis"""
    if not _redis_client:
        return False

    try:
        await _redis_client.setex(key, ttl, value)
        return True
    except Exception as e:
        log.error(f"[REDIS] Set error for key {key}: {e}")
        return False
