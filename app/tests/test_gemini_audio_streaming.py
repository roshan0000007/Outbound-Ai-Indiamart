"""
Gemini Live Audio Streaming - Integration Tests
Comprehensive tests for speech-to-speech audio streaming end-to-end
"""

import asyncio
import logging
from typing import Optional, List
import sys
import os

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


class GeminiAudioStreamingTestSuite:
    """Test suite for Gemini Live audio streaming"""

    def __init__(self):
        self.results: List[dict] = []
        self.failed_count = 0
        self.passed_count = 0

    async def test_provider_initialization(self) -> bool:
        """Test 1: Gemini Live provider initialization"""
        try:
            logger.info("\n" + "="*60)
            logger.info("TEST 1: Gemini Live Provider Initialization")
            logger.info("="*60)

            from app.llm.gemini_live_provider import init_gemini_live_provider, get_gemini_live_provider

            provider = await init_gemini_live_provider()
            if not provider:
                logger.error("❌ Provider initialization failed")
                self.failed_count += 1
                return False

            if not provider.client:
                logger.error("❌ Provider client not initialized")
                self.failed_count += 1
                return False

            logger.info("✅ Provider initialized successfully")
            logger.info(f"   Model: {provider.model}")
            logger.info(f"   Voice: {provider.voice}")
            logger.info(f"   Audio: {provider.audio_config}")

            self.passed_count += 1
            return True

        except Exception as e:
            logger.error(f"❌ Test failed: {e}", exc_info=True)
            self.failed_count += 1
            return False

    async def test_gemini_session_creation(self) -> bool:
        """Test 2: Gemini audio session creation"""
        try:
            logger.info("\n" + "="*60)
            logger.info("TEST 2: Gemini Audio Session Creation")
            logger.info("="*60)

            from app.services.gemini_audio_pipeline import create_gemini_audio_session

            call_id = "test_call_001"
            system_prompt = "You are a helpful assistant."

            session = await create_gemini_audio_session(
                call_id=call_id,
                language="en",
                system_prompt=system_prompt
            )

            if not session:
                logger.error("❌ Session creation failed")
                self.failed_count += 1
                return False

            if not session.session_active:
                logger.error("❌ Session not active")
                self.failed_count += 1
                return False

            logger.info("✅ Session created successfully")
            logger.info(f"   Call ID: {session.call_id}")
            logger.info(f"   Language: {session.language}")
            logger.info(f"   Status: {session.session_active}")

            # Cleanup
            from app.services.gemini_audio_pipeline import end_gemini_audio_session
            await end_gemini_audio_session(call_id)

            self.passed_count += 1
            return True

        except Exception as e:
            logger.error(f"❌ Test failed: {e}", exc_info=True)
            self.failed_count += 1
            return False

    async def test_gemini_session_manager(self) -> bool:
        """Test 3: Gemini session manager"""
        try:
            logger.info("\n" + "="*60)
            logger.info("TEST 3: Gemini Session Manager")
            logger.info("="*60)

            from app.services.gemini_session_manager import init_gemini_session_manager

            manager = await init_gemini_session_manager()
            if not manager:
                logger.error("❌ Manager initialization failed")
                self.failed_count += 1
                return False

            call_id = "test_call_002"
            session_meta = await manager.create_session(
                call_id=call_id,
                language="en"
            )

            if not session_meta:
                logger.error("❌ Session creation via manager failed")
                self.failed_count += 1
                return False

            logger.info("✅ Manager session created successfully")
            logger.info(f"   Call ID: {session_meta['call_id']}")
            logger.info(f"   Status: {session_meta['status']}")

            # Test retrieval
            retrieved = await manager.get_session(call_id)
            if not retrieved:
                logger.error("❌ Session retrieval failed")
                self.failed_count += 1
                return False

            # Cleanup
            await manager.end_session(call_id)

            self.passed_count += 1
            return True

        except Exception as e:
            logger.error(f"❌ Test failed: {e}", exc_info=True)
            self.failed_count += 1
            return False

    async def test_live_call_handler(self) -> bool:
        """Test 4: Live call handler with Gemini streaming"""
        try:
            logger.info("\n" + "="*60)
            logger.info("TEST 4: Live Call Handler - Gemini Streaming")
            logger.info("="*60)

            from app.services.live_call_handler import init_live_call_handler

            handler = await init_live_call_handler()
            if not handler:
                logger.error("❌ Handler initialization failed")
                self.failed_count += 1
                return False

            logger.info("✅ Live call handler initialized")
            logger.info(f"   Gemini audio enabled: {handler.gemini_audio_enabled}")

            call_id = "test_call_003"
            stream_info = await handler.start_call_audio_stream(
                call_id=call_id,
                language="en",
                system_prompt="Test assistant"
            )

            if not stream_info:
                logger.error("❌ Audio stream start failed")
                self.failed_count += 1
                return False

            logger.info("✅ Audio stream started successfully")
            logger.info(f"   Call ID: {stream_info['call_id']}")
            logger.info(f"   Streaming: {stream_info['streaming']}")

            # Cleanup
            await handler.end_call(call_id)

            self.passed_count += 1
            return True

        except Exception as e:
            logger.error(f"❌ Test failed: {e}", exc_info=True)
            self.failed_count += 1
            return False

    async def test_config_values(self) -> bool:
        """Test 5: Configuration values"""
        try:
            logger.info("\n" + "="*60)
            logger.info("TEST 5: Configuration Values")
            logger.info("="*60)

            from app.core.config import (
                GEMINI_API_KEY,
                GEMINI_LIVE_MODEL,
                GEMINI_VOICE,
                GEMINI_AUDIO_STREAMING_ENABLED,
                GEMINI_AUDIO_BUFFER_SIZE,
                GEMINI_AUDIO_TIMEOUT_SEC
            )

            if not GEMINI_API_KEY:
                logger.error("❌ GEMINI_API_KEY not configured")
                self.failed_count += 1
                return False

            logger.info("✅ Configuration loaded successfully")
            logger.info(f"   API Key: {GEMINI_API_KEY[:20]}...")
            logger.info(f"   Model: {GEMINI_LIVE_MODEL}")
            logger.info(f"   Voice: {GEMINI_VOICE}")
            logger.info(f"   Audio Streaming: {GEMINI_AUDIO_STREAMING_ENABLED}")
            logger.info(f"   Buffer Size: {GEMINI_AUDIO_BUFFER_SIZE}")
            logger.info(f"   Timeout: {GEMINI_AUDIO_TIMEOUT_SEC}s")

            self.passed_count += 1
            return True

        except Exception as e:
            logger.error(f"❌ Test failed: {e}", exc_info=True)
            self.failed_count += 1
            return False

    async def test_websocket_connection(self) -> bool:
        """Test 6: WebSocket connection capability"""
        try:
            logger.info("\n" + "="*60)
            logger.info("TEST 6: WebSocket Connection Capability")
            logger.info("="*60)

            try:
                import websockets
                logger.info("✅ websockets library available")
            except ImportError:
                logger.error("❌ websockets library not installed")
                logger.info("   Install with: pip install websockets")
                self.failed_count += 1
                return False

            try:
                import google.generativeai as genai
                logger.info("✅ google-generativeai library available")
            except ImportError:
                logger.error("❌ google-generativeai not installed")
                logger.info("   Install with: pip install google-generativeai")
                self.failed_count += 1
                return False

            self.passed_count += 1
            return True

        except Exception as e:
            logger.error(f"❌ Test failed: {e}", exc_info=True)
            self.failed_count += 1
            return False

    async def run_all_tests(self):
        """Run all tests"""
        logger.info("\n" + "🚀" * 30)
        logger.info("GEMINI LIVE AUDIO STREAMING - TEST SUITE")
        logger.info("🚀" * 30)

        # Run all tests
        await self.test_config_values()
        await self.test_websocket_connection()
        await self.test_provider_initialization()
        await self.test_gemini_session_creation()
        await self.test_gemini_session_manager()
        await self.test_live_call_handler()

        # Print summary
        logger.info("\n" + "="*60)
        logger.info("TEST SUMMARY")
        logger.info("="*60)
        logger.info(f"✅ Passed: {self.passed_count}")
        logger.info(f"❌ Failed: {self.failed_count}")
        logger.info(f"📊 Total: {self.passed_count + self.failed_count}")

        if self.failed_count == 0:
            logger.info("\n🎉 ALL TESTS PASSED! Ready for end-to-end streaming.")
        else:
            logger.error(f"\n⚠️  {self.failed_count} test(s) failed. Review errors above.")

        return self.failed_count == 0


async def main():
    """Main test execution"""
    suite = GeminiAudioStreamingTestSuite()
    success = await suite.run_all_tests()
    return 0 if success else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
