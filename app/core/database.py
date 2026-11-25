"""
Database Connection and Pool Management
Handles SQLAlchemy and aiomysql connections
"""

import logging
from typing import Optional
import aiomysql

from .config import (
    DATABASE_URL, DB_HOST, DB_PORT, DB_USER, DB_PASS, DB_NAME,
    DB_POOL_MIN, DB_POOL_MAX, log
)

_db_pool: Optional[aiomysql.Pool] = None

async def init_db_pool():
    """Initialize the database connection pool"""
    global _db_pool
    try:
        _db_pool = await aiomysql.create_pool(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASS,
            db=DB_NAME,
            minsize=DB_POOL_MIN,
            maxsize=DB_POOL_MAX,
            echo=False,
            charset='utf8mb4',
            autocommit=False
        )
        log.info(f"[DB] Connection pool initialized: minsize={DB_POOL_MIN} maxsize={DB_POOL_MAX} charset=utf8mb4")
        log.info(f"[DB] ✅ UTF-8 ENCODING ENFORCED: All connections use charset=utf8mb4 (full UTF-8 support for Hindi, English, and multi-language text)")
        return _db_pool
    except Exception as e:
        log.warning(f"[DB] Pool initialization failed: {e}")
        log.warning("[DB] Running in offline mode - database features will be unavailable")
        _db_pool = None
        return None

async def close_db_pool():
    """Close the database connection pool"""
    global _db_pool
    if _db_pool:
        _db_pool.close()
        await _db_pool.wait_closed()
        log.info("[DB] Connection pool closed")
        _db_pool = None

def get_db_pool() -> Optional[aiomysql.Pool]:
    """Get the global database pool"""
    return _db_pool

async def execute_query(query: str, params: tuple = ()):
    """Execute a database query"""
    if not _db_pool:
        log.warning("[DB] Query skipped - database pool not available")
        return []

    try:
        async with _db_pool.acquire() as conn:
            await conn.set_charset('utf8mb4')
            async with conn.cursor() as cur:
                await cur.execute(query, params)
                result = await cur.fetchall()
                await conn.commit()
                return result
    except Exception as e:
        log.error(f"[DB] Query execution error: {e}")
        raise

async def execute_insert(query: str, params: tuple = ()):
    """Execute an insert query and return the inserted ID"""
    if not _db_pool:
        log.warning("[DB] Insert skipped - database pool not available")
        return None

    try:
        async with _db_pool.acquire() as conn:
            await conn.set_charset('utf8mb4')
            async with conn.cursor() as cur:
                await cur.execute(query, params)
                await conn.commit()
                return cur.lastrowid
    except Exception as e:
        log.error(f"[DB] Insert execution error: {e}")
        raise
