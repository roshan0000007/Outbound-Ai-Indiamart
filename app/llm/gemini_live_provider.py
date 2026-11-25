"""
Gemini Live Provider - Speech-to-Speech Audio Streaming
Integration with Google Gemini Live API for real-time bidirectional audio conversations
Supports WebSocket streaming for end-to-end audio processing without STT/TTS intermediaries
"""

import os
import asyncio
import json
import base64
from typing import Optional, Dict, Any, Callable, AsyncIterator
from datetime import datetime
import websockets
from websockets.exceptions import ConnectionClosed

from ..core.config import log


class GeminiLiveProvider:
    """
    Gemini Live API provider for real-time speech-to-speech conversations
    
    Features:
    - WebSocket bidirectional streaming (bidiGenerateContent)
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
        """Initialize Gemini Live client"""
        try:
            if not self.api_key:
                log.error("[Gemini Live] API key not configured")
                return False

            try:
                import google.generativeai as genai
                genai.configure(api_key=self.api_key)
                self.client = genai
                log.info(f"[Gemini Live] ✅ Client initialized successfully")
                log.info(f"[Gemini Live]    ├─ Model: {self.model}")
                log.info(f"[Gemini Live]    ├─ Voice: {self.voice}")
                log.info(f"[Gemini Live]    ├─ Audio Config: {self.audio_config}")
                log.info(f"[Gemini Live]    ├─ Temperature: {self.temperature}")
                log.info(f"[Gemini Live]    └─ Max Tokens: {self.max_tokens}")
                return True
            except ImportError:
                log.error("[Gemini Live] google-generativeai not installed")
                log.error("[Gemini Live] Install: pip install google-generativeai websockets")
                return False

        except Exception as e:
            log.error(f"[Gemini Live] Initialization failed: {e}")
            return False

    async def create_live_session(self, system_prompt: Optional[str] = None) -> bool:
        """
        Create a new Gemini Live session with WebSocket connection
        
        Args:
            system_prompt: System instructions for the AI
            
        Returns:
            bool: True if session created successfully
        """
        try:
            if not self.client:
                log.error("[Gemini Live] Client not initialized")
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
        Bidirectional audio streaming - send audio, receive response audio in real-time
        
        Args:
            audio_input_stream: Async iterator providing audio chunks (160-byte frames @ 8kHz)
            on_audio_chunk: Callback for each audio response chunk received
            on_text_chunk: Callback for interim text transcription/response
            
        Returns:
            Complete response audio bytes (also streamed via callback)
        """
        try:
            if not self.session or not self.client:
                log.error("[Gemini Live] Session not active")
                return None

            log.info(f"[Gemini Live] Starting bidirectional audio stream: {self.session_id}")

            # Build WebSocket URL for Gemini Live API
            api_endpoint = f"wss://generativelanguage.googleapis.com/google.ai.generativelanguage.v1alpha.GenerativeService/BidiGenerateContent"
            
            # Prepare connection headers with authentication
            headers = {
                "Authorization": f"Bearer {self.api_key}",
            }

            response_audio = bytearray()
            current_generation_config = {
                "temperature": self.temperature,
                "max_output_tokens": self.max_tokens,
            }

            try:
                async with websockets.connect(
                    api_endpoint,
                    subprotocols=["chat"],
                    extra_headers=headers,
                    ping_interval=20,
                    ping_timeout=10
                ) as websocket:
                    self.websocket = websocket
                    log.info(f"[Gemini Live] WebSocket connected for session {self.session_id}")

                    # Initial setup message
                    setup_msg = {
                        "setup": {
                            "model": self.model,
                            "generation_config": current_generation_config,
                            "system_instruction": {
                                "parts": [{"text": self.session["system_prompt"]}]
                            },
                            "tools": [
                                {
                                    "google_search": {}
                                }
                            ]
                        }
                    }

                    await websocket.send(json.dumps(setup_msg))
                    log.debug("[Gemini Live] Setup message sent")

                    # Create async tasks for sending and receiving
                    send_task = asyncio.create_task(
                        self._send_audio_stream(websocket, audio_input_stream)
                    )
                    
                    receive_task = asyncio.create_task(
                        self._receive_audio_stream(
                            websocket,
                            response_audio,
                            on_audio_chunk,
                            on_text_chunk
                        )
                    )

                    # Wait for both to complete
                    await asyncio.gather(send_task, receive_task, return_exceptions=True)

                    self.websocket = None
                    log.info(f"[Gemini Live] Audio stream completed. Response: {len(response_audio)} bytes")

                    return bytes(response_audio) if response_audio else None

            except ConnectionClosed as e:
                log.error(f"[Gemini Live] WebSocket closed: {e}")
                self.websocket = None
                return bytes(response_audio) if response_audio else None
            except Exception as e:
                log.error(f"[Gemini Live] WebSocket error: {e}")
                self.websocket = None
                return bytes(response_audio) if response_audio else None

        except Exception as e:
            log.error(f"[Gemini Live] Bidirectional streaming error: {e}", exc_info=True)
            return None

    async def _send_audio_stream(
        self,
        websocket,
        audio_input_stream: AsyncIterator[bytes]
    ):
        """Send audio chunks to Gemini Live via WebSocket"""
        try:
            frame_count = 0
            async for audio_chunk in audio_input_stream:
                if not audio_chunk:
                    continue

                # Send audio chunk as streaming content
                msg = {
                    "real_time_input": {
                        "media_stream": {
                            "mime_type": "audio/pcm",
                            "data": base64.b64encode(audio_chunk).decode('utf-8')
                        }
                    }
                }

                await websocket.send(json.dumps(msg))
                frame_count += 1

                if frame_count % 50 == 0:
                    log.debug(f"[Gemini Live] Sent {frame_count} audio frames ({frame_count * 160 / 8} bytes)")

            # Signal end of input
            await websocket.send(json.dumps({"real_time_input": {"media_stream": {}}}))
            log.info(f"[Gemini Live] Audio input stream ended. Total frames: {frame_count}")

        except Exception as e:
            log.error(f"[Gemini Live] Error sending audio: {e}")

    async def _receive_audio_stream(
        self,
        websocket,
        response_audio: bytearray,
        on_audio_chunk: Optional[Callable[[bytes], None]],
        on_text_chunk: Optional[Callable[[str], None]]
    ):
        """Receive response audio chunks from Gemini Live via WebSocket"""
        try:
            chunk_count = 0
            async for message in websocket:
                if not message:
                    continue

                try:
                    data = json.loads(message)

                    # Extract audio from server response
                    if "server_content" in data:
                        server_content = data["server_content"]

                        # Handle audio response
                        if "media_stream" in server_content:
                            audio_data = server_content["media_stream"].get("data")
                            if audio_data:
                                try:
                                    audio_bytes = base64.b64decode(audio_data)
                                    response_audio.extend(audio_bytes)
                                    chunk_count += 1

                                    if on_audio_chunk:
                                        on_audio_chunk(audio_bytes)

                                    if chunk_count % 50 == 0:
                                        log.debug(f"[Gemini Live] Received {chunk_count} audio chunks")

                                except Exception as e:
                                    log.error(f"[Gemini Live] Error decoding audio: {e}")

                        # Handle text responses
                        if "model_turn" in server_content:
                            parts = server_content["model_turn"].get("parts", [])
                            for part in parts:
                                if "text" in part:
                                    text = part["text"]
                                    if on_text_chunk:
                                        on_text_chunk(text)
                                    log.debug(f"[Gemini Live] Text: {text[:100]}...")

                except json.JSONDecodeError:
                    log.debug(f"[Gemini Live] Non-JSON message received")
                except Exception as e:
                    log.error(f"[Gemini Live] Error processing response: {e}")

            log.info(f"[Gemini Live] Audio reception completed. Total chunks: {chunk_count}")

        except Exception as e:
            log.error(f"[Gemini Live] Error receiving audio: {e}")

    async def get_text_response(self, prompt: str, system_prompt: Optional[str] = None) -> Optional[str]:
        """
        Get text response using WebSocket bidirectional streaming
        Note: gemini-2.5-flash-native-audio-preview requires bidiGenerateContent
        
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
                # For now, use a fallback text-only model for testing
                # Actual Gemini Live requires WebSocket (bidiGenerateContent)
                # which is handled by the specialized audio streaming
                
                model = self.client.GenerativeModel(
                    model_name="gemini-1.5-flash",  # Use latest stable text model
                    system_instruction=system_prompt or "You are a professional sales assistant.",
                    generation_config={
                        "temperature": self.temperature,
                        "max_output_tokens": self.max_tokens,
                    }
                )

                response = model.generate_content(prompt)
                return response.text if response else None

            except Exception as e:
                log.error(f"[Gemini Live] Generation error: {e}")
                log.info("[Gemini Live] Note: Native audio model requires WebSocket (bidiGenerateContent)")
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
        Stream response text using text-only model
        Note: Native audio streaming requires WebSocket (bidiGenerateContent)
        
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
                model = self.client.GenerativeModel(
                    model_name="gemini-1.5-flash",  # Use latest stable text model
                    system_instruction=system_prompt or "You are a professional sales assistant.",
                    generation_config={
                        "temperature": self.temperature,
                        "max_output_tokens": self.max_tokens,
                    }
                )

                full_response = ""
                
                for chunk in model.generate_content(prompt, stream=True):
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
        """Close Gemini Live session and WebSocket"""
        try:
            if self.websocket:
                try:
                    await self.websocket.close()
                    log.info(f"[Gemini Live] WebSocket closed")
                except Exception as e:
                    log.warning(f"[Gemini Live] Error closing WebSocket: {e}")
                finally:
                    self.websocket = None

            if self.session:
                self.session["status"] = "closed"
                self.session["closed_at"] = datetime.utcnow().isoformat()
                log.info(f"[Gemini Live] Session closed: {self.session_id}")
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
        log.info("[Gemini Live] Provider initialized")
    return _provider


def get_gemini_live_provider() -> Optional[GeminiLiveProvider]:
    """Get Gemini Live provider instance"""
    return _provider
