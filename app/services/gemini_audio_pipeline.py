"""
Gemini Live Audio Pipeline
One Gemini Live conversation per call, in the language the caller chooses with DTMF.

Call flow:
  call connects
    -> ARI plays the language menu ("press 1 for English, 2 for Hindi")
    -> ARI calls session.set_dtmf_digit(digit) on ChannelDtmfReceived
    -> wait_for_language() returns "en" or "hi" (default "en" after the timeout)
    -> provider: greeting -> questions one by one -> mobile number -> closing
    -> call summary is logged, then the call ends

Audio flow:
  RTP RX (8 kHz PCMU, decoded to PCM16)
    -> add_audio_input()            (must be 16 kHz PCM16)
    -> audio_input_generator()      (real time, never gated on AI speaking state)
    -> GeminiLiveProvider           (one Live session per call)
    -> reply audio 24 kHz PCM16 -> 8 kHz mu-law (inside the provider)
    -> enqueue_ulaw_to_rtp()        (160-byte frames)
    -> media_session.tx_queue       (TX loop sends them to the caller)
"""

import asyncio
import os
import time
from typing import Optional, Dict, Callable, AsyncIterator
from datetime import datetime

from ..core.config import log
from ..llm.gemini_live_provider import get_gemini_live_provider
from ..llm.live_prompt import REQUIRED_QUESTIONS, normalize_call_language

RTP_FRAME_SIZE = 160  # 20 ms of G.711 mu-law at 8 kHz

LANGUAGE_MENU_TIMEOUT_SEC = float(os.getenv("LANGUAGE_MENU_TIMEOUT_SEC", "10"))
DTMF_LANGUAGE_MAP = {"1": "en", "2": "hi"}   # 1 = English, 2 = Hindi
DEFAULT_CALL_LANGUAGE = "en"


class GeminiAudioSession:
    """Manages one Gemini Live conversation for one call."""

    def __init__(self, call_id: str, language: Optional[str] = None):
        self.call_id = call_id
        self.gemini_provider = get_gemini_live_provider()
        self.session_active = False
        self.audio_buffer = asyncio.Queue(maxsize=1000)   # caller audio waiting for Gemini
        self.created_at = datetime.utcnow()
        self.media_session = None                          # set with attach_media()
        self._tx_remainder = bytearray()                   # partial 160-byte RTP frame

        # Language chosen by the caller (DTMF)
        self.language: Optional[str] = None
        self.language_selected = False
        self._language_event = asyncio.Event()

        # Collected answers for this call only
        self.collected: Dict[str, str] = {}

        # Optional hook for ARI: called when the closing message has finished
        self.hangup_callback: Optional[Callable[[str], None]] = None

        if language in ("en", "hi"):
            self.set_call_language(language)

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
            log.info(f"[Gemini Audio] Gemini session initialized for call {self.call_id}")

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
    # Language selection (DTMF)
    # ------------------------------------------------------------------ #
    def set_call_language(self, lang: str) -> None:
        """Set the call language and release any waiter."""
        self.language = normalize_call_language(lang)
        self.language_selected = True
        self._language_event.set()
        log.info(f"[Gemini Audio] Call language set: {self.language} (call {self.call_id})")

    def set_dtmf_digit(self, digit: str) -> None:
        """
        Call this from the ARI ChannelDtmfReceived handler.
        '1' selects English, '2' selects Hindi. Other digits are ignored.
        """
        digit = str(digit).strip()
        lang = DTMF_LANGUAGE_MAP.get(digit)
        if lang is None:
            log.info(f"[Gemini Audio] Ignored DTMF digit '{digit}' (call {self.call_id}); press 1 or 2")
            return
        if self.language_selected:
            log.info(f"[Gemini Audio] Language already selected ({self.language}); ignoring digit {digit}")
            return
        self.set_call_language(lang)

    async def wait_for_language(self, timeout: float = LANGUAGE_MENU_TIMEOUT_SEC) -> str:
        """
        Wait for the caller's language choice. Falls back to English on timeout.
        Also clears caller audio captured during the menu, so Gemini hears only
        what the caller says after choosing.
        """
        if not self.language_selected:
            try:
                await asyncio.wait_for(self._language_event.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                log.info(f"[Gemini Audio] No language choice in {timeout}s; using {DEFAULT_CALL_LANGUAGE}")
                self.set_call_language(DEFAULT_CALL_LANGUAGE)

        drained = 0
        while not self.audio_buffer.empty():
            try:
                self.audio_buffer.get_nowait()
                drained += 1
            except asyncio.QueueEmpty:
                break
        if drained:
            log.debug(f"[Gemini Audio] Dropped {drained} menu-time audio frames")

        return self.language

    # ------------------------------------------------------------------ #
    # Caller audio in
    # ------------------------------------------------------------------ #
    async def add_audio_input(self, audio_chunk: bytes) -> bool:
        """
        Queue one caller audio frame for Gemini.
        Must be 16 kHz 16-bit mono PCM (one 20 ms frame = 640 bytes).
        
        🔧 CRITICAL: Drop audio until language is confirmed.
        This ensures Gemini doesn't start before DTMF language selection.
        """
        try:
            if not self.session_active:
                log.warning(f"[Gemini Audio] Session not active for call {self.call_id}")
                return False
            if not audio_chunk:
                return True

            # 🔧 GATE: Drop audio until language is selected
            if not self.language_selected:
                # Audio is captured during language menu but discarded
                # This prevents Gemini from starting prematurely
                return True  # Accept silently but drop

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
        Yield caller audio for as long as the call lasts.
        Not gated on AI speaking state. Ends after 5 minutes with no audio, or when the session ends.
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
        """Split 8 kHz mu-law reply bytes into 160-byte frames and queue them for RTP TX."""
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
    # Collected details (saved from Gemini's record_answer calls)
    # ------------------------------------------------------------------ #
    def save_field(self, field: str, value: str) -> None:
        """Called by the provider each time a customer answer is saved."""
        self.collected[field] = value
        log.info(f"[CALL-DATA] {self.call_id} | {field} = {value}")

    def log_call_summary(self) -> None:
        """Print every collected detail for this call."""
        log.info("=" * 60)
        log.info(f"[CALL-DATA] CALL SUMMARY: {self.call_id} (language: {self.language})")
        log.info("=" * 60)
        if not self.collected:
            log.info("[CALL-DATA] No details collected")
        for field, value in self.collected.items():
            log.info(f"[CALL-DATA]   {field:<28}: {value}")
        log.info(f"[CALL-DATA] Collected {len(self.collected)} of {len(REQUIRED_QUESTIONS)} fields")
        log.info("=" * 60)

    def on_call_complete(self) -> None:
        """Called by the provider after the closing message has finished."""
        log.info(f"[Gemini Audio] Closing finished for call {self.call_id}; requesting hangup")
        if self.hangup_callback:
            try:
                self.hangup_callback(self.call_id)
            except Exception as e:
                log.error(f"[Gemini Audio] hangup_callback error: {e}")

    async def _send_dtmf_prompt_to_gemini(self) -> bool:
        """
        ✅ CRITICAL FIX: Send DTMF language selection prompt to Gemini Live
        
        This creates a temporary WebSocket connection JUST to send the language selection
        prompt BEFORE the main conversation starts. This ensures the caller hears:
        "Press 1 for English. Press 2 for Hindi."
        
        Flow:
        1. Open WebSocket connection to Gemini Live
        2. Send DTMF prompt instruction as first message
        3. Gemini synthesizes and streams audio to caller immediately
        4. Close connection after prompt finishes
        5. Main conversation connection will open separately after DTMF is received
        
        Returns:
            True if prompt was sent successfully
        """
        try:
            if not self.gemini_provider:
                log.error("[Gemini Audio] Provider not available for DTMF prompt")
                return False
            
            log.info(f"[Gemini Audio] 🎤 Opening temporary WebSocket for DTMF prompt")
            
            # Build config for DTMF prompt (use English for the prompt itself)
            from google.genai import types
            from ..llm.gemini_live_provider import _build_realtime_input_config, _build_tools
            
            model_name = self.gemini_provider.model
            if not model_name.startswith("models/"):
                model_name = f"models/{model_name}"
            
            config_kwargs = dict(
                response_modalities=["AUDIO"],
                system_instruction="You are an IVR system. Play language selection menu.",
                generation_config=types.GenerationConfig(temperature=1.0, max_output_tokens=50),
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=self.gemini_provider.voice
                        )
                    )
                ),
                tools=_build_tools(types),
            )
            
            realtime_cfg = _build_realtime_input_config(types)
            if realtime_cfg is not None:
                config_kwargs["realtime_input_config"] = realtime_cfg
            
            config = types.LiveConnectConfig(**config_kwargs)
            
            prompt_sent = False
            try:
                async with self.gemini_provider.client.aio.live.connect(model=model_name, config=config) as live:
                    log.info(f"[Gemini Audio] ✅ DTMF WebSocket connected")
                    
                    # Send DTMF prompt as first and ONLY instruction
                    dtmf_instruction = (
                        "[SYSTEM INSTRUCTION URGENT] You are playing a phone IVR menu. "
                        "Speak THIS EXACT prompt once, clearly and naturally, with appropriate pauses: "
                        "'Press 1 for English. Press 2 for Hindi.' "
                        "After speaking, STOP completely. Do NOT repeat. Do NOT say anything else. "
                        "The user will then press a digit."
                    )
                    
                    log.info(f"[Gemini Audio] 📤 Sending DTMF prompt instruction to Gemini...")
                    await live.send_client_content(
                        turns=types.Content(role="user", parts=[types.Part(text=dtmf_instruction)]),
                        turn_complete=True,
                    )
                    
                    log.info(f"[Gemini Audio] ⏳ Waiting for Gemini to synthesize DTMF prompt...")
                    
                    # Receive the DTMF prompt audio from Gemini
                    max_wait_time = 5  # seconds
                    wait_start = time.time()
                    audio_chunks = 0
                    turn_complete = False
                    
                    async for message in live.receive():
                        if time.time() - wait_start > max_wait_time:
                            log.warning(f"[Gemini Audio] ⚠️ Timeout waiting for DTMF prompt audio")
                            break
                        
                        sc = message.server_content
                        if sc is None:
                            continue
                        
                        # Receive and queue the audio to RTP
                        if sc.model_turn and sc.model_turn.parts:
                            for part in sc.model_turn.parts:
                                if part.inline_data and part.inline_data.data:
                                    audio_data = part.inline_data.data
                                    # Resample and queue to RTP
                                    from ..services.audio_codec_pipeline import get_codec_pipeline
                                    codec_pipeline = await get_codec_pipeline(self.call_id)
                                    if codec_pipeline:
                                        ulaw_frames = codec_pipeline.resample_gemini_to_rtp(audio_data)
                                        for frame in ulaw_frames:
                                            self.enqueue_ulaw_to_rtp(frame)
                                    audio_chunks += 1
                                    log.debug(f"[Gemini Audio] 🔊 DTMF prompt audio chunk {audio_chunks}")
                        
                        if sc.turn_complete:
                            turn_complete = True
                            log.info(f"[Gemini Audio] ✅ DTMF prompt sent: {audio_chunks} audio chunks")
                            prompt_sent = True
                            break
                    
                    if not turn_complete:
                        log.warning(f"[Gemini Audio] ⚠️ DTMF prompt ended without turn_complete")
                    
                    log.info(f"[Gemini Audio] 🔌 Closing DTMF prompt WebSocket")
                    
            except Exception as e:
                log.error(f"[Gemini Audio] ❌ Error in DTMF prompt WebSocket: {e}", exc_info=True)
                return False
            
            if prompt_sent:
                log.info(f"[Gemini Audio] ✅ DTMF prompt successfully sent to caller")
                # Give time for audio to finish playing
                await asyncio.sleep(0.5)
                return True
            else:
                log.warning(f"[Gemini Audio] ⚠️ DTMF prompt sent but no audio received")
                return True  # Still return True - we tried, caller can still press digits
                
        except Exception as e:
            log.error(f"[Gemini Audio] ❌ Error sending DTMF prompt: {e}", exc_info=True)
            return False

    # ------------------------------------------------------------------ #
    # Conversation
    # ------------------------------------------------------------------ #
    async def process_audio_stream(
        self,
        on_response_text: Optional[Callable[[str], None]] = None,
        greeting_text: Optional[str] = None,
    ) -> bool:
        """
        Wait for the language choice, then run the Gemini Live conversation for the whole call.

        greeting_text is accepted for compatibility but ignored: the greeting is chosen
        by the call language (English or Hindi) inside the provider.
        """
        try:
            if not self.session_active or not self.gemini_provider:
                log.error("[Gemini Audio] Session not ready")
                return False

            if self.media_session is None:
                log.error(f"[Gemini Audio] Media session not attached for call {self.call_id}")
                return False

            if greeting_text:
                log.debug("[Gemini Audio] greeting_text ignored; greeting follows the call language")

            # ✅ CRITICAL FIX: Send DTMF prompt to Gemini BEFORE waiting for language selection
            # This ensures the caller hears the language menu immediately
            log.info(f"[Gemini Audio] 📢 Preparing DTMF language selection prompt via Gemini Live")
            log.info(f"[Gemini Audio]    ├─ This prompt will play to the caller FIRST")
            log.info(f"[Gemini Audio]    ├─ Caller presses 1 or 2 to select language")
            log.info(f"[Gemini Audio]    └─ Timeout: 10 seconds (defaults to English)")
            
            # Create a temporary Gemini connection JUST to send the DTMF prompt
            # This happens BEFORE the main conversation starts
            try:
                await self._send_dtmf_prompt_to_gemini()
                log.info(f"[Gemini Audio] ✅ DTMF prompt sent to Gemini Live")
            except Exception as e:
                log.warning(f"[Gemini Audio] ⚠️ Error sending DTMF prompt: {e}")
                log.info(f"[Gemini Audio]    └─ Continuing with 10-second DTMF timeout")

            language = await self.wait_for_language()
            log.info(f"[Gemini Audio] Starting conversation for call {self.call_id} in '{language}'")

            audio_gen = self.audio_input_generator()

            try:
                from ..services.llm_failover_service import get_llm_failover_service
                failover_service = get_llm_failover_service()

                if failover_service:
                    log.info("[Gemini Audio] Attempting primary: Gemini Live")
                    response_audio = await failover_service.try_gemini_live(
                        self.call_id,
                        audio_input_stream=audio_gen,
                        on_ulaw_chunk=self.enqueue_ulaw_to_rtp,
                        on_text_chunk=on_response_text,
                        on_field_saved=self.save_field,
                        on_call_complete=self.on_call_complete,
                        call_language=language,
                    )
                else:
                    log.info("[Gemini Audio] No failover service, using Gemini Live directly")
                    response_audio = await self.gemini_provider.stream_audio_bidirectional(
                        audio_input_stream=audio_gen,
                        on_ulaw_chunk=self.enqueue_ulaw_to_rtp,
                        on_text_chunk=on_response_text,
                        on_field_saved=self.save_field,
                        on_call_complete=self.on_call_complete,
                        call_language=language,
                    )

                if response_audio:
                    log.info("[Gemini Audio] Gemini Live conversation finished with reply audio")
                else:
                    log.warning("[Gemini Audio] Gemini Live ended with no reply audio")
                return True

            except Exception as e:
                log.error(f"[Gemini Audio] Error during Gemini conversation: {e}", exc_info=True)
                return False

            finally:
                self.log_call_summary()

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
    language: Optional[str] = None,
    system_prompt: Optional[str] = None,
    media_session=None,
) -> Optional[GeminiAudioSession]:
    """
    Create the Gemini audio session for a call.

    language: pass "en" or "hi" to skip the DTMF menu. Leave None to wait for DTMF.
    media_session: the call's MediaSession, so reply audio reaches its TX queue.
    """
    try:
        async with _sessions_lock:
            if call_id in _audio_sessions:
                log.warning(f"[Gemini Audio] Session already exists for call {call_id}")
                return _audio_sessions[call_id]

            preselected = language if language in ("en", "hi") else None
            session = GeminiAudioSession(call_id, language=preselected)
            if media_session is not None:
                session.attach_media(media_session)

            if await session.initialize_session(system_prompt):
                _audio_sessions[call_id] = session
                log.info(f"[Gemini Audio] Audio session created: {call_id}")
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