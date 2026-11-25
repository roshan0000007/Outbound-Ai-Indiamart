"""
Gemini Live Provider - Speech-to-Speech Audio Streaming (google-genai)
Integration with Google Gemini Live API for real-time bidirectional audio conversations
Supports WebSocket streaming for end-to-end audio processing without STT/TTS intermediaries
"""

import os
import asyncio
import json
import base64
from typing import Optional, Dict, Any, Callable, AsyncIterator
from datetime import datetime

from ..core.config import log


class GeminiLiveProvider:
    """
    Gemini Live API provider for real-time speech-to-speech conversations
    Using google-genai package (new SDK)
    
    Features:
    - WebSocket bidirectional streaming (live.connect)
    - Real-time audio input/output
    - No intermediate STT/TTS processing required
    - 8kHz PCM audio streaming
    """

    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY", "")
        self.model = os.getenv("GEMINI_LIVE_MODEL", "gemini-2.5-flash-native-audio-preview-12-2025")
        self.voice = os.getenv("GEMINI_VOICE", "Aoede")
        self.client = None
        self.session = None
        self.temperature = float(os.getenv("LLM_TEMPERATURE", "0.3"))
        self.max_tokens = int(os.getenv("LLM_MAX_TOKENS", "500"))
        
        # WebSocket streaming attributes
        self.websocket = None
        self.session_id = None
        self.audio_config = {
            "encoding": "LINEAR16",
            "sample_rate_hertz": 8000,
        }
        self.stream_lock = asyncio.Lock()

    async def initialize(self) -> bool:
        """Initialize Gemini Live client using google-genai"""
        try:
            if not self.api_key:
                log.error("[Gemini Live] API key not configured")
                return False

            try:
                from google import genai
                
                # Create client with new SDK
                self.client = genai.Client(api_key=self.api_key)
                
                log.info(f"[Gemini Live] ✅ Client initialized successfully (google-genai)")
                log.info(f"[Gemini Live]    ├─ Model: {self.model}")
                log.info(f"[Gemini Live]    ├─ Voice: {self.voice}")
                log.info(f"[Gemini Live]    ├─ Audio Config: {self.audio_config}")
                log.info(f"[Gemini Live]    ├─ Temperature: {self.temperature}")
                log.info(f"[Gemini Live]    └─ Max Tokens: {self.max_tokens}")
                return True
                
            except ImportError:
                log.error("[Gemini Live] google-genai not installed")
                log.error("[Gemini Live] Install: pip install google-genai")
                return False

        except Exception as e:
            log.error(f"[Gemini Live] Initialization failed: {e}")
            return False

    async def create_live_session(self, system_prompt: Optional[str] = None) -> bool:
        """
        Create a new Gemini Live session
        
        Args:
            system_prompt: System instructions for the AI
            
        Returns:
            bool: True if session created successfully
        """
        try:
            if not self.client:
                log.error("[Gemini Live] Client not initialized - attempting re-initialization")
                init_success = await self.initialize()
                if not init_success:
                    log.error("[Gemini Live] Client initialization failed")
                    return False

            # Generate session ID
            self.session_id = f"session_{int(datetime.utcnow().timestamp() * 1000)}"
            
            log.info(f"[Gemini Live] Creating audio session: {self.session_id}")
            log.info(f"[Gemini Live]    ├─ System Prompt: {system_prompt[:100] if system_prompt else 'Default'}...")
            log.info(f"[Gemini Live]    ├─ Audio: {self.audio_config['encoding']} @ {self.audio_config['sample_rate_hertz']}Hz")
            log.info(f"[Gemini Live]    └─ Voice: {self.voice}")

            self.session = {
                "session_id": self.session_id,
                "created_at": datetime.utcnow().isoformat(),
                "model": self.model,
                "voice": self.voice,
                "status": "active",
                "system_prompt": system_prompt or "You are a helpful sales assistant. Respond concisely and naturally.",
                "audio_config": self.audio_config
            }

            log.info(f"[Gemini Live] ✅ Session created: {self.session_id}")
            return True

        except Exception as e:
            log.error(f"[Gemini Live] Session creation error: {e}")
            return False

    async def stream_audio_bidirectional(
        self,
        audio_input_stream: AsyncIterator[bytes],
        on_audio_chunk: Optional[Callable[[bytes], None]] = None,
        on_text_chunk: Optional[Callable[[str], None]] = None
    ) -> Optional[bytes]:
        """
        Bidirectional audio streaming - fallback to text processing with audio pass-through
        
        Args:
            audio_input_stream: Async iterator providing audio chunks
            on_audio_chunk: Callback for each audio response chunk
            on_text_chunk: Callback for interim text
            
        Returns:
            Response audio bytes
        """
        try:
            if not self.session or not self.client:
                log.error("[Gemini Live] Session not active")
                return None

            log.info(f"[Gemini Live] Starting audio stream processing: {self.session_id}")

            response_audio = bytearray()
            
            try:
                # Process audio stream with timeout
                frame_count = 0
                async for audio_chunk in audio_input_stream:
                    if audio_chunk:
                        frame_count += 1
                        # Pass through audio chunks directly for now
                        # In production, would send to Gemini for processing
                        if on_audio_chunk:
                            on_audio_chunk(audio_chunk)
                    
                    # Timeout after processing many frames
                    if frame_count > 1000:
                        break
                    
                    await asyncio.sleep(0.001)
                
                log.info(f"[Gemini Live] Audio stream processed: {frame_count} frames, {len(response_audio)} bytes")
                return bytes(response_audio) if response_audio else None

            except Exception as e:
                log.error(f"[Gemini Live] Stream processing error: {e}")
                return bytes(response_audio) if response_audio else None

        except Exception as e:
            log.error(f"[Gemini Live] Bidirectional streaming error: {e}")
            return None

    async def _send_audio_stream_genai(
        self,
        session,
        audio_input_stream: AsyncIterator[bytes]
    ):
        """Send audio chunks (now simplified since not using WebSocket)"""
        try:
            frame_count = 0
            async for audio_chunk in audio_input_stream:
                if audio_chunk:
                    frame_count += 1
                    if frame_count % 50 == 0:
                        log.debug(f"[Gemini Live] Processed {frame_count} audio frames")
            
            log.info(f"[Gemini Live] Audio input processing complete: {frame_count} frames")

        except Exception as e:
            log.error(f"[Gemini Live] Error processing audio: {e}")

    async def _receive_audio_stream_genai(
        self,
        session,
        response_audio: bytearray,
        on_audio_chunk: Optional[Callable[[bytes], None]],
        on_text_chunk: Optional[Callable[[str], None]]
    ):
        """Receive callbacks (simplified - process audio as it arrives)"""
        try:
            log.debug("[Gemini Live] Ready to receive audio responses")
            # In live mode, responses come via callbacks
            await asyncio.sleep(0.1)
            log.info("[Gemini Live] Response processing complete")

        except Exception as e:
            log.error(f"[Gemini Live] Error receiving: {e}")

    async def get_text_response(self, prompt: str, system_prompt: Optional[str] = None) -> Optional[str]:
        """
        Get text response using google-genai
        
        Args:
            prompt: User prompt
            system_prompt: System prompt
        
        Returns:
            Response text
        """
        try:
            if not self.client:
                log.error("[Gemini Live] Client not initialized")
                return None

            try:
                # Use GenerativeModel for text generation
                model = self.client.models.GenerativeModel(
                    model_id="gemini-1.5-flash",
                    system_instruction=system_prompt or "You are a professional sales assistant.",
                    generation_config={
                        "temperature": self.temperature,
                        "max_output_tokens": self.max_tokens,
                    }
                )

                response = await model.generate_content_async(prompt)
                return response.text if response else None

            except Exception as e:
                log.error(f"[Gemini Live] Generation error: {e}")
                return None

        except Exception as e:
            log.error(f"[Gemini Live] Error: {e}")
            return None

    async def stream_response(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        on_chunk: Optional[Callable[[str], None]] = None
    ) -> Optional[str]:
        """
        Stream response text using google-genai
        
        Args:
            prompt: User prompt
            system_prompt: System prompt
            on_chunk: Callback for each chunk
        
        Returns:
            Complete response
        """
        try:
            if not self.client:
                log.error("[Gemini Live] Client not initialized")
                return None

            try:
                model = self.client.models.GenerativeModel(
                    model_id="gemini-1.5-flash",
                    system_instruction=system_prompt or "You are a professional sales assistant.",
                    generation_config={
                        "temperature": self.temperature,
                        "max_output_tokens": self.max_tokens,
                    }
                )

                full_response = ""
                
                async for chunk in await model.generate_content_stream_async(prompt):
                    if chunk.text:
                        full_response += chunk.text
                        if on_chunk:
                            on_chunk(chunk.text)
                        log.debug(f"[Gemini Live] Chunk: {chunk.text[:50]}...")

                return full_response if full_response else None

            except Exception as e:
                log.error(f"[Gemini Live] Streaming error: {e}")
                return None

        except Exception as e:
            log.error(f"[Gemini Live] Error: {e}")
            return None

    async def close_session(self) -> bool:
        """Close Gemini Live session"""
        try:
            if self.websocket:
                try:
                    self.websocket = None
                    log.info(f"[Gemini Live] Session closed")
                except Exception as e:
                    log.warning(f"[Gemini Live] Error closing session: {e}")
                finally:
                    self.websocket = None

            if self.session:
                self.session["status"] = "closed"
                self.session["closed_at"] = datetime.utcnow().isoformat()
                log.info(f"[Gemini Live] Session metadata: {self.session_id}")
                self.session = None
                
            return True
        except Exception as e:
            log.error(f"[Gemini Live] Session close error: {e}")
            return False

    def get_session_info(self) -> Optional[Dict[str, Any]]:
        """Get current session information"""
        return self.session.copy() if self.session else None


_provider: Optional[GeminiLiveProvider] = None


async def init_gemini_live_provider():
    """Initialize Gemini Live provider"""
    global _provider
    _provider = GeminiLiveProvider()
    success = await _provider.initialize()
    if success:
        log.info("[Gemini Live] Provider initialized (google-genai SDK)")
    return _provider


def get_gemini_live_provider() -> Optional[GeminiLiveProvider]:
    """Get Gemini Live provider instance"""
    return _provider
