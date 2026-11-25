"""
Conversation Persistence Service
Handles conversation history persistence with minimal fields
"""

import asyncio
import json
from typing import Optional, Dict, Any, List
from datetime import datetime
from collections import deque

from ..core.config import log
from ..core.database import execute_insert
from ..core.redis import get_session

class ConversationPersistenceService:
    """
    Simple conversation persistence:
    1. Queue messages for async save
    2. Batch write to database
    3. UTF-8 multilingual support
    4. Graceful failure handling
    """

    def __init__(self):
        self.pending_saves: Dict[str, deque] = {}
        self.save_tasks: Dict[str, asyncio.Task] = {}
        self.batch_size = 10
        self.flush_interval_sec = 5

    async def queue_message(
        self,
        call_id: str,
        message: Dict[str, Any]
    ) -> bool:
        """
        Queue a message for persistence (non-blocking).
        
        Message structure:
        {
            "role": "user" or "assistant",
            "text": "Message text",
            "timestamp": ISO datetime,
            "language": "en", "hi", etc.
        }
        
        Returns:
            True if queued, False on error
        """
        try:
            if call_id not in self.pending_saves:
                self.pending_saves[call_id] = deque(maxlen=1000)

            self.pending_saves[call_id].append(message)

            log.debug(f"[ConvPersist] Queued message for {call_id}: "
                     f"role={message.get('role')} lang={message.get('language')}")

            if len(self.pending_saves[call_id]) >= self.batch_size:
                await self._flush_batch(call_id)

            return True

        except Exception as e:
            log.error(f"[ConvPersist] Queue message error: {e}")
            return False

    async def _flush_batch(self, call_id: str) -> bool:
        """
        Flush a batch of queued messages to database.
        Non-blocking - returns immediately, save happens in background.
        """
        try:
            if call_id not in self.pending_saves or len(self.pending_saves[call_id]) == 0:
                return True

            session = await get_session(f"call:{call_id}")
            if not session:
                log.warning(f"[ConvPersist] Session not found for {call_id}")
                self.pending_saves[call_id].clear()
                return False

            messages_to_save = []
            while len(self.pending_saves[call_id]) > 0:
                messages_to_save.append(self.pending_saves[call_id].popleft())

            save_task = asyncio.create_task(
                self._persist_messages_to_db(call_id, session, messages_to_save)
            )

            self.save_tasks[call_id] = save_task
            log.info(f"[ConvPersist] Background save started for {call_id}: {len(messages_to_save)} messages")

            return True

        except Exception as e:
            log.error(f"[ConvPersist] Flush batch error: {e}")
            return False

    async def _persist_messages_to_db(
        self,
        call_id: str,
        session: Dict[str, Any],
        messages: List[Dict[str, Any]]
    ) -> bool:
        """
        Persist messages to MySQL database.
        This runs in background and does NOT block the call.
        """
        try:
            saved_count = 0

            for message in messages:
                try:
                    query = """
                        INSERT INTO conversation_messages
                        (call_id, sender, message_text, language, created_at)
                        VALUES (%s, %s, %s, %s, %s)
                    """

                    sender = "customer" if message.get("role") == "user" else "ai"

                    params = (
                        call_id,
                        sender,
                        message.get("text", ""),
                        message.get("language", "en"),
                        message.get("timestamp") or datetime.utcnow()
                    )

                    await execute_insert(query, params)
                    saved_count += 1

                    log.debug(f"[ConvPersist] Saved message for {call_id}: "
                             f"sender={sender} lang={message.get('language')}")

                except Exception as e:
                    log.error(f"[ConvPersist] Failed to save individual message: {e}")

            log.info(f"[ConvPersist] ✅ Persisted {saved_count}/{len(messages)} messages for {call_id}")
            return saved_count > 0

        except Exception as e:
            log.error(f"[ConvPersist] Database persistence error: {e}")
            return False

    async def flush_call(self, call_id: str) -> bool:
        """
        Flush all pending messages for a call immediately.
        Called when call ends to ensure no messages are lost.
        
        This BLOCKS until all messages are saved.
        """
        try:
            log.info(f"[ConvPersist] Final flush for call {call_id}")

            if call_id in self.pending_saves and len(self.pending_saves[call_id]) > 0:
                await self._flush_batch(call_id)

            if call_id in self.save_tasks:
                task = self.save_tasks[call_id]
                if not task.done():
                    log.info(f"[ConvPersist] Waiting for in-flight save task to complete...")
                    await asyncio.wait_for(task, timeout=10.0)
                    log.info(f"[ConvPersist] ✅ Save task completed")

            log.info(f"[ConvPersist] ✅ Final flush complete for {call_id}")

            self.pending_saves.pop(call_id, None)
            self.save_tasks.pop(call_id, None)

            return True

        except asyncio.TimeoutError:
            log.error(f"[ConvPersist] ❌ Timeout: Final flush did not complete in 10s for {call_id}")
            return False

        except Exception as e:
            log.error(f"[ConvPersist] Final flush error: {e}")
            return False

    async def get_pending_count(self, call_id: str) -> int:
        """Get count of pending unsaved messages for a call"""
        if call_id in self.pending_saves:
            return len(self.pending_saves[call_id])
        return 0


_persistence_service: Optional[ConversationPersistenceService] = None

async def init_conversation_persistence_service():
    """Initialize persistence service"""
    global _persistence_service
    _persistence_service = ConversationPersistenceService()
    log.info("[ConvPersist] Service initialized - async persistence active")
    return _persistence_service

def get_conversation_persistence_service() -> Optional[ConversationPersistenceService]:
    """Get persistence service instance"""
    return _persistence_service
