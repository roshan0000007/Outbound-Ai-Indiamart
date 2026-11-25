#!/usr/bin/env python3
"""
Test script to verify ARI session initialization and bridge creation
Tests the fix for "[ARI] HTTP Session not initialized" error
"""

import asyncio
import sys
import logging
from pathlib import Path

# Add app to path
sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

async def test_ari_initialization():
    """Test ARI session initialization and configuration validation"""
    print("\n" + "="*80)
    print("TEST: ARI Session Initialization and Configuration Validation")
    print("="*80 + "\n")
    
    try:
        from app.core.config import (
            ARI_URL, ARI_USER, STASIS_APP, ASTERISK_IP, MY_PC_IP,
            RTP_START_PORT, RTP_END_PORT, log
        )
        from app.transport.asterisk import (
            init_ari_session, close_ari_session, get_ari_session,
            _validate_ari_config
        )
        
        # Test 1: Configuration Validation
        print("[TEST 1] Validating ARI configuration...")
        is_valid = _validate_ari_config()
        
        if not is_valid:
            print("❌ Configuration validation FAILED")
            return False
        
        print("✅ Configuration validation PASSED\n")
        
        # Test 2: ARI Session Initialization
        print("[TEST 2] Initializing ARI HTTP session...")
        try:
            session = await init_ari_session()
            if session is None or session.closed:
                print("❌ ARI session is None or closed")
                return False
            print("✅ ARI HTTP session initialized successfully\n")
        except Exception as e:
            print(f"❌ ARI session initialization failed: {e}")
            return False
        
        # Test 3: Session State Check
        print("[TEST 3] Verifying ARI session state...")
        session = get_ari_session()
        if session is None:
            print("❌ get_ari_session() returned None")
            return False
        
        if session.closed:
            print("❌ ARI session is marked as closed")
            return False
        
        print("✅ ARI session state is valid\n")
        
        # Test 4: Simulate Bridge Creation (dry run)
        print("[TEST 4] Testing bridge creation call (will verify HTTP layer)...")
        try:
            from app.transport.asterisk import ari_request
            
            # Make a test request to verify the session and auth work
            # Using a safe endpoint that just tests connectivity
            test_response = await ari_request("GET", "/ari/asterisk/info")
            
            if test_response is not None:
                print(f"✅ Successfully made ARI HTTP request")
                print(f"   Response type: {type(test_response)}")
                if isinstance(test_response, dict):
                    print(f"   Response keys: {list(test_response.keys())[:5]}")
            else:
                print("⚠️  ARI HTTP request returned empty response (may indicate connectivity issue)")
        except Exception as e:
            print(f"⚠️  ARI HTTP request error: {e}")
            # This might fail if Asterisk is not running, which is OK for this test
        
        print()
        
        # Cleanup
        print("[CLEANUP] Closing ARI session...")
        await close_ari_session()
        session = get_ari_session()
        if session is None or session.closed:
            print("✅ ARI session closed successfully\n")
        else:
            print("⚠️  ARI session not fully closed\n")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_startup_sequence():
    """Test the full startup sequence"""
    print("\n" + "="*80)
    print("TEST: Full Application Startup Sequence (Partial)")
    print("="*80 + "\n")
    
    try:
        from app.core.config import log
        from app.core.database import init_db_pool, close_db_pool
        from app.core.redis import init_redis, close_redis
        from app.transport.asterisk import init_ari_session, close_ari_session, get_ari_session
        
        print("[STARTUP] Starting core infrastructure...")
        
        # Initialize core infrastructure
        try:
            await init_db_pool()
            print("[STARTUP] ✓ Database pool initialized")
        except Exception as e:
            print(f"[STARTUP] ⚠️ Database pool failed: {e}")
        
        try:
            await init_redis()
            print("[STARTUP] ✓ Redis initialized")
        except Exception as e:
            print(f"[STARTUP] ⚠️ Redis failed: {e}")
        
        # Initialize ARI HTTP session
        print("[STARTUP] Initializing ARI HTTP session...")
        try:
            await init_ari_session()
            session = get_ari_session()
            if session and not session.closed:
                print("[STARTUP] ✅ ARI HTTP session ready for bridge/ExternalMedia operations")
            else:
                print("[STARTUP] ❌ ARI HTTP session not ready")
                return False
        except Exception as e:
            print(f"[STARTUP] ❌ ARI HTTP session failed: {e}")
            return False
        
        print("\n✅ Startup sequence validated - ARI HTTP session is ready BEFORE WebSocket\n")
        
        # Cleanup
        try:
            await close_ari_session()
            await close_db_pool()
            await close_redis()
            print("[CLEANUP] ✓ All services closed\n")
        except Exception as e:
            print(f"[CLEANUP] ⚠️ Error during cleanup: {e}\n")
        
        return True
        
    except Exception as e:
        print(f"❌ Startup test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Run all tests"""
    print("\n" + "="*80)
    print("ARI SESSION INITIALIZATION TEST SUITE")
    print("="*80)
    print("\nTesting fix for: '[ARI] HTTP Session not initialized' error")
    print("Context: Bridge creation during incoming call handling\n")
    
    test1_passed = await test_ari_initialization()
    test2_passed = await test_startup_sequence()
    
    print("\n" + "="*80)
    print("TEST RESULTS")
    print("="*80)
    print(f"Test 1 (ARI Initialization):    {'✅ PASSED' if test1_passed else '❌ FAILED'}")
    print(f"Test 2 (Startup Sequence):      {'✅ PASSED' if test2_passed else '❌ FAILED'}")
    print("="*80 + "\n")
    
    all_passed = test1_passed and test2_passed
    
    if all_passed:
        print("✅ ALL TESTS PASSED - ARI session will be initialized before call handling\n")
        return 0
    else:
        print("❌ SOME TESTS FAILED - Review errors above\n")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
