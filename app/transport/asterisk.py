"""
Asterisk ARI Integration Module
Handles Asterisk REST Interface operations and WebSocket event streaming
"""

import asyncio
import json
import logging
import time
from typing import Optional, Dict, Any, Callable
import aiohttp

from ..core.config import (
    ARI_URL, ARI_USER, ARI_PASS, STASIS_APP, ASTERISK_IP,
    RTP_START_PORT, RTP_END_PORT, log, MY_PC_IP, LOCAL_RTP_IP,
    START_PORT, END_PORT
)

_ari_session: Optional[aiohttp.ClientSession] = None
_ari_ws_session: Optional[aiohttp.ClientSession] = None
_port_lock: Optional[asyncio.Lock] = None
_ws_connection: Optional[aiohttp.ClientWebSocketResponse] = None
_event_handlers: Dict[str, Callable] = {}
_ws_task: Optional[asyncio.Task] = None

_available_ports = set(range(START_PORT, END_PORT + 1, 2))
_quarantined_ports: Dict[int, float] = {}

def _validate_ari_config() -> bool:
    """
    Validate ARI configuration at startup
    
    Returns:
        True if all required ARI config is present and valid, False otherwise
    """
    errors = []
    
    # Check required config variables
    if not ARI_URL:
        errors.append("ARI_URL is not set")
    else:
        log.info(f"[ARI-CONFIG] ✓ ARI_URL: {ARI_URL}")
    
    if not ARI_USER:
        errors.append("ARI_USER is not set")
    else:
        log.info(f"[ARI-CONFIG] ✓ ARI_USER: {ARI_USER}")
    
    if not ARI_PASS:
        errors.append("ARI_PASS is not set")
    else:
        log.info(f"[ARI-CONFIG] ✓ ARI_PASS: (configured)")
    
    if not STASIS_APP:
        errors.append("STASIS_APP is not set")
    else:
        log.info(f"[ARI-CONFIG] ✓ STASIS_APP: {STASIS_APP}")
    
    if not ASTERISK_IP:
        errors.append("ASTERISK_IP is not set")
    else:
        log.info(f"[ARI-CONFIG] ✓ ASTERISK_IP: {ASTERISK_IP}")
    
    if not MY_PC_IP:
        errors.append("MY_PC_IP is not set")
    else:
        log.info(f"[ARI-CONFIG] ✓ MY_PC_IP: {MY_PC_IP}")
    
    # Check RTP port range
    if RTP_START_PORT >= RTP_END_PORT:
        errors.append(f"Invalid RTP port range: {RTP_START_PORT}-{RTP_END_PORT}")
    else:
        log.info(f"[ARI-CONFIG] ✓ RTP port range: {RTP_START_PORT}-{RTP_END_PORT}")
    
    if errors:
        log.error("[ARI-CONFIG] ❌ Configuration validation FAILED:")
        for error in errors:
            log.error(f"[ARI-CONFIG]    - {error}")
        return False
    else:
        log.info("[ARI-CONFIG] ✅ All ARI configuration variables validated successfully")
        return True

async def init_ari_session():
    """Initialize the ARI HTTP session"""
    global _ari_session, _port_lock
    try:
        # Validate configuration first
        if not _validate_ari_config():
            raise RuntimeError("ARI configuration validation failed")
        
        _ari_session = aiohttp.ClientSession()
        _port_lock = asyncio.Lock()
        log.info(f"[ARI] ✅ HTTP Session initialized: {ARI_URL}")
        log.info(f"[ARI]    Auth: {ARI_USER}@{ASTERISK_IP}:8088")
        log.info(f"[ARI]    Stasis App: {STASIS_APP}")
        log.info(f"[ARI]    Ready for bridge/ExternalMedia operations")
        return _ari_session
    except Exception as e:
        log.error(f"[ARI] ❌ HTTP Session initialization failed: {e}")
        raise

async def close_ari_session():
    """Close the ARI session and WebSocket connections"""
    global _ari_session, _ari_ws_session, _ws_connection, _ws_task

    log.info("[ARI] Starting clean shutdown...")

    if _ws_task:
        log.info("[ARI] Cancelling WebSocket task...")
        _ws_task.cancel()
        try:
            await asyncio.wait_for(_ws_task, timeout=2.0)
        except asyncio.CancelledError:
            log.info("[ARI] WebSocket task cancelled successfully")
        except asyncio.TimeoutError:
            log.warning("[ARI] WebSocket task cancellation timed out")
        except Exception as e:
            log.warning(f"[ARI] Error waiting for WebSocket task: {e}")
        _ws_task = None

    if _ws_connection:
        try:
            log.info("[ARI] Closing WebSocket connection...")
            await _ws_connection.close()
            log.info("[ARI] WebSocket connection closed")
        except Exception as e:
            log.warning(f"[ARI] Error closing WebSocket: {e}")
        _ws_connection = None

    if _ari_ws_session:
        try:
            log.info("[ARI] Closing WebSocket session...")
            await _ari_ws_session.close()
            log.info("[ARI] WebSocket session closed")
        except Exception as e:
            log.warning(f"[ARI] Error closing WebSocket session: {e}")
        _ari_ws_session = None

    if _ari_session:
        try:
            log.info("[ARI] Closing HTTP session...")
            await _ari_session.close()
            log.info("[ARI] HTTP session closed")
        except Exception as e:
            log.warning(f"[ARI] Error closing HTTP session: {e}")
        _ari_session = None

    log.info("[ARI] Shutdown complete - all sessions closed")

async def ari_request(method: str, path: str, payload: Optional[Dict] = None,
                       params: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Make an ARI API request with automatic lazy initialization
    
    If the session is None or closed, automatically reinitialize it.
    This handles race conditions and ensures resilience.
    """
    global _ari_session
    
    # Check if session is None or closed, and auto-reinitialize if needed
    if not _ari_session or _ari_session.closed:
        log.warning("[ARI] HTTP Session not initialized or closed - attempting lazy re-initialization...")
        try:
            await init_ari_session()
            log.info("[ARI] ✓ HTTP Session re-initialized successfully")
        except Exception as e:
            log.error(f"[ARI] ✗ Failed to lazy re-initialize HTTP Session: {e}")
            return {}

    try:
        url = f"{ARI_URL}{path}"
        auth = aiohttp.BasicAuth(ARI_USER, ARI_PASS)

        async with _ari_session.request(
            method, url,
            json=payload,
            params=params,
            auth=auth,
            timeout=aiohttp.ClientTimeout(total=5)
        ) as resp:
            if resp.status in (200, 201):
                if resp.content_type == 'application/json':
                    try:
                        return await resp.json()
                    except:
                        return {}
                text = await resp.text()
                return json.loads(text) if text.strip() else {}

            elif resp.status == 204:
                log.debug(f"[ARI] {method} {path} → 204 No Content (success)")
                return {}

            elif resp.status == 404:
                log.debug(f"[ARI] {method} {path} → 404 Not Found (channel already cleaned up, benign race condition)")
                return {}

            else:
                error_text = await resp.text()
                log.warning(f"[ARI] {method} {path} → {resp.status}: {error_text}")
                return {}

    except asyncio.TimeoutError:
        log.warning(f"[ARI] Request timeout: {method} {path}")
        return {}
    except Exception as e:
        log.error(f"[ARI] Request error: {method} {path} - {e}")
        return {}

async def init_ari_websocket():
    """
    Initialize ARI WebSocket connection to Asterisk
    This creates a persistent connection that listens for Stasis app events
    
    CRITICAL: This must be called at startup and run as a background task
    """
    global _ari_ws_session, _ws_task
    try:
        _ari_ws_session = aiohttp.ClientSession()

        _ws_task = asyncio.create_task(_websocket_event_loop())
        log.info("[ARI-WS] WebSocket task started (background)")

        return True
    except Exception as e:
        log.error(f"[ARI-WS] WebSocket initialization failed: {e}")
        if _ari_ws_session:
            await _ari_ws_session.close()
            _ari_ws_session = None
        return False

async def _websocket_event_loop():
    """
    Main event loop for ARI WebSocket connection
    Handles reconnection and event processing with proper shutdown
    """
    global _ws_connection, _ari_ws_session

    reconnect_delay = 1
    max_reconnect_delay = 30
    shutdown_requested = False

    while not shutdown_requested:
        try:
            ws_url = f"ws://{ASTERISK_IP}:8088/ari/events"
            auth = aiohttp.BasicAuth(ARI_USER, ARI_PASS)

            log.info(f"[ARI-WS] Connecting to {ws_url} as app '{STASIS_APP}'...")

            async with _ari_ws_session.ws_connect(
                ws_url,
                auth=auth,
                params={
                    "app": STASIS_APP,
                    "subscriptions": ["channel:*"]
                },
                heartbeat=30,
                timeout=aiohttp.ClientTimeout(total=None)
            ) as ws:
                _ws_connection = ws
                reconnect_delay = 1
                log.info(f"[ARI-WS] ✅ Connected to Asterisk ARI as app '{STASIS_APP}'")
                log.info("[ARI-WS] Listening for Stasis events...")

                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        try:
                            event = json.loads(msg.data)
                            log.debug(f"[ARI-WS] Event received: {event.get('type', 'unknown')}")

                            await _dispatch_event(event)
                        except json.JSONDecodeError as e:
                            log.warning(f"[ARI-WS] JSON decode error: {e}")

                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        log.error(f"[ARI-WS] WebSocket error: {ws.exception()}")
                        break

                    elif msg.type == aiohttp.WSMsgType.CLOSED:
                        log.warning("[ARI-WS] WebSocket connection closed by server")
                        break

        except asyncio.CancelledError:
            log.info("[ARI-WS] WebSocket connection cancelled - SHUTTING DOWN")
            shutdown_requested = True
            if _ws_connection:
                try:
                    await _ws_connection.close()
                except:
                    pass
                _ws_connection = None
            break

        except Exception as e:
            log.error(f"[ARI-WS] Connection error: {e}")
            if _ws_connection:
                try:
                    await _ws_connection.close()
                except:
                    pass
                _ws_connection = None

        if not shutdown_requested:
            log.warning(f"[ARI-WS] Reconnecting in {reconnect_delay}s...")
            try:
                await asyncio.sleep(reconnect_delay)
            except asyncio.CancelledError:
                log.info("[ARI-WS] Reconnection sleep cancelled - SHUTTING DOWN")
                shutdown_requested = True
                break
            reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)

    log.info("[ARI-WS] WebSocket event loop FINISHED")

async def _dispatch_event(event: Dict[str, Any]):
    """
    Dispatch ARI events to registered handlers
    """
    try:
        event_type = event.get("type")

        if event_type in _event_handlers:
            handler = _event_handlers[event_type]
            await handler(event)
        else:
            log.debug(f"[ARI-WS] No handler for event type: {event_type}")

    except Exception as e:
        log.error(f"[ARI-WS] Event dispatch error: {e}", exc_info=True)

def register_event_handler(event_type: str, handler: Callable):
    """
    Register a handler for a specific ARI event type
    
    Args:
        event_type: e.g., "StasisStart", "StasisEnd", "ChannelDtmfReceived"
        handler: async callable that receives the event dict
    """
    _event_handlers[event_type] = handler
    log.info(f"[ARI-WS] Handler registered for event type: {event_type}")

async def send_ari_command(channel_id: str, command: str, params: Optional[Dict] = None) -> tuple[bool, Dict[str, Any]]:
    """
    Send an ARI command to a channel
    
    Returns:
        tuple: (success: bool, response: Dict)
        - success=True only if HTTP status is 2xx
        - success=False for any other status (3xx, 4xx, 5xx)
    
    Examples:
    - playback: success, resp = await send_ari_command(cid, "playback", {"media": "sound:welcome"})
    - answer: success, resp = await send_ari_command(cid, "answer")
    - hangup: success, resp = await send_ari_command(cid, "hangup")
    """
    if not _ari_session:
        log.error("[ARI] HTTP Session not initialized")
        return False, {}

    try:
        url = f"{ARI_URL}/ari/channels/{channel_id}/{command}"
        auth = aiohttp.BasicAuth(ARI_USER, ARI_PASS)

        async with _ari_session.request(
            "POST", url,
            json=params,
            auth=auth,
            timeout=aiohttp.ClientTimeout(total=5)
        ) as resp:
            log.debug(f"[ARI] POST /ari/channels/{channel_id}/{command} → {resp.status}")

            response_body = ""
            try:
                if resp.content_type == 'application/json':
                    response_body = await resp.json()
                else:
                    response_body = await resp.text()
            except:
                pass

            if 200 <= resp.status < 300:
                log.debug(f"[ARI] {command} succeeded on {channel_id}")
                return True, response_body if isinstance(response_body, dict) else {}

            error_msg = ""
            if isinstance(response_body, dict):
                error_msg = response_body.get("message", str(response_body))
            else:
                error_msg = str(response_body)

            log.error(f"[ARI] {command} FAILED on {channel_id}: HTTP {resp.status} - {error_msg}")
            return False, {"error": error_msg, "status": resp.status}

    except asyncio.TimeoutError:
        log.error(f"[ARI] {command} timeout on {channel_id}")
        return False, {"error": "timeout"}
    except Exception as e:
        log.error(f"[ARI] {command} exception on {channel_id}: {e}")
        return False, {"error": str(e)}

async def playback_audio(channel_id: str, audio_data_or_path) -> bool:
    """
    ⚠️ DEPRECATED FOR TTS: Do NOT use this for dynamic TTS audio
    
    This function is ONLY for:
    - Asterisk built-in sounds (sound:welcome)
    - Static pre-recorded files in Asterisk sounds directory
    
    For DYNAMIC TTS AUDIO:
    - Use MediaSession.send_audio_response() for real-time RTP streaming instead
    - This bypasses file I/O and cross-OS/cross-network issues
    
    Historical note: Previous approach of writing to Windows temp files
    and sending file:/// URIs to Asterisk (Ubuntu) always failed with 404
    because file paths don't work cross-OS/cross-network.
    
    Returns:
        True only if using built-in sounds (string parameter)
        False for audio bytes (redirects to RTP streaming via media service)
    """
    try:
        if isinstance(audio_data_or_path, bytes):
            log.error(
                f"[ARI-PLAYBACK] ❌ CRITICAL: playback_audio() called with bytes (TTS audio) "
                f"This method is DEPRECATED for TTS. Use MediaSession.send_audio_response() instead "
                f"for real-time RTP streaming to Asterisk."
            )
            return False

        elif isinstance(audio_data_or_path, str):
            media_uri = audio_data_or_path

            if not media_uri.startswith("sound:"):
                log.error(f"[ARI-PLAYBACK] ❌ Invalid sound URI: {media_uri}")
                log.error(f"[ARI-PLAYBACK] For file playback, use: sound:filename")
                log.error(f"[ARI-PLAYBACK] For TTS audio, use MediaSession.send_audio_response()")
                return False

            log.debug(f"[ARI-PLAYBACK] Using Asterisk built-in sound: {media_uri}")

            success, response = await send_ari_command(
                channel_id,
                "playback",
                {"media": media_uri}
            )

            if success:
                log.info(f"[ARI-PLAYBACK] ✅ Built-in sound playback initiated: {media_uri}")
                return True
            else:
                error_msg = response.get("error", "unknown error")
                log.error(f"[ARI-PLAYBACK] ❌ Playback FAILED: {error_msg}")
                return False

        else:
            log.error(f"[ARI-PLAYBACK] ❌ Invalid audio data type: {type(audio_data_or_path)}")
            log.error(f"[ARI-PLAYBACK] For TTS audio bytes, use MediaSession.send_audio_response() instead")
            return False

    except Exception as e:
        log.error(f"[ARI-PLAYBACK] ❌ Exception: {e}")
        return False

async def _cleanup_audio_file(filepath: str, delay: int = 5):
    """
    ⚠️ DEPRECATED: This function is no longer used
    Previous temp file approach for TTS playback is now obsolete
    Replaced by real-time RTP streaming via MediaSession.send_audio_response()
    
    Kept for backward compatibility only
    """
    try:
        await asyncio.sleep(delay)
        import os
        if os.path.exists(filepath):
            os.remove(filepath)
            log.debug(f"[ARI-CLEANUP] Removed: {filepath}")
    except Exception as e:
        log.debug(f"[ARI-CLEANUP] Could not clean up: {filepath} - {e}")

async def record_audio(channel_id: str, filename: str, format: str = "wav") -> bool:
    """
    Start recording audio from a channel
    
    Args:
        channel_id: Asterisk channel ID
        filename: Output filename
        format: Audio format (wav, ulaw, alaw)
    
    Returns:
        True if recording was started
    """
    try:
        result = await send_ari_command(
            channel_id,
            "record",
            {
                "name": filename,
                "format": format,
                "maxDurationSeconds": 300
            }
        )

        if result:
            log.info(f"[ARI] Recording started: {filename} on {channel_id}")
            return True
        else:
            log.warning(f"[ARI] Record command failed for {channel_id}")
            return False
    except Exception as e:
        log.error(f"[ARI] Record error: {e}")
        return False

async def blind_transfer(channel_id: str, context: str, extension: str, priority: str = "1") -> bool:
    """
    Transfer call to another extension (blind transfer)
    
    Args:
        channel_id: Asterisk channel ID
        context: Dialplan context (e.g., "CallCenterQueueIncoming")
        extension: Extension to transfer to (e.g., "CallCenterQueueIncoming")
        priority: Dialplan priority (default: "1")
    
    Returns:
        True if transfer was initiated
    """
    try:
        # ✅ FIX: Detect channel technology and use appropriate endpoint format
        # For PJSIP channels: Use PJSIP/extension format
        # For Local/SIP channels: Use Local/extension@context format
        
        channel_tech = channel_id.split("/")[0] if "/" in channel_id else "PJSIP"
        
        # Determine endpoint format based on channel technology
        if "PJSIP" in channel_tech.upper():
            # PJSIP channel - use PJSIP endpoint
            endpoint = f"PJSIP/{extension}"
            log.info(f"[ARI] ✅ PJSIP channel detected - using PJSIP endpoint format")
        else:
            # Local/other channels - use Local endpoint
            endpoint = f"Local/{extension}@{context}"
            log.info(f"[ARI] ✅ Non-PJSIP channel detected - using Local endpoint format")
        
        log.info(f"[ARI] Executing blind transfer")
        log.info(f"[ARI]    ├─ Channel: {channel_id}")
        log.info(f"[ARI]    ├─ Channel Tech: {channel_tech}")
        log.info(f"[ARI]    ├─ Context: {context}")
        log.info(f"[ARI]    ├─ Extension: {extension}")
        log.info(f"[ARI]    └─ Endpoint: {endpoint}")
        
        success, response = await send_ari_command(
            channel_id,
            "redirect",
            {
                "endpoint": endpoint,
            }
        )

        if success:
            log.info(f"[ARI] ✅ Transfer succeeded: {endpoint} on {channel_id}")
            return True
        else:
            log.warning(f"[ARI] ❌ Transfer command failed for {channel_id}")
            log.warning(f"[ARI]    └─ Response: {response}")
            return False
    except Exception as e:
        log.error(f"[ARI] ❌ Transfer error: {e}")
        return False

async def answer_channel(channel_id: str) -> bool:
    """Answer an incoming channel"""
    try:
        success, response = await send_ari_command(channel_id, "answer")
        if success:
            log.info(f"[ARI] ✅ Channel answered: {channel_id}")
            return True
        else:
            error_msg = response.get("error", "unknown error")
            log.error(f"[ARI] ❌ Answer FAILED on {channel_id}: {error_msg}")
            return False
    except Exception as e:
        log.error(f"[ARI] ❌ Answer exception on {channel_id}: {e}")
        return False

async def hangup_channel(channel_id: str, reason: str = "normal") -> bool:
    """
    Hangup a channel with idempotent behavior
    
    404 is EXPECTED if channel already hung up - treat as success
    """
    try:
        success, response = await send_ari_command(channel_id, "hangup")
        if success:
            log.info(f"[ARI] ✅ Channel hung up: {channel_id} (reason={reason})")
            return True
        else:
            error_msg = response.get("error", "unknown error")
            if "404" in str(error_msg) or "Resource not found" in str(error_msg) or "not found" in str(error_msg).lower():
                log.debug(f"[ARI] ✅ Channel already disconnected: {channel_id} (expected 404)")
                return True
            else:
                log.error(f"[ARI] ❌ Hangup FAILED on {channel_id}: {error_msg}")
                return False
    except Exception as e:
        log.error(f"[ARI] ❌ Hangup exception on {channel_id}: {e}")
        return False

async def create_bridge(bridge_type: str = "mixing") -> Optional[str]:
    """
    Create an Asterisk bridge for mixing audio
    
    Args:
        bridge_type: Type of bridge ("mixing", "holding", "dtmf_events", "all_dtmf_events")
    
    Returns:
        Bridge ID if successful, None otherwise
    """
    try:
        bridge_data = {
            "type": bridge_type,
            "name": f"ai-bridge-{int(time.time() * 1000)}"
        }

        log.info(f"[ARI-BRIDGE] Creating {bridge_type} bridge: {bridge_data['name']}")
        log.debug(f"[ARI-BRIDGE] ARI endpoint: POST {ARI_URL}/ari/bridges")
        log.debug(f"[ARI-BRIDGE] Auth: {ARI_USER}@{ARI_URL}")

        response = await ari_request("POST", "/ari/bridges", payload=bridge_data)

        if response and "id" in response:
            bridge_id = response["id"]
            log.info(f"[ARI-BRIDGE] ✅ Successfully created bridge: {bridge_id}")
            log.info(f"[ARI-BRIDGE]    Type: {bridge_type}")
            log.info(f"[ARI-BRIDGE]    Name: {bridge_data['name']}")
            return bridge_id
        else:
            log.error(f"[ARI-BRIDGE] ❌ Failed to create bridge: {bridge_type}")
            log.error(f"[ARI-BRIDGE] Response: {response}")
            log.error(f"[ARI-BRIDGE] Expected response to contain 'id' field")
            if isinstance(response, dict):
                log.error(f"[ARI-BRIDGE] Response keys: {response.keys()}")
                if "message" in response:
                    log.error(f"[ARI-BRIDGE] Error message: {response.get('message')}")
            return None
    except Exception as e:
        log.error(f"[ARI-BRIDGE] ❌ Bridge creation exception: {e}")
        log.error(f"[ARI-BRIDGE] Exception type: {type(e).__name__}")
        import traceback
        log.error(f"[ARI-BRIDGE] Traceback: {traceback.format_exc()}")
        return None

async def add_channel_to_bridge(bridge_id: str, channel_id: str, role: str = "participant") -> bool:
    """
    Add a channel to a bridge
    
    Args:
        bridge_id: Bridge ID
        channel_id: Channel ID to add
        role: Role in bridge ("participant", "moderator")
    
    Returns:
        True if successful
    """
    try:
        params = {
            "channel": channel_id,
            "role": role
        }

        response = await ari_request("POST", f"/ari/bridges/{bridge_id}/addChannel", payload=params)

        if response is not None or response == {}:
            log.info(f"[ARI-BRIDGE] ✅ Added channel to bridge: {channel_id} → {bridge_id}")
            return True
        else:
            log.error(f"[ARI-BRIDGE] ❌ Failed to add channel to bridge: {response}")
            return False
    except Exception as e:
        log.error(f"[ARI-BRIDGE] ❌ add_channel_to_bridge exception: {e}")
        return False

async def create_external_media(call_id: str, formats: str = "ulaw", rtp_ip: str = MY_PC_IP, rtp_port: int = 0) -> Optional[Dict[str, Any]]:
    """
    Create an ExternalMedia channel for real-time RTP streaming
    
    Args:
        call_id: Call ID (for unique identification)
        formats: Audio format ("ulaw", "alaw", "slin", "slin16")
        rtp_ip: Local RTP IP (where we receive/send audio)
        rtp_port: Local RTP port (0 = auto-assign)
    
    Returns:
        ExternalMedia response with channel_id, or None if failed
    """
    try:
        external_host = f"{rtp_ip}:{rtp_port}" if rtp_port else f"{rtp_ip}:0"
        external_media_data = {
            "app": STASIS_APP,
            "external_host": external_host,
            "format": formats,
            "channelId": f"external-{call_id}"
        }

        log.info(f"[ARI-EXTERNAL-MEDIA] Creating ExternalMedia channel for call: {call_id}")
        log.info(f"[ARI-EXTERNAL-MEDIA]    Format: {formats}")
        log.info(f"[ARI-EXTERNAL-MEDIA]    External Host: {external_host}")
        log.info(f"[ARI-EXTERNAL-MEDIA]    Channel ID: {external_media_data['channelId']}")
        log.info(f"[ARI-EXTERNAL-MEDIA]    Stasis App: {STASIS_APP}")
        log.debug(f"[ARI-EXTERNAL-MEDIA] ARI endpoint: POST {ARI_URL}/ari/channels/externalMedia")
        log.debug(f"[ARI-EXTERNAL-MEDIA] Payload: {external_media_data}")

        response = await ari_request("POST", "/ari/channels/externalMedia", payload=external_media_data)

        if response and "id" in response:
            channel_id = response["id"]
            log.info(f"[ARI-EXTERNAL-MEDIA] ✅ Successfully created ExternalMedia channel: {channel_id}")
            log.info(f"[ARI-EXTERNAL-MEDIA]    For Call: {call_id}")
            log.info(f"[ARI-EXTERNAL-MEDIA]    RTP Endpoint: {external_host}")
            log.debug(f"[ARI-EXTERNAL-MEDIA]    Full Response: {response}")
            return response
        else:
            log.error(f"[ARI-EXTERNAL-MEDIA] ❌ Failed to create ExternalMedia channel for {call_id}")
            log.error(f"[ARI-EXTERNAL-MEDIA] Response: {response}")
            log.error(f"[ARI-EXTERNAL-MEDIA] Expected response to contain 'id' field")
            if isinstance(response, dict):
                log.error(f"[ARI-EXTERNAL-MEDIA] Response keys: {response.keys()}")
                if "message" in response:
                    log.error(f"[ARI-EXTERNAL-MEDIA] Error message: {response.get('message')}")
            return None
    except Exception as e:
        log.error(f"[ARI-EXTERNAL-MEDIA] ❌ ExternalMedia creation exception for {call_id}: {e}")
        log.error(f"[ARI-EXTERNAL-MEDIA] Exception type: {type(e).__name__}")
        import traceback
        log.error(f"[ARI-EXTERNAL-MEDIA] Traceback: {traceback.format_exc()}")
        return None

async def allocate_rtp_port() -> Optional[int]:
    """Allocate an RTP port"""
    global _available_ports, _port_lock

    async with _port_lock:
        if _available_ports:
            port = _available_ports.pop()
            log.debug(f"[RTP] Port allocated: {port}")
            return port

        log.warning("[RTP] No ports available")
        return None

async def release_rtp_port(port: int):
    """Release an RTP port"""
    global _available_ports, _port_lock

    async with _port_lock:
        if port not in _available_ports:
            _available_ports.add(port)
            log.debug(f"[RTP] Port released: {port}")


async def play_language_selection_prompt(channel_id: str) -> bool:
    """
    Play language selection prompt to caller
    "Press 1 for English, Press 2 for Hindi"
    
    Uses Asterisk built-in playback with custom prompt generation
    or Asterisk voice announcements
    
    Args:
        channel_id: Channel ID to play prompt on
        
    Returns:
        True if prompt was initiated successfully
    """
    try:
        log.info(f"[LANG-PROMPT] Playing language selection prompt to {channel_id}")
        
        # Try to use Asterisk built-in playback with sound files
        # This attempts to play a TTS-like prompt via Asterisk's Say application
        success, response = await send_ari_command(
            channel_id,
            "play",
            {
                "media": "sound:vm-extension"  # "Press a key" or similar generic prompt
            }
        )
        
        if success:
            log.info(f"[LANG-PROMPT] ✅ Language selection prompt initiated")
            return True
        else:
            log.warning(f"[LANG-PROMPT] Built-in playback failed, attempting alternative...")
            
            # Alternative: Use send_ari_command with play endpoint
            success, response = await send_ari_command(
                channel_id,
                "playback",
                {"media": "sound:press-1"}
            )
            
            if success:
                log.info(f"[LANG-PROMPT] ✅ Language selection prompt played via fallback")
                return True
            else:
                log.warning(f"[LANG-PROMPT] ⚠️ Language prompt playback failed but DTMF will still be captured")
                # Don't fail - DTMF will still be captured by ARI even if prompt doesn't play
                return True
                
    except Exception as e:
        log.error(f"[LANG-PROMPT] Error playing language prompt: {e}", exc_info=True)
        # Don't fail - DTMF will still be captured
        return True


def get_ari_session() -> Optional[aiohttp.ClientSession]:
    """Get the global ARI HTTP session"""
    return _ari_session

def is_ari_websocket_connected() -> bool:
    """Check if WebSocket is connected"""
    global _ws_connection
    return _ws_connection is not None and not _ws_connection.is_closed()
