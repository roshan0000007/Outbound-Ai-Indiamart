"""
Gemini Session Manager
Manages Gemini Live audio sessions lifecycle and coordination with media sessions
Integrates media service with Gemini audio streaming
"""

import asyncio
from typing import Optional, Dict, Any, Callable
from datetime import datetime

from ..core.config import log, GEMINI_AUDIO_STREAMING_ENABLED
from .gemini_audio_pipeline import (
    create_gemini_audio_session,
    get_gemini_audio_session,
    end_gemini_audio_session
)


class GeminiSessionCoordinator:
    """Coordinates Gemini audio sessions with media sessions"""

    def __init__(self):
        self.active_sessions: Dict[str, Dict[str, Any]] = {}
        self.lock = asyncio.Lock()
        self.enabled = GEMINI_AUDIO_STREAMING_ENABLED
        
        log.info(f"[Gemini Session] Coordinator initialized - Streaming: {'✅ ON' if self.enabled else '⚠️ OFF'}")

    async def create_session(
        self,
        call_id: str,
        language: str = "en",
        system_prompt: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Create a new coordinated Gemini session
        
        Args:
            call_id: Unique call identifier
            language: Language code
            system_prompt: Custom system instructions
            
        Returns:
            Session metadata dict or None
        """
        try:
            if not self.enabled:
                log.warning("[Gemini Session] Audio streaming not enabled")
                return None

            async with self.lock:
                # Check if session already exists
                if call_id in self.active_sessions:
                    log.warning(f"[Gemini Session] Session already exists for {call_id}")
                    return self.active_sessions[call_id]

                log.info(f"[Gemini Session] Creating session: {call_id}")

                # Create Gemini audio session
                gemini_session = await create_gemini_audio_session(
                    call_id=call_id,
                    language=language,
                    system_prompt=system_prompt
                )

                if not gemini_session:
                    log.error(f"[Gemini Session] Failed to create Gemini session")
                    return None

                # Store session metadata
                session_meta = {
                    "call_id": call_id,
                    "language": language,
                    "gemini_session": gemini_session,
                    "created_at": datetime.utcnow().isoformat(),
                    "status": "active",
                    "audio_frames_received": 0,
                    "audio_frames_sent": 0,
                }

                self.active_sessions[call_id] = session_meta
                log.info(f"[Gemini Session] ✅ Session created: {call_id}")
                
                return session_meta

        except Exception as e:
            log.error(f"[Gemini Session] Error creating session: {e}", exc_info=True)
            return None

    async def get_session(self, call_id: str) -> Optional[Dict[str, Any]]:
        """Get session metadata"""
        async with self.lock:
            return self.active_sessions.get(call_id)

    async def update_session_metrics(self, call_id: str, **kwargs):
        """Update session metrics"""
        try:
            async with self.lock:
                if call_id in self.active_sessions:
                    for key, value in kwargs.items():
                        self.active_sessions[call_id][key] = value
        except Exception as e:
            log.error(f"[Gemini Session] Error updating metrics: {e}")

    async def stream_audio(
        self,
        call_id: str,
        media_session,
        on_response_audio: Optional[Callable[[bytes], None]] = None,
        on_response_text: Optional[Callable[[str], None]] = None
    ) -> bool:
        """
        Start audio streaming for a session
        
        Coordinates media session with Gemini session
        
        Args:
            call_id: Call identifier
            media_session: MediaSession instance
            on_response_audio: Callback for response audio
            on_response_text: Callback for response text
            
        Returns:
            bool: Success status
        """
        try:
            async with self.lock:
                if call_id not in self.active_sessions:
                    log.error(f"[Gemini Session] No session for {call_id}")
                    return False

                session_meta = self.active_sessions[call_id]
                gemini_session = session_meta["gemini_session"]

            log.info(f"[Gemini Session] Starting audio stream: {call_id}")

            # Use media session's Gemini streaming method
            success = await media_session.stream_audio_via_gemini(
                gemini_session=gemini_session,
                on_response_audio=on_response_audio,
                on_response_text=on_response_text
            )

            if success:
                await self.update_session_metrics(call_id, status="streaming")
                log.info(f"[Gemini Session] ✅ Audio stream started: {call_id}")
            else:
                log.error(f"[Gemini Session] Failed to start audio stream")

            return success

        except Exception as e:
            log.error(f"[Gemini Session] Error starting audio stream: {e}", exc_info=True)
            return False

    async def end_session(self, call_id: str) -> bool:
        """
        End a Gemini session and cleanup
        
        Args:
            call_id: Call identifier
            
        Returns:
            bool: Success status
        """
        try:
            async with self.lock:
                if call_id not in self.active_sessions:
                    log.warning(f"[Gemini Session] No session found for {call_id}")
                    return False

                session_meta = self.active_sessions.pop(call_id)

            log.info(f"[Gemini Session] Ending session: {call_id}")

            # End Gemini audio session
            await end_gemini_audio_session(call_id)

            # Log metrics
            log.info(f"[Gemini Session] Session metrics:")
            log.info(f"[Gemini Session]    ├─ Audio frames received: {session_meta.get('audio_frames_received', 0)}")
            log.info(f"[Gemini Session]    ├─ Audio frames sent: {session_meta.get('audio_frames_sent', 0)}")
            log.info(f"[Gemini Session]    └─ Duration: {session_meta.get('duration_sec', 'N/A')}s")

            log.info(f"[Gemini Session] ✅ Session ended: {call_id}")
            return True

        except Exception as e:
            log.error(f"[Gemini Session] Error ending session: {e}")
            return False

    async def get_active_sessions_count(self) -> int:
        """Get count of active sessions"""
        async with self.lock:
            return len(self.active_sessions)

    async def get_all_sessions(self) -> Dict[str, Dict[str, Any]]:
        """Get all active session metadata"""
        async with self.lock:
            return dict(self.active_sessions)

    async def cleanup_all(self) -> int:
        """Cleanup all sessions on shutdown"""
        try:
            async with self.lock:
                count = len(self.active_sessions)
                for call_id in list(self.active_sessions.keys()):
                    await end_gemini_audio_session(call_id)
                    self.active_sessions.pop(call_id, None)

                log.info(f"[Gemini Session] Cleaned up {count} sessions")
                return count

        except Exception as e:
            log.error(f"[Gemini Session] Error in cleanup: {e}")
            return 0


# Global coordinator instance
_coordinator: Optional[GeminiSessionCoordinator] = None


async def init_gemini_session_manager():
    """Initialize Gemini session manager"""
    global _coordinator
    _coordinator = GeminiSessionCoordinator()
    log.info("[Gemini Session] Manager initialized")
    return _coordinator


def get_gemini_session_manager() -> Optional[GeminiSessionCoordinator]:
    """Get Gemini session manager instance"""
    return _coordinator
