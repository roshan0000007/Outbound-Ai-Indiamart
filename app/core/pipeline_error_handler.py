"""
Pipeline Error Handler
Production-quality error handling for audio pipeline

**Task 11: Production-Quality Error Handling**

Provides:
- Try-catch blocks at each critical stage
- Fallback behaviors for different error types
- Error logging with full context
- Circuit breaker integration
- Graceful degradation
"""

import traceback
from typing import Optional, Dict, Callable, Any
from enum import Enum

from ..core.config import log
from ..core.error_handling import get_circuit_breaker, ErrorContext

class PipelineStage(Enum):
    """Audio pipeline stages"""
    TTS_GENERATION = "tts_generation"
    AUDIO_CODEC_CONVERSION = "audio_codec_conversion"
    RTP_TRANSMISSION = "rtp_transmission"
    STT_PROCESSING = "stt_processing"
    VAD_INITIALIZATION = "vad_initialization"
    LLM_PROCESSING = "llm_processing"
    RAG_RETRIEVAL = "rag_retrieval"
    GREETING_PLAYBACK = "greeting_playback"

class PipelineErrorHandler:
    """Production-quality error handling for pipeline stages"""

    def __init__(self):
        self.error_counts = {}

    def handle_stage_error(self,
                          stage: PipelineStage,
                          error: Exception,
                          call_id: str,
                          context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Handle error from a pipeline stage
        
        Args:
            stage: Pipeline stage where error occurred
            error: Exception object
            call_id: Call identifier
            context: Additional context data
            
        Returns:
            Error handling result {status, fallback_action, message}
        """

        if stage not in self.error_counts:
            self.error_counts[stage] = 0
        self.error_counts[stage] += 1

        context_data = context or {}
        error_context = ErrorContext(
            call_id=call_id,
            stage=stage.value,
            error_type=type(error).__name__,
            error_message=str(error),
            additional_context=context_data
        )
        error_context.log_error(log)

        log.debug(f"[PIPELINE-ERROR] Stack trace:\n{traceback.format_exc()}")

        cb = get_circuit_breaker(stage.value)
        cb.record_failure(str(error))

        fallback = self._get_fallback_for_stage(stage, call_id, error)

        return {
            "status": "error",
            "stage": stage.value,
            "error_type": type(error).__name__,
            "error_message": str(error),
            "fallback_action": fallback.get("action"),
            "fallback_message": fallback.get("message"),
        }

    def _get_fallback_for_stage(self,
                               stage: PipelineStage,
                               call_id: str,
                               error: Exception) -> Dict[str, str]:
        """
        Get fallback behavior for a specific pipeline stage
        
        Args:
            stage: Pipeline stage
            call_id: Call identifier
            error: Exception that occurred
            
        Returns:
            Fallback action {action, message}
        """

        if stage == PipelineStage.TTS_GENERATION:
            log.error(f"[PIPELINE-ERROR] TTS generation failed, using pre-generated fallback audio")
            return {
                "action": "use_pregenerated_audio",
                "message": "TTS service temporarily unavailable, using pre-recorded message",
            }

        elif stage == PipelineStage.AUDIO_CODEC_CONVERSION:
            log.error(f"[PIPELINE-ERROR] Audio codec conversion failed, using comfort noise")
            return {
                "action": "use_comfort_noise",
                "message": "Audio codec error, using comfort noise as fallback",
            }

        elif stage == PipelineStage.RTP_TRANSMISSION:
            log.error(f"[PIPELINE-ERROR] RTP transmission failed, will retry on next frame")
            return {
                "action": "retry_rtp_transmission",
                "message": "RTP transmission error, retrying",
            }

        elif stage == PipelineStage.STT_PROCESSING:
            log.error(f"[PIPELINE-ERROR] STT processing failed, asking customer to repeat")
            return {
                "action": "ask_customer_to_repeat",
                "message": "Speech processing error, please repeat your message",
            }

        elif stage == PipelineStage.VAD_INITIALIZATION:
            log.error(f"[PIPELINE-ERROR] VAD initialization failed, using default configuration")
            return {
                "action": "use_default_vad",
                "message": "VAD initialization failed, using default settings",
            }

        elif stage == PipelineStage.LLM_PROCESSING:
            log.error(f"[PIPELINE-ERROR] LLM processing failed, offering transfer to agent")
            return {
                "action": "transfer_to_agent",
                "message": "AI processing temporarily unavailable, transferring to agent",
            }

        elif stage == PipelineStage.RAG_RETRIEVAL:
            log.error(f"[PIPELINE-ERROR] RAG retrieval failed, using basic knowledge")
            return {
                "action": "use_basic_knowledge",
                "message": "Knowledge base temporarily unavailable, using basic information",
            }

        elif stage == PipelineStage.GREETING_PLAYBACK:
            log.error(f"[PIPELINE-ERROR] Greeting playback failed, continuing to listening")
            return {
                "action": "skip_greeting",
                "message": "Greeting playback failed, proceeding to listening",
            }

        else:
            return {
                "action": "continue",
                "message": "Pipeline error occurred, continuing",
            }

    def handle_service_unavailable(self,
                                   service_name: str,
                                   call_id: str) -> str:
        """
        Handle service unavailable scenario
        
        Args:
            service_name: Service that's unavailable (e.g., "tts", "stt", "llm")
            call_id: Call identifier
            
        Returns:
            Fallback message or action
        """
        cb = get_circuit_breaker(service_name)
        health = cb.get_health()

        log.error(f"[PIPELINE-ERROR] Service '{service_name}' is {health.value} for call {call_id}")

        if service_name == "tts":
            return "use_pregenerated_audio"
        elif service_name == "stt":
            return "ask_customer_to_repeat"
        elif service_name == "llm":
            return "transfer_to_agent"
        elif service_name == "rag":
            return "use_basic_knowledge"
        else:
            return "continue"

    def wrap_stage_call(self,
                       stage: PipelineStage,
                       func: Callable,
                       call_id: str,
                       *args,
                       **kwargs) -> Optional[Any]:
        """
        Wrap a pipeline stage call with error handling
        
        Args:
            stage: Pipeline stage
            func: Function to call
            call_id: Call identifier
            *args: Positional arguments for function
            **kwargs: Keyword arguments for function
            
        Returns:
            Function result or None on error
        """
        try:
            log.debug(f"[PIPELINE-ERROR] Executing stage: {stage.value}")
            result = func(*args, **kwargs)

            cb = get_circuit_breaker(stage.value)
            cb.record_success()

            return result

        except Exception as e:
            self.handle_stage_error(stage, e, call_id, {"function": func.__name__})
            return None

_pipeline_error_handler = None

def get_pipeline_error_handler() -> PipelineErrorHandler:
    """Get or create global pipeline error handler"""
    global _pipeline_error_handler
    if _pipeline_error_handler is None:
        _pipeline_error_handler = PipelineErrorHandler()
    return _pipeline_error_handler
