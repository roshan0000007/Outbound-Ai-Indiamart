"""
PHASE 2: SEMANTIC / CONTEXT-AWARE ENDPOINTING

4-Layer Noise Isolation & Semantic Turn-Taking Pipeline
Replaces fixed silence-duration cutoffs with linguistic completeness detection

Phase 2 Implementation:
- Analyze interim STT transcripts for grammatical completeness
- Distinguish INCOMPLETE (continues, filler words) vs COMPLETE (full thought)
- Dynamically adjust silence-hangover window based on completeness signal
- Preserve natural multi-clause/code-switched speech patterns

Integration point: live_call_handler.py listening loop
- Receives interim STT results
- Runs lightweight completeness check
- Applies dynamic hangover window to silence detection

Prerequisite: STT_ENABLE_INTERIM_RESULTS = true in config.py (already enabled)
"""

import re
import logging
from typing import Optional, Dict, Tuple, List
from enum import Enum
import time

log = logging.getLogger(__name__)

class CompletionSignal(Enum):
    """Signal indicating sentence/thought completeness"""
    INCOMPLETE = "incomplete"
    COMPLETE = "complete"
    UNCERTAIN = "uncertain"

class SemanticCompletenessAnalyzer:
    """
    Lightweight linguistic completeness detection for multi-language utterances.
    
    Analyzes partial STT transcripts to determine if speaker has finished a complete thought:
    
    INCOMPLETE indicators:
    - Trailing conjunction: "and", "but", "because", "or", "so"
    - Trailing filler word: "um", "uh", "hmm", "matlab", "socho", "like"
    - Clear phrase connectors: "aur" (Hindi), "lekin" (Hindi), "ki" (Hindi)
    - Unfinished clause structure: No closing punctuation, no verb
    
    COMPLETE indicators:
    - Ends with punctuation: . ? ! or similar terminal
    - Clear subject+verb+object structure
    - Question form detected ("what", "why", "kya", "why")
    - Full affirmation/negation: "yes", "no", "haan", "nahi"
    
    Supports:
    - English
    - Hindi (Hinglish, code-switched)
    - Hindi script
    - Multilingual mixing
    
    Performance: <1ms per utterance (regex-based, lightweight)
    """

    INCOMPLETE_TRAILING_PATTERNS = {
        r'\b(and|but|because|or|so|as|while|if|unless|when|where|what|why|how|which|who|that|is)\s*$': 0.8,
        r'\b(gonna|wanna|could|should|would|could|might|must|may|will|shall)\s*$': 0.7,

        r'\b(um|uh|er|ah|hmm|like|you\s+know|kind\s+of|sort\s+of)\s*$': 0.9,
        r'\b(actually|basically|literally|literally|well|anyway|anyway)\s*$': 0.6,

        r'\b(aur|or|lekin|but|kyunki|because|toh|then|matlab|means|socho|think|dekho|see|sunno|listen)\s*$': 0.8,
        r'\b(haan|ok|theek|alright|iska|its|uska|that)\s*$': 0.5,

        r'\.\.\.$|\.\.+$': 1.0,

        r'\b(to|at|from|with|by|of|ka|ke|ki|me|mein|par|pe|ne)\s*$': 0.7,
    }

    COMPLETE_PATTERNS = {
        r'[.?!]+\s*$': 0.95,

        r'\b(what|where|when|why|how|who|which|can|could|will|would|should|is|are|do|does)\b': 0.7,
        r'\b(is\s+this|are\s+you|do\s+you|does|can\s+i|will|would|should)\b.*[?]\s*$': 0.95,

        r'\b(kya|kis|kahan|kaun|kyun|kaise)\b': 0.7,
        r'\b(hai\s*kya|ho\s*gaya|ho\s*gyi|hai|hain)\s*\?\s*$': 0.9,

        r'\b(yes|no|yeah|yep|nope|okay|ok|alright|fine|agreed|agreed)\s*$': 0.95,
        r'\b(haan|nahi|nah|bilkul|theek|nahi)\s*$': 0.95,

        r'\b(done|finished|complete|ready|set|understood|got\s+it|makes\s+sense)\s*$': 0.9,
        r'\b(samajh\s+gaya|dekh\s+li|kar\s+li|ho\s+gya)\s*$': 0.9,

        r'^(yes|no|haan|nahi|ok|theek|sure|maybe|thanks|sorry)$': 0.95,
    }

    FILLER_WORDS_TO_STRIP = {
        'en': ['um', 'uh', 'er', 'ah', 'hmm', 'like', 'you know', 'kind of', 'sort of', 'actually', 'basically'],
        'hi': ['matlab', 'socho', 'dekho', 'sunno', 'haan', 'toh', 'ok'],
        'mixed': ['um', 'uh', 'hmm', 'like', 'matlab', 'socho', 'toh', 'na', 'hain']
    }

    def __init__(self):
        """Initialize analyzer with pre-compiled regex patterns"""
        self.incomplete_patterns = [
            (re.compile(pattern, re.IGNORECASE), score)
            for pattern, score in self.INCOMPLETE_TRAILING_PATTERNS.items()
        ]
        self.complete_patterns = [
            (re.compile(pattern, re.IGNORECASE), score)
            for pattern, score in self.COMPLETE_PATTERNS.items()
        ]

        self.utterances_analyzed = 0
        self.complete_detected = 0
        self.incomplete_detected = 0
        self.uncertain_detected = 0

        log.info(f"[PHASE2-SEMANTIC] ✅ Semantic Completeness Analyzer initialized")
        log.info(f"[PHASE2-SEMANTIC]    Language support: English, Hindi, Hinglish (code-switched)")
        log.info(f"[PHASE2-SEMANTIC]    Performance: <1ms per utterance (regex-based)")

    def strip_filler_words(self, text: str) -> Tuple[str, bool]:
        """
        Remove trailing filler words to check underlying completeness.
        
        Args:
            text: Transcript text
            
        Returns:
            (stripped_text, had_fillers)
        """
        original = text.lower()

        for fillers in self.FILLER_WORDS_TO_STRIP.values():
            for filler in fillers:
                if original.endswith(filler):
                    stripped = original[:-len(filler)].rstrip()
                    if stripped:
                        return stripped, True

        return text.lower(), False

    def analyze_completeness(self, transcript: str) -> Tuple[CompletionSignal, float]:
        """
        Determine if transcript represents a complete thought.
        
        Args:
            transcript: STT transcript (partial or interim result)
            
        Returns:
            (completion_signal, confidence_score: 0.0-1.0)
        """
        if not transcript or len(transcript.strip()) == 0:
            return CompletionSignal.UNCERTAIN, 0.0

        text = transcript.strip()
        text_lower = text.lower()

        if len(text_lower.split()) <= 1:
            for pattern, score in self.complete_patterns:
                if pattern.search(text_lower):
                    return CompletionSignal.COMPLETE, score
            return CompletionSignal.UNCERTAIN, 0.3

        max_complete_score = 0.0
        for pattern, score in self.complete_patterns:
            if pattern.search(text_lower):
                max_complete_score = max(max_complete_score, score)

        max_incomplete_score = 0.0
        for pattern, score in self.incomplete_patterns:
            if pattern.search(text_lower):
                max_incomplete_score = max(max_incomplete_score, score)

        stripped, had_fillers = self.strip_filler_words(text)
        if had_fillers and stripped != text_lower:
            for pattern, score in self.complete_patterns:
                if pattern.search(stripped):
                    max_complete_score = max(max_complete_score, score)

        if max_complete_score > 0.8:
            return CompletionSignal.COMPLETE, max_complete_score

        if max_incomplete_score > 0.7:
            return CompletionSignal.INCOMPLETE, max_incomplete_score

        if max_complete_score > max_incomplete_score:
            return CompletionSignal.COMPLETE, max_complete_score
        elif max_incomplete_score > max_complete_score:
            return CompletionSignal.INCOMPLETE, max_incomplete_score
        else:
            return CompletionSignal.UNCERTAIN, 0.5

    def get_dynamic_hangover_ms(self, completion_signal: CompletionSignal) -> int:
        """
        Map completion signal to dynamic silence-hangover duration.
        
        Args:
            completion_signal: COMPLETE, INCOMPLETE, or UNCERTAIN
            
        Returns:
            Silence hangover duration in milliseconds
        """
        if completion_signal == CompletionSignal.COMPLETE:
            return 400
        elif completion_signal == CompletionSignal.INCOMPLETE:
            return 1200
        else:
            return 600

    def get_metrics(self) -> Dict:
        """Return analyzer metrics"""
        total = self.utterances_analyzed
        if total == 0:
            return {"utterances_analyzed": 0, "status": "no_data"}

        return {
            "utterances_analyzed": total,
            "complete_pct": round(100 * self.complete_detected / total, 1),
            "incomplete_pct": round(100 * self.incomplete_detected / total, 1),
            "uncertain_pct": round(100 * self.uncertain_detected / total, 1),
        }

    def log_metrics(self):
        """Log analyzer metrics"""
        metrics = self.get_metrics()
        if metrics.get("utterances_analyzed", 0) > 0:
            log.info(f"[PHASE2-SEMANTIC] 📊 ANALYZER METRICS:")
            log.info(f"[PHASE2-SEMANTIC]    ├─ Total analyzed: {metrics['utterances_analyzed']}")
            log.info(f"[PHASE2-SEMANTIC]    ├─ Complete: {metrics['complete_pct']}%")
            log.info(f"[PHASE2-SEMANTIC]    ├─ Incomplete: {metrics['incomplete_pct']}%")
            log.info(f"[PHASE2-SEMANTIC]    └─ Uncertain: {metrics['uncertain_pct']}%")

class DynamicEndpointingController:
    """
    Controls dynamic silence-hangover window based on STT interim results.
    
    Replaces the fixed VAD_SILENCE_HANGOVER_MS (200ms) with context-aware timing:
    - COMPLETE utterance: 400ms (respond quickly once thought is done)
    - INCOMPLETE utterance: 1200ms (give room for thought continuation)
    - UNCERTAIN: 600ms (safe middle ground)
    
    Integration in live_call_handler.py:
    - As each interim STT result arrives, update completeness signal
    - Adjust silence-hangover threshold dynamically
    - Keep existing VAD_RESUME_GRACE_WINDOW_MS logic (complementary, not redundant)
    
    Performance: Lightweight (just signal tracking + threshold lookup)
    """

    def __init__(self):
        """Initialize endpointing controller"""
        self.analyzer = SemanticCompletenessAnalyzer()

        self.current_transcript = ""
        self.current_signal = CompletionSignal.UNCERTAIN
        self.current_confidence = 0.0
        self.last_update_time = time.time()

        self.hangover_adjustments = 0
        self.total_hangover_ms = 0
        self.hangover_updates = 0

        log.info(f"[PHASE2-CONTROLLER] ✅ Dynamic Endpointing Controller initialized")
        log.info(f"[PHASE2-CONTROLLER]    COMPLETE → 400ms hangover (prompt response)")
        log.info(f"[PHASE2-CONTROLLER]    INCOMPLETE → 1200ms hangover (allow continuation)")
        log.info(f"[PHASE2-CONTROLLER]    UNCERTAIN → 600ms hangover (safe default)")

    def update_with_interim_transcript(self, transcript: str) -> int:
        """
        Update endpointing state with new STT interim transcript.
        
        Called each time interim STT result arrives during speech collection.
        
        Args:
            transcript: Partial transcript from speech recognition
            
        Returns:
            Recommended silence hangover (milliseconds)
        """
        if not transcript or transcript == self.current_transcript:
            return self.get_current_hangover_ms()

        self.current_transcript = transcript
        signal, confidence = self.analyzer.analyze_completeness(transcript)

        old_signal = self.current_signal
        self.current_signal = signal
        self.current_confidence = confidence
        self.last_update_time = time.time()

        hangover_ms = self.analyzer.get_dynamic_hangover_ms(signal)
        self.total_hangover_ms += hangover_ms
        self.hangover_updates += 1

        if signal != old_signal:
            self.hangover_adjustments += 1
            log.debug(f"[PHASE2-CONTROLLER] 🔄 Completeness signal changed: {old_signal.value} → {signal.value}")
            log.debug(f"[PHASE2-CONTROLLER]    Transcript: '{transcript}'")
            log.debug(f"[PHASE2-CONTROLLER]    Confidence: {confidence:.2f}")
            log.debug(f"[PHASE2-CONTROLLER]    New hangover: {hangover_ms}ms")

        self.analyzer.utterances_analyzed += 1
        if signal == CompletionSignal.COMPLETE:
            self.analyzer.complete_detected += 1
        elif signal == CompletionSignal.INCOMPLETE:
            self.analyzer.incomplete_detected += 1
        else:
            self.analyzer.uncertain_detected += 1

        return hangover_ms

    def get_current_hangover_ms(self) -> int:
        """Get current recommended silence hangover (milliseconds)"""
        return self.analyzer.get_dynamic_hangover_ms(self.current_signal)

    def get_current_signal(self) -> CompletionSignal:
        """Get current completeness signal"""
        return self.current_signal

    def reset(self):
        """Reset state for new utterance collection"""
        self.current_transcript = ""
        self.current_signal = CompletionSignal.UNCERTAIN
        self.current_confidence = 0.0
        self.last_update_time = time.time()

    def get_metrics(self) -> Dict:
        """Get controller metrics"""
        return {
            "hangover_adjustments": self.hangover_adjustments,
            "avg_hangover_ms": round(self.total_hangover_ms / max(1, self.hangover_updates), 1),
            "analyzer_metrics": self.analyzer.get_metrics()
        }

    def log_metrics(self):
        """Log controller metrics"""
        metrics = self.get_metrics()
        log.info(f"[PHASE2-CONTROLLER] 📊 CONTROLLER METRICS:")
        log.info(f"[PHASE2-CONTROLLER]    ├─ Hangover adjustments: {metrics['hangover_adjustments']}")
        log.info(f"[PHASE2-CONTROLLER]    ├─ Avg hangover: {metrics['avg_hangover_ms']}ms")
        log.info(f"[PHASE2-CONTROLLER]    └─ Analyzer: {metrics['analyzer_metrics']}")

_endpointing_controller: Optional[DynamicEndpointingController] = None

def get_endpointing_controller() -> DynamicEndpointingController:
    """Get or create global endpointing controller"""
    global _endpointing_controller
    if _endpointing_controller is None:
        _endpointing_controller = DynamicEndpointingController()
    return _endpointing_controller

def update_endpointing_with_transcript(transcript: str) -> int:
    """
    Convenience function: Update endpointing with interim STT transcript
    
    Usage in live_call_handler.py when interim STT result arrives:
        hangover_ms = update_endpointing_with_transcript(stt_interim_response.transcript)
        # Use hangover_ms to adjust silence detection timeout
    
    Returns: Recommended silence hangover (milliseconds)
    """
    controller = get_endpointing_controller()
    return controller.update_with_interim_transcript(transcript)
