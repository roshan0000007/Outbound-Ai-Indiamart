"""
Conversation Context Manager
Manages live context window per call in Redis
Minimal implementation for core calling functionality
"""

import json
import asyncio
from typing import Optional, Dict, Any, List
from datetime import datetime

from ..core.config import log
from ..core.redis import get_redis_client

class ConversationContextManager:
    """
    Manages per-call live context window in Redis.
    
    Context is stored as:
    - Key: call:{call_id}:context
    - Value: JSON with list of exchanges
    - TTL: 3600 seconds
    
    Exchange structure:
    {
        "customer_message": str,
        "ai_response": str,
        "timestamp": str (ISO),
        "language": str
    }
    """

    def __init__(self):
        self.max_window_size = 10
        self.context_ttl = 3600
        self.context_key_template = "call:{call_id}:context"

    async def initialize_context(self, call_id: str) -> bool:
        """
        Initialize empty context window for a new call.
        
        Args:
            call_id: Unique call identifier
            
        Returns:
            True on success, False on failure
        """
        try:
            if not call_id:
                log.error("[ConversationContext] call_id is empty")
                return False

            context = {
                "call_id": call_id,
                "exchanges": [],
                "created_at": datetime.utcnow().isoformat()
            }

            key = self.context_key_template.format(call_id=call_id)

            redis_client = get_redis_client()
            if redis_client:
                await redis_client.setex(key, self.context_ttl, json.dumps(context))
            else:
                log.warning(f"[ConversationContext] Redis not available: {call_id}")
                return False

            log.info(f"[ConversationContext] ✅ Context initialized for {call_id}")
            return True

        except Exception as e:
            log.error(f"[ConversationContext] initialize_context failed: {e}")
            return False

    async def get_context(self, call_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve live context window for a call.
        
        Args:
            call_id: Unique call identifier
            
        Returns:
            Context dict on success, None if not found
        """
        try:
            if not call_id:
                return None

            key = self.context_key_template.format(call_id=call_id)

            redis_client = get_redis_client()
            if not redis_client:
                log.warning(f"[ConversationContext] Redis not available: {call_id}")
                return None

            data = await redis_client.get(key)
            if data:
                context = json.loads(data)
                return context

            return None

        except Exception as e:
            log.error(f"[ConversationContext] get_context failed: {e}")
            return None

    async def add_exchange(self, call_id: str, exchange: Dict[str, Any]) -> bool:
        """
        Add a customer-AI exchange to the context window.
        
        Args:
            call_id: Call identifier
            exchange: Exchange data with customer_message and ai_response
            
        Returns:
            True on success, False on failure
        """
        try:
            if not call_id or not exchange:
                return False

            context = await self.get_context(call_id)
            if not context:
                await self.initialize_context(call_id)
                context = await self.get_context(call_id)
                if not context:
                    return False

            # Add exchange
            context["exchanges"].append({
                "customer_message": exchange.get("customer_message", ""),
                "ai_response": exchange.get("ai_response", ""),
                "timestamp": exchange.get("timestamp", datetime.utcnow().isoformat()),
                "language": exchange.get("language", "en")
            })

            # Maintain window size
            if len(context["exchanges"]) > self.max_window_size:
                context["exchanges"] = context["exchanges"][-self.max_window_size:]

            # Save back to Redis
            key = self.context_key_template.format(call_id=call_id)
            redis_client = get_redis_client()
            if redis_client:
                await redis_client.setex(key, self.context_ttl, json.dumps(context))

            log.debug(f"[ConversationContext] Exchange added for {call_id}")
            return True

        except Exception as e:
            log.error(f"[ConversationContext] add_exchange failed: {e}")
            return False

    async def cleanup_context(self, call_id: str) -> bool:
        """
        Cleanup context for a call (called on call end).
        
        Args:
            call_id: Call identifier
            
        Returns:
            True on success
        """
        try:
            if not call_id:
                return False

            key = self.context_key_template.format(call_id=call_id)

            redis_client = get_redis_client()
            if redis_client:
                await redis_client.delete(key)

            log.info(f"[ConversationContext] ✅ Context cleaned up for {call_id}")
            return True

        except Exception as e:
            log.error(f"[ConversationContext] cleanup_context failed: {e}")
            return False


_context_manager: Optional[ConversationContextManager] = None

async def init_conversation_context_manager() -> ConversationContextManager:
    """Initialize context manager"""
    global _context_manager
    _context_manager = ConversationContextManager()
    log.info("[ConversationContext] Service initialized")
    return _context_manager

def get_conversation_context_manager() -> Optional[ConversationContextManager]:
    """Get context manager instance"""
    return _context_manager
