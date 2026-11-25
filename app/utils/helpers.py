"""
Helper Utilities
Miscellaneous utility functions for common operations
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict

from ..core.config import log

def json_dumps(obj: Any) -> str:
    """JSON dump with datetime handling"""
    try:
        def json_serializer(obj):
            if isinstance(obj, datetime):
                return obj.isoformat()
            raise TypeError(f"Type {type(obj)} not serializable")

        return json.dumps(obj, default=json_serializer)
    except Exception as e:
        log.error(f"[Utils] JSON serialization error: {e}")
        return "{}"

def json_loads(data: str) -> Dict:
    """JSON load with error handling"""
    try:
        return json.loads(data)
    except Exception as e:
        log.error(f"[Utils] JSON deserialization error: {e}")
        return {}

def generate_call_id(user_id: int, caller_number: str, timestamp: float = None) -> str:
    """Generate unique call ID"""
    import time
    if timestamp is None:
        timestamp = time.time()

    ts_ms = int(timestamp * 1000)
    return f"call_{user_id}_{caller_number}_{ts_ms}"

def sanitize_phone_number(number: str) -> str:
    """Sanitize phone number - extract digits only"""
    import re
    if not number:
        return ""

    digits = re.sub(r'\D', '', number)

    return digits[-10:] if len(digits) >= 10 else digits

def format_duration(seconds: int) -> str:
    """Format duration in seconds to readable format"""
    if seconds < 0:
        return "0s"

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    elif minutes > 0:
        return f"{minutes}m {secs}s"
    else:
        return f"{secs}s"

def truncate_text(text: str, max_length: int = 100) -> str:
    """Truncate text to max length"""
    if not text:
        return ""

    if len(text) <= max_length:
        return text

    return text[:max_length - 3] + "..."

def normalize_text(text: str) -> str:
    """Normalize text for processing"""
    if not text:
        return ""

    import re

    text = text.lower()

    text = re.sub(r'\s+', ' ', text)

    text = text.strip()

    return text

def get_timestamp_ms() -> int:
    """Get current timestamp in milliseconds"""
    import time
    return int(time.time() * 1000)

def get_timestamp_s() -> int:
    """Get current timestamp in seconds"""
    import time
    return int(time.time())

def log_operation(operation: str, duration_ms: float, success: bool = True, **kwargs):
    """Log an operation with timing"""
    status = "✓" if success else "✗"
    extra = " ".join(f"{k}={v}" for k, v in kwargs.items()) if kwargs else ""

    log.info(f"[Operation] {status} {operation} ({duration_ms:.0f}ms) {extra}")
