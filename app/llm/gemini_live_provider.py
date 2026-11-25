"""
Gemini Live Provider - continuous speech-to-speech conversation (google-genai SDK)

Audio contract:
  Input  : 16 kHz, 16-bit mono PCM bytes. Send continuously at real-time pace.
  Output : Gemini replies with 24 kHz, 16-bit mono PCM.
           Each reply chunk is converted to 8 kHz G.711 mu-law and passed to
           on_ulaw_chunk, ready for RTP.

Turn-taking is handled by Gemini's voice activity detection. The session stays
open for the whole call and ends when audio_input_stream ends.
"""

import os
import asyncio
import audioop
from typing import Optional, Dict, Any, Callable, AsyncIterator
from datetime import datetime

from ..core.config import log
from .live_prompt import build_live_system_instruction

INPUT_MIME = "audio/pcm;rate=16000"


class OutboundResampler:
    """
    Converts Gemini's 24 kHz 16-bit PCM into 8 kHz mu-law for RTP.
    Keeps resampler state and buffers about 100 ms before converting.
    Create one instance per call.
    """

    SRC_RATE = 24000
    DST_RATE = 8000
    MIN_BYTES = SRC_RATE * 2 // 10  # 100 ms of 16-bit mono at 24 kHz

    def __init__(self):
        self._buf = bytearray()
        self._state = None

    def push(self, pcm24k: bytes) -> bytes:
        self._buf.extend(pcm24k)
        if len(self._buf) < self.MIN_BYTES:
            return b""
        return self._convert(self._take())

    def flush(self) -> bytes:
        if not self._buf:
            return b""
        return self._convert(self._take())

    def reset(self) -> None:
        """Drop buffered audio, used on barge-in."""
        self._buf.clear()
        self._state = None

    def _take(self) -> bytes:
        chunk = bytes(self._buf)
        self._buf.clear()
        if len(chunk) % 2:  # keep whole 16-bit samples only
            chunk = chunk[:-1]
        return chunk

    def _convert(self, pcm24k: bytes) -> bytes:
        if not pcm24k:
            return b""
        pcm8k, self._state = audioop.ratecv(
            pcm24k, 2, 1, self.SRC_RATE, self.DST_RATE, self._state
        )
        return audioop.lin2ulaw(pcm8k, 2)


class GeminiLiveProvider:
    """Gemini Live API provider for real-time speech-to-speech conversations."""

    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY", "")
        self.model = os.getenv("GEMINI_LIVE_MODEL", "gemini-2.0-flash-live-001")
        self.text_model = os.getenv("GEMINI_TEXT_MODEL", "gemini-2.5-flash")
        self.voice = os.getenv("GEMINI_VOICE", "Aoede")
        self.temperature = float(os.getenv("LLM_TEMPERATURE", "0.3"))
        self.max_tokens = int(os.getenv("LLM_MAX_TOKENS", "500"))

        self.client = None
        self.session = None
        self.session_id = None
        self.audio_config = {"encoding": "LINEAR16", "sample_rate_hertz": 16000}

    # ------------------------------------------------------------------ #
    # Setup
    # ------------------------------------------------------------------ #
    async def initialize(self) -> bool:
        if not self.api_key:
            log.error("[Gemini Live] GEMINI_API_KEY not configured")
            return False
        try:
            from google import genai

            self.client = genai.Client(
                api_key=self.api_key,
                http_options={"api_version": "v1beta"},
            )
            log.info("[Gemini Live] Client initialized (google-genai SDK)")
            log.info(f"[Gemini Live]    ├─ Live model: {self.model}")
            log.info(f"[Gemini Live]    ├─ Text model: {self.text_model}")
            log.info(f"[Gemini Live]    ├─ Voice: {self.voice}")
            log.info(f"[Gemini Live]    └─ Temperature: {self.temperature}, Max tokens: {self.max_tokens}")
            return True
        except ImportError:
            log.error("[Gemini Live] google-genai not installed. Run: pip install google-genai")
            return False
        except Exception as e:
            log.error(f"[Gemini Live] Initialization failed: {e}", exc_info=True)
            return False

    async def create_live_session(self, system_prompt: Optional[str] = None) -> bool:
        """Create the per-call session record. The WebSocket opens in stream_audio_bidirectional()."""
        try:
            if not self.client and not await self.initialize():
                return False

            self.session_id = f"session_{int(datetime.utcnow().timestamp() * 1000)}"
            self.session = {
                "session_id": self.session_id,
                "created_at": datetime.utcnow().isoformat(),
                "model": self.model,
                "voice": self.voice,
                "status": "active",
                # Default is the full question script from live_prompt.py
                "system_prompt": system_prompt or build_live_system_instruction(),
                "audio_config": self.audio_config,
            }
            log.info(f"[Gemini Live] Session created: {self.session_id}")
            return True
        except Exception as e:
            log.error(f"[Gemini Live] Session creation error: {e}", exc_info=True)
            return False

    # ------------------------------------------------------------------ #
    # Live conversation
    # ------------------------------------------------------------------ #
    async def stream_audio_bidirectional(
        self,
        audio_input_stream: AsyncIterator[bytes],
        on_ulaw_chunk: Optional[Callable[[bytes], None]] = None,
        on_audio_chunk: Optional[Callable[[bytes], None]] = None,
        on_text_chunk: Optional[Callable[[str], None]] = None,
        on_interrupted: Optional[Callable[[], None]] = None,
        greeting_text: Optional[str] = None,
    ) -> Optional[bytes]:
        """
        Run one live conversation for the whole call.

        audio_input_stream: yields 16 kHz 16-bit mono PCM until the caller hangs up.
        on_ulaw_chunk:      8 kHz mu-law bytes ready for RTP (use this for the call).
        on_audio_chunk:     raw 24 kHz PCM from Gemini (optional, for logging/recording).
        on_text_chunk:      text transcript of Gemini's reply.
        on_interrupted:     called when the caller barges in. Clear the TX queue here.
        greeting_text:      greeting Gemini speaks once, before the caller answers.

        Returns all reply audio as 24 kHz PCM, or None.
        """
        from google.genai import types

        if not self.session or not self.client:
            log.error("[Gemini Live] Session not active - cannot stream audio")
            return None

        model_name = self.model if self.model.startswith("models/") else f"models/{self.model}"

        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=self.session.get("system_prompt") or build_live_system_instruction(),
            generation_config=types.GenerationConfig(
                temperature=self.temperature,
                max_output_tokens=self.max_tokens,
            ),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=self.voice)
                )
            ),
        )

        stats = {"sent": 0, "reply_chunks": 0, "turns": 0, "interrupts": 0}
        response_audio = bytearray()
        resampler = OutboundResampler()

        def emit_ulaw(ulaw: bytes):
            if ulaw and on_ulaw_chunk:
                on_ulaw_chunk(ulaw)

        try:
            async with self.client.aio.live.connect(model=model_name, config=config) as live:
                log.info(f"[Gemini Live] WebSocket connected: {self.session_id}")

                if greeting_text:
                    # Sent as an instruction, so the model speaks it instead of replying to it
                    await live.send_client_content(
                        turns=types.Content(
                            role="user",
                            parts=[types.Part(text=(
                                "The call has connected. Say this greeting once, exactly as written, "
                                "then wait for the customer to reply: " + greeting_text
                            ))],
                        ),
                        turn_complete=True,
                    )
                    log.info("[Gemini Live] Greeting sent")

                async def send_audio():
                    try:
                        async for chunk in audio_input_stream:
                            if not chunk:
                                continue
                            await live.send_realtime_input(
                                audio=types.Blob(data=chunk, mime_type=INPUT_MIME)
                            )
                            stats["sent"] += 1
                    finally:
                        log.info(f"[Gemini Live] Caller audio stream ended after {stats['sent']} frames")

                async def receive_audio():
                    # Runs for the whole call, one turn at a time
                    while True:
                        got_message = False
                        async for message in live.receive():
                            got_message = True
                            sc = message.server_content
                            if sc is None:
                                continue

                            if getattr(sc, "interrupted", False):
                                stats["interrupts"] += 1
                                resampler.reset()
                                log.info("[Gemini Live] Caller barged in: clearing reply audio")
                                if on_interrupted:
                                    on_interrupted()

                            if sc.model_turn and sc.model_turn.parts:
                                for part in sc.model_turn.parts:
                                    if part.text and on_text_chunk:
                                        on_text_chunk(part.text)
                                    if part.inline_data and part.inline_data.data:
                                        data = part.inline_data.data
                                        stats["reply_chunks"] += 1
                                        response_audio.extend(data)
                                        if on_audio_chunk:
                                            on_audio_chunk(data)
                                        emit_ulaw(resampler.push(data))

                            if sc.turn_complete:
                                stats["turns"] += 1
                                log.info(f"[Gemini Live] Turn {stats['turns']} complete")

                        if not got_message:
                            log.warning("[Gemini Live] Server closed the receive stream")
                            return

                send_task = asyncio.create_task(send_audio())
                recv_task = asyncio.create_task(receive_audio())
                try:
                    # The call lasts as long as the caller's audio
                    await send_task
                finally:
                    recv_task.cancel()
                    send_task.cancel()
                    await asyncio.gather(send_task, recv_task, return_exceptions=True)

        except Exception as e:
            log.error(
                f"[Gemini Live] Conversation failed after {stats['sent']} frames: {e}",
                exc_info=True,
            )

        emit_ulaw(resampler.flush())

        log.info(
            f"[Gemini Live] Conversation ended: sent={stats['sent']} frames, "
            f"turns={stats['turns']}, interrupts={stats['interrupts']}, "
            f"reply_chunks={stats['reply_chunks']}, reply_bytes={len(response_audio)}"
        )
        return bytes(response_audio) if response_audio else None

    # ------------------------------------------------------------------ #
    # Text helpers (standard generate API, not Live)
    # ------------------------------------------------------------------ #
    async def get_text_response(self, prompt: str, system_prompt: Optional[str] = None) -> Optional[str]:
        from google.genai import types

        if not self.client:
            log.error("[Gemini Live] Client not initialized")
            return None
        try:
            response = await self.client.aio.models.generate_content(
                model=self.text_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt or "You are a professional sales assistant.",
                    temperature=self.temperature,
                    max_output_tokens=self.max_tokens,
                ),
            )
            return response.text
        except Exception as e:
            log.error(f"[Gemini Live] Text generation error: {e}", exc_info=True)
            return None

    async def stream_response(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        on_chunk: Optional[Callable[[str], None]] = None,
    ) -> Optional[str]:
        from google.genai import types

        if not self.client:
            log.error("[Gemini Live] Client not initialized")
            return None
        try:
            full_response = ""
            stream = await self.client.aio.models.generate_content_stream(
                model=self.text_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt or "You are a professional sales assistant.",
                    temperature=self.temperature,
                    max_output_tokens=self.max_tokens,
                ),
            )
            async for chunk in stream:
                if chunk.text:
                    full_response += chunk.text
                    if on_chunk:
                        on_chunk(chunk.text)
            return full_response or None
        except Exception as e:
            log.error(f"[Gemini Live] Streaming error: {e}", exc_info=True)
            return None

    # ------------------------------------------------------------------ #
    # Session lifecycle
    # ------------------------------------------------------------------ #
    async def close_session(self) -> bool:
        try:
            if self.session:
                self.session["status"] = "closed"
                self.session["closed_at"] = datetime.utcnow().isoformat()
                log.info(f"[Gemini Live] Session closed: {self.session_id}")
                self.session = None
            return True
        except Exception as e:
            log.error(f"[Gemini Live] Session close error: {e}")
            return False

    def get_session_info(self) -> Optional[Dict[str, Any]]:
        return self.session.copy() if self.session else None


_provider: Optional[GeminiLiveProvider] = None


async def init_gemini_live_provider():
    global _provider
    _provider = GeminiLiveProvider()
    if await _provider.initialize():
        log.info("[Gemini Live] Provider initialized (google-genai SDK)")
    return _provider


def get_gemini_live_provider() -> Optional[GeminiLiveProvider]:
    return _provider