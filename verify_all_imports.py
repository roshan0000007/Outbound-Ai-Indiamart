#!/usr/bin/env python3
"""
Comprehensive Import & Dependency Verification Script
Tests all file connections and dependencies before startup
"""

import sys
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)-8s | %(name)s | %(message)s'
)
log = logging.getLogger("VERIFY")

def test_import(module_path: str, description: str) -> bool:
    """Test a single import"""
    try:
        parts = module_path.split('.')
        if parts[0] == 'app':
            module = __import__(module_path, fromlist=[parts[-1]])
        else:
            module = __import__(module_path)
        log.info(f"✅ {description}: {module_path}")
        return True
    except Exception as e:
        log.error(f"❌ {description}: {module_path}")
        log.error(f"   Error: {e}")
        return False

def test_class_exists(module_path: str, class_name: str, description: str) -> bool:
    """Test if a class exists in a module"""
    try:
        parts = module_path.split('.')
        module = __import__(module_path, fromlist=[parts[-1]])
        if hasattr(module, class_name):
            log.info(f"✅ {description}: {class_name} in {module_path}")
            return True
        else:
            log.error(f"❌ {description}: {class_name} NOT FOUND in {module_path}")
            return False
    except Exception as e:
        log.error(f"❌ {description}: Failed to check {class_name}")
        log.error(f"   Error: {e}")
        return False

def test_function_exists(module_path: str, func_name: str, description: str) -> bool:
    """Test if a function exists in a module"""
    try:
        parts = module_path.split('.')
        module = __import__(module_path, fromlist=[parts[-1]])
        if hasattr(module, func_name):
            log.info(f"✅ {description}: {func_name}() in {module_path}")
            return True
        else:
            log.error(f"❌ {description}: {func_name}() NOT FOUND in {module_path}")
            return False
    except Exception as e:
        log.error(f"❌ {description}: Failed to check {func_name}()")
        log.error(f"   Error: {e}")
        return False

def main():
    log.info("=" * 70)
    log.info("COMPREHENSIVE IMPORT & DEPENDENCY VERIFICATION")
    log.info("=" * 70)
    
    results = []
    
    # ======================================================================
    # CORE MODULES
    # ======================================================================
    log.info("\n[1] CORE MODULES")
    log.info("-" * 70)
    results.append(test_import("app.core.config", "Config module"))
    results.append(test_import("app.core.database", "Database module"))
    results.append(test_import("app.core.redis", "Redis module"))
    results.append(test_import("app.core.error_handling", "Error handling module"))
    
    # ======================================================================
    # MEDIA SERVICE (CRITICAL)
    # ======================================================================
    log.info("\n[2] MEDIA SERVICE (CRITICAL)")
    log.info("-" * 70)
    results.append(test_import("app.services.media_service", "Media service module"))
    results.append(test_class_exists("app.services.media_service", "MediaSession", "MediaSession class"))
    results.append(test_class_exists("app.services.media_service", "MediaServiceManager", "MediaServiceManager class"))
    results.append(test_class_exists("app.services.media_service", "MediaConfig", "MediaConfig class"))
    results.append(test_function_exists("app.services.media_service", "init_media_service", "init_media_service function"))
    results.append(test_function_exists("app.services.media_service", "get_media_service", "get_media_service function"))
    
    # ======================================================================
    # LLM & GEMINI
    # ======================================================================
    log.info("\n[3] LLM & GEMINI MODULES")
    log.info("-" * 70)
    results.append(test_import("app.llm.base", "LLM base module"))
    results.append(test_import("app.llm.gemini_live_provider", "Gemini Live provider"))
    results.append(test_class_exists("app.llm.gemini_live_provider", "GeminiLiveProvider", "GeminiLiveProvider class"))
    results.append(test_import("app.services.gemini_audio_pipeline", "Gemini audio pipeline"))
    results.append(test_import("app.services.gemini_session_manager", "Gemini session manager"))
    
    # ======================================================================
    # CALL & HANDLER SERVICES
    # ======================================================================
    log.info("\n[4] CALL & HANDLER SERVICES")
    log.info("-" * 70)
    results.append(test_import("app.services.call_service", "Call service"))
    results.append(test_import("app.services.live_call_handler", "Live call handler"))
    results.append(test_import("app.handlers.call_handler", "Call handler"))
    results.append(test_import("app.handlers.ari_event_handler", "ARI event handler"))
    
    # ======================================================================
    # AUDIO & TRANSPORT
    # ======================================================================
    log.info("\n[5] AUDIO & TRANSPORT MODULES")
    log.info("-" * 70)
    results.append(test_import("app.audio.noise_suppression", "Noise suppression"))
    results.append(test_import("app.audio.semantic_endpointing", "Semantic endpointing"))
    results.append(test_import("app.transport.asterisk", "Asterisk transport"))
    results.append(test_import("app.transport.rtp", "RTP transport"))
    
    # ======================================================================
    # API ROUTES
    # ======================================================================
    log.info("\n[6] API ROUTES")
    log.info("-" * 70)
    results.append(test_import("app.api.health", "Health API"))
    results.append(test_import("app.api.call", "Call API"))
    results.append(test_import("app.api.ai", "AI API"))
    
    # ======================================================================
    # MAIN APP
    # ======================================================================
    log.info("\n[7] MAIN APPLICATION")
    log.info("-" * 70)
    results.append(test_import("app.main", "Main application"))
    
    # ======================================================================
    # SUMMARY
    # ======================================================================
    log.info("\n" + "=" * 70)
    passed = sum(results)
    total = len(results)
    percentage = (passed / total * 100) if total > 0 else 0
    
    if passed == total:
        log.info(f"✅ ALL TESTS PASSED: {passed}/{total} ({percentage:.1f}%)")
        log.info("=" * 70)
        return 0
    else:
        log.error(f"❌ SOME TESTS FAILED: {passed}/{total} ({percentage:.1f}%)")
        log.info("=" * 70)
        return 1

if __name__ == "__main__":
    sys.exit(main())
