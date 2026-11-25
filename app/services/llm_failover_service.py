"""
LLM Failover Service
Manages failover from Gemini Live to Groq LLM with automatic recovery.

STRATEGY:
1. Primary:  Gemini Live (continuous speech-to-speech for the whole call)
2. Fallback: Groq LLM (text inference, used when Gemini cannot be reached)
3. Recovery: check Gemini health for new calls

FAILOVER TRIGGERS:
- Gemini Live connection or API error before any audio exchange
- Gemini call exceeding GEMINI_CALL_MAX_SEC (safety limit only)

NOTES:
- The live call is NOT limited to a few seconds. Caller audio is streamed for as
  long as the call lasts. Only GEMINI_CALL_MAX_SEC caps the total duration.
- The GeminiLiveProvider instance is shared across calls, so this service never
  calls create_live_session() for health checks (that would replace the shared session).
- The call language ("en" or "hi") is passed per call and is never stored on the provider.
"""

import os
import asyncio
from typing import Optional, Dict, Any, Callable
from datetime import datetime
from enum import Enum

from ..core.config import log
from ..llm.gemini_live_provider import get_gemini_live_provider
from ..llm.groq_provider import GroqLLMProvider


class LLMMode(Enum):
    """LLM operation modes"""
    GEMINI_LIVE = "gemini_live"        # Primary: speech-to-speech
    GROQ_FALLBACK = "groq_fallback"    # Fallback: text LLM
    UNAVAILABLE = "unavailable"        # Both failed


class LLMFailoverService:
    """Manages LLM failover and recovery"""

    def __init__(self):
        self.gemini_provider = get_gemini_live_provider()
        self.groq_provider = GroqLLMProvider()

        # State per call
        self.call_states: Dict[str, Dict[str, Any]] = {}

        # Failover configuration
        self.gemini_call_max_sec = float(os.getenv("GEMINI_CALL_MAX_SEC", "600"))
        self.groq_timeout_sec = float(os.getenv("GROQ_TIMEOUT_SEC", "5"))
        self.recovery_check_interval_sec = float(os.getenv("GEMINI_RECOVERY_CHECK_SEC", "10"))

        log.info("[LLM-FAILOVER] Service initialized")
        log.info("[LLM-FAILOVER]    ├─ Primary: Gemini Live (speech-to-speech)")
        log.info("[LLM-FAILOVER]    ├─ Fallback: Groq LLM (text inference)")
        log.info(f"[LLM-FAILOVER]    ├─ Gemini max call duration: {self.gemini_call_max_sec}s")
        log.info(f"[LLM-FAILOVER]    └─ Recovery check interval: {self.recovery_check_interval_sec}s")

    async def initialize_call(self, call_id: str) -> bool:
        """Initialize failover state for a call"""
        try:
            self.call_states[call_id] = {
                "mode": LLMMode.GEMINI_LIVE,
                "started_at": datetime.utcnow(),
                "gemini_failed": False,
                "gemini_failure_reason": None,
                "gemini_failure_time": None,
                "fallback_started_at": None,
                "recovery_attempted_at": None,
                "mode_switches": 0,
            }
            log.info(f"[LLM-FAILOVER:{call_id}] Call initialized - starting with Gemini Live")
            return True
        except Exception as e:
            log.error(f"[LLM-FAILOVER:{call_id}] Error initializing: {e}")
            return False

    async def try_gemini_live(
        self,
        call_id: str,
        audio_input_stream,
        on_ulaw_chunk: Optional[Callable[[bytes], None]] = None,
        on_interrupted: Optional[Callable[[], None]] = None,
        on_audio_chunk: Optional[Callable[[bytes], None]] = None,
        on_text_chunk: Optional[Callable[[str], None]] = None,
        on_field_saved: Optional[Callable[[str, str], None]] = None,
        on_call_complete: Optional[Callable[[], None]] = None,
        greeting_text: Optional[str] = None,
        call_language: str = "en",
    ) -> Optional[bytes]:
        """
        Run the Gemini Live conversation for the whole call, in one language.

        Returns the reply audio (24 kHz PCM) or None if Gemini could not be used.
        Caller audio keeps flowing until audio_input_stream ends or GEMINI_CALL_MAX_SEC passes.
        """
        if not self.gemini_provider:
            log.error(f"[LLM-FAILOVER:{call_id}] Gemini provider not available")
            await self._record_gemini_failure(call_id, "provider_not_initialized")
            return None

        log.info(f"[LLM-FAILOVER:{call_id}] Attempting Gemini Live conversation (language: {call_language})...")

        try:
            response_audio = await asyncio.wait_for(
                self.gemini_provider.stream_audio_bidirectional(
                    audio_input_stream=audio_input_stream,
                    on_ulaw_chunk=on_ulaw_chunk,
                    on_interrupted=on_interrupted,
                    on_audio_chunk=on_audio_chunk,
                    on_text_chunk=on_text_chunk,
                    on_field_saved=on_field_saved,
                    on_call_complete=on_call_complete,
                    greeting_text=greeting_text,
                    call_language=call_language,
                ),
                timeout=self.gemini_call_max_sec,
            )
            log.info(f"[LLM-FAILOVER:{call_id}] Gemini Live conversation ended normally")
            return response_audio

        except asyncio.TimeoutError:
            # Reached the safety cap on call length. This is not a Gemini failure.
            log.warning(
                f"[LLM-FAILOVER:{call_id}] Call reached max duration "
                f"({self.gemini_call_max_sec}s); ending Gemini session"
            )
            return None

        except Exception as e:
            log.error(f"[LLM-FAILOVER:{call_id}] Gemini Live error: {e}", exc_info=True)
            await self._record_gemini_failure(call_id, f"error: {str(e)[:50]}")
            return None

    async def fallback_to_groq(
        self,
        call_id: str,
        prompt: str,
        system_prompt: Optional[str] = None,
        language: Optional[str] = None,
    ) -> Optional[str]:
        """Fallback to Groq LLM for text inference. Returns response text or None."""
        try:
            await self._switch_mode(call_id, LLMMode.GROQ_FALLBACK)

            log.info(f"[LLM-FAILOVER:{call_id}] SWITCHING TO GROQ FALLBACK")
            log.info(f"[LLM-FAILOVER:{call_id}]    ├─ Reason: Gemini unavailable")
            log.info(f"[LLM-FAILOVER:{call_id}]    └─ Using Groq LLM for text responses")

            if not self.groq_provider.client:
                if not await self.groq_provider.initialize():
                    log.error(f"[LLM-FAILOVER:{call_id}] Failed to initialize Groq")
                    return None

            response = await asyncio.wait_for(
                self.groq_provider.generate(prompt),
                timeout=self.groq_timeout_sec,
            )

            if response:
                log.info(f"[LLM-FAILOVER:{call_id}] Groq response: {len(response)} chars")
            else:
                log.error(f"[LLM-FAILOVER:{call_id}] Groq returned empty response")
            return response

        except asyncio.TimeoutError:
            log.error(f"[LLM-FAILOVER:{call_id}] Groq timeout ({self.groq_timeout_sec}s)")
            return None
        except Exception as e:
            log.error(f"[LLM-FAILOVER:{call_id}] Groq error: {e}")
            return None

    async def check_gemini_recovery(self, call_id: str) -> bool:
        """
        Check whether Gemini is reachable again while this call is in fallback mode.

        Uses a read-only API call (list models). It does not create a session,
        so it cannot disturb other active calls on the shared provider.
        """
        try:
            state = self.call_states.get(call_id)
            if not state or state["mode"] != LLMMode.GROQ_FALLBACK:
                return False

            last = state.get("recovery_attempted_at")
            if last and (datetime.utcnow() - last).total_seconds() < self.recovery_check_interval_sec:
                return False

            state["recovery_attempted_at"] = datetime.utcnow()

            client = getattr(self.gemini_provider, "client", None)
            if client is None:
                return False

            log.info(f"[LLM-FAILOVER:{call_id}] Checking Gemini recovery...")
            pager = await asyncio.wait_for(client.aio.models.list(config={"page_size": 1}), timeout=2.0)
            # Awaiting the call is enough to prove the API is reachable
            del pager

            log.info(f"[LLM-FAILOVER:{call_id}] Gemini reachable again - switching back to Gemini Live")
            await self._switch_mode(call_id, LLMMode.GEMINI_LIVE)
            state["gemini_failed"] = False
            return True

        except asyncio.TimeoutError:
            log.debug(f"[LLM-FAILOVER:{call_id}] Gemini still not responding")
            return False
        except Exception as e:
            log.debug(f"[LLM-FAILOVER:{call_id}] Gemini recovery check failed: {e}")
            return False

    async def get_current_mode(self, call_id: str) -> LLMMode:
        state = self.call_states.get(call_id)
        return state["mode"] if state else LLMMode.UNAVAILABLE

    async def _record_gemini_failure(self, call_id: str, reason: str) -> None:
        try:
            state = self.call_states.get(call_id)
            if state:
                state["gemini_failed"] = True
                state["gemini_failure_reason"] = reason
                state["gemini_failure_time"] = datetime.utcnow()
                log.error(f"[LLM-FAILOVER:{call_id}] GEMINI FAILURE RECORDED: {reason}")
        except Exception as e:
            log.error(f"[LLM-FAILOVER:{call_id}] Error recording failure: {e}")

    async def _switch_mode(self, call_id: str, new_mode: LLMMode) -> None:
        try:
            state = self.call_states.get(call_id)
            if not state:
                return
            old_mode = state["mode"]
            if old_mode == new_mode:
                return
            state["mode"] = new_mode
            state["mode_switches"] += 1
            log.info(
                f"[LLM-FAILOVER:{call_id}] MODE SWITCH #{state['mode_switches']}: "
                f"{old_mode.value} -> {new_mode.value}"
            )
            if new_mode == LLMMode.GROQ_FALLBACK:
                state["fallback_started_at"] = datetime.utcnow()
        except Exception as e:
            log.error(f"[LLM-FAILOVER:{call_id}] Error switching mode: {e}")

    async def cleanup_call(self, call_id: str) -> Dict[str, Any]:
        """Clean up call state and return final statistics."""
        try:
            state = self.call_states.pop(call_id, None)
            if not state:
                return {}

            duration = (datetime.utcnow() - state["started_at"]).total_seconds()
            used_fallback = state["mode"] == LLMMode.GROQ_FALLBACK or state["gemini_failed"]
            stats = {
                "call_id": call_id,
                "duration_sec": duration,
                "final_mode": state["mode"].value,
                "mode_switches": state["mode_switches"],
                "gemini_failed": state["gemini_failed"],
                "gemini_failure_reason": state["gemini_failure_reason"],
                "used_fallback": used_fallback,
            }
            if state["fallback_started_at"]:
                stats["fallback_duration_sec"] = (
                    datetime.utcnow() - state["fallback_started_at"]
                ).total_seconds()

            log.info(f"[LLM-FAILOVER] CALL CLEANUP: {call_id}")
            log.info(f"[LLM-FAILOVER]    ├─ Duration: {duration:.1f}s")
            log.info(f"[LLM-FAILOVER]    ├─ Final mode: {state['mode'].value}")
            log.info(f"[LLM-FAILOVER]    ├─ Mode switches: {state['mode_switches']}")
            log.info(f"[LLM-FAILOVER]    ├─ Gemini failed: {state['gemini_failed']}")
            log.info(f"[LLM-FAILOVER]    └─ Used fallback: {used_fallback}")
            return stats

        except Exception as e:
            log.error(f"[LLM-FAILOVER] Cleanup error: {e}")
            return {}


_failover_service: Optional[LLMFailoverService] = None


async def init_llm_failover_service() -> LLMFailoverService:
    global _failover_service
    _failover_service = LLMFailoverService()
    return _failover_service


def get_llm_failover_service() -> Optional[LLMFailoverService]:
    return _failover_service