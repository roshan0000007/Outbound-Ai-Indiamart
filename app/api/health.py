"""
Health Check API Routes
Endpoints for system health monitoring
"""

from fastapi import APIRouter, status
from datetime import datetime

from ..core.config import log

router = APIRouter(prefix="/api/health", tags=["health"])

@router.get("/ping")
async def ping():
    """Simple ping endpoint"""
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat()
    }

@router.get("/ready", status_code=status.HTTP_200_OK)
async def readiness_check():
    """Readiness probe for Kubernetes"""
    try:
        checks = {
            "api": "ok",
            "timestamp": datetime.utcnow().isoformat()
        }

        return checks
    except Exception as e:
        log.error(f"[Health] Readiness check failed: {e}")
        return {
            "status": "not_ready",
            "error": str(e)
        }, status.HTTP_503_SERVICE_UNAVAILABLE

@router.get("/live", status_code=status.HTTP_200_OK)
async def liveness_check():
    """Liveness probe for Kubernetes"""
    return {
        "status": "alive",
        "timestamp": datetime.utcnow().isoformat()
    }

@router.get("/metrics")
async def get_metrics():
    """Get system metrics"""
    try:
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "metrics": {
                "cpu_usage": "N/A",
                "memory_usage": "N/A",
                "active_calls": 0,
                "uptime_seconds": 0
            }
        }
    except Exception as e:
        log.error(f"[Health] Metrics error: {e}")
        raise
