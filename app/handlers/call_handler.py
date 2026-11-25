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
        call_id: str
    ) -> bool:
        """
        When call ends - save conversation and cleanup
        
        CRITICAL FIX: Wait for Gemini stream to fully close before extracting data
        This prevents race condition where requirements are still being written to Redis
        
        Args:
            call_id: Call ID
            
        Returns:
            True if successful
        """
        try:
            log.info(f"[CallHandler] Call end: {call_id}")

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
                # 🔧 FIX: Get requirements from BOTH Gemini session AND RequirementService
                from ..services.customer_requirement_service import get_customer_requirement_service
                from ..services.requirement_tools_service import get_requirement_tools_service
                from ..services.lead_storage_service import get_lead_storage_service
                
                req_service = get_customer_requirement_service()
                requirement_tools = get_requirement_tools_service()
                lead_service = get_lead_storage_service()
                
                # Get collected requirements
                requirements = None
                if req_service:
                    requirements = await req_service.get_requirements(call_id)
                    log.info(f"[CallHandler] ✅ Requirements fetched: {requirements}")
                
                # Build complete conversation text from all messages
                conversation = session.get("conversation", [])
                conversation_parts = []
                detected_language = "en"
                
                for message in conversation:
                    sender = message.get("sender", "unknown").upper()
                    text = message.get("text", "")
                    if text:
                        conversation_parts.append(f"{sender}: {text}")
                        
                        # Detect language from first non-empty message
                        from ..services.language_service import get_language_service
                        lang_service = get_language_service()
                        if lang_service and detected_language == "en":
                            detected_language = lang_service.detect_language(text)
                
                full_conversation_text = "\n".join(conversation_parts)
                
                # 🔧 FIX: Save requirements even if conversation is empty
                # (Gemini might have collected data but not logged it in conversation table)
                if requirements:
                    log.info(f"[CallHandler] 💾 Saving requirements to Google Sheets for {call_id}")
                    result = await lead_service.save_requirements(requirements)
                    if result:
                        log.info(f"[CallHandler] ✅ Requirements saved to Google Sheets")
                    else:
                        log.warning(f"[CallHandler] ⚠️ Failed to save requirements")
                else:
                    log.warning(f"[CallHandler] ⚠️ No requirements found for {call_id}")
                
                # Save conversation if exists
                if full_conversation_text and full_conversation_text.strip():
                    try:
                        query = """
                            INSERT INTO conversation_history 
                            (call_id, participant_type, message_text, language, created_at)
                            VALUES (%s, %s, %s, %s, %s)
                        """
                        await execute_insert(query, [
                            call_id,
                            "CONVERSATION",
                            full_conversation_text[:5000],  # Limit length
                            detected_language,
                            datetime.utcnow()
                        ])
                        log.info(f"[CallHandler] ✅ Conversation saved to database")
                    except Exception as e:
                        log.warning(f"[CallHandler] Error saving conversation: {e}")
                else:
                    log.info(f"[CallHandler] ℹ️ No conversation text, skipping conversation save")
                
                # Cleanup requirements from Redis
                if req_service:
                    await req_service.cleanup_call(call_id)
                    log.info(f"[CallHandler] ✅ Requirements cleaned up from Redis")
                
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
