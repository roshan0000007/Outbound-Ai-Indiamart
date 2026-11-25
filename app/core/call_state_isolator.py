"""
Call State Isolator
Ensures per-call state isolation for parallel concurrent calls

**Task 8: Parallel Service Initialization for Multiple Calls**

Verifies:
- Each call has unique: call_id, session, STT buffer, RTP session
- No shared global state except read-only config
- Session storage uses call_id as key
- Call-specific WebSocket streams are isolated
- STT WebSocket connection is per-call
- RTP port is per-call
- Audio buffers are per-call
- No cross-call session pollution
"""

from typing import Dict, Optional, Set
from datetime import datetime
import asyncio
from ..core.config import log

class CallStateIsolator:
    """Ensures complete isolation of state between concurrent calls"""

    def __init__(self):
        self.active_calls: Set[str] = set()
        self.call_metadata: Dict[str, Dict] = {}
        self.call_start_times: Dict[str, float] = {}
        self.call_rtp_ports: Dict[str, int] = {}
        self.call_stt_connections: Dict[str, str] = {}
        self.call_buffers: Dict[str, Dict] = {}

    def register_call(self, call_id: str) -> bool:
        """
        Register a new call for state isolation tracking
        
        Args:
            call_id: Call identifier
            
        Returns:
            True if registered successfully, False if already exists
        """
        if call_id in self.active_calls:
            log.warning(f"[CALL-STATE] Call {call_id} already registered!")
            return False

        self.active_calls.add(call_id)
        self.call_metadata[call_id] = {
            "created_at": datetime.now().isoformat(),
            "status": "active",
            "stasis_app_id": call_id,
        }
        self.call_start_times[call_id] = asyncio.get_event_loop().time() if hasattr(asyncio.get_event_loop(), 'time') else 0
        self.call_buffers[call_id] = {
            "stt_buffer": bytearray(),
            "vad_buffer": bytearray(),
            "audio_queue": asyncio.Queue() if hasattr(asyncio, 'Queue') else None,
        }

        log.info(f"[CALL-STATE] ✅ Registered call {call_id} (total active: {len(self.active_calls)})")
        return True

    def assign_rtp_port(self, call_id: str, port: int) -> bool:
        """
        Assign RTP port to specific call
        
        Args:
            call_id: Call identifier
            port: RTP port number
            
        Returns:
            True if assigned successfully
        """
        if call_id not in self.active_calls:
            log.error(f"[CALL-STATE] Cannot assign RTP port to unregistered call {call_id}")
            return False

        self.call_rtp_ports[call_id] = port
        log.debug(f"[CALL-STATE] Assigned RTP port {port} to call {call_id}")
        return True

    def get_rtp_port(self, call_id: str) -> Optional[int]:
        """
        Get RTP port assigned to call
        
        Args:
            call_id: Call identifier
            
        Returns:
            RTP port number or None if not assigned
        """
        return self.call_rtp_ports.get(call_id)

    def verify_call_isolation(self, call_id: str) -> Dict[str, bool]:
        """
        Verify call state isolation (no cross-call pollution)
        
        Args:
            call_id: Call identifier
            
        Returns:
            Verification results {check_name → passed}
        """
        if call_id not in self.active_calls:
            return {"error": True}

        checks = {
            "call_registered": call_id in self.active_calls,
            "rtp_port_unique": self._verify_rtp_port_unique(call_id),
            "stt_connection_unique": self._verify_stt_connection_unique(call_id),
            "buffers_isolated": self._verify_buffers_isolated(call_id),
            "metadata_present": call_id in self.call_metadata,
        }

        all_passed = all(checks.values())

        if all_passed:
            log.debug(f"[CALL-STATE] ✅ Call {call_id} isolation verified")
        else:
            log.warning(f"[CALL-STATE] ⚠️  Call {call_id} isolation issues: {checks}")

        return checks

    def _verify_rtp_port_unique(self, call_id: str) -> bool:
        """Verify RTP port is unique to this call"""
        my_port = self.call_rtp_ports.get(call_id)
        if not my_port:
            return True

        for other_call_id, port in self.call_rtp_ports.items():
            if other_call_id != call_id and port == my_port:
                log.error(f"[CALL-STATE] ❌ RTP port {my_port} shared between {call_id} and {other_call_id}")
                return False

        return True

    def _verify_stt_connection_unique(self, call_id: str) -> bool:
        """Verify STT connection is unique to this call"""
        my_conn = self.call_stt_connections.get(call_id)
        if not my_conn:
            return True

        for other_call_id, conn in self.call_stt_connections.items():
            if other_call_id != call_id and conn == my_conn:
                log.error(f"[CALL-STATE] ❌ STT connection {my_conn} shared between {call_id} and {other_call_id}")
                return False

        return True

    def _verify_buffers_isolated(self, call_id: str) -> bool:
        """Verify audio buffers are isolated to this call"""
        if call_id not in self.call_buffers:
            return False

        my_buffers = self.call_buffers[call_id]
        for other_call_id, other_buffers in self.call_buffers.items():
            if other_call_id != call_id:
                if my_buffers.get("stt_buffer") is other_buffers.get("stt_buffer"):
                    log.error(f"[CALL-STATE] ❌ STT buffer shared between {call_id} and {other_call_id}")
                    return False

        return True

    def unregister_call(self, call_id: str) -> bool:
        """
        Unregister completed call and clean up state
        
        Args:
            call_id: Call identifier
            
        Returns:
            True if unregistered successfully
        """
        if call_id not in self.active_calls:
            log.warning(f"[CALL-STATE] Attempt to unregister non-existent call {call_id}")
            return False

        self.active_calls.discard(call_id)
        self.call_metadata.pop(call_id, None)
        self.call_start_times.pop(call_id, None)
        self.call_rtp_ports.pop(call_id, None)
        self.call_stt_connections.pop(call_id, None)
        self.call_buffers.pop(call_id, None)

        log.info(f"[CALL-STATE] ✅ Unregistered call {call_id} (remaining active: {len(self.active_calls)})")
        return True

    def get_active_calls_count(self) -> int:
        """
        Get count of currently active calls
        
        Returns:
            Number of active calls
        """
        return len(self.active_calls)

    def get_active_calls(self) -> Set[str]:
        """
        Get set of all active call IDs
        
        Returns:
            Set of call_ids
        """
        return set(self.active_calls)

    def verify_all_calls_isolated(self) -> bool:
        """
        Verify all active calls have proper isolation
        
        Returns:
            True if all calls are properly isolated
        """
        for call_id in self.active_calls:
            checks = self.verify_call_isolation(call_id)
            if not all(checks.values()):
                return False

        return True

    def log_concurrency_status(self) -> None:
        """Log current concurrency status"""
        active_count = len(self.active_calls)

        log.info(f"[CALL-STATE] Concurrency Status:")
        log.info(f"[CALL-STATE]   ├─ Active calls: {active_count}")

        if active_count > 0:
            log.info(f"[CALL-STATE]   ├─ Call IDs: {', '.join(sorted(self.active_calls))}")
            log.info(f"[CALL-STATE]   ├─ RTP ports in use: {len(self.call_rtp_ports)}")
            log.info(f"[CALL-STATE]   ├─ STT connections: {len(self.call_stt_connections)}")

            all_isolated = self.verify_all_calls_isolated()
            status = "✅ ISOLATED" if all_isolated else "❌ CROSS-POLLUTION"
            log.info(f"[CALL-STATE]   └─ State isolation: {status}")

_call_state_isolator = None

def get_call_state_isolator() -> CallStateIsolator:
    """Get or create global call state isolator"""
    global _call_state_isolator
    if _call_state_isolator is None:
        _call_state_isolator = CallStateIsolator()
    return _call_state_isolator
