"""
Gemini Live Provider - continuous speech-to-speech conversation (google-genai SDK)

Audio contract:
  Input  : 16 kHz, 16-bit mono PCM. Send continuously at real-time pace.
  Output : 24 kHz, 16-bit mono PCM from Gemini, converted to 8 kHz G.711 mu-law
           and passed to on_ulaw_chunk.

Question flow (code-driven):
  greeting -> question 1 -> record_answer -> next unanswered question -> ... -> closing
"""

import os
import array
import asyncio
import audioop
from typing import Optional, Dict, Any, Callable, AsyncIterator
from datetime import datetime

from ..core.config import log
from .live_prompt import (
    REQUIRED_QUESTIONS,
    RECORD_FIELDS,
    build_live_system_instruction,
    question_instruction,
    closing_instruction,
)

INPUT_MIME = "audio/pcm;rate=16000"


class OutboundResampler:
    """
    Converts Gemini's 24 kHz 16-bit PCM into 8 kHz mu-law for RTP.
    Averages each group of 3 samples (24 kHz -> 8 kHz is exactly 3:1) to reduce aliasing.
    Create one instance per call.
    """

    MIN_SAMPLES = 2400  # 100 ms at 24 kHz

    def __init__(self):
        self._pending = array.array("h")

    def push(self, pcm24k: bytes) -> bytes:
        usable = pcm24k[: len(pcm24k) // 2 * 2]
        samples = array.array("h")
        samples.frombytes(usable)
        self._pending.extend(samples)
        if len(self._pending) < self.MIN_SAMPLES:
            return b""
        return self._emit(final=False)

    def flush(self) -> bytes:
        if not self._pending:
            return b""
        return self._emit(final=True)

    def reset(self) -> None:
        self._pending = array.array("h")

    def _emit(self, final: bool) -> bytes:
        if final and len(self._pending) % 3:
            self._pending.extend([0] * (3 - len(self._pending) % 3))
        n = len(self._pending) // 3 * 3
        if n == 0:
            return b""
        block = self._pending[:n]
        del self._pending[:n]
        out = array.array("h", [sum(block[i:i + 3]) // 3 for i in range(0, n, 3)])
        return audioop.lin2ulaw(out.tobytes(), 2)


def _build_realtime_input_config(types):
    """Turn off barge-in so the caller's speech cannot cut off a reply."""
    try:
        return types.RealtimeInputConfig(
            activity_handling=types.ActivityHandling.NO_INTERRUPTION,
        )
    except AttributeError:
        log.warning("[Gemini Live] ActivityHandling.NO_INTERRUPTION not available; barge-in stays enabled")
        return None


def _build_tools(types):
    """Declare record_answer so the model can save each answer."""
    return [types.Tool(function_declarations=[types.FunctionDeclaration(
        name="record_answer",
        description="Save one detail the customer just gave. Call once per detail.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "field": types.Schema(
                    type=types.Type.STRING,
                    enum=RECORD_FIELDS,
                    description="Field key from the list in the instructions",
                ),
                "value": types.Schema(
                    type=types.Type.STRING,
                    description="The value as the customer said it",
                ),
            },
            required=["field", "value"],
        ),
    )])]


class GeminiLiveProvider:
    """Gemini Live API provider for real-time speech-to-speech conversations."""

    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY", "")
        self.model = os.getenv("GEMINI_LIVE_MODEL", "gemini-2.0-flash-live-001")
        self.text_model = os.getenv("GEMINI_TEXT_MODEL", "gemini-2.5-flash")
        self.voice = os.getenv("GEMINI_VOICE", "Kore")
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
        on_field_saved: Optional[Callable[[str, str], None]] = None,
        on_call_complete: Optional[Callable[[], None]] = None,
        greeting_text: Optional[str] = None,
    ) -> Optional[bytes]:
        """
        Run one live conversation for the whole call.

        audio_input_stream: 16 kHz 16-bit mono PCM until the caller hangs up.
        on_ulaw_chunk:      8 kHz mu-law bytes for RTP (the call's audio output).
        on_audio_chunk:     raw 24 kHz PCM from Gemini (optional, for logging only).
        on_text_chunk:      text transcript of Gemini's reply.
        on_interrupted:     only fires if barge-in is enabled (not with NO_INTERRUPTION).
        on_field_saved:     called as on_field_saved(field, value) for each record_answer call.
                            Use it to write to Google Sheets / Excel.
        on_call_complete:   called once after the closing instruction has been sent.
        greeting_text:      greeting Gemini says once, before the first question.

        Returns all reply audio as 24 kHz PCM, or None.
        """
        from google.genai import types

        if not self.session or not self.client:
            log.error("[Gemini Live] Session not active - cannot stream audio")
            return None

        model_name = self.model if self.model.startswith("models/") else f"models/{self.model}"

        config_kwargs = dict(
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
            tools=_build_tools(types),
        )
        realtime_cfg = _build_realtime_input_config(types)
        if realtime_cfg is not None:
            config_kwargs["realtime_input_config"] = realtime_cfg
        config = types.LiveConnectConfig(**config_kwargs)

        stats = {"sent": 0, "reply_chunks": 0, "turns": 0, "interrupts": 0, "saved": 0}
        response_audio = bytearray()
        resampler = OutboundResampler()

        # Question state (owned by this call only)
        answered: set = set()           # field keys already saved
        question_asked: int = -1        # index of the last question sent
        greeting_pending = bool(greeting_text)
        closing_sent = False

        def emit_ulaw(ulaw: bytes):
            if ulaw and on_ulaw_chunk:
                on_ulaw_chunk(ulaw)

        def next_unanswered_index() -> Optional[int]:
            for i, q in enumerate(REQUIRED_QUESTIONS):
                if q["key"] not in answered:
                    return i
            return None

        async def send_instruction(live, text: str):
            await live.send_client_content(
                turns=types.Content(role="user", parts=[types.Part(text=text)]),
                turn_complete=True,
            )

        try:
            async with self.client.aio.live.connect(model=model_name, config=config) as live:
                log.info(f"[Gemini Live] WebSocket connected: {self.session_id}")

                if greeting_text:
                    await send_instruction(
                        live,
                        "[SYSTEM INSTRUCTION] The call has connected. Greet the customer once, "
                        "warmly and naturally, in your own words, keeping the same meaning as this "
                        "greeting: " + greeting_text + " Then wait for the customer to reply.",
                    )
                    log.info("[Gemini Live] Greeting sent")
                else:
                    # No greeting: ask question 1 right away
                    await send_instruction(live, question_instruction(0))
                    question_asked = 0

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
                    nonlocal greeting_pending, question_asked, closing_sent
                    while True:
                        got_message = False
                        async for message in live.receive():
                            got_message = True

                            # 1. Function calls: record_answer
                            tool_call = getattr(message, "tool_call", None)
                            if tool_call and tool_call.function_calls:
                                responses = []
                                for fc in tool_call.function_calls:
                                    args = dict(fc.args or {})
                                    field = str(args.get("field", "")).strip()
                                    value = str(args.get("value", "")).strip()
                                    if fc.name == "record_answer" and field in RECORD_FIELDS and value:
                                        answered.add(field)
                                        stats["saved"] += 1
                                        log.info(f"[Gemini Live] Saved {field} = {value}")
                                        if on_field_saved:
                                            try:
                                                on_field_saved(field, value)
                                            except Exception as cb_err:
                                                log.error(f"[Gemini Live] on_field_saved error: {cb_err}")
                                        status = "saved"
                                    else:
                                        status = "rejected: unknown field or empty value"
                                    responses.append(types.FunctionResponse(
                                        id=fc.id, name=fc.name, response={"result": status},
                                    ))
                                await live.send_tool_response(function_responses=responses)

                                # Ask the next unanswered question, or close the call
                                nxt = next_unanswered_index()
                                if nxt is None and not closing_sent:
                                    closing_sent = True
                                    await send_instruction(live, closing_instruction())
                                    log.info("[Gemini Live] All details collected; closing")
                                elif nxt is not None and nxt != question_asked and not greeting_pending:
                                    question_asked = nxt
                                    await send_instruction(live, question_instruction(nxt))
                                    log.info(f"[Gemini Live] Asking question {nxt + 1}: {REQUIRED_QUESTIONS[nxt]['key']}")

                            sc = message.server_content
                            if sc is None:
                                continue

                            if getattr(sc, "interrupted", False):
                                stats["interrupts"] += 1
                                resampler.reset()
                                log.info("[Gemini Live] Caller barged in")
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

                                # Greeting finished: ask question 1
                                if greeting_pending:
                                    greeting_pending = False
                                    question_asked = 0
                                    await send_instruction(live, question_instruction(0))
                                    log.info("[Gemini Live] Greeting complete; asking question 1")

                                # Closing finished: end the conversation
                                if closing_sent and not answered_all_pending(answered):
                                    if on_call_complete:
                                        on_call_complete()
                                    return

                        if not got_message:
                            log.warning("[Gemini Live] Server closed the receive stream")
                            return

                def answered_all_pending(done: set) -> bool:
                    return len(done) < len(REQUIRED_QUESTIONS)

                send_task = asyncio.create_task(send_audio())
                recv_task = asyncio.create_task(receive_audio())
                try:
                    # Call lasts as long as the caller's audio (or until closing finishes)
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
            f"turns={stats['turns']}, saved={stats['saved']}/{len(REQUIRED_QUESTIONS)}, "
            f"interrupts={stats['interrupts']}, reply_chunks={stats['reply_chunks']}, "
            f"reply_bytes={len(response_audio)}"
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