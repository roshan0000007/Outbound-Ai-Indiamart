"""
Customer Requirements API Routes
Endpoints for requirement collection tools and operations
"""

from fastapi import APIRouter, HTTPException, status
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

from ..services.requirement_tools_service import get_requirement_tools_service
from ..services.customer_requirement_service import get_customer_requirement_service
from ..core.config import log

router = APIRouter(prefix="/api/requirements", tags=["requirements"])


# ═══════════════════════════════════════════════════════════
# Request/Response Models
# ═══════════════════════════════════════════════════════════

class UpdateRequirementsRequest(BaseModel):
    """Update customer requirements"""
    call_id: str = Field(..., description="Unique call identifier")
    customer_name: Optional[str] = None
    company_name: Optional[str] = None
    location: Optional[str] = None
    interested_products: Optional[List[str]] = None
    required_quantity: Optional[str] = None
    business_requirement: Optional[str] = None
    bulk_and_other_requirements: Optional[str] = None


class UpdateRequirementsResponse(BaseModel):
    """Update response"""
    success: bool
    message: str
    updated_fields: List[str]
    current_state: Optional[Dict[str, Any]]


class ValidateRequirementsRequest(BaseModel):
    """Validate customer requirements"""
    call_id: str = Field(..., description="Unique call identifier")


class ValidateRequirementsResponse(BaseModel):
    """Validation response"""
    is_complete: bool
    completed_fields: List[str]
    pending_fields: List[str]
    unclear_fields: List[str]
    validation_errors: List[str]


class SaveRequirementsRequest(BaseModel):
    """Save customer requirements"""
    call_id: str = Field(..., description="Unique call identifier")


class SaveRequirementsResponse(BaseModel):
    """Save response"""
    success: bool
    message: str
    storage: Optional[str]
    row_number: Optional[int]
    timestamp: Optional[str]


class CompleteConversationRequest(BaseModel):
    """Complete customer conversation"""
    call_id: str = Field(..., description="Unique call identifier")
    final_message: Optional[str] = None


class CompleteConversationResponse(BaseModel):
    """Completion response"""
    success: bool
    message: str
    requirements_saved: bool
    call_ended: bool


# ═══════════════════════════════════════════════════════════
# Tool Endpoints
# ═══════════════════════════════════════════════════════════

@router.post("/update", response_model=UpdateRequirementsResponse)
async def update_requirements(request: UpdateRequirementsRequest):
    """
    TOOL 1: Update customer requirements
    
    Extracts and updates specific requirement categories from customer information.
    """
    try:
        log.info(f"[API] update_requirements: {request.call_id}")
        
        tools_service = get_requirement_tools_service()
        if not tools_service:
            raise HTTPException(status_code=500, detail="Tools service not available")
        
        # Prepare updates dictionary
        updates = {}
        if request.customer_name:
            updates["customer_name"] = request.customer_name
        if request.company_name:
            updates["company_name"] = request.company_name
        if request.location:
            updates["location"] = request.location
        if request.interested_products:
            updates["interested_products"] = request.interested_products
        if request.required_quantity:
            updates["required_quantity"] = request.required_quantity
        if request.business_requirement:
            updates["business_requirement"] = request.business_requirement
        if request.bulk_and_other_requirements:
            updates["bulk_and_other_requirements"] = request.bulk_and_other_requirements
        
        result = await tools_service.update_customer_requirements(
            request.call_id,
            updates
        )
        
        return UpdateRequirementsResponse(
            success=result.get("success", False),
            message=result.get("message", ""),
            updated_fields=result.get("updated_fields", []),
            current_state=result.get("current_state")
        )
    
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"[API] update_requirements error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/validate", response_model=ValidateRequirementsResponse)
async def validate_requirements(request: ValidateRequirementsRequest):
    """
    TOOL 2: Validate customer requirements
    
    Checks if all required fields are complete and valid.
    """
    try:
        log.info(f"[API] validate_requirements: {request.call_id}")
        
        tools_service = get_requirement_tools_service()
        if not tools_service:
            raise HTTPException(status_code=500, detail="Tools service not available")
        
        result = await tools_service.validate_customer_requirements(request.call_id)
        
        return ValidateRequirementsResponse(
            is_complete=result.get("is_complete", False),
            completed_fields=result.get("completed_fields", []),
            pending_fields=result.get("pending_fields", []),
            unclear_fields=result.get("unclear_fields", []),
            validation_errors=result.get("validation_errors", [])
        )
    
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"[API] validate_requirements error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/save", response_model=SaveRequirementsResponse)
async def save_requirements(request: SaveRequirementsRequest):
    """
    TOOL 3: Save customer requirements
    
    Persists validated requirements to storage (MySQL, Google Sheets, or Excel).
    """
    try:
        log.info(f"[API] save_requirements: {request.call_id}")
        
        tools_service = get_requirement_tools_service()
        if not tools_service:
            raise HTTPException(status_code=500, detail="Tools service not available")
        
        result = await tools_service.save_customer_requirements(request.call_id)
        
        return SaveRequirementsResponse(
            success=result.get("success", False),
            message=result.get("message", ""),
            storage=result.get("storage"),
            row_number=result.get("row_number"),
            timestamp=result.get("timestamp")
        )
    
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"[API] save_requirements error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/complete", response_model=CompleteConversationResponse)
async def complete_conversation(request: CompleteConversationRequest):
    """
    TOOL 4: Complete customer conversation
    
    Finalizes conversation after all requirements are collected and saved.
    """
    try:
        log.info(f"[API] complete_conversation: {request.call_id}")
        
        tools_service = get_requirement_tools_service()
        if not tools_service:
            raise HTTPException(status_code=500, detail="Tools service not available")
        
        result = await tools_service.complete_customer_conversation(
            request.call_id,
            request.final_message
        )
        
        return CompleteConversationResponse(
            success=result.get("success", False),
            message=result.get("message", ""),
            requirements_saved=result.get("requirements_saved", False),
            call_ended=result.get("call_ended", False)
        )
    
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"[API] complete_conversation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════
# Utility Endpoints
# ═══════════════════════════════════════════════════════════

@router.get("/status/{call_id}", response_model=Dict[str, Any])
async def get_requirement_status(call_id: str):
    """Get current requirement collection status for a call"""
    try:
        req_service = get_customer_requirement_service()
        if not req_service:
            raise HTTPException(status_code=500, detail="Requirement service not available")
        
        requirements = await req_service.get_requirements(call_id)
        validation = await req_service.validate_requirements(call_id)
        
        return {
            "call_id": call_id,
            "requirements": requirements,
            "validation": validation
        }
    
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"[API] get_requirement_status error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/questions", response_model=Dict[str, str])
async def get_all_questions():
    """Get all requirement collection questions"""
    try:
        from ..core.client_config import ClientConfig
        return ClientConfig.get_all_questions()
    
    except Exception as e:
        log.error(f"[API] get_all_questions error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
