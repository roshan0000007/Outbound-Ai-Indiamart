"""
Latency Metrics Module
Tracks comprehensive latency at each pipeline stage

**Task 9: Add Comprehensive Latency Logging**

Tracks:
- TTS generation latency
- Audio codec conversion latency
- RTP transmission latency
- STT processing latency
- VAD initialization latency
- Speech detection latency
- LLM processing latency
- RAG retrieval latency
- Total end-to-end response latency
"""

import time
from typing import Optional, Dict, Any, List
from datetime import datetime
from collections import defaultdict
from ..core.config import log

class LatencyMetrics:
    """Track latency across all pipeline stages"""

    GREETING_GENERATION = "greeting_generation_ms"
    GREETING_CODEC_CONVERSION = "greeting_codec_conversion_ms"
    GREETING_PLAYBACK_START = "greeting_playback_start_ms"
    GREETING_PLAYBACK_END = "greeting_playback_end_ms"
    GREETING_TO_LISTENING = "greeting_to_listening_ms"
    VAD_INITIALIZATION = "vad_initialization_ms"
    SPEECH_DETECTION = "speech_detection_latency_ms"
    STT_PROCESSING = "stt_processing_ms"
    RAG_RETRIEVAL = "rag_retrieval_ms"
    LLM_PROCESSING = "llm_processing_ms"
    TTS_GENERATION = "tts_generation_ms"
    RESPONSE_CODEC_CONVERSION = "response_codec_conversion_ms"
    RESPONSE_PLAYBACK_LATENCY = "response_playback_latency_ms"
    TOTAL_RESPONSE_LATENCY = "total_response_latency_ms"

    def __init__(self):
        self.metrics = defaultdict(dict)
        self.milestones = defaultdict(dict)
        self.latency_buckets = defaultdict(list)

    def record_start(self, call_id: str, metric_name: str) -> None:
        """
        Record start time for a metric
        
        Args:
            call_id: Call identifier
            metric_name: Metric name (e.g., GREETING_GENERATION)
        """
        self.milestones[call_id][f"{metric_name}_start"] = time.time()

    def record_end(self, call_id: str, metric_name: str) -> float:
        """
        Record end time for a metric and calculate duration
        
        Args:
            call_id: Call identifier
            metric_name: Metric name
            
        Returns:
            Duration in milliseconds or 0 if start not recorded
        """
        start_key = f"{metric_name}_start"
        if start_key not in self.milestones[call_id]:
            log.warning(f"[LATENCY] End recorded without start for {call_id}.{metric_name}")
            return 0.0

        end_time = time.time()
        start_time = self.milestones[call_id][start_key]
        duration_ms = (end_time - start_time) * 1000

        self.metrics[call_id][metric_name] = duration_ms
        self.latency_buckets[metric_name].append(duration_ms)

        log.debug(f"[LATENCY] {call_id}: {metric_name} = {duration_ms:.1f}ms")

        return duration_ms

    def record_value(self, call_id: str, metric_name: str, value_ms: float) -> None:
        """
        Record a direct latency value
        
        Args:
            call_id: Call identifier
            metric_name: Metric name
            value_ms: Value in milliseconds
        """
        self.metrics[call_id][metric_name] = value_ms
        self.latency_buckets[metric_name].append(value_ms)

        log.debug(f"[LATENCY] {call_id}: {metric_name} = {value_ms:.1f}ms")

    def get_metric(self, call_id: str, metric_name: str) -> Optional[float]:
        """
        Get recorded metric value
        
        Args:
            call_id: Call identifier
            metric_name: Metric name
            
        Returns:
            Metric value in milliseconds or None if not recorded
        """
        return self.metrics[call_id].get(metric_name)

    def get_all_metrics(self, call_id: str) -> Dict[str, float]:
        """
        Get all metrics for a call
        
        Args:
            call_id: Call identifier
            
        Returns:
            Dictionary of {metric_name → value_ms}
        """
        return dict(self.metrics[call_id])

    def log_summary(self, call_id: str) -> None:
        """
        Log summary of all latency metrics for a call
        
        Args:
            call_id: Call identifier
        """
        metrics = self.metrics[call_id]

        if not metrics:
            log.info(f"[LATENCY] No metrics recorded for {call_id}")
            return

        greeting_latency = metrics.get(self.GREETING_TO_LISTENING, 0)
        speech_detection = metrics.get(self.SPEECH_DETECTION, 0)
        total_response = metrics.get(self.TOTAL_RESPONSE_LATENCY, 0)

        log.info(f"[LATENCY] ╔════════════════════════════════════╗")
        log.info(f"[LATENCY] ║ Call: {call_id}")
        log.info(f"[LATENCY] ╠════════════════════════════════════╣")

        greeting_gen = metrics.get(self.GREETING_GENERATION, 0)
        greeting_conv = metrics.get(self.GREETING_CODEC_CONVERSION, 0)
        if greeting_gen or greeting_conv or greeting_latency:
            log.info(f"[LATENCY] ║ GREETING PHASE:")
            if greeting_gen:
                log.info(f"[LATENCY] ║   - Generation: {greeting_gen:.0f}ms")
            if greeting_conv:
                log.info(f"[LATENCY] ║   - Codec conversion: {greeting_conv:.0f}ms")
            log.info(f"[LATENCY] ║   - Greeting→Listening: {greeting_latency:.0f}ms (target: <200ms)")

        vad_init = metrics.get(self.VAD_INITIALIZATION, 0)
        speech_det = metrics.get(self.SPEECH_DETECTION, 0)
        if vad_init or speech_det:
            log.info(f"[LATENCY] ║ LISTENING PHASE:")
            if vad_init:
                log.info(f"[LATENCY] ║   - VAD initialization: {vad_init:.0f}ms")
            log.info(f"[LATENCY] ║   - Speech detection: {speech_det:.0f}ms (target: 100-300ms)")

        stt = metrics.get(self.STT_PROCESSING, 0)
        rag = metrics.get(self.RAG_RETRIEVAL, 0)
        llm = metrics.get(self.LLM_PROCESSING, 0)
        tts = metrics.get(self.TTS_GENERATION, 0)

        if stt or rag or llm or tts:
            log.info(f"[LATENCY] ║ PROCESSING PHASE:")
            if stt:
                log.info(f"[LATENCY] ║   - STT processing: {stt:.0f}ms")
            if rag:
                log.info(f"[LATENCY] ║   - RAG retrieval: {rag:.0f}ms")
            if llm:
                log.info(f"[LATENCY] ║   - LLM generation: {llm:.0f}ms")
            if tts:
                log.info(f"[LATENCY] ║   - TTS generation: {tts:.0f}ms")

        response_playback = metrics.get(self.RESPONSE_PLAYBACK_LATENCY, 0)
        if response_playback or total_response:
            log.info(f"[LATENCY] ║ RESPONSE DELIVERY:")
            if response_playback:
                log.info(f"[LATENCY] ║   - Playback latency: {response_playback:.0f}ms")
            log.info(f"[LATENCY] ║   - Total response latency: {total_response:.0f}ms (target: <2500ms)")

        log.info(f"[LATENCY] ╚════════════════════════════════════╝")

    def get_percentile(self, metric_name: str, percentile: int) -> Optional[float]:
        """
        Get percentile value for a metric across all calls
        
        Args:
            metric_name: Metric name
            percentile: Percentile (0-100)
            
        Returns:
            Metric value or None if not available
        """
        values = sorted(self.latency_buckets[metric_name])
        if not values:
            return None

        index = int(len(values) * (percentile / 100.0))
        return values[min(index, len(values) - 1)]

    def get_stats(self, metric_name: str) -> Dict[str, float]:
        """
        Get statistics for a metric across all calls
        
        Args:
            metric_name: Metric name
            
        Returns:
            Dictionary with min, max, avg, p50, p95, p99
        """
        values = self.latency_buckets[metric_name]
        if not values:
            return {}

        sorted_values = sorted(values)

        stats = {
            "count": len(values),
            "min": min(values),
            "max": max(values),
            "avg": sum(values) / len(values),
            "p50": self.get_percentile(metric_name, 50) or 0,
            "p95": self.get_percentile(metric_name, 95) or 0,
            "p99": self.get_percentile(metric_name, 99) or 0,
        }

        return stats

    def cleanup(self, call_id: str) -> None:
        """
        Clean up metrics for completed call
        
        Args:
            call_id: Call identifier
        """
        if call_id in self.metrics:
            del self.metrics[call_id]
        if call_id in self.milestones:
            del self.milestones[call_id]

        log.debug(f"[LATENCY] Cleaned up metrics for {call_id}")

_latency_metrics = None

def get_latency_metrics() -> LatencyMetrics:
    """Get or create global latency metrics instance"""
    global _latency_metrics
    if _latency_metrics is None:
        _latency_metrics = LatencyMetrics()
    return _latency_metrics
