"""
Conversation Capture Service
Tracks all AI and customer messages in strict sequence for complete conversation history.
Prevents duplicates from Gemini streaming, RTP callbacks, and retries.
Maintains per-call conversation state with sequence numbers and timestamps.
"""

import json
from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum

from ..core.config import log


class MessageType(str, Enum):
    """Message type classifications"""
    GREETING = "greeting"
    QUESTION = "question"
    CUSTOMER_RESPONSE = "customer_response"
    AI_ACKNOWLEDGEMENT = "ai_acknowledgement"
    CLARIFICATION = "clarification"
    REPEATED_QUESTION = "repeated_question"
    CUSTOMER_CORRECTION = "customer_correction"
    CLOSING = "closing"
    SYSTEM_MESSAGE = "system_message"


class ConversationEntry:
    """Immutable conversation message entry with deduplication key"""

    def __init__(
        self,
        speaker: str,  # "AI" or "CUSTOMER"
        message: str,
        message_type: MessageType,
        timestamp: Optional[datetime] = None,
        sequence_number: Optional[int] = None,
        field_name: Optional[str] = None,
        dedup_key: Optional[str] = None
    ):
        self.speaker = speaker.upper()
        self.message = message.strip() if message else ""
        self.message_type = message_type
        self.timestamp = timestamp or datetime.utcnow()
        self.sequence_number = sequence_number
        self.field_name = field_name
        # Dedup key: speaker+type+message hash to prevent exact duplicates
        self.dedup_key = dedup_key or f"{self.speaker}|{self.message_type}|{hash(self.message) % 999999}"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            "speaker": self.speaker,
            "message": self.message,
            "message_type": self.message_type.value,
            "timestamp": self.timestamp.isoformat(),
            "sequence_number": self.sequence_number,
            "field_name": self.field_name
        }

    def to_text_line(self) -> str:
        """Format as single text line for transcript"""
        return f"{self.speaker}: {self.message}"


class ConversationCaptureService:
    """
    Service to capture complete conversation history per call.
    
    Responsibilities:
    - Track all AI and customer messages in strict order
    - Assign sequence numbers starting from 1
    - Prevent duplicates from streaming/retry events
    - Provide complete ordered transcript
    - Support conversation snapshots for safe persistence
    """

    def __init__(self):
        # Per-call conversation state: call_id -> ConversationState
        self.conversations: Dict[str, "ConversationState"] = {}

    def create_conversation(self, call_id: str) -> "ConversationState":
        """Create new conversation tracking for a call"""
        if call_id in self.conversations:
            log.warning(f"[ConvCapture] Conversation already exists for {call_id}, resetting")
            self.conversations[call_id] = ConversationState(call_id)
        else:
            self.conversations[call_id] = ConversationState(call_id)
            log.info(f"[ConvCapture] Created conversation: {call_id}")

        return self.conversations[call_id]

    def get_conversation(self, call_id: str) -> Optional["ConversationState"]:
        """Get conversation state for a call"""
        return self.conversations.get(call_id)

    def add_message(
        self,
        call_id: str,
        speaker: str,
        message: str,
        message_type: MessageType,
        field_name: Optional[str] = None,
        dedup_key: Optional[str] = None
    ) -> bool:
        """
        Add a message to conversation with duplicate prevention.
        
        Args:
            call_id: Call identifier
            speaker: "AI" or "CUSTOMER"
            message: Message text
            message_type: Type classification
            field_name: Requirement field if applicable
            dedup_key: Custom deduplication key
            
        Returns:
            True if added, False if duplicate or error
        """
        try:
            # Skip empty messages
            if not message or not message.strip():
                log.debug(f"[ConvCapture] Skipping empty message for {call_id}")
                return False

            conv = self.get_conversation(call_id)
            if not conv:
                log.warning(f"[ConvCapture] No conversation for {call_id}, creating")
                conv = self.create_conversation(call_id)

            entry = ConversationEntry(
                speaker=speaker,
                message=message,
                message_type=message_type,
                field_name=field_name,
                dedup_key=dedup_key
            )

            # Check for exact duplicate
            if conv.has_duplicate(entry):
                log.debug(f"[ConvCapture] Duplicate message detected, skipping: {entry.dedup_key}")
                return False

            # Add message with sequence number
            seq_num = len(conv.entries) + 1
            entry.sequence_number = seq_num

            conv.entries.append(entry)

            log.info(
                f"[ConvCapture] [{call_id}] Message #{seq_num}: {speaker} ({message_type.value}) - "
                f"{len(entry.message)} chars"
            )

            return True

        except Exception as e:
            log.error(f"[ConvCapture] Error adding message: {e}")
            return False

    def get_full_transcript(self, call_id: str, as_text: bool = True) -> Optional[str]:
        """
        Get complete ordered conversation transcript.
        
        Args:
            call_id: Call identifier
            as_text: If True, return as newline-separated text; if False, return as JSON
            
        Returns:
            Transcript string or None
        """
        conv = self.get_conversation(call_id)
        if not conv or not conv.entries:
            return None

        if as_text:
            lines = [entry.to_text_line() for entry in conv.entries]
            return "\n".join(lines)
        else:
            # Return as JSON array
            entries = [entry.to_dict() for entry in conv.entries]
            return json.dumps(entries, indent=2)

    def get_entries_list(self, call_id: str) -> List[Dict[str, Any]]:
        """Get conversation entries as list of dictionaries"""
        conv = self.get_conversation(call_id)
        if not conv:
            return []

        return [entry.to_dict() for entry in conv.entries]

    def take_snapshot(self, call_id: str) -> Optional[Dict[str, Any]]:
        """
        Take immutable snapshot of conversation for safe persistence.
        Called before database insert to freeze state.
        
        Args:
            call_id: Call identifier
            
        Returns:
            Snapshot dict with frozen conversation state
        """
        conv = self.get_conversation(call_id)
        if not conv:
            return None

        snapshot = {
            "call_id": call_id,
            "timestamp_taken": datetime.utcnow().isoformat(),
            "total_messages": len(conv.entries),
            "entries": [entry.to_dict() for entry in conv.entries]
        }

        log.info(f"[ConvCapture] Snapshot taken for {call_id}: {len(conv.entries)} messages")
        return snapshot

    def cleanup_conversation(self, call_id: str) -> bool:
        """Remove conversation from memory after safe persistence"""
        if call_id in self.conversations:
            self.conversations.pop(call_id)
            log.info(f"[ConvCapture] Conversation cleaned up: {call_id}")
            return True
        return False

    def get_stats(self, call_id: str) -> Optional[Dict[str, Any]]:
        """Get conversation statistics"""
        conv = self.get_conversation(call_id)
        if not conv:
            return None

        ai_count = sum(1 for e in conv.entries if e.speaker == "AI")
        customer_count = sum(1 for e in conv.entries if e.speaker == "CUSTOMER")

        message_types = {}
        for entry in conv.entries:
            msg_type = entry.message_type.value
            message_types[msg_type] = message_types.get(msg_type, 0) + 1

        return {
            "call_id": call_id,
            "total_messages": len(conv.entries),
            "ai_messages": ai_count,
            "customer_messages": customer_count,
            "message_types": message_types,
            "has_greeting": any(e.message_type == MessageType.GREETING for e in conv.entries),
            "has_closing": any(e.message_type == MessageType.CLOSING for e in conv.entries)
        }


class ConversationState:
    """Mutable conversation state for a single call during active session"""

    def __init__(self, call_id: str):
        self.call_id = call_id
        self.entries: List[ConversationEntry] = []
        self.dedup_set: set = set()  # Dedup keys of all entries
        self.created_at = datetime.utcnow()

    def has_duplicate(self, entry: ConversationEntry) -> bool:
        """Check if entry with same dedup key already exists"""
        return entry.dedup_key in self.dedup_set

    def add_entry(self, entry: ConversationEntry) -> bool:
        """Add entry if not duplicate"""
        if self.has_duplicate(entry):
            return False

        self.entries.append(entry)
        self.dedup_set.add(entry.dedup_key)
        return True

    def get_message_count(self) -> int:
        """Total messages"""
        return len(self.entries)

    def get_ai_count(self) -> int:
        """Count AI messages"""
        return sum(1 for e in self.entries if e.speaker == "AI")

    def get_customer_count(self) -> int:
        """Count customer messages"""
        return sum(1 for e in self.entries if e.speaker == "CUSTOMER")


# Global singleton instance
_capture_service: Optional[ConversationCaptureService] = None


async def init_conversation_capture_service() -> ConversationCaptureService:
    """Initialize conversation capture service"""
    global _capture_service
    _capture_service = ConversationCaptureService()
    log.info("[ConvCapture] Service initialized")
    return _capture_service


def get_conversation_capture_service() -> Optional[ConversationCaptureService]:
    """Get conversation capture service instance"""
    global _capture_service
    if not _capture_service:
        _capture_service = ConversationCaptureService()
    return _capture_service
