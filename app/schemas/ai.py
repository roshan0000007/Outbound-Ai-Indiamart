"""
AI Interaction Schemas
Pydantic models for AI API validation
"""

from typing import Optional, List, Literal
from pydantic import BaseModel, Field

class ConversationMessage(BaseModel):
    """Conversation message schema"""
    sender: str = Field(..., pattern="^(user|ai)$")
    text: str = Field(..., min_length=1, max_length=2000)
    timestamp: Optional[float] = None

    class Config:
        json_schema_extra = {
            "example": {
                "sender": "user",
                "text": "Hello, how can I help you?"
            }
        }

class AIResponseRequest(BaseModel):
    """AI response request schema"""
    call_id: str
    user_text: str = Field(..., min_length=1, max_length=2000)
    language: str = Field(default="en", pattern="^(en|hi)$")
    conversation_history: Optional[List[ConversationMessage]] = []

    class Config:
        json_schema_extra = {
            "example": {
                "call_id": "call_12345",
                "user_text": "Hello, I have a question",
                "language": "en",
                "conversation_history": []
            }
        }

class AIResponse(BaseModel):
    """
    Structured AI Response Schema
    Returns grounded, validated response with confidence levels
    """
    answer: str = Field(..., min_length=1, max_length=500)
    language: Literal["hi", "en"] = Field(default="en")
    confidence: Literal["high", "medium", "low"] = Field(default="medium")

    class Config:
        json_schema_extra = {
            "example": {
                "answer": "Thank you for calling. How can I assist you?",
                "language": "en",
                "confidence": "high"
            }
        }

class AIResponseData(BaseModel):
    """AI response data schema"""
    response_text: str
    language: str
    confidence: float

    class Config:
        json_schema_extra = {
            "example": {
                "response_text": "Thank you for your message",
                "language": "en",
                "confidence": 0.98
            }
        }

class AIResponseResponse(BaseModel):
    """AI response response schema"""
    call_id: str
    success: bool
    data: Optional[AIResponseData] = None
    error: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "call_id": "call_12345",
                "success": True,
                "data": {
                    "response_text": "Your current balance is 5000 rupees",
                    "language": "en",
                    "intent": "balance_check",
                    "confidence": 0.98,
                    "grounded": True,
                    "transfer_recommended": False,
                    "requires_human": False
                }
            }
        }
