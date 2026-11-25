"""
Greeting Service
Handles playing client greeting after call answer
"""

from typing import Optional, Dict, Any
from datetime import datetime

from ..core.config import log
from ..core.client_config import ClientConfig
from ..core.redis import set_session, get_session
from ..services.media_service import get_media_service


class GreetingService:
    """Service for managing greeting playback"""

    def __init__(self):
        self.media_service = get_media_service()
        self.greeting_ttl = 60  # Greeting state TTL

    async def play_greeting(self, call_id: str) -> bool:
        """
        Play the client greeting for a call
        
        Args:
            call_id: Unique call identifier
        
        Returns:
            True if greeting was played successfully
        """
        try:
            log.info(f"[Greeting] Starting greeting for call: {call_id}")
            
            # Check if greeting already played
            greeting_state = await self._get_greeting_state(call_id)
            if greeting_state and greeting_state.get("played"):
                log.warning(f"[Greeting] Greeting already played for {call_id}")
                return False
            
            # Get greeting message
            greeting_text = ClientConfig.get_greeting()
            if not greeting_text:
                log.error("[Greeting] No greeting text configured")
                return False
            
            log.info(f"[Greeting] Greeting text: {greeting_text[:50]}...")
            
            # Mark greeting as played in state
            await self._mark_greeting_played(call_id)
            
            # Note: Actual TTS and audio playback would happen here via media service
            # For now, we're just marking it as handled
            # The actual greeting playback would integrate with the media_service
            
            log.info(f"[Greeting] ✅ Greeting trigger set for {call_id}")
            return True
            
        except Exception as e:
            log.error(f"[Greeting] Error playing greeting: {e}")
            return False

    async def _get_greeting_state(self, call_id: str) -> Optional[Dict[str, Any]]:
        """Get greeting state from Redis"""
        try:
            from ..core.redis import get_session as redis_get_session
            data = await redis_get_session(f"greeting:{call_id}")
            if isinstance(data, str):
                import json
                data = json.loads(data)
            return data
        except Exception as e:
            log.debug(f"[Greeting] Error getting state: {e}")
            return None

    async def _mark_greeting_played(self, call_id: str) -> bool:
        """Mark greeting as played in state"""
        try:
            from ..core.redis import set_session as redis_set_session
            state = {
                "call_id": call_id,
                "played": True,
                "played_at": datetime.utcnow().isoformat(),
                "greeting_text": ClientConfig.get_greeting()[:100] + "..."
            }
            await redis_set_session(
                f"greeting:{call_id}",
                state,
                ttl=self.greeting_ttl
            )
            return True
        except Exception as e:
            log.error(f"[Greeting] Error marking greeting played: {e}")
            return False

    async def has_greeting_been_played(self, call_id: str) -> bool:
        """Check if greeting has been played for this call"""
        try:
            state = await self._get_greeting_state(call_id)
            return state and state.get("played", False)
        except Exception as e:
            log.debug(f"[Greeting] Error checking greeting state: {e}")
            return False


_service: Optional[GreetingService] = None


async def init_greeting_service():
    """Initialize greeting service"""
    global _service
    _service = GreetingService()
    log.info("[Greeting] Greeting service initialized")
    return _service


def get_greeting_service() -> Optional[GreetingService]:
    """Get greeting service instance"""
    return _service
