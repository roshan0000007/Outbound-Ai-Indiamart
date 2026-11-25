"""
Live Call Handler Service - Gemini Live Audio Streaming
Handles real-time speech-to-speech call flow using Gemini Live
No intermediate STT/TTS processing - direct audio streaming
"""

import asyncio
from typing import Optional, Dict, Any, Callable
from datetime import datetime
from ..core.config import log, GEMINI_AUDIO_STREAMING_ENABLED
from ..core.redis import set_session, get_session, delete_session
from ..services.call_service import get_call_service
from ..services.conversation_history_service import get_conversation_history_service
from ..services.language_service import get_language_service
from ..services.gemini_audio_pipeline import (
    create_gemini_audio_session,
    get_gemini_audio_session,
    end_gemini_audio_session
)


class LiveCallHandler:
    """
    Handles live call flow with Gemini Live audio streaming
    
    Features:
    - Direct audio-to-audio streaming (no STT/TTS)
    - Real-time bidirectional communication
    - Conversation history tracking
    - Multi-call session management
    """

    def __init__(self):
        self.call_service = get_call_service()
        self.conversation_history_service = get_conversation_history_service()
        self.language_service = get_language_service()
        self.call_session_ttl = 3600
        self.gemini_audio_enabled = GEMINI_AUDIO_STREAMING_ENABLED
        
        log.info(f"[LiveCall] Gemini audio streaming: {'✅ ENABLED' if self.gemini_audio_enabled else '⚠️ DISABLED'}")

    async def initialize(self):
        """Initialize handler"""
        log.info("[LiveCall] Handler initialized - Ready for Gemini audio streaming")
        return True

    async def start_listening(self, call_id: str, language: str = "en") -> bool:
        """
        Start listening for audio on a call
        Initializes Gemini Live audio streaming and connects RTP to Gemini
        
        Args:
            call_id: Call ID
            language: Language code (default: en)
            
        Returns:
            True if successful
        """
        try:
            log.info(f"[LiveCall] Starting audio listening: {call_id}")
            
            # Start Gemini audio stream
            result = await self.start_call_audio_stream(
                call_id=call_id,
                language=language
            )
            
            if not result or not result.get("success"):
                log.error(f"[LiveCall] Failed to start audio listening: {call_id}")
                return False
            
            # CRITICAL: Get media session and connect RTP ↔ Gemini bidirectional streaming
            try:
                from ..services.media_service import get_media_service
                from ..services.gemini_audio_pipeline import get_gemini_audio_session
                
                media_service = get_media_service()
                if not media_service:
                    log.error(f"[LiveCall] Media service not available")
                    return False
                
                # Get media session created for this call
                media_session = await media_service.get_session(call_id)
                if not media_session:
                    log.error(f"[LiveCall] Media session not found for {call_id}")
                    return False
                
                # Get Gemini audio session
                gemini_session = await get_gemini_audio_session(call_id)
                if not gemini_session:
                    log.error(f"[LiveCall] Gemini audio session not found for {call_id}")
                    return False
                
                # Start bidirectional RTP ↔ Gemini audio streaming
                log.info(f"[LiveCall] Connecting RTP ↔ Gemini Live bidirectional streaming for {call_id}")
                
                async def run_audio_streaming():
                    """Run audio streaming as background task"""
                    try:
                        await media_session.stream_audio_via_gemini(
                            gemini_session=gemini_session,
                            on_response_audio=None,
                            on_response_text=None
                        )
                    except Exception as e:
                        log.error(f"[LiveCall] Audio streaming error: {e}")
                
                # Start streaming as background task (don't await, let it run independently)
                asyncio.create_task(run_audio_streaming())
                
                log.info(f"[LiveCall] ✅ Audio listening started: {call_id}")
                log.info(f"[LiveCall]    ├─ RTP audio → Gemini Live (input)")
                log.info(f"[LiveCall]    └─ Gemini Live → RTP audio (output)")
                
                return True
                
            except Exception as e:
                log.error(f"[LiveCall] Error connecting audio streams: {e}", exc_info=True)
                return False
                
        except Exception as e:
            log.error(f"[LiveCall] Error starting listening: {e}")
            return False

    async def stop_listening(self, call_id: str) -> bool:
        """
        Stop listening for audio on a call
        Closes Gemini Live audio streaming
        
        Args:
            call_id: Call ID
            
        Returns:
            True if successful
        """
        try:
            log.info(f"[LiveCall] Stopping audio listening: {call_id}")
            
            # End Gemini audio session
            await end_gemini_audio_session(call_id)
            
            log.info(f"[LiveCall] ✅ Audio listening stopped: {call_id}")
            return True
            
        except Exception as e:
            log.error(f"[LiveCall] Error stopping listening: {e}")
            return False

    async def start_call_audio_stream(
        self,
        call_id: str,
        language: str = "en",
        system_prompt: Optional[str] = None,
        on_response_audio: Optional[Callable[[bytes], None]] = None,
        on_response_text: Optional[Callable[[str], None]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Start Gemini Live audio streaming for a call
        
        This replaces the old STT → LLM → TTS pipeline with direct audio streaming
        
        Args:
            call_id: Unique call identifier
            language: Language code (en, hi, etc.)
            system_prompt: Custom system instructions for the AI
            on_response_audio: Callback for each response audio chunk
            on_response_text: Callback for response text transcriptions
            
        Returns:
            Dict with stream info or None on error
        """
        try:
            if not self.gemini_audio_enabled:
                log.warning("[LiveCall] Gemini audio streaming not enabled, falling back to text mode")
                return None

            log.info(f"[LiveCall] Starting Gemini audio stream: call_id={call_id}, language={language}")

            # Create Gemini audio session
            gemini_session = await create_gemini_audio_session(
                call_id=call_id,
                language=language,
                system_prompt=system_prompt or self._get_default_system_prompt(language)
            )

            if not gemini_session:
                log.error(f"[LiveCall] Failed to create Gemini audio session")
                return None

            # Initialize session in Redis
            session = {
                "call_id": call_id,
                "language": language,
                "gemini_session_id": gemini_session.session_active,
                "stream_started_at": datetime.utcnow().isoformat(),
                "conversation": []
            }
            await set_session(f"call:{call_id}", session, ttl=self.call_session_ttl)

            log.info(f"[LiveCall] ✅ Gemini audio stream initialized for call {call_id}")

            return {
                "success": True,
                "call_id": call_id,
                "session_id": gemini_session.session_id if hasattr(gemini_session, 'session_id') else "active",
                "language": language,
                "streaming": True
            }

        except Exception as e:
            log.error(f"[LiveCall] Error starting audio stream: {e}", exc_info=True)
            return None

    def _get_default_system_prompt(self, language: str = "en") -> str:
        """Get default system prompt for the AI"""
        prompts = {
            "en": "You are a professional sales assistant. Be concise, friendly, and helpful. Listen to customer needs and provide relevant information.",
            "hi": "आप एक पेशेवर बिक्री सहायक हैं। संक्षिप्त, मित्रवत और सहायक बनें। ग्राहक की आवश्यकताओं को सुनें और प्रासंगिक जानकारी प्रदान करें।"
        }
        return prompts.get(language, prompts["en"])

    async def process_customer_message(
        self,
        call_id: str,
        customer_text: str,
        detected_language: str = "en"
    ) -> Optional[Dict[str, Any]]:
        """
        Process customer message text (for fallback scenarios)
        
        Note: With Gemini audio streaming, this is used for text-only fallback
        In normal operation, audio is processed directly in the media session
        """
        try:
            log.debug(f"[LiveCall] Processing text message: {customer_text[:50]}...")

            # Get session
            session = await get_session(f"call:{call_id}")
            if not session:
                session = {
                    "call_id": call_id,
                    "language": detected_language,
                    "conversation": []
                }
                await set_session(f"call:{call_id}", session, ttl=self.call_session_ttl)

            # Save to conversation history
            try:
                user_id = session.get("user_id", 0)
                campaign_id = session.get("campaign_id", 0)
                caller_number = session.get("caller_number", "Unknown")
                dnid = session.get("dnid", "unknown")

                await self.conversation_history_service.save_conversation(
                    call_id=call_id,
                    user_id=user_id,
                    campaign_id=campaign_id,
                    caller_number=caller_number,
                    dnid=dnid,
                    customer_message=customer_text,
                    ai_response="[Gemini Live Audio Response]",
                    detected_language=detected_language
                )
            except Exception as e:
                log.warning(f"[LiveCall] Failed to save conversation: {e}")

            return {
                "success": True,
                "message": "Message received, processing via Gemini audio stream",
                "call_id": call_id
            }

        except Exception as e:
            log.error(f"[LiveCall] Process message error: {e}")
            return {
                "success": False,
                "error": str(e),
                "call_id": call_id
            }

    async def end_call(self, call_id: str, reason: str = "normal") -> bool:
        """
        End call and cleanup all resources
        Closes Gemini audio session and call session
        """
        try:
            log.info(f"[LiveCall] Ending call: {call_id}, reason={reason}")

            # End Gemini audio session
            await end_gemini_audio_session(call_id)

            # End call service
            if self.call_service:
                await self.call_service.end_call(call_id, reason)
            
            # Delete session
            await delete_session(f"call:{call_id}")
            
            log.info(f"[LiveCall] ✅ Call ended: {call_id}")
            return True
        except Exception as e:
            log.error(f"[LiveCall] End call error: {e}")
            return False

    async def get_active_session(self, call_id: str) -> Optional[Dict[str, Any]]:
        """Get information about active Gemini audio session"""
        try:
            gemini_session = await get_gemini_audio_session(call_id)
            if gemini_session:
                return {
                    "call_id": call_id,
                    "active": gemini_session.session_active,
                    "language": gemini_session.language,
                    "created_at": gemini_session.created_at.isoformat()
                }
            return None
        except Exception as e:
            log.error(f"[LiveCall] Error getting session info: {e}")
            return None


_handler: Optional[LiveCallHandler] = None


async def init_live_call_handler():
    """Initialize live call handler"""
    global _handler
    _handler = LiveCallHandler()
    await _handler.initialize()
    log.info("[LiveCall] ✅ Handler initialized - Gemini audio streaming ready")
    return _handler


def get_live_call_handler() -> Optional[LiveCallHandler]:
    """Get live call handler instance"""
    return _handler
