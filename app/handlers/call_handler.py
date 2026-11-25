"""
Call Lifecycle Handlers
Handles call start and end events
"""

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
        call_id: str
    ) -> bool:
        """
        When call ends - save conversation and cleanup
        
        Args:
            call_id: Call ID
            
        Returns:
            True if successful
        """
        try:
            log.info(f"[CallHandler] Call end: {call_id}")

            session_mgr = get_call_session()
            if not session_mgr:
                log.error("[CallHandler] Session manager not available")
                return False

            session = await session_mgr.get_session(call_id)
            if not session:
                log.warning(f"[CallHandler] No session found for {call_id}")
                return False

            try:
                # Build complete conversation text from all messages
                conversation = session.get("conversation", [])
                conversation_parts = []
                detected_language = "en"
                
                for message in conversation:
                    sender = message.get("sender", "unknown").upper()
                    text = message.get("text", "")
                    if text:
                        conversation_parts.append(f"{sender}: {text}")
                    
                    # Track language from messages
                    msg_lang = message.get("language", "en")
                    if msg_lang and msg_lang != "en":
                        detected_language = msg_lang
                
                # Build full conversation text with one insert query
                full_conversation_text = "\n".join(conversation_parts) if conversation_parts else ""
                
                if full_conversation_text:
                    # Get call metadata from session
                    user_id = session.get("user_id", 0)
                    caller_number = session.get("caller_number", "Unknown")
                    call_start_time = session.get("created_at")
                    call_end_time = datetime.utcnow()
                    
                    # Calculate call duration
                    call_duration = 0
                    if call_start_time:
                        if isinstance(call_start_time, str):
                            from dateutil import parser as date_parser
                            call_start_time = date_parser.parse(call_start_time)
                        call_duration = int((call_end_time - call_start_time).total_seconds())
                    
                    # Save to conversation_history table in one query
                    insert_sql = """
                        INSERT INTO conversation_history
                        (call_id, userid, caller_number, conversation_text, detected_language,
                         call_duration, call_start_time, call_end_time)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                            conversation_text = %s,
                            detected_language = %s,
                            call_duration = %s,
                            call_end_time = %s
                    """
                    
                    params = (
                        call_id, user_id, caller_number, full_conversation_text, detected_language,
                        call_duration, call_start_time, call_end_time,
                        full_conversation_text, detected_language, call_duration, call_end_time
                    )
                    
                    await execute_insert(insert_sql, params)
                    log.info(f"[CallHandler] ✅ Saved complete conversation to conversation_history for {call_id}: {len(conversation)} messages")
                else:
                    log.warning(f"[CallHandler] No conversation text to save for {call_id}")
                    
            except Exception as e:
                log.warning(f"[CallHandler] Could not save conversation: {e}", exc_info=True)

            # Save requirements to Google Sheets on call hangup
            try:
                from ..services.customer_requirement_service import get_customer_requirement_service
                from ..services.lead_storage_service import get_lead_storage_service
                
                req_service = get_customer_requirement_service()
                lead_service = get_lead_storage_service()
                
                if req_service and lead_service:
                    requirements = await req_service.get_requirements(call_id)
                    if requirements:
                        # CRITICAL FIX: Only save to Google Sheets if conversation contains actual text
                        # Check if conversation has any meaningful content before marking success
                        has_valid_conversation = bool(full_conversation_text and full_conversation_text.strip())
                        
                        if has_valid_conversation:
                            # Save to Google Sheets only when there's actual conversation
                            result = await lead_service.save_requirements(requirements)
                            if result.get("success"):
                                log.info(f"[CallHandler] ✅ Saved requirements to Google Sheets: {call_id}")
                            else:
                                log.warning(f"[CallHandler] Failed to save requirements to Google Sheets: {result.get('message')}")
                        else:
                            log.info(f"[CallHandler] ⓘ No conversation text captured - skipping Google Sheets save for {call_id}")
                    else:
                        log.info(f"[CallHandler] ⓘ No requirements collected for {call_id}")
                    
                    # Cleanup requirement collection state
                    await req_service.cleanup_call(call_id)
                    log.info(f"[CallHandler] Requirement state cleaned up: {call_id}")
            except Exception as e:
                log.warning(f"[CallHandler] Failed to save/cleanup requirements: {e}", exc_info=True)

            # Close session
            await session_mgr.close_session(call_id)
            log.info(f"[CallHandler] ✅ Session closed for {call_id}")
            
            # Cleanup LLM failover service for this call
            try:
                from ..services.llm_failover_service import get_llm_failover_service
                failover_service = get_llm_failover_service()
                if failover_service:
                    stats = await failover_service.cleanup_call(call_id)
                    if stats:
                        log.info(f"[CallHandler] LLM failover stats: {stats}")
            except Exception as e:
                log.warning(f"[CallHandler] Error cleaning up failover service: {e}")
            
            return True

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
