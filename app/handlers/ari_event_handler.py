"""
ARI Event Handler
Processes Asterisk ARI WebSocket events
Routes events to appropriate call handlers
"""

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

        dnid = extract_dnid(channel)
        caller_number = extract_caller_number(channel)

        if not dnid or not caller_number:
            log.error(f"[ARI] StasisStart: missing dnid or caller_number")
            return False

        log.info(f"[ARI] ✅ Call started: {call_id} from {caller_number} to {dnid}")

        # Initialize call session
        call_handler = get_call_handler()
        success = await call_handler.on_call_start(
            call_id=call_id,
            user_id=1,  # Default user
            dnid=dnid,
            caller_number=caller_number
        )

        if success:
            # Initialize customer requirement collection
            try:
                from ..services.customer_requirement_service import get_customer_requirement_service
                req_service = get_customer_requirement_service()
                if req_service:
                    await req_service.initialize_call(call_id)
                    log.info(f"[ARI] Requirement collection initialized: {call_id}")
            except Exception as e:
                log.warning(f"[ARI] Failed to initialize requirements: {e}")
            
            # Trigger greeting
            try:
                from ..services.greeting_service import get_greeting_service
                greeting_service = get_greeting_service()
                if greeting_service:
                    await greeting_service.play_greeting(call_id)
                    log.info(f"[ARI] ✅ Greeting triggered: {call_id}")
            except Exception as e:
                log.warning(f"[ARI] Failed to trigger greeting: {e}")
            
            # Start listening for audio
            live_handler = get_live_call_handler()
            if live_handler:
                await live_handler.start_listening(call_id)

        return success

    except Exception as e:
        log.error(f"[ARI] StasisStart error: {e}")
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
