"""
Call Request/Response Schemas
Pydantic models for call API validation
"""

from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field

class CallStartRequest(BaseModel):
    """Call start request schema"""
    caller_number: str = Field(..., min_length=10, max_length=20)
    dnid: Optional[str] = None
    user_id: int

    class Config:
        json_schema_extra = {
            "example": {
                "caller_number": "919876543210",
                "dnid": "1234",
                "user_id": 1
            }
        }

class CallEndRequest(BaseModel):
    """Call end request schema"""
    call_id: str = Field(..., min_length=1)
    reason: str = Field(default="normal")

    class Config:
        json_schema_extra = {
            "example": {
                "call_id": "call_12345",
                "reason": "user_hangup"
            }
        }

class CallResponse(BaseModel):
    """Call response schema"""
    call_id: str
    caller_number: str
    user_id: int
    call_started_at: datetime
    call_duration: Optional[int]

    class Config:
        json_schema_extra = {
            "example": {
                "call_id": "call_12345",
                "caller_number": "919876543210",
                "user_id": 1,
                "call_started_at": "2024-01-15T10:30:00",
                "call_duration": 180
            }
        }

class CallStatusRequest(BaseModel):
    """Call status request schema"""
    call_id: str

    class Config:
        json_schema_extra = {
            "example": {"call_id": "call_12345"}
        }

class CallListResponse(BaseModel):
    """Call list response schema"""
    total: int
    calls: list[CallResponse]
