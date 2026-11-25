"""
Language Processing Service
Handles language detection, translation, and NLP operations
"""

import re
from typing import Optional, Dict, Tuple

from ..core.config import log

class LanguageService:
    """Language processing service"""

    def __init__(self):
        self.hindi_pattern = re.compile(r'[\u0900-\u097F]')
        self.english_pattern = re.compile(r'[a-zA-Z]')
        self.gujarati_pattern = re.compile(r'[\u0A80-\u0AFF]')
        self.devanagari_pattern = re.compile(r'[\u0900-\u097F]')

    def detect_language(self, text: str) -> str:
        """
        Detect language of the text
        Returns: "en" (English), "hi" (Hindi), "gu" (Gujarati), or "hinglish" (Hindi + English mix)
        """
        try:
            if not text:
                return "en"

            hindi_count = len(self.hindi_pattern.findall(text))
            gujarati_count = len(self.gujarati_pattern.findall(text))
            english_count = len(self.english_pattern.findall(text))

            total_chars = hindi_count + gujarati_count + english_count

            if total_chars == 0:
                return "en"

            hindi_ratio = hindi_count / total_chars
            gujarati_ratio = gujarati_count / total_chars
            english_ratio = english_count / total_chars

            if gujarati_ratio > 0.5:
                log.debug(f"[Language] Detected Gujarati: Gujarati={gujarati_ratio:.1%}")
                return "gu"

            if hindi_ratio > 0.2 and english_ratio > 0.2 and gujarati_ratio < 0.1:
                log.debug(f"[Language] Detected Hinglish: Hindi={hindi_ratio:.1%}, English={english_ratio:.1%}")
                return "hinglish"

            if hindi_ratio > english_ratio and hindi_ratio > gujarati_ratio:
                log.debug(f"[Language] Detected Hindi: Hindi={hindi_ratio:.1%}")
                return "hi"

            log.debug(f"[Language] Detected English: English={english_ratio:.1%}")
            return "en"

        except Exception as e:
            log.error(f"[Language] Detection error: {e}")
            return "en"

    def normalize_text(self, text: str) -> str:
        """Normalize text for processing"""
        try:
            if not text:
                return ""

            text = re.sub(r'\s+', ' ', text)
            text = re.sub(r'[^\w\s]', '', text)
            text = text.lower().strip()

            return text
        except Exception as e:
            log.error(f"[Language] Normalization error: {e}")
            return text

    def extract_entities(self, text: str) -> Dict[str, str]:
        """Extract entities from text"""
        try:
            entities = {
                "numbers": [],
                "names": [],
                "special_terms": [],
            }

            numbers = re.findall(r'\b\d+\b', text)
            if numbers:
                entities["numbers"] = numbers

            return entities
        except Exception as e:
            log.error(f"[Language] Entity extraction error: {e}")
            return {}

_language_service: Optional[LanguageService] = None

def init_language_service():
    """Initialize language service"""
    global _language_service
    _language_service = LanguageService()
    log.info("[LanguageService] Initialized")
    return _language_service

def get_language_service() -> Optional[LanguageService]:
    """Get language service instance"""
    return _language_service
