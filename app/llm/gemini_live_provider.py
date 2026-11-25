"""
Gemini Live Provider - Speech-to-Speech Audio Streaming (google-genai)
Integration with Google Gemini Live API for real-time bidirectional audio conversations
Supports WebSocket streaming for end-to-end audio processing without STT/TTS intermediaries
"""

import os
import asyncio
import json
import base64
import time
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
        self.model = os.getenv("GEMINI_LIVE_MODEL", "gemini-3.8-live")
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
        
        # Session ready event for greeting synchronization (reset for each call)
        self.session_ready_event = asyncio.Event()

    async def initialize(self) -> bool:
        """Initialize Gemini Live client using google-genai SDK with proper API version"""
        try:
            if not self.api_key:
                log.error("[Gemini Live] API key not configured")
                return False

            try:
                from google import genai
                
                # Create client with official google-genai SDK
                # Use v1beta for Gemini Live API endpoint
                self.client = genai.Client(
                    api_key=self.api_key,
                    http_options={"api_version": "v1beta"}
                )
                
                log.info(f"[Gemini Live] ✅ Client initialized successfully (google-genai SDK)")
                log.info(f"[Gemini Live]    ├─ Model: {self.model}")
                log.info(f"[Gemini Live]    ├─ API Version: v1beta")
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
            log.error(f"[Gemini Live] Initialization failed: {e}", exc_info=True)
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

            # Reset session_ready_event for new call
            self.session_ready_event.clear()

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
            
            # Signal that session is ready for greeting
            self.session_ready_event.set()
            log.info(f"[Gemini Live] ✅ Session ready event signaled - greeting can proceed")
            
            return True

        except Exception as e:
            log.error(f"[Gemini Live] Session creation error: {e}", exc_info=True)
            return False

    async def stream_audio_bidirectional(
        self,
        audio_input_stream: AsyncIterator[bytes],
        on_audio_chunk: Optional[Callable[[bytes], None]] = None,
        on_text_chunk: Optional[Callable[[str], None]] = None
    ) -> Optional[bytes]:
        """
        ✅ FIX: Proper bidirectional audio streaming via Gemini Live WebSocket
        
        CRITICAL FIX: Handle model validation and 404 errors
        """
        try:
            from google import genai
            
            if not self.session or not self.client:
                log.error("[Gemini Live] ❌ Session not active - cannot stream audio")
                return None

            log.info(f"[Gemini Live] 🎤 Starting bidirectional audio streaming: {self.session_id}")
            log.info(f"[Gemini Live]    ├─ Opening WebSocket connection to Gemini Live API")
            log.info(f"[Gemini Live]    ├─ Audio format: PCM16 @ {self.audio_config['sample_rate_hertz']}Hz")
            log.info(f"[Gemini Live]    ├─ Model: {self.model}")
            log.info(f"[Gemini Live]    └─ Waiting for caller audio and Gemini responses...")

            response_audio = bytearray()
            frame_count = 0
            response_frames = 0

            try:
                # ✅ CRITICAL FIX: Use correct model and error handling
                # The model name must be valid for Gemini Live API
                # Format: "models/gemini-2.0-flash-exp" (proper Live API model)
                model_for_live = self.model
                
                # Ensure proper prefix
                if not model_for_live.startswith("models/"):
                    model_for_live = f"models/{model_for_live}"
                
                log.info(f"[Gemini Live] Using model: {model_for_live}")

                # ✅ CRITICAL: Create WebSocket connection with response_modalities=["AUDIO"]
                try:
                    async with self.client.aio.live.connect(
                        model=model_for_live,
                        config=genai.types.LiveConnectConfig(
                            generation_config=genai.types.GenerationConfig(
                                temperature=self.temperature,
                                max_output_tokens=self.max_tokens,
                            ),
                            # ✅ CRITICAL: Configure audio response output
                            response_modalities=["AUDIO"],
                            system_instruction=self.session.get('system_prompt', 
                                "You are a helpful sales assistant. Respond concisely and naturally."),
                        ),
                    ) as session:
                        log.info(f"[Gemini Live] ✅ WebSocket connected to Gemini Live API")
                        log.info(f"[Gemini Live]    └─ Ready for bidirectional streaming")

                        # Create concurrent tasks for sending and receiving
                        async def send_audio_to_gemini():
                            """Feed caller audio to Gemini"""
                            try:
                                nonlocal frame_count
                                async for audio_chunk in audio_input_stream:
                                    if audio_chunk and len(audio_chunk) > 0:
                                        frame_count += 1
                                        
                                        try:
                                            # Send audio chunk to Gemini
                                            await session.send(
                                                genai.types.LiveClientMessage(
                                                    realtime_input=genai.types.LiveClientRealtimeInput(
                                                        media_chunks=[
                                                            genai.types.MediaChunk(
                                                                data=audio_chunk,
                                                                mime_type="audio/pcm;rate=8000"
                                                            )
                                                        ]
                                                    )
                                                )
                                            )
                                        except Exception as send_error:
                                            log.error(f"[Gemini Live] Error sending audio chunk: {send_error}")
                                            break
                                        
                                        if frame_count % 50 == 0:
                                            log.debug(f"[Gemini Live] 📤 Sent {frame_count} caller audio frames to Gemini")
                                    
                                    await asyncio.sleep(0.001)
                                
                                log.info(f"[Gemini Live] Audio input complete: {frame_count} frames sent")
                                
                            except asyncio.CancelledError:
                                log.info(f"[Gemini Live] Audio send task cancelled")
                                raise
                            except Exception as e:
                                log.error(f"[Gemini Live] ❌ Error sending audio to Gemini: {e}")
                                raise

                        async def receive_audio_from_gemini():
                            """Receive response audio and text from Gemini"""
                            try:
                                nonlocal response_frames
                                
                                async for response in session.receive():
                                    # Handle server content (text responses)
                                    if response.server_content:
                                        if response.server_content.model_turn:
                                            # Process model turn response
                                            for part in response.server_content.model_turn.parts:
                                                # Handle text
                                                if part.text:
                                                    log.info(f"[Gemini Live] 💬 Text response: {part.text[:100]}...")
                                                    if on_text_chunk:
                                                        on_text_chunk(part.text)
                                                
                                                # Handle audio response
                                                if part.inline_data and part.inline_data.data:
                                                    audio_data = part.inline_data.data
                                                    response_frames += 1
                                                    response_audio.extend(audio_data)
                                                    
                                                    log.debug(f"[Gemini Live] 📥 Response audio chunk {response_frames}: {len(audio_data)} bytes")
                                                    
                                                    if on_audio_chunk:
                                                        on_audio_chunk(audio_data)
                                        
                                        # Handle server messages
                                        if response.server_content.server_message:
                                            msg = response.server_content.server_message
                                            log.debug(f"[Gemini Live] 📨 Server message: {msg}")
                                
                                log.info(f"[Gemini Live] ✅ Audio stream complete: {response_frames} response frames received")
                                
                            except asyncio.CancelledError:
                                log.info(f"[Gemini Live] Audio receive task cancelled")
                                raise
                            except Exception as e:
                                log.error(f"[Gemini Live] ❌ Error receiving audio from Gemini: {e}")
                                raise

                        # Run send and receive concurrently
                        try:
                            await asyncio.gather(
                                send_audio_to_gemini(),
                                receive_audio_from_gemini(),
                                return_exceptions=False
                            )
                        except Exception as gather_error:
                            log.error(f"[Gemini Live] ❌ Concurrent streaming error: {gather_error}")
                            raise

                        log.info(f"[Gemini Live] ✅ Bidirectional streaming complete")
                        log.info(f"[Gemini Live]    ├─ Caller audio: {frame_count} frames sent")
                        log.info(f"[Gemini Live]    ├─ Gemini response: {response_frames} frames received")
                        log.info(f"[Gemini Live]    ├─ Response audio size: {len(response_audio)} bytes")
                        log.info(f"[Gemini Live]    └─ Ready for next turn")

                except Exception as ws_error:
                    # Handle WebSocket specific errors
                    error_str = str(ws_error)
                    if "404" in error_str or "HTTP 404" in error_str:
                        log.error(f"[Gemini Live] ❌ HTTP 404: Gemini Live API endpoint not found")
                        log.error(f"[Gemini Live]    Model: {model_for_live}")
                        log.error(f"[Gemini Live]    FIX: Check if model '{model_for_live}' supports Live API")
                        log.error(f"[Gemini Live]    FIX: Try model='models/gemini-2.0-flash-exp'")
                    else:
                        log.error(f"[Gemini Live] ❌ WebSocket connection failed: {ws_error}", exc_info=True)
                    
                    return bytes(response_audio) if response_audio else None

            except Exception as e:
                log.error(f"[Gemini Live] ❌ Gemini stream processing failed: {e}")
                log.error(f"[Gemini Live]    Session: {self.session_id}")
                log.error(f"[Gemini Live]    Frames sent: {frame_count}")
                log.error(f"[Gemini Live]    Response frames received: {response_frames}")
                return bytes(response_audio) if response_audio else None

            return bytes(response_audio) if response_audio else None

        except ImportError:
            log.error("[Gemini Live] ❌ google-genai not installed")
            log.error("[Gemini Live] Install: pip install google-genai")
            return None
        except Exception as e:
            log.error(f"[Gemini Live] ❌ Bidirectional streaming error: {e}", exc_info=True)
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
        on_chunk: Optional[Callable[[str], None]] = None,
        on_audio_chunk: Optional[Callable[[bytes], None]] = None
    ) -> Optional[str]:
        """
        Stream response using google-genai
        
        Can return either text or audio depending on configuration
        
        Args:
            prompt: User prompt
            system_prompt: System prompt
            on_chunk: Callback for each text chunk
            on_audio_chunk: Callback for each audio chunk (for live streaming)
        
        Returns:
            Complete response (text or audio bytes)
        """
        try:
            from google import genai
            
            if not self.client:
                log.error("[Gemini Live] Client not initialized")
                return None

            # If session is active and audio callback requested, use live API for audio response
            if self.session and on_audio_chunk:
                log.info(f"[Gemini Live] 🎵 Sending greeting text to Gemini Live for audio synthesis...")
                
                try:
                    # Use Live API for audio response
                    model_name = self.model
                    if not model_name.startswith("models/"):
                        model_name = f"models/{model_name}"
                    
                    async with self.client.aio.live.connect(
                        model=model_name,
                        config=genai.types.LiveConnectConfig(
                            generation_config=genai.types.GenerationConfig(
                                temperature=self.temperature,
                                max_output_tokens=self.max_tokens,
                            ),
                            response_modalities=["AUDIO"],
                            system_instruction=system_prompt or self.session.get('system_prompt', 
                                "You are a helpful sales assistant. Respond concisely and naturally."),
                        ),
                    ) as session:
                        log.info(f"[Gemini Live] 🔌 Connected to Live API for greeting audio synthesis")
                        
                        # Send prompt
                        await session.send(
                            genai.types.LiveClientMessage(
                                realtime_input=genai.types.LiveClientRealtimeInput(
                                    media_chunks=[]  # No audio input for greeting
                                )
                            )
                        )
                        
                        # Send text prompt
                        await session.send(
                            genai.types.LiveClientMessage(
                                client_content=genai.types.ClientContent(
                                    turns=[
                                        genai.types.Content(
                                            role="user",
                                            parts=[
                                                genai.types.Part(text=prompt)
                                            ]
                                        )
                                    ],
                                    turn_complete=True
                                )
                            )
                        )
                        
                        log.info(f"[Gemini Live] 📤 Greeting prompt sent, waiting for audio response...")
                        
                        response_audio = bytearray()
                        frame_count = 0
                        
                        # Receive audio response
                        async for response in session.receive():
                            if response.server_content and response.server_content.model_turn:
                                for part in response.server_content.model_turn.parts:
                                    if part.inline_data and part.inline_data.data:
                                        audio_data = part.inline_data.data
                                        frame_count += 1
                                        response_audio.extend(audio_data)
                                        
                                        log.debug(f"[Gemini Live] 📥 Greeting audio chunk {frame_count}: {len(audio_data)} bytes")
                                        
                                        # Callback with audio chunk
                                        if on_audio_chunk:
                                            on_audio_chunk(audio_data)
                        
                        log.info(f"[Gemini Live] ✅ Greeting audio complete: {frame_count} frames, {len(response_audio)} bytes total")
                        return bytes(response_audio) if response_audio else None
                        
                except Exception as e:
                    log.error(f"[Gemini Live] Error in greeting audio synthesis: {e}", exc_info=True)
                    return None
            
            # Otherwise use standard text model
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

        except ImportError:
            log.error("[Gemini Live] google-genai not installed")
            return None
        except Exception as e:
            log.error(f"[Gemini Live] Error: {e}", exc_info=True)
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
