"""
SIP (Session Initiation Protocol) Utilities
SIP call state management and utilities
"""

from ..core.config import log

class SIPCallState:
    """SIP call states"""
    NEW = "NEW"
    RINGING = "RINGING"
    ANSWERED = "ANSWERED"
    HOLDING = "HOLDING"
    TRANSFERRING = "TRANSFERRING"
    DISCONNECTING = "DISCONNECTING"
    DISCONNECTED = "DISCONNECTED"

class CallState:
    """Call lifecycle states"""
    NEW = "NEW"
    SIP_UP = "SIP_UP"
    BRIDGE_CREATED = "BRIDGE_CREATED"
    SIP_ADDED = "SIP_ADDED"
    MEDIA_CREATED = "MEDIA_CREATED"
    MEDIA_ADDED = "MEDIA_ADDED"
    BRIDGE_VERIFIED = "BRIDGE_VERIFIED"
    RTP_ESTABLISHED = "RTP_ESTABLISHED"
    GREETING = "GREETING"
    LISTENING = "LISTENING"
    RESPONDING = "RESPONDING"
    HANGING_UP = "HANGING_UP"
    CLEANUP = "CLEANUP"

    TRANSITIONS = {
        NEW: [SIP_UP],
        SIP_UP: [BRIDGE_CREATED],
        BRIDGE_CREATED: [SIP_ADDED],
        SIP_ADDED: [MEDIA_CREATED],
        MEDIA_CREATED: [MEDIA_ADDED],
        MEDIA_ADDED: [BRIDGE_VERIFIED, MEDIA_CREATED],
        BRIDGE_VERIFIED: [RTP_ESTABLISHED],
        RTP_ESTABLISHED: [GREETING],
        GREETING: [LISTENING],
        LISTENING: [RESPONDING, HANGING_UP],
        RESPONDING: [LISTENING, HANGING_UP],
        HANGING_UP: [CLEANUP],
        CLEANUP: [],
    }

    @staticmethod
    def is_valid_transition(current: str, next_state: str) -> bool:
        """Check if a state transition is valid"""
        return next_state in CallState.TRANSITIONS.get(current, [])

    @staticmethod
    def log_transition(cid: str, current: str, next_state: str) -> bool:
        """Log and validate a state transition"""
        if CallState.is_valid_transition(current, next_state):
            log.info(f"[{cid}] Call state: {current} → {next_state}")
            return True
        else:
            log.warning(f"[{cid}] Invalid transition: {current} → {next_state}")
            return False
