"""
Production-Quality Error Handling Module
Implements circuit breaker pattern, graceful degradation, and error recovery

**Task 11: Production-Quality Error Handling**

Features:
- Circuit breaker for failing services
- Graceful degradation with fallbacks
- Comprehensive error logging with context
- Error tracking and alerting
- Service health monitoring
"""

import time
import asyncio
from typing import Optional, Callable, Any, Dict
from enum import Enum
from dataclasses import dataclass
from datetime import datetime, timedelta
from ..core.config import log

class CircuitBreakerState(Enum):
    """Circuit breaker states"""
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker"""
    failure_threshold: int = 5
    success_threshold: int = 3
    timeout_seconds: int = 60
    failure_window_seconds: int = 300

class CircuitBreaker:
    """
    Circuit breaker pattern for service resilience
    
    Prevents cascade failures when upstream services are failing.
    """

    def __init__(self, name: str, config: Optional[CircuitBreakerConfig] = None):
        """
        Initialize circuit breaker
        
        Args:
            name: Service name
            config: Configuration (uses defaults if None)
        """
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self.state = CircuitBreakerState.CLOSED
        self.failures = []
        self.successes = 0
        self.last_failure_time = None
        self.last_state_change = datetime.now()
        self.state_change_count = 0

        log.info(f"[CIRCUIT-BREAKER] Initialized for service '{name}'")

    def can_attempt(self) -> bool:
        """
        Check if a request can be attempted
        
        Returns:
            True if request should be attempted, False if circuit is open
        """
        now = datetime.now()

        if self.state == CircuitBreakerState.CLOSED:
            return True

        elif self.state == CircuitBreakerState.OPEN:
            time_since_open = (now - self.last_state_change).total_seconds()

            if time_since_open >= self.config.timeout_seconds:
                self._transition_state(CircuitBreakerState.HALF_OPEN)
                log.info(f"[CIRCUIT-BREAKER] {self.name}: OPEN → HALF_OPEN (timeout expired)")
                return True
            else:
                return False

        elif self.state == CircuitBreakerState.HALF_OPEN:
            return True

        return False

    def record_success(self) -> None:
        """Record successful operation"""
        now = datetime.now()

        cutoff_time = now - timedelta(seconds=self.config.failure_window_seconds)
        self.failures = [f for f in self.failures if f > cutoff_time]

        self.last_failure_time = None
        self.successes += 1

        if self.state == CircuitBreakerState.HALF_OPEN:
            if self.successes >= self.config.success_threshold:
                self._transition_state(CircuitBreakerState.CLOSED)
                log.info(f"[CIRCUIT-BREAKER] {self.name}: HALF_OPEN → CLOSED (service recovered)")
                self.successes = 0

        elif self.state == CircuitBreakerState.OPEN:
            self.successes = 0

    def record_failure(self, error_msg: str = "") -> None:
        """
        Record failed operation
        
        Args:
            error_msg: Error message for logging
        """
        now = datetime.now()
        self.failures.append(now)
        self.last_failure_time = now
        self.successes = 0

        cutoff_time = now - timedelta(seconds=self.config.failure_window_seconds)
        self.failures = [f for f in self.failures if f > cutoff_time]

        recent_failures = len(self.failures)

        log.warning(f"[CIRCUIT-BREAKER] {self.name}: Failure recorded ({recent_failures}/{self.config.failure_threshold})")
        if error_msg:
            log.warning(f"[CIRCUIT-BREAKER]    Error: {error_msg}")

        if recent_failures >= self.config.failure_threshold:
            if self.state != CircuitBreakerState.OPEN:
                self._transition_state(CircuitBreakerState.OPEN)
                log.error(f"[CIRCUIT-BREAKER] {self.name}: CLOSED → OPEN (threshold reached)")
                log.error(f"[CIRCUIT-BREAKER]    Service will reject requests for {self.config.timeout_seconds}s")

    def _transition_state(self, new_state: CircuitBreakerState) -> None:
        """
        Transition to new state
        
        Args:
            new_state: New state
        """
        if self.state != new_state:
            old_state = self.state
            self.state = new_state
            self.last_state_change = datetime.now()
            self.state_change_count += 1

            log.info(f"[CIRCUIT-BREAKER] {self.name}: {old_state.value.upper()} → {new_state.value.upper()}")

    def get_health(self) -> CircuitBreakerState:
        """
        Get current circuit breaker state
        
        Returns:
            Current state
        """
        return self.state

    def reset(self) -> None:
        """Reset circuit breaker to closed state"""
        self._transition_state(CircuitBreakerState.CLOSED)
        self.failures = []
        self.successes = 0
        self.last_failure_time = None
        log.info(f"[CIRCUIT-BREAKER] {self.name}: Reset to CLOSED")

_circuit_breakers: Dict[str, CircuitBreaker] = {}

def get_circuit_breaker(service_name: str) -> CircuitBreaker:
    """
    Get or create circuit breaker for a service
    
    Args:
        service_name: Service name
        
    Returns:
        Circuit breaker instance
    """
    if service_name not in _circuit_breakers:
        _circuit_breakers[service_name] = CircuitBreaker(service_name)
    return _circuit_breakers[service_name]

class ErrorHandler:
    """Centralized error handling with logging and recovery"""

    @staticmethod
    def log_error(
        context: str,
        error: Exception,
        call_id: Optional[str] = None,
        user_id: Optional[int] = None,
        stage: Optional[str] = None,
        severity: str = "error"
    ) -> None:
        """
        Log error with full context
        
        Args:
            context: Error context (e.g., "[TTS] Audio synthesis failed")
            error: Exception object
            call_id: Call ID
            user_id: User ID
            stage: Pipeline stage
            severity: Severity level (debug, info, warning, error, critical)
        """
        error_type = type(error).__name__
        error_msg = str(error)

        context_str = context
        if call_id:
            context_str += f" [call_id={call_id}]"
        if user_id:
            context_str += f" [user_id={user_id}]"
        if stage:
            context_str += f" [stage={stage}]"

        log_func = getattr(log, severity, log.error)
        log_func(f"{context_str}: {error_type}: {error_msg}", exc_info=True)

    @staticmethod
    async def handle_error_with_fallback(
        operation_name: str,
        primary_func: Callable,
        fallback_func: Optional[Callable] = None,
        call_id: Optional[str] = None,
        **kwargs
    ) -> Any:
        """
        Execute operation with fallback on error
        
        Args:
            operation_name: Name of operation (for logging)
            primary_func: Primary async function to execute
            fallback_func: Optional fallback function if primary fails
            call_id: Call ID for context
            **kwargs: Arguments to pass to functions
            
        Returns:
            Result from primary or fallback function
        """
        try:
            log.debug(f"[ERROR-HANDLER] Attempting {operation_name}")
            result = await primary_func(**kwargs) if asyncio.iscoroutinefunction(primary_func) else primary_func(**kwargs)
            log.debug(f"[ERROR-HANDLER] {operation_name} succeeded")
            return result

        except Exception as e:
            log.warning(f"[ERROR-HANDLER] {operation_name} failed: {e}")

            if fallback_func:
                try:
                    log.warning(f"[ERROR-HANDLER] Attempting fallback for {operation_name}")
                    result = await fallback_func(**kwargs) if asyncio.iscoroutinefunction(fallback_func) else fallback_func(**kwargs)
                    log.warning(f"[ERROR-HANDLER] Fallback succeeded for {operation_name}")
                    return result
                except Exception as fallback_error:
                    log.error(f"[ERROR-HANDLER] Fallback also failed for {operation_name}: {fallback_error}")
                    raise
            else:
                raise

def handle_error_with_fallback(
    operation_name: str,
    primary_func: Callable,
    fallback_func: Optional[Callable] = None,
    **kwargs
) -> Any:
    """
    Synchronous wrapper for error handling with fallback
    
    Args:
        operation_name: Name of operation
        primary_func: Primary function
        fallback_func: Optional fallback
        **kwargs: Function arguments
        
    Returns:
        Result from primary or fallback
    """
    try:
        return primary_func(**kwargs)
    except Exception as e:
        log.warning(f"[ERROR-HANDLER] {operation_name} failed: {e}")

        if fallback_func:
            try:
                log.warning(f"[ERROR-HANDLER] Using fallback for {operation_name}")
                return fallback_func(**kwargs)
            except Exception as fallback_error:
                log.error(f"[ERROR-HANDLER] Fallback failed: {fallback_error}")
                raise
        else:
            raise

class ServiceAvailability:
    """Track service availability and health"""

    def __init__(self):
        self.services = {}

    def mark_healthy(self, service_name: str) -> None:
        """Mark service as healthy"""
        self.services[service_name] = {
            "status": "healthy",
            "last_check": datetime.now().isoformat(),
            "failure_count": 0
        }
        log.info(f"[SERVICE-HEALTH] {service_name} is HEALTHY")

    def mark_unhealthy(self, service_name: str, reason: str = "") -> None:
        """Mark service as unhealthy"""
        current = self.services.get(service_name, {})
        failure_count = current.get("failure_count", 0) + 1

        self.services[service_name] = {
            "status": "unhealthy",
            "last_check": datetime.now().isoformat(),
            "failure_count": failure_count,
            "reason": reason
        }
        log.error(f"[SERVICE-HEALTH] {service_name} is UNHEALTHY: {reason}")

    def is_healthy(self, service_name: str) -> bool:
        """Check if service is healthy"""
        return self.services.get(service_name, {}).get("status") == "healthy"

    def get_status(self, service_name: str) -> Dict[str, Any]:
        """Get service status"""
        return self.services.get(service_name, {"status": "unknown"})

_service_availability = ServiceAvailability()

def get_service_availability() -> ServiceAvailability:
    """Get service availability tracker"""
    return _service_availability
