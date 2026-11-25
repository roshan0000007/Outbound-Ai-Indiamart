"""
AI Interaction API Routes
Endpoints for AI conversations and responses
"""

from fastapi import APIRouter, HTTPException, status
from typing import Optional, List
from pydantic import BaseModel, Field
import uuid
from datetime import datetime

from ..schemas.ai import AIResponseRequest, AIResponseResponse, AIResponseData
from ..llm.gemini_live_provider import get_gemini_live_provider
from ..session.redis_session import get_call_session
from ..core.config import log

router = APIRouter(prefix="/api/ai", tags=["ai"])

class AIQueryRequest(BaseModel):
    """AI query request"""
    call_id: str = Field(..., description="Unique call identifier")
    user_id: int = Field(..., description="User ID")
    query: str = Field(..., min_length=1, max_length=2000, description="Customer question")
    language: Optional[str] = Field("en", description="Language: en, hi")
    conversation_history: Optional[List[dict]] = Field([], description="Previous messages")

    class Config:
        json_schema_extra = {
            "example": {
                "call_id": "call_12345",
                "user_id": 1,
                "query": "What can I help you with?",
                "language": "en",
                "conversation_history": []
            }
        }

class AIQueryResponse(BaseModel):
    """AI query response"""
    call_id: str
    success: bool
    answer: Optional[str] = None
    confidence: float = 0.0
    error: Optional[str] = None
    language: Optional[str] = "en"

    class Config:
        json_schema_extra = {
            "example": {
                "call_id": "call_12345",
                "success": True,
                "answer": "I'm here to help you. How can I assist?",
                "confidence": 0.95,
                "language": "en"
            }
        }

@router.post("/query", response_model=AIQueryResponse)
async def ai_query(request: AIQueryRequest):
    """Generate AI response for customer query"""
    try:
        call_id = request.call_id
        query_text = request.query
        language = request.language or "en"

        log.info(f"[AI Query] Processing: {query_text[:50]}...")

        # Get Gemini Live provider
        gemini = get_gemini_live_provider()
        if not gemini:
            raise HTTPException(status_code=500, detail="Gemini Live provider not initialized")

        # Build context
        context_messages = []
        
        # Add conversation history
        if request.conversation_history:
            for msg in request.conversation_history:
                context_messages.append({
                    "role": msg.get("role", "user"),
                    "content": msg.get("content", "")
                })

        # Add current query
        context_messages.append({
            "role": "user",
            "content": query_text
        })

        # Get AI response (using Gemini Live for fast processing)
        response = await gemini.get_text_response(
            prompt=query_text,
            system_prompt="You are a professional sales assistant. Answer concisely and helpfully."
        )

        if not response:
            raise HTTPException(status_code=500, detail="Failed to generate response")

        log.info(f"[AI Query] ✅ Response generated: {response[:50]}...")

        return AIQueryResponse(
            call_id=call_id,
            success=True,
            answer=response,
            confidence=0.9,
            language=language
        )

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"[AI Query] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/respond", response_model=AIResponseResponse)
async def ai_respond(request: AIResponseRequest):
    """
    Generate AI response with conversation context
    
    Args:
        request: AIResponseRequest with call_id, user_text, language, history
    
    Returns:
        AIResponseResponse with answer and metadata
    """
    try:
        call_id = request.call_id
        user_text = request.user_text
        language = request.language or "en"

        log.info(f"[AI Respond] Call {call_id}: {user_text[:50]}...")

        # Get Gemini Live provider
        gemini = get_gemini_live_provider()
        if not gemini:
            raise HTTPException(status_code=500, detail="Gemini Live provider not initialized")

        # Build context messages
        messages = []
        
        # Add conversation history
        if request.conversation_history:
            for msg in request.conversation_history:
                messages.append({
                    "role": msg.sender if hasattr(msg, 'sender') else msg.get("sender", "user"),
                    "content": msg.text if hasattr(msg, 'text') else msg.get("text", "")
                })

        # Add current message
        messages.append({
            "role": "user",
            "content": user_text
        })

        # Get AI response (using Gemini Live for fast processing)
        response = await gemini.get_text_response(
            prompt=user_text,
            system_prompt="You are a professional sales assistant. Answer concisely and helpfully."
        )

        if not response:
            raise HTTPException(status_code=500, detail="Failed to generate response")

        log.info(f"[AI Respond] ✅ Generated response for {call_id}")

        return AIResponseResponse(
            call_id=call_id,
            success=True,
            data=AIResponseData(
                response_text=response,
                language=language,
                confidence=0.9
            )
        )

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"[AI Respond] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
