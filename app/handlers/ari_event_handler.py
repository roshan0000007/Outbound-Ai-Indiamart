"""
ARI Event Handler
Processes Asterisk ARI WebSocket events
Routes events to appropriate call handlers
"""

import asyncio
from typing import Dict, Any, Optional
from datetime import datetime
import uuid

from ..core.config import log
from ..core.redis import set_session, get_session, delete_session
from ..services.live_call_handler import get_live_call_handler
from ..services.media_service import get_media_service
from ..services.call_service import get_call_service
from ..handlers.call_handler import get_call_handler

def extract_dnid(channel: Dict[str, Any]) -> Optional[str]:
    """
    Extract called number (DNID) from ARI channel object
    
    Returns:
        DNID string or None if not found
    """
    try:
        # Try multiple sources
        if channel.get("dialed", {}).get("number"):
            return channel["dialed"]["number"]
        
        exten = channel.get("dialplan", {}).get("exten")
        if exten and exten not in ("s", "unknown"):
            return exten
        
        if channel.get("called", {}).get("number"):
            return channel["called"]["number"]
        
        return None

    except Exception as e:
        log.error(f"[ARI] DNID extraction error: {e}")
        return None


def extract_caller_number(channel: Dict[str, Any]) -> Optional[str]:
    """
    Extract caller number from ARI channel object
    
    Returns:
        Caller number string or None if not found
    """
    try:
        if channel.get("caller", {}).get("number"):
            return channel["caller"]["number"]
        
        return None

    except Exception as e:
        log.error(f"[ARI] Caller extraction error: {e}")
        return None


async def handle_stasis_start(event: Dict[str, Any]) -> bool:
    """
    Handle StasisStart event - new call incoming
    
    ✅ FIX #1: Ignore external-* channels (ExternalMedia channels we created)
    When we create an ExternalMedia channel via ARI, Asterisk enters it into Stasis.
    This triggers StasisStart again, but it's NOT a new incoming call - it's OUR channel.
    We detect and ignore these to prevent duplicate call initialization.
    
    CRITICAL ORCHESTRATION SEQUENCE:
    1. Initialize call session and media (creates RTP socket, binds to MY_PC_IP:port)
    2. Create mixing bridge
    3. Add original caller channel to bridge
    4. Create ExternalMedia channel with the allocated RTP port
    5. Add ExternalMedia channel to bridge
    6. Now Asterisk knows where to send RTP (to the allocated port)
    7. Start RTP receive loop
    
    Args:
        event: ARI StasisStart event
        
    Returns:
        True if handled successfully
    """
    try:
        channel = event.get("channel", {})
        call_id = channel.get("id")
        
        if not call_id:
            log.error("[ARI] StasisStart: missing call_id")
            return False

        # ✅ FIX #1: Ignore external-* channels (ExternalMedia channels we created)
        if call_id.startswith("external-"):
            log.info(f"[ARI] ✅ Ignoring ExternalMedia channel StasisStart: {call_id}")
            log.info(f"[ARI]    └─ This is our RTP bridge channel (not an incoming call)")
            return True  # Return True (success), just don't process it

        dnid = extract_dnid(channel)
        caller_number = extract_caller_number(channel)

        if not dnid or not caller_number:
            log.error(f"[ARI] StasisStart: missing dnid or caller_number")
            return False

        log.info(f"[ARI] ✅ Call started: {call_id} from {caller_number} to {dnid}")

        # ========== LIFECYCLE LOG: Call Start ==========
        try:
            from ..services.call_lifecycle_logger import get_call_lifecycle_logger
            lifecycle_logger = get_call_lifecycle_logger()
            if lifecycle_logger:
                lifecycle_logger.log_call_start(call_id, caller_number, dnid)
        except Exception as e:
            log.warning(f"[ARI] Error logging call start: {e}")

        # ========== STEP 1: Initialize call session and media ==========
        call_handler = get_call_handler()
        success = await call_handler.on_call_start(
            call_id=call_id,
            user_id=1,  # Default user
            dnid=dnid,
            caller_number=caller_number
        )

        if not success:
            log.error(f"[ARI] Call initialization failed for {call_id}")
            return False

        # Get the media session to access the allocated RTP port
        media_service = get_media_service()
        media_session = None
        allocated_rtp_port = None
        
        if media_service:
            media_session = await media_service.get_session(call_id)
            if media_session and media_session.local_port:
                allocated_rtp_port = media_session.local_port
                log.info(f"[ARI-ORCHESTRATION] ✅ Media session allocated RTP port: {allocated_rtp_port}")
            else:
                log.warning(f"[ARI-ORCHESTRATION] ⚠️ Could not get RTP port from media session")
        
        if not allocated_rtp_port:
            log.error(f"[ARI-ORCHESTRATION] ❌ Failed to allocate RTP port for {call_id}")
            return False

        # ========== STEP 2: Create mixing bridge ==========
        from ..transport.asterisk import create_bridge, add_channel_to_bridge, create_external_media
        
        bridge_id = await create_bridge("mixing")
        if not bridge_id:
            log.error(f"[ARI-ORCHESTRATION] ❌ Failed to create bridge for {call_id}")
            return False
        
        log.info(f"[ARI-ORCHESTRATION] ✅ Bridge created: {bridge_id}")

        # ========== LIFECYCLE LOG: Bridge Ready ==========
        try:
            from ..services.call_lifecycle_logger import get_call_lifecycle_logger
            lifecycle_logger = get_call_lifecycle_logger()
            if lifecycle_logger:
                lifecycle_logger.log_bridge_ready(call_id, bridge_id)
        except Exception as e:
            log.warning(f"[ARI] Error logging bridge ready: {e}")

        # ========== STEP 3: Add original caller channel to bridge ==========
        added_caller = await add_channel_to_bridge(bridge_id, call_id)
        if not added_caller:
            log.error(f"[ARI-ORCHESTRATION] ❌ Failed to add caller channel {call_id} to bridge {bridge_id}")
            return False
        
        log.info(f"[ARI-ORCHESTRATION] ✅ Caller channel {call_id} added to bridge {bridge_id}")

        # ========== STEP 4: Create ExternalMedia channel with RTP port ==========
        external_media_response = await create_external_media(
            call_id=call_id,
            formats="ulaw",
            rtp_ip="163.223.186.31",  # MY_PC_IP from config
            rtp_port=allocated_rtp_port
        )
        
        if not external_media_response:
            log.error(f"[ARI-ORCHESTRATION] ❌ Failed to create ExternalMedia channel for {call_id}")
            return False
        
        external_channel_id = external_media_response.get("id")
        log.info(f"[ARI-ORCHESTRATION] ✅ ExternalMedia channel created: {external_channel_id}")
        log.info(f"[ARI-ORCHESTRATION]    RTP endpoint: 163.223.186.31:{allocated_rtp_port}")

        # ========== STEP 5: Add ExternalMedia channel to bridge ==========
        added_external = await add_channel_to_bridge(bridge_id, external_channel_id)
        if not added_external:
            log.error(f"[ARI-ORCHESTRATION] ❌ Failed to add ExternalMedia {external_channel_id} to bridge {bridge_id}")
            return False
        
        log.info(f"[ARI-ORCHESTRATION] ✅ ExternalMedia channel {external_channel_id} added to bridge {bridge_id}")

        # ========== DIAGNOSTIC SUMMARY ==========
        log.info(f"[ARI-ORCHESTRATION] ✅✅✅ BRIDGE ORCHESTRATION COMPLETE FOR {call_id}")
        log.info(f"[ARI-ORCHESTRATION] Bridge ID: {bridge_id}")
        log.info(f"[ARI-ORCHESTRATION] Caller Channel: {call_id} → {bridge_id}")
        log.info(f"[ARI-ORCHESTRATION] ExternalMedia Channel: {external_channel_id} → {bridge_id}")
        log.info(f"[ARI-ORCHESTRATION] RTP Reception Point: 163.223.186.31:{allocated_rtp_port}")
        log.info(f"[ARI-ORCHESTRATION] Asterisk will now mix caller ↔ ExternalMedia bidirectionally")

        # Initialize customer requirement collection
        try:
            from ..services.customer_requirement_service import get_customer_requirement_service
            req_service = get_customer_requirement_service()
            if req_service:
                await req_service.initialize_call(call_id)
                log.info(f"[ARI] Requirement collection initialized: {call_id}")
        except Exception as e:
            log.warning(f"[ARI] Failed to initialize requirements: {e}")
        
        # ========== STEP 6: Start listening for audio (Gemini session initialization) ==========
        live_handler = get_live_call_handler()
        if live_handler:
            listen_success = await live_handler.start_listening(call_id)
            if not listen_success:
                log.warning(f"[ARI] Failed to start listening, but continuing call")
        
        # ========== STEP 7: Gemini session will start automatically in Step 6 ==========
        # Note: The greeting is already integrated into stream_audio_via_gemini()
        # via ClientConfig.get_greeting() call in media_service.py
        # No need for separate greeting service call - it's part of the pipeline
        
        log.info(f"[ARI] ✅✅✅ CALL ORCHESTRATION COMPLETE FOR {call_id}")
        log.info(f"[ARI]    ├─ Bridge: {bridge_id} (caller ↔ ExternalMedia)")
        log.info(f"[ARI]    ├─ RTP endpoint: 163.223.186.31:{allocated_rtp_port}")
        log.info(f"[ARI]    ├─ Gemini Live will initialize when start_listening() is called")
        log.info(f"[ARI]    ├─ Greeting will be sent as first message to Gemini")
        log.info(f"[ARI]    └─ Audio streaming: RTP ↔ Gemini ↔ RTP TX")

        return True

    except Exception as e:
        log.error(f"[ARI] StasisStart error: {e}", exc_info=True)
        return False


async def handle_stasis_end(event: Dict[str, Any]) -> bool:
    """
    Handle StasisEnd event - call ended
    
    Args:
        event: ARI StasisEnd event
        
    Returns:
        True if handled successfully
    """
    try:
        channel = event.get("channel", {})
        call_id = channel.get("id")

        if not call_id:
            log.error("[ARI] StasisEnd: missing call_id")
            return False

        log.info(f"[ARI] Call ended: {call_id}")

        # ========== LIFECYCLE LOG: Call End ==========
        try:
            from ..services.call_lifecycle_logger import get_call_lifecycle_logger
            lifecycle_logger = get_call_lifecycle_logger()
            if lifecycle_logger:
                stats = lifecycle_logger.log_call_end(call_id, reason="StasisEnd")
        except Exception as e:
            log.debug(f"[ARI] Error logging call end: {e}")

        # Stop listening
        live_handler = get_live_call_handler()
        if live_handler:
            await live_handler.stop_listening(call_id)

        # Save conversation and cleanup
        call_handler = get_call_handler()
        success = await call_handler.on_call_end(call_id)

        # Cleanup media
        media_service = get_media_service()
        if media_service:
            await media_service.release_call_resources(call_id)

        return success

    except Exception as e:
        log.error(f"[ARI] StasisEnd error: {e}")
        return False


async def handle_channel_dtmf_received(event: Dict[str, Any]) -> bool:
    """
    Handle DTMF digit received during call
    
    Args:
        event: ARI ChannelDtmfReceived event
        
    Returns:
        True if handled successfully
    """
    try:
        channel = event.get("channel", {})
        call_id = channel.get("id")
        digit = event.get("digit")

        if not call_id or not digit:
            log.error("[ARI] DTMF: missing call_id or digit")
            return False

        log.debug(f"[ARI] DTMF received: {call_id} - digit: {digit}")
        return True

    except Exception as e:
        log.error(f"[ARI] DTMF error: {e}")
        return False


async def route_ari_event(event_type: str, event: Dict[str, Any]) -> bool:
    """
    Route ARI events to appropriate handlers
    
    Args:
        event_type: Type of event (StasisStart, StasisEnd, etc.)
        event: Event data
        
    Returns:
        True if handled successfully
    """
    try:
        if event_type == "StasisStart":
            return await handle_stasis_start(event)
        
        elif event_type == "StasisEnd":
            return await handle_stasis_end(event)
        
        elif event_type == "ChannelDtmfReceived":
            return await handle_channel_dtmf_received(event)
        
        else:
            log.debug(f"[ARI] Unhandled event type: {event_type}")
            return False

    except Exception as e:
        log.error(f"[ARI] Event routing error: {e}")
        return False
