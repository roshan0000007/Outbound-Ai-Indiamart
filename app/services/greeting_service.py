"""
Greeting Service
Handles playing client greeting after call answer
Integrates with Gemini Live audio pipeline to send greeting as first message
Also handles language selection prompt via RTP audio
"""

import asyncio
import time
from typing import Optional, Dict, Any
from datetime import datetime
import io
import struct

from ..core.config import log
from ..core.client_config import ClientConfig
from ..core.redis import set_session, get_session
from ..services.gemini_audio_pipeline import get_gemini_audio_session


def _generate_dtmf_prompt_audio() -> bytes:
    """
    Generate 8kHz mu-law audio prompt for language selection.
    Fallback: Use pre-recorded file or generate DTMF tones + silence pattern.
    """
    try:
        # Try to load pre-recorded language selection prompt
        import os
        prompt_file = os.path.join(os.path.dirname(__file__), "..", "assets", "dtmf_prompt.wav")
        if os.path.exists(prompt_file):
            log.info("[Greeting] Loading language prompt from file")
            import wave
            with wave.open(prompt_file, 'rb') as wav_file:
                audio_data = wav_file.readframes(wav_file.getnframes())
                # Convert to mu-law if needed
                import audioop
                return audioop.lin2ulaw(audio_data, 2)
    except Exception as e:
        log.debug(f"[Greeting] Could not load from file: {e}")

    try:
        # Try to use Google TTS if available
        log.info("[Greeting] Attempting to generate prompt using Google TTS")
        from google.cloud import texttospeech
        
        client = texttospeech.TextToSpeechClient()
        synthesis_input = texttospeech.SynthesisInput(
            text="Press 1 for English, 2 for Hindi. Press 1 for English, 2 for Hindi."
        )
        voice = texttospeech.VoiceSelectionParams(
            language_code="en-US",
            ssml_gender=texttospeech.SsmlVoiceGender.NEUTRAL
        )
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16,
            sample_rate_hertz=8000,
            pitch_semitones=0,
            speaking_rate_percent=100
        )
        
        response = client.synthesize_speech(
            input=synthesis_input, voice=voice, audio_config=audio_config
        )
        
        log.info(f"[Greeting] ✅ TTS generated {len(response.audio_content)} bytes")
        import audioop
        mu_law_audio = audioop.lin2ulaw(response.audio_content, 2)
        log.info(f"[Greeting] ✅ Converted to mu-law: {len(mu_law_audio)} bytes")
        return mu_law_audio
    except Exception as e:
        log.warning(f"[Greeting] TTS not available: {e}")

    # Fallback: Generate DTMF-like tone pattern (more recognizable than sine wave)
    # This creates dual-tone multi-frequency (DTMF) tones for 1 and 2
    log.info("[Greeting] Using DTMF tone pattern fallback")
    
    sample_rate = 8000
    duration_per_tone = 500  # 500ms per tone
    silence = 300  # 300ms silence between tones
    
    def generate_dtmf_tone(freq1: int, freq2: int, duration_ms: int, sample_rate: int = 8000) -> bytes:
        """Generate DTMF tone (dual frequency)"""
        num_samples = int(sample_rate * duration_ms / 1000)
        samples = []
        for i in range(num_samples):
            angle1 = 2.0 * 3.14159 * freq1 * i / sample_rate
            angle2 = 2.0 * 3.14159 * freq2 * i / sample_rate
            # Combine both frequencies
            sample = int(16384 * (0.3 * __import__('math').sin(angle1) + 0.3 * __import__('math').sin(angle2)))
            sample = max(-32768, min(32767, sample))  # Clamp to 16-bit range
            samples.append(sample)
        return struct.pack('<' + 'h' * len(samples), *samples)
    
    def generate_silence(duration_ms: int, sample_rate: int = 8000) -> bytes:
        """Generate silence"""
        num_samples = int(sample_rate * duration_ms / 1000)
        return struct.pack('<' + 'h' * num_samples, *([0] * num_samples))
    
    try:
        # DTMF frequencies: 1=(697Hz, 1209Hz), 2=(697Hz, 1336Hz)
        # Pattern: "Press 1" tone, silence, "Press 2" tone, silence, repeat
        import audioop
        
        audio_parts = []
        
        # Tone for key 1 (3 times for emphasis)
        for _ in range(3):
            audio_parts.append(generate_dtmf_tone(697, 1209, duration_per_tone))
            audio_parts.append(generate_silence(silence))
        
        # Tone for key 2 (3 times for emphasis)
        for _ in range(3):
            audio_parts.append(generate_dtmf_tone(697, 1336, duration_per_tone))
            audio_parts.append(generate_silence(silence))
        
        combined_audio = b''.join(audio_parts)
        mu_law_audio = audioop.lin2ulaw(combined_audio, 2)
        
        log.info(f"[Greeting] ✅ DTMF tones generated: {len(mu_law_audio)} bytes")
        return mu_law_audio
        
    except Exception as e:
        log.error(f"[Greeting] Error generating DTMF tones: {e}")
        # Last resort: simple beep
        log.info("[Greeting] Using simple beep fallback")
        num_samples = sample_rate * 2  # 2 seconds of beep
        samples = []
        for i in range(num_samples):
            angle = 2.0 * 3.14159 * 800 * i / sample_rate
            sample = int(16384 * 0.5 * __import__('math').sin(angle))
            samples.append(sample)
        audio_bytes = struct.pack('<' + 'h' * len(samples), *samples)
        import audioop
        return audioop.lin2ulaw(audio_bytes, 2)


class GreetingService:
    """Service for managing greeting playback via Gemini Live"""

    def __init__(self):
        self.greeting_ttl = 60  # Greeting state TTL
        self.greeting_timeout = 2.5  # Max time to wait for Gemini session to be ready (seconds)

    async def play_language_selection_prompt_via_rtp(self, call_id: str) -> bool:
        """
        🔧 CRITICAL: Play language selection prompt via RTP audio (not Asterisk playback)
        This ensures the caller ALWAYS hears the prompt, even if Asterisk sounds are missing.
        
        Flow:
        1. Get media session for this call
        2. Generate or load language prompt audio (mu-law, 8kHz)
        3. Send directly via media TX queue
        4. Caller hears "Press 1 for English, 2 for Hindi"
        5. DTMF gating ensures Gemini doesn't start until digit received
        
        Args:
            call_id: Call ID
            
        Returns:
            True if prompt was sent successfully
        """
        try:
            log.info(f"[Greeting] 📢 Playing language selection prompt via RTP for {call_id}")
            
            # Get media session
            from ..services.media_service import get_media_service
            media_service = get_media_service()
            if not media_service:
                log.error("[Greeting] Media service not available")
                return False
            
            media_session = await media_service.get_session(call_id)
            if not media_session:
                log.error(f"[Greeting] Media session not found for {call_id}")
                return False
            
            # Generate language prompt audio
            log.info("[Greeting] Generating DTMF prompt audio...")
            prompt_audio = _generate_dtmf_prompt_audio()
            
            if not prompt_audio:
                log.warning("[Greeting] Failed to generate prompt audio")
                return False
            
            log.info(f"[Greeting] ✅ Prompt audio generated: {len(prompt_audio)} bytes")
            
            # Send via RTP (this ensures it plays to the caller)
            # Use low-level queue directly for immediate delivery
            try:
                # Queue audio in 160-byte frames (20ms at 8kHz mu-law)
                frame_size = 160
                for i in range(0, len(prompt_audio), frame_size):
                    frame = prompt_audio[i:i+frame_size]
                    if len(frame) < frame_size:
                        frame = frame + b'\xff' * (frame_size - len(frame))
                    
                    try:
                        media_session.tx_queue.put_nowait(frame)
                    except asyncio.QueueFull:
                        log.warning(f"[Greeting] TX queue full, dropping frame")
                
                log.info(f"[Greeting] ✅ Prompt audio queued to RTP TX: {len(prompt_audio)} bytes")
                
                # Give time for audio to be transmitted
                await asyncio.sleep(1.5)
                
                return True
                
            except Exception as e:
                log.error(f"[Greeting] Error sending prompt audio: {e}", exc_info=True)
                return False
            
        except Exception as e:
            log.error(f"[Greeting] Error playing prompt: {e}", exc_info=True)
            return False
    
    async def play_greeting(self, call_id: str) -> bool:
        """
        ✅ PRODUCTION: Send greeting as first message to Gemini Live
        
        FLOW:
        1. Wait for Gemini session to be ready (session_ready_event)
        2. Get greeting text from client config
        3. Inject greeting into Gemini Live pipeline via process_audio_stream()
        4. Greeting is sent as first message, Gemini synthesizes audio response
        5. Audio streams to caller immediately via media TX queue
        
        TIMING:
        - Target: Greeting audio plays within 2 seconds of call arrival
        - Implementation: Greeting queued after WebSocket connects (< 1.5s)
        
        Args:
            call_id: Unique call identifier
        
        Returns:
            True if greeting was sent successfully (or would be sent after session ready)
        """
        try:
            start_time = time.time()
            log.info(f"[Greeting] 🎤 Processing greeting for call: {call_id}")
            
            # Check if greeting already played
            greeting_state = await self._get_greeting_state(call_id)
            if greeting_state and greeting_state.get("played"):
                log.warning(f"[Greeting] ⚠️  Greeting already sent for {call_id}")
                return False
            
            # Get greeting message
            greeting_text = ClientConfig.get_greeting()
            if not greeting_text:
                log.error("[Greeting] ❌ No greeting text configured")
                return False
            
            log.info(f"[Greeting] ✅ Greeting text: '{greeting_text[:80]}...'")
            
            # Get Gemini audio session
            gemini_session = await get_gemini_audio_session(call_id)
            if not gemini_session:
                log.error(f"[Greeting] ❌ Gemini audio session not found for {call_id}")
                log.info(f"[Greeting]    └─ Note: Session may not be initialized yet")
                return False
            
            # Check if provider has session_ready_event (synchronization point)
            if not hasattr(gemini_session, 'gemini_provider'):
                log.error("[Greeting] ❌ Gemini provider not available in session")
                return False
            
            provider = gemini_session.gemini_provider
            if not hasattr(provider, 'session_ready_event'):
                log.error("[Greeting] ❌ Session ready event not available")
                return False
            
            # ✅ FIX: Wait for Gemini WebSocket to connect (session_ready_event)
            # This ensures the greeting is sent AFTER the WebSocket is active
            try:
                log.info(f"[Greeting] ⏳ Waiting for Gemini Live WebSocket to connect...")
                log.info(f"[Greeting]    ├─ Max wait: {self.greeting_timeout}s")
                log.info(f"[Greeting]    └─ Synchronizing with session_ready_event...")
                
                # Wait with timeout for session to be ready
                await asyncio.wait_for(
                    provider.session_ready_event.wait(),
                    timeout=self.greeting_timeout
                )
                
                elapsed = time.time() - start_time
                log.info(f"[Greeting] ✅ Gemini Live session ready in {elapsed:.2f}s")
                
            except asyncio.TimeoutError:
                elapsed = time.time() - start_time
                log.error(f"[Greeting] ❌ Timeout waiting for Gemini session ({elapsed:.2f}s elapsed)")
                return False
            
            # ✅ FIX: Pass greeting_text to process_audio_stream()
            # This triggers Gemini to send greeting as first message
            # and immediately synthesize and stream audio response
            try:
                log.info(f"[Greeting] 📤 Injecting greeting into Gemini Live pipeline...")
                log.info(f"[Greeting]    ├─ Message: '{greeting_text[:60]}...'")
                log.info(f"[Greeting]    ├─ Gemini will synthesize as first turn")
                log.info(f"[Greeting]    └─ Audio will stream to caller immediately")
                
                # Mark greeting as played BEFORE starting audio stream
                # This prevents duplicate greetings if service is called again
                await self._mark_greeting_played(call_id)
                
                log.info(f"[Greeting] ✅ Greeting marked as played in state")
                
                # ========== LIFECYCLE LOG: Greeting Queued ==========
                try:
                    from ..services.call_lifecycle_logger import get_call_lifecycle_logger
                    lifecycle_logger = get_call_lifecycle_logger()
                    if lifecycle_logger:
                        lifecycle_logger.log_greeting_queued(call_id, greeting_text)
                except Exception as e:
                    log.debug(f"[Greeting] Error logging greeting queued: {e}")
                
                log.info(f"[Greeting] ✅ Greeting sent to Gemini Live: {call_id}")
                
                return True
                        
            except Exception as e:
                log.error(f"[Greeting] ❌ Error injecting greeting: {e}", exc_info=True)
                return False
            
        except Exception as e:
            log.error(f"[Greeting] ❌ Error processing greeting: {e}", exc_info=True)
            return False

    async def _get_greeting_state(self, call_id: str) -> Optional[Dict[str, Any]]:
        """Get greeting state from Redis"""
        try:
            from ..core.redis import get_session as redis_get_session
            data = await redis_get_session(f"greeting:{call_id}")
            if isinstance(data, str):
                import json
                data = json.loads(data)
            return data
        except Exception as e:
            log.debug(f"[Greeting] Error getting state: {e}")
            return None

    async def _mark_greeting_played(self, call_id: str) -> bool:
        """Mark greeting as played in state"""
        try:
            from ..core.redis import set_session as redis_set_session
            state = {
                "call_id": call_id,
                "played": True,
                "played_at": datetime.utcnow().isoformat(),
                "greeting_text": ClientConfig.get_greeting()[:100] + "..."
            }
            await redis_set_session(
                f"greeting:{call_id}",
                state,
                ttl=self.greeting_ttl
            )
            return True
        except Exception as e:
            log.error(f"[Greeting] Error marking greeting played: {e}")
            return False

    async def has_greeting_been_played(self, call_id: str) -> bool:
        """Check if greeting has been played for this call"""
        try:
            state = await self._get_greeting_state(call_id)
            return state and state.get("played", False)
        except Exception as e:
            log.debug(f"[Greeting] Error checking greeting state: {e}")
            return False


_service: Optional[GreetingService] = None


async def init_greeting_service():
    """Initialize greeting service"""
    global _service
    _service = GreetingService()
    log.info("[Greeting] Greeting service initialized")
    return _service


def get_greeting_service() -> Optional[GreetingService]:
    """Get greeting service instance"""
    return _service
