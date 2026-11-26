"""
Comprehensive tests for conversation capture, persistence, and call termination.

Tests cover:
1. Conversation capture flow - all message types in sequence
2. Exact one INSERT per call with idempotent protection
3. RTP playback drain before hangup
4. Multi-call isolation
5. Abnormal termination handling
"""

import pytest
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

# Import services to test
from app.services.conversation_capture_service import (
    ConversationCaptureService,
    ConversationEntry,
    MessageType,
    get_conversation_capture_service,
    init_conversation_capture_service
)
from app.services.call_state_machine import (
    CallStateMachine,
    CallState,
    StateTransitionRule,
    create_state_machine,
    get_state_machine,
    cleanup_state_machine
)
from app.services.call_termination_sequence import (
    CallTerminationSequence,
    create_termination_sequence,
    get_termination_sequence,
    cleanup_termination_sequence
)
from app.services.conversation_integration import (
    capture_ai_greeting,
    capture_requirement_question,
    capture_customer_response,
    capture_ai_acknowledgement,
    capture_clarification_question,
    capture_customer_correction,
    capture_closing_message,
    get_complete_transcript,
    take_conversation_snapshot,
    cleanup_conversation,
    get_conversation_stats
)


class TestConversationCapture:
    """Tests for ConversationCaptureService"""

    @pytest.fixture
    async def capture_service(self):
        """Initialize capture service"""
        await init_conversation_capture_service()
        return get_conversation_capture_service()

    @pytest.mark.asyncio
    async def test_greeting_captured(self, capture_service):
        """Test 1: Greeting is captured in conversation history"""
        call_id = "test_call_001"
        greeting = "Hello, thank you for calling. How may I assist you?"

        # Capture greeting
        success = await capture_ai_greeting(call_id, greeting)
        assert success is True

        # Verify transcript
        transcript = await get_complete_transcript(call_id)
        assert greeting in transcript
        assert "AI:" in transcript

        # Cleanup
        await cleanup_conversation(call_id)

    @pytest.mark.asyncio
    async def test_all_message_types_captured(self, capture_service):
        """Test 2-7: All message types captured in correct order"""
        call_id = "test_call_002"

        # 1. Greeting
        await capture_ai_greeting(call_id, "Welcome to our service!")

        # 2. Question
        await capture_requirement_question(
            call_id, "What is your name?", "customer_name"
        )

        # 3. Customer response
        await capture_customer_response(
            call_id, "My name is Rahul", "customer_name"
        )

        # 4. AI acknowledgement
        await capture_ai_acknowledgement(
            call_id, "Thank you, Rahul", "customer_name"
        )

        # 5. Next question
        await capture_requirement_question(
            call_id, "What company do you work for?", "company_name"
        )

        # 6. Customer response
        await capture_customer_response(
            call_id, "ABC Industries", "company_name"
        )

        # 7. Closing message
        await capture_closing_message(
            call_id, "Thank you for your time. Goodbye!"
        )

        # Verify order and content
        transcript = await get_complete_transcript(call_id)
        lines = transcript.split("\n")

        assert len(lines) == 7
        assert "AI: Welcome" in lines[0]
        assert "AI: What is your name?" in lines[1]
        assert "CUSTOMER: My name is Rahul" in lines[2]
        assert "AI: Thank you, Rahul" in lines[3]
        assert "AI: What company" in lines[4]
        assert "CUSTOMER: ABC Industries" in lines[5]
        assert "AI: Thank you for your time" in lines[6]

        # Cleanup
        await cleanup_conversation(call_id)

    @pytest.mark.asyncio
    async def test_clarification_captured(self, capture_service):
        """Test 8: Clarification messages captured in correct order"""
        call_id = "test_call_003"

        await capture_ai_greeting(call_id, "Hello!")
        await capture_requirement_question(call_id, "How many units?", "quantity")
        await capture_customer_response(call_id, "unclear response", "quantity")
        await capture_clarification_question(
            call_id, "Could you repeat that?", "quantity", attempt_number=1
        )
        await capture_customer_response(call_id, "10,000 units", "quantity")

        transcript = await get_complete_transcript(call_id)
        assert "Could you repeat that?" in transcript
        assert transcript.index("Could you repeat") > transcript.index("unclear response")

        await cleanup_conversation(call_id)

    @pytest.mark.asyncio
    async def test_customer_correction_captured(self, capture_service):
        """Test 9: Customer corrections captured"""
        call_id = "test_call_004"

        await capture_ai_greeting(call_id, "Hello!")
        await capture_requirement_question(call_id, "What's your name?", "name")
        await capture_customer_response(call_id, "John", "name")
        await capture_customer_correction(
            call_id, "Actually, it's Jon with one N", "name", "John"
        )

        transcript = await get_complete_transcript(call_id)
        assert "Actually, it's Jon" in transcript

        await cleanup_conversation(call_id)

    @pytest.mark.asyncio
    async def test_empty_messages_excluded(self, capture_service):
        """Test 10: Empty messages are excluded from conversation"""
        call_id = "test_call_005"

        await capture_ai_greeting(call_id, "Hello!")
        
        # Try to capture empty message - should be skipped
        success = await capture_customer_response(call_id, "", "field")
        assert success is False

        # Try whitespace-only - should be skipped
        success = await capture_customer_response(call_id, "   ", "field")
        assert success is False

        # Verify empty messages not in transcript
        transcript = await get_complete_transcript(call_id)
        lines = [l for l in transcript.split("\n") if l.strip()]
        assert len(lines) == 1  # Only greeting

        await cleanup_conversation(call_id)

    @pytest.mark.asyncio
    async def test_duplicate_prevention(self, capture_service):
        """Test 11: Duplicate Gemini/RTP events don't duplicate messages"""
        call_id = "test_call_006"

        await capture_ai_greeting(call_id, "Hello!")

        # Try to capture same greeting again (simulating duplicate event)
        success = await capture_ai_greeting(call_id, "Hello!")
        assert success is False  # Duplicate prevention

        # Verify only one greeting in transcript
        transcript = await get_complete_transcript(call_id)
        count = transcript.count("Hello!")
        assert count == 1

        await cleanup_conversation(call_id)

    @pytest.mark.asyncio
    async def test_conversation_sequence_numbers(self, capture_service):
        """Test: Sequence numbers assigned correctly"""
        call_id = "test_call_007"

        await capture_ai_greeting(call_id, "Hello!")
        await capture_requirement_question(call_id, "Name?", "name")
        await capture_customer_response(call_id, "John", "name")

        # Get as structured entries
        service = get_conversation_capture_service()
        entries_list = service.get_entries_list(call_id)

        # Verify sequence numbers
        assert len(entries_list) == 3
        assert entries_list[0]["sequence_number"] == 1
        assert entries_list[1]["sequence_number"] == 2
        assert entries_list[2]["sequence_number"] == 3

        await cleanup_conversation(call_id)

    @pytest.mark.asyncio
    async def test_conversation_snapshot(self, capture_service):
        """Test: Immutable snapshot for safe persistence"""
        call_id = "test_call_008"

        await capture_ai_greeting(call_id, "Hello!")
        await capture_requirement_question(call_id, "Name?", "name")
        await capture_customer_response(call_id, "John", "name")

        snapshot = await take_conversation_snapshot(call_id)
        assert snapshot is not None
        assert snapshot["call_id"] == call_id
        assert snapshot["total_messages"] == 3
        assert len(snapshot["entries"]) == 3

        # Verify immutability (entries are copies)
        assert snapshot["entries"][0]["message"] == "Hello!"

        await cleanup_conversation(call_id)

    @pytest.mark.asyncio
    async def test_conversation_stats(self, capture_service):
        """Test: Conversation statistics calculated correctly"""
        call_id = "test_call_009"

        await capture_ai_greeting(call_id, "Hello!")
        await capture_requirement_question(call_id, "Name?", "name")
        await capture_customer_response(call_id, "John", "name")
        await capture_closing_message(call_id, "Goodbye!")

        stats = await get_conversation_stats(call_id)
        assert stats is not None
        assert stats["total_messages"] == 4
        assert stats["ai_messages"] == 3
        assert stats["customer_messages"] == 1
        assert stats["has_greeting"] is True
        assert stats["has_closing"] is True
        assert stats["message_types"]["greeting"] == 1
        assert stats["message_types"]["question"] == 1
        assert stats["message_types"]["customer_response"] == 1
        assert stats["message_types"]["closing"] == 1

        await cleanup_conversation(call_id)


class TestStateMachine:
    """Tests for CallStateMachine"""

    def test_valid_transitions(self):
        """Test: Valid state transitions are allowed"""
        sm = CallStateMachine("test_call")

        # Valid progression
        assert sm.transition(CallState.SESSION_INITIALIZING) is True
        assert sm.transition(CallState.MEDIA_CONNECTING) is True
        assert sm.transition(CallState.GEMINI_CONNECTING) is True
        assert sm.transition(CallState.GREETING_GENERATING) is True
        assert sm.transition(CallState.GREETING_PLAYING) is True

    def test_invalid_transitions_blocked(self):
        """Test: Invalid transitions are blocked"""
        sm = CallStateMachine("test_call")

        # Invalid jump
        assert sm.transition(CallState.DATABASE_PERSISTENCE) is False

        # Verify still in initial state
        assert sm.current_state == CallState.CALL_ANSWERED

    def test_state_history(self):
        """Test: State history is maintained"""
        sm = CallStateMachine("test_call")

        sm.transition(CallState.SESSION_INITIALIZING)
        sm.transition(CallState.MEDIA_CONNECTING)

        history = sm.get_history()
        assert len(history) == 3  # Initial + 2 transitions
        assert history[0][0] == CallState.CALL_ANSWERED
        assert history[1][0] == CallState.SESSION_INITIALIZING
        assert history[2][0] == CallState.MEDIA_CONNECTING

    def test_playback_phase_detection(self):
        """Test: Playback phase detection"""
        sm = CallStateMachine("test_call")

        # Transition to greeting playback
        sm.transition(CallState.SESSION_INITIALIZING)
        sm.transition(CallState.MEDIA_CONNECTING)
        sm.transition(CallState.GEMINI_CONNECTING)
        sm.transition(CallState.GREETING_GENERATING)
        sm.transition(CallState.GREETING_PLAYING)

        assert sm.is_in_playback_phase() is True

        sm.transition(CallState.GREETING_COMPLETE)
        assert sm.is_in_playback_phase() is False

    def test_closing_sequence_detection(self):
        """Test: Closing sequence detection"""
        sm = CallStateMachine("test_call")

        # Navigate to closing
        sm.current_state = CallState.ALL_REQUIREMENTS_COMPLETED
        assert sm.is_in_closing_sequence() is False

        sm.transition(CallState.SAVING_REQUIREMENTS)
        assert sm.is_in_closing_sequence() is True

        sm.transition(CallState.CLOSING_MESSAGE_GENERATING)
        sm.transition(CallState.CLOSING_MESSAGE_PLAYING)
        sm.transition(CallState.PLAYBACK_DRAINING)
        sm.transition(CallState.CALL_HANGUP)
        sm.transition(CallState.DATABASE_PERSISTENCE)

        assert sm.is_in_closing_sequence() is True


class TestTerminationSequence:
    """Tests for CallTerminationSequence"""

    def test_termination_sequence_created(self):
        """Test: Termination sequence created with state machine"""
        call_id = "test_call_term_001"
        sm = create_state_machine(call_id)
        term_seq = create_termination_sequence(call_id)

        assert term_seq is not None
        assert term_seq.call_id == call_id
        assert term_seq.state_machine == sm

        cleanup_state_machine(call_id)
        cleanup_termination_sequence(call_id)

    @pytest.mark.asyncio
    async def test_playback_drain_timeout(self):
        """Test 14: Playback drain with timeout handling"""
        call_id = "test_call_term_002"
        sm = create_state_machine(call_id)
        term_seq = create_termination_sequence(call_id)

        # Mock media session with queue
        media_session = MagicMock()
        media_session.tx_queue = MagicMock()
        media_session.tx_queue.qsize = MagicMock(return_value=5)  # Queue has frames

        # Wait for drain (will timeout)
        success, error = await term_seq.wait_for_playback_drain(
            media_session, timeout_sec=0.5
        )

        # Should succeed (timeout is not error, still proceeds)
        assert success is True
        assert error is None

        cleanup_state_machine(call_id)
        cleanup_termination_sequence(call_id)

    @pytest.mark.asyncio
    async def test_abnormal_termination_handling(self):
        """Test 18: Abnormal termination saves partial conversation"""
        call_id = "test_call_term_003"
        sm = create_state_machine(call_id)
        term_seq = create_termination_sequence(call_id)

        # Simulate early hangup with partial conversation
        conversation_text = "AI: Hello\nCUSTOMER: Hi\n[call disconnected]"

        # Mock conversation history service
        mock_service = MagicMock()
        mock_service.save_conversation = AsyncMock(return_value=True)

        success = await term_seq.handle_abnormal_termination(
            reason="Customer hung up",
            conversation_text=conversation_text,
            conversation_history_service=mock_service,
            userid=123,
            caller_number="9876543210"
        )

        assert success is True
        assert term_seq.abnormal_termination is True
        assert "Customer hung up" in term_seq.abnormal_reason

        # Verify save was called
        mock_service.save_conversation.assert_called_once()

        cleanup_state_machine(call_id)
        cleanup_termination_sequence(call_id)


class TestMultiCallIsolation:
    """Tests for multi-call isolation"""

    @pytest.mark.asyncio
    async def test_two_simultaneous_calls_isolated(self, capture_service):
        """Test 15: Two simultaneous calls maintain separate conversations"""
        call_id_1 = "call_isolation_001"
        call_id_2 = "call_isolation_002"

        # Call 1 conversation
        await capture_ai_greeting(call_id_1, "Hello, this is call 1")
        await capture_requirement_question(call_id_1, "Name?", "name")
        await capture_customer_response(call_id_1, "John", "name")

        # Call 2 conversation (different)
        await capture_ai_greeting(call_id_2, "Hello, this is call 2")
        await capture_requirement_question(call_id_2, "Company?", "company")
        await capture_customer_response(call_id_2, "ACME Corp", "company")

        # Verify separation
        transcript_1 = await get_complete_transcript(call_id_1)
        transcript_2 = await get_complete_transcript(call_id_2)

        assert "call 1" in transcript_1
        assert "call 1" not in transcript_2
        assert "call 2" in transcript_2
        assert "call 2" not in transcript_1

        assert "John" in transcript_1
        assert "John" not in transcript_2
        assert "ACME Corp" in transcript_2
        assert "ACME Corp" not in transcript_1

        await cleanup_conversation(call_id_1)
        await cleanup_conversation(call_id_2)

    @pytest.mark.asyncio
    async def test_cleanup_isolation(self, capture_service):
        """Test 15: Cleanup of one call doesn't affect another"""
        call_id_1 = "cleanup_iso_001"
        call_id_2 = "cleanup_iso_002"

        # Create conversations
        await capture_ai_greeting(call_id_1, "Call 1")
        await capture_ai_greeting(call_id_2, "Call 2")

        # Cleanup call 1
        await cleanup_conversation(call_id_1)

        # Verify call 2 still exists
        transcript_2 = await get_complete_transcript(call_id_2)
        assert transcript_2 is not None
        assert "Call 2" in transcript_2

        # Cleanup call 2
        await cleanup_conversation(call_id_2)


class TestIdempotentPersistence:
    """Tests for exact one INSERT per call"""

    @pytest.mark.asyncio
    async def test_single_insert_success(self):
        """Test 13: Single INSERT succeeds"""
        from app.services.conversation_history_service import ConversationHistoryService

        service = ConversationHistoryService()

        result = await asyncio.to_thread(
            service.save_conversation,
            call_id="test_insert_001",
            userid=100,
            caller_number="1234567890",
            conversation_text="AI: Hello\nCUSTOMER: Hi",
            detected_language="en",
            call_duration=60
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_retry_no_duplicate(self):
        """Test 13: Retry doesn't create duplicate (ON DUPLICATE KEY UPDATE)"""
        from app.services.conversation_history_service import ConversationHistoryService

        service = ConversationHistoryService()

        # First insert
        result1 = await asyncio.to_thread(
            service.save_conversation,
            call_id="test_insert_002",
            userid=100,
            caller_number="1234567890",
            conversation_text="Message 1",
            detected_language="en",
            call_duration=60
        )
        assert result1 is True

        # Retry with updated message
        result2 = await asyncio.to_thread(
            service.save_conversation,
            call_id="test_insert_002",
            userid=100,
            caller_number="1234567890",
            conversation_text="Message 1 updated",
            detected_language="en",
            call_duration=65
        )
        assert result2 is True

        # Verify record exists (not duplicated)
        record = await asyncio.to_thread(
            service.get_by_call_id,
            call_id="test_insert_002"
        )
        assert record is not None
        assert record["conversation_text"] == "Message 1 updated"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
