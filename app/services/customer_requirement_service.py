"""
Customer Requirement Collection Service
Manages the seven-category requirement collection workflow
Handles state management, validation, and tool execution
"""

import json
from typing import Optional, Dict, Any, List
from datetime import datetime

from ..core.config import log
from ..core.redis import set_session, get_session, delete_session
from ..core.database import execute_insert, execute_query


class CustomerRequirementState:
    """In-memory state for a single call's customer requirement collection"""

    def __init__(self, call_id: str):
        self.call_id = call_id
        self.data = {
            "customer_name": None,
            "company_name": None,
            "location": None,
            "interested_products": [],
            "required_quantity": None,
            "business_requirement": None,
            "bulk_and_other_requirements": None
        }
        self.created_at = datetime.utcnow()
        self.last_updated = datetime.utcnow()

    def update(self, updates: Dict[str, Any]) -> None:
        """Update specific fields"""
        for key, value in updates.items():
            if key in self.data:
                if value is not None:
                    self.data[key] = value
                    self.last_updated = datetime.utcnow()

    def get_pending_fields(self) -> List[str]:
        """Get list of fields that still need values"""
        required_fields = [
            "customer_name",
            "company_name",
            "location",
            "interested_products",
            "required_quantity",
            "business_requirement",
            "bulk_and_other_requirements"
        ]
        
        pending = []
        for field in required_fields:
            value = self.data.get(field)
            # Check if field is empty or None
            if value is None or (isinstance(value, (str, list)) and not value):
                pending.append(field)
        
        return pending

    def is_complete(self) -> bool:
        """Check if all required fields have values"""
        return len(self.get_pending_fields()) == 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage"""
        return {
            "call_id": self.call_id,
            "data": self.data,
            "created_at": self.created_at.isoformat(),
            "last_updated": self.last_updated.isoformat(),
            "is_complete": self.is_complete()
        }


class CustomerRequirementService:
    """Service for managing customer requirement collection workflow"""

    def __init__(self):
        self.call_states: Dict[str, CustomerRequirementState] = {}
        self.redis_ttl = 3600

    async def initialize_call(self, call_id: str) -> CustomerRequirementState:
        """Initialize requirement collection for a new call"""
        try:
            state = CustomerRequirementState(call_id)
            self.call_states[call_id] = state
            
            # Also store in Redis for persistence
            await set_session(
                f"req:{call_id}",
                state.to_dict(),
                ttl=self.redis_ttl
            )
            
            log.info(f"[ReqService] Initialized requirement collection: {call_id}")
            return state
        except Exception as e:
            log.error(f"[ReqService] Failed to initialize call {call_id}: {e}")
            raise

    async def get_call_state(self, call_id: str) -> Optional[CustomerRequirementState]:
        """Get requirement state for a call"""
        try:
            # Try in-memory first
            if call_id in self.call_states:
                return self.call_states[call_id]
            
            # Fall back to Redis
            data = await get_session(f"req:{call_id}")
            if data:
                state = CustomerRequirementState(call_id)
                if isinstance(data, str):
                    data = json.loads(data)
                state.data = data.get("data", state.data)
                self.call_states[call_id] = state
                return state
            
            log.warning(f"[ReqService] No state found for {call_id}")
            return None
        except Exception as e:
            log.error(f"[ReqService] Error getting call state: {e}")
            return None

    async def update_requirements(
        self,
        call_id: str,
        updates: Dict[str, Any]
    ) -> bool:
        """Update customer requirements for a call"""
        try:
            state = await self.get_call_state(call_id)
            if not state:
                state = await self.initialize_call(call_id)
            
            state.update(updates)
            
            # Persist to Redis
            await set_session(
                f"req:{call_id}",
                state.to_dict(),
                ttl=self.redis_ttl
            )
            
            log.debug(f"[ReqService] Updated requirements for {call_id}: {list(updates.keys())}")
            return True
        except Exception as e:
            log.error(f"[ReqService] Error updating requirements: {e}")
            return False

    async def get_requirements(self, call_id: str) -> Optional[Dict[str, Any]]:
        """Get current requirements for a call, properly formatted for Google Sheets"""
        try:
            state = await self.get_call_state(call_id)
            if state:
                # Format requirements for external storage (Google Sheets)
                data = state.data.copy()
                
                # Convert products list to comma-separated string for sheets
                products = data.get("interested_products", [])
                if isinstance(products, list):
                    data["interested_products"] = ", ".join(str(p) for p in products) if products else ""
                
                # Ensure all values are strings or None
                for key in data:
                    if data[key] is None:
                        data[key] = ""
                    elif not isinstance(data[key], str):
                        data[key] = str(data[key])
                
                log.debug(f"[ReqService] Returning requirements for {call_id}: {data}")
                return data
            return None
        except Exception as e:
            log.error(f"[ReqService] Error getting requirements: {e}")
            return None

    async def cleanup_call(self, call_id: str) -> bool:
        """Clean up after call ends"""
        try:
            if call_id in self.call_states:
                del self.call_states[call_id]
            
            await delete_session(f"req:{call_id}")
            log.debug(f"[ReqService] Cleaned up requirements: {call_id}")
            return True
        except Exception as e:
            log.error(f"[ReqService] Error during cleanup: {e}")
            return False


_service: Optional[CustomerRequirementService] = None


async def init_customer_requirement_service():
    """Initialize customer requirement service"""
    global _service
    _service = CustomerRequirementService()
    log.info("[ReqService] Customer requirement service initialized")
    return _service


def get_customer_requirement_service() -> Optional[CustomerRequirementService]:
    """Get customer requirement service instance"""
    return _service
