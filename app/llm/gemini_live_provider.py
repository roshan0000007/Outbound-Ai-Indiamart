"""
Gemini Live Provider - Speech-to-speech audio streaming (google-genai SDK)

Audio contract:
  Input  : 16 kHz, 16-bit mono PCM bytes. Upsample the 8 kHz caller audio first.
  Output : Gemini replies with 24 kHz, 16-bit mono PCM bytes.
           stream_audio_bidirectional() also converts each reply chunk to
           8 kHz G.711 mu-law and passes it to on_ulaw_chunk, ready for RTP.
"""

import os
import asyncio
import audioop
from typing import Optional, Dict, Any, Callable, AsyncIterator
from datetime import datetime

from ..core.config import log

INPUT_MIME = "audio/pcm;rate=16000"
DEFAULT_SYSTEM_PROMPT = "You are a helpful sales assistant. Respond concisely and naturally."
DEFAULT_TEXT_SYSTEM_PROMPT = "You are a professional sales assistant."


class OutboundResampler:
    """
    Converts Gemini's 24 kHz 16-bit PCM into 8 kHz mu-law for RTP.

    Keeps resampler state across calls and buffers about 100 ms of input before
    converting. Converting single small chunks with no state produces empty output.
    Create one instance per call.
    """

    SRC_RATE = 24000
    DST_RATE = 8000
    MIN_BYTES = SRC_RATE * 2 // 10  # 100 ms of 16-bit mono at 24 kHz

    def __init__(self):
        self._buf = bytearray()
        self._state = None

    def push(self, pcm24k: bytes) -> bytes:
        """Add 24 kHz PCM. Returns mu-law bytes once enough audio is buffered, else b''."""
        self._buf.extend(pcm24k)
        if len(self._buf) < self.MIN_BYTES:
            return b""
        return self._convert(self._take())

    def flush(self) -> bytes:
        """Convert whatever is left at the end of a reply."""
        if not self._buf:
            return b""
        return self._convert(self._take())

    def _take(self) -> bytes:
        chunk = bytes(self._buf)
        self._buf.clear()
        # Keep only whole 16-bit samples
        if len(chunk) % 2:
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
        self.reply_timeout = float(os.getenv("GEMINI_REPLY_TIMEOUT", "15"))

        self.client = None
        self.session = None
        self.session_id = None
        self.audio_config = {"encoding": "LINEAR16", "sample_rate_hertz": 16000}

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
        """Create the per-call session record. The WebSocket opens in stream_audio_bidirectional()."""
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
        on_ulaw_chunk: Optional[Callable[[bytes], None]] = None,
        on_text_chunk: Optional[Callable[[str], None]] = None,
        greeting_text: Optional[str] = None,
    ) -> Optional[bytes]:
        """
        Stream caller audio to Gemini Live and route its audio reply back.

        audio_input_stream: yields 16 kHz 16-bit mono PCM bytes.
        on_audio_chunk:     raw 24 kHz 16-bit mono PCM from Gemini (optional).
        on_ulaw_chunk:      8 kHz mu-law bytes ready for RTP (use this for the call).
        on_text_chunk:      text transcript of Gemini's reply.
        greeting_text:      optional text Gemini speaks first.

        Returns the full reply audio as 24 kHz PCM, or None.
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
        sent_all = asyncio.Event()     # caller audio fully sent
        turn_done = asyncio.Event()    # Gemini finished replying after the caller audio
        greeting_pending = bool(greeting_text)
        resampler = OutboundResampler()

        def emit_ulaw(ulaw: bytes):
            if ulaw and on_ulaw_chunk:
                on_ulaw_chunk(ulaw)

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
                    try:
                        async for chunk in audio_input_stream:
                            if not chunk:
                                continue
                            await live.send_realtime_input(
                                audio=types.Blob(data=chunk, mime_type=INPUT_MIME)
                            )
                            frame_count += 1
                    except asyncio.CancelledError:
                        log.warning(f"[Gemini Live] Caller audio generator cancelled after {frame_count} frames")
                        raise
                    finally:
                        log.info(f"[Gemini Live] Caller audio sent: {frame_count} frames")
                        sent_all.set()

                async def receive_audio():
                    nonlocal response_chunks, greeting_pending
                    while not turn_done.is_set():
                        got_message = False
                        async for message in live.receive():
                            got_message = True
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
                                        log.info(
                                            f"[Gemini Live] Reply chunk {response_chunks}: "
                                            f"{len(data)} bytes, mime={part.inline_data.mime_type}"
                                        )
                                        response_audio.extend(data)
                                        if on_audio_chunk:
                                            on_audio_chunk(data)
                                        emit_ulaw(resampler.push(data))

                            if sc.turn_complete:
                                # The greeting's turn completes first; ignore it.
                                if greeting_pending and not sent_all.is_set():
                                    greeting_pending = False
                                    log.info("[Gemini Live] Greeting reply complete")
                                    continue
                                if sent_all.is_set():
                                    turn_done.set()
                                    return

                        if not got_message:
                            break  # stream closed by the server

                send_task = asyncio.create_task(send_audio())
                recv_task = asyncio.create_task(receive_audio())
                try:
                    await sent_all.wait()
                    # Give Gemini time to answer the last caller utterance
                    await asyncio.wait_for(turn_done.wait(), timeout=self.reply_timeout)
                except asyncio.TimeoutError:
                    log.warning(f"[Gemini Live] No turn completion within {self.reply_timeout}s after caller audio")
                finally:
                    for t in (send_task, recv_task):
                        t.cancel()
                    await asyncio.gather(send_task, recv_task, return_exceptions=True)

        except Exception as e:
            log.error(
                f"[Gemini Live] Streaming failed (frames sent: {frame_count}): {e}",
                exc_info=True,
            )

        # Flush the last partial block of resampled audio
        emit_ulaw(resampler.flush())

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
                    system_instruction=system_prompt or DEFAULT_TEXT_SYSTEM_PROMPT,
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
                    system_instruction=system_prompt or DEFAULT_TEXT_SYSTEM_PROMPT,
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