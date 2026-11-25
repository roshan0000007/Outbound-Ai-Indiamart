"""
Conversation Service
Manages multi-turn conversations and conversation history retrieval
"""

from typing import Optional, List, Dict, Any

from ..core.config import log
from ..core.database import execute_query, execute_insert

class ConversationService:
    """Service for managing call conversations and history"""

    def __init__(self):
        self.history_fetch_limit = 10

    async def get_conversation_history(
        self,
        call_id: str,
        limit: int = 10
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Retrieve conversation history for a call
        
        Args:
            call_id: Call ID to fetch history for
            limit: Number of previous messages to retrieve
            
        Returns:
            List of previous messages in conversation
        """
        try:
            query = """
                SELECT id, call_id, sender, message_text, detected_language, created_at
                FROM conversation_messages
                WHERE call_id = %s
                ORDER BY created_at ASC
                LIMIT %s
            """

            results = await execute_query(query, (call_id, limit))

            if not results:
                return []

            messages = []
            for row in results:
                sender = row[2]
                message_text = row[3]
                role = "user" if sender == "customer" else "assistant"

                messages.append({
                    "role": role,
                    "content": message_text
                })

            log.debug(f"[ConvService] Retrieved {len(messages)} messages for call_id={call_id}")
            return messages

        except Exception as e:
            log.error(f"[ConvService] History fetch error: {e}")
            return []

    async def save_message(
        self,
        call_id: str,
        user_id: Optional[int],
        customer_number: Optional[str],
        sender: str,
        message_text: str,
        language: Optional[str] = "en"
    ) -> bool:
        """
        Save a conversation message to MySQL
        
        Args:
            call_id: Call ID
            user_id: User ID
            customer_number: Customer phone number
            sender: 'customer' or 'ai'
            message_text: Message text
            language: Detected language
            
        Returns:
            True if successful
        """
        try:
            query = """
                INSERT INTO conversation_messages
                (call_id, sender, message_text, detected_language)
                VALUES (%s, %s, %s, %s)
            """

            params = (call_id, sender, message_text, language)
            
            await execute_insert(query, params)
            log.debug(f"[ConvService] Message saved for {call_id}: sender={sender} lang={language}")
            return True

        except Exception as e:
            log.error(f"[ConvService] Save message error: {e}")
            return False


_conversation_service: Optional[ConversationService] = None

async def init_conversation_service():
    """Initialize conversation service"""
    global _conversation_service
    _conversation_service = ConversationService()
    log.info("[ConversationService] Initialized")
    return _conversation_service

def get_conversation_service() -> Optional[ConversationService]:
    """Get conversation service instance"""
    return _conversation_service
