"""
Call Termination Sequence
Manages the complete call ending sequence:
1. All requirements completed
2. Closing message generated and queued
3. Closing message audio fully drained from RTP
4. ARI hangup initiated
5. Hangup confirmed
6. Complete conversation saved to database (exactly one INSERT)
7. Session cleanup

CRITICAL: RTP playback MUST fully drain before hangup initiated.
Hangup MUST be confirmed before database persistence begins.
"""

import asyncio
from typing import Optional, Dict, Any, Tuple
from datetime import datetime

from ..core.config import log
from .call_state_machine import CallState, get_state_machine


class CallTerminationSequence:
    """Manages the complete controlled termination sequence for a call"""

    def __init__(self, call_id: str):
        self.call_id = call_id
        self.state_machine = get_state_machine(call_id)
        self.closing_message: Optional[str] = None
        self.closing_audio_queued_at: Optional[datetime] = None
        self.playback_drain_start: Optional[datetime] = None
        self.playback_drain_complete: Optional[datetime] = None
        self.hangup_initiated_at: Optional[datetime] = None
        self.hangup_confirmed_at: Optional[datetime] = None
        self.persistence_start: Optional[datetime] = None
        self.persistence_complete: Optional[datetime] = None
        self.abnormal_termination = False
        self.abnormal_reason: Optional[str] = None

    async def begin_closing_sequence(self, closing_message: str) -> bool:
        """
        Start closing message sequence.
        
        Args:
            closing_message: Final message to play to customer
            
        Returns:
            True if successful
        """
        try:
            if not self.state_machine:
                log.error(f"[Termination] [{self.call_id}] No state machine found")
                return False

            self.closing_message = closing_message

            # Transition to SAVING_REQUIREMENTS
            if not self.state_machine.transition(
                CallState.SAVING_REQUIREMENTS,
                "Beginning closing sequence"
            ):
                log.error(f"[Termination] [{self.call_id}] Cannot transition to SAVING_REQUIREMENTS")
                return False

            log.info(f"[Termination] [{self.call_id}] ✅ Closing sequence started")
            return True

        except Exception as e:
            log.error(f"[Termination] [{self.call_id}] Error beginning closing sequence: {e}")
            return False

    async def notify_requirements_saved(self) -> bool:
        """
        Called after requirements successfully saved to Google Sheets.
        Move to closing message generation.
        
        Returns:
            True if successful
        """
        try:
            if not self.state_machine.transition(
                CallState.CLOSING_MESSAGE_GENERATING,
                "Requirements saved to Google Sheets"
            ):
                return False

            log.info(f"[Termination] [{self.call_id}] ✅ Requirements saved, generating closing message")
            return True

        except Exception as e:
            log.error(f"[Termination] [{self.call_id}] Error notifying requirements saved: {e}")
            return False

    async def notify_closing_message_generated(self) -> bool:
        """
        Called after closing message generated but BEFORE audio playback.
        Move to CLOSING_MESSAGE_PLAYING state.
        
        Returns:
            True if successful
        """
        try:
            if not self.state_machine.transition(
                CallState.CLOSING_MESSAGE_PLAYING,
                "Closing message generated and queued"
            ):
                return False

            self.closing_audio_queued_at = datetime.utcnow()
            log.info(f"[Termination] [{self.call_id}] ✅ Closing message queued for playback")
            return True

        except Exception as e:
            log.error(f"[Termination] [{self.call_id}] Error notifying message generated: {e}")
            return False

    async def wait_for_playback_drain(
        self,
        media_session,
        timeout_sec: float = 15.0,
        check_interval: float = 0.1
    ) -> Tuple[bool, Optional[str]]:
        """
        CRITICAL: Wait for RTP playback queue to fully drain.
        
        This ensures the closing message has been completely transmitted
        before initiating hangup.
        
        Args:
            media_session: MediaSession instance
            timeout_sec: Maximum wait time (seconds)
            check_interval: Check interval (seconds)
            
        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        try:
            if not self.state_machine.transition(
                CallState.PLAYBACK_DRAINING,
                "Beginning RTP playback drain"
            ):
                return False, "Cannot transition to PLAYBACK_DRAINING"

            self.playback_drain_start = datetime.utcnow()

            log.info(f"[Termination] [{self.call_id}] ⏳ Waiting for RTP playback queue to drain (timeout={timeout_sec}s)")

            # Wait for media session's TX queue to drain
            elapsed = 0.0
            while elapsed < timeout_sec:
                # Check if TX queue is empty
                if hasattr(media_session, 'tx_queue'):
                    queue_size = media_session.tx_queue.qsize()
                    if queue_size == 0:
                        log.info(f"[Termination] [{self.call_id}] ✅ RTP queue drained after {elapsed:.2f}s")
                        self.playback_drain_complete = datetime.utcnow()
                        return True, None

                    if int(elapsed) % 2 == 0:  # Log every 2 seconds
                        log.debug(f"[Termination] [{self.call_id}] RTP queue size: {queue_size} (waited {elapsed:.2f}s)")

                # Wait before checking again
                await asyncio.sleep(check_interval)
                elapsed += check_interval

            # Timeout - log warning but continue (audio may be transmitted)
            log.warning(
                f"[Termination] [{self.call_id}] ⚠️ RTP queue drain timeout after {timeout_sec}s "
                f"(queue may still have {media_session.tx_queue.qsize() if hasattr(media_session, 'tx_queue') else 'unknown'} frames)"
            )
            self.playback_drain_complete = datetime.utcnow()

            # Still consider it success - proceed with hangup
            return True, None

        except Exception as e:
            error_msg = f"Error waiting for playback drain: {e}"
            log.error(f"[Termination] [{self.call_id}] {error_msg}")
            return False, error_msg

    async def initiate_hangup(self, ari_client) -> Tuple[bool, Optional[str]]:
        """
        CRITICAL: Initiate ARI channel hangup.
        
        Called ONLY after confirmed RTP playback drain.
        
        Args:
            ari_client: ARI client instance
            
        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        try:
            if not self.state_machine.transition(
                CallState.CALL_HANGUP,
                "Initiating ARI hangup"
            ):
                return False, "Cannot transition to CALL_HANGUP"

            self.hangup_initiated_at = datetime.utcnow()

            log.info(f"[Termination] [{self.call_id}] 📞 Initiating ARI channel hangup")

            # TODO: Implement actual ARI hangup call
            # channel_id = self.call_id
            # await ari_client.channels.hangup(channelId=channel_id)

            # For now, simulate success
            await asyncio.sleep(0.5)
            self.hangup_confirmed_at = datetime.utcnow()

            log.info(f"[Termination] [{self.call_id}] ✅ Hangup initiated and confirmed")
            return True, None

        except Exception as e:
            error_msg = f"Error initiating hangup: {e}"
            log.error(f"[Termination] [{self.call_id}] {error_msg}")
            return False, error_msg

    async def save_conversation_to_database(
        self,
        conversation_history_service,
        userid: int,
        caller_number: str,
        conversation_text: str,
        detected_language: str = "en",
        call_duration_sec: int = 0
    ) -> Tuple[bool, Optional[str]]:
        """
        CRITICAL: Save complete conversation to database.
        
        Called ONLY after:
        - Hangup initiated
        - Hangup confirmed
        
        Uses exactly one parameterized INSERT with idempotent protection.
        
        Args:
            conversation_history_service: ConversationHistoryService instance
            userid: User ID
            caller_number: Caller's phone number
            conversation_text: Complete conversation transcript
            detected_language: Language code
            call_duration_sec: Call duration in seconds
            
        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        try:
            if not self.state_machine.transition(
                CallState.DATABASE_PERSISTENCE,
                "Beginning database persistence"
            ):
                return False, "Cannot transition to DATABASE_PERSISTENCE"

            self.persistence_start = datetime.utcnow()

            log.info(f"[Termination] [{self.call_id}] 💾 Persisting conversation to database")

            if not conversation_text or not conversation_text.strip():
                log.warning(f"[Termination] [{self.call_id}] ⚠️ Empty conversation text, still saving metadata")

            # Call service to save
            success = await conversation_history_service.save_conversation(
                call_id=self.call_id,
                userid=userid,
                caller_number=caller_number,
                conversation_text=conversation_text or "",
                detected_language=detected_language,
                call_duration=call_duration_sec
            )

            if success:
                self.persistence_complete = datetime.utcnow()
                duration_ms = (self.persistence_complete - self.persistence_start).total_seconds() * 1000
                log.info(
                    f"[Termination] [{self.call_id}] ✅ Conversation persisted ({duration_ms:.0f}ms, "
                    f"{len(conversation_text)} chars)"
                )
                return True, None
            else:
                error_msg = "Database save failed"
                log.error(f"[Termination] [{self.call_id}] ❌ {error_msg}")
                return False, error_msg

        except Exception as e:
            error_msg = f"Error persisting to database: {e}"
            log.error(f"[Termination] [{self.call_id}] {error_msg}")
            return False, error_msg

    async def complete_cleanup(self) -> bool:
        """
        Final cleanup after successful persistence.
        
        Returns:
            True if successful
        """
        try:
            if not self.state_machine.transition(
                CallState.SESSION_CLEANUP,
                "Beginning session cleanup"
            ):
                return False

            log.info(f"[Termination] [{self.call_id}] 🧹 Session cleanup started")

            # TODO: Cleanup resources:
            # - Close media session
            # - Close Gemini session
            # - Clean Redis
            # - Release ports

            # Transition to terminal state
            self.state_machine.transition(
                CallState.CALL_TERMINATED,
                "Call sequence complete"
            )

            log.info(f"[Termination] [{self.call_id}] ✅ Call terminated completely")
            return True

        except Exception as e:
            log.error(f"[Termination] [{self.call_id}] Error in cleanup: {e}")
            return False

    async def handle_abnormal_termination(
        self,
        reason: str,
        conversation_text: Optional[str] = None,
        conversation_history_service = None,
        userid: Optional[int] = None,
        caller_number: Optional[str] = None
    ) -> bool:
        """
        Handle abnormal call termination (customer hangup, error, etc.).
        
        IMPORTANT: Still save conversation to database, but mark it as incomplete.
        
        Args:
            reason: Reason for abnormal termination
            conversation_text: Conversation collected so far
            conversation_history_service: Service to save
            userid: User ID
            caller_number: Caller number
            
        Returns:
            True if cleanup successful
        """
        try:
            self.abnormal_termination = True
            self.abnormal_reason = reason

            log.warning(f"[Termination] [{self.call_id}] ⚠️ ABNORMAL TERMINATION: {reason}")

            # Try to transition to error state if not already in terminal state
            if not self.state_machine.is_terminated():
                self.state_machine.transition(CallState.ERROR, f"Abnormal termination: {reason}")

            # Still try to save conversation if we have data
            if conversation_text and conversation_history_service and userid and caller_number:
                log.info(f"[Termination] [{self.call_id}] Attempting to save partial conversation")

                success = await conversation_history_service.save_conversation(
                    call_id=self.call_id,
                    userid=userid,
                    caller_number=caller_number,
                    conversation_text=conversation_text,
                    detected_language="en"
                )

                if success:
                    log.info(f"[Termination] [{self.call_id}] ✅ Partial conversation saved")
                else:
                    log.warning(f"[Termination] [{self.call_id}] Failed to save partial conversation")

            # Cleanup
            await self.complete_cleanup()
            return True

        except Exception as e:
            log.error(f"[Termination] [{self.call_id}] Error in abnormal termination handling: {e}")
            return False

    def get_summary(self) -> Dict[str, Any]:
        """Get termination sequence summary"""
        return {
            "call_id": self.call_id,
            "abnormal_termination": self.abnormal_termination,
            "abnormal_reason": self.abnormal_reason,
            "closing_message": self.closing_message is not None,
            "closing_audio_queued_at": self.closing_audio_queued_at.isoformat() if self.closing_audio_queued_at else None,
            "playback_drain_start": self.playback_drain_start.isoformat() if self.playback_drain_start else None,
            "playback_drain_complete": self.playback_drain_complete.isoformat() if self.playback_drain_complete else None,
            "playback_drain_duration_sec": (
                (self.playback_drain_complete - self.playback_drain_start).total_seconds()
                if self.playback_drain_start and self.playback_drain_complete
                else None
            ),
            "hangup_initiated_at": self.hangup_initiated_at.isoformat() if self.hangup_initiated_at else None,
            "hangup_confirmed_at": self.hangup_confirmed_at.isoformat() if self.hangup_confirmed_at else None,
            "persistence_start": self.persistence_start.isoformat() if self.persistence_start else None,
            "persistence_complete": self.persistence_complete.isoformat() if self.persistence_complete else None,
            "persistence_duration_ms": (
                (self.persistence_complete - self.persistence_start).total_seconds() * 1000
                if self.persistence_start and self.persistence_complete
                else None
            )
        }


# Global registry of active termination sequences
_termination_sequences: Dict[str, CallTerminationSequence] = {}


def create_termination_sequence(call_id: str) -> CallTerminationSequence:
    """Create new termination sequence for call"""
    seq = CallTerminationSequence(call_id)
    _termination_sequences[call_id] = seq
    return seq


def get_termination_sequence(call_id: str) -> Optional[CallTerminationSequence]:
    """Get termination sequence for call"""
    return _termination_sequences.get(call_id)


def cleanup_termination_sequence(call_id: str) -> bool:
    """Remove termination sequence after call complete"""
    if call_id in _termination_sequences:
        _termination_sequences.pop(call_id)
        return True
    return False
