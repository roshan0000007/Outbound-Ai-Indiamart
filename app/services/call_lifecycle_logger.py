"""
Call Lifecycle Logger - Structured Latency & Performance Tracking
Logs all critical milestones with precise timing for call analysis

MILESTONES:
- CallStart (T=0s): Call arrives via Asterisk ARI
- BridgeReady (T<0.3s): Mixing bridge created and channels added
- MediaSessionReady (T<0.5s): RTP socket allocated
- GeminiConnected (T<1.0s): Gemini Live WebSocket connected
- SessionReady (T<1.5s): Gemini session initialized
- GreetingQueuedToMediaTX (T<2.0s): First greeting audio queued for transmission
- FirstRXFrameReceived (T<3.0s): First RTP frame from caller received
- AudioStreamingActive (T<5.0s): Bidirectional streaming established
- CallEnd (T=N): Call ended

TARGET PERFORMANCE:
✅ Greeting audio plays within 2 seconds of call arrival
✅ All milestones logged with sub-millisecond precision
✅ Frame counts tracked for RX/TX audio verification
"""

import time
from typing import Dict, Any, Optional, List
from datetime import datetime
from dataclasses import dataclass, field, asdict
from enum import Enum

from ..core.config import log


class CallMilestone(Enum):
    """Call lifecycle milestones"""
    CALL_START = "CALL_START"
    BRIDGE_READY = "BRIDGE_READY"
    MEDIA_SESSION_READY = "MEDIA_SESSION_READY"
    GEMINI_CONNECTED = "GEMINI_CONNECTED"
    SESSION_READY = "SESSION_READY"
    GREETING_QUEUED_TX = "GREETING_QUEUED_TX"
    FIRST_RX_FRAME = "FIRST_RX_FRAME"
    AUDIO_STREAMING_ACTIVE = "AUDIO_STREAMING_ACTIVE"
    GEMINI_RESPONSE_RECEIVED = "GEMINI_RESPONSE_RECEIVED"
    FIRST_TX_FRAME = "FIRST_TX_FRAME"
    CALL_END = "CALL_END"


@dataclass
class MilestoneEvent:
    """Represents a single milestone event"""
    milestone: CallMilestone
    timestamp: float
    elapsed_sec: float
    details: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'milestone': self.milestone.value,
            'timestamp': self.timestamp,
            'elapsed_sec': self.elapsed_sec,
            'details': self.details
        }


@dataclass
class CallStats:
    """Call statistics and metrics"""
    call_id: str
    caller_number: str
    dnid: str
    start_time: float
    end_time: Optional[float] = None
    duration_sec: float = 0.0
    
    # Milestones
    milestones: List[MilestoneEvent] = field(default_factory=list)
    
    # Audio metrics
    rx_frames_received: int = 0
    tx_frames_sent: int = 0
    rx_bytes_received: int = 0
    tx_bytes_sent: int = 0
    
    # Latency targets
    bridge_ready_sec: Optional[float] = None
    media_session_ready_sec: Optional[float] = None
    gemini_connected_sec: Optional[float] = None
    session_ready_sec: Optional[float] = None
    greeting_queued_sec: Optional[float] = None
    first_rx_frame_sec: Optional[float] = None
    audio_streaming_active_sec: Optional[float] = None
    
    # Failover info
    used_gemini_fallback: bool = False
    failover_reason: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'call_id': self.call_id,
            'caller_number': self.caller_number,
            'dnid': self.dnid,
            'start_time': self.start_time,
            'end_time': self.end_time,
            'duration_sec': self.duration_sec,
            'milestones': [m.to_dict() for m in self.milestones],
            'rx_frames_received': self.rx_frames_received,
            'tx_frames_sent': self.tx_frames_sent,
            'rx_bytes_received': self.rx_bytes_received,
            'tx_bytes_sent': self.tx_bytes_sent,
            'bridge_ready_sec': self.bridge_ready_sec,
            'media_session_ready_sec': self.media_session_ready_sec,
            'gemini_connected_sec': self.gemini_connected_sec,
            'session_ready_sec': self.session_ready_sec,
            'greeting_queued_sec': self.greeting_queued_sec,
            'first_rx_frame_sec': self.first_rx_frame_sec,
            'audio_streaming_active_sec': self.audio_streaming_active_sec,
            'used_gemini_fallback': self.used_gemini_fallback,
            'failover_reason': self.failover_reason,
        }


class CallLifecycleLogger:
    """Logs and tracks call lifecycle with precise timing"""
    
    def __init__(self):
        self.calls: Dict[str, CallStats] = {}
        
        log.info("[LIFECYCLE-LOG] ✅ Call lifecycle logger initialized")
        log.info("[LIFECYCLE-LOG]    ├─ Tracking: CallStart → BridgeReady → MediaReady → GeminiConnected → SessionReady → GreetingQueued → AudioStreaming → CallEnd")
        log.info("[LIFECYCLE-LOG]    ├─ Targets: Bridge <0.3s, Media <0.5s, Gemini <1.0s, Session <1.5s, Greeting <2.0s")
        log.info("[LIFECYCLE-LOG]    └─ Output: Structured logs with sub-millisecond precision")

    def log_call_start(
        self,
        call_id: str,
        caller_number: str,
        dnid: str
    ) -> None:
        """Log call arrival"""
        try:
            timestamp = time.time()
            stats = CallStats(
                call_id=call_id,
                caller_number=caller_number,
                dnid=dnid,
                start_time=timestamp
            )
            self.calls[call_id] = stats
            
            # Log milestone
            self._log_milestone(call_id, CallMilestone.CALL_START, {
                'caller_number': caller_number,
                'dnid': dnid
            })
            
            log.info(f"[LIFECYCLE] ✅ CALL START: {call_id}")
            log.info(f"[LIFECYCLE]    ├─ Caller: {caller_number} → DNID: {dnid}")
            log.info(f"[LIFECYCLE]    ├─ Timestamp: {timestamp}")
            log.info(f"[LIFECYCLE]    └─ ⏱️  Target: Greeting within 2.0s")
            
        except Exception as e:
            log.error(f"[LIFECYCLE] Error logging call start: {e}")

    def log_bridge_ready(self, call_id: str, bridge_id: str) -> None:
        """Log when Asterisk bridge is ready"""
        try:
            stats = self.calls.get(call_id)
            if not stats:
                return
            
            elapsed = time.time() - stats.start_time
            stats.bridge_ready_sec = elapsed
            
            self._log_milestone(call_id, CallMilestone.BRIDGE_READY, {
                'bridge_id': bridge_id,
                'elapsed_sec': elapsed
            })
            
            status = "✅" if elapsed < 0.3 else "⚠️"
            log.info(f"[LIFECYCLE] {status} BRIDGE READY: {call_id}")
            log.info(f"[LIFECYCLE]    ├─ Bridge ID: {bridge_id}")
            log.info(f"[LIFECYCLE]    ├─ Elapsed: {elapsed:.3f}s (target <0.3s)")
            log.info(f"[LIFECYCLE]    └─ Next: MediaSessionReady")
            
        except Exception as e:
            log.error(f"[LIFECYCLE] Error logging bridge ready: {e}")

    def log_media_session_ready(
        self,
        call_id: str,
        rtp_port: int,
        rtp_ip: str = "163.223.186.31"
    ) -> None:
        """Log when RTP media session is allocated"""
        try:
            stats = self.calls.get(call_id)
            if not stats:
                return
            
            elapsed = time.time() - stats.start_time
            stats.media_session_ready_sec = elapsed
            
            self._log_milestone(call_id, CallMilestone.MEDIA_SESSION_READY, {
                'rtp_port': rtp_port,
                'rtp_ip': rtp_ip,
                'elapsed_sec': elapsed
            })
            
            status = "✅" if elapsed < 0.5 else "⚠️"
            log.info(f"[LIFECYCLE] {status} MEDIA SESSION READY: {call_id}")
            log.info(f"[LIFECYCLE]    ├─ RTP Endpoint: {rtp_ip}:{rtp_port}")
            log.info(f"[LIFECYCLE]    ├─ Elapsed: {elapsed:.3f}s (target <0.5s)")
            log.info(f"[LIFECYCLE]    └─ Next: GeminiConnected")
            
        except Exception as e:
            log.error(f"[LIFECYCLE] Error logging media ready: {e}")

    def log_gemini_connected(self, call_id: str) -> None:
        """Log when Gemini Live WebSocket connects"""
        try:
            stats = self.calls.get(call_id)
            if not stats:
                return
            
            elapsed = time.time() - stats.start_time
            stats.gemini_connected_sec = elapsed
            
            self._log_milestone(call_id, CallMilestone.GEMINI_CONNECTED)
            
            status = "✅" if elapsed < 1.0 else "⚠️"
            log.info(f"[LIFECYCLE] {status} GEMINI CONNECTED: {call_id}")
            log.info(f"[LIFECYCLE]    ├─ WebSocket: Connected to Gemini Live API")
            log.info(f"[LIFECYCLE]    ├─ Elapsed: {elapsed:.3f}s (target <1.0s)")
            log.info(f"[LIFECYCLE]    └─ Next: SessionReady")
            
        except Exception as e:
            log.error(f"[LIFECYCLE] Error logging Gemini connected: {e}")

    def log_session_ready(self, call_id: str, session_id: str) -> None:
        """Log when Gemini session is initialized and ready"""
        try:
            stats = self.calls.get(call_id)
            if not stats:
                return
            
            elapsed = time.time() - stats.start_time
            stats.session_ready_sec = elapsed
            
            self._log_milestone(call_id, CallMilestone.SESSION_READY, {
                'session_id': session_id,
                'elapsed_sec': elapsed
            })
            
            status = "✅" if elapsed < 1.5 else "⚠️"
            log.info(f"[LIFECYCLE] {status} SESSION READY: {call_id}")
            log.info(f"[LIFECYCLE]    ├─ Session: {session_id}")
            log.info(f"[LIFECYCLE]    ├─ Elapsed: {elapsed:.3f}s (target <1.5s)")
            log.info(f"[LIFECYCLE]    ├─ Ready to send greeting")
            log.info(f"[LIFECYCLE]    └─ Next: GreetingQueuedToMediaTX")
            
        except Exception as e:
            log.error(f"[LIFECYCLE] Error logging session ready: {e}")

    def log_greeting_queued(self, call_id: str, greeting_text: str) -> None:
        """Log when greeting audio is queued to media TX"""
        try:
            stats = self.calls.get(call_id)
            if not stats:
                return
            
            elapsed = time.time() - stats.start_time
            stats.greeting_queued_sec = elapsed
            
            self._log_milestone(call_id, CallMilestone.GREETING_QUEUED_TX, {
                'greeting_text': greeting_text[:60] + "..." if len(greeting_text) > 60 else greeting_text,
                'elapsed_sec': elapsed
            })
            
            status = "✅" if elapsed < 2.0 else "⚠️"
            log.info(f"[LIFECYCLE] {status} GREETING QUEUED TO MEDIA TX: {call_id}")
            log.info(f"[LIFECYCLE]    ├─ Text: '{greeting_text[:60]}...'")
            log.info(f"[LIFECYCLE]    ├─ Elapsed: {elapsed:.3f}s (target <2.0s) ⏱️")
            log.info(f"[LIFECYCLE]    ├─ Audio streaming to caller now")
            log.info(f"[LIFECYCLE]    └─ Next: FirstRXFrameReceived")
            
        except Exception as e:
            log.error(f"[LIFECYCLE] Error logging greeting queued: {e}")

    def log_first_rx_frame(self, call_id: str, frame_size: int) -> None:
        """Log when first RTP frame is received from caller"""
        try:
            stats = self.calls.get(call_id)
            if not stats:
                return
            
            if stats.rx_frames_received > 0:
                return  # Already logged
            
            elapsed = time.time() - stats.start_time
            stats.first_rx_frame_sec = elapsed
            stats.rx_frames_received = 1
            stats.rx_bytes_received = frame_size
            
            self._log_milestone(call_id, CallMilestone.FIRST_RX_FRAME, {
                'frame_size': frame_size,
                'elapsed_sec': elapsed
            })
            
            log.info(f"[LIFECYCLE] ✅ FIRST RX FRAME RECEIVED: {call_id}")
            log.info(f"[LIFECYCLE]    ├─ Frame size: {frame_size} bytes (8kHz PCMU)")
            log.info(f"[LIFECYCLE]    ├─ Elapsed: {elapsed:.3f}s")
            log.info(f"[LIFECYCLE]    ├─ Caller audio now flowing to Gemini Live")
            log.info(f"[LIFECYCLE]    └─ Next: AudioStreamingActive")
            
        except Exception as e:
            log.error(f"[LIFECYCLE] Error logging first RX frame: {e}")

    def log_audio_streaming_active(self, call_id: str) -> None:
        """Log when bidirectional audio streaming is active"""
        try:
            stats = self.calls.get(call_id)
            if not stats:
                return
            
            elapsed = time.time() - stats.start_time
            stats.audio_streaming_active_sec = elapsed
            
            self._log_milestone(call_id, CallMilestone.AUDIO_STREAMING_ACTIVE)
            
            log.info(f"[LIFECYCLE] ✅ AUDIO STREAMING ACTIVE: {call_id}")
            log.info(f"[LIFECYCLE]    ├─ Elapsed: {elapsed:.3f}s (cumulative)")
            log.info(f"[LIFECYCLE]    ├─ RX → Gemini Live → TX flowing")
            log.info(f"[LIFECYCLE]    ├─ Greeting audio playing to caller")
            log.info(f"[LIFECYCLE]    └─ Call active - listening for caller input")
            
        except Exception as e:
            log.error(f"[LIFECYCLE] Error logging audio streaming active: {e}")

    def log_first_tx_frame(self, call_id: str, frame_size: int) -> None:
        """Log when first TX frame is sent to caller"""
        try:
            stats = self.calls.get(call_id)
            if not stats:
                return
            
            if stats.tx_frames_sent > 0:
                return  # Already logged
            
            elapsed = time.time() - stats.start_time
            stats.tx_frames_sent = 1
            stats.tx_bytes_sent = frame_size
            
            self._log_milestone(call_id, CallMilestone.FIRST_TX_FRAME, {
                'frame_size': frame_size,
                'elapsed_sec': elapsed
            })
            
            log.info(f"[LIFECYCLE] ✅ FIRST TX FRAME SENT: {call_id}")
            log.info(f"[LIFECYCLE]    ├─ Frame size: {frame_size} bytes (8kHz PCMU)")
            log.info(f"[LIFECYCLE]    ├─ Elapsed: {elapsed:.3f}s")
            log.info(f"[LIFECYCLE]    └─ Caller now hearing Gemini response audio")
            
        except Exception as e:
            log.error(f"[LIFECYCLE] Error logging first TX frame: {e}")

    def log_call_end(self, call_id: str, reason: str = "normal") -> Optional[Dict[str, Any]]:
        """Log call end and return statistics"""
        try:
            stats = self.calls.pop(call_id, None)
            if not stats:
                return None
            
            stats.end_time = time.time()
            stats.duration_sec = stats.end_time - stats.start_time
            
            self._log_milestone(call_id, CallMilestone.CALL_END, {
                'reason': reason,
                'duration_sec': stats.duration_sec
            })
            
            log.info(f"[LIFECYCLE] ✅ CALL END: {call_id}")
            log.info(f"[LIFECYCLE]    ├─ Reason: {reason}")
            log.info(f"[LIFECYCLE]    ├─ Duration: {stats.duration_sec:.1f}s")
            log.info(f"[LIFECYCLE]    ├─ RX frames: {stats.rx_frames_received} ({stats.rx_bytes_received} bytes)")
            log.info(f"[LIFECYCLE]    └─ TX frames: {stats.tx_frames_sent} ({stats.tx_bytes_sent} bytes)")
            
            # Log performance summary
            self._log_performance_summary(stats)
            
            return stats.to_dict()
            
        except Exception as e:
            log.error(f"[LIFECYCLE] Error logging call end: {e}")
            return None

    def update_audio_metrics(
        self,
        call_id: str,
        rx_frames: int = 0,
        rx_bytes: int = 0,
        tx_frames: int = 0,
        tx_bytes: int = 0
    ) -> None:
        """Update audio frame and byte counts"""
        try:
            stats = self.calls.get(call_id)
            if stats:
                if rx_frames > 0:
                    stats.rx_frames_received = rx_frames
                if rx_bytes > 0:
                    stats.rx_bytes_received = rx_bytes
                if tx_frames > 0:
                    stats.tx_frames_sent = tx_frames
                if tx_bytes > 0:
                    stats.tx_bytes_sent = tx_bytes
        except Exception as e:
            log.error(f"[LIFECYCLE] Error updating audio metrics: {e}")

    def _log_milestone(
        self,
        call_id: str,
        milestone: CallMilestone,
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        """Internal: log a milestone event"""
        try:
            stats = self.calls.get(call_id)
            if not stats:
                return
            
            elapsed = time.time() - stats.start_time
            event = MilestoneEvent(
                milestone=milestone,
                timestamp=time.time(),
                elapsed_sec=elapsed,
                details=details or {}
            )
            stats.milestones.append(event)
            
        except Exception as e:
            log.error(f"[LIFECYCLE] Error logging milestone: {e}")

    def _log_performance_summary(self, stats: CallStats) -> None:
        """Log final performance summary"""
        try:
            log.info(f"[LIFECYCLE] 📊 PERFORMANCE SUMMARY: {stats.call_id}")
            
            # Greeting latency (critical metric)
            if stats.greeting_queued_sec is not None:
                greeting_status = "✅ PASS" if stats.greeting_queued_sec < 2.0 else "❌ FAIL"
                log.info(f"[LIFECYCLE]    Greeting latency: {stats.greeting_queued_sec:.3f}s {greeting_status} (target <2.0s)")
            
            # Milestone times
            if stats.bridge_ready_sec is not None:
                log.info(f"[LIFECYCLE]    Bridge ready: {stats.bridge_ready_sec:.3f}s (target <0.3s)")
            if stats.media_session_ready_sec is not None:
                log.info(f"[LIFECYCLE]    Media ready: {stats.media_session_ready_sec:.3f}s (target <0.5s)")
            if stats.gemini_connected_sec is not None:
                log.info(f"[LIFECYCLE]    Gemini connected: {stats.gemini_connected_sec:.3f}s (target <1.0s)")
            if stats.session_ready_sec is not None:
                log.info(f"[LIFECYCLE]    Session ready: {stats.session_ready_sec:.3f}s (target <1.5s)")
            
            # Audio stats
            if stats.rx_frames_received > 0 or stats.tx_frames_sent > 0:
                log.info(f"[LIFECYCLE]    Audio RX: {stats.rx_frames_received} frames, {stats.rx_bytes_received} bytes")
                log.info(f"[LIFECYCLE]    Audio TX: {stats.tx_frames_sent} frames, {stats.tx_bytes_sent} bytes")
            
            # Failover info
            if stats.used_gemini_fallback:
                log.warning(f"[LIFECYCLE]    ⚠️ Used Groq fallback: {stats.failover_reason}")
            
        except Exception as e:
            log.error(f"[LIFECYCLE] Error logging performance summary: {e}")

    def get_call_stats(self, call_id: str) -> Optional[Dict[str, Any]]:
        """Get call statistics"""
        stats = self.calls.get(call_id)
        return stats.to_dict() if stats else None


# Global lifecycle logger
_logger: Optional[CallLifecycleLogger] = None


async def init_call_lifecycle_logger() -> CallLifecycleLogger:
    """Initialize call lifecycle logger"""
    global _logger
    _logger = CallLifecycleLogger()
    return _logger


def get_call_lifecycle_logger() -> Optional[CallLifecycleLogger]:
    """Get call lifecycle logger instance"""
    return _logger
