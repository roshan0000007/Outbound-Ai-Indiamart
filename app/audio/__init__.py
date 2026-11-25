"""
Audio Processing Module

Semantic Turn-Taking & Smart Barge-In Pipeline:

PHASE 2: Semantic / Context-Aware Endpointing
- Analyze interim STT transcripts for completeness
- Dynamic silence-hangover adjustment
- Preserves natural multi-clause/code-switched speech

PHASE 3: Smart Barge-In / Interruption Gate
- 3-stage detection: RMS energy, sustained duration, word-length
- Only genuine customer speech interrupts AI playback
- Rejects coughs, background noise, short bursts

NOTE: Acoustic noise suppression (Phase 1) is now handled by Gemini Live natively.
"""

from .semantic_endpointing import (
    CompletionSignal,
    SemanticCompletenessAnalyzer,
    DynamicEndpointingController,
    get_endpointing_controller,
    update_endpointing_with_transcript
)

from .barge_in_gating import (
    BargeInGateStage,
    RMSEnergyGate,
    SustainedDurationGate,
    WordLengthGate,
    SmartBargeInGate,
    get_barge_in_gate,
    check_barge_in
)

__all__ = [
    "CompletionSignal",
    "SemanticCompletenessAnalyzer",
    "DynamicEndpointingController",
    "get_endpointing_controller",
    "update_endpointing_with_transcript",

    "BargeInGateStage",
    "RMSEnergyGate",
    "SustainedDurationGate",
    "WordLengthGate",
    "SmartBargeInGate",
    "get_barge_in_gate",
    "check_barge_in"
]
