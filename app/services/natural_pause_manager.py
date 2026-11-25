"""
Natural Pause Manager Service

Manages natural pauses in speech synthesis for natural conversational flow.
"""

import logging
from typing import Dict, Optional, Any

logger = logging.getLogger(__name__)

class NaturalPauseManager:
    """
    Manages natural pauses between response components for realistic voice conversations.
    
    A natural pause:
    - Simulates a human breathing moment between sentences
    - Allows listeners to process the previous statement
    - Makes concatenated speech feel less robotic
    - Range: 250-700ms (natural human pause)
    - Default: 350ms (realistic conversational pause)
    
    Implementation uses SSML break tags for TTS compatibility:
    <break time="350ms"/>
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize Natural Pause Manager with optional configuration.
        
        Args:
            config: Optional configuration dict with:
                - default_pause_ms: Default pause duration (default: 350)
                - min_pause_ms: Minimum pause (default: 250)
                - max_pause_ms: Maximum pause (default: 700)
                - language_adjustments: Dict of language → pause adjustment
        """
        self.config = config or {}

        self.default_pause_ms = self.config.get("default_pause_ms", 350)
        self.min_pause_ms = self.config.get("min_pause_ms", 250)
        self.max_pause_ms = self.config.get("max_pause_ms", 700)

        self.language_adjustments = self.config.get("language_adjustments", {
            "en": 0,
            "hi": 50
        })

        self.question_type_adjustments = {
            "clarification": 50,
            "follow_up": 0,
            "standard": 0,
        }

        logger.info(
            f"[NaturalPauseManager] Initialized: "
            f"default={self.default_pause_ms}ms, "
            f"range=[{self.min_pause_ms}-{self.max_pause_ms}]ms"
        )

    def generate_pause_marker(self, duration_ms: int) -> str:
        """
        Generate pause marker for TTS pipeline.
        
        Format: SSML break tag compatible with most TTS engines
        - Standard: <break time="350ms"/>
        - Alternative: Can be parsed by TTS service
        
        Args:
            duration_ms: Pause duration in milliseconds
            
        Returns:
            SSML-formatted pause marker string
        """
        clamped_duration = max(self.min_pause_ms, min(duration_ms, self.max_pause_ms))

        if clamped_duration != duration_ms:
            logger.debug(
                f"[NaturalPauseManager] Pause duration {duration_ms}ms "
                f"out of range [{self.min_pause_ms}-{self.max_pause_ms}]ms, "
                f"clamped to {clamped_duration}ms"
            )

        pause_marker = f'<break time="{clamped_duration}ms"/>'

        logger.debug(f"[NaturalPauseManager] Generated pause marker: {pause_marker}")
        return pause_marker

    def calculate_pause_duration(
        self,
        answer_length: int,
        question_type: str = "standard",
        language: str = "en"
    ) -> int:
        """
        Calculate optimal pause duration based on answer length, question type, and language.
        
        Duration calculation formula:
        1. Base pause = 300ms (minimum realistic pause)
        2. Answer length modifier:
           - <100 chars: 250ms (short, don't pause much)
           - <500 chars: 350ms (standard pause)
           - <1000 chars: 400ms (longer answer, longer pause)
           - >=1000 chars: 500ms (very long, give processing time)
        3. Language modifier (from config):
           - English: 0ms (baseline)
           - Hindi: +50ms (more time to parse)
        4. Question type modifier:
           - clarification: +50ms
           - follow_up: 0ms
           - standard: 0ms
        
        Args:
            answer_length: Length of answer text in characters
            question_type: Type of question ("standard", "follow_up", "clarification")
            language: Language code ("en", "hi")  # ✅ FIX: Removed hinglish - only en or hi
            
        Returns:
            Pause duration in milliseconds (250-700ms range)
        """
        if answer_length < 100:
            base_pause = 250
        elif answer_length < 500:
            base_pause = 350
        elif answer_length < 1000:
            base_pause = 400
        else:
            base_pause = 500

        language_adjustment = self.language_adjustments.get(language.lower(), 0)

        question_adjustment = self.question_type_adjustments.get(
            question_type.lower(), 0
        )

        total_pause = base_pause + language_adjustment + question_adjustment

        final_pause = max(self.min_pause_ms, min(total_pause, self.max_pause_ms))

        logger.debug(
            f"[NaturalPauseManager] Calculated pause: "
            f"answer_len={answer_length}, "
            f"type={question_type}, "
            f"lang={language} → "
            f"base={base_pause}ms + "
            f"lang_adj={language_adjustment}ms + "
            f"type_adj={question_adjustment}ms = "
            f"{final_pause}ms"
        )

        return final_pause

    def insert_pauses(
        self,
        answer_text: str,
        question_text: str,
        language: str = "en",
        pause_ms: Optional[int] = None
    ) -> str:
        """
        Insert pause markers into response structure.
        
        Combines answer and question with a natural pause between them.
        
        Args:
            answer_text: KB-based answer text
            question_text: Qualification question text
            language: Language code for context
            pause_ms: Optional override pause duration (if None, calculated)
            
        Returns:
            Formatted response with pause marker: "{answer} {pause_marker} {question}"
        """
        if not answer_text or not question_text:
            logger.warning(
                f"[NaturalPauseManager] Missing text: "
                f"answer_empty={not answer_text}, "
                f"question_empty={not question_text}"
            )
            return answer_text or question_text or ""

        if pause_ms is None:
            pause_ms = self.calculate_pause_duration(
                len(answer_text),
                question_type="standard",
                language=language
            )

        pause_marker = self.generate_pause_marker(pause_ms)

        formatted_response = f"{answer_text} {pause_marker} {question_text}"

        logger.debug(
            f"[NaturalPauseManager] Inserted pause: "
            f"answer_len={len(answer_text)}, "
            f"pause={pause_ms}ms, "
            f"question_len={len(question_text)}"
        )

        return formatted_response

    def format_for_tts_streaming(
        self,
        answer_text: str,
        question_text: str,
        language: str = "en",
        pause_ms: Optional[int] = None
    ) -> str:
        """
        Format response with pauses for TTS streaming.
        
        Produces TTS-ready output compatible with streaming TTS services.
        
        This method:
        1. Inserts natural pause markers between answer and question
        2. Ensures SSML compatibility with TTS engine
        3. Returns formatted response ready for TTS pipeline
        
        Args:
            answer_text: KB-based answer
            question_text: Qualification question
            language: Language code for pause calculation
            pause_ms: Optional override pause duration
            
        Returns:
            TTS-ready formatted response with SSML pause markers
        """
        formatted = self.insert_pauses(
            answer_text=answer_text,
            question_text=question_text,
            language=language,
            pause_ms=pause_ms
        )

        logger.debug(
            f"[NaturalPauseManager] Formatted for TTS: "
            f"length={len(formatted)} chars, "
            f"language={language}, "
            f"has_pause_marker={'<break time=' in formatted}"
        )

        return formatted
