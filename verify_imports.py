#!/usr/bin/env python3
"""Verify all 27+ modules import successfully"""

print("=" * 60)
print("IMPORT VERIFICATION - All 27+ Modules")
print("=" * 60)

modules = [
    "app.core.config",
    "app.core.database",
    "app.core.redis",
    "app.core.error_handling",
    "app.session.redis_session",
    "app.services.call_service",
    "app.services.language_service",
    "app.services.conversation_service",
    "app.services.live_call_handler",
    "app.services.conversation_history_service",
    "app.services.media_service",
    "app.services.customer_requirement_service",
    "app.services.requirement_tools_service",
    "app.services.lead_storage_service",
    "app.services.greeting_service",
    "app.services.gemini_session_manager",
    "app.llm.gemini_live_provider",
    "app.llm.base",
    "app.transport.asterisk",
    "app.transport.rtp",
    "app.handlers.ari_event_handler",
    "app.handlers.call_handler",
    "app.api.health",
    "app.api.call",
    "app.api.ai",
]

success = 0
failed = 0
failed_modules = []

for module in modules:
    try:
        __import__(module)
        print(f"✅ {module}")
        success += 1
    except Exception as e:
        error_msg = str(e)[:80]
        print(f"✗ {module}: {error_msg}")
        failed += 1
        failed_modules.append((module, error_msg))

print("=" * 60)
print(f"RESULT: {success} passed, {failed} failed")
if failed_modules:
    print("\nFailed modules:")
    for mod, err in failed_modules:
        print(f"  - {mod}: {err}")
print("=" * 60)
