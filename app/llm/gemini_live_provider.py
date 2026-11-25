"""
Gemini Live Provider - Speech-to-Speech audio streaming (google-genai SDK)

Audio contract:
  Input  : 16 kHz, 16-bit mono PCM bytes (upsample the 8 kHz caller audio first)
  Output : Gemini replies with 24 kHz, 16-bit mono PCM bytes.
           Use pcm24k_to_pcmu8k() before sending the audio to RTP.
"""

import os
import asyncio
import audioop
from typing import Optional, Dict, Any, Callable, AsyncIterator
from datetime import datetime

from ..core.config import log

INPUT_MIME = "audio/pcm;rate=16000"
DEFAULT_SYSTEM_PROMPT = "You are a helpful sales assistant. Respond concisely and naturally."


def pcm24k_to_pcmu8k(pcm24k: bytes, state=None):
    """
    Convert Gemini's 24 kHz 16-bit mono PCM into 8 kHz G.711 mu-law bytes for RTP.
    Pass the returned state back on the next call so resampling stays continuous.
    Returns (ulaw_bytes, state).
    """
    pcm8k, state = audioop.ratecv(pcm24k, 2, 1, 24000, 8000, state)
    return audioop.lin2ulaw(pcm8k, 2), state


class GeminiLiveProvider:
    """Gemini Live API provider for real-time speech-to-speech conversations."""

    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY", "")
        self.model = os.getenv("GEMINI_LIVE_MODEL", "gemini-2.0-flash-live-001")
        self.text_model = os.getenv("GEMINI_TEXT_MODEL", "gemini-2.5-flash")
        self.voice = os.getenv("GEMINI_VOICE", "Aoede")
        self.temperature = float(os.getenv("LLM_TEMPERATURE", "0.3"))
        self.max_tokens = int(os.getenv("LLM_MAX_TOKENS", "500"))
        self.reply_timeout = float(os.getenv("GEMINI_REPLY_TIMEOUT", "15"))

        self.client = None
        self.session = None
        self.session_id = None
        self.audio_config = {"encoding": "LINEAR16", "sample_rate_hertz": 16000}

        # Set once a session is created; reset for each call
        self.session_ready_event = asyncio.Event()

    # ------------------------------------------------------------------ #
    # Setup
    # ------------------------------------------------------------------ #
    async def initialize(self) -> bool:
        """Create the google-genai client."""
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
        """Create the per-call session record. The WebSocket opens in stream_audio_bidirectional."""
        try:
            if not self.client and not await self.initialize():
                return False

            self.session_ready_event.clear()
            self.session_id = f"session_{int(datetime.utcnow().timestamp() * 1000)}"

            self.session = {
                "session_id": self.session_id,
                "created_at": datetime.utcnow().isoformat(),
                "model": self.model,
                "voice": self.voice,
                "status": "active",
                "system_prompt": system_prompt or DEFAULT_SYSTEM_PROMPT,
                "audio_config": self.audio_config,
            }
            self.session_ready_event.set()
            log.info(f"[Gemini Live] Session created: {self.session_id}")
            return True
        except Exception as e:
            log.error(f"[Gemini Live] Session creation error: {e}", exc_info=True)
            return False

    # ------------------------------------------------------------------ #
    # Live audio streaming
    # ------------------------------------------------------------------ #
    async def stream_audio_bidirectional(
        self,
        audio_input_stream: AsyncIterator[bytes],
        on_audio_chunk: Optional[Callable[[bytes], None]] = None,
        on_text_chunk: Optional[Callable[[str], None]] = None,
        greeting_text: Optional[str] = None,
    ) -> Optional[bytes]:
        """
        Stream caller audio to Gemini Live and route its audio reply back.

        audio_input_stream: yields 16 kHz 16-bit mono PCM bytes.
        on_audio_chunk:     receives 24 kHz 16-bit mono PCM bytes from Gemini.
        on_text_chunk:      receives text transcripts of Gemini's reply.
        greeting_text:      optional text Gemini speaks first.

        Returns the full reply audio (24 kHz PCM), or None.
        """
        from google.genai import types

        if not self.session or not self.client:
            log.error("[Gemini Live] Session not active - cannot stream audio")
            return None

        model_name = self.model if self.model.startswith("models/") else f"models/{self.model}"

        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=self.session.get("system_prompt", DEFAULT_SYSTEM_PROMPT),
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

        response_audio = bytearray()
        frame_count = 0
        response_chunks = 0
        turn_done = asyncio.Event()

        try:
            async with self.client.aio.live.connect(model=model_name, config=config) as live:
                log.info(f"[Gemini Live] WebSocket connected: {self.session_id}")

                if greeting_text:
                    await live.send_client_content(
                        turns=types.Content(role="user", parts=[types.Part(text=greeting_text)]),
                        turn_complete=True,
                    )
                    log.info("[Gemini Live] Greeting sent")

                async def send_audio():
                    nonlocal frame_count
                    async for chunk in audio_input_stream:
                        if not chunk:
                            continue
                        await live.send_realtime_input(
                            audio=types.Blob(data=chunk, mime_type=INPUT_MIME)
                        )
                        frame_count += 1
                    log.info(f"[Gemini Live] Caller audio sent: {frame_count} frames")

                async def receive_audio():
                    nonlocal response_chunks
                    # receive() yields messages for the current turn; loop to keep reading
                    while True:
                        async for message in live.receive():
                            sc = message.server_content
                            if sc is None:
                                continue
                            if sc.model_turn and sc.model_turn.parts:
                                for part in sc.model_turn.parts:
                                    if part.text and on_text_chunk:
                                        on_text_chunk(part.text)
                                    if part.inline_data and part.inline_data.data:
                                        data = part.inline_data.data
                                        response_chunks += 1
                                        response_audio.extend(data)
                                        if on_audio_chunk:
                                            on_audio_chunk(data)
                            if sc.turn_complete:
                                turn_done.set()

                send_task = asyncio.create_task(send_audio())
                recv_task = asyncio.create_task(receive_audio())
                try:
                    await send_task
                    # Wait for Gemini to finish replying to the last caller audio
                    await asyncio.wait_for(turn_done.wait(), timeout=self.reply_timeout)
                except asyncio.TimeoutError:
                    log.warning(f"[Gemini Live] No turn completion within {self.reply_timeout}s")
                finally:
                    for t in (send_task, recv_task):
                        t.cancel()
                    await asyncio.gather(send_task, recv_task, return_exceptions=True)

        except Exception as e:
            log.error(
                f"[Gemini Live] Streaming failed (frames sent: {frame_count}): {e}",
                exc_info=True,
            )

        log.info(
            f"[Gemini Live] Done: sent={frame_count} frames, "
            f"received={response_chunks} audio chunks, {len(response_audio)} bytes"
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
    """Create and initialize the global provider."""
    global _provider
    _provider = GeminiLiveProvider()
    if await _provider.initialize():
        log.info("[Gemini Live] Provider initialized (google-genai SDK)")
    return _provider


def get_gemini_live_provider() -> Optional[GeminiLiveProvider]:
    return _provider