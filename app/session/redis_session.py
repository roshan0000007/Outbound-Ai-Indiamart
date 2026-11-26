"""
Call Session Manager
Redis-based session management for live AI calling
Manages call state and conversation history during active calls
"""

import json
from typing import Optional, List, Dict, Any
from datetime import datetime

from ..core.redis import get_redis_client
from ..core.config import log

class CallSession:
    """
    Manages Redis session for a single live call
    
    Session structure:
    {
        "call_id": "call_12345",
        "user_id": 101,
        "agent_name": "AI Agent",
        "language": "en",
        "conversation": [
            {
                "sender": "customer/ai",
                "text": "...",
                "timestamp": "2026-08-12T10:30:00Z"
            }
        ],
        "call_status": "active/ended",
        "started_at": "2026-08-12T10:00:00Z"
    }
    """

    SESSION_TTL = 3600
    MAX_CONVERSATION_HISTORY = 20

    def __init__(self):
        self.redis_client = None

    async def initialize(self):
        """Initialize Redis client"""
        self.redis_client = get_redis_client()
        if not self.redis_client:
            log.error("[CallSession] Redis client not available")
            return False
        return True

    async def create_session(
        self,
        call_id: str,
        user_id: int,
        agent_name: str,
        language: str = "en"
    ) -> Optional[Dict]:
        """
        Create a new call session in Redis
        Called when call starts
        
        Args:
            call_id: Unique call identifier
            user_id: User ID
            agent_name: Agent name for welcome
            language: Initial language
            
        Returns:
            Session dict or None if failed
        """
        try:
            if not self.redis_client:
                log.warning("[CallSession] Redis not initialized")
                return None

            session = {
                "call_id": call_id,
                "user_id": user_id,
                "campaign_id": 0,
                "agent_name": agent_name,
                "language": language,
                # ✅ NEW: Per-call voice and persona state
                "response_language": "en-IN",  # Only en-IN or hi-IN
                "detected_language": None,
                "voice_persona": "female",
                "current_question_index": 0,
                "current_field": None,
                "clarification_attempts": {},
                "session_status": "active",
                # ✅ NEW: Track requirements separately
                "current_product": None,
                "conversation": [],
                "call_status": "active",
                "started_at": datetime.utcnow().isoformat(),
                "metadata": {}
            }

            redis_key = f"call:{call_id}"

            await self.redis_client.setex(
                redis_key,
                self.SESSION_TTL,
                json.dumps(session)
            )

            log.info(f"[CallSession] Created session: call_id={call_id}, user_id={user_id}, language={language}, voice=female")
            return session

        except Exception as e:
            log.error(f"[CallSession] Create session error: {e}")
            return None

    async def get_session(self, call_id: str) -> Optional[Dict]:
        """
        STEP 21.6: Get session from Redis
        
        Args:
            call_id: Call identifier
            
        Returns:
            Session dict or None if not found
        """
        try:
            if not self.redis_client:
                return None

            redis_key = f"call:{call_id}"
            data = await self.redis_client.get(redis_key)

            if data:
                return json.loads(data)

            log.warning(f"[CallSession] Session not found: {call_id}")
            return None

        except Exception as e:
            log.error(f"[CallSession] Get session error for {call_id}: {e}")
            return None

    async def update_session(
        self,
        call_id: str,
        updates: Dict[str, Any]
    ) -> bool:
        """
        STEP 21.6: Update session in Redis
        
        Args:
            call_id: Call identifier
            updates: Dictionary of fields to update
            
        Returns:
            True if successful
        """
        try:
            if not self.redis_client:
                return False

            session = await self.get_session(call_id)
            if not session:
                log.warning(f"[CallSession] Cannot update: session not found {call_id}")
                return False

            session.update(updates)

            redis_key = f"call:{call_id}"
            await self.redis_client.setex(
                redis_key,
                self.SESSION_TTL,
                json.dumps(session)
            )

            log.debug(f"[CallSession] Updated session: {call_id}")
            return True

        except Exception as e:
            log.error(f"[CallSession] Update session error for {call_id}: {e}")
            return False

    async def close_session(self, call_id: str) -> bool:
        """
        Close/cleanup session from Redis
        Called when call ends
        
        Args:
            call_id: Call identifier
            
        Returns:
            True if successful
        """
        try:
            if not self.redis_client:
                return False

            redis_key = f"call:{call_id}"
            await self.redis_client.delete(redis_key)

            log.info(f"[CallSession] Closed session: {call_id}")
            return True

        except Exception as e:
            log.error(f"[CallSession] Close session error for {call_id}: {e}")
            return False

    async def get_current_product(self, call_id: str) -> Optional[str]:
        """
        STEP 21.9: Get current product context from session
        Used to filter RAG retrieval
        
        Args:
            call_id: Call identifier
            
        Returns:
            Current product name or None
        """
        try:
            session = await self.get_session(call_id)
            if session:
                return session.get("current_product")
            return None
        except Exception as e:
            log.error(f"[CallSession] Get current product error: {e}")
            return None

    async def set_current_product(
        self,
        call_id: str,
        product: Optional[str]
    ) -> bool:
        """
        STEP 21.18: Update current product context
        Called when customer mentions different product
        
        Args:
            call_id: Call identifier
            product: Product name (Dialer, IVR, SMS, etc.) or None
            
        Returns:
            True if successful
        """
        try:
            old_product = await self.get_current_product(call_id)

            if old_product != product:
                success = await self.update_session(
                    call_id,
                    {"current_product": product}
                )

                if success and old_product:
                    log.info(f"[CallSession] Product change: {call_id} {old_product} → {product}")

                return success

            return True
        except Exception as e:
            log.error(f"[CallSession] Set current product error: {e}")
            return False

    async def set_language(self, call_id: str, language: str) -> bool:
        """
        STEP 21.8: Update detected language
        ✅ ENHANCED: Validate language is en-IN or hi-IN only
        
        Args:
            call_id: Call identifier
            language: Language code (en-IN or hi-IN ONLY)  
            
        Returns:
            True if successful, False if language not supported
        """
        # ✅ STRICT VALIDATION: Only en-IN and hi-IN allowed
        SUPPORTED_RESPONSE_LANGUAGES = ["en-IN", "hi-IN", "en", "hi"]
        DEFAULT_RESPONSE_LANGUAGE = "en-IN"
        
        # Normalize language code
        lang_normalized = language.lower()
        if lang_normalized not in SUPPORTED_RESPONSE_LANGUAGES:
            log.warning(f"[CallSession] Unsupported language attempted: {language}. Defaulting to {DEFAULT_RESPONSE_LANGUAGE}")
            language = DEFAULT_RESPONSE_LANGUAGE
        elif lang_normalized == "en":
            language = "en-IN"
        elif lang_normalized == "hi":
            language = "hi-IN"
        
        return await self.update_session(call_id, {
            "response_language": language,
            "detected_language": language
        })

    async def add_message(
        self,
        call_id: str,
        sender: str,
        text: str,
        product: Optional[str] = None,
        language: Optional[str] = None,
        metadata: Optional[Dict] = None
    ) -> bool:
        """
        STEP 21.20: Add message to conversation history
        ✅ ENHANCED: Track clarification attempts and response quality
        
        Args:
            call_id: Call identifier
            sender: "customer" or "ai"
            text: Message text
            product: Current product context
            language: Message language
            metadata: Optional metadata (grounded, confidence, is_unclear, is_refusal, etc.)
            
        Returns:
            True if successful
        """
        try:
            session = await self.get_session(call_id)
            if not session:
                log.warning(f"[CallSession] Session not found for add_message: {call_id}")
                return False

            message = {
                "sender": sender,
                "text": text,
                "product": product,
                "language": language,
                "timestamp": datetime.utcnow().isoformat(),
                # ✅ NEW: Track response quality
                "is_unclear": False,
                "is_refusal": False,
                "clarification_needed": False,
                "confidence": 1.0
            }

            if metadata:
                message.update(metadata)

            conversation = session.get("conversation", [])
            conversation.append(message)

            if len(conversation) > self.MAX_CONVERSATION_HISTORY:
                conversation = conversation[-self.MAX_CONVERSATION_HISTORY:]

            session["conversation"] = conversation

            return await self.update_session(call_id, {"conversation": conversation})

        except Exception as e:
            log.error(f"[CallSession] Add message error: {e}")
            return False

    async def get_conversation_history(
        self,
        call_id: str,
        limit: Optional[int] = None
    ) -> List[Dict]:
        """
        STEP 21.17: Get conversation history for context building
        Used by LLM to understand context
        
        Args:
            call_id: Call identifier
            limit: Max messages to return (default: last 10)
            
        Returns:
            List of messages
        """
        try:
            session = await self.get_session(call_id)
            if not session:
                return []

            conversation = session.get("conversation", [])

            if limit and len(conversation) > limit:
                conversation = conversation[-limit:]

            return conversation

        except Exception as e:
            log.error(f"[CallSession] Get conversation history error: {e}")
            return []

    async def get_session_summary(self, call_id: str) -> Optional[Dict]:
        """
        Get summary of current session state
        
        Args:
            call_id: Call identifier
            
        Returns:
            Summary dict or None
        """
        try:
            session = await self.get_session(call_id)
            if not session:
                return None

            return {
                "call_id": call_id,
                "user_id": session.get("user_id"),
                "campaign_id": session.get("campaign_id"),
                "current_product": session.get("current_product"),
                "language": session.get("language"),
                "response_language": session.get("response_language"),
                "voice_persona": session.get("voice_persona"),
                "message_count": len(session.get("conversation", [])),
                "status": session.get("call_status"),
                "duration_seconds": self._calculate_duration(session.get("started_at"))
            }
        except Exception as e:
            log.error(f"[CallSession] Get session summary error: {e}")
            return None

    async def track_clarification_attempt(self, call_id: str, field: str, attempt_num: int = 1) -> bool:
        """
        ✅ NEW: Track clarification attempts to prevent infinite loops
        
        Args:
            call_id: Call identifier
            field: Field requiring clarification
            attempt_num: Attempt number (1, 2, 3...)
            
        Returns:
            True if should continue asking (attempt_num < max_attempts), False otherwise
        """
        try:
            MAX_CLARIFICATION_ATTEMPTS = 3
            
            if attempt_num >= MAX_CLARIFICATION_ATTEMPTS:
                log.warning(f"[CallSession] Max clarification attempts reached for {field} in {call_id}")
                # Mark as N/A and move on
                await self.update_session(call_id, {
                    "clarification_attempts": {field: "max_reached"}
                })
                return False
            
            return True
        except Exception as e:
            log.error(f"[CallSession] Track clarification error: {e}")
            return False

    async def mark_refusal(self, call_id: str, field: str) -> bool:
        """
        ✅ NEW: Mark a field as explicitly refused by customer
        Mark as N/A and prevent further asking
        
        Args:
            call_id: Call identifier
            field: Field that was refused
            
        Returns:
            True if successful
        """
        try:
            session = await self.get_session(call_id)
            if not session:
                return False
            
            refusals = session.get("refusals", {})
            refusals[field] = datetime.utcnow().isoformat()
            
            return await self.update_session(call_id, {"refusals": refusals})
        except Exception as e:
            log.error(f"[CallSession] Mark refusal error: {e}")
            return False

    async def get_response_language(self, call_id: str) -> str:
        """
        ✅ NEW: Get the validated response language for this call
        Only returns en-IN or hi-IN
        
        Args:
            call_id: Call identifier
            
        Returns:
            Response language (en-IN or hi-IN), defaults to en-IN
        """
        try:
            session = await self.get_session(call_id)
            if session:
                lang = session.get("response_language", "en-IN")
                if lang in ["en-IN", "hi-IN", "en", "hi"]:
                    return "en-IN" if lang in ["en", "en-IN"] else "hi-IN"
            return "en-IN"
        except:
            return "en-IN"

    def _calculate_duration(self, started_at: Optional[str]) -> int:
        """Calculate call duration in seconds"""
        try:
            if not started_at:
                return 0
            start_time = datetime.fromisoformat(started_at)
            duration = (datetime.utcnow() - start_time).total_seconds()
            return int(duration)
        except:
            return 0

_session_manager: Optional[CallSession] = None

async def init_call_session():
    """Initialize call session manager"""
    global _session_manager
    _session_manager = CallSession()
    success = await _session_manager.initialize()
    if success:
        log.info("[CallSession] Manager initialized")
    return _session_manager

def get_call_session() -> Optional[CallSession]:
    """Get call session manager instance"""
    return _session_manager
