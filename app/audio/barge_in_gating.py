"""
PHASE 3: SMART BARGE-IN / INTERRUPTION GATE

4-Layer Noise Isolation & Semantic Turn-Taking Pipeline
Only real customer speech triggers the AI to stop talking mid-response

Phase 3 Implementation:
Multi-stage decision gate for barge-in detection:
1. RMS Energy Gate: Frame must exceed calibrated noise-floor threshold
2. Minimum Sustained Duration: Require 3-5 consecutive frames (60-100ms)
3. Word-Length Gate: Interim STT results must show ≥1-2 words (not coughs/noise)
4. Decision: Send stop signal to media_service to halt TTS and flush tx_queue

Does NOT include optional Phase 4 (voiceprint matching) unless needed after testing

Integration point: live_call_handler.py barge-in detection loop
- Run WHILE AI audio transmission in progress
- Check each incoming frame against 3-step gate
- If all pass: trigger barge-in (stop AI playback)

Prerequisite: Phase 1 (clean audio) and Phase 2 (completeness concepts) in place
"""

import logging
import time
from typing import Optional, List, Tuple
from enum import Enum
from collections import deque
import numpy as np

log = logging.getLogger(__name__)

class BargeInGateStage(Enum):
    """Barge-in detection stage"""
    STAGE_1_RMS_ENERGY = "rms_energy"
    STAGE_2_DURATION = "sustained_duration"
    STAGE_3_WORD_LENGTH = "word_length"
    ALL_PASSED = "all_passed"
    REJECTED = "rejected"

class RMSEnergyGate:
    """
    STAGE 1: RMS Energy Gate
    
    Frame RMS energy must exceed calibrated noise-floor threshold.
    Rejects ambient noise, AC hum, fan noise, etc.
    
    Uses same adaptive noise-floor calibration as Phase 1 VAD:
    - During listening startup: sample first 5 frames (noise baseline)
    - Dynamic threshold: baseline_noise + margin (200 units)
    - Prevents false triggers from background noise alone
    
    Performance: <0.1ms per frame
    """

    def __init__(self, noise_floor_rms: int = 800, speech_threshold: int = 2000):
        """
        Initialize RMS gate.
        
        Args:
            noise_floor_rms: Baseline noise floor (config: NOISE_FLOOR_RMS)
            speech_threshold: Speech detection threshold (config: SPEECH_RMS_FLOOR)
        """
        self.noise_floor_rms = noise_floor_rms
        self.speech_threshold = speech_threshold
        self.calibrated_threshold = None
        self.is_calibrated = False

        self.calibration_samples = []
        self.calibration_frames_target = 5

        log.debug(f"[PHASE3-RMS-GATE] RMS Energy Gate initialized")
        log.debug(f"[PHASE3-RMS-GATE]    Noise floor: {noise_floor_rms} RMS units")
        log.debug(f"[PHASE3-RMS-GATE]    Speech threshold: {speech_threshold} RMS units")

    def calibrate_with_sample(self, frame_rms: float) -> bool:
        """
        Add sample for calibration (called during listening startup).
        
        Args:
            frame_rms: RMS energy of current frame
            
        Returns:
            True if calibration complete
        """
        if not self.is_calibrated:
            self.calibration_samples.append(frame_rms)

            if len(self.calibration_samples) >= self.calibration_frames_target:
                baseline = sum(self.calibration_samples) / len(self.calibration_samples)
                margin = 200
                self.calibrated_threshold = baseline + margin
                self.calibrated_threshold = min(self.calibrated_threshold, self.speech_threshold + 100)
                self.calibrated_threshold = max(self.calibrated_threshold, self.noise_floor_rms + 100)

                self.is_calibrated = True
                log.debug(f"[PHASE3-RMS-GATE] ✅ Calibration complete")
                log.debug(f"[PHASE3-RMS-GATE]    Baseline: {baseline:.0f}")
                log.debug(f"[PHASE3-RMS-GATE]    Calibrated threshold: {self.calibrated_threshold:.0f}")
                return True

        return self.is_calibrated

    def check_energy(self, frame_rms: float) -> Tuple[bool, float]:
        """
        Check if frame RMS exceeds threshold.
        
        Args:
            frame_rms: RMS energy of current frame
            
        Returns:
            (passed: bool, margin_above_threshold: float)
        """
        threshold = self.calibrated_threshold if self.is_calibrated else self.speech_threshold

        passed = frame_rms > threshold
        margin = frame_rms - threshold

        return passed, margin

class SustainedDurationGate:
    """
    STAGE 2: Minimum Sustained Duration
    
    Require 3-5 consecutive high-energy frames (60-100ms) before confirming barge-in.
    
    Rejects single-frame spikes (clicks, coughs) that briefly cross energy threshold.
    Typical barge-in speech: 200-500ms burst (10-25 frames), easily passes this gate.
    
    Performance: <0.1ms per frame
    """

    def __init__(self, min_consecutive_frames: int = 3, frame_duration_ms: int = 20):
        """
        Initialize duration gate.
        
        Args:
            min_consecutive_frames: Minimum consecutive high-energy frames (3-5)
            frame_duration_ms: Duration per frame (20ms at 8kHz)
        """
        self.min_consecutive_frames = min_consecutive_frames
        self.frame_duration_ms = frame_duration_ms
        self.consecutive_count = 0
        self.burst_start_time = None

        log.debug(f"[PHASE3-DURATION-GATE] Duration Gate initialized")
        log.debug(f"[PHASE3-DURATION-GATE]    Min consecutive frames: {min_consecutive_frames}")
        log.debug(f"[PHASE3-DURATION-GATE]    Min duration: {min_consecutive_frames * frame_duration_ms}ms")

    def add_frame(self, frame_passed_energy_gate: bool) -> Tuple[bool, int, float]:
        """
        Track frame, accumulate consecutive high-energy frames.
        
        Args:
            frame_passed_energy_gate: True if frame passed Stage 1 RMS gate
            
        Returns:
            (duration_gate_passed: bool, consecutive_count: int, burst_duration_ms: float)
        """
        if frame_passed_energy_gate:
            if self.consecutive_count == 0:
                self.burst_start_time = time.time()

            self.consecutive_count += 1
        else:
            self.consecutive_count = 0
            self.burst_start_time = None

        duration_passed = self.consecutive_count >= self.min_consecutive_frames

        burst_duration_ms = 0
        if self.burst_start_time is not None:
            burst_duration_ms = (time.time() - self.burst_start_time) * 1000.0

        return duration_passed, self.consecutive_count, burst_duration_ms

    def reset(self):
        """Reset for new burst detection"""
        self.consecutive_count = 0
        self.burst_start_time = None

class WordLengthGate:
    """
    STAGE 3: Word-Length Gate
    
    Require interim STT to show ≥1-2 words before treating as genuine interruption.
    
    Filters false positives from:
    - Coughs, throat clears: Often trigger energy gate but produce no words
    - "uh", "um": Single filler that briefly crosses threshold
    - Background speech fragments: <1 word caught mid-sentence
    
    Adds latency: Waits for at least partial STT result.
    - Typical interim results arrive within 100-150ms on 8kHz audio
    - Can relax this gate for borderline/uncertain cases to reduce latency
    - For clearly strong sustained speech, word check is optional (already passed 60-100ms threshold)
    
    Performance: <1ms per check (just word counting)
    """

    def __init__(self, min_word_count: int = 1, enable_for_weak_signals: bool = True):
        """
        Initialize word-length gate.
        
        Args:
            min_word_count: Minimum words to consider genuine speech (1-2)
            enable_for_weak_signals: Only require words for borderline RMS energy
        """
        self.min_word_count = min_word_count
        self.enable_for_weak_signals = enable_for_weak_signals

        log.debug(f"[PHASE3-WORD-GATE] Word-Length Gate initialized")
        log.debug(f"[PHASE3-WORD-GATE]    Min word count: {min_word_count}")
        log.debug(f"[PHASE3-WORD-GATE]    Enable for weak signals: {enable_for_weak_signals}")

    @staticmethod
    def count_words(transcript: str) -> int:
        """Count words in transcript (simple whitespace split)"""
        if not transcript:
            return 0
        words = [w for w in transcript.split() if w.strip()]
        return len(words)

    def check_word_count(self, transcript: str, is_weak_signal: bool = False) -> Tuple[bool, int]:
        """
        Check if transcript has sufficient word count.
        
        Args:
            transcript: Interim STT transcript
            is_weak_signal: True if RMS energy was borderline/weak
            
        Returns:
            (word_gate_passed: bool, word_count: int)
        """
        if not self.enable_for_weak_signals and not is_weak_signal:
            return True, self.count_words(transcript)

        word_count = self.count_words(transcript)
        passed = word_count >= self.min_word_count

        return passed, word_count

    def estimate_stasis_latency_ms(self, consecutive_frames: int, frame_duration_ms: int = 20) -> float:
        """
        Estimate latency waiting for STT interim result.
        
        Typical: 100-150ms for first interim result at 8kHz audio.
        
        Args:
            consecutive_frames: Frames accumulated so far
            frame_duration_ms: Duration per frame
            
        Returns:
            Estimated total latency (accumulated frames + STT wait time)
        """
        accumulated_ms = consecutive_frames * frame_duration_ms
        stasis_wait_ms = 100.0
        return accumulated_ms + stasis_wait_ms

class BackchannelFilter:
    """
    Twilio ignoreBackchannel-equivalent filter.
    
    Detects if speech contains ONLY backchannel filler words ("haan", "ok", "uh huh", etc.)
    and treats them as non-interrupting acknowledgments rather than barge-in triggers.
    
    This is distinct from follow-up continuation: backchannel filtering applies DURING
    AI playback, whereas follow-up detection applies AFTER AI finishes (next customer turn).
    """
    
    def __init__(self):
        """Initialize backchannel filter with filler word list"""
        from ..core.config import (
            BACKCHANNEL_FILLER_WORDS,
            BACKCHANNEL_DETECTION_CONFIDENCE,
            IGNORE_BACKCHANNEL_DURING_AI_PLAYBACK
        )
        self.backchannel_words = BACKCHANNEL_FILLER_WORDS
        self.confidence_threshold = BACKCHANNEL_DETECTION_CONFIDENCE
        self.enabled = IGNORE_BACKCHANNEL_DURING_AI_PLAYBACK
        self.calls_checked = 0
        self.backchannel_detected = 0
    
    def is_backchannel_only(self, interim_transcript: str) -> Tuple[bool, float]:
        """
        Check if interim STT result contains ONLY backchannel words.
        
        Args:
            interim_transcript: STT interim result (e.g., "haan", "ok", "uh huh")
            
        Returns:
            (is_backchannel: bool, confidence: float) where confidence is match ratio
            
        Logic:
        1. Normalize transcript (lowercase, remove punctuation)
        2. Split into words
        3. Check if ALL words are in backchannel filler list
        4. Return (True, 1.0) if 100% match, (False, 0.0) if no match
        """
        if not self.enabled or not interim_transcript:
            return False, 0.0
        
        self.calls_checked += 1
        
        # Normalize
        normalized = interim_transcript.strip().lower()
        normalized = ''.join(c for c in normalized if c.isalnum() or c.isspace())
        words = [w for w in normalized.split() if w]
        
        if not words:
            return False, 0.0
        
        # Check if all words are backchannel
        matching_words = sum(1 for w in words if w in self.backchannel_words)
        confidence = matching_words / len(words) if words else 0.0
        
        is_backchannel = confidence >= self.confidence_threshold
        
        if is_backchannel:
            self.backchannel_detected += 1
            log.debug(f"[BACKCHANNEL-FILTER] ✅ Detected backchannel: '{interim_transcript}' "
                     f"(confidence={confidence:.1%})")
        
        return is_backchannel, confidence
    
    def get_metrics(self) -> dict:
        """Return backchannel detection metrics"""
        return {
            "calls_checked": self.calls_checked,
            "backchannel_detected": self.backchannel_detected,
            "detection_rate": (self.backchannel_detected / self.calls_checked * 100 
                             if self.calls_checked > 0 else 0.0)
        }


class SmartBargeInGate:
    """
    Complete 3-stage smart barge-in gate.
    
    Decision chain per inbound frame while AI is transmitting:
    1. RMS Energy Gate: Frame above noise-floor threshold?
    2. Sustained Duration: 3-5 consecutive high-energy frames (60-100ms)?
    3. Word-Length Gate: Interim STT shows ≥1-2 words?
    
    ONLY after all three pass: Trigger barge-in (stop AI TTS)
    
    False positive goal: <5% of actual coughs/background noise during AI playback
    False negative goal: <5% of genuine interruptions missed
    
    Integration in live_call_handler.py:
        gate = SmartBargeInGate()
        while ai_playback_active:
            frame = get_rtp_frame()
            frame_rms = calculate_rms(frame)
            stage, passed = gate.check_frame(frame_rms, frame)
            if stage == BargeInGateStage.ALL_PASSED:
                # BARGE-IN TRIGGERED
                stop_tts()
                flush_tx_queue()
                break
    """

    def __init__(self,
                 noise_floor_rms: int = 800,
                 speech_threshold: int = 2000,
                 min_duration_frames: int = 3):
        """
        Initialize smart barge-in gate.
        
        Args:
            noise_floor_rms: Noise floor RMS (from config)
            speech_threshold: Speech detection threshold (from config)
            min_duration_frames: Min consecutive frames (3-5)
        """
        self.rms_gate = RMSEnergyGate(noise_floor_rms, speech_threshold)
        self.duration_gate = SustainedDurationGate(min_duration_frames)
        self.word_gate = WordLengthGate(min_word_count=1, enable_for_weak_signals=True)
        self.backchannel_filter = BackchannelFilter()  # NEW: Stage 4 - backchannel detection

        self.frames_checked = 0
        self.stage1_pass = 0
        self.stage2_pass = 0
        self.stage3_pass = 0
        self.barge_ins_triggered = 0

        self.pending_transcript = ""
        self.stt_result_time = None

        log.info(f"[PHASE3-GATE] ✅ Smart Barge-In Gate initialized")
        log.info(f"[PHASE3-GATE]    Stage 1: RMS Energy Gate")
        log.info(f"[PHASE3-GATE]    Stage 2: Sustained Duration (min {min_duration_frames} frames = {min_duration_frames*20}ms)")
        log.info(f"[PHASE3-GATE]    Stage 3: Word-Length Gate (min 1 word)")
        log.info(f"[PHASE3-GATE]    Goal: Only genuine interruptions trigger barge-in")

    def check_frame(self,
                    frame_rms: float,
                    interim_transcript: Optional[str] = None) -> Tuple[BargeInGateStage, bool, dict]:
        """
        Run frame through complete barge-in detection gate.
        
        Args:
            frame_rms: RMS energy of current frame
            interim_transcript: Optional interim STT transcript (from concurrent STT)
            
        Returns:
            (last_stage_reached: BargeInGateStage, barge_in_triggered: bool, diagnostics: dict)
        """
        self.frames_checked += 1
        diagnostics = {
            "frame_num": self.frames_checked,
            "frame_rms": round(frame_rms, 1),
            "stage_reached": None,
            "stage_name": None,
            "details": []
        }

        energy_passed, margin = self.rms_gate.check_energy(frame_rms)
        if energy_passed:
            self.stage1_pass += 1

        diagnostics["stage_reached"] = BargeInGateStage.STAGE_1_RMS_ENERGY
        diagnostics["stage_name"] = "RMS Energy"
        diagnostics["details"].append(f"Energy check: {'✓' if energy_passed else '✗'} (margin: {margin:.0f})")

        if not energy_passed:
            self.duration_gate.reset()
            return BargeInGateStage.STAGE_1_RMS_ENERGY, False, diagnostics

        duration_passed, consecutive, burst_duration = self.duration_gate.add_frame(energy_passed)
        if duration_passed:
            self.stage2_pass += 1

        diagnostics["stage_reached"] = BargeInGateStage.STAGE_2_DURATION
        diagnostics["stage_name"] = "Sustained Duration"
        diagnostics["details"].append(f"Duration check: {'✓' if duration_passed else '✗'} ({consecutive} frames, {burst_duration:.0f}ms)")

        if not duration_passed:
            return BargeInGateStage.STAGE_2_DURATION, False, diagnostics

        if interim_transcript is not None:
            self.pending_transcript = interim_transcript
            self.stt_result_time = time.time()

            is_weak = margin < 100
            word_passed, word_count = self.word_gate.check_word_count(interim_transcript, is_weak)
            if word_passed:
                self.stage3_pass += 1

            diagnostics["stage_reached"] = BargeInGateStage.STAGE_3_WORD_LENGTH
            diagnostics["stage_name"] = "Word-Length"
            diagnostics["details"].append(f"Word count check: {'✓' if word_passed else '✗'} ({word_count} words)")
            diagnostics["transcript"] = interim_transcript

            if not word_passed:
                return BargeInGateStage.STAGE_3_WORD_LENGTH, False, diagnostics

            self.barge_ins_triggered += 1
            diagnostics["stage_reached"] = BargeInGateStage.ALL_PASSED
            diagnostics["stage_name"] = "ALL PASSED → BARGE-IN TRIGGER"

            return BargeInGateStage.ALL_PASSED, True, diagnostics
        else:
            diagnostics["stage_reached"] = BargeInGateStage.STAGE_3_WORD_LENGTH
            diagnostics["stage_name"] = "Word-Length (pending STT)"
            diagnostics["details"].append(f"Word count check: pending (no STT result yet)")

            return BargeInGateStage.STAGE_3_WORD_LENGTH, False, diagnostics

    def calibrate_with_silence_frame(self, frame_rms: float) -> bool:
        """
        Calibrate RMS gate using silence frame (called during listening startup).
        
        Args:
            frame_rms: RMS energy of silence frame
            
        Returns:
            True if calibration complete
        """
        return self.rms_gate.calibrate_with_sample(frame_rms)

    def reset_burst_tracking(self):
        """Reset burst tracking for new detection cycle"""
        self.duration_gate.reset()
        self.pending_transcript = ""
        self.stt_result_time = None

    def get_metrics(self) -> dict:
        """Get gate metrics"""
        if self.frames_checked == 0:
            return {"frames_checked": 0, "status": "no_data"}

        return {
            "frames_checked": self.frames_checked,
            "stage1_pass_rate": round(100 * self.stage1_pass / self.frames_checked, 1),
            "stage2_pass_rate": round(100 * self.stage2_pass / self.stage1_pass, 1) if self.stage1_pass > 0 else 0,
            "stage3_pass_rate": round(100 * self.stage3_pass / self.stage2_pass, 1) if self.stage2_pass > 0 else 0,
            "barge_ins_triggered": self.barge_ins_triggered,
            "false_positive_estimate": f"{round(100 * self.stage1_pass / self.frames_checked, 1)}% noise alone"
        }

    def log_metrics(self):
        """Log gate metrics"""
        metrics = self.get_metrics()
        if metrics.get("frames_checked", 0) > 0:
            log.info(f"[PHASE3-GATE] 📊 BARGE-IN GATE METRICS:")
            log.info(f"[PHASE3-GATE]    ├─ Frames checked: {metrics['frames_checked']}")
            log.info(f"[PHASE3-GATE]    ├─ Stage 1 pass rate: {metrics['stage1_pass_rate']}%")
            log.info(f"[PHASE3-GATE]    ├─ Stage 2 pass rate: {metrics['stage2_pass_rate']}%")
            log.info(f"[PHASE3-GATE]    ├─ Stage 3 pass rate: {metrics['stage3_pass_rate']}%")
            log.info(f"[PHASE3-GATE]    ├─ Barge-ins triggered: {metrics['barge_ins_triggered']}")
            log.info(f"[PHASE3-GATE]    └─ Est. false positives (noise alone): {metrics['false_positive_estimate']}")

_barge_in_gate: Optional[SmartBargeInGate] = None

def get_barge_in_gate() -> SmartBargeInGate:
    """Get or create global barge-in gate"""
    global _barge_in_gate
    if _barge_in_gate is None:
        from ..core.config import NOISE_FLOOR_RMS, SPEECH_RMS_FLOOR
        _barge_in_gate = SmartBargeInGate(
            noise_floor_rms=NOISE_FLOOR_RMS,
            speech_threshold=SPEECH_RMS_FLOOR,
            min_duration_frames=3
        )
    return _barge_in_gate

def check_barge_in(frame_rms: float, interim_transcript: Optional[str] = None) -> Tuple[bool, dict]:
    """
    Convenience function: Check if frame triggers barge-in
    
    Usage in live_call_handler.py:
        barge_in_triggered, diagnostics = check_barge_in(frame_rms, interim_stt)
        if barge_in_triggered:
            # STOP TTS, flush tx_queue
    
    Returns: (barge_in_triggered: bool, diagnostics: dict)
    """
    gate = get_barge_in_gate()
    stage, triggered, diagnostics = gate.check_frame(frame_rms, interim_transcript)
    return triggered, diagnostics
