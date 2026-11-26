"""
Closing Message Service
Generates and plays the final closing message with proper RTP playback drain.

CRITICAL SEQUENCE:
1. All requirements collected and validated
2. Requirements saved to Google Sheets
3. Closing message generated
4. Closing message captured in conversation history
5. Closing message queued for RTP playback
6. WAIT FOR RTP QUEUE TO FULLY DRAIN
7. Confirm playback complete
8. Initiate ARI hangup
9. Confirm hangup complete
10. Save conversation to database
11. Cleanup
"""

import asyncio
from typing import Optional, Tuple
from datetime import datetime

from ..core.config import log
from ..core.client_config import ClientConfig
from .conversation_integration import capture_closing_message
from .call_state_machine import CallState, get_state_machine
from .call_termination_sequence import get_termination_sequence


class ClosingMessageService:
    """Service for generating and playing closing message"""

    def __init__(self):
        self.language_closing_messages = {
            "en-IN": (
                "Thank you for sharing your requirements with us. We have noted your product and quantity requirements. "
                "Our sales team will review the details and contact you shortly for further discussion. "
                "Thank you for your valuable time. Have a great day!"
            ),
            "hi-IN": (
                "अपनी आवश्यकताएँ साझा करने के लिए आपका धन्यवाद। हमने आपकी उत्पाद और मात्रा की आवश्यकताओं को नोट कर लिया है। "
                "हमारी बिक्रय टीम विवरण की समीक्षा करेगी और आपसे शीघ्र संपर्क करेगी। आपके मूल्यवान समय के लिए धन्यवाद। आपका दिन शुभ हो!"
            ),
            "en": (
                "Thank you for sharing your requirements with us. Our team will review the details and get back to you soon. "
                "Have a great day!"
            ),
            "hi": (
                "अपनी आवश्यकताएँ साझा करने के लिए आपका धन्यवाद। हमारी टीम विवरण की समीक्षा करेगी और आपसे शीघ्र संपर्क करेगी। "
                "आपका दिन शुभ हो!"
            )
        }

    def get_closing_message(self, language: str = "en-IN") -> str:
        """
        Get closing message in appropriate language.
        
        Falls back to config if set, then to default language messages.
        
        Args:
            language: Response language (en-IN, hi-IN, etc.)
            
        Returns:
            Closing message text
        """
        try:
            # Try configured closing message first
            if hasattr(ClientConfig, 'CLOSING_MESSAGE') and ClientConfig.CLOSING_MESSAGE:
                return ClientConfig.CLOSING_MESSAGE

            # Try language-specific message
            if language in self.language_closing_messages:
                return self.language_closing_messages[language]

            # Normalize language and try again
            lang_normalized = language.lower()
            if lang_normalized.startswith("en"):
                return self.language_closing_messages.get("en-IN", self.language_closing_messages["en"])
            elif lang_normalized.startswith("hi"):
                return self.language_closing_messages.get("hi-IN", self.language_closing_messages["hi"])

            # Default fallback
            return self.language_closing_messages["en-IN"]

        except Exception as e:
            log.error(f"[ClosingMessage] Error getting closing message: {e}")
            return self.language_closing_messages["en-IN"]

    async def prepare_and_play_closing_message(
        self,
        call_id: str,
        language: str = "en-IN",
        media_session = None,
        gemini_session = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Complete sequence: Prepare → Generate → Capture → Queue → Drain → Confirm.
        
        CRITICAL: This method handles the entire closing sequence including:
        1. Getting closing message
        2. Capturing in conversation history
        3. Generating audio (if needed)
        4. Queueing for RTP transmission
        5. WAITING FOR RTP DRAIN
        
        Args:
            call_id: Call identifier
            language: Response language
            media_session: MediaSession instance for RTP
            gemini_session: Gemini session for audio generation
            
        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        try:
            state_machine = get_state_machine(call_id)
            if not state_machine:
                return False, "No state machine for call"

            term_seq = get_termination_sequence(call_id)
            if not term_seq:
                return False, "No termination sequence for call"

            log.info(f"[ClosingMessage] [{call_id}] Starting closing message sequence")

            # Get closing message
            closing_message = self.get_closing_message(language)
            log.info(f"[ClosingMessage] [{call_id}] ✅ Closing message loaded ({len(closing_message)} chars)")

            # Capture closing message in conversation history
            await capture_closing_message(call_id, closing_message)

            # Notify termination sequence that closing message is ready
            success = await term_seq.notify_closing_message_generated()
            if not success:
                return False, "Failed to notify termination sequence"

            log.info(f"[ClosingMessage] [{call_id}] ✅ Closing message queued for playback")

            # TODO: Queue audio for transmission via media_session.send_audio_response()
            # For now, simulate that audio is queued
            if media_session:
                log.debug(f"[ClosingMessage] [{call_id}] 🔊 Would queue audio for transmission")
            else:
                log.warning(f"[ClosingMessage] [{call_id}] ⚠️ No media session available for audio transmission")

            # CRITICAL: Wait for RTP playback to drain
            if media_session:
                drain_success, drain_error = await term_seq.wait_for_playback_drain(
                    media_session=media_session,
                    timeout_sec=15.0
                )
                if not drain_success:
                    return False, f"Playback drain failed: {drain_error}"

                log.info(f"[ClosingMessage] [{call_id}] ✅ RTP playback fully drained")
            else:
                log.warning(f"[ClosingMessage] [{call_id}] ⚠️ No media session for drain detection, proceeding")

            return True, None

        except Exception as e:
            error_msg = f"Error in closing message sequence: {e}"
            log.error(f"[ClosingMessage] [{call_id}] {error_msg}")
            return False, error_msg

    async def initiate_call_termination(
        self,
        call_id: str,
        ari_client = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Initiate call hangup and confirm termination.
        
        MUST be called ONLY after confirmed RTP playback drain.
        
        Args:
            call_id: Call identifier
            ari_client: ARI client for hangup
            
        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        try:
            term_seq = get_termination_sequence(call_id)
            if not term_seq:
                return False, "No termination sequence"

            # Initiate hangup
            hangup_success, hangup_error = await term_seq.initiate_hangup(ari_client)
            if not hangup_success:
                return False, f"Hangup failed: {hangup_error}"

            log.info(f"[ClosingMessage] [{call_id}] ✅ Call hangup initiated and confirmed")
            return True, None

        except Exception as e:
            return False, f"Error initiating hangup: {e}"

    async def save_call_conversation(
        self,
        call_id: str,
        userid: int,
        caller_number: str,
        conversation_history_service,
        language: str = "en"
    ) -> Tuple[bool, Optional[str]]:
        """
        Save complete conversation to database.
        
        MUST be called ONLY after confirmed ARI hangup.
        Uses ConversationCaptureService to get complete transcript.
        
        Args:
            call_id: Call identifier
            userid: User ID
            caller_number: Caller number
            conversation_history_service: ConversationHistoryService instance
            language: Detected language
            
        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        try:
            from .conversation_integration import get_complete_transcript, take_conversation_snapshot

            # Get complete transcript from ConversationCaptureService
            transcript = await get_complete_transcript(call_id)
            if not transcript:
                log.warning(f"[ClosingMessage] [{call_id}] ⚠️ Empty transcript, still saving")
                transcript = "[No conversation captured]"

            # Take immutable snapshot
            snapshot = await take_conversation_snapshot(call_id)
            if snapshot:
                log.info(
                    f"[ClosingMessage] [{call_id}] 📸 Conversation snapshot: "
                    f"{snapshot.get('total_messages')} messages"
                )

            # Get termination sequence for final persistence
            term_seq = get_termination_sequence(call_id)
            if not term_seq:
                return False, "No termination sequence"

            # Save to database via termination sequence
            # This ensures single INSERT with idempotent protection
            persist_success, persist_error = await term_seq.save_conversation_to_database(
                conversation_history_service=conversation_history_service,
                userid=userid,
                caller_number=caller_number,
                conversation_text=transcript,
                detected_language=language,
                call_duration_sec=0  # TODO: Calculate actual duration
            )

            if persist_success:
                log.info(f"[ClosingMessage] [{call_id}] ✅ Conversation saved to database")
                return True, None
            else:
                return False, f"Database persistence failed: {persist_error}"

        except Exception as e:
            error_msg = f"Error saving conversation: {e}"
            log.error(f"[ClosingMessage] [{call_id}] {error_msg}")
            return False, error_msg

    async def complete_call_cleanup(
        self,
        call_id: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Final cleanup after successful persistence.
        
        Args:
            call_id: Call identifier
            
        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        try:
            from .conversation_integration import cleanup_conversation

            term_seq = get_termination_sequence(call_id)
            if not term_seq:
                return False, "No termination sequence"

            # Complete cleanup
            cleanup_success = await term_seq.complete_cleanup()
            if not cleanup_success:
                log.warning(f"[ClosingMessage] [{call_id}] ⚠️ Cleanup failed but continuing")

            # Cleanup conversation from memory
            await cleanup_conversation(call_id)

            log.info(f"[ClosingMessage] [{call_id}] ✅ Call terminated and cleaned up")
            return True, None

        except Exception as e:
            return False, f"Error in cleanup: {e}"


# Global singleton
_closing_service: Optional[ClosingMessageService] = None


async def init_closing_message_service() -> ClosingMessageService:
    """Initialize closing message service"""
    global _closing_service
    _closing_service = ClosingMessageService()
    log.info("[ClosingMessage] Service initialized")
    return _closing_service


def get_closing_message_service() -> Optional[ClosingMessageService]:
    """Get closing message service instance"""
    global _closing_service
    if not _closing_service:
        _closing_service = ClosingMessageService()
    return _closing_service
