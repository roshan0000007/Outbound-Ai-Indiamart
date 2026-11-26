"""
Conversation Integration Helpers
Provides convenient methods to capture messages from various parts of the system.
Used by greeting_service, live_call_handler, requirement_tools_service, etc.
"""

from typing import Optional
from datetime import datetime

from ..core.config import log
from .conversation_capture_service import (
    get_conversation_capture_service,
    MessageType
)


async def capture_ai_greeting(call_id: str, greeting_text: str) -> bool:
    """
    Capture AI greeting message.
    Called from greeting_service after greeting is generated.
    
    Args:
        call_id: Call identifier
        greeting_text: Full greeting text
        
    Returns:
        True if captured
    """
    try:
        service = get_conversation_capture_service()
        if not service:
            log.warning(f"[ConvIntegration] Conversation capture service not available")
            return False

        success = service.add_message(
            call_id=call_id,
            speaker="AI",
            message=greeting_text,
            message_type=MessageType.GREETING
        )

        if success:
            log.debug(f"[ConvIntegration] ✅ Greeting captured for {call_id}")
        else:
            log.debug(f"[ConvIntegration] Greeting already captured (duplicate) for {call_id}")

        return success

    except Exception as e:
        log.error(f"[ConvIntegration] Error capturing greeting: {e}")
        return False


async def capture_requirement_question(
    call_id: str,
    question_text: str,
    field_name: str
) -> bool:
    """
    Capture requirement collection question.
    Called from requirement_tools_service before question is played.
    
    Args:
        call_id: Call identifier
        question_text: Full question text
        field_name: Field being asked (customer_name, company_name, etc.)
        
    Returns:
        True if captured
    """
    try:
        service = get_conversation_capture_service()
        if not service:
            return False

        success = service.add_message(
            call_id=call_id,
            speaker="AI",
            message=question_text,
            message_type=MessageType.QUESTION,
            field_name=field_name
        )

        if success:
            log.debug(f"[ConvIntegration] ✅ Question captured for {field_name}")

        return success

    except Exception as e:
        log.error(f"[ConvIntegration] Error capturing question: {e}")
        return False


async def capture_customer_response(
    call_id: str,
    response_text: str,
    field_name: Optional[str] = None,
    confidence: float = 1.0,
    is_valid: bool = True
) -> bool:
    """
    Capture customer's recognized response.
    Called from live_call_handler after STT recognition and validation.
    
    Args:
        call_id: Call identifier
        response_text: Recognized response text
        field_name: Requirement field if applicable
        confidence: Recognition confidence (0.0-1.0)
        is_valid: Whether response was valid for current question
        
    Returns:
        True if captured
    """
    try:
        service = get_conversation_capture_service()
        if not service:
            return False

        success = service.add_message(
            call_id=call_id,
            speaker="CUSTOMER",
            message=response_text,
            message_type=MessageType.CUSTOMER_RESPONSE,
            field_name=field_name,
            dedup_key=f"CUSTOMER|RESPONSE|{field_name}|{hash(response_text) % 999999}"
        )

        if success:
            log.debug(
                f"[ConvIntegration] ✅ Customer response captured: {len(response_text)} chars, "
                f"valid={is_valid}, confidence={confidence:.2f}"
            )

        return success

    except Exception as e:
        log.error(f"[ConvIntegration] Error capturing customer response: {e}")
        return False


async def capture_ai_acknowledgement(
    call_id: str,
    acknowledgement_text: str,
    field_name: Optional[str] = None
) -> bool:
    """
    Capture AI acknowledgement/validation message.
    Called from requirement_tools_service after validating response.
    
    Examples:
    - "Thank you, Rahul."
    - "ABC Enterprises, got it."
    - "10,000 units, understood."
    
    Args:
        call_id: Call identifier
        acknowledgement_text: Acknowledgement text
        field_name: Field that was acknowledged
        
    Returns:
        True if captured
    """
    try:
        service = get_conversation_capture_service()
        if not service:
            return False

        success = service.add_message(
            call_id=call_id,
            speaker="AI",
            message=acknowledgement_text,
            message_type=MessageType.AI_ACKNOWLEDGEMENT,
            field_name=field_name
        )

        if success:
            log.debug(f"[ConvIntegration] ✅ AI acknowledgement captured")

        return success

    except Exception as e:
        log.error(f"[ConvIntegration] Error capturing acknowledgement: {e}")
        return False


async def capture_clarification_question(
    call_id: str,
    clarification_text: str,
    field_name: str,
    attempt_number: int = 1
) -> bool:
    """
    Capture clarification question when response is unclear.
    Called from requirement_tools_service when validation fails.
    
    Examples:
    - "I'm sorry, I didn't quite catch that. Could you please repeat your name?"
    - "Could you clarify - did you say 5,000 or 50,000 units?"
    
    Args:
        call_id: Call identifier
        clarification_text: Clarification question text
        field_name: Field needing clarification
        attempt_number: Which attempt (1st, 2nd, 3rd)
        
    Returns:
        True if captured
    """
    try:
        service = get_conversation_capture_service()
        if not service:
            return False

        success = service.add_message(
            call_id=call_id,
            speaker="AI",
            message=clarification_text,
            message_type=MessageType.CLARIFICATION,
            field_name=field_name,
            dedup_key=f"AI|CLARIFICATION|{field_name}|attempt{attempt_number}|{hash(clarification_text) % 999999}"
        )

        if success:
            log.debug(f"[ConvIntegration] ✅ Clarification question captured (attempt {attempt_number})")

        return success

    except Exception as e:
        log.error(f"[ConvIntegration] Error capturing clarification: {e}")
        return False


async def capture_customer_correction(
    call_id: str,
    correction_text: str,
    field_name: str,
    previous_value: str
) -> bool:
    """
    Capture customer's correction/clarification when they correct themselves.
    
    Examples:
    - "Actually, I said 5,000, not 50,000"
    - "No, the company name is XYZ Limited, not ABC"
    
    Args:
        call_id: Call identifier
        correction_text: Correction message
        field_name: Field being corrected
        previous_value: What they said before
        
    Returns:
        True if captured
    """
    try:
        service = get_conversation_capture_service()
        if not service:
            return False

        success = service.add_message(
            call_id=call_id,
            speaker="CUSTOMER",
            message=correction_text,
            message_type=MessageType.CUSTOMER_CORRECTION,
            field_name=field_name
        )

        if success:
            log.debug(
                f"[ConvIntegration] ✅ Customer correction captured for {field_name}: "
                f"'{previous_value}' → '{correction_text}'"
            )

        return success

    except Exception as e:
        log.error(f"[ConvIntegration] Error capturing correction: {e}")
        return False


async def capture_closing_message(
    call_id: str,
    closing_text: str
) -> bool:
    """
    Capture final closing message.
    Called from closing service after message is generated.
    
    Args:
        call_id: Call identifier
        closing_text: Closing message
        
    Returns:
        True if captured
    """
    try:
        service = get_conversation_capture_service()
        if not service:
            return False

        success = service.add_message(
            call_id=call_id,
            speaker="AI",
            message=closing_text,
            message_type=MessageType.CLOSING
        )

        if success:
            log.debug(f"[ConvIntegration] ✅ Closing message captured")

        return success

    except Exception as e:
        log.error(f"[ConvIntegration] Error capturing closing message: {e}")
        return False


async def get_complete_transcript(call_id: str) -> str:
    """
    Get complete ordered conversation transcript.
    
    Args:
        call_id: Call identifier
        
    Returns:
        Complete conversation as newline-separated text
    """
    try:
        service = get_conversation_capture_service()
        if not service:
            return ""

        transcript = service.get_full_transcript(call_id, as_text=True)
        return transcript or ""

    except Exception as e:
        log.error(f"[ConvIntegration] Error getting transcript: {e}")
        return ""


async def take_conversation_snapshot(call_id: str) -> Optional[dict]:
    """
    Take immutable snapshot of conversation for safe persistence.
    
    Args:
        call_id: Call identifier
        
    Returns:
        Snapshot dict or None
    """
    try:
        service = get_conversation_capture_service()
        if not service:
            return None

        snapshot = service.take_snapshot(call_id)
        return snapshot

    except Exception as e:
        log.error(f"[ConvIntegration] Error taking snapshot: {e}")
        return None


async def cleanup_conversation(call_id: str) -> bool:
    """Remove conversation from memory after persistence"""
    try:
        service = get_conversation_capture_service()
        if not service:
            return False

        return service.cleanup_conversation(call_id)

    except Exception as e:
        log.error(f"[ConvIntegration] Error cleaning up conversation: {e}")
        return False


async def get_conversation_stats(call_id: str) -> Optional[dict]:
    """Get conversation statistics"""
    try:
        service = get_conversation_capture_service()
        if not service:
            return None

        return service.get_stats(call_id)

    except Exception as e:
        log.error(f"[ConvIntegration] Error getting stats: {e}")
        return None
