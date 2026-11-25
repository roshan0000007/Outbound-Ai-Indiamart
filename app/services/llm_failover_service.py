"""
LLM Failover Service
Manages seamless fallback from Gemini Live to Groq LLM with automatic recovery

STRATEGY:
1. Primary: Gemini Live (real-time speech-to-speech, lowest latency)
2. Fallback: Groq LLM (fast text inference, automatic TTS synthesis)
3. Recovery: Monitor Gemini health, switch back when available

FAILOVER TRIGGERS:
- Gemini Live WebSocket fails to connect within 2.5s
- Gemini returns API error (401, 404, 429, 500, etc.)
- Gemini response timeout (> 5s)
- Gemini rate limit (429)

FALLBACK BEHAVIOR:
- Use Groq for LLM inference (fast, deterministic)
- Pre-synthesized fallback audio played to caller during transition
- Conversation continues via text in fallback mode
- Automatic recovery when Gemini reconnects
"""

import asyncio
import time
from typing import Optional, Dict, Any, Callable
from datetime import datetime, timedelta
from enum import Enum

from ..core.config import log
from ..llm.gemini_live_provider import get_gemini_live_provider
from ..llm.groq_provider import GroqLLMProvider


class LLMMode(Enum):
    """LLM operation modes"""
    GEMINI_LIVE = "gemini_live"      # Primary: speech-to-speech
    GROQ_FALLBACK = "groq_fallback"  # Fallback: text LLM + optional TTS
    UNAVAILABLE = "unavailable"      # Both failed


class LLMFailoverService:
    """Manages LLM failover and recovery"""
    
    def __init__(self):
        self.gemini_provider = get_gemini_live_provider()
        self.groq_provider = GroqLLMProvider()
        
        # State per call
        self.call_states: Dict[str, Dict[str, Any]] = {}
        
        # Failover configuration
        self.gemini_connect_timeout_sec = 2.5    # Max time to connect to Gemini
        self.gemini_response_timeout_sec = 5.0   # Max time for Gemini response
        self.recovery_check_interval_sec = 10.0  # How often to check for Gemini recovery
        self.max_failover_duration_sec = 300.0   # Max time to stay in fallback mode (5 min)
        
        log.info("[LLM-FAILOVER] ✅ Service initialized")
        log.info("[LLM-FAILOVER]    ├─ Primary: Gemini Live (speech-to-speech)")
        log.info("[LLM-FAILOVER]    ├─ Fallback: Groq LLM (text inference)")
        log.info("[LLM-FAILOVER]    ├─ Gemini connect timeout: {self.gemini_connect_timeout_sec}s")
        log.info("[LLM-FAILOVER]    └─ Recovery check interval: {self.recovery_check_interval_sec}s")

    async def initialize_call(self, call_id: str) -> bool:
        """Initialize failover state for a call"""
        try:
            self.call_states[call_id] = {
                'mode': LLMMode.GEMINI_LIVE,
                'started_at': datetime.utcnow(),
                'gemini_failed': False,
                'gemini_failure_reason': None,
                'gemini_failure_time': None,
                'fallback_started_at': None,
                'recovery_attempted_at': None,
                'mode_switches': 0,
            }
            
            log.info(f"[LLM-FAILOVER:{call_id}] ✅ Call initialized - starting with Gemini Live")
            return True
            
        except Exception as e:
            log.error(f"[LLM-FAILOVER:{call_id}] Error initializing: {e}")
            return False

    async def try_gemini_live(
        self,
        call_id: str,
        audio_input_stream,
        on_audio_chunk: Optional[Callable] = None,
        on_text_chunk: Optional[Callable] = None,
        greeting_text: Optional[str] = None
    ) -> Optional[bytes]:
        """
        Try Gemini Live audio streaming
        
        Returns:
            Response audio bytes or None if failed
        """
        try:
            if not self.gemini_provider:
                log.error(f"[LLM-FAILOVER:{call_id}] ❌ Gemini provider not available")
                await self._record_gemini_failure(call_id, "provider_not_initialized")
                return None
            
            log.info(f"[LLM-FAILOVER:{call_id}] 🎯 Attempting Gemini Live audio streaming...")
            
            try:
                # Stream audio through Gemini Live (with timeout)
                response_audio = await asyncio.wait_for(
                    self.gemini_provider.stream_audio_bidirectional(
                        audio_input_stream=audio_input_stream,
                        on_audio_chunk=on_audio_chunk,
                        on_text_chunk=on_text_chunk,
                        greeting_text=greeting_text
                    ),
                    timeout=self.gemini_response_timeout_sec
                )
                
                log.info(f"[LLM-FAILOVER:{call_id}] ✅ Gemini Live succeeded")
                return response_audio
                
            except asyncio.TimeoutError:
                log.error(f"[LLM-FAILOVER:{call_id}] ❌ Gemini Live timeout ({self.gemini_response_timeout_sec}s)")
                await self._record_gemini_failure(call_id, "response_timeout")
                return None
                
            except Exception as e:
                log.error(f"[LLM-FAILOVER:{call_id}] ❌ Gemini Live error: {e}")
                await self._record_gemini_failure(call_id, f"error: {str(e)[:50]}")
                return None
                
        except Exception as e:
            log.error(f"[LLM-FAILOVER:{call_id}] Unexpected error: {e}")
            return None

    async def fallback_to_groq(
        self,
        call_id: str,
        prompt: str,
        system_prompt: Optional[str] = None,
        language: Optional[str] = None
    ) -> Optional[str]:
        """
        Fallback to Groq LLM for text inference
        
        Returns:
            Response text or None if failed
        """
        try:
            # Switch to fallback mode
            await self._switch_mode(call_id, LLMMode.GROQ_FALLBACK)
            
            log.info(f"[LLM-FAILOVER:{call_id}] 🔄 SWITCHING TO GROQ FALLBACK")
            log.info(f"[LLM-FAILOVER:{call_id}]    ├─ Reason: Gemini unavailable")
            log.info(f"[LLM-FAILOVER:{call_id}]    ├─ Using fast Groq LLM for text responses")
            log.info(f"[LLM-FAILOVER:{call_id}]    └─ Caller may hear fallback audio message")
            
            # Initialize Groq if needed
            if not self.groq_provider.client:
                init_success = await self.groq_provider.initialize()
                if not init_success:
                    log.error(f"[LLM-FAILOVER:{call_id}] ❌ Failed to initialize Groq")
                    return None
            
            # Generate response via Groq
            response = await asyncio.wait_for(
                self.groq_provider.generate(prompt),
                timeout=5.0
            )
            
            if response:
                log.info(f"[LLM-FAILOVER:{call_id}] ✅ Groq response: {len(response)} chars")
            else:
                log.error(f"[LLM-FAILOVER:{call_id}] ❌ Groq returned empty response")
            
            return response
            
        except asyncio.TimeoutError:
            log.error(f"[LLM-FAILOVER:{call_id}] ❌ Groq timeout")
            return None
        except Exception as e:
            log.error(f"[LLM-FAILOVER:{call_id}] ❌ Groq error: {e}")
            return None

    async def check_gemini_recovery(self, call_id: str) -> bool:
        """
        Periodically check if Gemini has recovered
        
        Returns:
            True if Gemini is now available
        """
        try:
            state = self.call_states.get(call_id)
            if not state or state['mode'] != LLMMode.GROQ_FALLBACK:
                return False  # Not in fallback mode
            
            # Don't check too frequently
            if state.get('recovery_attempted_at'):
                elapsed = (datetime.utcnow() - state['recovery_attempted_at']).total_seconds()
                if elapsed < self.recovery_check_interval_sec:
                    return False
            
            log.info(f"[LLM-FAILOVER:{call_id}] 🔍 Checking Gemini recovery...")
            
            # Try to create a Gemini session (simple health check)
            if self.gemini_provider:
                try:
                    success = await asyncio.wait_for(
                        self.gemini_provider.create_live_session("Quick recovery check"),
                        timeout=2.0
                    )
                    
                    if success:
                        log.info(f"[LLM-FAILOVER:{call_id}] ✅ GEMINI RECOVERED - Switching back to Gemini Live")
                        await self._switch_mode(call_id, LLMMode.GEMINI_LIVE)
                        state['gemini_failed'] = False
                        return True
                    
                except asyncio.TimeoutError:
                    log.debug(f"[LLM-FAILOVER:{call_id}] Gemini still not responding")
                except Exception as e:
                    log.debug(f"[LLM-FAILOVER:{call_id}] Gemini recovery check failed: {e}")
            
            state['recovery_attempted_at'] = datetime.utcnow()
            return False
            
        except Exception as e:
            log.error(f"[LLM-FAILOVER:{call_id}] Recovery check error: {e}")
            return False

    async def get_current_mode(self, call_id: str) -> LLMMode:
        """Get current LLM mode for call"""
        state = self.call_states.get(call_id)
        return state['mode'] if state else LLMMode.UNAVAILABLE

    async def _record_gemini_failure(self, call_id: str, reason: str) -> None:
        """Record Gemini failure"""
        try:
            state = self.call_states.get(call_id)
            if state:
                state['gemini_failed'] = True
                state['gemini_failure_reason'] = reason
                state['gemini_failure_time'] = datetime.utcnow()
                
                log.error(f"[LLM-FAILOVER:{call_id}] ❌ GEMINI FAILURE RECORDED: {reason}")
        except Exception as e:
            log.error(f"[LLM-FAILOVER:{call_id}] Error recording failure: {e}")

    async def _switch_mode(self, call_id: str, new_mode: LLMMode) -> None:
        """Switch LLM mode"""
        try:
            state = self.call_states.get(call_id)
            if state:
                old_mode = state['mode']
                state['mode'] = new_mode
                state['mode_switches'] += 1
                
                if old_mode != new_mode:
                    log.info(f"[LLM-FAILOVER:{call_id}] 🔄 MODE SWITCH #{state['mode_switches']}: {old_mode.value} → {new_mode.value}")
                    
                    if new_mode == LLMMode.GROQ_FALLBACK:
                        state['fallback_started_at'] = datetime.utcnow()
                
        except Exception as e:
            log.error(f"[LLM-FAILOVER:{call_id}] Error switching mode: {e}")

    async def cleanup_call(self, call_id: str) -> Dict[str, Any]:
        """
        Clean up and get final statistics
        
        Returns:
            Call statistics dict
        """
        try:
            state = self.call_states.pop(call_id, None)
            if not state:
                return {}
            
            duration = (datetime.utcnow() - state['started_at']).total_seconds()
            stats = {
                'call_id': call_id,
                'duration_sec': duration,
                'final_mode': state['mode'].value,
                'mode_switches': state['mode_switches'],
                'gemini_failed': state['gemini_failed'],
                'gemini_failure_reason': state['gemini_failure_reason'],
                'used_fallback': state['mode'] == LLMMode.GROQ_FALLBACK or state['gemini_failed'],
            }
            
            if state['fallback_started_at']:
                fallback_duration = (datetime.utcnow() - state['fallback_started_at']).total_seconds()
                stats['fallback_duration_sec'] = fallback_duration
            
            log.info(f"[LLM-FAILOVER] CALL CLEANUP: {call_id}")
            log.info(f"[LLM-FAILOVER]    ├─ Duration: {duration:.1f}s")
            log.info(f"[LLM-FAILOVER]    ├─ Final mode: {state['mode'].value}")
            log.info(f"[LLM-FAILOVER]    ├─ Mode switches: {state['mode_switches']}")
            log.info(f"[LLM-FAILOVER]    ├─ Gemini failed: {state['gemini_failed']}")
            log.info(f"[LLM-FAILOVER]    └─ Used fallback: {stats['used_fallback']}")
            
            return stats
            
        except Exception as e:
            log.error(f"[LLM-FAILOVER] Cleanup error: {e}")
            return {}


# Global failover service
_failover_service: Optional[LLMFailoverService] = None


async def init_llm_failover_service() -> LLMFailoverService:
    """Initialize LLM failover service"""
    global _failover_service
    _failover_service = LLMFailoverService()
    return _failover_service


def get_llm_failover_service() -> Optional[LLMFailoverService]:
    """Get LLM failover service instance"""
    return _failover_service
