# """
# Gemini Live Provider - continuous speech-to-speech conversation (google-genai SDK)

# Audio contract:
#   Input  : 16 kHz, 16-bit mono PCM. Send continuously at real-time pace.
#   Output : 24 kHz, 16-bit mono PCM from Gemini, converted to 8 kHz G.711 mu-law
#            and passed to on_ulaw_chunk.

# Per-call flow (code-driven):
#   greeting (call language) -> question 1 -> record_answer -> next unanswered
#   question -> ... -> mobile number -> closing -> end

# The language is passed to stream_audio_bidirectional() for each call. Nothing
# about the language is stored on the shared provider instance.
# """

# import os
# import array
# import asyncio
# import audioop
# from typing import Optional, Dict, Any, Callable, AsyncIterator
# from datetime import datetime

# from ..core.config import log
# from .live_prompt import (
#     REQUIRED_QUESTIONS,
#     RECORD_FIELDS,
#     build_live_system_instruction,
#     question_instruction,
#     closing_instruction,
#     greeting_text as build_greeting_text,
#     normalize_call_language,
# )

# INPUT_MIME = "audio/pcm;rate=16000"


# class OutboundResampler:
#     """
#     Converts Gemini's 24 kHz 16-bit PCM into 8 kHz mu-law for RTP.
#     Averages each group of 3 samples (24 kHz -> 8 kHz is exactly 3:1) to reduce aliasing.
#     Create one instance per call.
#     """

#     MIN_SAMPLES = 2400  # 100 ms at 24 kHz

#     def __init__(self):
#         self._pending = array.array("h")

#     def push(self, pcm24k: bytes) -> bytes:
#         usable = pcm24k[: len(pcm24k) // 2 * 2]
#         samples = array.array("h")
#         samples.frombytes(usable)
#         self._pending.extend(samples)
#         if len(self._pending) < self.MIN_SAMPLES:
#             return b""
#         return self._emit(final=False)

#     def flush(self) -> bytes:
#         if not self._pending:
#             return b""
#         return self._emit(final=True)

#     def reset(self) -> None:
#         self._pending = array.array("h")

#     def _emit(self, final: bool) -> bytes:
#         if final and len(self._pending) % 3:
#             self._pending.extend([0] * (3 - len(self._pending) % 3))
#         n = len(self._pending) // 3 * 3
#         if n == 0:
#             return b""
#         block = self._pending[:n]
#         del self._pending[:n]
#         out = array.array("h", [sum(block[i:i + 3]) // 3 for i in range(0, n, 3)])
#         return audioop.lin2ulaw(out.tobytes(), 2)


# def _build_realtime_input_config(types):
#     """Turn off barge-in so the caller's speech cannot cut off a reply."""
#     try:
#         return types.RealtimeInputConfig(
#             activity_handling=types.ActivityHandling.NO_INTERRUPTION,
#         )
#     except AttributeError:
#         log.warning("[Gemini Live] ActivityHandling.NO_INTERRUPTION not available; barge-in stays enabled")
#         return None


# def _build_tools(types):
#     """Declare record_answer so the model can save each answer."""
#     return [types.Tool(function_declarations=[types.FunctionDeclaration(
#         name="record_answer",
#         description="Save one detail the customer just gave. Call once per detail.",
#         parameters=types.Schema(
#             type=types.Type.OBJECT,
#             properties={
#                 "field": types.Schema(
#                     type=types.Type.STRING,
#                     enum=RECORD_FIELDS,
#                     description="Field key from the list in the instructions",
#                 ),
#                 "value": types.Schema(
#                     type=types.Type.STRING,
#                     description="The value as the customer said it",
#                 ),
#             },
#             required=["field", "value"],
#         ),
#     )])]


# class GeminiLiveProvider:
#     """Gemini Live API provider for real-time speech-to-speech conversations."""

#     def __init__(self):
#         self.api_key = os.getenv("GEMINI_API_KEY", "")
#         self.model = os.getenv("GEMINI_LIVE_MODEL", "gemini-2.0-flash-live-001")
#         self.text_model = os.getenv("GEMINI_TEXT_MODEL", "gemini-2.5-flash")
#         # ✅ Changed from "Kore" to "Aoede" for natural female Indian voice
#         self.voice = os.getenv("GEMINI_VOICE", "Aoede")
#         self.temperature = float(os.getenv("LLM_TEMPERATURE", "0.3"))
#         self.max_tokens = int(os.getenv("LLM_MAX_TOKENS", "500"))

#         self.client = None
#         self.session = None
#         self.session_id = None
#         self.audio_config = {"encoding": "LINEAR16", "sample_rate_hertz": 16000}

#     # ------------------------------------------------------------------ #
#     # Setup
#     # ------------------------------------------------------------------ #
#     async def initialize(self) -> bool:
#         if not self.api_key:
#             log.error("[Gemini Live] GEMINI_API_KEY not configured")
#             return False
#         try:
#             from google import genai

#             self.client = genai.Client(
#                 api_key=self.api_key,
#                 http_options={"api_version": "v1beta"},
#             )
#             log.info("[Gemini Live] Client initialized (google-genai SDK)")
#             log.info(f"[Gemini Live]    ├─ Live model: {self.model}")
#             log.info(f"[Gemini Live]    ├─ Voice: {self.voice}")
#             log.info(f"[Gemini Live]    └─ Temperature: {self.temperature}, Max tokens: {self.max_tokens}")
#             return True
#         except ImportError:
#             log.error("[Gemini Live] google-genai not installed. Run: pip install google-genai")
#             return False
#         except Exception as e:
#             log.error(f"[Gemini Live] Initialization failed: {e}", exc_info=True)
#             return False

#     async def create_live_session(self, system_prompt: Optional[str] = None) -> bool:
#         """
#         Create the per-call session record. The WebSocket opens in stream_audio_bidirectional().
#         system_prompt is optional. If omitted, the prompt for the call language is used.
#         """
#         try:
#             if not self.client and not await self.initialize():
#                 return False

#             self.session_id = f"session_{int(datetime.utcnow().timestamp() * 1000)}"
#             self.session = {
#                 "session_id": self.session_id,
#                 "created_at": datetime.utcnow().isoformat(),
#                 "model": self.model,
#                 "voice": self.voice,
#                 "status": "active",
#                 "system_prompt": system_prompt,   # None = use the language-specific prompt
#                 "audio_config": self.audio_config,
#             }
#             log.info(f"[Gemini Live] Session created: {self.session_id}")
#             return True
#         except Exception as e:
#             log.error(f"[Gemini Live] Session creation error: {e}", exc_info=True)
#             return False

#     # ------------------------------------------------------------------ #
#     # Live conversation
#     # ------------------------------------------------------------------ #
#     async def stream_audio_bidirectional(
#         self,
#         audio_input_stream: AsyncIterator[bytes],
#         on_ulaw_chunk: Optional[Callable[[bytes], None]] = None,
#         on_audio_chunk: Optional[Callable[[bytes], None]] = None,
#         on_text_chunk: Optional[Callable[[str], None]] = None,
#         on_interrupted: Optional[Callable[[], None]] = None,
#         on_field_saved: Optional[Callable[[str, str], None]] = None,
#         on_call_complete: Optional[Callable[[], None]] = None,
#         greeting_text: Optional[str] = None,
#         call_language: str = "en",
#     ) -> Optional[bytes]:
#         """
#         Run one live conversation for the whole call, in one language.

#         audio_input_stream: 16 kHz 16-bit mono PCM until the caller hangs up.
#         on_ulaw_chunk:      8 kHz mu-law bytes for RTP (the call's audio output).
#         on_audio_chunk:     raw 24 kHz PCM from Gemini (optional, logging only).
#         on_text_chunk:      text transcript of Gemini's reply.
#         on_interrupted:     only fires if barge-in is enabled (not with NO_INTERRUPTION).
#         on_field_saved:     on_field_saved(field, value) for each record_answer call.
#         on_call_complete:   called once, after the closing message has finished playing.
#         greeting_text:      optional override. If None, the greeting for call_language is used.
#         call_language:      "en" or "hi", chosen by the caller with DTMF.

#         Returns all reply audio as 24 kHz PCM, or None.
#         """
#         from google.genai import types

#         if not self.session or not self.client:
#             log.error("[Gemini Live] Session not active - cannot stream audio")
#             return None

#         lang = normalize_call_language(call_language)
#         lang_name = "English" if lang == "en" else "Hindi"
#         system_instruction = self.session.get("system_prompt") or build_live_system_instruction(lang)
#         greeting = greeting_text or build_greeting_text(lang)

#         model_name = self.model if self.model.startswith("models/") else f"models/{self.model}"

#         config_kwargs = dict(
#             response_modalities=["AUDIO"],
#             system_instruction=system_instruction,
#             generation_config=types.GenerationConfig(
#                 temperature=self.temperature,
#                 max_output_tokens=self.max_tokens,
#             ),
#             speech_config=types.SpeechConfig(
#                 voice_config=types.VoiceConfig(
#                     prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=self.voice)
#                 )
#             ),
#             tools=_build_tools(types),
#         )
#         realtime_cfg = _build_realtime_input_config(types)
#         if realtime_cfg is not None:
#             config_kwargs["realtime_input_config"] = realtime_cfg
#         config = types.LiveConnectConfig(**config_kwargs)

#         stats = {"sent": 0, "reply_chunks": 0, "turns": 0, "interrupts": 0, "saved": 0}
#         response_audio = bytearray()
#         resampler = OutboundResampler()
#         answered: set = set()
#         state = {
#             "greeting_pending": True,   # waiting for the greeting turn to finish
#             "question_asked": -1,       # index of the last question sent
#             "closing_sent": False,
#         }
#         closing_done = asyncio.Event()

#         def emit_ulaw(ulaw: bytes):
#             if ulaw and on_ulaw_chunk:
#                 on_ulaw_chunk(ulaw)

#         def next_unanswered_index() -> Optional[int]:
#             unanswered = []
#             for i, q in enumerate(REQUIRED_QUESTIONS):
#                 if q["key"] not in answered:
#                     unanswered.append(f"{i}:{q['key']}")
#             if unanswered:
#                 log.debug(f"[Gemini Live] Unanswered: {', '.join(unanswered)}")
#                 return int(unanswered[0].split(':')[0])
#             log.info(f"[Gemini Live] ✅ ALL QUESTIONS COMPLETE - Total answered: {len(answered)}/{len(REQUIRED_QUESTIONS)}")
#             log.info(f"[Gemini Live] Answered fields: {sorted(list(answered))}")
#             return None

#         async def send_instruction(live, text: str):
#             await live.send_client_content(
#                 turns=types.Content(role="user", parts=[types.Part(text=text)]),
#                 turn_complete=True,
#             )

#         async def ask_question(live, index: int):
#             state["question_asked"] = index
#             await send_instruction(live, question_instruction(index, lang))
#             log.info(f"[Gemini Live] Asking question {index + 1}: {REQUIRED_QUESTIONS[index]['key']}")

#         async def handle_tool_calls(live, function_calls):
#             responses = []
#             for fc in function_calls:
#                 args = dict(fc.args or {})
#                 field = str(args.get("field", "")).strip()
#                 value = str(args.get("value", "")).strip()
                
#                 # ✅ ENHANCED: Response validation and N/A handling
#                 if fc.name == "record_answer" and field in RECORD_FIELDS and value:
#                     # Check for refusal patterns
#                     refusal_patterns = [
#                         "n/a", "na", "don't know", "dont know", "don't have", "dont have",
#                         "not provided", "prefer not", "won't provide", "don't want to share",
#                         "not interested", "not applicable", "नहीं पता", "नहीं बता सकता",
#                         "नहीं दे सकता", "पता नहीं", "नहीं दूँगा", "नहीं दूंगा"
#                     ]
                    
#                     value_lower = value.lower()
#                     is_refusal = any(pattern in value_lower for pattern in refusal_patterns)
                    
#                     if is_refusal:
#                         value = "N/A"
#                         log.info(f"[Gemini Live] Refusal detected and marked N/A: {field}")
                    
#                     # ✅ ENHANCED: Validate response completeness
#                     # For fields requiring multiple words (name, company, location), check length
#                     if field in ["customer_name", "company_name", "location"]:
#                         word_count = len(value.split())
#                         if word_count == 0 or (word_count == 1 and len(value) < 2):
#                             # Likely incomplete or just "yes/no" - trigger clarification
#                             log.warning(f"[Gemini Live] Response too brief for {field}: {value}")
#                             status = "rejected: response too brief, needs clarification"
#                             responses.append(types.FunctionResponse(
#                                 id=fc.id, name=fc.name, response={"result": status},
#                             ))
#                             continue
                    
#                     answered.add(field)
#                     stats["saved"] += 1
#                     log.info(f"[Gemini Live] ✅ Saved {field} = '{value}' ({len(answered)}/{len(REQUIRED_QUESTIONS)} total)")
#                     if on_field_saved:
#                         try:
#                             on_field_saved(field, value)
#                         except Exception as cb_err:
#                             log.error(f"[Gemini Live] on_field_saved error: {cb_err}")
#                     status = "saved"
#                 else:
#                     status = "rejected: unknown field or empty value"
#                     if not value:
#                         log.info(f"[Gemini Live] Empty response for {field} - requesting clarification")
                
#                 responses.append(types.FunctionResponse(
#                     id=fc.id, name=fc.name, response={"result": status},
#                 ))
#             await live.send_tool_response(function_responses=responses)
#             log.debug(f"[Gemini Live] Tool responses sent for {len(responses)} calls")

#             # ✅ CRITICAL: Move on to next question or closing
#             nxt = next_unanswered_index()
#             if nxt is None:
#                 # All questions answered
#                 log.info(f"[Gemini Live] nxt = None, checking if closing_sent={state['closing_sent']}")
#                 if not state["closing_sent"]:
#                     state["closing_sent"] = True
#                     log.info(f"[Gemini Live] ✅ All {len(answered)} details collected; sending closing instruction")
#                     await send_instruction(live, closing_instruction(lang))
#                     log.info(f"[Gemini Live] Closing instruction sent, waiting for turn_complete to trigger on_call_complete")
#                 else:
#                     log.warning(f"[Gemini Live] nxt=None but closing_sent already True (should not reach here)")
#             elif not state["greeting_pending"] and nxt != state["question_asked"]:
#                 # More questions to ask
#                 log.info(f"[Gemini Live] Moving to next question: {nxt + 1}/{len(REQUIRED_QUESTIONS)}")
#                 await ask_question(live, nxt)
#             else:
#                 log.debug(f"[Gemini Live] Waiting for more input (greeting_pending={state['greeting_pending']}, next_q={nxt}, last_q={state['question_asked']})")

#         try:
#             async with self.client.aio.live.connect(model=model_name, config=config) as live:
#                 log.info(f"[Gemini Live] WebSocket connected: {self.session_id} (language: {lang_name})")

#                 await send_instruction(
#                     live,
#                     f"[SYSTEM INSTRUCTION] The call has connected. Speak only in {lang_name}. "
#                     "Greet the caller once, warmly and naturally, keeping the meaning of this "
#                     f"greeting: {greeting} Then stop and wait for the caller to reply.",
#                 )
#                 log.info("[Gemini Live] Greeting sent")

#                 async def send_audio():
#                     try:
#                         async for chunk in audio_input_stream:
#                             if not chunk:
#                                 continue
#                             await live.send_realtime_input(
#                                 audio=types.Blob(data=chunk, mime_type=INPUT_MIME)
#                             )
#                             stats["sent"] += 1
#                     finally:
#                         log.info(f"[Gemini Live] Caller audio stream ended after {stats['sent']} frames")

#                 async def receive_audio():
#                     while True:
#                         got_message = False
#                         async for message in live.receive():
#                             got_message = True

#                             tool_call = getattr(message, "tool_call", None)
#                             if tool_call and tool_call.function_calls:
#                                 log.debug(f"[Gemini Live] Processing {len(tool_call.function_calls)} tool calls")
#                                 await handle_tool_calls(live, tool_call.function_calls)

#                             sc = message.server_content
#                             if sc is None:
#                                 continue

#                             if getattr(sc, "interrupted", False):
#                                 stats["interrupts"] += 1
#                                 resampler.reset()
#                                 log.info("[Gemini Live] Caller barged in")
#                                 if on_interrupted:
#                                     on_interrupted()

#                             if sc.model_turn and sc.model_turn.parts:
#                                 for part in sc.model_turn.parts:
#                                     if part.text and on_text_chunk:
#                                         on_text_chunk(part.text)
#                                     if part.inline_data and part.inline_data.data:
#                                         data = part.inline_data.data
#                                         stats["reply_chunks"] += 1
#                                         response_audio.extend(data)
#                                         if on_audio_chunk:
#                                             on_audio_chunk(data)
#                                         emit_ulaw(resampler.push(data))

#                             if sc.turn_complete:
#                                 stats["turns"] += 1
#                                 log.info(f"[Gemini Live] Turn {stats['turns']} complete (greeting_pending={state['greeting_pending']}, closing_sent={state['closing_sent']}, answered={len(answered)}/{len(REQUIRED_QUESTIONS)})")

#                                 if state["greeting_pending"]:
#                                     # ✅ STEP 1: Greeting finished → Ask first question
#                                     state["greeting_pending"] = False
#                                     await ask_question(live, 0)
#                                     log.info("[Gemini Live] Greeting complete; waiting for customer response to Q1")
                                    
#                                 elif state["closing_sent"]:
#                                     # ✅ STEP FINAL: Closing finished → End call
#                                     log.info("[Gemini Live] ✅ Closing message finished, triggering on_call_complete")
#                                     if on_call_complete:
#                                         try:
#                                             on_call_complete()
#                                         except Exception as cb_err:
#                                             log.error(f"[Gemini Live] on_call_complete error: {cb_err}")
#                                     closing_done.set()
#                                     return
                                
#                                 else:
#                                     # ✅ STEP NORMAL: Question asked and turn is complete
#                                     # Check if ALL questions have been answered (closing needed)
#                                     nxt = next_unanswered_index()
#                                     if nxt is None and not state["closing_sent"]:
#                                         # All questions answered - send closing
#                                         log.info(f"[Gemini Live] Turn {stats['turns']}: All questions complete, sending closing")
#                                         state["closing_sent"] = True
                                        
#                                         # ✅ CRITICAL FIX #4: Capture final requirements snapshot before closing
#                                         # This ensures CallHandler.on_call_end() can retrieve complete data even if stream ends abruptly
#                                         try:
#                                             # Store the complete collected data in Redis with ready flag
#                                             # This signals CallHandler that the [CALL-DATA] summary is complete
#                                             from ..services.session.redis_session import get_call_session
#                                             session_mgr = get_call_session()
#                                             if session_mgr:
#                                                 # Build snapshot from local collected data
#                                                 snapshot_data = {
#                                                     "requirements_ready": True,
#                                                     "captured_fields": len(answered),
#                                                     "total_fields": len(REQUIRED_QUESTIONS),
#                                                     "timestamp": datetime.utcnow().isoformat()
#                                                 }
#                                                 # Note: Don't update session here as we're in Gemini stream context
#                                                 # The actual requirements are already in CustomerRequirementService via save_field
#                                                 log.info(f"[Gemini Live] ✅ [CALL-DATA] FINAL SUMMARY: {len(answered)}/{len(REQUIRED_QUESTIONS)} fields")
#                                                 log.info(f"[Gemini Live] [CALL-DATA] Collected: {sorted(list(answered))}")
#                                         except Exception as e:
#                                             log.debug(f"[Gemini Live] Error capturing requirements snapshot: {e}")
                                        
#                                         log.info(f"[Gemini Live] ✅ All {len(answered)} details collected; sending closing instruction")
#                                         await send_instruction(live, closing_instruction(lang))
#                                         log.info(f"[Gemini Live] Closing instruction sent, waiting for turn_complete to trigger on_call_complete")
#                                     else:
#                                         log.debug(f"[Gemini Live] Turn {stats['turns']} finished; waiting for customer response (nxt={nxt})")

#                         if not got_message:
#                             log.warning("[Gemini Live] Server closed the receive stream")
#                             return

#                 send_task = asyncio.create_task(send_audio())
#                 recv_task = asyncio.create_task(receive_audio())
#                 end_task = asyncio.create_task(closing_done.wait())
#                 try:
#                     # The call ends when: (1) closing finishes, (2) caller hangs up during questions, or (3) stream drops
#                     # CRITICAL: If closing_sent is True, we MUST wait for end_task (closing completion) even if send_task ends
#                     if state.get("closing_sent"):
#                         # Closing is in progress - prioritize completion
#                         done, pending = await asyncio.wait(
#                             {send_task, recv_task, end_task},
#                             return_when=asyncio.FIRST_COMPLETED
#                         )
#                         # If closing finished, end_task is done, so we're good
#                         # If send_task ended (caller hung up) but closing NOT done, give it a few more seconds
#                         if end_task not in done:
#                             log.warning("[Gemini Live] Caller hung up during closing playback; waiting max 3s for closing to complete")
#                             try:
#                                 await asyncio.wait_for(end_task, timeout=3.0)
#                             except asyncio.TimeoutError:
#                                 log.error("[Gemini Live] Closing did not complete within 3s timeout")
#                     else:
#                         # Normal flow - wait for first completion
#                         await asyncio.wait({send_task, recv_task, end_task},
#                                            return_when=asyncio.FIRST_COMPLETED)
#                 finally:
#                     for t in (send_task, recv_task, end_task):
#                         t.cancel()
#                     await asyncio.gather(send_task, recv_task, end_task, return_exceptions=True)

#         except Exception as e:
#             log.error(
#                 f"[Gemini Live] Conversation failed after {stats['sent']} frames: {e}",
#                 exc_info=True,
#             )

#         emit_ulaw(resampler.flush())

#         log.info(
#             f"[Gemini Live] Conversation ended: language={lang}, sent={stats['sent']} frames, "
#             f"turns={stats['turns']}, saved={stats['saved']}/{len(REQUIRED_QUESTIONS)}, "
#             f"interrupts={stats['interrupts']}, reply_chunks={stats['reply_chunks']}, "
#             f"reply_bytes={len(response_audio)}"
#         )
#         return bytes(response_audio) if response_audio else None

#     # ------------------------------------------------------------------ #
#     # Text helpers (standard generate API, not Live)
#     # ------------------------------------------------------------------ #
#     async def get_text_response(self, prompt: str, system_prompt: Optional[str] = None) -> Optional[str]:
#         from google.genai import types

#         if not self.client:
#             log.error("[Gemini Live] Client not initialized")
#             return None
#         try:
#             response = await self.client.aio.models.generate_content(
#                 model=self.text_model,
#                 contents=prompt,
#                 config=types.GenerateContentConfig(
#                     system_instruction=system_prompt or "You are a professional sales assistant.",
#                     temperature=self.temperature,
#                     max_output_tokens=self.max_tokens,
#                 ),
#             )
#             return response.text
#         except Exception as e:
#             log.error(f"[Gemini Live] Text generation error: {e}", exc_info=True)
#             return None

#     async def stream_response(
#         self,
#         prompt: str,
#         system_prompt: Optional[str] = None,
#         on_chunk: Optional[Callable[[str], None]] = None,
#     ) -> Optional[str]:
#         from google.genai import types

#         if not self.client:
#             log.error("[Gemini Live] Client not initialized")
#             return None
#         try:
#             full_response = ""
#             stream = await self.client.aio.models.generate_content_stream(
#                 model=self.text_model,
#                 contents=prompt,
#                 config=types.GenerateContentConfig(
#                     system_instruction=system_prompt or "You are a professional sales assistant.",
#                     temperature=self.temperature,
#                     max_output_tokens=self.max_tokens,
#                 ),
#             )
#             async for chunk in stream:
#                 if chunk.text:
#                     full_response += chunk.text
#                     if on_chunk:
#                         on_chunk(chunk.text)
#             return full_response or None
#         except Exception as e:
#             log.error(f"[Gemini Live] Streaming error: {e}", exc_info=True)
#             return None

#     # ------------------------------------------------------------------ #
#     # Session lifecycle
#     # ------------------------------------------------------------------ #
#     async def close_session(self) -> bool:
#         try:
#             if self.session:
#                 self.session["status"] = "closed"
#                 self.session["closed_at"] = datetime.utcnow().isoformat()
#                 log.info(f"[Gemini Live] Session closed: {self.session_id}")
#                 self.session = None
#             return True
#         except Exception as e:
#             log.error(f"[Gemini Live] Session close error: {e}")
#             return False

#     def get_session_info(self) -> Optional[Dict[str, Any]]:
#         return self.session.copy() if self.session else None


# _provider: Optional[GeminiLiveProvider] = None


# async def init_gemini_live_provider():
#     global _provider
#     _provider = GeminiLiveProvider()
#     if await _provider.initialize():
#         log.info("[Gemini Live] Provider initialized (google-genai SDK)")
#     return _provider


# def get_gemini_live_provider() -> Optional[GeminiLiveProvider]:
#     return _provider




# """
# Gemini Live Provider - continuous speech-to-speech conversation (google-genai SDK)

# Audio contract:
#   Input  : 16 kHz, 16-bit mono PCM. Send continuously at real-time pace.
#   Output : 24 kHz, 16-bit mono PCM from Gemini, converted to 8 kHz G.711 mu-law
#            and passed to on_ulaw_chunk.

# Per-call flow (one language per call):
#   greeting -> question 1 -> record_answer -> next question -> ... -> mobile number
#   -> closing (sent only after the model finishes its current turn, and only when
#      all 8 fields are saved) -> closing audio generated -> on_call_complete (once)
# """

# import os
# import re
# import array
# import asyncio
# import audioop
# from typing import Optional, Dict, Any, Callable, AsyncIterator
# from datetime import datetime

# from ..core.config import log
# from .live_prompt import (
#     REQUIRED_QUESTIONS,
#     RECORD_FIELDS,
#     build_live_system_instruction,
#     question_instruction,
#     closing_instruction,
#     greeting_text as build_greeting_text,
#     normalize_call_language,
# )

# INPUT_MIME = "audio/pcm;rate=16000"

# # Seconds to wait for the closing audio before ending the call anyway
# CLOSING_TIMEOUT_SEC = float(os.getenv("CLOSING_TIMEOUT_SEC", "30"))

# REFUSAL_PATTERNS = [
#     "n/a", "not provided", "don't know", "dont know", "don't have", "dont have",
#     "prefer not", "won't provide", "don't want to share", "not applicable",
#     "नहीं पता", "नहीं बता सकता", "नहीं दे सकता", "पता नहीं", "नहीं दूँगा", "नहीं दूंगा",
#     "नहीं बताऊंगा", "नहीं बताऊँगा", "नहीं बताना", "नहीं दूंगी", "नहीं दूँगी",
# ]


# class OutboundResampler:
#     """
#     Converts Gemini's 24 kHz 16-bit PCM into 8 kHz mu-law for RTP.
#     Averages each group of 3 samples (24 kHz -> 8 kHz is exactly 3:1). Create one per call.
#     """

#     MIN_SAMPLES = 2400  # 100 ms at 24 kHz

#     def __init__(self):
#         self._pending = array.array("h")

#     def push(self, pcm24k: bytes) -> bytes:
#         usable = pcm24k[: len(pcm24k) // 2 * 2]
#         samples = array.array("h")
#         samples.frombytes(usable)
#         self._pending.extend(samples)
#         if len(self._pending) < self.MIN_SAMPLES:
#             return b""
#         return self._emit(final=False)

#     def flush(self) -> bytes:
#         if not self._pending:
#             return b""
#         return self._emit(final=True)

#     def reset(self) -> None:
#         self._pending = array.array("h")

#     def _emit(self, final: bool) -> bytes:
#         if final and len(self._pending) % 3:
#             self._pending.extend([0] * (3 - len(self._pending) % 3))
#         n = len(self._pending) // 3 * 3
#         if n == 0:
#             return b""
#         block = self._pending[:n]
#         del self._pending[:n]
#         out = array.array("h", [sum(block[i:i + 3]) // 3 for i in range(0, n, 3)])
#         return audioop.lin2ulaw(out.tobytes(), 2)


# def _build_realtime_input_config(types):
#     """Turn off barge-in so the caller's speech cannot cut off a reply."""
#     try:
#         return types.RealtimeInputConfig(
#             activity_handling=types.ActivityHandling.NO_INTERRUPTION,
#         )
#     except AttributeError:
#         log.warning("[Gemini Live] ActivityHandling.NO_INTERRUPTION not available; barge-in stays enabled")
#         return None


# def _build_tools(types):
#     """Declare record_answer so the model can save each answer."""
#     return [types.Tool(function_declarations=[types.FunctionDeclaration(
#         name="record_answer",
#         description="Save one detail the customer just gave. Call once per detail.",
#         parameters=types.Schema(
#             type=types.Type.OBJECT,
#             properties={
#                 "field": types.Schema(
#                     type=types.Type.STRING,
#                     enum=RECORD_FIELDS,
#                     description="Field key from the list in the instructions",
#                 ),
#                 "value": types.Schema(
#                     type=types.Type.STRING,
#                     description="The value as the customer said it",
#                 ),
#             },
#             required=["field", "value"],
#         ),
#     )])]


# class GeminiLiveProvider:
#     """Gemini Live API provider for real-time speech-to-speech conversations."""

#     def __init__(self):
#         self.api_key = os.getenv("GEMINI_API_KEY", "")
#         self.model = os.getenv("GEMINI_LIVE_MODEL", "gemini-2.0-flash-live-001")
#         self.text_model = os.getenv("GEMINI_TEXT_MODEL", "gemini-2.5-flash")
#         self.voice = os.getenv("GEMINI_VOICE", "Aoede")
#         self.temperature = float(os.getenv("LLM_TEMPERATURE", "0.3"))
#         self.max_tokens = int(os.getenv("LLM_MAX_TOKENS", "500"))

#         self.client = None
#         self.session = None
#         self.session_id = None
#         self.audio_config = {"encoding": "LINEAR16", "sample_rate_hertz": 16000}

#     # ------------------------------------------------------------------ #
#     # Setup
#     # ------------------------------------------------------------------ #
#     async def initialize(self) -> bool:
#         if not self.api_key:
#             log.error("[Gemini Live] GEMINI_API_KEY not configured")
#             return False
#         try:
#             from google import genai

#             self.client = genai.Client(
#                 api_key=self.api_key,
#                 http_options={"api_version": "v1beta"},
#             )
#             log.info("[Gemini Live] Client initialized (google-genai SDK)")
#             log.info(f"[Gemini Live]    ├─ Live model: {self.model}")
#             log.info(f"[Gemini Live]    ├─ Voice: {self.voice}")
#             log.info(f"[Gemini Live]    └─ Temperature: {self.temperature}, Max tokens: {self.max_tokens}")
#             return True
#         except ImportError:
#             log.error("[Gemini Live] google-genai not installed. Run: pip install google-genai")
#             return False
#         except Exception as e:
#             log.error(f"[Gemini Live] Initialization failed: {e}", exc_info=True)
#             return False

#     async def create_live_session(self, system_prompt: Optional[str] = None) -> bool:
#         """Create the per-call session record. The WebSocket opens in stream_audio_bidirectional()."""
#         try:
#             if not self.client and not await self.initialize():
#                 return False

#             self.session_id = f"session_{int(datetime.utcnow().timestamp() * 1000)}"
#             self.session = {
#                 "session_id": self.session_id,
#                 "created_at": datetime.utcnow().isoformat(),
#                 "model": self.model,
#                 "voice": self.voice,
#                 "status": "active",
#                 "system_prompt": system_prompt,   # None = language-specific prompt
#                 "audio_config": self.audio_config,
#             }
#             log.info(f"[Gemini Live] Session created: {self.session_id}")
#             return True
#         except Exception as e:
#             log.error(f"[Gemini Live] Session creation error: {e}", exc_info=True)
#             return False

#     # ------------------------------------------------------------------ #
#     # Live conversation
#     # ------------------------------------------------------------------ #
#     async def stream_audio_bidirectional(
#         self,
#         audio_input_stream: AsyncIterator[bytes],
#         on_ulaw_chunk: Optional[Callable[[bytes], None]] = None,
#         on_audio_chunk: Optional[Callable[[bytes], None]] = None,
#         on_text_chunk: Optional[Callable[[str], None]] = None,
#         on_interrupted: Optional[Callable[[], None]] = None,
#         on_field_saved: Optional[Callable[[str, str], None]] = None,
#         on_call_complete: Optional[Callable[[], None]] = None,
#         greeting_text: Optional[str] = None,
#         call_language: str = "en",
#     ) -> Optional[bytes]:
#         """
#         Run one live conversation for the whole call, in one language.

#         on_call_complete is called once, after the closing message's audio has been
#         generated. It is never called unless all 8 fields were saved.
#         """
#         from google.genai import types

#         if not self.session or not self.client:
#             log.error("[Gemini Live] Session not active - cannot stream audio")
#             return None

#         lang = normalize_call_language(call_language)
#         lang_name = "English" if lang == "en" else "Hindi"
#         system_instruction = self.session.get("system_prompt") or build_live_system_instruction(lang)
#         greeting = greeting_text or build_greeting_text(lang)
#         total = len(REQUIRED_QUESTIONS)

#         model_name = self.model if self.model.startswith("models/") else f"models/{self.model}"

#         config_kwargs = dict(
#             response_modalities=["AUDIO"],
#             system_instruction=system_instruction,
#             generation_config=types.GenerationConfig(
#                 temperature=self.temperature,
#                 max_output_tokens=self.max_tokens,
#             ),
#             speech_config=types.SpeechConfig(
#                 voice_config=types.VoiceConfig(
#                     prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=self.voice)
#                 )
#             ),
#             tools=_build_tools(types),
#         )
#         realtime_cfg = _build_realtime_input_config(types)
#         if realtime_cfg is not None:
#             config_kwargs["realtime_input_config"] = realtime_cfg
#         config = types.LiveConnectConfig(**config_kwargs)

#         stats = {"sent": 0, "reply_chunks": 0, "turns": 0, "interrupts": 0, "saved": 0}
#         response_audio = bytearray()
#         resampler = OutboundResampler()
#         answered: set = set()
#         state = {
#             "greeting_pending": True,   # greeting turn not finished yet
#             "question_asked": -1,       # index of the last question sent
#             "turn_active": False,       # model is in the middle of a turn
#             "pending_closing": False,   # closing wanted, waiting for the current turn to end
#             "closing_sent": False,
#             "closing_audio": 0,         # bytes of reply audio produced after closing was sent
#             "closing_done": False,
#         }
#         call_end = asyncio.Event()

#         def emit_ulaw(ulaw: bytes):
#             if ulaw and on_ulaw_chunk:
#                 on_ulaw_chunk(ulaw)

#         def next_unanswered_index() -> Optional[int]:
#             for i, q in enumerate(REQUIRED_QUESTIONS):
#                 if q["key"] not in answered:
#                     return i
#             return None

#         async def send_instruction(live, text: str):
#             await live.send_client_content(
#                 turns=types.Content(role="user", parts=[types.Part(text=text)]),
#                 turn_complete=True,
#             )

#         async def ask_question(live, index: int):
#             state["question_asked"] = index
#             await send_instruction(live, question_instruction(index, lang))
#             log.info(f"[Gemini Live] Asking question {index + 1}/{total}: {REQUIRED_QUESTIONS[index]['key']}")

#         async def send_closing(live):
#             if state["closing_sent"]:
#                 return
#             state["closing_sent"] = True
#             state["pending_closing"] = False
#             await send_instruction(live, closing_instruction(lang))
#             log.info(f"[Gemini Live] All {len(answered)}/{total} fields saved; closing sent in {lang_name}")

#         def finish_call(reason: str):
#             """Mark the closing as finished and end the call once (idempotent)."""
#             if state["closing_done"]:
#                 return
#             state["closing_done"] = True
#             log.info(f"[Gemini Live] Call finishing: {reason}")
#             if on_call_complete:
#                 try:
#                     on_call_complete()
#                 except Exception as cb_err:
#                     log.error(f"[Gemini Live] on_call_complete error: {cb_err}")
#             call_end.set()

#         async def handle_tool_calls(live, function_calls):
#             responses = []
#             for fc in function_calls:
#                 args = dict(fc.args or {})
#                 field = str(args.get("field", "")).strip()
#                 value = str(args.get("value", "")).strip()

#                 if fc.name == "record_answer" and field in RECORD_FIELDS and value:
#                     is_refusal = any(p in value.lower() for p in REFUSAL_PATTERNS)
#                     if is_refusal:
#                         value = "N/A"
#                         log.info(f"[Gemini Live] Refusal recorded as N/A: {field}")

#                     if not is_refusal and field in ("customer_name", "company_name", "location") and len(value) < 2:
#                         responses.append(types.FunctionResponse(
#                             id=fc.id, name=fc.name,
#                             response={"result": "rejected: response too brief, ask again"},
#                         ))
#                         continue

#                     if not is_refusal and field == "mobile_number":
#                         if len(re.sub(r"\D", "", value)) < 10:
#                             log.warning(f"[Gemini Live] Mobile number incomplete: '{value}'")
#                             responses.append(types.FunctionResponse(
#                                 id=fc.id, name=fc.name,
#                                 response={"result": "rejected: mobile number incomplete, ask again"},
#                             ))
#                             continue

#                     answered.add(field)
#                     stats["saved"] += 1
#                     log.info(f"[Gemini Live] Saved {field} = '{value}' ({len(answered)}/{total})")
#                     if on_field_saved:
#                         try:
#                             on_field_saved(field, value)
#                         except Exception as cb_err:
#                             log.error(f"[Gemini Live] on_field_saved error: {cb_err}")
#                     status = "saved"
#                 else:
#                     status = "rejected: unknown field or empty value"

#                 responses.append(types.FunctionResponse(
#                     id=fc.id, name=fc.name, response={"result": status},
#                 ))
#             await live.send_tool_response(function_responses=responses)

#             nxt = next_unanswered_index()
#             if nxt is None:
#                 # All 8 saved. Send the closing now if the model is idle,
#                 # otherwise after its current turn finishes (see turn_complete handling).
#                 if state["turn_active"]:
#                     state["pending_closing"] = True
#                 else:
#                     await send_closing(live)
#             elif not state["greeting_pending"] and nxt != state["question_asked"]:
#                 await ask_question(live, nxt)

#         try:
#             async with self.client.aio.live.connect(model=model_name, config=config) as live:
#                 log.info(f"[Gemini Live] WebSocket connected: {self.session_id} (language: {lang_name})")

#                 await send_instruction(
#                     live,
#                     f"[SYSTEM INSTRUCTION] The call has connected. Speak only in {lang_name}. "
#                     "Greet the caller once, warmly and naturally, keeping the meaning of this "
#                     f"greeting: {greeting} Then stop and wait for the caller to reply.",
#                 )
#                 log.info("[Gemini Live] Greeting sent")

#                 async def send_audio():
#                     try:
#                         async for chunk in audio_input_stream:
#                             if not chunk:
#                                 continue
#                             await live.send_realtime_input(
#                                 audio=types.Blob(data=chunk, mime_type=INPUT_MIME)
#                             )
#                             stats["sent"] += 1
#                     finally:
#                         log.info(f"[Gemini Live] Caller audio stream ended after {stats['sent']} frames")

#                 async def receive_audio():
#                     while True:
#                         got_message = False
#                         async for message in live.receive():
#                             got_message = True

#                             tool_call = getattr(message, "tool_call", None)
#                             if tool_call and tool_call.function_calls:
#                                 await handle_tool_calls(live, tool_call.function_calls)

#                             sc = message.server_content
#                             if sc is None:
#                                 continue

#                             if sc.model_turn and sc.model_turn.parts:
#                                 state["turn_active"] = True

#                             if getattr(sc, "interrupted", False):
#                                 stats["interrupts"] += 1
#                                 resampler.reset()
#                                 log.info("[Gemini Live] Caller barged in")
#                                 if on_interrupted:
#                                     on_interrupted()

#                             if sc.model_turn and sc.model_turn.parts:
#                                 for part in sc.model_turn.parts:
#                                     if part.text and on_text_chunk:
#                                         on_text_chunk(part.text)
#                                     if part.inline_data and part.inline_data.data:
#                                         data = part.inline_data.data
#                                         stats["reply_chunks"] += 1
#                                         response_audio.extend(data)
#                                         if state["closing_sent"]:
#                                             state["closing_audio"] += len(data)
#                                         if on_audio_chunk:
#                                             on_audio_chunk(data)
#                                         emit_ulaw(resampler.push(data))

#                             if sc.turn_complete:
#                                 stats["turns"] += 1
#                                 state["turn_active"] = False
#                                 log.debug(f"[Gemini Live] Turn {stats['turns']} complete")

#                                 if state["greeting_pending"]:
#                                     state["greeting_pending"] = False
#                                     await ask_question(live, 0)

#                                 elif state["pending_closing"]:
#                                     await send_closing(live)

#                                 elif (state["closing_sent"] and not state["closing_done"]
#                                       and state["closing_audio"] > 0):
#                                     # The closing turn has produced audio and is complete
#                                     log.info(f"[Gemini Live] Closing message finished in {lang_name}")
#                                     finish_call("closing complete")
#                                     return

#                         if not got_message:
#                             log.warning("[Gemini Live] Server closed the receive stream")
#                             return

#                 async def closing_watchdog():
#                     """If the closing never produces audio, end the call after CLOSING_TIMEOUT_SEC."""
#                     while not state["closing_sent"]:
#                         await asyncio.sleep(0.5)
#                     await asyncio.sleep(CLOSING_TIMEOUT_SEC)
#                     if not state["closing_done"]:
#                         log.warning(f"[Gemini Live] Closing did not finish within {CLOSING_TIMEOUT_SEC}s")
#                         finish_call("closing timeout")

#                 send_task = asyncio.create_task(send_audio())
#                 recv_task = asyncio.create_task(receive_audio())
#                 watchdog_task = asyncio.create_task(closing_watchdog())
#                 end_task = asyncio.create_task(call_end.wait())
#                 try:
#                     # Ends when the closing finishes, the caller hangs up, or the stream drops
#                     await asyncio.wait({send_task, recv_task, end_task},
#                                        return_when=asyncio.FIRST_COMPLETED)
#                 finally:
#                     for t in (send_task, recv_task, watchdog_task, end_task):
#                         t.cancel()
#                     await asyncio.gather(send_task, recv_task, watchdog_task, end_task,
#                                          return_exceptions=True)

#         except Exception as e:
#             log.error(
#                 f"[Gemini Live] Conversation failed after {stats['sent']} frames: {e}",
#                 exc_info=True,
#             )

#         emit_ulaw(resampler.flush())

#         log.info(
#             f"[Gemini Live] Conversation ended: language={lang}, sent={stats['sent']} frames, "
#             f"turns={stats['turns']}, saved={stats['saved']}/{total}, "
#             f"closing_done={state['closing_done']}, closing_audio={state['closing_audio']}, "
#             f"interrupts={stats['interrupts']}, reply_bytes={len(response_audio)}"
#         )
#         return bytes(response_audio) if response_audio else None

#     # ------------------------------------------------------------------ #
#     # Text helpers (standard generate API, not Live)
#     # ------------------------------------------------------------------ #
#     async def get_text_response(self, prompt: str, system_prompt: Optional[str] = None) -> Optional[str]:
#         from google.genai import types

#         if not self.client:
#             log.error("[Gemini Live] Client not initialized")
#             return None
#         try:
#             response = await self.client.aio.models.generate_content(
#                 model=self.text_model,
#                 contents=prompt,
#                 config=types.GenerateContentConfig(
#                     system_instruction=system_prompt or "You are a professional sales assistant.",
#                     temperature=self.temperature,
#                     max_output_tokens=self.max_tokens,
#                 ),
#             )
#             return response.text
#         except Exception as e:
#             log.error(f"[Gemini Live] Text generation error: {e}", exc_info=True)
#             return None

#     async def stream_response(
#         self,
#         prompt: str,
#         system_prompt: Optional[str] = None,
#         on_chunk: Optional[Callable[[str], None]] = None,
#     ) -> Optional[str]:
#         from google.genai import types

#         if not self.client:
#             log.error("[Gemini Live] Client not initialized")
#             return None
#         try:
#             full_response = ""
#             stream = await self.client.aio.models.generate_content_stream(
#                 model=self.text_model,
#                 contents=prompt,
#                 config=types.GenerateContentConfig(
#                     system_instruction=system_prompt or "You are a professional sales assistant.",
#                     temperature=self.temperature,
#                     max_output_tokens=self.max_tokens,
#                 ),
#             )
#             async for chunk in stream:
#                 if chunk.text:
#                     full_response += chunk.text
#                     if on_chunk:
#                         on_chunk(chunk.text)
#             return full_response or None
#         except Exception as e:
#             log.error(f"[Gemini Live] Streaming error: {e}", exc_info=True)
#             return None

#     # ------------------------------------------------------------------ #
#     # Session lifecycle
#     # ------------------------------------------------------------------ #
#     async def close_session(self) -> bool:
#         try:
#             if self.session:
#                 self.session["status"] = "closed"
#                 self.session["closed_at"] = datetime.utcnow().isoformat()
#                 log.info(f"[Gemini Live] Session closed: {self.session_id}")
#                 self.session = None
#             return True
#         except Exception as e:
#             log.error(f"[Gemini Live] Session close error: {e}")
#             return False

#     def get_session_info(self) -> Optional[Dict[str, Any]]:
#         return self.session.copy() if self.session else None


# _provider: Optional[GeminiLiveProvider] = None


# async def init_gemini_live_provider():
#     global _provider
#     _provider = GeminiLiveProvider()
#     if await _provider.initialize():
#         log.info("[Gemini Live] Provider initialized (google-genai SDK)")
#     return _provider


# def get_gemini_live_provider() -> Optional[GeminiLiveProvider]:
#     return _provider






"""
Gemini Live Provider - continuous speech-to-speech conversation (google-genai SDK)

Audio contract:
  Input  : 16 kHz, 16-bit mono PCM. Send continuously at real-time pace.
  Output : 24 kHz, 16-bit mono PCM from Gemini, converted to 8 kHz G.711 mu-law
           and passed to on_ulaw_chunk.

Per-call flow:
  greeting -> question -> record_answer -> next question -> ... -> mobile number
  -> closing (after all 8 fields are saved) -> on_call_complete

Language:
  The call starts in the language passed as call_language. The model can call
  set_call_language when the caller asks to switch. From then on, every instruction
  (questions, confirmations, closing) uses the new language.
"""

import os
import re
import array
import asyncio
import audioop
from typing import Optional, Dict, Any, Callable, AsyncIterator
from datetime import datetime

from ..core.config import log
from .live_prompt import (
    REQUIRED_QUESTIONS,
    RECORD_FIELDS,
    SUPPORTED_CALL_LANGS,
    build_live_system_instruction,
    question_instruction,
    closing_instruction,
    greeting_text as build_greeting_text,
    normalize_call_language,
    language_name,
)

INPUT_MIME = "audio/pcm;rate=16000"

# Seconds to wait for the closing audio before ending the call anyway
CLOSING_TIMEOUT_SEC = float(os.getenv("CLOSING_TIMEOUT_SEC", "30"))

REFUSAL_PATTERNS = [
    "n/a", "not provided", "don't know", "dont know", "don't have", "dont have",
    "prefer not", "won't provide", "don't want to share", "not applicable",
    "नहीं पता", "नहीं बता सकता", "नहीं दे सकता", "पता नहीं", "नहीं दूँगा", "नहीं दूंगा",
    "नहीं बताऊंगा", "नहीं बताऊँगा", "नहीं बताना", "नहीं दूंगी", "नहीं दूँगी",
]


class OutboundResampler:
    """
    Converts Gemini's 24 kHz 16-bit PCM into 8 kHz mu-law for RTP.
    Averages each group of 3 samples (24 kHz -> 8 kHz is exactly 3:1). Create one per call.
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
    """Tools the model can call: save an answer, or switch the call language."""
    return [types.Tool(function_declarations=[
        types.FunctionDeclaration(
            name="record_answer",
            description=(
                "Save one detail the customer clearly answered in reply to the current question. "
                "Do not use speech from other people in the background."
            ),
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
        ),
        types.FunctionDeclaration(
            name="set_call_language",
            description=(
                "Switch the language of the whole call. Call this only when the customer clearly asks "
                "to talk in English or Hindi. Use 'en' for English or 'hi' for Hindi."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "language": types.Schema(
                        type=types.Type.STRING,
                        enum=sorted(SUPPORTED_CALL_LANGS),
                        description="'en' for English, 'hi' for Hindi",
                    ),
                },
                required=["language"],
            ),
        ),
    ])]


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
                "system_prompt": system_prompt,   # None = language-specific prompt
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
        on_language_changed: Optional[Callable[[str], None]] = None,
        greeting_text: Optional[str] = None,
        call_language: str = "en",
    ) -> Optional[bytes]:
        """
        Run one live conversation for the whole call.

        on_language_changed(lang) is called when the caller switches language ("en" or "hi").
        on_call_complete is called once, after the closing audio has been generated.
        """
        from google.genai import types

        if not self.session or not self.client:
            log.error("[Gemini Live] Session not active - cannot stream audio")
            return None

        start_lang = normalize_call_language(call_language)
        system_instruction = self.session.get("system_prompt") or build_live_system_instruction(start_lang)
        greeting = greeting_text or build_greeting_text(start_lang)
        total = len(REQUIRED_QUESTIONS)

        model_name = self.model if self.model.startswith("models/") else f"models/{self.model}"

        config_kwargs = dict(
            response_modalities=["AUDIO"],
            system_instruction=system_instruction,
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

        stats = {"sent": 0, "reply_chunks": 0, "turns": 0, "interrupts": 0, "saved": 0, "lang_changes": 0}
        response_audio = bytearray()
        resampler = OutboundResampler()
        answered: set = set()
        state = {
            "lang": start_lang,           # current call language (can change mid-call)
            "greeting_pending": True,
            "question_asked": -1,
            "turn_active": False,
            "pending_closing": False,
            "closing_sent": False,
            "closing_audio": 0,
            "closing_attempts": 0,
            "closing_done": False,
        }
        call_end = asyncio.Event()

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

        async def ask_question(live, index: int):
            state["question_asked"] = index
            await send_instruction(live, question_instruction(index, state["lang"]))
            log.info(f"[Gemini Live] Asking question {index + 1}/{total} "
                     f"({language_name(state['lang'])}): {REQUIRED_QUESTIONS[index]['key']}")

        async def send_closing(live):
            if state["closing_attempts"] >= 2:
                return
            state["closing_attempts"] += 1
            state["closing_sent"] = True
            state["pending_closing"] = False
            state["closing_audio"] = 0
            await send_instruction(live, closing_instruction(state["lang"]))
            log.info(f"[Gemini Live] Closing sent in {language_name(state['lang'])} "
                     f"(attempt {state['closing_attempts']})")

        def finish_call(reason: str):
            """Mark the call as finished and notify once (idempotent)."""
            if state["closing_done"]:
                return
            state["closing_done"] = True
            log.info(f"[Gemini Live] Call finishing: {reason}")
            if on_call_complete:
                try:
                    on_call_complete()
                except Exception as cb_err:
                    log.error(f"[Gemini Live] on_call_complete error: {cb_err}")
            call_end.set()

        async def handle_language_change(live, new_lang: str):
            """Switch the whole call to new_lang. The change is not announced to the caller."""
            state["lang"] = new_lang
            stats["lang_changes"] += 1
            log.info(f"[Gemini Live] Language changed to {language_name(new_lang)} by caller")
            if on_language_changed:
                try:
                    on_language_changed(new_lang)
                except Exception as cb_err:
                    log.error(f"[Gemini Live] on_language_changed error: {cb_err}")

            # Closing already started in the old language: say it again in the new one
            if state["closing_sent"] and not state["closing_done"]:
                state["closing_audio"] = 0
                await send_instruction(live, closing_instruction(new_lang))
                return

            # Still in the greeting: the first question will use the new language
            if state["greeting_pending"]:
                return

            nxt = next_unanswered_index()
            if nxt is None:
                state["pending_closing"] = True
                if not state["turn_active"]:
                    await send_closing(live)
            else:
                # Re-ask the current question in the new language
                await ask_question(live, nxt)

        async def handle_tool_calls(live, function_calls):
            responses = []
            new_lang = None

            for fc in function_calls:
                args = dict(fc.args or {})

                if fc.name == "set_call_language":
                    requested = str(args.get("language", "")).strip().lower()
                    if requested in SUPPORTED_CALL_LANGS and requested != state["lang"]:
                        new_lang = requested
                        status = "language changed"
                    else:
                        status = "language unchanged"
                    responses.append(types.FunctionResponse(
                        id=fc.id, name=fc.name, response={"result": status},
                    ))
                    continue

                field = str(args.get("field", "")).strip()
                value = str(args.get("value", "")).strip()

                if fc.name == "record_answer" and field in RECORD_FIELDS and value:
                    is_refusal = any(p in value.lower() for p in REFUSAL_PATTERNS)
                    if is_refusal:
                        value = "N/A"
                        log.info(f"[Gemini Live] Refusal recorded as N/A: {field}")

                    if not is_refusal and field in ("customer_name", "company_name", "location") and len(value) < 2:
                        responses.append(types.FunctionResponse(
                            id=fc.id, name=fc.name,
                            response={"result": "rejected: response too brief, ask again"},
                        ))
                        continue

                    if not is_refusal and field == "mobile_number":
                        if len(re.sub(r"\D", "", value)) < 10:
                            log.warning(f"[Gemini Live] Mobile number incomplete: '{value}'")
                            responses.append(types.FunctionResponse(
                                id=fc.id, name=fc.name,
                                response={"result": "rejected: mobile number incomplete, ask again"},
                            ))
                            continue

                    answered.add(field)
                    stats["saved"] += 1
                    log.info(f"[Gemini Live] Saved {field} = '{value}' ({len(answered)}/{total})")
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

            if new_lang:
                await handle_language_change(live, new_lang)
                return

            nxt = next_unanswered_index()
            if nxt is None:
                state["pending_closing"] = True
                if not state["turn_active"]:
                    await send_closing(live)
            elif not state["greeting_pending"] and nxt != state["question_asked"]:
                await ask_question(live, nxt)

        try:
            async with self.client.aio.live.connect(model=model_name, config=config) as live:
                log.info(f"[Gemini Live] WebSocket connected: {self.session_id} "
                         f"(language: {language_name(start_lang)})")

                await send_instruction(
                    live,
                    f"[SYSTEM INSTRUCTION] The call has connected. Speak only in {language_name(start_lang)}. "
                    "Greet the caller once, warmly and naturally, keeping the meaning of this "
                    f"greeting: {greeting} Then stop and wait for the caller to reply.",
                )
                log.info("[Gemini Live] Greeting sent")

                async def send_audio():
                    try:
                        async for chunk in audio_input_stream:
                            if not chunk:
                                continue
                            if state["closing_sent"]:
                                # Call is ending: background speech must not interrupt the closing
                                continue
                            await live.send_realtime_input(
                                audio=types.Blob(data=chunk, mime_type=INPUT_MIME)
                            )
                            stats["sent"] += 1
                    finally:
                        log.info(f"[Gemini Live] Caller audio stream ended after {stats['sent']} frames")

                async def receive_audio():
                    while True:
                        got_message = False
                        async for message in live.receive():
                            got_message = True

                            tool_call = getattr(message, "tool_call", None)
                            if tool_call and tool_call.function_calls:
                                await handle_tool_calls(live, tool_call.function_calls)

                            sc = message.server_content
                            if sc is None:
                                continue

                            if sc.model_turn and sc.model_turn.parts:
                                state["turn_active"] = True

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
                                        if state["closing_sent"]:
                                            state["closing_audio"] += len(data)
                                        if on_audio_chunk:
                                            on_audio_chunk(data)
                                        emit_ulaw(resampler.push(data))

                            if sc.turn_complete:
                                stats["turns"] += 1
                                state["turn_active"] = False

                                if state["greeting_pending"]:
                                    state["greeting_pending"] = False
                                    await ask_question(live, 0)

                                elif state["pending_closing"]:
                                    await send_closing(live)

                                elif state["closing_sent"] and not state["closing_done"]:
                                    if state["closing_audio"] > 0:
                                        log.info(f"[Gemini Live] Closing audio complete in "
                                                 f"{language_name(state['lang'])}")
                                        finish_call("closing complete")
                                        return
                                    if state["closing_attempts"] < 2:
                                        log.warning("[Gemini Live] Closing turn ended with no audio; retrying once")
                                        await send_closing(live)
                                    else:
                                        log.warning("[Gemini Live] Closing produced no audio after retry")
                                        finish_call("closing produced no audio")
                                        return

                        if not got_message:
                            log.warning("[Gemini Live] Server closed the receive stream")
                            return

                async def closing_watchdog():
                    """Last-resort safety net: end the call if the closing never produces audio."""
                    while not state["closing_sent"]:
                        await asyncio.sleep(0.5)
                    await asyncio.sleep(CLOSING_TIMEOUT_SEC)
                    if not state["closing_done"]:
                        log.warning(f"[Gemini Live] Closing did not finish within {CLOSING_TIMEOUT_SEC}s")
                        finish_call("closing timeout")

                send_task = asyncio.create_task(send_audio())
                recv_task = asyncio.create_task(receive_audio())
                watchdog_task = asyncio.create_task(closing_watchdog())
                end_task = asyncio.create_task(call_end.wait())
                try:
                    # Ends when the closing finishes, the caller hangs up, or the stream drops
                    await asyncio.wait({send_task, recv_task, end_task},
                                       return_when=asyncio.FIRST_COMPLETED)
                finally:
                    for t in (send_task, recv_task, watchdog_task, end_task):
                        t.cancel()
                    await asyncio.gather(send_task, recv_task, watchdog_task, end_task,
                                         return_exceptions=True)

        except Exception as e:
            log.error(
                f"[Gemini Live] Conversation failed after {stats['sent']} frames: {e}",
                exc_info=True,
            )

        emit_ulaw(resampler.flush())

        log.info(
            f"[Gemini Live] Conversation ended: final_language={state['lang']}, "
            f"sent={stats['sent']} frames, turns={stats['turns']}, "
            f"saved={stats['saved']}/{total}, lang_changes={stats['lang_changes']}, "
            f"closing_done={state['closing_done']}, closing_audio={state['closing_audio']}, "
            f"interrupts={stats['interrupts']}, reply_bytes={len(response_audio)}"
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