"""
Gemini Live Audio Pipeline
End-to-end speech-to-speech audio processing without STT/TTS intermediaries
Handles real-time audio streaming from caller to Gemini and response back to caller
"""

import asyncio
from typing import Optional, Dict, Any, Callable, AsyncIterator
from datetime import datetime

from ..core.config import log
from ..llm.gemini_live_provider import get_gemini_live_provider


class GeminiAudioSession:
    """Manages a Gemini Live audio session for a specific call"""

    def __init__(self, call_id: str, language: str = "en"):
        self.call_id = call_id
        self.language = language
        self.gemini_provider = get_gemini_live_provider()
        self.session_active = False
        self.audio_buffer = asyncio.Queue(maxsize=1000)  # Buffer incoming RTP audio
        self.response_queue = asyncio.Queue(maxsize=1000)  # Buffer response audio
        self.created_at = datetime.utcnow()
        self.session_lock = asyncio.Lock()
        
        log.info(f"[Gemini Audio] Session created: {call_id}")

    async def initialize_session(self, system_prompt: Optional[str] = None) -> bool:
        """Initialize Gemini Live session for this call"""
        try:
            if not self.gemini_provider:
                log.error(f"[Gemini Audio] Gemini provider not available")
                return False

            # Create Gemini session
            success = await self.gemini_provider.create_live_session(system_prompt)
            if success:
                self.session_active = True
                log.info(f"[Gemini Audio] ✅ Gemini session initialized for call {self.call_id}")
                return True
            else:
                log.error(f"[Gemini Audio] Failed to initialize Gemini session")
                return False

        except Exception as e:
            log.error(f"[Gemini Audio] Session initialization error: {e}")
            return False

    async def add_audio_input(self, audio_chunk: bytes) -> bool:
        """
        Queue incoming audio chunk from caller for Gemini processing
        
        Args:
            audio_chunk: 160-byte PCM audio frame @ 8kHz
            
        Returns:
            bool: True if queued successfully
        """
        try:
            if not self.session_active:
                log.warning(f"[Gemini Audio] Session not active for call {self.call_id}")
                return False

            if not audio_chunk or len(audio_chunk) == 0:
                return True

            try:
                self.audio_buffer.put_nowait(audio_chunk)
                return True
            except asyncio.QueueFull:
                log.warning(f"[Gemini Audio] Audio buffer full for call {self.call_id}")
                # Remove oldest to make space
                try:
                    self.audio_buffer.get_nowait()
                    self.audio_buffer.put_nowait(audio_chunk)
                except asyncio.QueueEmpty:
                    pass
                return False

        except Exception as e:
            log.error(f"[Gemini Audio] Error adding audio input: {e}")
            return False

    async def get_response_audio(self) -> Optional[bytes]:
        """
        Get next response audio chunk from queue
        
        Returns:
            Audio chunk or None if queue empty
        """
        try:
            return self.response_queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    async def audio_input_generator(self) -> AsyncIterator[bytes]:
        """
        Async generator for audio input stream
        Yields audio chunks from the input buffer
        """
        try:
            timeout_count = 0
            max_timeout = 300  # 5 minutes of continuous silence
            
            while self.session_active:
                try:
                    # Wait for audio with timeout
                    audio_chunk = await asyncio.wait_for(
                        self.audio_buffer.get(),
                        timeout=1.0
                    )
                    timeout_count = 0
                    yield audio_chunk
                    
                except asyncio.TimeoutError:
                    timeout_count += 1
                    if timeout_count >= max_timeout:
                        log.warning(f"[Gemini Audio] No audio for 5 minutes, ending stream")
                        break
                    # Continue waiting
                    continue

                except asyncio.CancelledError:
                    log.info(f"[Gemini Audio] Audio generator cancelled")
                    break

        except Exception as e:
            log.error(f"[Gemini Audio] Error in audio generator: {e}")

    async def process_audio_stream(
        self,
        on_response_audio: Optional[Callable[[bytes], None]] = None,
        on_response_text: Optional[Callable[[str], None]] = None
    ) -> bool:
        """
        Start processing audio through Gemini Live
        
        Args:
            on_response_audio: Callback for each response audio chunk
            on_response_text: Callback for response text transcriptions
            
        Returns:
            bool: Success status
        """
        try:
            if not self.session_active or not self.gemini_provider:
                log.error(f"[Gemini Audio] Session not ready")
                return False

            log.info(f"[Gemini Audio] Starting audio stream processing for call {self.call_id}")

            # Create audio input generator
            audio_gen = self.audio_input_generator()

            # Callback to queue response audio
            def queue_response_audio(audio_bytes: bytes):
                try:
                    self.response_queue.put_nowait(audio_bytes)
                except asyncio.QueueFull:
                    log.warning(f"[Gemini Audio] Response queue full, dropping frame")

            # Start bidirectional streaming
            response_audio = await self.gemini_provider.stream_audio_bidirectional(
                audio_input_stream=audio_gen,
                on_audio_chunk=queue_response_audio,
                on_text_chunk=on_response_text
            )

            if response_audio:
                log.info(f"[Gemini Audio] ✅ Stream processing completed: {len(response_audio)} bytes response")
                return True
            else:
                log.warning(f"[Gemini Audio] No response received")
                return False

        except Exception as e:
            log.error(f"[Gemini Audio] Stream processing error: {e}", exc_info=True)
            return False

    async def end_session(self) -> bool:
        """End the Gemini audio session"""
        try:
            self.session_active = False
            
            # Close Gemini session
            if self.gemini_provider:
                await self.gemini_provider.close_session()
            
            log.info(f"[Gemini Audio] Session ended for call {self.call_id}")
            return True

        except Exception as e:
            log.error(f"[Gemini Audio] Error ending session: {e}")
            return False


# Global session manager
_audio_sessions: Dict[str, GeminiAudioSession] = {}
_sessions_lock = asyncio.Lock()


async def create_gemini_audio_session(call_id: str, language: str = "en", system_prompt: Optional[str] = None) -> Optional[GeminiAudioSession]:
    """
    Create a new Gemini audio session for a call
    
    Args:
        call_id: Unique call identifier
        language: Language code (en, hi, etc.)
        system_prompt: Custom system instructions
        
    Returns:
        GeminiAudioSession instance or None
    """
    try:
        async with _sessions_lock:
            # Check if session already exists
            if call_id in _audio_sessions:
                log.warning(f"[Gemini Audio] Session already exists for call {call_id}")
                return _audio_sessions[call_id]

            # Create new session
            session = GeminiAudioSession(call_id, language)
            success = await session.initialize_session(system_prompt)
            
            if success:
                _audio_sessions[call_id] = session
                log.info(f"[Gemini Audio] ✅ Audio session created: {call_id}")
                return session
            else:
                log.error(f"[Gemini Audio] Failed to create audio session")
                return None

    except Exception as e:
        log.error(f"[Gemini Audio] Error creating session: {e}")
        return None


async def get_gemini_audio_session(call_id: str) -> Optional[GeminiAudioSession]:
    """Get existing Gemini audio session"""
    async with _sessions_lock:
        return _audio_sessions.get(call_id)


async def end_gemini_audio_session(call_id: str) -> bool:
    """End a Gemini audio session"""
    try:
        async with _sessions_lock:
            session = _audio_sessions.pop(call_id, None)
            if session:
                await session.end_session()
                log.info(f"[Gemini Audio] Session ended: {call_id}")
                return True
            else:
                log.warning(f"[Gemini Audio] No session found for call {call_id}")
                return False

    except Exception as e:
        log.error(f"[Gemini Audio] Error ending session: {e}")
        return False


async def cleanup_all_sessions() -> bool:
    """Cleanup all active Gemini audio sessions"""
    try:
        async with _sessions_lock:
            count = len(_audio_sessions)
            for call_id in list(_audio_sessions.keys()):
                session = _audio_sessions.pop(call_id)
                await session.end_session()
            
            log.info(f"[Gemini Audio] Cleaned up {count} sessions")
            return True

    except Exception as e:
        log.error(f"[Gemini Audio] Error cleaning up sessions: {e}")
        return False


def get_gemini_provider():
    """Get the Gemini Live provider instance"""
    return get_gemini_live_provider()
