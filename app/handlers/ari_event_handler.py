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
        
        # ========== STEP 6: Play Language Selection Prompt via RTP ==========
        # 🔧 CRITICAL: Use RTP for language prompt, NOT Asterisk playback (which has 404 issues)
        log.info(f"[ARI] 📢 Playing language selection prompt via RTP for {call_id}")
        try:
            from ..services.greeting_service import get_greeting_service
            greeting_service = get_greeting_service()
            if greeting_service:
                prompt_success = await greeting_service.play_language_selection_prompt_via_rtp(call_id)
                if prompt_success:
                    log.info(f"[ARI] ✅ Language selection prompt sent via RTP")
                    # Give caller time to hear and respond
                    await asyncio.sleep(0.5)
                else:
                    log.warning(f"[ARI] ⚠️ Language prompt failed via RTP, continuing anyway")
            else:
                log.warning(f"[ARI] Greeting service not available")
        except Exception as e:
            log.warning(f"[ARI] Error playing language prompt: {e}")
        
        # ========== STEP 7: Start listening (Gemini will wait for DTMF) ==========
        # Gemini session initialization starts here
        # It will call wait_for_language() which blocks until DTMF digit received
        log.info(f"[ARI] ⏳ Starting audio listening (waiting for DTMF 1 or 2)...")
        
        live_handler = get_live_call_handler()
        if live_handler:
            listen_success = await live_handler.start_listening(call_id)
            if not listen_success:
                log.warning(f"[ARI] Failed to start listening, but continuing call")
        
        # ========== STEP 8: Gemini will start only after DTMF ==========
        # Note: GeminiAudioSession.wait_for_language() blocks here until language is set by DTMF handler
        # Audio input is gated (dropped) until language_selected = True
        
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
    
    Flow:
    - After language prompt is played, caller presses 1 (English) or 2 (Hindi)
    - Language is set, Gemini session unblocked
    - Language-specific greeting is then sent by Gemini Live
    
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

        log.info(f"[ARI] DTMF received: {call_id} - digit: {digit}")

        # Check if language has already been selected
        from ..core.redis import get_session as redis_get_session
        try:
            language_state = await redis_get_session(f"language_selection:{call_id}")
            if language_state:
                log.info(f"[DTMF] Language already selected for {call_id}: ignoring DTMF")
                return True
        except Exception as e:
            log.debug(f"[DTMF] Error checking language state: {e}")

        # Map DTMF digits to languages
        language_mapping = {
            "1": "en",    # English
            "2": "hi"     # Hindi
        }

        selected_language = language_mapping.get(digit)
        if not selected_language:
            log.warning(f"[DTMF] Invalid DTMF digit: {digit} (expected 1 or 2)")
            return False

        language_name = "English" if selected_language == "en" else "Hindi"
        log.info(f"[DTMF] 🎯 Language selected: {digit} → {selected_language} ({language_name}) for {call_id}")

        # Save language selection to state
        from ..core.redis import set_session as redis_set_session
        try:
            language_state = {
                "call_id": call_id,
                "language": selected_language,
                "digit_pressed": digit,
                "language_name": language_name,
                "selected_at": datetime.utcnow().isoformat()
            }
            await redis_set_session(
                f"language_selection:{call_id}",
                language_state,
                ttl=3600  # Keep for 1 hour
            )
            log.info(f"[DTMF] ✅ Language state saved: {language_name}")
        except Exception as e:
            log.error(f"[DTMF] Error saving language state: {e}")
            return False

        # Update call session language
        try:
            from ..session.redis_session import get_call_session
            session_mgr = get_call_session()
            if session_mgr:
                session = await session_mgr.get_session(call_id)
                if session:
                    session["language"] = selected_language
                    await session_mgr.update_session(call_id, session)
                    log.info(f"[DTMF] ✅ Call session language updated: {language_name}")
        except Exception as e:
            log.warning(f"[DTMF] Error updating session language: {e}")

        # 🔧 CRITICAL: Set language on Gemini audio session
        # This releases the wait_for_language() in process_audio_stream()
        try:
            from ..services.gemini_audio_pipeline import get_gemini_audio_session
            gemini_session = await get_gemini_audio_session(call_id)
            if gemini_session:
                gemini_session.set_call_language(selected_language)
                log.info(f"[DTMF] ✅ Gemini session language set: {language_name}")
                log.info(f"[DTMF] 📞 Gemini will now send {language_name} greeting and ask questions")
            else:
                log.warning(f"[DTMF] ⚠️ Gemini audio session not found, but continuing...")
        except Exception as e:
            log.warning(f"[DTMF] Error setting Gemini language: {e}", exc_info=True)

        # ========== LIFECYCLE LOG: Language Selected ==========
        try:
            from ..services.call_lifecycle_logger import get_call_lifecycle_logger
            lifecycle_logger = get_call_lifecycle_logger()
            if lifecycle_logger:
                lifecycle_logger.log_language_selected(call_id, selected_language, digit)
        except Exception as e:
            log.debug(f"[DTMF] Error logging language selection: {e}")

        log.info(f"[DTMF] ✅✅✅ LANGUAGE SELECTION COMPLETE")
        log.info(f"[DTMF]    ├─ Call ID: {call_id}")
        log.info(f"[DTMF]    ├─ Language: {language_name}")
        log.info(f"[DTMF]    ├─ DTMF Digit Pressed: {digit}")
        log.info(f"[DTMF]    ├─ Gemini session unblocked")
        log.info(f"[DTMF]    └─ Waiting for Gemini to send {language_name} greeting...")

        return True

    except Exception as e:
        log.error(f"[ARI] DTMF error: {e}", exc_info=True)
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
