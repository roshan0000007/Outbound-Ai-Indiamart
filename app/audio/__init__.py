"""
Audio Processing Module

4-Layer Noise Isolation & Semantic Turn-Taking Pipeline:

PHASE 1: Acoustic Noise Suppression + Band-Pass Filter
- RNNoise integration (lightweight, 8kHz telephony)
- Band-pass filter (80Hz-3.4kHz telephony voice range)
- Processes audio BEFORE VAD for noise rejection

PHASE 2: Semantic / Context-Aware Endpointing
- Analyze interim STT transcripts for completeness
- Dynamic silence-hangover adjustment
- Preserves natural multi-clause/code-switched speech

PHASE 3: Smart Barge-In / Interruption Gate
- 3-stage detection: RMS energy, sustained duration, word-length
- Only genuine customer speech interrupts AI playback
- Rejects coughs, background noise, short bursts

PHASE 4: Speaker Voiceprint Isolation (optional, evaluate after Phase 1-3)
"""

from .noise_suppression import (
    AudioCleaningPipeline,
    RNNoiseProcessor,
    BandPassFilter,
    get_audio_pipeline,
    process_rtp_audio
)

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
    "AudioCleaningPipeline",
    "RNNoiseProcessor",
    "BandPassFilter",
    "get_audio_pipeline",
    "process_rtp_audio",

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
