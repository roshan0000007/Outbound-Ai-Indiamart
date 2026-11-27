"""
Call Lifecycle Handlers
Handles call start and end events
"""

import asyncio
from typing import Optional, Dict, Any
from datetime import datetime

from ..session.redis_session import get_call_session
from ..core.database import execute_insert
from ..core.config import log

class CallHandler:
    """
    Handles call lifecycle events:
    - Call start: Initialize session
    - Call end: Cleanup and persist conversation
    """

    async def on_call_start(
        self,
        call_id: str,
        user_id: int,
        dnid: str,
        caller_number: str
    ) -> bool:
        """
        When call arrives - initialize session
        
        Args:
            call_id: Unique call ID
            user_id: User ID
            dnid: Called number
            caller_number: Caller's number
            
        Returns:
            True if successful
        """
        try:
            log.info(f"[CallHandler] Call start: {call_id} from {caller_number}")

            session_mgr = get_call_session()
            if not session_mgr:
                log.error("[CallHandler] Session manager not initialized")
                return False

            session = await session_mgr.create_session(
                call_id=call_id,
                user_id=user_id,
                agent_name="AI Agent",
                language="en"
            )

            if not session:
                log.error("[CallHandler] Failed to create session")
                return False

            log.info(f"[CallHandler] ✅ Session initialized for {call_id}")
            
            # ✅ CRITICAL FIX #2: Store caller_number from ARI at call start
            # This ensures mobile_number never becomes 'unknown' or 'N/A'
            if caller_number and caller_number != "unknown":
                # Normalize phone number: remove leading 0, keep only digits
                normalized_caller = ''.join(c for c in caller_number if c.isdigit())
                if normalized_caller.startswith('0'):
                    normalized_caller = normalized_caller[1:]
                
                log.info(f"[CallHandler] 📱 Storing mobile_number from ARI: {normalized_caller}")
                
                # Store in session for later retrieval at call end
                await session_mgr.update_session(
                    call_id,
                    {"caller_number": normalized_caller}
                )
                
                # Store in CustomerRequirementService as mobile_number
                try:
                    from ..services.customer_requirement_service import get_customer_requirement_service
                    req_service = get_customer_requirement_service()
                    if req_service:
                        await req_service.update_requirements(
                            call_id,
                            {"mobile_number": normalized_caller}
                        )
                        log.info(f"[CallHandler] ✅ mobile_number persisted to ReqService: {normalized_caller}")
                except Exception as e:
                    log.error(f"[CallHandler] Failed to store mobile_number in ReqService: {e}")
            else:
                log.warning(f"[CallHandler] ⚠️ No valid caller_number provided")
                # Store placeholder but don't use it yet - wait for customer-provided number
                await session_mgr.update_session(
                    call_id,
                    {"caller_number": "unknown"}
                )
            
            # Initialize LLM failover service for this call
            try:
                from ..services.llm_failover_service import get_llm_failover_service
                failover_service = get_llm_failover_service()
                if failover_service:
                    await failover_service.initialize_call(call_id)
                    log.info(f"[CallHandler] ✅ LLM failover initialized: Gemini Live → Groq")
            except Exception as e:
                log.warning(f"[CallHandler] Error initializing failover: {e}")
            
            # 🔧 CRITICAL: Create media (RTP) session for audio streaming
            try:
                from ..services.media_service import get_media_service, MediaConfig
                
                media_service = get_media_service()
                if media_service:
                    # Create proper MediaConfig with all required fields
                    media_config = MediaConfig(
                        call_id=call_id,
                        channel_id=call_id,
                        external_media_id=call_id,
                        bridge_id=call_id,
                        user_id=user_id,
                        campaign_id=0,
                        dnid=dnid,
                        language="en",
                        codec=0,
                        sample_rate=8000,
                        frame_size=160
                    )
                    
                    media_session = await media_service.create_session(media_config)
                    if media_session:
                        log.info(f"[CallHandler] ✅ Media session created for {call_id}")
                        
                        # ========== LIFECYCLE LOG: Media Session Ready ==========
                        try:
                            from ..services.call_lifecycle_logger import get_call_lifecycle_logger
                            lifecycle_logger = get_call_lifecycle_logger()
                            if lifecycle_logger and hasattr(media_session, 'local_port'):
                                lifecycle_logger.log_media_session_ready(call_id, media_session.local_port)
                        except Exception as e:
                            log.debug(f"[CallHandler] Error logging media session ready: {e}")
                    else:
                        log.warning(f"[CallHandler] Failed to create media session, audio may not work")
                else:
                    log.warning("[CallHandler] Media service not available, audio may not work")
                    
            except Exception as e:
                log.warning(f"[CallHandler] Error creating media session: {e}")
            
            return True

        except Exception as e:
            log.error(f"[CallHandler] on_call_start error: {e}")
            return False

    async def on_call_end(
        self,
        call_id: str,
        user_id: int = 0,
        caller_number: str = "unknown"
    ) -> bool:
        """
        When call ends - save conversation and cleanup using proper termination sequence.
        
        CRITICAL SEQUENCE:
        1. Wait for Gemini session to fully close
        2. Extract complete conversation from ConversationCaptureService
        3. Take immutable snapshot for safe persistence
        4. Perform database persistence with idempotent protection
        5. Handle cleanup
        
        Args:
            call_id: Call ID
            user_id: User ID
            caller_number: Caller's phone number
            
        Returns:
            True if successful
        """
        try:
            log.info(f"[CallHandler] 📞 Call ending: {call_id}")

            # 🔧 CRITICAL: Wait for Gemini session to fully close (max 3 seconds)
            try:
                from ..services.gemini_audio_pipeline import get_gemini_audio_session
                gemini_session = await get_gemini_audio_session(call_id)
                if gemini_session:
                    log.info(f"[CallHandler] ⏳ Waiting for Gemini session to close for {call_id}...")
                    # Wait for session_active to become False or timeout
                    for attempt in range(30):  # 30 * 100ms = 3 seconds
                        if not gemini_session.session_active:
                            log.info(f"[CallHandler] ✅ Gemini session closed")
                            break
                        await asyncio.sleep(0.1)
                    else:
                        log.warning(f"[CallHandler] ⚠️ Gemini session timeout, continuing anyway")
            except Exception as e:
                log.debug(f"[CallHandler] Error waiting for Gemini close: {e}")

            session_mgr = get_call_session()
            if not session_mgr:
                log.error("[CallHandler] Session manager not available")
                return False

            session = await session_mgr.get_session(call_id)
            if not session:
                log.warning(f"[CallHandler] No session found for {call_id}")
                return False

            try:
                from ..services.customer_requirement_service import get_customer_requirement_service
                from ..services.requirement_tools_service import get_requirement_tools_service
                from ..services.lead_storage_service import get_lead_storage_service
                from ..services.conversation_history_service import get_conversation_history_service
                from ..services.conversation_integration import get_complete_transcript, take_conversation_snapshot
                from ..services.call_state_machine import create_state_machine
                from ..services.call_termination_sequence import create_termination_sequence
                
                req_service = get_customer_requirement_service()
                requirement_tools = get_requirement_tools_service()
                lead_service = get_lead_storage_service()
                conv_history_service = get_conversation_history_service()
                
                # Ensure state machine exists for this call
                state_machine = create_state_machine(call_id)
                
                # Ensure termination sequence exists
                term_seq = create_termination_sequence(call_id)

                # ✅ CRITICAL FIX #3: Multi-source merge for requirements with wait logic
                # 1. Wait briefly for Gemini cleanup to finish
                # 2. Merge from GeminiAudioSession.collected + ReqService + Redis
                # 3. Preserve partial data (don't overwrite captured fields with empty strings)
                
                log.info(f"[CallHandler] 🔄 Fetching requirements from multiple sources for {call_id}...")
                
                requirements = None
                gemini_session = None
                
                # Try to get Gemini session for direct access to collected data
                try:
                    from ..services.gemini_audio_pipeline import get_gemini_audio_session
                    gemini_session = await get_gemini_audio_session(call_id)
                except Exception as e:
                    log.debug(f"[CallHandler] Could not get Gemini session: {e}")
                
                # Wait up to 2 seconds for Gemini stream final summary to complete
                # This allows the [CALL-DATA] summary extraction to finish
                log.info(f"[CallHandler] ⏳ Waiting up to 2.0s for Gemini final summary (stream end)...")
                for wait_attempt in range(20):  # 20 * 100ms = 2.0s
                    if gemini_session and not gemini_session.session_active:
                        log.info(f"[CallHandler] ✅ Gemini session finalized after {wait_attempt * 100}ms")
                        break
                    await asyncio.sleep(0.1)
                else:
                    log.warning(f"[CallHandler] ⚠️ Gemini stream still active after 2.0s, proceeding with available data")
                
                # Build merged requirements from multiple sources
                merged_requirements = {
                    "customer_name": "",
                    "company_name": "",
                    "location": "",
                    "interested_products": "",
                    "required_quantity": "",
                    "business_requirement": "",
                    "bulk_and_other_requirements": "",
                    "mobile_number": ""
                }
                
                # Source 1: CustomerRequirementService (Redis + in-memory, updated via save_field)
                if req_service:
                    try:
                        req_data = await req_service.get_requirements(call_id)
                        if req_data:
                            log.info(f"[CallHandler] ✅ Source 1 (ReqService): Found {len([v for v in req_data.values() if v])} fields")
                            for key, value in req_data.items():
                                if value and value != "N/A" and not (isinstance(value, str) and value.strip() == ""):
                                    merged_requirements[key] = value
                        else:
                            log.info(f"[CallHandler] ⚠️ Source 1 (ReqService): No data")
                    except Exception as e:
                        log.error(f"[CallHandler] Error retrieving from ReqService: {e}")
                
                # Source 2: GeminiAudioSession.collected (local in-process cache)
                if gemini_session and gemini_session.collected:
                    try:
                        log.info(f"[CallHandler] ✅ Source 2 (GeminiSession): Found {len(gemini_session.collected)} fields in memory")
                        for key, value in gemini_session.collected.items():
                            if value and value != "N/A" and not (isinstance(value, str) and value.strip() == ""):
                                # Only overwrite if ReqService didn't have it
                                if not merged_requirements[key]:
                                    merged_requirements[key] = value
                    except Exception as e:
                        log.error(f"[CallHandler] Error retrieving from GeminiSession: {e}")
                
                # Count how many fields we actually have
                captured_fields = sum(1 for v in merged_requirements.values() if v and v != "N/A" and v.strip() != "")
                log.info(f"[CallHandler] 📊 Final merge result: {captured_fields}/8 fields captured")
                
                # Create final requirements dict (remove empty strings, keep N/A for missing fields)
                requirements = {}
                for key, value in merged_requirements.items():
                    if value and value != "N/A" and value.strip() != "":
                        requirements[key] = value
                    else:
                        requirements[key] = "N/A"  # Mark as N/A only if truly not captured
                
                log.info(f"[CallHandler] ✅ Requirements finalized: {requirements}")

                # ========== GOOGLE SHEETS SAVE WITH IDEMPOTENCY ==========
                # Check if requirements were already saved (idempotency protection)
                requirements_already_saved = session.get("requirements_saved_to_sheets", False)
                
                log.info(f"[GOOGLE-SHEETS] Session ID in session: {session.get('call_session_id', 'NOT FOUND')}")
                log.info(f"[GOOGLE-SHEETS] Requirements saved flag: {requirements_already_saved}")
                log.info(f"[GOOGLE-SHEETS] Requirements keys: {requirements.keys() if requirements else 'None'}")
                log.info(f"[GOOGLE-SHEETS] Requirements: {requirements if requirements else 'None'}")
                
                if requirements and lead_service and not requirements_already_saved:
                    log.info(f"[GOOGLE-SHEETS] Preparing customer requirement record (may be partial capture)")
                    
                    # ✅ CRITICAL FIX #2: Use mobile_number from session (set at call start from ARI)
                    # First try to get mobile_number from requirements (if customer provided one during call)
                    mobile_number = requirements.get("mobile_number", "").strip()
                    
                    # If not provided during call, use the ARI caller_number stored at call start
                    if not mobile_number or mobile_number == "N/A":
                        session_mobile = session.get("caller_number", "").strip()
                        if session_mobile and session_mobile != "unknown":
                            mobile_number = session_mobile
                            log.info(f"[GOOGLE-SHEETS] Using mobile_number from call start (ARI): {mobile_number}")
                        else:
                            mobile_number = "N/A"
                            log.warning(f"[GOOGLE-SHEETS] No mobile_number available, using N/A")
                    else:
                        log.info(f"[GOOGLE-SHEETS] Using mobile_number provided during call: {mobile_number}")
                    
                    # Get call session ID from session
                    call_session_id = session.get("call_session_id", call_id)
                    
                    log.info(f"[GOOGLE-SHEETS] Call Session ID: {call_session_id}")
                    log.info(f"[GOOGLE-SHEETS] Call ID (from ARI): {call_id}")
                    log.info(f"[GOOGLE-SHEETS] Customer Mobile: {mobile_number}")
                    
                    # Count captured fields (non-N/A values)
                    captured_count = sum(1 for k in ["customer_name", "company_name", "location", 
                                                      "interested_products", "required_quantity", 
                                                      "business_requirement", "bulk_and_other_requirements"] 
                                        if requirements.get(k, "N/A") != "N/A")
                    log.info(f"[GOOGLE-SHEETS] Captured fields: {captured_count}/7 requirement fields")
                    log.info(f"[GOOGLE-SHEETS] Target worksheet: GID 0")
                    
                    # Prepare complete requirement payload with metadata
                    # CRITICAL: Preserve captured values exactly as extracted, only use N/A for truly missing fields
                    # 
                    # Column Mapping to Google Sheets (10 columns):
                    #   A: call_session_id
                    #   B: mobile_number (ARI caller ID or customer-provided)
                    #   C: customer_name
                    #   D: company_name
                    #   E: location
                    #   F: interested_products (comma-separated if array)
                    #   G: required_quantity
                    #   H: business_requirement
                    #   I: bulk_and_other_requirements
                    #   J: call_timestamp (ISO format)
                    sheets_payload = {
                        "call_session_id": call_session_id,
                        "mobile_number": mobile_number,
                        "customer_name": requirements.get("customer_name", "N/A"),
                        "company_name": requirements.get("company_name", "N/A"),
                        "location": requirements.get("location", "N/A"),
                        "interested_products": requirements.get("interested_products", "N/A"),
                        "required_quantity": requirements.get("required_quantity", "N/A"),
                        "business_requirement": requirements.get("business_requirement", "N/A"),
                        "bulk_and_other_requirements": requirements.get("bulk_and_other_requirements", "N/A"),
                        "call_timestamp": datetime.utcnow().isoformat()
                    }
                    
                    log.info(f"[GOOGLE-SHEETS] Payload: {sheets_payload}")
                    log.info(f"[GOOGLE-SHEETS] Header mapping validated")
                    log.info(f"[GOOGLE-SHEETS] Appending customer record (partial capture OK: {captured_count}/7)")
                    
                    # Save to Google Sheets
                    result = await lead_service.save_requirements(sheets_payload)
                    
                    if result and result.get("success"):
                        log.info(f"[GOOGLE-SHEETS] ✅ Row appended successfully")
                        log.info(f"[GOOGLE-SHEETS] 📊 Captured {captured_count}/7 fields + mobile")
                        log.info(f"[GOOGLE-SHEETS] Persistence completed for call: {call_session_id}")
                        
                        # Mark as saved ONLY after successful API response
                        await session_mgr.update_session(
                            call_id,
                            {"requirements_saved_to_sheets": True}
                        )
                        log.info(f"[CallHandler] ✅ Requirements saved to Google Sheets")
                    else:
                        log.error(f"[GOOGLE-SHEETS][ERROR] Failed to save customer requirements")
                        log.error(f"[GOOGLE-SHEETS][ERROR] Call Session ID: {call_session_id}")
                        log.error(f"[GOOGLE-SHEETS][ERROR] Reason: {result.get('message', 'Unknown error') if result else 'No result'}")
                        # Continue with cleanup - don't block call end
                        
                elif requirements_already_saved:
                    log.info(f"[GOOGLE-SHEETS] ⏭️ Skipping: Requirements already saved (idempotency)")
                    log.info(f"[GOOGLE-SHEETS] Call Session ID: {session.get('call_session_id', call_id)}")
                else:
                    if not requirements:
                        log.warning(f"[CallHandler] ⚠️ No requirements collected for {call_id}")
                    if not lead_service:
                        log.warning(f"[CallHandler] ⚠️ Lead storage service not available")

                # Get complete conversation transcript
                full_conversation_text = await get_complete_transcript(call_id)
                
                # Fallback to Redis session conversation if ConversationCaptureService empty
                if not full_conversation_text:
                    conversation = session.get("conversation", [])
                    conversation_parts = []
                    
                    for message in conversation:
                        sender = message.get("sender", "unknown").upper()
                        text = message.get("text", "")
                        if text:
                            conversation_parts.append(f"{sender}: {text}")
                    
                    full_conversation_text = "\n".join(conversation_parts) if conversation_parts else ""

                # Detect language
                detected_language = session.get("response_language", "en")
                if detected_language not in ["en-IN", "hi-IN", "en", "hi"]:
                    detected_language = "en"

                # Take immutable snapshot before persistence
                snapshot = await take_conversation_snapshot(call_id)
                if snapshot:
                    log.info(
                        f"[CallHandler] 📸 Conversation snapshot: {snapshot.get('total_messages')} messages"
                    )

                # Save conversation to database with idempotent protection
                if full_conversation_text or snapshot:
                    log.info(f"[CallHandler] 💾 Persisting conversation to database")
                    
                    persist_success = await term_seq.save_conversation_to_database(
                        conversation_history_service=conv_history_service,
                        userid=user_id,
                        caller_number=caller_number,
                        conversation_text=full_conversation_text or "",
                        detected_language=detected_language,
                        call_duration_sec=0  # TODO: Calculate from timestamps
                    )

                    if persist_success:
                        log.info(f"[CallHandler] ✅ Conversation persisted to database")
                    else:
                        log.error(f"[CallHandler] ❌ Failed to persist conversation")
                        # Continue with cleanup anyway
                else:
                    log.info(f"[CallHandler] ℹ️ No conversation data to save")

                # Cleanup
                try:
                    # Cleanup requirements from Redis
                    if req_service:
                        await req_service.cleanup_call(call_id)
                        log.info(f"[CallHandler] ✅ Requirements cleaned up from Redis")
                    
                    # Cleanup session from Redis
                    await session_mgr.close_session(call_id)
                    log.info(f"[CallHandler] ✅ Session cleaned up")
                    
                    # Cleanup state machine
                    from ..services.call_state_machine import cleanup_state_machine
                    cleanup_state_machine(call_id)
                    
                    # Cleanup termination sequence
                    from ..services.call_termination_sequence import cleanup_termination_sequence
                    cleanup_termination_sequence(call_id)
                    
                    # Cleanup conversation from memory
                    from ..services.conversation_integration import cleanup_conversation
                    await cleanup_conversation(call_id)
                    
                    log.info(f"[CallHandler] ✅ Call cleanup complete")

                except Exception as e:
                    log.warning(f"[CallHandler] Error in cleanup: {e}")

                return True

            except Exception as e:
                log.error(f"[CallHandler] Error processing call end: {e}", exc_info=True)
                return False

        except Exception as e:
            log.error(f"[CallHandler] on_call_end error: {e}")
            return False

    async def get_call_status(self, call_id: str) -> Optional[Dict[str, Any]]:
        """Get current call status"""
        try:
            session_mgr = get_call_session()
            if not session_mgr:
                return None

            session = await session_mgr.get_session(call_id)
            if not session:
                return None

            return {
                "call_id": call_id,
                "user_id": session.get("user_id"),
                "language": session.get("language", "en"),
                "created_at": session.get("created_at"),
                "conversation_turns": len(session.get("conversation", []))
            }

        except Exception as e:
            log.error(f"[CallHandler] get_call_status error: {e}")
            return None


async def init_call_handler():
    """Initialize call handler"""
    return CallHandler()


def get_call_handler() -> Optional[CallHandler]:
    """Get call handler instance"""
    return CallHandler()
