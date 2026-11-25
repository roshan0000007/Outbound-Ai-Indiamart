"""
ENDPOINTING INTEGRATION MODULE
================================

Integration layer for call management with Gemini Live audio streaming.

This module provides:
1. Per-call state machine initialization
2. Frame-by-frame processing integration
3. Endpoint detection and audio buffering
4. Direct Gemini Live streaming

Usage in live_call_handler:
    - Audio flows directly to Gemini Live
    - No intermediate STT/TTS steps
    - Real-time bidirectional streaming
"""
        frozen_audio = endpointing.get_frozen_audio()
        # Send frozen audio to STT (no contamination)
"""

import logging
from typing import Tuple, Optional
from ..services.caller_speech_state_machine import (
    CallerSpeechStateMachine,
    SpeechState
)

log = logging.getLogger("endpointing_integration")

# Global registry of state machines (keyed by call_id)
_state_machines = {}


class EndpointingIntegration:
    """
    Integration wrapper for caller speech state machine.
    
    Provides simple interface for live_call_handler to use the state machine.
    """
    
    def __init__(
        self,
        call_id: str,
        min_speech_ms: int = 200,
        end_silence_ms: int = 450,
        max_utterance_ms: int = 8000,
    ):
        """
        Initialize endpointing for a call.
        
        Args:
            call_id: Unique call identifier
            min_speech_ms: Minimum speech duration to confirm onset
            end_silence_ms: Silence timeout to confirm endpoint
            max_utterance_ms: Safety ceiling for utterance collection
        """
        self.call_id = call_id
        self.state_machine = CallerSpeechStateMachine(
            call_id=call_id,
            min_speech_ms=min_speech_ms,
            end_silence_ms=end_silence_ms,
            max_utterance_ms=max_utterance_ms,
        )
        
        # Register in global registry
        _state_machines[call_id] = self.state_machine
        
        log.info(f"[EndpointingIntegration] Initialized for {call_id}")
    
    def on_ai_speaking_start(self):
        """Call when AI starts generating response"""
        self.state_machine.on_ai_speaking_start()
    
    def on_ai_speaking_end(self):
        """Call when AI finishes response"""
        self.state_machine.on_ai_speaking_end()
    
    def process_frame(
        self,
        frame: bytes,
        frame_energy: float,
        is_speech_detected: bool,
    ) -> Tuple[bool, str]:
        """
        Process a single RTP frame through the state machine.
        
        CRITICAL INTEGRATION POINT:
        This is where the fix for "background speech extends caller endpoint" happens.
        
        Returns:
            (should_freeze, reason):
            - True: Endpoint detected, audio frozen, stop processing this utterance
            - False: Continue processing frames
        """
        return self.state_machine.process_frame(
            frame=frame,
            frame_energy=frame_energy,
            is_speech_detected=is_speech_detected,
        )
    
    def get_frozen_audio(self) -> Optional[bytes]:
        """
        Get frozen caller audio after endpoint.
        
        Returns:
            ULAW audio bytes ready for STT, or None if not finalized
        """
        return self.state_machine.get_frozen_audio()
    
    def get_state(self) -> str:
        """Get current state as string"""
        return self.state_machine.state.value
    
    def on_audio_processing_complete(self):
        """Mark that audio processing is complete - Ready for Gemini"""
        self.state_machine.state = "ready_for_gemini"
    
    def get_diagnostics(self):
        """Get diagnostic information"""
        return self.state_machine.get_diagnostics()
    
    @staticmethod
    def get_or_create(
        call_id: str,
        min_speech_ms: int = 200,
        end_silence_ms: int = 450,
        max_utterance_ms: int = 8000,
    ) -> "EndpointingIntegration":
        """
        Get existing or create new endpointing instance for call.
        
        This is safe to call multiple times - won't create duplicates.
        """
        if call_id not in _state_machines:
            return EndpointingIntegration(
                call_id=call_id,
                min_speech_ms=min_speech_ms,
                end_silence_ms=end_silence_ms,
                max_utterance_ms=max_utterance_ms,
            )
        
        # Return wrapper for existing machine
        wrapper = EndpointingIntegration.__new__(EndpointingIntegration)
        wrapper.call_id = call_id
        wrapper.state_machine = _state_machines[call_id]
        return wrapper
    
    @staticmethod
    def cleanup(call_id: str):
        """Clean up state machine for call (call teardown)"""
        if call_id in _state_machines:
            del _state_machines[call_id]
            log.info(f"[EndpointingIntegration] Cleaned up for {call_id}")


def get_endpointing_for_call(call_id: str) -> Optional[EndpointingIntegration]:
    """
    Get endpointing instance for a call, or None if not initialized.
    
    Safe to call - returns None if call not found.
    """
    if call_id not in _state_machines:
        return None
    
    wrapper = EndpointingIntegration.__new__(EndpointingIntegration)
    wrapper.call_id = call_id
    wrapper.state_machine = _state_machines[call_id]
    return wrapper
