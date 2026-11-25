"""
Real-Time Media Service
Manages bidirectional audio streaming between Asterisk and Python.

Audio paths:
  Caller : RTP RX (8 kHz PCMU) -> rx_buffer -> codec pipeline (16 kHz PCM16) -> Gemini
  Reply  : Gemini (24 kHz PCM16) -> 8 kHz mu-law -> tx_queue -> RTP TX -> caller
"""

from __future__ import annotations

import asyncio
import struct
import time
import logging
from datetime import datetime
from typing import Optional, Dict, Tuple, Callable
from collections import deque
from dataclasses import dataclass
import socket

from ..core.config import (
    RTP_FRAME_SIZE, RTP_SAMPLE_RATE, RTP_HDR_FMT,
    RTP_COMFORT_NOISE_ULAW, log, MY_PC_IP, RTP_START_PORT, RTP_END_PORT,
    RTP_PORT_QUARANTINE_DURATION_S, LOCAL_RTP_IP, GREETING_RTP_WAIT_S,
    START_PORT, END_PORT, RTP_QUEUE_SIZE
)

# Receive-path tuning
RX_BUFFER_MAX_FRAMES = 500        # 10 s of 20 ms frames
JITTER_BUFFER_DEPTH = 3           # hold up to 3 out-of-order packets (~60 ms)
JITTER_MAX_CONCEAL_FRAMES = 5     # fill gaps up to 100 ms with silence
ULAW_SILENCE_FRAME = b'\xff' * RTP_FRAME_SIZE


def parse_rtp_packet(data: bytes) -> Optional[Tuple[int, int, int, int, bytes]]:
    """
    Parse an RTP packet per RFC 3550 (CSRC list, header extension, padding).
    Returns (payload_type, seq, timestamp, ssrc, payload) or None if malformed.
    """
    if len(data) < 12:
        return None
    b0 = data[0]
    if (b0 >> 6) != 2:
        return None
    has_padding = bool(b0 & 0x20)
    has_extension = bool(b0 & 0x10)
    csrc_count = b0 & 0x0F
    pt = data[1] & 0x7F
    seq, ts, ssrc = struct.unpack('!HII', data[2:12])

    offset = 12 + 4 * csrc_count
    if len(data) < offset:
        return None
    if has_extension:
        if len(data) < offset + 4:
            return None
        ext_words = struct.unpack('!H', data[offset + 2:offset + 4])[0]
        offset += 4 + 4 * ext_words
        if len(data) < offset:
            return None

    end = len(data)
    if has_padding:
        pad_len = data[-1]
        if pad_len == 0 or offset + pad_len > end:
            return None
        end -= pad_len

    return pt, seq, ts, ssrc, data[offset:end]


@dataclass
class MediaConfig:
    """Configuration for a media session"""
    call_id: str
    channel_id: str
    external_media_id: str
    bridge_id: str
    user_id: int
    campaign_id: int
    dnid: str
    language: str = "en-IN"
    codec: int = 0
    sample_rate: int = 8000
    frame_size: int = 160


class MediaSession:
    """Manages a single call's bidirectional RTP audio streaming."""

    def __init__(self, config: MediaConfig):
        self.config = config
        self.active = False

        self.udp_socket: Optional[socket.socket] = None
        self.local_port: Optional[int] = None
        self.remote_addr: Optional[Tuple[str, int]] = None

        self.first_packet_event: Optional[asyncio.Event] = None
        self.first_packet_received = False

        self.rtp_seq = 1
        self.rtp_ts = int(time.time()) % 0xFFFFFFFF
        self.rtp_ssrc = int(time.time() * 1000) % 0xFFFFFFFF

        self.rx_buffer = deque(maxlen=RX_BUFFER_MAX_FRAMES)

        # Small jitter buffer: reorders by RTP sequence and drops duplicates
        self._jb_packets: Dict[int, bytes] = {}
        self._jb_next_seq: Optional[int] = None
        self._jb_ssrc: Optional[int] = None
        self.rtp_seq_gaps = 0
        self.rtp_seq_reorders = 0
        self.rtp_duplicates = 0
        self.rtp_late_drops = 0

        # Echo-tail discard window after TTS playback (legacy TTS path)
        self._rx_discard_until = 0.0
        self._tx_last_send_time = 0.0
        self._tx_generation = 0

        self.tx_queue = asyncio.Queue(maxsize=RTP_QUEUE_SIZE)

        self._redis_session_lock = asyncio.Lock()
        self._tx_metrics_lock = asyncio.Lock()

        self.state = "INIT"
        self.current_task = None
        self.stt_partial = ""
        self.stt_final = ""

        self.packets_received = 0
        self.packets_sent = 0
        self.packets_dropped_no_remote_addr = 0
        self.packets_failed_send = 0
        self.created_at = time.time()

        self.silence_detection_active = False
        self.silence_start_time = None
        self.silence_timeout_sec = 4.5

        # Caller muting during legacy TTS playback.
        # Not set on the Gemini Live path, so caller audio always reaches Gemini.
        self.is_ai_speaking = False
        self.ai_speaking_start_time = None

        log.info(f"[MEDIA-SESSION] Created: call_id={config.call_id}, external_media={config.external_media_id}")

    async def initialize_socket(self, local_port: int) -> bool:
        """
        Initialize the UDP socket for RTP.
        Reuse flags allow immediate rebind after close. Bind to MY_PC_IP, not 0.0.0.0,
        so Asterisk knows exactly where to send packets.
        """
        try:
            self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

            try:
                self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            except (AttributeError, OSError) as e:
                log.warning(f"[MEDIA-SESSION] Failed to set SO_REUSEADDR: {e}")

            try:
                if hasattr(socket, 'SO_REUSEPORT'):
                    self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except (AttributeError, OSError) as e:
                log.warning(f"[MEDIA-SESSION] Failed to set SO_REUSEPORT: {e}")

            self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 2097152)
            self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1048576)

            self.udp_socket.bind((MY_PC_IP, local_port))
            self.udp_socket.setblocking(False)

            self.local_port = local_port
            self.active = True

            log.info(f"[MEDIA-SESSION] UDP socket initialized for {self.config.call_id}: {MY_PC_IP}:{local_port}")
            return True
        except Exception as e:
            log.error(f"[MEDIA-SESSION] Socket initialization FAILED: {e}")
            log.error(f"[MEDIA-SESSION] MY_PC_IP={MY_PC_IP} must match an actual network interface IP")
            return False

    async def update_remote_addr(self, ip: str, port: int):
        """Update the remote endpoint (from Asterisk SDP)"""
        self.remote_addr = (ip, port)
        log.info(f"[MEDIA-SESSION] Remote endpoint set: {self.config.call_id} <- {ip}:{port}")

    def _jitter_buffer_push(self, seq: int, ssrc: int, payload: bytes) -> list:
        """
        Reordering jitter buffer.
        - Duplicates and already-played packets are dropped.
        - Out-of-order packets are held until the gap fills (up to JITTER_BUFFER_DEPTH).
        - Short real gaps are filled with mu-law silence; long gaps are skipped.
        Returns the payloads ready to play, in sequence order.
        """
        if self._jb_ssrc != ssrc or self._jb_next_seq is None:
            if self._jb_ssrc is not None and self._jb_ssrc != ssrc:
                log.info(f"[MEDIA-RX] SSRC changed {self._jb_ssrc} -> {ssrc}, jitter buffer reset")
            self._jb_ssrc = ssrc
            self._jb_packets.clear()
            self._jb_next_seq = seq

        ahead = (seq - self._jb_next_seq) & 0xFFFF
        if ahead >= 0x8000:
            self.rtp_late_drops += 1
            return []
        if seq in self._jb_packets:
            self.rtp_duplicates += 1
            log.debug(f"[MEDIA-RX] Duplicate RTP packet dropped: seq={seq}")
            return []
        if ahead > 0:
            self.rtp_seq_reorders += 1
        self._jb_packets[seq] = payload

        ready = []
        while True:
            nxt = self._jb_next_seq
            if nxt in self._jb_packets:
                ready.append(self._jb_packets.pop(nxt))
                self._jb_next_seq = (nxt + 1) & 0xFFFF
                continue
            if len(self._jb_packets) <= JITTER_BUFFER_DEPTH:
                break
            gap = min(((s - nxt) & 0xFFFF) for s in self._jb_packets)
            self.rtp_seq_gaps += gap
            log.warning(f"[MEDIA-RX] RTP packet loss: {gap} packet(s) missing after seq {(nxt - 1) & 0xFFFF} (~{gap * 20}ms)")
            if gap <= JITTER_MAX_CONCEAL_FRAMES:
                ready.extend([ULAW_SILENCE_FRAME] * gap)
            self._jb_next_seq = (nxt + gap) & 0xFFFF
        return ready

    async def recv_rtp_packets(self):
        """
        Receive RTP packets from Asterisk.
        - Detects the first packet and sets remote_addr (signals first_packet_event)
        - Accepts only PCMU (payload type 0)
        - Buffers caller audio in rx_buffer for the Gemini feed
        - Socket is always closed in the finally block
        """
        try:
            log.info(f"[MEDIA-RX] RTP receive loop STARTED: {self.config.call_id}")
            log.info(f"[MEDIA-RX]    Listening on: {MY_PC_IP}:{self.local_port} (PCMU, PT=0)")

            first_non_pcmu_warning_logged = False
            received_codec_types = set()
            start_log_time = time.time()

            while self.active:
                try:
                    data, addr = self.udp_socket.recvfrom(1024)

                    if self.packets_received == 0:
                        log.info(f"[MEDIA-RX] FIRST RTP PACKET RECEIVED from {addr[0]}:{addr[1]} ({len(data)} bytes)")

                    parsed = parse_rtp_packet(data)
                    if parsed is None:
                        log.debug(f"[MEDIA-RX] Malformed/short RTP packet ({len(data)} bytes), skipping")
                        continue
                    pt, rtp_seq, rtp_ts, rtp_ssrc, payload = parsed

                    if pt != 0:
                        if not first_non_pcmu_warning_logged:
                            codec_name_map = {8: "PCMA (A-law)", 18: "G.729", 116: "SLIN16 (16-bit linear)"}
                            codec_name = codec_name_map.get(pt, f"Unknown (PT={pt})")
                            log.warning(f"[MEDIA-RX] CODEC MISMATCH: expected PCMU (PT=0), received {codec_name}")
                            first_non_pcmu_warning_logged = True
                        received_codec_types.add(pt)
                        continue

                    received_codec_types.add(pt)

                    if not self.first_packet_received:
                        self.first_packet_received = True
                        self.remote_addr = addr
                        log.info(f"[MEDIA-RX] BIDIRECTIONAL RTP ESTABLISHED: {addr[0]}:{addr[1]}, payload {len(payload)} bytes")
                        if self.first_packet_event and not self.first_packet_event.is_set():
                            self.first_packet_event.set()

                    if len(payload) >= RTP_FRAME_SIZE:
                        bytes_per_sample = 1  # mu-law
                        frame_duration_ms = 20
                        detected_sample_rate = int((len(payload) * 1000) / (frame_duration_ms * bytes_per_sample))

                        if len(payload) != RTP_FRAME_SIZE:
                            log.warning(f"[MEDIA-RX] FRAME SIZE MISMATCH: expected {RTP_FRAME_SIZE}, received {len(payload)} bytes (~{detected_sample_rate} Hz)")
                            if len(payload) == 320:
                                log.error("[MEDIA-RX] Asterisk is sending 320-byte frames (16 kHz). Check pjsip.conf/sip.conf: allow=ulaw only")
                        elif self.packets_received % 100 == 0:
                            log.info(f"[MEDIA-RX] Sample rate verification: {detected_sample_rate} Hz (8 kHz)")

                        # Jitter buffer runs on every packet so sequence tracking stays continuous
                        ready_payloads = self._jitter_buffer_push(rtp_seq, rtp_ssrc, payload)
                        self.packets_received += 1

                        # Legacy TTS muting. Only set by send_audio_response(), not on the Gemini path.
                        if self.is_ai_speaking:
                            continue

                        if time.time() < self._rx_discard_until:
                            continue

                        for ready_payload in ready_payloads:
                            if len(self.rx_buffer) == self.rx_buffer.maxlen:
                                log.warning(f"[MEDIA-RX] RX buffer full ({self.rx_buffer.maxlen} frames), oldest frame evicted")
                            self.rx_buffer.append(ready_payload)

                        if self.packets_received % 50 == 0:
                            log.debug(f"[MEDIA-RX] {self.packets_received} packets received from {addr[0]}:{addr[1]}")

                except BlockingIOError:
                    elapsed = time.time() - start_log_time
                    if elapsed > 5 and self.packets_received == 0:
                        log.warning(f"[MEDIA-RX] NO RTP PACKETS RECEIVED after {elapsed:.1f}s on {MY_PC_IP}:{self.local_port}")
                        log.warning("[MEDIA-RX] Check: Asterisk ExternalMedia target, firewall, ARI RTP endpoint")
                        start_log_time = time.time()
                    await asyncio.sleep(0.01)
                except OSError as socket_error:
                    if self.active:
                        log.error(f"[MEDIA-RX] Socket error: {socket_error}")
                    break
                except Exception as e:
                    log.error(f"[MEDIA-RX] Unexpected error: {e}")
                    break

        except Exception as e:
            log.error(f"[MEDIA-RX] recv_rtp_packets FAILED: {e}", exc_info=True)
            self.active = False
        finally:
            log.info(f"[MEDIA-RX] RTP receive loop STOPPED for {self.config.call_id}")
            if self.udp_socket:
                try:
                    self.udp_socket.close()
                except Exception as socket_close_error:
                    log.warning(f"[MEDIA-RX] Error closing socket in finally: {socket_close_error}")

            log.info(f"[MEDIA-RX] FINAL REPORT: packets={self.packets_received}, "
                     f"lost={self.rtp_seq_gaps}, out_of_order={self.rtp_seq_reorders}, "
                     f"duplicates={self.rtp_duplicates}, late={self.rtp_late_drops}, "
                     f"codecs={[f'PT={pt}' for pt in sorted(received_codec_types)]}, "
                     f"first_packet={'yes' if self.first_packet_received else 'never'}")

    async def send_rtp_packet(self, payload: bytes) -> bool:
        """
        Send one RTP packet (V=2, P=0, X=0, CC=0, M=0, PT=0 for PCMU) to remote_addr.
        Returns True on success, False if remote_addr is unknown or the socket fails.
        """
        if not self.remote_addr:
            log.error(
                f"[MEDIA-TX] Cannot send RTP packet: remote_addr is None. "
                f"call_id={self.config.call_id}, first_packet_received={self.first_packet_received}"
            )
            return False

        if not self.udp_socket:
            log.error(f"[MEDIA-TX] Cannot send RTP packet: UDP socket is None. call_id={self.config.call_id}")
            return False

        try:
            header = RTP_HDR_FMT.pack(
                0x80,
                0x00,
                self.rtp_seq & 0xFFFF,
                self.rtp_ts & 0xFFFFFFFF,
                self.rtp_ssrc
            )
            self.udp_socket.sendto(header + payload, self.remote_addr)

            self.rtp_seq = (self.rtp_seq + 1) & 0xFFFF
            self.rtp_ts = (self.rtp_ts + len(payload)) & 0xFFFFFFFF
            self.packets_sent += 1
            return True

        except socket.error as e:
            log.error(
                f"[MEDIA-TX] Socket error sending RTP to {self.remote_addr}: {e}. "
                f"call_id={self.config.call_id}, packet_size={len(payload)}"
            )
            return False
        except Exception as e:
            log.error(f"[MEDIA-TX] Unexpected error sending RTP packet: {e}. call_id={self.config.call_id}")
            return False

    # ------------------------------------------------------------------ #
    # Caller muting (legacy TTS path)
    # ------------------------------------------------------------------ #
    def set_ai_speaking(self, is_speaking: bool, reason: str = ""):
        """
        Toggle caller muting during legacy TTS playback.
        True = mute caller (drop RTP), False = unmute caller.
        Not used by the Gemini Live path.
        """
        try:
            from ..core.config import AUDIO_MUTING_POST_TTS_CLEAR_DELAY_MS

            old_state = self.is_ai_speaking
            self.is_ai_speaking = is_speaking

            if is_speaking:
                self.ai_speaking_start_time = time.time()
                log.info(f"[MEDIA-SESSION] AI SPEAKING: caller muted. Reason: {reason}")
                self.clear_rx_buffer()
            else:
                duration = time.time() - self.ai_speaking_start_time if self.ai_speaking_start_time else 0
                log.info(f"[MEDIA-SESSION] AI SILENT: caller unmuted. Reason: {reason}, spoke {duration:.2f}s")
                if AUDIO_MUTING_POST_TTS_CLEAR_DELAY_MS > 0:
                    self._rx_discard_until = time.time() + AUDIO_MUTING_POST_TTS_CLEAR_DELAY_MS / 1000.0
                self.ai_speaking_start_time = None

            if old_state != is_speaking:
                log.debug(f"[MEDIA-SESSION] State transition: {old_state} -> {is_speaking} ({reason})")
        except Exception as e:
            log.error(f"[MEDIA-SESSION] Error in set_ai_speaking: {e}", exc_info=True)

    def get_ai_speaking_state(self) -> bool:
        return self.is_ai_speaking

    async def handle_barge_in_interruption(self):
        """Unmute the caller immediately when they interrupt legacy TTS playback."""
        try:
            if self.is_ai_speaking:
                log.info("[MEDIA-SESSION] BARGE-IN: caller interrupted AI, unmuting")
                self.set_ai_speaking(False, "Caller interrupted (barge-in detected)")
        except Exception as e:
            log.error(f"[MEDIA-SESSION] Error in handle_barge_in_interruption: {e}", exc_info=True)

    def clear_rx_buffer(self):
        """Discard stale receive audio (buffer poisoning fix)."""
        stale_frames = len(self.rx_buffer)
        self.rx_buffer.clear()
        if stale_frames > 0:
            log.info(f"[MEDIA-SESSION] RX buffer cleared: {stale_frames} stale frames (~{stale_frames * 20}ms)")

    async def get_received_audio_chunk(self, timeout_sec: float = 0.5) -> Optional[bytes]:
        """Pop one received 8 kHz PCMU frame, waiting up to timeout_sec."""
        try:
            start = time.time()
            while len(self.rx_buffer) == 0 and (time.time() - start) < timeout_sec:
                await asyncio.sleep(0.01)
            if self.rx_buffer:
                return self.rx_buffer.popleft()
            return None
        except Exception as e:
            log.error(f"[MEDIA-SESSION] get_received_audio error: {e}")
            return None

    async def get_listener_metrics(self) -> dict:
        return {
            "is_ai_speaking": self.is_ai_speaking,
            "rx_buffer_size": len(self.rx_buffer),
            "packets_received": self.packets_received,
        }

    # ------------------------------------------------------------------ #
    # Beeps and silence detection
    # ------------------------------------------------------------------ #
    async def _queue_beep(self, frequency_hz: int = 1000, duration_ms: int = 200, amplitude: float = 0.5):
        """Queue a confirmation beep without blocking the call flow."""
        try:
            from ..transport.rtp import generate_beep_frames

            beep_frames = generate_beep_frames(
                duration_ms=duration_ms,
                frequency_hz=frequency_hz,
                amplitude=amplitude
            )
            if not beep_frames:
                log.debug("[MEDIA-BEEP] Beep generation failed")
                return

            for frame in beep_frames:
                try:
                    self.tx_queue.put_nowait(frame)
                except asyncio.QueueFull:
                    log.debug("[MEDIA-BEEP] Queue full, beep frames skipped")
                    break
        except Exception as e:
            log.debug(f"[MEDIA-BEEP] Error: {e}")

    async def start_silence_detection(self, timeout_sec: float = 4.5):
        self.silence_start_time = time.time()
        self.silence_timeout_sec = timeout_sec
        self.silence_detection_active = True

    async def stop_silence_detection(self):
        self.silence_detection_active = False

    def check_silence_timeout(self) -> bool:
        try:
            if not self.silence_detection_active or self.silence_start_time is None:
                return False
            return (time.time() - self.silence_start_time) > self.silence_timeout_sec
        except Exception:
            return False

    # ------------------------------------------------------------------ #
    # Legacy pre-recorded audio playback (greeting/TTS bytes in 160-byte frames)
    # ------------------------------------------------------------------ #
    async def send_audio_response(self, audio_bytes: bytes, reset_rtp_state: bool = True,
                                  wait_for_completion: bool = False, add_beep_after: bool = False):
        """Queue pre-encoded 8 kHz mu-law audio (160-byte aligned) for transmission."""
        try:
            if not audio_bytes:
                log.warning("[MEDIA-TX] send_audio_response called with empty audio")
                return

            from ..core.config import AUDIO_MUTING_ENABLED
            self._tx_generation += 1
            playback_generation = self._tx_generation
            if AUDIO_MUTING_ENABLED:
                self.set_ai_speaking(True, "TTS response transmission starting")

            if len(audio_bytes) % RTP_FRAME_SIZE != 0:
                remainder = len(audio_bytes) % RTP_FRAME_SIZE
                log.error(f"[MEDIA-TX] Audio not frame-aligned: {len(audio_bytes)} bytes, remainder {remainder}. Rejected")
                return

            from ..core.config import PREFLUSH_RX_BUFFER_STALE_FRAMES
            if self.rx_buffer:
                flush_limit = min(len(self.rx_buffer), PREFLUSH_RX_BUFFER_STALE_FRAMES)
                for _ in range(flush_limit):
                    self.rx_buffer.popleft()

            if reset_rtp_state:
                self.rtp_seq = (int(time.time()) * 100) % 0xFFFF
                self.rtp_ts = (int(time.time() * 1000) * 8) % 0xFFFFFFFF

            frames_queued = 0
            for i in range(0, len(audio_bytes), RTP_FRAME_SIZE):
                chunk = audio_bytes[i:i + RTP_FRAME_SIZE]
                if len(chunk) < RTP_FRAME_SIZE:
                    chunk += b'\xff' * (RTP_FRAME_SIZE - len(chunk))
                try:
                    self.tx_queue.put_nowait(chunk)
                    frames_queued += 1
                except asyncio.QueueFull:
                    log.error(f"[MEDIA-TX] TX queue full at frame {frames_queued}")
                    break

            max_playback_wait = (self.tx_queue.qsize() * 0.02) + 5.0

            if wait_for_completion:
                await self._wait_for_tx_drain(max_playback_wait)

                from ..services.intelligent_beep_manager import get_intelligent_beep_manager, BeepContext
                beep_manager = get_intelligent_beep_manager()
                if beep_manager and add_beep_after:
                    should_beep = await beep_manager.should_play_beep(
                        self.config.call_id,
                        BeepContext.NORMAL_CONVERSATION
                    )
                    if should_beep:
                        from ..core.config import (
                            BEEP_AFTER_RESPONSE_DURATION_MS,
                            BEEP_AFTER_RESPONSE_FREQUENCY_HZ,
                            BEEP_AFTER_RESPONSE_AMPLITUDE,
                        )
                        await self._queue_beep(
                            frequency_hz=BEEP_AFTER_RESPONSE_FREQUENCY_HZ,
                            duration_ms=BEEP_AFTER_RESPONSE_DURATION_MS,
                            amplitude=BEEP_AFTER_RESPONSE_AMPLITUDE,
                        )
                    await beep_manager.log_beep_event(self.config.call_id, BeepContext.NORMAL_CONVERSATION, should_beep)

            from ..core.config import AUDIO_MUTING_POST_TTS_CLEAR_DELAY_MS
            if AUDIO_MUTING_ENABLED:
                if wait_for_completion:
                    await self._finish_playback_and_unmute(playback_generation, max_playback_wait)
                    if AUDIO_MUTING_POST_TTS_CLEAR_DELAY_MS > 0:
                        await asyncio.sleep(AUDIO_MUTING_POST_TTS_CLEAR_DELAY_MS / 1000.0)
                else:
                    asyncio.create_task(
                        self._finish_playback_and_unmute(playback_generation, max_playback_wait)
                    )
        except Exception as e:
            log.error(f"[MEDIA-SESSION] send_audio_response error: {e}", exc_info=True)

    async def _wait_for_tx_drain(self, max_wait_sec: float) -> bool:
        """Wait until the TX queue is empty and the last frame has been sent."""
        start = time.time()
        while self.active and (time.time() - start) < max_wait_sec:
            if self.tx_queue.empty() and (time.time() - self._tx_last_send_time) >= 0.04:
                return True
            await asyncio.sleep(0.02)
        return self.tx_queue.empty()

    async def _finish_playback_and_unmute(self, generation: int, max_wait_sec: float):
        """Unmute the caller after the TX queue drains. A newer playback keeps the mute."""
        try:
            drained = await self._wait_for_tx_drain(max_wait_sec)
            if generation != self._tx_generation:
                return
            if not self.is_ai_speaking:
                return
            self.set_ai_speaking(False, f"TTS playback finished (tx drained={drained})")
        except Exception as e:
            log.error(f"[MEDIA-TX] _finish_playback_and_unmute error: {e}", exc_info=True)
            self.is_ai_speaking = False

    # ------------------------------------------------------------------ #
    # TX pacing loop
    # ------------------------------------------------------------------ #
    async def transmit_audio_loop(self):
        """
        Send tx_queue frames to Asterisk at real-time pace (one 160-byte frame per 20 ms).
        Frames are re-queued while remote_addr is unknown. Send errors are counted, not fatal.
        TX sources: Gemini Live reply audio (via enqueue_ulaw_to_rtp), greeting, and beeps.
        """
        frames_processed = 0
        frames_re_queued = 0
        first_frame_time = None

        try:
            log.info(f"[MEDIA-TX] Transmit loop started for {self.config.call_id}")

            while self.active:
                try:
                    try:
                        chunk = await asyncio.wait_for(self.tx_queue.get(), timeout=0.05)
                    except asyncio.TimeoutError:
                        continue

                    if not self.remote_addr:
                        try:
                            await asyncio.wait_for(self.tx_queue.put(chunk), timeout=0.5)
                            frames_re_queued += 1
                        except asyncio.TimeoutError:
                            log.warning("[MEDIA-TX] Could not re-queue frame (queue full)")
                            continue
                        await asyncio.sleep(0.01)
                        continue

                    success = await self.send_rtp_packet(chunk)
                    frames_processed += 1
                    self._tx_last_send_time = time.time()

                    if frames_processed == 1:
                        first_frame_time = time.time()
                        log.info(f"[MEDIA-TX] FIRST TX FRAME SENT to {self.remote_addr[0]}:{self.remote_addr[1]}")

                    if not success:
                        self.packets_failed_send += 1
                        log.error(f"[MEDIA-TX] Frame send failed (continuing): {self.packets_failed_send} total failures")
                        continue

                    if frames_processed % 100 == 0:
                        elapsed = time.time() - first_frame_time if first_frame_time else 0
                        expected_time = (frames_processed * 20) / 1000.0
                        log.info(f"[MEDIA-TX] Checkpoint: {frames_processed} frames, elapsed {elapsed:.2f}s "
                                 f"(expected {expected_time:.2f}s), tx_queue={self.tx_queue.qsize()}")

                    await asyncio.sleep(0.02)

                except Exception as e:
                    log.error(f"[MEDIA-TX] Loop error: {e}")
                    await asyncio.sleep(0.01)

        except Exception as e:
            log.error(f"[MEDIA-SESSION] transmit_audio_loop FAILED: {e}", exc_info=True)
            self.active = False
        finally:
            log.info(f"[MEDIA-TX] Transmit loop stopped for {self.config.call_id}")
            if self.udp_socket:
                try:
                    self.udp_socket.close()
                except Exception as socket_close_error:
                    log.warning(f"[MEDIA-TX] Error closing socket in finally: {socket_close_error}")

            log.info(f"[MEDIA-TX] FINAL REPORT: processed={frames_processed}, re_queued={frames_re_queued}, "
                     f"failed={self.packets_failed_send}, total_sent={self.packets_sent}, "
                     f"audio={(frames_processed * 20) / 1000:.1f}s")

    async def close(self):
        """Stop the RX/TX loops and release the UDP socket."""
        try:
            self.active = False
            await asyncio.sleep(0.1)

            if self.udp_socket:
                try:
                    self.udp_socket.close()
                    log.info("[MEDIA-SESSION] Socket closed successfully")
                except OSError as os_error:
                    if "Bad file descriptor" in str(os_error) or "cannot switch" in str(os_error):
                        log.debug("[MEDIA-SESSION] Socket already closed (expected)")
                    else:
                        log.warning(f"[MEDIA-SESSION] Error closing socket: {os_error}")
                except Exception as e:
                    log.warning(f"[MEDIA-SESSION] Unexpected error closing socket: {e}")
                finally:
                    self.udp_socket = None

            self.remote_addr = None
            duration = time.time() - self.created_at

            log.info(f"[MEDIA-SESSION] Session closed: {self.config.call_id}")
            log.info(f"[MEDIA-SESSION]    Duration: {duration:.1f}s, RX={self.packets_received}, "
                     f"TX={self.packets_sent}, failed={self.packets_failed_send}")
        except Exception as e:
            log.error(f"[MEDIA-SESSION] Error in close(): {e}", exc_info=True)
            try:
                if self.udp_socket:
                    self.udp_socket.close()
            except Exception:
                pass
            finally:
                self.udp_socket = None
                self.active = False

    # ------------------------------------------------------------------ #
    # Gemini Live integration
    # ------------------------------------------------------------------ #
    async def stream_audio_via_gemini(
        self,
        gemini_session,
        on_response_audio: Optional[Callable[[bytes], None]] = None,
        on_response_text: Optional[Callable[[str], None]] = None
    ) -> bool:
        """
        Run the Gemini Live conversation for this call.

        Caller path: RTP (8 kHz PCMU) -> 16 kHz PCM16 -> gemini_session.add_audio_input()
        Reply path:  Gemini (24 kHz) -> 8 kHz mu-law -> gemini_session.enqueue_ulaw_to_rtp()
                     -> this session's tx_queue -> transmit_audio_loop() -> caller

        on_response_audio is accepted for compatibility and not used.
        """
        try:
            from ..services.audio_codec_pipeline import get_codec_pipeline
            from ..core.client_config import ClientConfig

            log.info(f"[MEDIA-SESSION] Starting Gemini conversation for call {self.config.call_id}")

            # Attach this call's TX queue before the conversation starts
            if hasattr(gemini_session, "attach_media"):
                gemini_session.attach_media(self)

            if on_response_audio is not None:
                log.debug("[MEDIA-SESSION] on_response_audio ignored: reply audio goes straight to RTP")

            async def feed_rtp_to_gemini():
                """Read caller RTP frames, convert 8 kHz PCMU -> 16 kHz PCM16, feed Gemini."""
                try:
                    codec_pipeline = await get_codec_pipeline(self.config.call_id)
                    frame_count = 0

                    while self.active and gemini_session.session_active:
                        audio_chunk = await self.get_received_audio_chunk(timeout_sec=0.1)
                        if audio_chunk:
                            pcm_16k = await codec_pipeline.process_rtp_rx_frame(audio_chunk)
                            if pcm_16k:
                                await gemini_session.add_audio_input(pcm_16k)
                                frame_count += 1
                                if frame_count % 500 == 0:
                                    log.debug(f"[MEDIA-SESSION] Fed {frame_count} caller frames to Gemini")
                        await asyncio.sleep(0.001)

                    log.info(f"[MEDIA-SESSION] Caller feed stopped after {frame_count} frames")
                except Exception as e:
                    log.error(f"[MEDIA-SESSION] Error feeding RTP to Gemini: {e}", exc_info=True)

            async def run_gemini_conversation():
                """Run the Live session for the whole call, greeting first."""
                try:
                    greeting_text = ClientConfig.get_greeting()
                    success = await gemini_session.process_audio_stream(
                        on_response_text=on_response_text,
                        greeting_text=greeting_text,
                    )
                    if success:
                        log.info("[MEDIA-SESSION] Gemini conversation completed")
                    else:
                        log.warning("[MEDIA-SESSION] Gemini conversation returned False")
                except Exception as e:
                    log.error(f"[MEDIA-SESSION] Error in Gemini conversation: {e}", exc_info=True)

            await asyncio.gather(
                feed_rtp_to_gemini(),
                run_gemini_conversation(),
                return_exceptions=True,
            )
            log.info(f"[MEDIA-SESSION] Gemini streaming ended for call {self.config.call_id}")
            return True

        except Exception as e:
            log.error(f"[MEDIA-SESSION] Error starting Gemini streaming: {e}", exc_info=True)
            return False


class MediaServiceManager:
    """Manages multiple concurrent media sessions."""

    def __init__(self):
        self.port_pool: set = set(range(RTP_START_PORT, RTP_END_PORT + 1, 2))
        self.port_quarantine: Dict[int, float] = {}
        self.sessions: Dict[str, MediaSession] = {}
        self.lock: asyncio.Lock = asyncio.Lock()

        self._rtp_first_packet_events: Dict[str, asyncio.Event] = {}
        self._rtp_remote_ports: Dict[str, Tuple[str, int]] = {}

        log.info(f"[MEDIA-SERVICE] Manager initialized. Ports: {RTP_START_PORT}-{RTP_END_PORT}, "
                 f"quarantine: {RTP_PORT_QUARANTINE_DURATION_S}s")

    async def allocate_port(self) -> Optional[int]:
        """
        Allocate an RTP port: from the pre-allocated pool first, then a dynamic
        free port. Returns None if nothing is available.
        """
        async with self.lock:
            if self.port_pool:
                port = self.port_pool.pop()
                log.debug(f"[MEDIA-SERVICE] Allocated port from pool: {port}")
                return port

            log.info("[MEDIA-SERVICE] Port pool empty, attempting dynamic port selection")
            dynamic_port = await self._find_available_port()
            if dynamic_port:
                log.info(f"[MEDIA-SERVICE] Dynamically allocated port: {dynamic_port}")
                return dynamic_port

            log.error("[MEDIA-SERVICE] No RTP ports available (pool empty, no dynamic ports)")
            return None

    async def _find_available_port(self, start_range: int = 10000, end_range: int = 20000) -> Optional[int]:
        """Find a free UDP port by test-binding within the range."""
        for attempt in range(start_range, end_range, 2):
            try:
                test_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                try:
                    test_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                except (AttributeError, OSError):
                    pass
                try:
                    if hasattr(socket, 'SO_REUSEPORT'):
                        test_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                except (AttributeError, OSError):
                    pass

                test_socket.bind((MY_PC_IP, attempt))
                test_socket.close()
                return attempt
            except OSError:
                continue
            except Exception as e:
                log.warning(f"[MEDIA-SERVICE] Error testing port {attempt}: {e}")
                continue

        log.error(f"[MEDIA-SERVICE] No available ports in dynamic range {start_range}-{end_range}")
        return None

    async def release_port(self, port: int):
        async with self.lock:
            if port not in self.port_pool:
                self.port_pool.add(port)

    def get_first_packet_event(self, call_id: str) -> Optional[asyncio.Event]:
        return self._rtp_first_packet_events.get(call_id)

    def get_remote_port(self, call_id: str) -> Optional[Tuple[str, int]]:
        return self._rtp_remote_ports.get(call_id)

    def set_remote_port(self, call_id: str, ip: str, port: int):
        self._rtp_remote_ports[call_id] = (ip, port)
        log.debug(f"[MEDIA-SERVICE] Tracked Asterisk RTP port for {call_id}: {ip}:{port}")

    async def create_session(self, config: MediaConfig) -> Optional[MediaSession]:
        """Create a media session, bind its socket, and start the RX/TX loops."""
        try:
            port = await self.allocate_port()
            if not port:
                log.error("[MEDIA-SERVICE] No RTP ports available")
                return None

            session = MediaSession(config)
            if not await session.initialize_socket(port):
                await self.release_port(port)
                return None

            first_packet_event = asyncio.Event()
            self._rtp_first_packet_events[config.call_id] = first_packet_event
            session.first_packet_event = first_packet_event

            async with self.lock:
                self.sessions[config.call_id] = session

            asyncio.create_task(session.recv_rtp_packets())
            asyncio.create_task(session.transmit_audio_loop())

            log.info(f"[MEDIA-SERVICE] RTP loops started for {config.call_id} on {MY_PC_IP}:{port}")
            log.info(f"[MEDIA-SERVICE] Asterisk must send RTP to {MY_PC_IP}:{port}")
            return session

        except Exception as e:
            log.error(f"[MEDIA-SERVICE] create_session error: {e}")
            return None

    async def get_session(self, call_id: str) -> Optional[MediaSession]:
        async with self.lock:
            return self.sessions.get(call_id)

    async def close_session(self, call_id: str):
        try:
            async with self.lock:
                session = self.sessions.pop(call_id, None)

            if session:
                await session.close()
                if session.local_port:
                    await self.release_port(session.local_port)

                self._rtp_first_packet_events.pop(call_id, None)
                self._rtp_remote_ports.pop(call_id, None)
                log.info(f"[MEDIA-SERVICE] Session closed: {call_id}")
        except Exception as e:
            log.error(f"[MEDIA-SERVICE] close_session error: {e}")

    async def release_call_resources(self, call_id: str) -> bool:
        """Release all resources for a call (session, RTP port, codec pipeline)."""
        try:
            log.info(f"[MEDIA-SERVICE] Releasing resources for call: {call_id}")

            # Read the port before the session is removed
            async with self.lock:
                session = self.sessions.get(call_id)
                port = session.local_port if session else None

            await self.close_session(call_id)

            try:
                from ..services.audio_codec_pipeline import cleanup_codec_pipeline
                await cleanup_codec_pipeline(call_id)
            except Exception as e:
                log.warning(f"[MEDIA-SERVICE] Error cleaning codec pipeline: {e}")

            if port is not None and port not in self.port_quarantine:
                self.port_quarantine[port] = datetime.now().timestamp()

            log.info(f"[MEDIA-SERVICE] Resources released for call {call_id}")
            return True

        except Exception as e:
            log.error(f"[MEDIA-SERVICE] Error releasing resources: {e}")
            return False

    async def shutdown(self):
        try:
            for call_id in list(self.sessions.keys()):
                await self.close_session(call_id)
            log.info("[MEDIA-SERVICE] Shutdown complete")
        except Exception as e:
            log.error(f"[MEDIA-SERVICE] shutdown error: {e}")


_media_service: Optional[MediaServiceManager] = None


async def init_media_service():
    """Initialize the media service manager."""
    global _media_service
    _media_service = MediaServiceManager()
    log.info("[MEDIA-SERVICE] Initialized")
    return _media_service


def get_media_service() -> Optional[MediaServiceManager]:
    """Get the global media service manager."""
    return _media_service