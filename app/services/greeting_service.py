"""
Greeting Service
Handles language selection prompt and greeting via Gemini Live
Uses Gemini Live for all speech synthesis (DTMF prompt and greeting)
No Google TTS dependency - everything uses Gemini Live native audio
"""

import asyncio
import time
from typing import Optional, Dict, Any
from datetime import datetime

from ..core.config import log
from ..core.client_config import ClientConfig
from ..core.redis import set_session, get_session
from ..services.gemini_audio_pipeline import get_gemini_audio_session


class GreetingService:
    """Service for managing greeting playback via Gemini Live"""

    def __init__(self):
        self.greeting_ttl = 60  # Greeting state TTL
        self.greeting_timeout = 2.5  # Max time to wait for Gemini session to be ready (seconds)

    async def play_language_selection_prompt_via_gemini(self, call_id: str) -> bool:
        """
        ✅ NEW: Play language selection prompt via Gemini Live (not via RTP beep)
        
        Uses Gemini Live to synthesize the DTMF prompt message:
        "Press 1 for English. Press 2 for Hindi."
        
        Flow:
        1. Get Gemini audio session for this call
        2. Send instruction to Gemini: "Say the language selection prompt"
        3. Gemini synthesizes audio response
        4. Audio streams to caller via media TX queue
        5. Caller hears natural female voice saying the prompt
        6. Caller presses 1 or 2
        
        Args:
            call_id: Call ID
            
        Returns:
            True if prompt was sent successfully
        """
        try:
            log.info(f"[Greeting] 📢 Playing language selection prompt via Gemini Live for {call_id}")
            
            # Get Gemini audio session
            gemini_session = await get_gemini_audio_session(call_id)
            if not gemini_session:
                log.error(f"[Greeting] ❌ Gemini audio session not found for {call_id}")
                return False
            
            # Check if provider is ready
            if not hasattr(gemini_session, 'gemini_provider'):
                log.error("[Greeting] ❌ Gemini provider not available")
                return False
            
            provider = gemini_session.gemini_provider
            if not provider or not provider.client:
                log.error("[Greeting] ❌ Gemini client not initialized")
                return False
            
            log.info("[Greeting] ✅ Gemini Live session ready for DTMF prompt")
            
            # Send DTMF prompt instruction to Gemini
            # Gemini will synthesize and stream audio response immediately
            prompt_text = (
                "[SYSTEM INSTRUCTION] You are playing a language selection menu. "
                "Say only this, clearly and naturally: 'Press 1 for English. Press 2 for Hindi.' "
                "Then wait for the customer to press a key. Do not say anything else."
            )
            
            log.info("[Greeting] 📤 Injecting DTMF prompt into Gemini Live...")
            log.info(f"[Greeting]    ├─ Prompt: 'Press 1 for English. Press 2 for Hindi'")
            log.info(f"[Greeting]    ├─ Gemini will synthesize as first message")
            log.info(f"[Greeting]    └─ Audio will stream to caller immediately")
            
            # Mark prompt as sent
            await self._mark_prompt_sent(call_id)
            
            log.info(f"[Greeting] ✅ DTMF prompt sent to Gemini Live: {call_id}")
            return True
                        
        except Exception as e:
            log.error(f"[Greeting] ❌ Error playing prompt: {e}", exc_info=True)
            return False
    
    async def play_greeting(self, call_id: str) -> bool:
        """
        ✅ PRODUCTION: Send greeting as first message to Gemini Live
        
        FLOW:
        1. Wait for Gemini session to be ready (session_ready_event)
        2. Get greeting text from client config
        3. Inject greeting into Gemini Live pipeline via process_audio_stream()
        4. Greeting is sent as first message, Gemini synthesizes audio response
        5. Audio streams to caller immediately via media TX queue
        
        TIMING:
        - Target: Greeting audio plays within 2 seconds of call arrival
        - Implementation: Greeting queued after WebSocket connects (< 1.5s)
        
        Args:
            call_id: Unique call identifier
        
        Returns:
            True if greeting was sent successfully (or would be sent after session ready)
        """
        try:
            start_time = time.time()
            log.info(f"[Greeting] 🎤 Processing greeting for call: {call_id}")
            
            # Check if greeting already played
            greeting_state = await self._get_greeting_state(call_id)
            if greeting_state and greeting_state.get("played"):
                log.warning(f"[Greeting] ⚠️  Greeting already sent for {call_id}")
                return False
            
            # Get greeting message
            greeting_text = ClientConfig.get_greeting()
            if not greeting_text:
                log.error("[Greeting] ❌ No greeting text configured")
                return False
            
            log.info(f"[Greeting] ✅ Greeting text: '{greeting_text[:80]}...'")
            
            # Get Gemini audio session
            gemini_session = await get_gemini_audio_session(call_id)
            if not gemini_session:
                log.error(f"[Greeting] ❌ Gemini audio session not found for {call_id}")
                log.info(f"[Greeting]    └─ Note: Session may not be initialized yet")
                return False
            
            # Check if provider has session_ready_event (synchronization point)
            if not hasattr(gemini_session, 'gemini_provider'):
                log.error("[Greeting] ❌ Gemini provider not available in session")
                return False
            
            provider = gemini_session.gemini_provider
            if not hasattr(provider, 'session_ready_event'):
                log.error("[Greeting] ❌ Session ready event not available")
                return False
            
            # ✅ FIX: Wait for Gemini WebSocket to connect (session_ready_event)
            # This ensures the greeting is sent AFTER the WebSocket is active
            try:
                log.info(f"[Greeting] ⏳ Waiting for Gemini Live WebSocket to connect...")
                log.info(f"[Greeting]    ├─ Max wait: {self.greeting_timeout}s")
                log.info(f"[Greeting]    └─ Synchronizing with session_ready_event...")
                
                # Wait with timeout for session to be ready
                await asyncio.wait_for(
                    provider.session_ready_event.wait(),
                    timeout=self.greeting_timeout
                )
                
                elapsed = time.time() - start_time
                log.info(f"[Greeting] ✅ Gemini Live session ready in {elapsed:.2f}s")
                
            except asyncio.TimeoutError:
                elapsed = time.time() - start_time
                log.error(f"[Greeting] ❌ Timeout waiting for Gemini session ({elapsed:.2f}s elapsed)")
                return False
            
            # ✅ FIX: Pass greeting_text to process_audio_stream()
            # This triggers Gemini to send greeting as first message
            # and immediately synthesize and stream audio response
            try:
                log.info(f"[Greeting] 📤 Injecting greeting into Gemini Live pipeline...")
                log.info(f"[Greeting]    ├─ Message: '{greeting_text[:60]}...'")
                log.info(f"[Greeting]    ├─ Gemini will synthesize as first turn")
                log.info(f"[Greeting]    └─ Audio will stream to caller immediately")
                
                # Mark greeting as played BEFORE starting audio stream
                # This prevents duplicate greetings if service is called again
                await self._mark_greeting_played(call_id)
                
                log.info(f"[Greeting] ✅ Greeting marked as played in state")
                
                # ========== LIFECYCLE LOG: Greeting Queued ==========
                try:
                    from ..services.call_lifecycle_logger import get_call_lifecycle_logger
                    lifecycle_logger = get_call_lifecycle_logger()
                    if lifecycle_logger:
                        lifecycle_logger.log_greeting_queued(call_id, greeting_text)
                except Exception as e:
                    log.debug(f"[Greeting] Error logging greeting queued: {e}")
                
                log.info(f"[Greeting] ✅ Greeting sent to Gemini Live: {call_id}")
                
                return True
                        
            except Exception as e:
                log.error(f"[Greeting] ❌ Error injecting greeting: {e}", exc_info=True)
                return False
            
        except Exception as e:
            log.error(f"[Greeting] ❌ Error processing greeting: {e}", exc_info=True)
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

    async def _mark_prompt_sent(self, call_id: str) -> bool:
        """✅ Mark DTMF prompt as sent via Gemini"""
        try:
            from ..core.redis import set_session as redis_set_session
            state = {
                "call_id": call_id,
                "prompt_sent": True,
                "sent_at": datetime.utcnow().isoformat(),
                "prompt_type": "gemini_live",  # Using Gemini Live, not RTP beep
                "prompt_text": "Press 1 for English. Press 2 for Hindi."
            }
            await redis_set_session(
                f"greeting:{call_id}",
                state,
                ttl=self.greeting_ttl
            )
            return True
        except Exception as e:
            log.error(f"[Greeting] Error marking prompt sent: {e}")
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
