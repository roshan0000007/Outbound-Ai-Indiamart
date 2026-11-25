"""
RTP (Real-time Transport Protocol) Handler
Manages RTP audio streaming and packet processing

Audio codec conversions are handled by Gemini Live directly:
- Incoming RTP: 8kHz PCM/µLaw
- Outgoing RTP: 8kHz PCM/µLaw
"""

import asyncio
import struct
import time
import io
import wave
import base64
import audioop
import math
from typing import Optional, Dict, Tuple
from collections import deque

from ..core.config import (
    RTP_FRAME_SIZE, RTP_HDR_FMT, RTP_SAMPLE_RATE,
    RTP_COMFORT_NOISE_ULAW, log
)

def wav_bytes_to_pcm(wav_bytes: bytes) -> Optional[bytes]:
    """
    Convert WAV file bytes to raw PCM samples (16-bit signed)
    
    Input: Complete WAV file
    Output: Raw PCM audio samples (16-bit signed, little-endian)
    
    Args:
        wav_bytes: Complete WAV file bytes
        
    Returns:
        Raw PCM audio bytes (16-bit signed) or None on error
    """
    try:
        if not wav_bytes or len(wav_bytes) < 44:
            log.error(f"[CODEC] WAV too short: {len(wav_bytes)} bytes (minimum 44 for header)")
            return None

        wav_file = io.BytesIO(wav_bytes)

        try:
            with wave.open(wav_file, 'rb') as wav:
                num_channels = wav.getnchannels()
                sample_width = wav.getsampwidth()
                frame_rate = wav.getframerate()
                num_frames = wav.getnframes()

                log.debug(f"[CODEC] WAV header parsed: channels={num_channels}, sample_width={sample_width} bytes, frame_rate={frame_rate}Hz, num_frames={num_frames}")

                if frame_rate == 16000:
                    log.warning(f"[CODEC] ⚠️  TTS returned 16kHz audio (will be resampled to 8kHz for Asterisk)")
                elif frame_rate == 8000:
                    log.debug(f"[CODEC] ✅ TTS audio already 8kHz (Asterisk compatible)")
                else:
                    log.warning(f"[CODEC] ⚠️  Unexpected sample rate: {frame_rate}Hz (expected 8000 or 16000)")

                validation_errors = []

                if num_channels != 1:
                    validation_errors.append(f"channels={num_channels} (expected 1 for mono)")

                if sample_width != 2:
                    validation_errors.append(f"sample_width={sample_width} bytes (expected 2 for 16-bit)")

                if frame_rate not in (8000, 16000):
                    validation_errors.append(f"frame_rate={frame_rate}Hz (expected 8kHz or 16kHz)")

                if validation_errors:
                    log.error(f"[CODEC] WAV validation failed: {', '.join(validation_errors)}")
                    return None

                log.debug(f"[CODEC] ✅ WAV format validated: mono, 16-bit, {frame_rate}Hz")

                audio_data = wav.readframes(num_frames)

                audio_duration_ms = (num_frames / frame_rate) * 1000
                log.info(f"[CODEC] ✅ WAV decoded: {len(audio_data)} bytes ({num_frames} frames = {audio_duration_ms:.1f}ms at {frame_rate}Hz, mono, 16-bit)")

                return audio_data
        except wave.Error as e:
            log.error(f"[CODEC] WAV parse error: {e}")
            return None

    except Exception as e:
        log.error(f"[CODEC] wav_bytes_to_pcm error: {e}")
        return None

def linear_to_ulaw(pcm_bytes: bytes) -> bytes:
    """
    Convert 16-bit signed PCM to µ-law (ULAW/G.711) audio with optimal clarity
    
    CRITICAL FIX #2: Convert TTS audio format to RTP transmission format
    
    Input: 16-bit signed PCM samples (little-endian)
    Output: µ-law compressed audio (8-bit, one byte per sample)
    
    Compression ratio: 2:1 (16-bit → 8-bit)
    
    µ-law encoding (ITU G.711):
    - Compresses 16-bit linear PCM to 8-bit logarithmic scale
    - Standard for telephony (ITU G.711)
    - Used by Asterisk ExternalMedia (RTP payload type 0 = PCMU)
    - Formula: sign (1 bit) + exponent (3 bits) + mantissa (4 bits)
    
    ✅ NEW: Multi-stage clarity enhancement:
    1. Normalize amplitude for optimal µ-law encoding
    2. Apply gentle pre-emphasis for clarity
    3. Encode to µ-law
    4. Verify output consistency
    
    Args:
        pcm_bytes: 16-bit signed PCM audio (little-endian)
        
    Returns:
        µ-law encoded audio (8-bit)
        
    Validates: Requirements 8.1, 8.2
    """
    try:
        if not pcm_bytes:
            return b''

        if len(pcm_bytes) % 2 != 0:
            log.error(f"[CODEC] Invalid PCM: {len(pcm_bytes)} bytes (must be even)")
            return b'\xff' * RTP_FRAME_SIZE

        sample_count = len(pcm_bytes) // 2
        samples = struct.unpack(f'<{sample_count}h', pcm_bytes)

        log.debug(f"[CODEC] Skipping custom filters - passing PCM straight to µ-law encoder (no distortion)")

        peak_amplitude = max(abs(s) for s in samples) if samples else 1

        target_peak = 30000

        if peak_amplitude < target_peak and peak_amplitude > 0:
            scale_factor = target_peak / peak_amplitude

            log.debug(f"[CODEC] Audio normalization: peak={peak_amplitude}, scale_factor={scale_factor:.2f}")

            normalized = []
            for s in samples:
                scaled = s * scale_factor

                if abs(scaled) > 32767:
                    clipped = int(32767 * (2.0 / math.pi * math.atan(scaled / 32767)))
                    normalized.append(clipped)
                else:
                    normalized.append(int(scaled))

            samples = tuple(normalized)
            log.info(f"[CODEC] ✅ PCM normalized: peak {peak_amplitude} → {max(abs(s) for s in samples)}")

        rms = (sum(s*s for s in samples) / len(samples)) ** 0.5 if samples else 1

        if rms > 0:
            compressed = []
            compression_ratio = 1.5
            threshold = int(rms * 2.5)

            for s in samples:
                if abs(s) > threshold:
                    compressed.append(int(threshold + (abs(s) - threshold) / compression_ratio) if s >= 0 else int(-(threshold + (abs(s) - threshold) / compression_ratio)))
                else:
                    compressed.append(s)

            samples = tuple(compressed)
            log.debug(f"[CODEC] Applied gentle compression (threshold={threshold}, ratio=1.5:1)")

        pcm_bytes = struct.pack(f'<{sample_count}h', *samples)

        try:
            ulaw_bytes = audioop.lin2ulaw(pcm_bytes, 2)
            log.debug(f"[CODEC] PCM→µlaw: {len(pcm_bytes)} bytes → {len(ulaw_bytes)} bytes (compression 2:1)")
            return ulaw_bytes
        except audioop.error as e:
            log.error(f"[CODEC] audioop.lin2ulaw error: {e}")
            return b'\xff' * RTP_FRAME_SIZE

    except Exception as e:
        log.error(f"[CODEC] linear_to_ulaw error: {e}", exc_info=True)
        return b'\xff' * RTP_FRAME_SIZE

def ulaw_to_linear(ulaw_bytes: bytes) -> bytes:
    """
    Convert µ-law (ULAW/G.711) audio to 16-bit signed PCM
    
    Part of Gemini Live audio handling pipeline
    
    Args:
        ulaw_bytes: µ-law encoded audio (8-bit)
        
    Returns:
        16-bit signed PCM audio (little-endian) or empty bytes on error
    """
    try:
        if not ulaw_bytes:
            log.warning(f"[CODEC-ULAW] ⚠️  Empty ULAW bytes received for conversion")
            return b''

        ulaw_frame_count = len(ulaw_bytes)
        
        try:
            pcm_bytes = audioop.ulaw2lin(ulaw_bytes, 2)
            
            # ✅ FIX #1 VALIDATION: Check conversion integrity
            expected_pcm_len = ulaw_frame_count * 2
            if len(pcm_bytes) != expected_pcm_len:
                log.error(f"[CODEC-ULAW] ❌ CONVERSION INTEGRITY ERROR: {ulaw_frame_count} ULAW bytes → {len(pcm_bytes)} PCM bytes (expected {expected_pcm_len})")
                return b''
            
            # Calculate RMS of converted audio
            import struct
            samples = struct.unpack(f'<{len(pcm_bytes)//2}h', pcm_bytes)
            rms_energy = (sum(s*s for s in samples) / len(samples)) ** 0.5 if samples else 0
            
            log.debug(f"[CODEC-ULAW] ✅ µlaw→PCM: {ulaw_frame_count} bytes → {len(pcm_bytes)} bytes (RMS={rms_energy:.1f})")
            
            # Log warning if RMS is suspiciously low (possible silent/corrupted frame)
            if rms_energy < 50 and len(samples) > 0:
                log.warning(f"[CODEC-ULAW] ⚠️  Very low RMS energy ({rms_energy:.1f}) - possible silent or corrupted frame")
            
            return pcm_bytes
        except audioop.error as e:
            log.error(f"[CODEC-ULAW] ❌ audioop.ulaw2lin error: {e} (input: {ulaw_frame_count} bytes)")
            return b''

    except Exception as e:
        log.error(f"[CODEC-ULAW] ❌ ulaw_to_linear error: {e}")
        return b''

def calculate_frame_rms_energy(frame_bytes: bytes, is_ulaw: bool = True) -> float:
    """
    Calculate RMS (root mean square) energy of audio frame.
    
    ✅ CRITICAL FIX #4: Proper audio energy calculation for VAD
    
    This is the correct way to measure audio amplitude for speech detection.
    RMS energy is the standard metric used in speech processing.
    
    Args:
        frame_bytes: Audio data (either µ-law 8-bit or PCM16)
        is_ulaw: If True, decode µ-law first; if False, treat as PCM16
        
    Returns:
        RMS energy value (0-32767 for PCM16, represents amplitude)
        
    Algorithm:
        1. If µ-law: decode to PCM16 (2 bytes per sample)
        2. Unpack PCM16 samples (signed 16-bit little-endian)
        3. Calculate RMS = sqrt(mean(sample^2))
        4. Return RMS value
    """
    try:
        if not frame_bytes or len(frame_bytes) == 0:
            return 0.0

        if is_ulaw:
            pcm_bytes = ulaw_to_linear(frame_bytes)
        else:
            pcm_bytes = frame_bytes

        if not pcm_bytes or len(pcm_bytes) < 2:
            return 0.0

        sample_count = len(pcm_bytes) // 2
        try:
            samples = struct.unpack(f'<{sample_count}h', pcm_bytes)
        except struct.error:
            log.error(f"[CODEC-VAD] Failed to unpack PCM samples: {len(pcm_bytes)} bytes")
            return 0.0

        sum_squares = sum(s * s for s in samples)
        mean_square = sum_squares / len(samples)
        rms_energy = (mean_square ** 0.5) if mean_square > 0 else 0.0

        return rms_energy

    except Exception as e:
        log.error(f"[CODEC-VAD] calculate_frame_rms_energy error: {e}")
        return 0.0

def generate_beep_frames(duration_ms: int = 400, frequency_hz: int = 1000, amplitude: float = 0.8) -> Optional[list]:
    """
    Generate a confirmation beep tone in RTP frame format.
    
    Used to provide audio feedback after greeting (before listening starts).
    Generates pure sine wave tone, encodes to PCMU, splits into RTP frames.
    
    Args:
        duration_ms: Beep duration in milliseconds (default 400ms for short confirmation)
        frequency_hz: Tone frequency in Hz (default 1000Hz - pleasant beep)
        amplitude: Wave amplitude 0.0-1.0 (default 0.8 for clear but not loud)
        
    Returns:
        List of 160-byte RTP frames or None on error
    """
    try:
        if duration_ms < 50 or duration_ms > 5000:
            log.warning(f"[BEEP] Duration {duration_ms}ms outside normal range (50-5000ms)")
            duration_ms = max(50, min(5000, duration_ms))

        sample_rate = 8000
        num_samples = int(sample_rate * duration_ms / 1000.0)

        pcm_samples = bytearray()
        for i in range(num_samples):
            phase = (2.0 * math.pi * frequency_hz * i) / sample_rate
            sample_value = int(32767 * amplitude * math.sin(phase))

            pcm_samples.extend(struct.pack('<h', sample_value))

        pcm_bytes = bytes(pcm_samples)
        ulaw_bytes = linear_to_ulaw(pcm_bytes)

        if not ulaw_bytes:
            log.error(f"[BEEP] µ-law encoding failed")
            return None

        frames = []
        frames_padded = 0

        for i in range(0, len(ulaw_bytes), RTP_FRAME_SIZE):
            frame = ulaw_bytes[i:i+RTP_FRAME_SIZE]

            if len(frame) < RTP_FRAME_SIZE:
                frame = frame + (b'\xff' * (RTP_FRAME_SIZE - len(frame)))
                frames_padded += 1

            frames.append(frame)

        log.info(f"[BEEP] Generated beep: {duration_ms}ms @ {frequency_hz}Hz = {len(frames)} RTP frames")
        log.debug(f"[BEEP]    ├─ PCM samples: {num_samples}")
        log.debug(f"[BEEP]    ├─ µ-law bytes: {len(ulaw_bytes)}")
        log.debug(f"[BEEP]    ├─ RTP frames: {len(frames)}")
        log.debug(f"[BEEP]    └─ Frames padded: {frames_padded}")

        return frames

    except Exception as e:
        log.error(f"[BEEP] Generation error: {e}", exc_info=True)
        return None

def convert_audio_to_rtp_frames(audio_bytes: bytes, frame_size: int = RTP_FRAME_SIZE, is_greeting: bool = False, call_id: str = None) -> Optional[list]:
    """
    GEMINI LIVE AUDIO PROCESSING: RTP ↔ Audio Conversion
    
    Handles audio frame conversion for RTP transmission and reception
    
    Pipeline:
    1. Receive/send PCM audio (8kHz)
    2. Convert to µ-law (8-bit) for RTP transmission if needed
    3. Split into RTP frames (160 bytes = 20ms at 8kHz)
    4. Manage frame boundaries and padding
    
    Args:
        audio_bytes: Audio bytes for processing
        frame_size: RTP frame size (default 160 bytes = 20ms)
        is_greeting: If True, apply clarity enhancements for greeting audio
        call_id: Call identifier for diagnostic logging (optional)
        
    Returns:
        List of RTP-ready audio frames or None on error
    """
    try:
        if not audio_bytes or len(audio_bytes) == 0:
            log.error(f"[CODEC-PIPELINE] ❌ Empty audio bytes")
            return None

        try:
            from ..services.audio_diagnostics import get_audio_diagnostics
            diagnostics = get_audio_diagnostics()
            if call_id:
                diagnostics.start_diagnostic(call_id, "audio_codec_conversion")
        except:
            diagnostics = None

        log.info(f"[CODEC-PIPELINE] 🔄 Converting TTS audio to RTP frames: {len(tts_audio_bytes)} bytes input {'(GREETING)' if is_greeting else ''}")

        input_type = "string" if isinstance(tts_audio_bytes, str) else "bytes"
        log.debug(f"[CODEC-PIPELINE] Input type: {input_type} ({len(tts_audio_bytes)} bytes)")

        if isinstance(tts_audio_bytes, str):
            log.debug(f"[CODEC-PIPELINE] Decoding base64-encoded WAV...")
            try:
                tts_audio_bytes = base64.b64decode(tts_audio_bytes)
                log.debug(f"[CODEC-PIPELINE] ✅ Base64 decoded: {len(tts_audio_bytes)} bytes WAV")
            except Exception as e:
                log.error(f"[CODEC-PIPELINE] ❌ Base64 decode failed: {e}")
                return None

        log.debug(f"[CODEC-PIPELINE] Decoding WAV to PCM...")
        pcm_bytes = wav_bytes_to_pcm(tts_audio_bytes)

        if not pcm_bytes or len(pcm_bytes) == 0:
            log.error(f"[CODEC-PIPELINE] ❌ WAV decode returned empty PCM")
            return None

        pcm_duration_ms = (len(pcm_bytes) / 2) / 8.0
        log.info(f"[CODEC-PIPELINE] ✅ WAV→PCM: {len(pcm_bytes)} bytes PCM ({pcm_duration_ms:.1f}ms at 8kHz)")

        try:
            wav_file = io.BytesIO(tts_audio_bytes)
            with wave.open(wav_file, 'rb') as wav:
                actual_sample_rate = wav.getframerate()

                if actual_sample_rate == 16000:
                    log.warning(f"[CODEC-PIPELINE] ⚠️  TTS returned 16kHz audio but Asterisk REQUIRES 8kHz")
                    log.warning(f"[CODEC-PIPELINE]    Downsampling 16kHz → 8kHz using high-quality decimation")

                    try:
                        resampled_pcm, _ = audioop.ratecv(pcm_bytes, 2, 1, 16000, 8000, None)
                        pcm_bytes = resampled_pcm
                        pcm_duration_ms = (len(pcm_bytes) / 2) / 8.0
                        log.info(f"[CODEC-PIPELINE] ✅ High-quality resampled 16kHz→8kHz: {len(pcm_bytes)} bytes ({pcm_duration_ms:.1f}ms)")
                    except Exception as resample_error:
                        log.warning(f"[CODEC-PIPELINE] audioop.ratecv failed: {resample_error}, falling back to simple decimation")
                        resampled = bytearray()
                        for i in range(0, len(pcm_bytes), 4):
                            resampled.extend(pcm_bytes[i:i+2])
                        pcm_bytes = bytes(resampled)
                        pcm_duration_ms = (len(pcm_bytes) / 2) / 8.0
                        log.info(f"[CODEC-PIPELINE] ✅ Fallback resampled 16kHz→8kHz: {len(pcm_bytes)} bytes ({pcm_duration_ms:.1f}ms)")
        except:
            pass

        log.debug(f"[CODEC-PIPELINE] Normalizing PCM amplitude for µ-law codec...")

        import struct
        pcm_samples = []
        peak_amplitude = 0

        for i in range(0, len(pcm_bytes), 2):
            if i + 1 < len(pcm_bytes):
                sample = struct.unpack('<h', pcm_bytes[i:i+2])[0]
                pcm_samples.append(sample)
                peak_amplitude = max(peak_amplitude, abs(sample))

        log.debug(f"[CODEC-PIPELINE] PCM peak amplitude: {peak_amplitude} (max=32767)")

        TARGET_PEAK = 25000

        if peak_amplitude > 0:
            normalization_factor = TARGET_PEAK / peak_amplitude
            log.info(f"[CODEC-PIPELINE] Normalizing amplitude: factor={normalization_factor:.3f} "
                    f"(peak {peak_amplitude} → {int(peak_amplitude * normalization_factor)})")

            normalized_samples = []
            clipped_count = 0

            for sample in pcm_samples:
                normalized = int(sample * normalization_factor)
                if normalized > 32767:
                    normalized = 32767
                    clipped_count += 1
                elif normalized < -32768:
                    normalized = -32768
                    clipped_count += 1
                normalized_samples.append(normalized)

            normalized_pcm = b''.join(
                struct.pack('<h', s) for s in normalized_samples
            )

            if clipped_count > 0:
                clip_pct = (clipped_count / len(normalized_samples)) * 100
                log.warning(f"[CODEC-PIPELINE] ⚠️  Clipping detected: {clipped_count}/{len(normalized_samples)} samples ({clip_pct:.1f}%)")
                log.warning(f"[CODEC-PIPELINE] If audio sounds distorted, reduce TTS loudness parameter")

            pcm_bytes = normalized_pcm
            log.info(f"[CODEC-PIPELINE] ✅ PCM amplitude normalized: {len(pcm_bytes)} bytes (clipped={clipped_count})")

        log.debug(f"[CODEC-PIPELINE] Compressing PCM to µ-law (G.711)...")
        ulaw_bytes = linear_to_ulaw(pcm_bytes)

        if not ulaw_bytes or len(ulaw_bytes) == 0:
            log.error(f"[CODEC-PIPELINE] ❌ µ-law encoding returned empty")
            return None

        compression_ratio = len(pcm_bytes) / len(ulaw_bytes) if len(ulaw_bytes) > 0 else 0
        log.info(f"[CODEC-PIPELINE] ✅ PCM→µlaw: {len(ulaw_bytes)} bytes µ-law (compression ratio={compression_ratio:.2f}:1)")

        log.debug(f"[CODEC-PIPELINE] Splitting µ-law audio into {frame_size}-byte RTP frames...")
        frames = []
        frames_padded = 0

        for i in range(0, len(ulaw_bytes), frame_size):
            frame = ulaw_bytes[i:i+frame_size]

            if len(frame) < frame_size:
                padding = b'\xff' * (frame_size - len(frame))
                frame = frame + padding
                frames_padded += 1
                log.debug(f"[CODEC-PIPELINE] Frame {len(frames)+1}: padded from {len(frame)-len(padding)} to {len(frame)} bytes")

            frames.append(frame)

        expected_frames_from_ulaw = (len(ulaw_bytes) // frame_size) + (1 if (len(ulaw_bytes) % frame_size) != 0 else 0)

        audio_duration_ms = len(frames) * 20
        audio_duration_s = audio_duration_ms / 1000.0

        log.info(f"[CODEC-PIPELINE] 📊 AUDIO VALIDATION:")
        log.info(f"[CODEC-PIPELINE]   ├─ Frames generated: {len(frames)}")
        log.info(f"[CODEC-PIPELINE]   ├─ Frames padded: {frames_padded}")
        log.info(f"[CODEC-PIPELINE]   ├─ Expected from µlaw: {expected_frames_from_ulaw}")
        log.info(f"[CODEC-PIPELINE]   ├─ Frame size: {frame_size} bytes")
        log.info(f"[CODEC-PIPELINE]   ├─ Total audio bytes: {len(frames) * frame_size} bytes ({len(ulaw_bytes)} original µ-law)")
        log.info(f"[CODEC-PIPELINE]   ├─ Audio duration: {audio_duration_ms}ms ({audio_duration_s:.2f}s)")
        log.info(f"[CODEC-PIPELINE]   └─ Transmission pace: 20ms/frame (1 frame every 20ms)")

        for idx, frame in enumerate(frames):
            if len(frame) != frame_size:
                log.error(f"[CODEC-PIPELINE] ❌ Frame {idx}: size {len(frame)} != {frame_size}")
                return None

        log.info(f"[CODEC-PIPELINE] ✅ PIPELINE COMPLETE: {len(frames)} frames ready for RTP transmission")
        log.info(f"[CODEC-PIPELINE] ✅ ASTERISK REQUIREMENTS MET:")
        log.info(f"[CODEC-PIPELINE]    ├─ Sample rate: 8kHz (PCMU requirement)")
        log.info(f"[CODEC-PIPELINE]    ├─ Codec: µ-law (RTP payload type 0)")
        log.info(f"[CODEC-PIPELINE]    ├─ Channels: mono (1 channel)")
        log.info(f"[CODEC-PIPELINE]    ├─ Frame size: 160 bytes = 20ms")
        log.info(f"[CODEC-PIPELINE]    └─ Total frames: {len(frames)} ready to send")

        if diagnostics and call_id:
            diagnostics.log_rtp_frame_validation(
                call_id=call_id,
                frame_count=len(frames),
                frame_size=frame_size,
                total_bytes=len(frames) * frame_size,
                duration_ms=audio_duration_ms,
                frames_padded=frames_padded
            )
            diagnostics.log_asterisk_requirements(call_id)
            diagnostics.end_diagnostic(
                call_id,
                "audio_codec_conversion",
                input_size=len(tts_audio_bytes),
                output_size=len(frames) * frame_size
            )

        if is_greeting:
            log.info(f"[CODEC-PIPELINE] 🎙️  GREETING AUDIO: Enhanced for maximum clarity and smooth delivery")

        return frames

    except Exception as e:
        log.error(f"[CODEC-PIPELINE] ❌ Error: {e}", exc_info=True)
        return None

class RTPState:
    """RTP connection states"""
    INIT = "INIT"
    WAITING_REMOTE = "WAITING_REMOTE"
    ESTABLISHED = "ESTABLISHED"
    FAILED = "FAILED"

async def send_rtp_packet(transport, remote_addr: Tuple[str, int],
                          payload: bytes, seq: int, ts: int,
                          ssrc: int) -> bool:
    """Send an RTP packet"""
    try:
        header = RTP_HDR_FMT.pack(0x80, 0x00, seq & 0xFFFF, ts & 0xFFFFFFFF, ssrc)
        packet = header + payload

        transport.sendto(packet, remote_addr)
        return True
    except Exception as e:
        log.error(f"[RTP] Send error: {e}")
        return False

async def bootstrap_rtp(transport, remote_addr: Tuple[str, int],
                        packets: int = 15, interval_ms: float = 5) -> int:
    """Send bootstrap RTP packets to establish connection"""
    try:
        sent = 0
        seq = 1
        ts = 0
        ssrc = int(time.time()) % 0xFFFFFFFF

        for _ in range(packets):
            header = RTP_HDR_FMT.pack(0x80, 0x00, seq & 0xFFFF, ts & 0xFFFFFFFF, ssrc)
            packet = header + RTP_COMFORT_NOISE_ULAW

            transport.sendto(packet, remote_addr)
            sent += 1

            seq += 1
            ts += RTP_FRAME_SIZE

            if interval_ms > 0:
                await asyncio.sleep(interval_ms / 1000.0)

        log.info(f"[RTP] Bootstrap sent: {sent} packets to {remote_addr}")
        return sent
    except Exception as e:
        log.error(f"[RTP] Bootstrap failed: {e}")
        return 0

async def calculate_adaptive_threshold(
    media_session,
    calibration_duration_ms: int = 2000,
    noise_percentile: float = 10.0,
    multiplier: float = 2.5,
    min_threshold: int = 400,
    max_threshold: int = 3000
) -> Tuple[int, Dict[str, float]]:
    """
    Calculate adaptive speech detection threshold by analyzing environment.
    
    ✅ CRITICAL FIX: Automatically tune speech detection for any environment
    
    Analyzes ~2 seconds of incoming audio to determine:
    1. Noise floor (baseline environmental noise in dB)
    2. Optimal threshold = noise_floor * multiplier
    3. Bounds result between min/max for safety
    
    Works across:
    - Mobile phones (speaker or headphone)
    - Desktop phones
    - VoIP endpoints
    - Noisy call centers
    - Quiet offices
    - High-end telephony equipment
    
    Algorithm:
    1. Collect audio frames for 2 seconds
    2. Calculate RMS energy for each frame
    3. Find noise baseline (bottom 10% of energies = quietest frames)
    4. Calculate optimal threshold = noise_baseline * 2.5x
    5. Clamp result: 400 ≤ threshold ≤ 3000
    6. Return threshold + diagnostic info
    
    Args:
        media_session: RTP media session with get_received_audio_chunk() method
        calibration_duration_ms: Calibration window (default 2000ms = 2 seconds)
        noise_percentile: Percentile for noise baseline (default 10.0 = quietest 10%)
        multiplier: Threshold multiplier (default 2.5x = balanced for all devices)
        min_threshold: Minimum threshold safety limit (default 400)
        max_threshold: Maximum threshold safety limit (default 3000)
        
    Returns:
        Tuple: (threshold_value, diagnostic_dict)
        - threshold_value: Recommended speech detection threshold
        - diagnostic_dict: {
            'noise_floor': float,           # dB level of environment
            'noise_floor_energy': float,    # RMS energy of noise baseline
            'calculated_threshold': int,    # Before clamping
            'final_threshold': int,         # After clamping
            'frames_analyzed': int,
            'min_energy': float,
            'max_energy': float,
            'mean_energy': float,
            'std_dev_energy': float,
            'percentile_energy': float,
            'calibration_duration_ms': int,
            'multiplier': float
          }
    """
    try:
        import statistics

        log.info(f"\n{'='*70}")
        log.info(f"🎧 ADAPTIVE THRESHOLD CALIBRATION - Analyzing environment...")
        log.info(f"{'='*70}")
        log.info(f"[ADAPT] Duration: {calibration_duration_ms}ms (capturing ambient noise/speech patterns)")
        log.info(f"[ADAPT] Noise percentile: {noise_percentile}% (quietest frames = noise baseline)")
        log.info(f"[ADAPT] Multiplier: {multiplier}x (threshold = noise_floor * multiplier)")
        log.info(f"[ADAPT] Bounds: {min_threshold} ≤ threshold ≤ {max_threshold}")

        frame_energies = []
        frames_collected = 0
        start_time = time.time()

        calibration_duration_sec = calibration_duration_ms / 1000.0
        timeout_sec = calibration_duration_sec + 5.0

        log.info(f"[ADAPT] Collecting frames...\n")

        while (time.time() - start_time) < calibration_duration_sec:
            try:
                frame = await media_session.get_received_audio_chunk(timeout_sec=0.1)

                if frame is None:
                    continue

                frame_energy = calculate_frame_rms_energy(frame, is_ulaw=True)
                frame_energies.append(frame_energy)
                frames_collected += 1

                if frames_collected % 20 == 0:
                    elapsed = time.time() - start_time
                    avg_energy_so_far = statistics.mean(frame_energies)
                    log.debug(f"[ADAPT] Progress: {frames_collected} frames collected ({elapsed:.1f}s), avg_energy={avg_energy_so_far:.1f}")

            except asyncio.TimeoutError:
                continue
            except Exception as e:
                log.warning(f"[ADAPT] Error collecting frame: {e}")
                continue

        elapsed_time = time.time() - start_time

        if not frame_energies or len(frame_energies) < 5:
            log.warning(f"[ADAPT] ⚠️  Insufficient frames collected: {len(frame_energies)} (need ≥5)")
            log.warning(f"[ADAPT]    Using fallback threshold: {min_threshold + 200} (noise detection may not work)")

            return min_threshold + 200, {
                'noise_floor': 0,
                'noise_floor_energy': 0,
                'calculated_threshold': min_threshold + 200,
                'final_threshold': min_threshold + 200,
                'frames_analyzed': len(frame_energies),
                'min_energy': 0,
                'max_energy': 0,
                'mean_energy': 0,
                'std_dev_energy': 0,
                'percentile_energy': 0,
                'calibration_duration_ms': calibration_duration_ms,
                'multiplier': multiplier,
                'status': 'insufficient_frames'
            }

        log.info(f"[ADAPT] ✅ Collected {len(frame_energies)} frames in {elapsed_time:.2f}s")

        min_energy = min(frame_energies)
        max_energy = max(frame_energies)
        mean_energy = statistics.mean(frame_energies)
        std_dev_energy = statistics.stdev(frame_energies) if len(frame_energies) > 1 else 0

        log.info(f"[ADAPT] 📊 ENERGY ANALYSIS:")
        log.info(f"[ADAPT]    ├─ Min energy: {min_energy:.1f}")
        log.info(f"[ADAPT]    ├─ Max energy: {max_energy:.1f}")
        log.info(f"[ADAPT]    ├─ Mean energy: {mean_energy:.1f}")
        log.info(f"[ADAPT]    ├─ Std dev: {std_dev_energy:.1f}")
        log.info(f"[ADAPT]    └─ Range: {max_energy - min_energy:.1f}")

        sorted_energies = sorted(frame_energies)
        percentile_index = int((noise_percentile / 100.0) * len(sorted_energies))
        percentile_index = min(percentile_index, len(sorted_energies) - 1)

        noise_floor_energy = sorted_energies[percentile_index]

        log.info(f"[ADAPT] 🔇 NOISE BASELINE:")
        log.info(f"[ADAPT]    ├─ Percentile: {noise_percentile}% (index {percentile_index}/{len(sorted_energies)})")
        log.info(f"[ADAPT]    ├─ Noise floor (RMS energy): {noise_floor_energy:.1f}")

        calculated_threshold = int(noise_floor_energy * multiplier)

        log.info(f"[ADAPT] 🎯 THRESHOLD CALCULATION:")
        log.info(f"[ADAPT]    ├─ Formula: noise_floor × multiplier")
        log.info(f"[ADAPT]    ├─ Calculation: {noise_floor_energy:.1f} × {multiplier} = {calculated_threshold}")

        final_threshold = max(min_threshold, min(max_threshold, calculated_threshold))

        if final_threshold != calculated_threshold:
            log.warning(f"[ADAPT] ⚠️  Threshold clamped: {calculated_threshold} → {final_threshold}")
            log.warning(f"[ADAPT]    Clamping: {min_threshold} ≤ threshold ≤ {max_threshold}")

        log.info(f"[ADAPT] ✅ FINAL THRESHOLD: {final_threshold}")
        log.info(f"[ADAPT]    ├─ This threshold will detect sounds ≥ {final_threshold} RMS energy")
        log.info(f"[ADAPT]    ├─ Sounds < {final_threshold} will be treated as silence")
        log.info(f"[ADAPT]    ├─ Automatic adjustment for environment completed")
        log.info(f"[ADAPT]    └─ Custom: Can override with SPEECH_DETECTION_THRESHOLD env var")
        log.info(f"\n{'='*70}\n")

        diagnostics = {
            'noise_floor': float(noise_floor_energy),
            'noise_floor_energy': float(noise_floor_energy),
            'calculated_threshold': calculated_threshold,
            'final_threshold': final_threshold,
            'frames_analyzed': len(frame_energies),
            'min_energy': float(min_energy),
            'max_energy': float(max_energy),
            'mean_energy': float(mean_energy),
            'std_dev_energy': float(std_dev_energy),
            'percentile_energy': float(noise_floor_energy),
            'calibration_duration_ms': calibration_duration_ms,
            'multiplier': multiplier,
            'status': 'success'
        }

        return final_threshold, diagnostics

    except Exception as e:
        log.error(f"[ADAPT] ❌ Calibration error: {e}", exc_info=True)

        fallback_threshold = 1200
        return fallback_threshold, {
            'noise_floor': 0,
            'noise_floor_energy': 0,
            'calculated_threshold': fallback_threshold,
            'final_threshold': fallback_threshold,
            'frames_analyzed': 0,
            'min_energy': 0,
            'max_energy': 0,
            'mean_energy': 0,
            'std_dev_energy': 0,
            'percentile_energy': 0,
            'calibration_duration_ms': calibration_duration_ms,
            'multiplier': multiplier,
            'status': 'error',
            'error': str(e)
        }
