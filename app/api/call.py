"""
Call Management API Routes
Endpoints for managing calls and live call flow
"""

from fastapi import APIRouter, HTTPException, status
from typing import Optional
from pydantic import BaseModel, Field

from ..schemas.call import CallStartRequest, CallEndRequest, CallResponse, CallStatusRequest
from ..services.call_service import get_call_service
from ..handlers.call_handler import get_call_handler
from ..core.config import log

router = APIRouter(prefix="/api/calls", tags=["calls"])

@router.post("/start", response_model=CallResponse, status_code=status.HTTP_201_CREATED)
async def start_call(request: CallStartRequest):
    """Start a new call"""
    try:
        call_service = get_call_service()
        if not call_service:
            raise HTTPException(status_code=500, detail="Call service not initialized")

        import time
        cid = f"call_{request.user_id}_{request.caller_number}_{int(time.time() * 1000)}"

        success = await call_service.create_call(
            cid, request.caller_number, request.user_id, request.dnid
        )

        if not success:
            raise HTTPException(status_code=400, detail="Failed to create call")

        call = await call_service.get_call(cid)
        return CallResponse(**call)
    except Exception as e:
        log.error(f"[API] Call start error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/end", status_code=status.HTTP_200_OK)
async def end_call(request: CallEndRequest):
    """End an active call"""
    try:
        call_service = get_call_service()
        if not call_service:
            raise HTTPException(status_code=500, detail="Call service not initialized")

        success = await call_service.end_call(request.call_id, request.reason)

        if not success:
            raise HTTPException(status_code=404, detail="Call not found")

        return {"message": "Call ended successfully", "call_id": request.call_id}
    except Exception as e:
        log.error(f"[API] Call end error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/status/{call_id}", response_model=dict)
async def get_call_status(call_id: str):
    """Get call status"""
    try:
        call_service = get_call_service()
        if not call_service:
            raise HTTPException(status_code=500, detail="Call service not initialized")

        call = await call_service.get_call(call_id)

        if not call:
            raise HTTPException(status_code=404, detail="Call not found")

        return {"call_id": call_id, "status": call.get("status"), "data": call}
    except Exception as e:
        log.error(f"[API] Status check error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/active-count", response_model=dict)
async def get_active_calls_count():
    """Get count of active calls"""
    try:
        call_service = get_call_service()
        if not call_service:
            raise HTTPException(status_code=500, detail="Call service not initialized")

        count = await call_service.get_active_calls_count()
        return {"active_calls": count}
    except Exception as e:
        log.error(f"[API] Active calls count error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

class CallStartHandlerRequest(BaseModel):
    """Call start handler request"""
    call_id: str = Field(..., description="Unique call identifier")
    caller_number: str = Field(..., description="Caller's phone number")
    dnid: str = Field(..., description="Called number")
    user_id: int = Field(..., description="User ID")

class CallEndHandlerRequest(BaseModel):
    """Call end handler request"""
    call_id: str = Field(..., description="Call identifier")

@router.post("/handler/start")
async def call_start_handler(request: CallStartHandlerRequest):
    """
    Call Start Handler - Initialize call session
    
    Args:
        call_id: Unique call ID
        caller_number: Customer phone
        dnid: Called number
        user_id: User ID
    
    Returns:
        Success status and call data
    """
    try:
        handler = get_call_handler()
        if not handler:
            raise HTTPException(status_code=500, detail="Call handler not initialized")

        success = await handler.on_call_start(
            call_id=request.call_id,
            user_id=request.user_id,
            dnid=request.dnid,
            caller_number=request.caller_number
        )

        if not success:
            raise HTTPException(status_code=400, detail="Failed to initialize call")

        log.info(f"[API] Call initialized: {request.call_id}")

        return {
            "call_id": request.call_id,
            "success": True,
            "message": "Call session initialized"
        }

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"[API] Call start handler error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/handler/end")
async def call_end_handler(request: CallEndHandlerRequest):
    """
    Call End Handler - Save conversation and cleanup
    
    Args:
        call_id: Call ID
    
    Returns:
        Success status
    """
    try:
        handler = get_call_handler()
        if not handler:
            raise HTTPException(status_code=500, detail="Call handler not initialized")

        success = await handler.on_call_end(request.call_id)

        if not success:
            raise HTTPException(status_code=400, detail="Failed to end call")

        log.info(f"[API] Call ended: {request.call_id}")

        return {
            "call_id": request.call_id,
            "success": True,
            "message": "Call session closed"
        }

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"[API] Call end handler error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
