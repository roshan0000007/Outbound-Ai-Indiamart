"""
Call State Machine
Manages strict call lifecycle states with proper transitions.
Ensures sequential flow: GREETING → QUESTIONS → CLOSING → HANGUP → PERSISTENCE.
"""

from enum import Enum
from typing import Optional, Dict, Any
from datetime import datetime

from ..core.config import log


class CallState(str, Enum):
    """Call lifecycle states"""
    CALL_ANSWERED = "CALL_ANSWERED"
    SESSION_INITIALIZING = "SESSION_INITIALIZING"
    MEDIA_CONNECTING = "MEDIA_CONNECTING"
    GEMINI_CONNECTING = "GEMINI_CONNECTING"
    
    # Greeting phase
    GREETING_GENERATING = "GREETING_GENERATING"
    GREETING_PLAYING = "GREETING_PLAYING"
    GREETING_COMPLETE = "GREETING_COMPLETE"
    
    # Question/answer loop
    QUESTION_GENERATING = "QUESTION_GENERATING"
    QUESTION_PLAYING = "QUESTION_PLAYING"
    LISTENING = "LISTENING"
    
    # Processing customer input
    PROCESSING_CUSTOMER_RESPONSE = "PROCESSING_CUSTOMER_RESPONSE"
    VALIDATING_REQUIREMENT = "VALIDATING_REQUIREMENT"
    
    # Clarification if needed
    CLARIFICATION_PLAYING = "CLARIFICATION_PLAYING"
    
    # All requirements complete
    ALL_REQUIREMENTS_COMPLETED = "ALL_REQUIREMENTS_COMPLETED"
    
    # Closing sequence
    SAVING_REQUIREMENTS = "SAVING_REQUIREMENTS"
    CLOSING_MESSAGE_GENERATING = "CLOSING_MESSAGE_GENERATING"
    CLOSING_MESSAGE_PLAYING = "CLOSING_MESSAGE_PLAYING"
    PLAYBACK_DRAINING = "PLAYBACK_DRAINING"
    
    # Call termination
    CALL_HANGUP = "CALL_HANGUP"
    
    # Persistence
    DATABASE_PERSISTENCE = "DATABASE_PERSISTENCE"
    SESSION_CLEANUP = "SESSION_CLEANUP"
    
    # Error states
    ERROR = "ERROR"
    CALL_TERMINATED = "CALL_TERMINATED"


class StateTransitionRule:
    """Defines valid state transitions"""
    
    # State transition map: current_state -> list of valid next_states
    VALID_TRANSITIONS = {
        CallState.CALL_ANSWERED: [
            CallState.SESSION_INITIALIZING,
            CallState.ERROR
        ],
        
        CallState.SESSION_INITIALIZING: [
            CallState.MEDIA_CONNECTING,
            CallState.ERROR
        ],
        
        CallState.MEDIA_CONNECTING: [
            CallState.GEMINI_CONNECTING,
            CallState.ERROR
        ],
        
        CallState.GEMINI_CONNECTING: [
            CallState.GREETING_GENERATING,
            CallState.ERROR
        ],
        
        CallState.GREETING_GENERATING: [
            CallState.GREETING_PLAYING,
            CallState.ERROR
        ],
        
        CallState.GREETING_PLAYING: [
            CallState.GREETING_COMPLETE,
            CallState.ERROR,
            CallState.CALL_TERMINATED  # Early hangup
        ],
        
        CallState.GREETING_COMPLETE: [
            CallState.QUESTION_GENERATING,
            CallState.ERROR
        ],
        
        CallState.QUESTION_GENERATING: [
            CallState.QUESTION_PLAYING,
            CallState.ERROR
        ],
        
        CallState.QUESTION_PLAYING: [
            CallState.LISTENING,
            CallState.ERROR,
            CallState.CALL_TERMINATED  # Barge-in or hangup
        ],
        
        CallState.LISTENING: [
            CallState.PROCESSING_CUSTOMER_RESPONSE,
            CallState.CALL_TERMINATED,  # Silence timeout or hangup
            CallState.ERROR
        ],
        
        CallState.PROCESSING_CUSTOMER_RESPONSE: [
            CallState.VALIDATING_REQUIREMENT,
            CallState.ERROR
        ],
        
        CallState.VALIDATING_REQUIREMENT: [
            CallState.QUESTION_GENERATING,  # Next question
            CallState.CLARIFICATION_PLAYING,  # Need clarification
            CallState.ALL_REQUIREMENTS_COMPLETED,  # All requirements done
            CallState.ERROR
        ],
        
        CallState.CLARIFICATION_PLAYING: [
            CallState.LISTENING,
            CallState.ERROR,
            CallState.CALL_TERMINATED
        ],
        
        CallState.ALL_REQUIREMENTS_COMPLETED: [
            CallState.SAVING_REQUIREMENTS,
            CallState.ERROR
        ],
        
        CallState.SAVING_REQUIREMENTS: [
            CallState.CLOSING_MESSAGE_GENERATING,
            CallState.ERROR
        ],
        
        CallState.CLOSING_MESSAGE_GENERATING: [
            CallState.CLOSING_MESSAGE_PLAYING,
            CallState.ERROR
        ],
        
        CallState.CLOSING_MESSAGE_PLAYING: [
            CallState.PLAYBACK_DRAINING,
            CallState.ERROR,
            CallState.CALL_TERMINATED
        ],
        
        CallState.PLAYBACK_DRAINING: [
            CallState.CALL_HANGUP,
            CallState.ERROR
        ],
        
        CallState.CALL_HANGUP: [
            CallState.DATABASE_PERSISTENCE,
            CallState.ERROR
        ],
        
        CallState.DATABASE_PERSISTENCE: [
            CallState.SESSION_CLEANUP,
            CallState.ERROR
        ],
        
        CallState.SESSION_CLEANUP: [
            CallState.CALL_TERMINATED,
        ],
        
        # Error state - try cleanup
        CallState.ERROR: [
            CallState.CALL_HANGUP,
            CallState.DATABASE_PERSISTENCE,
            CallState.SESSION_CLEANUP,
            CallState.CALL_TERMINATED
        ],
        
        # Terminal state - no transitions
        CallState.CALL_TERMINATED: []
    }

    @classmethod
    def is_valid_transition(cls, from_state: CallState, to_state: CallState) -> bool:
        """Check if transition is allowed"""
        allowed = cls.VALID_TRANSITIONS.get(from_state, [])
        return to_state in allowed


class CallStateMachine:
    """
    Manages call state transitions with strict validation.
    
    Per-call instance to track state progression through complete lifecycle.
    """

    def __init__(self, call_id: str):
        self.call_id = call_id
        self.current_state = CallState.CALL_ANSWERED
        self.previous_state: Optional[CallState] = None
        self.state_history: list = [(CallState.CALL_ANSWERED, datetime.utcnow().isoformat())]
        self.state_data: Dict[str, Any] = {}
        self.error_message: Optional[str] = None

        log.info(f"[StateMachine] [{call_id}] Initialized in state: {self.current_state.value}")

    def transition(self, to_state: CallState, reason: Optional[str] = None) -> bool:
        """
        Transition to new state with validation.
        
        Args:
            to_state: Target state
            reason: Reason for transition (logged)
            
        Returns:
            True if transition valid, False otherwise
        """
        if not StateTransitionRule.is_valid_transition(self.current_state, to_state):
            log.error(
                f"[StateMachine] [{self.call_id}] INVALID TRANSITION: "
                f"{self.current_state.value} → {to_state.value}"
            )
            return False

        self.previous_state = self.current_state
        self.current_state = to_state
        self.state_history.append((to_state, datetime.utcnow().isoformat()))

        reason_str = f" ({reason})" if reason else ""
        log.info(
            f"[StateMachine] [{self.call_id}] STATE: {self.previous_state.value} → {to_state.value}{reason_str}"
        )

        return True

    def set_state_data(self, key: str, value: Any) -> None:
        """Store state-specific data"""
        self.state_data[key] = value

    def get_state_data(self, key: str, default: Any = None) -> Any:
        """Retrieve state-specific data"""
        return self.state_data.get(key, default)

    def set_error(self, message: str) -> None:
        """Mark error state with message"""
        self.error_message = message
        log.error(f"[StateMachine] [{self.call_id}] ERROR: {message}")

    def get_history(self) -> list:
        """Get complete state transition history"""
        return self.state_history

    def is_in_playback_phase(self) -> bool:
        """Check if in any playback state"""
        playback_states = [
            CallState.GREETING_PLAYING,
            CallState.QUESTION_PLAYING,
            CallState.CLARIFICATION_PLAYING,
            CallState.CLOSING_MESSAGE_PLAYING
        ]
        return self.current_state in playback_states

    def is_listening(self) -> bool:
        """Check if actively listening for customer input"""
        return self.current_state == CallState.LISTENING

    def is_in_closing_sequence(self) -> bool:
        """Check if in closing/hangup sequence"""
        closing_states = [
            CallState.SAVING_REQUIREMENTS,
            CallState.CLOSING_MESSAGE_GENERATING,
            CallState.CLOSING_MESSAGE_PLAYING,
            CallState.PLAYBACK_DRAINING,
            CallState.CALL_HANGUP,
            CallState.DATABASE_PERSISTENCE,
            CallState.SESSION_CLEANUP
        ]
        return self.current_state in closing_states

    def is_in_error_state(self) -> bool:
        """Check if in error state"""
        return self.current_state == CallState.ERROR

    def is_terminated(self) -> bool:
        """Check if call is fully terminated"""
        return self.current_state == CallState.CALL_TERMINATED

    def get_summary(self) -> Dict[str, Any]:
        """Get current state summary"""
        return {
            "call_id": self.call_id,
            "current_state": self.current_state.value,
            "previous_state": self.previous_state.value if self.previous_state else None,
            "total_transitions": len(self.state_history),
            "in_playback": self.is_in_playback_phase(),
            "is_listening": self.is_listening(),
            "is_in_closing": self.is_in_closing_sequence(),
            "error": self.error_message
        }


# Global registry of active state machines
_state_machines: Dict[str, CallStateMachine] = {}


def create_state_machine(call_id: str) -> CallStateMachine:
    """Create new state machine for call"""
    if call_id in _state_machines:
        log.warning(f"[StateMachine] State machine already exists for {call_id}")
        return _state_machines[call_id]

    sm = CallStateMachine(call_id)
    _state_machines[call_id] = sm
    return sm


def get_state_machine(call_id: str) -> Optional[CallStateMachine]:
    """Get state machine for call"""
    return _state_machines.get(call_id)


def cleanup_state_machine(call_id: str) -> bool:
    """Remove state machine after call ends"""
    if call_id in _state_machines:
        _state_machines.pop(call_id)
        log.info(f"[StateMachine] State machine cleaned up: {call_id}")
        return True
    return False


def get_active_machines_count() -> int:
    """Get count of active state machines"""
    return len(_state_machines)
