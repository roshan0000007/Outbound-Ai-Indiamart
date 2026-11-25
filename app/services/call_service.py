"""
Call Service
Manages call lifecycle and operations
"""

import time
from typing import Optional, Dict, Any
from datetime import datetime

from ..core.config import log
from ..core.database import get_db_pool

class CallService:
    """Service for call management"""

    def __init__(self):
        self.db_pool = get_db_pool()
        self.active_calls: Dict[str, Dict[str, Any]] = {}

    async def create_call(self, cid: str, caller_number: str, user_id: int,
                         dnid: Optional[str] = None, campaign_id: Optional[int] = None) -> bool:
        """Create a new call record"""
        try:
            if cid in self.active_calls:
                log.warning(f"[{cid}] Call already exists")
                return False

            self.active_calls[cid] = {
                "call_id": cid,
                "caller_number": caller_number,
                "user_id": user_id,
                "dnid": dnid,
                "campaign_id": campaign_id,
                "call_started_at": datetime.utcnow(),
                "greeting_played": False,
                "status": "active",
            }

            log.info(f"[{cid}] Call created: {caller_number}")
            return True
        except Exception as e:
            log.error(f"[{cid}] Call creation error: {e}")
            return False

    async def end_call(self, cid: str, reason: str = "normal") -> bool:
        """End a call"""
        try:
            if cid not in self.active_calls:
                log.warning(f"[{cid}] Call not found")
                return False

            call_data = self.active_calls.pop(cid)
            call_data["call_ended_at"] = datetime.utcnow()
            call_data["call_duration"] = int(
                (call_data["call_ended_at"] - call_data["call_started_at"]).total_seconds()
            )
            call_data["end_reason"] = reason

            log.info(f"[{cid}] Call ended: duration={call_data['call_duration']}s reason={reason}")
            return True
        except Exception as e:
            log.error(f"[{cid}] Call end error: {e}")
            return False

    async def get_call(self, cid: str) -> Optional[Dict]:
        """Get call details"""
        return self.active_calls.get(cid)

    async def get_active_calls_count(self) -> int:
        """Get count of active calls"""
        return len(self.active_calls)

    async def mark_greeting_played(self, cid: str) -> bool:
        """Mark greeting as played"""
        try:
            if cid in self.active_calls:
                self.active_calls[cid]["greeting_played"] = True
                log.info(f"[{cid}] Greeting marked as played")
                return True
            return False
        except Exception as e:
            log.error(f"[{cid}] Mark greeting error: {e}")
            return False

_call_service: Optional[CallService] = None

async def init_call_service():
    """Initialize call service"""
    global _call_service
    _call_service = CallService()
    log.info("[CallService] Initialized")
    return _call_service

def get_call_service() -> Optional[CallService]:
    """Get call service instance"""
    return _call_service
