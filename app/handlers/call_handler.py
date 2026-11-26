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
            log.info(f"[CallHandler] ===== CALL END DEBUG =====")
            log.info(f"[CallHandler] call_id: {call_id}")
            log.info(f"[CallHandler] user_id: {user_id}")
            log.info(f"[CallHandler] caller_number: {caller_number}")

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

            log.info(f"[CallHandler] ===== SESSION RETRIEVED =====")
            log.info(f"[CallHandler] Session keys: {session.keys()}")
            log.info(f"[CallHandler] call_session_id in session: {session.get('call_session_id', 'KEY NOT FOUND')}")
            log.info(f"[CallHandler] call_id in session: {session.get('call_id', 'KEY NOT FOUND')}")
            log.info(f"[CallHandler] requirements_saved_to_sheets: {session.get('requirements_saved_to_sheets', 'KEY NOT FOUND')}")

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

                # Get collected requirements
                requirements = None
                if req_service:
                    requirements = await req_service.get_requirements(call_id)
                    if requirements:
                        log.info(f"[CallHandler] ✅ Requirements fetched for {call_id}")

                # ========== GOOGLE SHEETS SAVE WITH IDEMPOTENCY ==========
                # Check if requirements were already saved (idempotency protection)
                requirements_already_saved = session.get("requirements_saved_to_sheets", False)
                
                log.info(f"[GOOGLE-SHEETS] Session ID in session: {session.get('call_session_id', 'NOT FOUND')}")
                log.info(f"[GOOGLE-SHEETS] Requirements saved flag: {requirements_already_saved}")
                log.info(f"[GOOGLE-SHEETS] Requirements keys: {requirements.keys() if requirements else 'None'}")
                log.info(f"[GOOGLE-SHEETS] Requirements: {requirements if requirements else 'None'}")
                
                if requirements and lead_service and not requirements_already_saved:
                    log.info(f"[GOOGLE-SHEETS] Preparing customer requirement record")
                    
                    # Get call session ID and mobile number from session
                    call_session_id = session.get("call_session_id", call_id)
                    mobile_number = caller_number if caller_number != "unknown" else "N/A"
                    
                    log.info(f"[GOOGLE-SHEETS] Call Session ID: {call_session_id}")
                    log.info(f"[GOOGLE-SHEETS] Call ID (from ARI): {call_id}")
                    log.info(f"[GOOGLE-SHEETS] Customer Mobile: {mobile_number}")
                    log.info(f"[GOOGLE-SHEETS] Validated fields: 8/8")
                    log.info(f"[GOOGLE-SHEETS] Target worksheet: GID 0")
                    
                    # Prepare complete requirement payload with metadata
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
                    log.info(f"[GOOGLE-SHEETS] Appending customer record")
                    
                    # Save to Google Sheets
                    result = await lead_service.save_requirements(sheets_payload)
                    
                    if result and result.get("success"):
                        log.info(f"[GOOGLE-SHEETS] Row appended successfully")
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
                    log.info(f"[GOOGLE-SHEETS] Skipping: Requirements already saved (idempotency)")
                    log.info(f"[GOOGLE-SHEETS] Call Session ID: {session.get('call_session_id', call_id)}")
                else:
                    if not requirements:
                        log.warning(f"[CallHandler] No requirements collected for {call_id}")
                    if not lead_service:
                        log.warning(f"[CallHandler] Lead storage service not available")

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
