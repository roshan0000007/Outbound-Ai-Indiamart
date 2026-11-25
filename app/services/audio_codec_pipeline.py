"""
Audio Codec Pipeline - Production-Grade Resampling & Codec Conversion
Implements stateful resampling for Gemini Live audio processing

PIPELINE:
  RTP RX (8kHz PCMU) → Decode → 8kHz PCM16 → Upsample → 16kHz PCM16 → Gemini Live
  Gemini Live → 24kHz PCM16 → Downsample → 8kHz PCM16 → Encode → 8kHz PCMU → RTP TX

CRITICAL REQUIREMENTS:
- Stateful resampling (preserve filter state across frames for no clicks/pops)
- Handle arbitrary frame boundaries (160-byte RTP frames don't align with resampling blocks)
- Zero distortion, preserve audio quality
- Sub-20ms latency per frame
"""

import audioop
import struct
import io
import wave
from typing import Optional, Tuple, Dict, Any
from collections import deque

from ..core.config import log


class AudioResamplingContext:
    """
    Maintains resampling state across frame boundaries
    
    For seamless resampling without clicks/pops at frame boundaries,
    we need to preserve the internal filter state of audioop.ratecv()
    """
    
    def __init__(self, name: str = ""):
        self.name = name
        self.state = None  # Maintains filter state across calls
        self.samples_in = 0
        self.samples_out = 0
        self.calls = 0
        
    def resample_frame(
        self,
        audio_bytes: bytes,
        input_rate: int,
        output_rate: int,
        channels: int = 1,
        sample_width: int = 2
    ) -> Optional[bytes]:
        """
        Resample audio frame while preserving state across boundaries
        
        Args:
            audio_bytes: Input audio data
            input_rate: Input sample rate (e.g., 8000 or 24000)
            output_rate: Output sample rate (e.g., 16000 or 8000)
            channels: Number of audio channels (default 1 for mono)
            sample_width: Bytes per sample (default 2 for 16-bit)
            
        Returns:
            Resampled audio bytes or None on error
        """
        try:
            if not audio_bytes or len(audio_bytes) == 0:
                log.debug(f"[RESAMPLER:{self.name}] Empty input, returning empty output")
                return b''
            
            if len(audio_bytes) % (channels * sample_width) != 0:
                log.error(f"[RESAMPLER:{self.name}] Invalid audio length: {len(audio_bytes)} bytes "
                         f"(must be multiple of {channels * sample_width} for {channels}ch {sample_width*8}-bit)")
                return None
            
            # Use audioop.ratecv with preserved state
            # Returns: (output_bytes, state)
            resampled, self.state = audioop.ratecv(
                audio_bytes,
                sample_width,  # bytes per sample
                channels,      # number of channels
                input_rate,    # input sample rate
                output_rate,   # output sample rate
                self.state     # preserved state from previous call (or None for first)
            )
            
            if not resampled:
                log.warning(f"[RESAMPLER:{self.name}] ratecv returned empty output")
                return b''
            
            self.calls += 1
            input_samples = len(audio_bytes) // (channels * sample_width)
            output_samples = len(resampled) // (channels * sample_width)
            self.samples_in += input_samples
            self.samples_out += output_samples
            
            if self.calls % 50 == 0:
                log.debug(f"[RESAMPLER:{self.name}] Stats: {self.calls} calls, "
                         f"{self.samples_in} samples in → {self.samples_out} samples out "
                         f"({input_rate}Hz → {output_rate}Hz)")
            
            return resampled
            
        except audioop.error as e:
            log.error(f"[RESAMPLER:{self.name}] audioop.ratecv error: {e}")
            return None
        except Exception as e:
            log.error(f"[RESAMPLER:{self.name}] Resampling error: {e}", exc_info=True)
            return None


class AudioCodecPipeline:
    """
    Complete audio codec pipeline for Gemini Live integration
    
    Handles all conversions:
    - RTP ↔ PCM16 codec conversion (PCMU decode/encode)
    - Resampling (8kHz ↔ 16kHz ↔ 24kHz)
    - Frame buffering for misaligned boundaries
    """
    
    def __init__(self, call_id: str = ""):
        self.call_id = call_id
        self.name = f"[CODEC-PIPELINE:{call_id}]" if call_id else "[CODEC-PIPELINE]"
        
        # Resampling contexts (stateful, one per conversion type)
        self.upsample_8k_to_16k = AudioResamplingContext(f"upsample_8k_to_16k")
        self.downsample_24k_to_8k = AudioResamplingContext(f"downsample_24k_to_8k")
        
        # Buffering for frame boundary alignment
        self.rx_buffer = deque()  # Buffers RTP frames before processing
        self.tx_buffer = deque()  # Buffers processed audio before TX
        
        log.info(f"{self.name} ✅ Initialized - Ready for bidirectional audio codec processing")

    async def process_rtp_rx_frame(self, rtp_frame: bytes) -> Optional[bytes]:
        """
        Process incoming RTP frame (8kHz PCMU) for Gemini Live
        
        FLOW:
        1. Decode 8kHz PCMU (160 bytes) → 8kHz PCM16 (320 bytes)
        2. Upsample 8kHz PCM16 → 16kHz PCM16 (640 bytes, stateful)
        3. Send to Gemini Live
        
        Args:
            rtp_frame: 160-byte PCMU audio frame @ 8kHz
            
        Returns:
            16kHz PCM16 audio ready for Gemini (or None on error)
        """
        try:
            if not rtp_frame or len(rtp_frame) != 160:
                log.warning(f"{self.name} ⚠️ RTP frame size mismatch: {len(rtp_frame)} bytes (expected 160)")
                # Pad if too small
                if len(rtp_frame) < 160:
                    rtp_frame = rtp_frame + (b'\xff' * (160 - len(rtp_frame)))
                elif len(rtp_frame) > 160:
                    rtp_frame = rtp_frame[:160]
            
            # ✅ STEP 1: Decode 8kHz PCMU → 8kHz PCM16
            try:
                pcm_8k = audioop.ulaw2lin(rtp_frame, 2)
                log.debug(f"{self.name} ✅ Decoded PCMU: 160 bytes → {len(pcm_8k)} bytes PCM16 @ 8kHz")
            except audioop.error as e:
                log.error(f"{self.name} ❌ PCMU decode error: {e}")
                return None
            
            # ✅ STEP 2: Upsample 8kHz PCM16 → 16kHz PCM16 (stateful)
            pcm_16k = self.upsample_8k_to_16k.resample_frame(
                pcm_8k,
                input_rate=8000,
                output_rate=16000,
                channels=1,
                sample_width=2
            )
            
            if not pcm_16k:
                log.error(f"{self.name} ❌ Upsampling failed: 8kHz → 16kHz")
                return None
            
            log.debug(f"{self.name} ✅ Upsampled: {len(pcm_8k)} bytes @ 8kHz → {len(pcm_16k)} bytes @ 16kHz")
            return pcm_16k
            
        except Exception as e:
            log.error(f"{self.name} ❌ RTP RX processing error: {e}", exc_info=True)
            return None

    async def process_gemini_response_audio(self, gemini_audio: bytes) -> Optional[bytes]:
        """
        Process Gemini Live response audio (24kHz PCM16) for RTP TX
        
        FLOW:
        1. Downsample 24kHz PCM16 → 8kHz PCM16 (stateful, 320 bytes → 160 bytes... ish)
        2. Encode 8kHz PCM16 → 8kHz PCMU (160 bytes)
        3. Send via RTP
        
        Args:
            gemini_audio: 24kHz PCM16 audio from Gemini Live (variable length)
            
        Returns:
            8kHz PCMU audio ready for RTP TX (or None on error)
        """
        try:
            if not gemini_audio or len(gemini_audio) == 0:
                log.debug(f"{self.name} Empty Gemini response audio, returning empty")
                return b''
            
            if len(gemini_audio) % 2 != 0:
                log.warning(f"{self.name} ⚠️ Gemini audio has odd byte count: {len(gemini_audio)} (should be even for 16-bit PCM)")
                # Discard last byte
                gemini_audio = gemini_audio[:-1]
            
            # ✅ STEP 1: Downsample 24kHz PCM16 → 8kHz PCM16 (stateful)
            pcm_8k = self.downsample_24k_to_8k.resample_frame(
                gemini_audio,
                input_rate=24000,
                output_rate=8000,
                channels=1,
                sample_width=2
            )
            
            if not pcm_8k:
                log.error(f"{self.name} ❌ Downsampling failed: 24kHz → 8kHz")
                return None
            
            log.debug(f"{self.name} ✅ Downsampled: {len(gemini_audio)} bytes @ 24kHz → {len(pcm_8k)} bytes @ 8kHz")
            
            # ✅ STEP 2: Encode 8kHz PCM16 → 8kHz PCMU
            try:
                ulaw_audio = audioop.lin2ulaw(pcm_8k, 2)
                log.debug(f"{self.name} ✅ Encoded to PCMU: {len(pcm_8k)} bytes @ 8kHz → {len(ulaw_audio)} bytes PCMU")
            except audioop.error as e:
                log.error(f"{self.name} ❌ PCMU encode error: {e}")
                return None
            
            return ulaw_audio
            
        except Exception as e:
            log.error(f"{self.name} ❌ Gemini response processing error: {e}", exc_info=True)
            return None

    def slice_into_rtp_frames(self, audio_bytes: bytes, frame_size: int = 160) -> Optional[list]:
        """
        Slice audio into RTP frames with proper padding
        
        Args:
            audio_bytes: Audio bytes to slice
            frame_size: RTP frame size (default 160 bytes = 20ms @ 8kHz)
            
        Returns:
            List of frame_size-byte frames or None on error
        """
        try:
            if not audio_bytes or len(audio_bytes) == 0:
                return []
            
            frames = []
            frames_padded = 0
            
            for i in range(0, len(audio_bytes), frame_size):
                frame = audio_bytes[i:i+frame_size]
                
                if len(frame) < frame_size:
                    # Pad with silence (0xFF = silence in PCMU)
                    frame = frame + (b'\xff' * (frame_size - len(frame)))
                    frames_padded += 1
                
                frames.append(frame)
            
            if frames_padded > 0:
                log.debug(f"{self.name} Sliced {len(audio_bytes)} bytes into {len(frames)} frames "
                         f"({frames_padded} frames padded with silence)")
            
            return frames
            
        except Exception as e:
            log.error(f"{self.name} ❌ Frame slicing error: {e}")
            return None

    def get_stats(self) -> Dict[str, Any]:
        """Get pipeline statistics"""
        return {
            'call_id': self.call_id,
            'upsample_8k_16k': {
                'calls': self.upsample_8k_to_16k.calls,
                'samples_in': self.upsample_8k_to_16k.samples_in,
                'samples_out': self.upsample_8k_to_16k.samples_out,
            },
            'downsample_24k_8k': {
                'calls': self.downsample_24k_to_8k.calls,
                'samples_in': self.downsample_24k_to_8k.samples_in,
                'samples_out': self.downsample_24k_to_8k.samples_out,
            }
        }


# Global codec pipeline per call
_codec_pipelines: Dict[str, AudioCodecPipeline] = {}


async def get_codec_pipeline(call_id: str) -> AudioCodecPipeline:
    """Get or create codec pipeline for a call"""
    if call_id not in _codec_pipelines:
        _codec_pipelines[call_id] = AudioCodecPipeline(call_id)
    return _codec_pipelines[call_id]


async def cleanup_codec_pipeline(call_id: str) -> bool:
    """Clean up codec pipeline when call ends"""
    try:
        if call_id in _codec_pipelines:
            pipeline = _codec_pipelines.pop(call_id)
            stats = pipeline.get_stats()
            log.info(f"[CODEC] Call {call_id} pipeline stats: {stats}")
            return True
    except Exception as e:
        log.error(f"[CODEC] Error cleaning up pipeline: {e}")
    return False
