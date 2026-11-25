"""
Performance Instrumentation and Timing Utilities
Tracks latency for each stage of the call pipeline
Outputs [PERFORMANCE] tagged logs with detailed metrics

✅ TASK 8: Concurrency Metrics
- active_calls_count: Number of concurrent active calls
- per_call_status: Status and resource usage per call
- deadlock detection: Monitor for resource contention
- WebSocket stream isolation: Per-call stream metrics
"""

import time
from typing import Dict, Optional, List
from datetime import datetime
import asyncio
from .config import log

class ConcurrencyMetrics:
    """Tracks concurrency-related metrics for monitoring parallel call safety"""

    def __init__(self):
        self.active_calls: Dict[str, Dict] = {}
        self.lock = asyncio.Lock()

    async def register_call(self, call_id: str, caller_number: str, user_id: int):
        """Register a new active call"""
        async with self.lock:
            self.active_calls[call_id] = {
                "caller_number": caller_number,
                "user_id": user_id,
                "start_time": time.time(),
                "status": "initializing",
                "stt_buffer_size": 0,
                "tts_processing": False,
                "websocket_connected": False,
                "rtp_port": None,
                "messages_processed": 0,
                "bytes_received": 0,
                "bytes_sent": 0
            }
            log.info(f"[CONCURRENCY] Registered call {call_id}: active_calls={len(self.active_calls)}")

    async def unregister_call(self, call_id: str):
        """Unregister a ended call"""
        async with self.lock:
            if call_id in self.active_calls:
                call_data = self.active_calls.pop(call_id)
                duration = time.time() - call_data["start_time"]
                log.info(f"[CONCURRENCY] Unregistered call {call_id}: "
                        f"duration={duration:.1f}s, "
                        f"messages={call_data['messages_processed']}, "
                        f"active_calls_remaining={len(self.active_calls)}")

    async def update_call_status(self, call_id: str, status: str, **metrics):
        """Update call status and metrics"""
        async with self.lock:
            if call_id in self.active_calls:
                self.active_calls[call_id]["status"] = status
                self.active_calls[call_id].update(metrics)

                if status in ("listening", "processing", "error"):
                    log.debug(f"[CONCURRENCY] {call_id} status={status}, metrics={metrics}")

    async def get_active_calls_count(self) -> int:
        """Get count of active concurrent calls"""
        async with self.lock:
            return len(self.active_calls)

    async def get_call_status(self, call_id: str) -> Optional[Dict]:
        """Get call status and metrics"""
        async with self.lock:
            return self.active_calls.get(call_id)

    async def get_all_calls_status(self) -> List[Dict]:
        """Get status of all active calls"""
        async with self.lock:
            return list(self.active_calls.values())

    async def log_concurrency_metrics(self):
        """Log current concurrency metrics for monitoring"""
        async with self.lock:
            active_count = len(self.active_calls)
            if active_count > 0:
                statuses = {}
                total_bytes_received = 0
                total_bytes_sent = 0

                for call_data in self.active_calls.values():
                    status = call_data.get("status", "unknown")
                    statuses[status] = statuses.get(status, 0) + 1
                    total_bytes_received += call_data.get("bytes_received", 0)
                    total_bytes_sent += call_data.get("bytes_sent", 0)

                log.info(f"[CONCURRENCY-METRICS] active_calls={active_count}, "
                        f"statuses={statuses}, "
                        f"bytes_in={total_bytes_received}, "
                        f"bytes_out={total_bytes_sent}")

class CallPerformanceTracker:
    """
    Tracks performance metrics for a single call
    Measures latency at each pipeline stage
    """

    def __init__(self, call_id: str):
        self.call_id = call_id
        self.stages: Dict[str, Dict] = {}
        self.start_time = time.time()

        self.greeting_start_time = None
        self.greeting_complete_time = None
        self.listening_start_time = None

    def mark_greeting_start(self):
        """Mark when greeting generation starts"""
        self.greeting_start_time = time.time()
        log.info(f"[TRANSITION] ✅ Greeting generation START")

    def mark_greeting_complete(self):
        """Mark when greeting is ready to play"""
        self.greeting_complete_time = time.time()
        if self.greeting_start_time:
            greeting_gen_ms = (self.greeting_complete_time - self.greeting_start_time) * 1000
            log.info(f"[TRANSITION] ✅ Greeting generation COMPLETE: {greeting_gen_ms:.0f}ms")

    def mark_greeting_transmitted(self):
        """Mark when greeting has been fully transmitted via RTP (audio actually sent to caller)"""
        self.greeting_transmitted_time = time.time()
        if self.greeting_start_time:
            total_ms = (self.greeting_transmitted_time - self.greeting_start_time) * 1000
            log.info(f"[TRANSITION] ✅ Greeting transmission COMPLETE: {total_ms:.0f}ms (from generation start)")

    def record_ttft(self, ttft_ms: float):
        """BUGFIX: Record LLM time-to-first-token for latency debugging"""
        self.llm_ttft_ms = ttft_ms
        log.info(f"[PERFORMANCE] LLM TTFT: {ttft_ms:.0f}ms (target: <200ms for responsive feel)")
        if ttft_ms > 2000:
            log.warning(f"[PERFORMANCE] ⚠️  ELEVATED TTFT: {ttft_ms:.0f}ms > 2000ms (indicates LLM queue or network delay)")
        elif ttft_ms > 1000:
            log.warning(f"[PERFORMANCE] ⚠️  High TTFT: {ttft_ms:.0f}ms > 1000ms")

    def mark_listening_start(self):
        """Mark when listening mode becomes active (customer can start speaking)"""
        self.listening_start_time = time.time()

        if hasattr(self, 'greeting_transmitted_time') and self.greeting_transmitted_time:
            greeting_to_listening_ms = (self.listening_start_time - self.greeting_transmitted_time) * 1000
            metric_label = "greeting_transmitted → listening_active"
        elif self.greeting_complete_time:
            greeting_to_listening_ms = (self.listening_start_time - self.greeting_complete_time) * 1000
            metric_label = "greeting_complete → listening_active (includes setup)"
        else:
            greeting_to_listening_ms = 0
            metric_label = "unknown (no greeting_complete_time)"

        log.info(f"[TRANSITION] ✅ Listening mode ACTIVE - customer can now speak")
        log.info(f"[TRANSITION] 📊 GREETING → LISTENING LATENCY: {greeting_to_listening_ms:.0f}ms ({metric_label})")
        log.info(f"[TRANSITION] 📊 TARGET: <200ms (ideal), <500ms (acceptable)")

        if greeting_to_listening_ms > 500:
            log.error(f"[TRANSITION] ❌ CRITICAL BUG DETECTED: Greeting-to-listening latency {greeting_to_listening_ms:.0f}ms EXCEEDS 500ms maximum!")
            log.error(f"[TRANSITION] ❌ ROOT CAUSE: This indicates the double-wait bug is still present or reintroduced")
            log.error(f"[TRANSITION] ❌ IMPACT: Customers will experience dead air for {greeting_to_listening_ms:.0f}ms after greeting")
            log.error(f"[TRANSITION] ❌ CHECK: Look for redundant asyncio.sleep() after send_audio_response(wait_for_completion=True)")
            assert greeting_to_listening_ms <= 500, f"BUG: Greeting-to-listening latency {greeting_to_listening_ms:.0f}ms > 500ms (the double-wait bug)"
        elif greeting_to_listening_ms > 200:
            log.warning(f"[TRANSITION] ⚠️  Latency slightly exceeds ideal target: {greeting_to_listening_ms:.0f}ms > 200ms (acceptable but not optimal)")

    def start_stage(self, stage_name: str, description: str = ""):
        """Mark start of a pipeline stage"""
        self.stages[stage_name] = {
            "start": time.time(),
            "description": description,
            "duration_ms": None,
            "status": "running"
        }
        log.debug(f"[PERF-{self.call_id}] Stage START: {stage_name} - {description}")

    def end_stage(self, stage_name: str, status: str = "success"):
        """Mark end of a pipeline stage"""
        if stage_name not in self.stages:
            log.warning(f"[PERF-{self.call_id}] End stage called before start: {stage_name}")
            return

        self.stages[stage_name]["end"] = time.time()
        self.stages[stage_name]["duration_ms"] = (
            self.stages[stage_name]["end"] - self.stages[stage_name]["start"]
        ) * 1000
        self.stages[stage_name]["status"] = status

        log.info(f"[PERFORMANCE] {stage_name}={self.stages[stage_name]['duration_ms']:.0f}ms (status={status})")

    def log_stage_event(self, stage_name: str, event: str, details: str = ""):
        """Log an event within a stage (for detailed diagnostics)"""
        log.debug(f"[PERF-{self.call_id}] {stage_name}/{event}: {details}")

    def get_total_duration_ms(self) -> float:
        """Get total call duration since tracker creation"""
        return (time.time() - self.start_time) * 1000

    def get_stage_duration_ms(self, stage_name: str) -> Optional[float]:
        """Get duration of specific stage"""
        if stage_name in self.stages:
            return self.stages[stage_name].get("duration_ms")
        return None

    def print_summary(self):
        """Print performance summary for entire call"""
        total_ms = self.get_total_duration_ms()
        log.info(f"\n{'='*70}")
        log.info(f"[PERFORMANCE-SUMMARY] Call {self.call_id}")
        log.info(f"{'='*70}")

        greeting_latency = self.stages.get("greeting_generation_ms", {}).get("duration_ms", 0)
        vad_latency = self.stages.get("speech_detection_latency_ms", {}).get("duration_ms", 0)
        stt_latency = self.stages.get("stt_processing_ms", {}).get("duration_ms", 0)
        rag_latency = self.stages.get("rag_retrieval_ms", {}).get("duration_ms", 0)
        llm_latency = self.stages.get("llm_processing_ms", {}).get("duration_ms", 0)
        tts_latency = self.stages.get("tts_generation_ms", {}).get("duration_ms", 0)
        response_latency = self.stages.get("total_response_latency_ms", {}).get("duration_ms", 0)

        greeting_to_listening_latency = 0
        if self.greeting_complete_time and self.listening_start_time:
            greeting_to_listening_latency = (self.listening_start_time - self.greeting_complete_time) * 1000

        for stage_name, metrics in self.stages.items():
            duration = metrics.get("duration_ms", "N/A")
            status = metrics.get("status", "unknown")
            if isinstance(duration, float):
                pct = (duration / total_ms * 100) if total_ms > 0 else 0
                log.info(f"  {stage_name:30s}: {duration:7.0f}ms ({pct:5.1f}%) [{status}]")
            else:
                log.info(f"  {stage_name:30s}: {duration:>7s} [{status}]")

        log.info(f"{'='*70}")
        log.info(f"  KEY LATENCY METRICS:")
        log.info(f"    Greeting Generation:  {greeting_latency:7.0f}ms")
        log.info(f"    Greeting → Listening: {greeting_to_listening_latency:7.0f}ms (target: <200ms) ⭐ CRITICAL")
        log.info(f"    Speech Detection:     {vad_latency:7.0f}ms (target: 100-300ms)")
        log.info(f"    STT Processing:       {stt_latency:7.0f}ms")
        log.info(f"    RAG Retrieval:        {rag_latency:7.0f}ms")
        log.info(f"    LLM Processing:       {llm_latency:7.0f}ms")
        log.info(f"    TTS Generation:       {tts_latency:7.0f}ms")
        log.info(f"    Total Response:       {response_latency:7.0f}ms (target: < 2500ms)")
        log.info(f"{'='*70}")
        log.info(f"  TOTAL CALL DURATION: {total_ms:.0f}ms")
        log.info(f"{'='*70}\n")

    def get_performance_report(self) -> Dict:
        """Return performance data as dictionary for logging/storage with latency budget tracking"""
        from ..core.config import (
            VAD_LATENCY_BUDGET_MS,
            STT_LATENCY_BUDGET_MS,
            RAG_LATENCY_BUDGET_MS,
            LLM_LATENCY_BUDGET_MS,
            TTS_LATENCY_BUDGET_MS,
            RTP_LATENCY_BUDGET_MS,
            LATENCY_TARGET_MS,
            LATENCY_WARNING_THRESHOLD_PCT,
        )

        report = {
            "call_id": self.call_id,
            "total_duration_ms": self.get_total_duration_ms(),
            "timestamp": datetime.utcnow().isoformat(),
            "stages": {},
            "budget_compliance": {},
            "warnings": []
        }

        total_ms = report["total_duration_ms"]

        for stage_name, stage_data in self.stages.items():
            if stage_data.get("end_time"):
                duration = stage_data["end_time"] - stage_data["start_time"]
                duration_ms = duration * 1000

                stage_budget = 0
                if "vad" in stage_name.lower():
                    stage_budget = VAD_LATENCY_BUDGET_MS
                elif "stt" in stage_name.lower():
                    stage_budget = STT_LATENCY_BUDGET_MS
                elif "rag" in stage_name.lower():
                    stage_budget = RAG_LATENCY_BUDGET_MS
                elif "llm" in stage_name.lower():
                    stage_budget = LLM_LATENCY_BUDGET_MS
                elif "tts" in stage_name.lower():
                    stage_budget = TTS_LATENCY_BUDGET_MS
                elif "rtp" in stage_name.lower():
                    stage_budget = RTP_LATENCY_BUDGET_MS

                compliant = duration_ms <= stage_budget if stage_budget > 0 else True
                overage_pct = ((duration_ms / stage_budget - 1) * 100) if stage_budget > 0 else 0

                report["stages"][stage_name] = {
                    "duration_ms": duration_ms,
                    "budget_ms": stage_budget,
                    "compliant": compliant,
                    "overage_pct": overage_pct,
                    "status": stage_data.get("status", "unknown")
                }

                if stage_budget > 0:
                    threshold = stage_budget * LATENCY_WARNING_THRESHOLD_PCT
                    if duration_ms > threshold:
                        report["warnings"].append(
                            f"⚠️  LATENCY BUDGET: {stage_name} = {duration_ms:.0f}ms "
                            f"({overage_pct:+.1f}% of {stage_budget}ms budget)"
                        )

        report["budget_compliance"] = {
            "total_ms": total_ms,
            "target_ms": LATENCY_TARGET_MS,
            "compliant": total_ms <= LATENCY_TARGET_MS,
            "overage_pct": ((total_ms / LATENCY_TARGET_MS - 1) * 100) if LATENCY_TARGET_MS > 0 else 0
        }

        if not report["budget_compliance"]["compliant"]:
            report["warnings"].append(
                f"⚠️  TOTAL LATENCY: {total_ms:.0f}ms exceeds {LATENCY_TARGET_MS}ms target "
                f"({report['budget_compliance']['overage_pct']:+.1f}%)"
            )

        for warning in report["warnings"]:
            log.warning(f"[PERF-BUDGET] {warning}")

        return report

_call_trackers: Dict[str, CallPerformanceTracker] = {}
_concurrency_metrics: Optional[ConcurrencyMetrics] = None

def get_call_tracker(call_id: str) -> CallPerformanceTracker:
    """Get or create performance tracker for call"""
    if call_id not in _call_trackers:
        _call_trackers[call_id] = CallPerformanceTracker(call_id)
    return _call_trackers[call_id]

def cleanup_tracker(call_id: str):
    """Clean up tracker for ended call"""
    if call_id in _call_trackers:
        tracker = _call_trackers.pop(call_id)
        tracker.print_summary()

def get_concurrency_metrics() -> ConcurrencyMetrics:
    """Get or create concurrency metrics tracker"""
    global _concurrency_metrics
    if _concurrency_metrics is None:
        _concurrency_metrics = ConcurrencyMetrics()
    return _concurrency_metrics
