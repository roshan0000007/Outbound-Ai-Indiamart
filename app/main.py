"""
Main Application Entry Point
Minimal initialization - only essential services for calling and conversation history
"""

import asyncio
import logging
import warnings
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

warnings.filterwarnings("ignore", category=RuntimeWarning)

def suppress_httpx_warnings():
    """Suppress HTTPX-related warnings from async client cleanup"""
    try:
        loop = asyncio.get_event_loop()
        original_exception_handler = loop.get_exception_handler

        def custom_exception_handler(loop, context):
            exception = context.get('exception')
            if exception and isinstance(exception, AttributeError):
                if "'_state'" in str(exception) and "AsyncHttpxClientWrapper" in str(exception):
                    return
            if original_exception_handler:
                original_exception_handler(context)

        loop.set_exception_handler(custom_exception_handler)
    except Exception:
        pass

suppress_httpx_warnings()

from app.core.config import APP_NAME, APP_HOST, APP_PORT, LOG_LEVEL, log
from app.core.database import init_db_pool, close_db_pool, get_db_pool
from app.core.redis import init_redis, close_redis

from app.services.call_service import init_call_service
from app.services.language_service import init_language_service
from app.services.conversation_service import init_conversation_service
from app.services.live_call_handler import init_live_call_handler
from app.services.conversation_history_service import get_conversation_history_service

from app.llm.gemini_live_provider import init_gemini_live_provider
from app.services.gemini_session_manager import init_gemini_session_manager

from app.session.redis_session import init_call_session
from app.handlers.call_handler import init_call_handler

from app.transport.asterisk import init_ari_session, close_ari_session, init_ari_websocket, register_event_handler

from app.api import call, ai, health

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown"""

    log.info(f"[STARTUP] {APP_NAME}")

    try:
        # Initialize core infrastructure
        await init_db_pool()
        await init_redis()

        # Initialize call management
        try:
            await init_call_service()
            log.info("[STARTUP] ✓ Call service initialized")
        except Exception as e:
            log.warning(f"[STARTUP] Call service initialization failed: {e}")

        # Initialize language service
        init_language_service()

        # Initialize conversation capture service (CRITICAL: conversation history tracking)
        try:
            from app.services.conversation_capture_service import init_conversation_capture_service
            await init_conversation_capture_service()
            log.info("[STARTUP] ✓ Conversation capture service initialized (conversation history tracking)")
        except Exception as e:
            log.warning(f"[STARTUP] Conversation capture service initialization failed: {e}")

        # Initialize conversation services
        try:
            await init_conversation_service()
            log.info("[STARTUP] ✓ Conversation service initialized")
        except Exception as e:
            log.warning(f"[STARTUP] Conversation service initialization failed: {e}")

        try:
            await init_live_call_handler()
            log.info("[STARTUP] ✓ Live call handler initialized")
        except Exception as e:
            log.warning(f"[STARTUP] Live call handler initialization failed: {e}")

        # Initialize LLM provider (Gemini Live for fast processing)
        try:
            await init_gemini_live_provider()
            log.info("[STARTUP] ✓ Gemini Live provider initialized for fast call processing")
        except Exception as e:
            log.warning(f"[STARTUP] Gemini Live provider initialization failed: {e}")

        # Initialize Gemini Session Manager
        try:
            await init_gemini_session_manager()
            log.info("[STARTUP] ✓ Gemini session manager initialized for audio streaming")
        except Exception as e:
            log.warning(f"[STARTUP] Gemini session manager initialization failed: {e}")

        # Initialize session management
        try:
            await init_call_session()
            log.info("[STARTUP] ✓ Session manager initialized")
        except Exception as e:
            log.warning(f"[STARTUP] Session manager initialization failed: {e}")

        # Initialize customer requirement service
        try:
            from app.services.customer_requirement_service import init_customer_requirement_service
            await init_customer_requirement_service()
            log.info("[STARTUP] ✓ Customer requirement service initialized")
        except Exception as e:
            log.warning(f"[STARTUP] Customer requirement service initialization failed: {e}")

        # Initialize requirement tools service
        try:
            from app.services.requirement_tools_service import init_requirement_tools_service
            await init_requirement_tools_service()
            log.info("[STARTUP] ✓ Requirement tools service initialized")
        except Exception as e:
            log.warning(f"[STARTUP] Requirement tools service initialization failed: {e}")

        # Initialize lead storage service
        try:
            from app.services.lead_storage_service import init_lead_storage_service
            await init_lead_storage_service()
            log.info("[STARTUP] ✓ Lead storage service initialized")
        except Exception as e:
            log.warning(f"[STARTUP] Lead storage service initialization failed: {e}")

        # Initialize greeting service
        try:
            from app.services.greeting_service import init_greeting_service
            await init_greeting_service()
            log.info("[STARTUP] ✓ Greeting service initialized")
        except Exception as e:
            log.warning(f"[STARTUP] Greeting service initialization failed: {e}")

        # Initialize LLM failover service (Gemini Live → Groq)
        try:
            from app.services.llm_failover_service import init_llm_failover_service
            await init_llm_failover_service()
            log.info("[STARTUP] ✓ LLM failover service initialized (Gemini Live → Groq)")
        except Exception as e:
            log.warning(f"[STARTUP] LLM failover service initialization failed: {e}")

        # Initialize call lifecycle logger (latency tracking)
        try:
            from app.services.call_lifecycle_logger import init_call_lifecycle_logger
            await init_call_lifecycle_logger()
            log.info("[STARTUP] ✓ Call lifecycle logger initialized (latency tracking)")
        except Exception as e:
            log.warning(f"[STARTUP] Call lifecycle logger initialization failed: {e}")

        # Initialize call handler
        try:
            await init_call_handler()
            log.info("[STARTUP] ✓ Call handler initialized")
        except Exception as e:
            log.warning(f"[STARTUP] Call handler initialization failed: {e}")

        # Initialize media service
        try:
            from app.services.media_service import init_media_service
            await init_media_service()
            log.info("[STARTUP] ✓ Media service initialized")
        except Exception as e:
            log.error(f"[STARTUP] ✗ Media service initialization failed: {e}")
            raise RuntimeError(f"Media service failed to initialize: {e}")

        # Initialize ARI HTTP session (CRITICAL: must be before WebSocket)
        try:
            await init_ari_session()
            log.info("[STARTUP] ✓ ARI HTTP session initialized for bridge/ExternalMedia operations")
        except Exception as e:
            log.error(f"[STARTUP] ✗ ARI HTTP session initialization failed: {e}")
            raise RuntimeError(f"ARI HTTP session initialization failed: {e}")

        # Initialize ARI WebSocket connection
        try:
            from app.transport.asterisk import init_ari_websocket, register_event_handler
            from app.handlers.ari_event_handler import (
                handle_stasis_start, handle_stasis_end, handle_channel_dtmf_received
            )

            success = await init_ari_websocket()
            if success:
                register_event_handler("StasisStart", handle_stasis_start)
                register_event_handler("StasisEnd", handle_stasis_end)
                register_event_handler("ChannelDtmfReceived", handle_channel_dtmf_received)
                log.info("[STARTUP] ✓ ARI WebSocket connected and listening for Stasis events")
            else:
                log.error("[STARTUP] ✗ ARI WebSocket connection failed")
        except Exception as e:
            log.error(f"[STARTUP] ARI WebSocket initialization failed: {e}")
            raise RuntimeError(f"ARI WebSocket initialization failed: {e}")

        log.info("[STARTUP] ✓ All services initialized successfully")
    except Exception as e:
        log.error(f"[STARTUP] ✗ Initialization failed: {e}")
        raise

    yield

    log.info("[SHUTDOWN] Closing services")

    try:
        try:
            from app.services.gemini_session_manager import get_gemini_session_manager
            coordinator = get_gemini_session_manager()
            if coordinator:
                await coordinator.cleanup_all()
                log.info("[SHUTDOWN] ✓ Gemini session manager cleaned up")
        except Exception as e:
            log.warning(f"[SHUTDOWN] Gemini session cleanup error: {e}")

        try:
            from app.services.media_service import get_media_service
            media_service = get_media_service()
            if media_service:
                await media_service.shutdown()
                log.info("[SHUTDOWN] ✓ Media service shut down")
        except Exception as e:
            log.warning(f"[SHUTDOWN] Media service shutdown error: {e}")

        await close_ari_session()
        await close_db_pool()
        await close_redis()
        log.info("[SHUTDOWN] ✓ All services closed")
    except Exception as e:
        log.error(f"[SHUTDOWN] Error: {e}")

app = FastAPI(
    title=APP_NAME,
    description="AI call handler with conversation history",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """Handle general exceptions"""
    log.error(f"[Exception] {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )

# Include only essential routers
app.include_router(health.router)
app.include_router(call.router)
app.include_router(ai.router)

try:
    from app.api import requirements
    app.include_router(requirements.router)
    log.info("[Startup] Requirements API endpoints available at /api/requirements")
except Exception as e:
    log.warning(f"[Startup] Requirements router not available: {e}")

try:
    from app.api import debug
    app.include_router(debug.router)
    log.info("[Startup] Debug API endpoints available at /api/debug")
except Exception as e:
    log.warning(f"[Startup] Debug router not available: {e}")

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "name": APP_NAME,
        "status": "running",
        "version": "1.0.0",
    }

if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(level=getattr(logging, LOG_LEVEL))

    uvicorn.run(
        app,
        host=APP_HOST,
        port=APP_PORT,
        reload=False,
        log_level=LOG_LEVEL.lower(),
    )
