"""
Requirement Tools Service
Implements the four backend tools for requirement collection workflow
1. update_customer_requirements
2. validate_customer_requirements
3. save_customer_requirements
4. complete_customer_conversation
"""

import json
from typing import Optional, Dict, Any
from datetime import datetime

from ..core.config import log
from .customer_requirement_service import get_customer_requirement_service
from .call_service import get_call_service
from .media_service import get_media_service


class RequirementToolsService:
    """Service for executing customer requirement tools"""

    def __init__(self):
        self.req_service = get_customer_requirement_service()

    async def update_customer_requirements(
        self,
        call_id: str,
        updates: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        TOOL 1: Update customer requirements
        
        Purpose: Extract and update specific requirement categories
        
        Args:
            call_id: Unique call identifier
            updates: Dictionary with fields to update
                - customer_name
                - company_name
                - location
                - interested_products (array)
                - required_quantity
                - business_requirement
                - bulk_and_other_requirements
        
        Returns:
            {
                "success": bool,
                "message": str,
                "updated_fields": [list of updated fields],
                "current_state": {all 7 fields}
            }
        """
        try:
            log.info(f"[Tools] update_customer_requirements called for {call_id}")
            
            if not self.req_service:
                log.error("[Tools] Requirement service not initialized")
                return {
                    "success": False,
                    "message": "Service not available",
                    "updated_fields": [],
                    "current_state": {}
                }
            
            # Ensure only valid fields are updated
            valid_fields = {
                "customer_name", "company_name", "location",
                "interested_products", "required_quantity",
                "business_requirement", "bulk_and_other_requirements"
            }
            
            filtered_updates = {k: v for k, v in updates.items() if k in valid_fields}
            
            if not filtered_updates:
                log.warning(f"[Tools] No valid fields to update for {call_id}")
                return {
                    "success": False,
                    "message": "No valid fields provided",
                    "updated_fields": [],
                    "current_state": {}
                }
            
            # Update requirements
            success = await self.req_service.update_requirements(call_id, filtered_updates)
            
            if not success:
                log.error(f"[Tools] Failed to update requirements for {call_id}")
                return {
                    "success": False,
                    "message": "Failed to update requirements",
                    "updated_fields": [],
                    "current_state": {}
                }
            
            # Get current state
            current_state = await self.req_service.get_requirements(call_id)
            
            log.info(f"[Tools] ✅ Updated fields: {list(filtered_updates.keys())}")
            
            return {
                "success": True,
                "message": "Requirements updated successfully",
                "updated_fields": list(filtered_updates.keys()),
                "current_state": current_state
            }
        except Exception as e:
            log.error(f"[Tools] Error in update_customer_requirements: {e}")
            return {
                "success": False,
                "message": str(e),
                "updated_fields": [],
                "current_state": {}
            }

    async def validate_customer_requirements(
        self,
        call_id: str
    ) -> Dict[str, Any]:
        """
        TOOL 2: Validate customer requirements
        
        Purpose: Check if all required fields are complete and valid
        
        Args:
            call_id: Unique call identifier
        
        Returns:
            {
                "is_complete": bool,
                "completed_fields": [list],
                "pending_fields": [list],
                "unclear_fields": [list],
                "validation_errors": [list]
            }
        """
        try:
            log.info(f"[Tools] validate_customer_requirements called for {call_id}")
            
            if not self.req_service:
                log.error("[Tools] Requirement service not initialized")
                return {
                    "is_complete": False,
                    "completed_fields": [],
                    "pending_fields": [],
                    "unclear_fields": [],
                    "validation_errors": ["Service not available"]
                }
            
            # Validate requirements
            validation_result = await self.req_service.validate_requirements(call_id)
            
            log.info(f"[Tools] Validation result: is_complete={validation_result['is_complete']}")
            if validation_result['pending_fields']:
                log.debug(f"[Tools] Pending fields: {validation_result['pending_fields']}")
            if validation_result['unclear_fields']:
                log.debug(f"[Tools] Unclear fields: {validation_result['unclear_fields']}")
            
            return validation_result
        except Exception as e:
            log.error(f"[Tools] Error in validate_customer_requirements: {e}")
            return {
                "is_complete": False,
                "completed_fields": [],
                "pending_fields": [],
                "unclear_fields": [],
                "validation_errors": [str(e)]
            }

    async def save_customer_requirements(
        self,
        call_id: str
    ) -> Dict[str, Any]:
        """
        TOOL 3: Save customer requirements
        
        Purpose: Persist validated requirements to storage
        
        Args:
            call_id: Unique call identifier
        
        Returns:
            {
                "success": bool,
                "message": str,
                "storage": str (google_sheets or excel),
                "row_number": int (if applicable),
                "timestamp": str
            }
        """
        try:
            log.info(f"[Tools] save_customer_requirements called for {call_id}")
            
            if not self.req_service:
                log.error("[Tools] Requirement service not initialized")
                return {
                    "success": False,
                    "message": "Service not available",
                    "storage": None,
                    "row_number": None,
                    "timestamp": None
                }
            
            # First validate
            validation = await self.req_service.validate_requirements(call_id)
            if not validation['is_complete']:
                log.warning(f"[Tools] Cannot save incomplete requirements: {call_id}")
                return {
                    "success": False,
                    "message": f"Incomplete requirements. Missing: {validation['pending_fields']}",
                    "storage": None,
                    "row_number": None,
                    "timestamp": None
                }
            
            # Save to database (MySQL)
            success = await self.req_service.save_to_database(call_id)
            
            if not success:
                log.error(f"[Tools] Failed to save to database: {call_id}")
                return {
                    "success": False,
                    "message": "Failed to save to database",
                    "storage": None,
                    "row_number": None,
                    "timestamp": None
                }
            
            # Note: Google Sheets integration would happen here
            # For now, we're saving to MySQL
            
            log.info(f"[Tools] ✅ Successfully saved requirements: {call_id}")
            
            return {
                "success": True,
                "message": "Requirements saved successfully",
                "storage": "mysql",
                "row_number": None,  # MySQL doesn't use row numbers
                "timestamp": datetime.utcnow().isoformat()
            }
        except Exception as e:
            log.error(f"[Tools] Error in save_customer_requirements: {e}")
            return {
                "success": False,
                "message": str(e),
                "storage": None,
                "row_number": None,
                "timestamp": None
            }

    async def complete_customer_conversation(
        self,
        call_id: str,
        final_message: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        TOOL 4: Complete customer conversation
        
        Purpose: Finalize conversation and prepare for call hangup
        
        Args:
            call_id: Unique call identifier
            final_message: Optional final message to play to customer
        
        Returns:
            {
                "success": bool,
                "message": str,
                "requirements_saved": bool,
                "call_ended": bool
            }
        """
        try:
            log.info(f"[Tools] complete_customer_conversation called for {call_id}")
            
            # Verify requirements were saved
            validation = await self.req_service.validate_requirements(call_id)
            if not validation['is_complete']:
                log.error(f"[Tools] Cannot complete: requirements incomplete for {call_id}")
                return {
                    "success": False,
                    "message": "Requirements not complete",
                    "requirements_saved": False,
                    "call_ended": False
                }
            
            # Clean up requirement state
            await self.req_service.cleanup_call(call_id)
            
            log.info(f"[Tools] ✅ Conversation completed: {call_id}")
            
            return {
                "success": True,
                "message": "Conversation completed successfully",
                "requirements_saved": True,
                "call_ended": False  # Actual hangup happens after audio playback
            }
        except Exception as e:
            log.error(f"[Tools] Error in complete_customer_conversation: {e}")
            return {
                "success": False,
                "message": str(e),
                "requirements_saved": False,
                "call_ended": False
            }


_service: Optional[RequirementToolsService] = None


async def init_requirement_tools_service():
    """Initialize requirement tools service"""
    global _service
    _service = RequirementToolsService()
    log.info("[Tools] Requirement tools service initialized")
    return _service


def get_requirement_tools_service() -> Optional[RequirementToolsService]:
    """Get requirement tools service instance"""
    return _service
