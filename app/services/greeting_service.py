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
        ✅ FIX #3: Play the client greeting for a call via Gemini Live
        
        NEW FLOW:
        1. Get greeting text from client config
        2. Send greeting via Gemini Live API (turn-based text mode)
        3. Gemini generates audio response (greeting speech)
        4. Response audio streams back to caller via RTP TX queue
        5. Caller hears AI greeting immediately upon call pickup
        
        Uses Gemini Live to deliver the greeting as natural speech audio
        
        Args:
            call_id: Unique call identifier
        
        Returns:
            True if greeting was played successfully
        """
        try:
            log.info(f"[Greeting] 🎤 Starting greeting for call: {call_id}")
            
            # Check if greeting already played
            greeting_state = await self._get_greeting_state(call_id)
            if greeting_state and greeting_state.get("played"):
                log.warning(f"[Greeting] Greeting already played for {call_id}")
                return False
            
            # Get greeting message
            greeting_text = ClientConfig.get_greeting()
            if not greeting_text:
                log.error("[Greeting] ❌ No greeting text configured")
                return False
            
            log.info(f"[Greeting] ✅ Greeting text: {greeting_text[:80]}...")
            
            # Mark greeting as played in state
            await self._mark_greeting_played(call_id)
            
            # ✅ FIX #3: Send greeting to Gemini Live via text mode
            # Gemini will synthesize the text to speech and return audio
            try:
                from ..llm.gemini_live_provider import get_gemini_live_provider
                
                gemini_provider = get_gemini_live_provider()
                if not gemini_provider or not gemini_provider.session:
                    log.error("[Greeting] ❌ Gemini provider or session not available")
                    return False
                
                log.info(f"[Greeting] 📤 Sending greeting text to Gemini Live for speech synthesis...")
                
                # Get media service to queue the response audio
                media_service = get_media_service()
                if not media_service:
                    log.error("[Greeting] ❌ Media service not available")
                    return False
                
                # Get media session for this call
                media_session = await media_service.get_session(call_id)
                if not media_session:
                    log.error(f"[Greeting] ❌ Media session not found for {call_id}")
                    return False
                
                # Create a callback to queue audio to RTP TX
                async def on_greeting_audio(audio_chunk: bytes):
                    """Queue greeting audio to RTP transmission"""
                    if audio_chunk and len(audio_chunk) > 0:
                        try:
                            await media_session.tx_queue.put(audio_chunk)
                            log.debug(f"[Greeting] 📥 Queued {len(audio_chunk)} bytes of greeting audio to TX")
                        except asyncio.QueueFull:
                            log.warning(f"[Greeting] ❌ TX queue full, greeting audio dropped")
                
                # Send greeting text to Gemini and get audio response
                # Use the stream_response method which provides audio callbacks
                log.info(f"[Greeting] Generating greeting audio via Gemini...")
                
                response_audio = await gemini_provider.stream_response(
                    prompt=greeting_text,
                    on_audio_chunk=on_greeting_audio,
                    on_text_chunk=None
                )
                
                if response_audio:
                    log.info(f"[Greeting] ✅ Greeting audio generated successfully")
                    log.info(f"[Greeting]    ├─ Response size: {len(response_audio)} bytes")
                    log.info(f"[Greeting]    ├─ Queued to RTP TX")
                    log.info(f"[Greeting]    └─ Caller will hear greeting upon call pickup")
                    return True
                else:
                    log.error(f"[Greeting] ❌ Gemini did not generate greeting audio")
                    return False
                        
            except Exception as e:
                log.error(f"[Greeting] ❌ Error sending greeting to Gemini: {e}", exc_info=True)
                return False
            
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
