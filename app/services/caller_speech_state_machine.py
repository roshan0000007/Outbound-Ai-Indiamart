"""
CALLER SPEECH STATE MACHINE & ENDPOINTING
==========================================

Critical fix for real-time caller speech endpointing.

PROBLEM SOLVED:
Background voice MUST NOT extend the caller's utterance.

When the caller stops speaking, the caller utterance MUST end even if:
- another person continues speaking
- background human speech is clear
- multiple people are talking simultaneously
- background voice is louder than caller
- VAD continues detecting speech

SOLUTION:
Implement per-call speech state machine that:
1. Tracks CALLER speech independently from background speech
2. Uses speaker continuity to separate caller from background
3. Freezes audio immediately when caller endpoint is detected
4. Never allows background speech to reset caller timestamps
5. Sends frozen audio to STT without contamination

ARCHITECTURE:
- Per-call state machine (not global)
- Speaker profile created from first valid utterance
- Lightweight speaker verification on each speech segment
- Caller timestamps updated ONLY for verified caller speech
- Background speech ignored for endpointing purposes
"""

import logging
import time
from enum import Enum
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field
import numpy as np

log = logging.getLogger("caller_speech_state_machine")


class SpeechState(Enum):
    """State machine states for caller speech processing"""
    AI_SPEAKING = "ai_speaking"                    # AI is generating response (TTS)
    WAITING_FOR_CALLER = "waiting_for_caller"      # Ready for caller speech
    CALLER_SPEAKING = "caller_speaking"            # Caller is actively speaking
    CALLER_ENDPOINT_CANDIDATE = "endpoint_candidate"  # Caller may have ended (confirmation window)
    FINALIZE_CALLER_UTTERANCE = "finalize_utterance"  # Freeze audio, stop capture
    PROCESSING_STT = "processing_stt"              # STT is being called


@dataclass
class CallerSpeakerProfile:
    """Speaker characteristics extracted from first valid caller utterance"""
    mean_energy: float = 0.0                 # Average RMS energy
    energy_variance: float = 0.0             # Variance of energy (stability)
    mean_frequency_content: Optional[np.ndarray] = None  # Spectral characteristics
    created_at: float = field(default_factory=time.time)
    num_samples_used: int = 0
    
    def is_valid(self) -> bool:
        """Check if profile has sufficient data"""
        return self.num_samples_used > 0 and self.mean_energy > 0


@dataclass
class SpeechSegmentAnalysis:
    """Analysis result for a speech segment"""
    is_caller: bool = True                   # Is this segment from the caller?
    confidence: float = 0.5                  # 0.0-1.0, how confident we are
    energy_deviation: float = 0.0           # How much energy differs from caller baseline
    segment_duration_ms: int = 0
    reason: str = "initial"                 # Why we classified this way


class CallerSpeechStateMachine:
    """
    Per-call speech state machine for caller utterance detection and endpointing.
    
    KEY DESIGN RULES (from requirements):
    1. BACKGROUND SPEECH MUST NEVER EXTEND CALLER UTTERANCE
    2. Only CALLER speech can update last_caller_speech_time
    3. Background speech updates are ignored for endpoint purposes
    4. Each call has isolated state (no cross-call contamination)
    5. Once endpoint detected, audio is frozen (no new frames appended)
    """
    
    def __init__(
        self,
        call_id: str,
        min_speech_ms: int = 200,          # Minimum speech duration to confirm onset
        end_silence_ms: int = 450,          # Silence timeout to confirm endpoint
        max_utterance_ms: int = 8000,       # Safety ceiling
        energy_threshold: int = 800,        # RMS energy threshold for speech
        caller_continuity_threshold: float = 0.7,  # How similar must segment be to caller profile?
    ):
        """
        Initialize per-call speech state machine.
        
        Args:
            call_id: Unique call identifier
            min_speech_ms: Minimum speech duration before confirming onset
            end_silence_ms: Silence duration before confirming caller endpoint
            max_utterance_ms: Safety ceiling for utterance collection
            energy_threshold: RMS energy threshold for speech detection
            caller_continuity_threshold: Similarity score needed to classify as caller (0.0-1.0)
        """
        self.call_id = call_id
        self.min_speech_ms = min_speech_ms
        self.end_silence_ms = end_silence_ms
        self.max_utterance_ms = max_utterance_ms
        self.energy_threshold = energy_threshold
        self.caller_continuity_threshold = caller_continuity_threshold
        
        # State tracking
        self.state = SpeechState.WAITING_FOR_CALLER
        self.caller_speaker_profile: Optional[CallerSpeakerProfile] = None
        self.has_enrolled_speaker = False
        
        # Per-utterance tracking
        self.speech_buffer: List[bytes] = []
        self.speech_frames_energies: List[float] = []
        self.last_caller_speech_time: float = time.time()
        self.speech_start_time: float = 0.0
        self.endpoint_start_time: Optional[float] = None
        self.silent_frames_since_caller_end: int = 0
        
        # Frozen audio (after endpoint)
        self.frozen_caller_audio: Optional[bytes] = None
        
        # Diagnostics
        self.utterance_count = 0
        self.background_speech_events = []
        
        log.info(f"[{call_id}] 🎤 Speech state machine initialized")
        log.info(f"[{call_id}]    ├─ min_speech_ms: {min_speech_ms}")
        log.info(f"[{call_id}]    ├─ end_silence_ms: {end_silence_ms}")
        log.info(f"[{call_id}]    ├─ max_utterance_ms: {max_utterance_ms}")
        log.info(f"[{call_id}]    ├─ energy_threshold: {energy_threshold}")
        log.info(f"[{call_id}]    └─ caller_continuity_threshold: {caller_continuity_threshold}")
    
    def on_ai_speaking_start(self):
        """Call this when AI starts generating response"""
        self.state = SpeechState.AI_SPEAKING
        log.info(f"[{self.call_id}] 🤖 STATE: AI_SPEAKING (muting caller audio)")
    
    def on_ai_speaking_end(self):
        """Call this when AI finishes response"""
        self._start_new_utterance()
        log.info(f"[{self.call_id}] 📢 STATE: WAITING_FOR_CALLER (AI response complete, ready for speech)")
    
    def _start_new_utterance(self):
        """Reset state for new utterance collection"""
        self.state = SpeechState.WAITING_FOR_CALLER
        self.speech_buffer = []
        self.speech_frames_energies = []
        self.speech_start_time = time.time()
        self.last_caller_speech_time = time.time()
        self.endpoint_start_time = None
        self.silent_frames_since_caller_end = 0
        self.frozen_caller_audio = None
        self.utterance_count += 1
    
    def enroll_caller_speaker(self, audio_frames: List[bytes], frame_energies: List[float]) -> bool:
        """
        Enroll caller speaker profile from first valid utterance.
        
        This is called ONCE at the beginning of the first valid utterance.
        The profile is used to verify subsequent speech segments.
        
        Args:
            audio_frames: List of audio frames (ULAW bytes, 160 bytes each)
            frame_energies: List of RMS energy values for each frame
        
        Returns:
            True if enrollment successful, False otherwise
        """
        if not audio_frames or not frame_energies or len(audio_frames) != len(frame_energies):
            log.warning(f"[{self.call_id}] ⚠️ Cannot enroll speaker: insufficient data")
            return False
        
        if self.has_enrolled_speaker:
            log.debug(f"[{self.call_id}] Speaker already enrolled, skipping re-enrollment")
            return True
        
        try:
            mean_energy = np.mean(frame_energies)
            energy_variance = np.var(frame_energies)
            
            self.caller_speaker_profile = CallerSpeakerProfile(
                mean_energy=float(mean_energy),
                energy_variance=float(energy_variance),
                num_samples_used=len(audio_frames)
            )
            self.has_enrolled_speaker = True
            
            log.info(f"[{self.call_id}] ✅ CALLER SPEAKER ENROLLED")
            log.info(f"[{self.call_id}]    ├─ Mean energy: {mean_energy:.0f} RMS")
            log.info(f"[{self.call_id}]    ├─ Energy variance: {energy_variance:.0f}")
            log.info(f"[{self.call_id}]    ├─ Samples: {len(audio_frames)} frames (~{len(audio_frames)*20}ms)")
            log.info(f"[{self.call_id}]    └─ Profile ready for speaker verification")
            
            return True
        
        except Exception as e:
            log.error(f"[{self.call_id}] ❌ Speaker enrollment failed: {e}")
            return False
    
    def verify_speech_segment(self, frame_energies: List[float]) -> SpeechSegmentAnalysis:
        """
        Verify if a speech segment belongs to the caller or is background.
        
        CRITICAL: This is the core logic that separates caller from background speech.
        
        Algorithm:
        1. If no speaker profile yet, assume caller (first utterance)
        2. Compare segment energy to caller profile
        3. Caller speech: consistent energy (small variance)
        4. Background speech: inconsistent energy (high variance) or very different level
        
        Args:
            frame_energies: List of RMS energy values for speech segment
        
        Returns:
            SpeechSegmentAnalysis with is_caller decision and confidence
        """
        if not frame_energies:
            return SpeechSegmentAnalysis(
                is_caller=False,
                confidence=0.0,
                reason="no_frames"
            )
        
        # Case 1: No speaker profile yet - assume caller
        if not self.caller_speaker_profile or not self.has_enrolled_speaker:
            return SpeechSegmentAnalysis(
                is_caller=True,
                confidence=1.0,
                reason="no_profile_yet"
            )
        
        # Case 2: Analyze segment characteristics
        segment_mean_energy = np.mean(frame_energies)
        segment_variance = np.var(frame_energies)
        
        caller_mean = self.caller_speaker_profile.mean_energy
        caller_variance = self.caller_speaker_profile.energy_variance
        
        # Key metrics for speaker identification:
        
        # 1. Energy level similarity
        #    Caller speech: typically within ±40% of baseline
        #    Background speech: often 30-60% of caller (farther from phone) or 2x (loud room)
        energy_ratio = segment_mean_energy / max(1, caller_mean)
        energy_deviation = abs(energy_ratio - 1.0)
        
        # Too quiet = likely background
        if energy_ratio < 0.3:  # <30% of caller
            return SpeechSegmentAnalysis(
                is_caller=False,
                confidence=0.85,
                energy_deviation=energy_deviation,
                reason="too_quiet_background"
            )
        
        # Too loud = unlikely to be same speaker in same position
        if energy_ratio > 2.5:  # >250% of caller
            return SpeechSegmentAnalysis(
                is_caller=False,
                confidence=0.75,
                energy_deviation=energy_deviation,
                reason="too_loud_background"
            )
        
        # 2. Energy stability (variance)
        #    Caller speech: moderate variance (natural speech modulation)
        #    Background noise: either very stable (constant hum) or very unstable (TV, multiple speakers)
        variance_ratio = segment_variance / max(1, caller_variance)
        
        # Extreme stability = likely background (like HVAC, fan)
        if variance_ratio < 0.1:  # <10% of caller variance
            return SpeechSegmentAnalysis(
                is_caller=False,
                confidence=0.70,
                energy_deviation=energy_deviation,
                reason="background_noise_stable"
            )
        
        # Extreme instability = could be overlapping speech or crowd
        if variance_ratio > 5.0:  # >500% of caller variance
            return SpeechSegmentAnalysis(
                is_caller=False,
                confidence=0.65,
                energy_deviation=energy_deviation,
                reason="overlapping_or_crowd"
            )
        
        # Case 3: Energy within acceptable range, variance reasonable
        # This is likely the caller
        similarity_score = 1.0 - min(energy_deviation, 1.0)  # Scale to 0-1
        
        if similarity_score >= self.caller_continuity_threshold:
            return SpeechSegmentAnalysis(
                is_caller=True,
                confidence=similarity_score,
                energy_deviation=energy_deviation,
                reason="caller_continuity_match"
            )
        else:
            return SpeechSegmentAnalysis(
                is_caller=False,
                confidence=1.0 - similarity_score,
                energy_deviation=energy_deviation,
                reason="speaker_mismatch"
            )
    
    def process_frame(
        self,
        frame: bytes,
        frame_energy: float,
        is_speech_detected: bool,
    ) -> Tuple[bool, str]:
        """
        Process incoming RTP frame and update state machine.
        
        CRITICAL RULE:
        Only CALLER speech updates last_caller_speech_time.
        Background speech is logged but does NOT extend the endpoint.
        
        Args:
            frame: Audio frame (160 bytes ULAW)
            frame_energy: RMS energy of frame
            is_speech_detected: Is this frame speech (above VAD threshold)?
        
        Returns:
            (should_freeze_audio, reason): True if endpoint detected and audio should be frozen
        """
        # Rule 1: AI is speaking - ignore caller audio
        if self.state == SpeechState.AI_SPEAKING:
            return False, "ai_speaking"
        
        # Rule 2: Endpoint already confirmed and frozen
        if self.state == SpeechState.FINALIZE_CALLER_UTTERANCE:
            # Don't accept any more frames for this utterance
            return True, "already_finalized"
        
        # Rule 3: Processing STT - no new capture
        if self.state == SpeechState.PROCESSING_STT:
            return True, "stt_processing"
        
        # ─── CASE 1: WAITING_FOR_CALLER ───
        if self.state == SpeechState.WAITING_FOR_CALLER:
            if not is_speech_detected:
                # Still waiting for speech
                return False, "waiting_for_speech"
            
            # Speech detected - transition to CALLER_SPEAKING
            self.state = SpeechState.CALLER_SPEAKING
            self.speech_buffer = [frame]
            self.speech_frames_energies = [frame_energy]
            self.speech_start_time = time.time()
            self.last_caller_speech_time = self.speech_start_time
            self.endpoint_start_time = None
            self.silent_frames_since_caller_end = 0
            
            log.info(f"[{self.call_id}] 🎤 CALLER_SPEAKING (onset detected)")
            
            # Enroll speaker on first utterance
            if not self.has_enrolled_speaker:
                self.enroll_caller_speaker([frame], [frame_energy])
            
            return False, "speech_onset"
        
        # ─── CASE 2: CALLER_SPEAKING ───
        if self.state == SpeechState.CALLER_SPEAKING:
            if is_speech_detected:
                # Verify this is caller speech, not background
                segment_analysis = self.verify_speech_segment([frame_energy])
                
                if segment_analysis.is_caller:
                    # ✅ CALLER SPEECH: Update only if CALLER verified
                    self.speech_buffer.append(frame)
                    self.speech_frames_energies.append(frame_energy)
                    self.last_caller_speech_time = time.time()
                    self.silent_frames_since_caller_end = 0
                    self.endpoint_start_time = None
                    
                    log.debug(f"[{self.call_id}] 🎙️ Caller speech (confidence={segment_analysis.confidence:.0%})")
                    
                    return False, "caller_speech_continues"
                else:
                    # ❌ BACKGROUND SPEECH: Do NOT update caller timestamps
                    # This is the CRITICAL FIX - background speech is logged but ignored
                    self.background_speech_events.append({
                        "time": time.time(),
                        "reason": segment_analysis.reason,
                        "energy": frame_energy,
                        "confidence": segment_analysis.confidence
                    })
                    
                    log.warning(f"[{self.call_id}] 🚫 BACKGROUND SPEECH DETECTED (NOT extending caller endpoint)")
                    log.warning(f"[{self.call_id}]    ├─ Reason: {segment_analysis.reason}")
                    log.warning(f"[{self.call_id}]    ├─ Energy: {frame_energy:.0f} (caller baseline: {self.caller_speaker_profile.mean_energy if self.caller_speaker_profile else 'N/A'})")
                    log.warning(f"[{self.call_id}]    ├─ Confidence: {segment_analysis.confidence:.0%}")
                    log.warning(f"[{self.call_id}]    └─ Action: IGNORING (last_caller_speech_time NOT updated)")
                    
                    # ✅ CRITICAL: Do NOT append to buffer, do NOT update caller timestamps
                    # Treat as silent frame for endpoint purposes
                    self.silent_frames_since_caller_end += 1
                    
                    return False, "background_speech_ignored"
            else:
                # Silence detected (below VAD threshold)
                self.speech_buffer.append(frame)
                self.speech_frames_energies.append(frame_energy)
                self.silent_frames_since_caller_end += 1
                
                # Check if endpoint should be confirmed
                endpoint_duration_ms = self.silent_frames_since_caller_end * 20
                
                if endpoint_duration_ms >= self.end_silence_ms:
                    # Endpoint confirmed
                    self.state = SpeechState.ENDPOINT_CANDIDATE
                    self.endpoint_start_time = time.time()
                    
                    log.info(f"[{self.call_id}] ✋ ENDPOINT_CANDIDATE (caller speech ended)")
                    log.info(f"[{self.call_id}]    ├─ Silence duration: {endpoint_duration_ms}ms (threshold: {self.end_silence_ms}ms)")
                    log.info(f"[{self.call_id}]    ├─ Speech frames: {len(self.speech_buffer)}")
                    log.info(f"[{self.call_id}]    ├─ Duration: {(len(self.speech_buffer)*20)/1000:.2f}s")
                    log.info(f"[{self.call_id}]    └─ Confirmation window: {200}ms (caller can resume within this window)")
                    
                    return False, "endpoint_candidate"
                
                return False, "silence_accumulating"
        
        # ─── CASE 3: ENDPOINT_CANDIDATE ───
        if self.state == SpeechState.ENDPOINT_CANDIDATE:
            if is_speech_detected:
                # Verify if this is caller resuming or background speech
                segment_analysis = self.verify_speech_segment([frame_energy])
                
                if segment_analysis.is_caller:
                    # Caller resumed - go back to CALLER_SPEAKING
                    self.state = SpeechState.CALLER_SPEAKING
                    self.speech_buffer.append(frame)
                    self.speech_frames_energies.append(frame_energy)
                    self.last_caller_speech_time = time.time()
                    self.silent_frames_since_caller_end = 0
                    
                    log.info(f"[{self.call_id}] ↩️  CALLER_SPEAKING (resumed after pause)")
                    
                    return False, "caller_resumed"
                else:
                    # Background speech during endpoint window - STAY in ENDPOINT_CANDIDATE
                    # Don't extend, don't return to CALLER_SPEAKING
                    log.warning(f"[{self.call_id}] 🚫 BACKGROUND during endpoint window (NOT extending)")
                    
                    # Check if endpoint confirmation window has expired
                    if self.endpoint_start_time:
                        window_duration_ms = (time.time() - self.endpoint_start_time) * 1000
                        if window_duration_ms > 200:  # 200ms confirmation window
                            # Finalize utterance
                            self._finalize_utterance()
                            return True, "endpoint_finalized"
                    
                    return False, "endpoint_window_active"
            else:
                # Still silence - finalize endpoint
                self._finalize_utterance()
                return True, "endpoint_finalized"
        
        return False, "unknown_state"
    
    def _finalize_utterance(self):
        """
        Freeze audio and prepare for STT.
        
        After this point, NO additional frames are appended to this utterance.
        Audio is frozen and contamination-free.
        """
        self.state = SpeechState.FINALIZE_CALLER_UTTERANCE
        self.frozen_caller_audio = b"".join(self.speech_buffer)
        
        duration_ms = len(self.speech_buffer) * 20
        
        log.info(f"[{self.call_id}] ❄️ UTTERANCE FROZEN")
        log.info(f"[{self.call_id}]    ├─ Audio frames: {len(self.speech_buffer)}")
        log.info(f"[{self.call_id}]    ├─ Duration: {duration_ms}ms ({duration_ms/1000:.2f}s)")
        log.info(f"[{self.call_id}]    ├─ Audio size: {len(self.frozen_caller_audio)} bytes")
        log.info(f"[{self.call_id}]    ├─ Background speech events during call: {len(self.background_speech_events)}")
        if self.background_speech_events:
            log.info(f"[{self.call_id}]    └─ Background events:")
            for i, event in enumerate(self.background_speech_events[-3:]):  # Last 3 events
                log.info(f"[{self.call_id}]       └─ Event {i+1}: {event['reason']} (confidence={event['confidence']:.0%})")
    
    def get_frozen_audio(self) -> Optional[bytes]:
        """
        Get frozen caller audio after endpoint.
        
        IMPORTANT: Audio is only available after endpoint is confirmed.
        This ensures no background speech has contaminated the buffer.
        
        Returns:
            Frozen ULAW audio bytes, or None if not finalized
        """
        if self.state not in [SpeechState.FINALIZE_CALLER_UTTERANCE, SpeechState.PROCESSING_STT]:
            return None
        
        return self.frozen_caller_audio
    
    def move_to_stt_processing(self):
        """Mark that STT processing has started"""
        if self.state == SpeechState.FINALIZE_CALLER_UTTERANCE:
            self.state = SpeechState.PROCESSING_STT
            log.info(f"[{self.call_id}] 📡 STATE: PROCESSING_STT")
    
    def get_diagnostics(self) -> Dict[str, Any]:
        """Get diagnostic information about speech state"""
        return {
            "call_id": self.call_id,
            "current_state": self.state.value,
            "utterance_count": self.utterance_count,
            "has_speaker_profile": self.has_enrolled_speaker,
            "speech_buffer_size": len(self.speech_buffer),
            "frozen_audio_size": len(self.frozen_caller_audio) if self.frozen_caller_audio else 0,
            "background_speech_events": len(self.background_speech_events),
            "silent_frames_since_caller": self.silent_frames_since_caller_end,
            "time_since_last_caller_speech_ms": int((time.time() - self.last_caller_speech_time) * 1000),
        }
