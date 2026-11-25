"""
Conversation History Service
Handles database operations for conversation_history table
Stores call conversations with minimal schema
"""

import json
from typing import Optional, Dict, Any, List
from datetime import datetime
import mysql.connector

from ..core.config import log

def get_sync_db():
    """Get a synchronous MySQL connection with UTF-8 encoding"""
    try:
        from ..core.config import DB_HOST, DB_PORT, DB_USER, DB_PASS, DB_NAME
        conn = mysql.connector.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASS,
            database=DB_NAME,
            charset='utf8mb4',
            collation='utf8mb4_unicode_ci',
            autocommit=True,
            use_unicode=True
        )
        conn.set_charset_collation('utf8mb4', 'utf8mb4_unicode_ci')
        return conn
    except Exception as e:
        log.error(f"[ConvHistoryService] Failed to get sync DB connection: {e}")
        return None

class ConversationHistoryService:
    """Service for conversation_history table operations"""

    @staticmethod
    def save_conversation(
        call_id: str,
        userid: int,
        caller_number: str,
        conversation_text: str,
        detected_language: str = "en",
        call_duration: int = 0,
        call_arrived_time: Optional[datetime] = None,
        call_start_time: Optional[datetime] = None,
        call_end_time: Optional[datetime] = None
    ) -> bool:
        """
        Save conversation data to conversation_history table
        
        Args:
            call_id: Asterisk call identifier
            userid: User ID
            caller_number: Caller phone number
            conversation_text: Full conversation transcript
            detected_language: Language code (en, hi, etc.)
            call_duration: Duration in seconds
            call_arrived_time: When call arrived
            call_start_time: When conversation started
            call_end_time: When call ended
        
        Returns:
            True if saved successfully, False otherwise
        """
        try:
            if not call_id:
                log.error("[ConvHistoryService] call_id is required")
                return False
            if userid is None:
                log.error("[ConvHistoryService] userid is required")
                return False
            if not caller_number:
                log.error("[ConvHistoryService] caller_number is required")
                return False
            if not conversation_text:
                log.error("[ConvHistoryService] conversation_text is required")
                return False

            if call_arrived_time is None:
                call_arrived_time = datetime.utcnow()

            log.info(f"[ConvHistoryService] Saving conversation:")
            log.info(f"[ConvHistoryService]   ├─ Call ID: {call_id}")
            log.info(f"[ConvHistoryService]   ├─ User ID: {userid}")
            log.info(f"[ConvHistoryService]   ├─ Caller: {caller_number}")
            log.info(f"[ConvHistoryService]   ├─ Duration: {call_duration}s")
            log.info(f"[ConvHistoryService]   ├─ Language: {detected_language}")
            log.info(f"[ConvHistoryService]   └─ Conversation size: {len(conversation_text)} chars")

            db = get_sync_db()
            if not db:
                log.error("[ConvHistoryService] Database connection failed")
                return False

            query = """
            INSERT INTO conversation_history (
                call_id, userid, caller_number, conversation_text, detected_language,
                call_duration, call_arrived_time, call_start_time, call_end_time
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s
            )
            ON DUPLICATE KEY UPDATE
                conversation_text = %s,
                detected_language = %s,
                call_duration = %s
            """

            params = (
                call_id, userid, caller_number, conversation_text, detected_language,
                call_duration, call_arrived_time, call_start_time, call_end_time,
                conversation_text, detected_language, call_duration
            )

            cursor = db.cursor()
            cursor.execute(query, params)
            db.commit()
            cursor.close()

            log.info(f"[ConvHistoryService] ✅ Conversation saved successfully for call_id={call_id}")
            return True

        except Exception as e:
            log.error(f"[ConvHistoryService] Save failed: {e}", exc_info=True)
            return False

    @staticmethod
    def get_by_call_id(call_id: str) -> Optional[Dict[str, Any]]:
        """Get conversation by call ID"""
        try:
            db = get_sync_db()
            if not db:
                return None

            query = "SELECT * FROM conversation_history WHERE call_id = %s LIMIT 1"
            cursor = db.cursor(dictionary=True)
            cursor.execute(query, (call_id,))
            result = cursor.fetchone()
            cursor.close()

            return result

        except Exception as e:
            log.error(f"[ConvHistoryService] Get by call_id failed: {e}")
            return None

    @staticmethod
    def get_conversations_by_userid(userid: int, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent conversations by user ID"""
        try:
            db = get_sync_db()
            if not db:
                return []

            query = """
            SELECT * FROM conversation_history 
            WHERE userid = %s
            ORDER BY created_at DESC LIMIT %s
            """
            cursor = db.cursor(dictionary=True)
            cursor.execute(query, (userid, limit))
            results = cursor.fetchall()
            cursor.close()

            return results if results else []

        except Exception as e:
            log.error(f"[ConvHistoryService] Get conversations failed: {e}")
            return []


def get_conversation_history_service() -> ConversationHistoryService:
    """Factory function to get ConversationHistoryService instance"""
    return ConversationHistoryService()
