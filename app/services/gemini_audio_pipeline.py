"""
Gemini Live Audio Pipeline
Streams caller audio into Gemini Live and sends Gemini's reply back to the caller's RTP leg.

Audio flow:
  RTP RX (8 kHz PCMU, decoded to PCM16)
    -> add_audio_input()            (queue, must be 16 kHz PCM16 - see note in add_audio_input)
    -> audio_input_generator()      (real-time, never gated on AI speaking state)
    -> GeminiLiveProvider           (Gemini Live session for the whole call)
    -> reply audio 24 kHz PCM16
    -> OutboundResampler            (inside the provider: 24 kHz -> 8 kHz mu-law)
    -> enqueue_ulaw_to_rtp()        (splits into 160-byte frames)
    -> media_session.tx_queue       (existing TX loop sends them to the caller)
"""

import asyncio
from typing import Optional, Dict, Callable, AsyncIterator
from datetime import datetime

from ..core.config import log
from ..llm.gemini_live_provider import get_gemini_live_provider

RTP_FRAME_SIZE = 160  # 20 ms of G.711 mu-law at 8 kHz


class GeminiAudioSession:
    """Manages one Gemini Live conversation for one call."""

    def __init__(self, call_id: str, language: str = "en"):
        self.call_id = call_id
        self.language = language
        self.gemini_provider = get_gemini_live_provider()
        self.session_active = False
        self.audio_buffer = asyncio.Queue(maxsize=1000)   # caller audio waiting for Gemini
        self.created_at = datetime.utcnow()
        self.media_session = None                          # set with attach_media()
        self._tx_remainder = bytearray()                   # partial 160-byte RTP frame

        log.info(f"[Gemini Audio] Session created: {call_id}")

    # ------------------------------------------------------------------ #
    # Setup
    # ------------------------------------------------------------------ #
    def attach_media(self, media_session) -> None:
        """Give this session the media session whose tx_queue carries audio to the caller."""
        self.media_session = media_session
        log.info(f"[Gemini Audio] Media session attached for call {self.call_id}")

    async def initialize_session(self, system_prompt: Optional[str] = None) -> bool:
        """Create the per-call Gemini session record."""
        try:
            if not self.gemini_provider:
                log.error("[Gemini Audio] Gemini provider not available")
                return False

            success = await self.gemini_provider.create_live_session(system_prompt)
            if not success:
                log.error("[Gemini Audio] Failed to initialize Gemini session")
                return False

            self.session_active = True
            log.info(f"[Gemini Audio] ✅ Gemini session initialized for call {self.call_id}")

            try:
                from ..services.call_lifecycle_logger import get_call_lifecycle_logger
                lifecycle_logger = get_call_lifecycle_logger()
                if lifecycle_logger:
                    lifecycle_logger.log_gemini_connected(self.call_id)
                    if self.gemini_provider.session_id:
                        lifecycle_logger.log_session_ready(self.call_id, self.gemini_provider.session_id)
            except Exception as e:
                log.debug(f"[Gemini Audio] Error logging session ready: {e}")

            return True

        except Exception as e:
            log.error(f"[Gemini Audio] Session initialization error: {e}")
            return False

    # ------------------------------------------------------------------ #
    # Caller audio in
    # ------------------------------------------------------------------ #
    async def add_audio_input(self, audio_chunk: bytes) -> bool:
        """
        Queue one caller audio frame for Gemini.

        Note: the provider expects 16 kHz 16-bit mono PCM. If the RX path gives 8 kHz
        PCM, upsample it before calling this method (one 20 ms frame = 640 bytes at 16 kHz).
        Frames must arrive at real-time pace, including silence.
        """
        try:
            if not self.session_active:
                log.warning(f"[Gemini Audio] Session not active for call {self.call_id}")
                return False
            if not audio_chunk:
                return True

            try:
                self.audio_buffer.put_nowait(audio_chunk)
                return True
            except asyncio.QueueFull:
                # Drop the oldest frame so the newest speech is kept
                log.warning(f"[Gemini Audio] Audio buffer full for call {self.call_id}")
                try:
                    self.audio_buffer.get_nowait()
                    self.audio_buffer.put_nowait(audio_chunk)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass
                return False

        except Exception as e:
            log.error(f"[Gemini Audio] Error adding audio input: {e}")
            return False

    async def audio_input_generator(self) -> AsyncIterator[bytes]:
        """
        Yield caller audio to the provider for as long as the call lasts.
        Nothing here depends on whether the AI is currently speaking.
        Ends after 5 minutes with no caller audio at all, or when the session ends.
        """
        silent_seconds = 0
        max_silent_seconds = 300

        while self.session_active:
            try:
                chunk = await asyncio.wait_for(self.audio_buffer.get(), timeout=1.0)
                silent_seconds = 0
                yield chunk
            except asyncio.TimeoutError:
                silent_seconds += 1
                if silent_seconds >= max_silent_seconds:
                    log.warning(f"[Gemini Audio] No caller audio for {max_silent_seconds}s, ending stream")
                    break
            except asyncio.CancelledError:
                log.info(f"[Gemini Audio] Audio generator cancelled for call {self.call_id}")
                raise

    # ------------------------------------------------------------------ #
    # Reply audio out
    # ------------------------------------------------------------------ #
    def enqueue_ulaw_to_rtp(self, ulaw: bytes) -> None:
        """
        Called by the provider with 8 kHz mu-law bytes of Gemini's reply.
        Splits them into 160-byte frames and queues them for the RTP TX loop.
        """
        if not ulaw:
            return
        if self.media_session is None:
            log.error(f"[Gemini Audio] No media session attached for call {self.call_id}; reply dropped")
            return

        self._tx_remainder.extend(ulaw)
        tx_queue = self.media_session.tx_queue

        while len(self._tx_remainder) >= RTP_FRAME_SIZE:
            frame = bytes(self._tx_remainder[:RTP_FRAME_SIZE])
            del self._tx_remainder[:RTP_FRAME_SIZE]
            try:
                tx_queue.put_nowait(frame)
            except asyncio.QueueFull:
                log.warning(f"[Gemini Audio] TX queue full, dropping reply frame for call {self.call_id}")
                return

    # ------------------------------------------------------------------ #
    # Conversation
    # ------------------------------------------------------------------ #
    async def process_audio_stream(
        self,
        on_response_text: Optional[Callable[[str], None]] = None,
        greeting_text: Optional[str] = None,
    ) -> bool:
        """
        Run the Gemini Live conversation for the whole call.
        Reply audio goes straight to RTP via enqueue_ulaw_to_rtp().
        Returns True if the conversation ran, False if Gemini could not be used.
        """
        try:
            if not self.session_active or not self.gemini_provider:
                log.error("[Gemini Audio] Session not ready")
                return False

            if self.media_session is None:
                log.error(f"[Gemini Audio] Media session not attached for call {self.call_id}")
                return False

            log.info(f"[Gemini Audio] Starting conversation for call {self.call_id}")
            if greeting_text:
                log.info(f"[Gemini Audio]    ├─ Greeting: '{greeting_text[:60]}...'")

            audio_gen = self.audio_input_generator()

            try:
                from ..services.llm_failover_service import get_llm_failover_service
                failover_service = get_llm_failover_service()

                if failover_service:
                    log.info("[Gemini Audio] 🎯 Attempting primary: Gemini Live")
                    response_audio = await failover_service.try_gemini_live(
                        self.call_id,
                        audio_input_stream=audio_gen,
                        on_ulaw_chunk=self.enqueue_ulaw_to_rtp,
                        on_text_chunk=on_response_text,
                        greeting_text=greeting_text,
                    )
                else:
                    log.info("[Gemini Audio] No failover service, using Gemini Live directly")
                    response_audio = await self.gemini_provider.stream_audio_bidirectional(
                        audio_input_stream=audio_gen,
                        on_ulaw_chunk=self.enqueue_ulaw_to_rtp,
                        on_text_chunk=on_response_text,
                        greeting_text=greeting_text,
                    )

                if response_audio:
                    log.info("[Gemini Audio] ✅ Gemini Live conversation finished with reply audio")
                else:
                    log.warning("[Gemini Audio] ⚠️  Gemini Live ended with no reply audio")
                return True

            except Exception as e:
                log.error(f"[Gemini Audio] Error during Gemini conversation: {e}", exc_info=True)

            log.warning("[Gemini Audio] ⚠️  Could not process audio stream (Gemini unavailable)")
            return False

        except Exception as e:
            log.error(f"[Gemini Audio] Stream processing error: {e}", exc_info=True)
            return False

    async def end_session(self) -> bool:
        """End the session and flush any partial reply frame."""
        try:
            self.session_active = False
            self._tx_remainder.clear()

            if self.gemini_provider:
                await self.gemini_provider.close_session()

            log.info(f"[Gemini Audio] Session ended for call {self.call_id}")
            return True

        except Exception as e:
            log.error(f"[Gemini Audio] Error ending session: {e}")
            return False


# ---------------------------------------------------------------------- #
# Session registry (one entry per call)
# ---------------------------------------------------------------------- #
_audio_sessions: Dict[str, GeminiAudioSession] = {}
_sessions_lock = asyncio.Lock()


async def create_gemini_audio_session(
    call_id: str,
    language: str = "en",
    system_prompt: Optional[str] = None,
    media_session=None,
) -> Optional[GeminiAudioSession]:
    """
    Create the Gemini audio session for a call.
    Pass media_session so reply audio can reach the caller's TX queue.
    """
    try:
        async with _sessions_lock:
            if call_id in _audio_sessions:
                log.warning(f"[Gemini Audio] Session already exists for call {call_id}")
                return _audio_sessions[call_id]

            session = GeminiAudioSession(call_id, language)
            if media_session is not None:
                session.attach_media(media_session)

            if await session.initialize_session(system_prompt):
                _audio_sessions[call_id] = session
                log.info(f"[Gemini Audio] ✅ Audio session created: {call_id}")
                return session

            log.error("[Gemini Audio] Failed to create audio session")
            return None

    except Exception as e:
        log.error(f"[Gemini Audio] Error creating session: {e}")
        return None


async def get_gemini_audio_session(call_id: str) -> Optional[GeminiAudioSession]:
    async with _sessions_lock:
        return _audio_sessions.get(call_id)


async def end_gemini_audio_session(call_id: str) -> bool:
    try:
        async with _sessions_lock:
            session = _audio_sessions.pop(call_id, None)
            if session:
                await session.end_session()
                log.info(f"[Gemini Audio] Session ended: {call_id}")
                return True
            log.warning(f"[Gemini Audio] No session found for call {call_id}")
            return False
    except Exception as e:
        log.error(f"[Gemini Audio] Error ending session: {e}")
        return False


async def cleanup_all_sessions() -> bool:
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
    return get_gemini_live_provider()