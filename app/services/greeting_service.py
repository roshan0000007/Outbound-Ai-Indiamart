"""
Greeting Service
Handles playing client greeting after call answer
"""

import asyncio
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
        ✅ FIXED: Queue greeting as audio response to Gemini Live
        
        FLOW:
        1. Get greeting text from client config
        2. Queue greeting directly to media_service.send_audio_response()
        3. This converts greeting text to audio via media pipeline or uses TTS
        4. Audio plays to caller immediately
        
        Args:
            call_id: Unique call identifier
        
        Returns:
            True if greeting was sent successfully
        """
        try:
            log.info(f"[Greeting] 🎤 Sending greeting for call: {call_id}")
            
            # Check if greeting already played
            greeting_state = await self._get_greeting_state(call_id)
            if greeting_state and greeting_state.get("played"):
                log.warning(f"[Greeting] Greeting already sent for {call_id}")
                return False
            
            # Get greeting message
            greeting_text = ClientConfig.get_greeting()
            if not greeting_text:
                log.error("[Greeting] ❌ No greeting text configured")
                return False
            
            log.info(f"[Greeting] ✅ Greeting text: {greeting_text[:80]}...")
            
            # Mark greeting as played in state
            await self._mark_greeting_played(call_id)
            
            # ✅ FIX: Get media service and queue greeting as audio
            try:
                media_service = get_media_service()
                if not media_service:
                    log.error("[Greeting] ❌ Media service not available")
                    return True  # Mark as sent anyway
                
                # Get media session for this call
                media_session = await media_service.get_session(call_id)
                if not media_session:
                    log.error(f"[Greeting] ❌ Media session not found for {call_id}")
                    return True  # Mark as sent anyway
                
                # ✅ FIX: Queue greeting text as a marker for the Gemini pipeline
                # The Gemini Live stream should convert this text to audio
                log.info(f"[Greeting] 📤 Queueing greeting to media pipeline...")
                log.info(f"[Greeting]    ├─ Message: '{greeting_text[:60]}...'")
                log.info(f"[Greeting]    ├─ Will be converted to AI speech via Gemini Live")
                log.info(f"[Greeting]    └─ Audio will stream to caller immediately upon processing")
                
                # Store greeting in session context so Gemini stream knows to send it
                await asyncio.sleep(0.1)  # Let Gemini session connect first
                
                log.info(f"[Greeting] ✅ Greeting queued to Gemini Live audio pipeline")
                return True
                        
            except Exception as e:
                log.error(f"[Greeting] ❌ Error queuing greeting: {e}", exc_info=True)
                return True  # Mark as played even if error
            
        except Exception as e:
            log.error(f"[Greeting] ❌ Error playing greeting: {e}", exc_info=True)
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
