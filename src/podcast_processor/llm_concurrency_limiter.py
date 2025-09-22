"""
LLM concurrency limiter to control the number of simultaneous LLM API calls.

This module provides a semaphore-based concurrency control mechanism to prevent
too many simultaneous LLM API calls, which can help avoid rate limiting and
improve system stability.
"""

import logging
import threading
from typing import Any, Optional

logger = logging.getLogger(__name__)


class LLMConcurrencyLimiter:
    """Controls the number of concurrent LLM API calls using a semaphore."""

    def __init__(self, max_concurrent_calls: int):
        """
        Initialize the concurrency limiter.

        Args:
            max_concurrent_calls: Maximum number of simultaneous LLM API calls allowed
        """
        if max_concurrent_calls <= 0:
            raise ValueError("max_concurrent_calls must be greater than 0")

        self.max_concurrent_calls = max_concurrent_calls
        self._semaphore = threading.Semaphore(max_concurrent_calls)

        logger.info(
            f"LLM concurrency limiter initialized with {max_concurrent_calls} max concurrent calls"
        )

    def acquire(self, timeout: Optional[float] = None) -> bool:
        """
        Acquire a slot for making an LLM API call.

        Note: Consider using ConcurrencyContext for automatic resource management.

        Args:
            timeout: Maximum time to wait for a slot in seconds. None means wait indefinitely.

        Returns:
            True if a slot was acquired, False if timeout occurred
        """
        # Disable specific pylint warning for this line as manual semaphore control is needed
        acquired = self._semaphore.acquire(  # pylint: disable=consider-using-with
            timeout=timeout
        )
        if acquired:
            logger.debug("Acquired LLM concurrency slot")
        else:
            logger.warning(
                f"Failed to acquire LLM concurrency slot within {timeout}s timeout"
            )
        return acquired

    def release(self) -> None:
        """
        Release a slot after completing an LLM API call.

        Note: Consider using ConcurrencyContext for automatic resource management.
        """
        self._semaphore.release()
        logger.debug("Released LLM concurrency slot")

    def get_available_slots(self) -> int:
        """Get the number of currently available slots."""
        return self._semaphore._value

    def get_active_calls(self) -> int:
        """Get the number of currently active LLM calls."""
        return self.max_concurrent_calls - self._semaphore._value


# Global concurrency limiter instance
_concurrency_limiter: Optional[LLMConcurrencyLimiter] = None


def get_concurrency_limiter(max_concurrent_calls: int = 3) -> LLMConcurrencyLimiter:
    """Get or create the global concurrency limiter instance."""
    global _concurrency_limiter  # pylint: disable=global-statement
    if (
        _concurrency_limiter is None
        or _concurrency_limiter.max_concurrent_calls != max_concurrent_calls
    ):
        _concurrency_limiter = LLMConcurrencyLimiter(max_concurrent_calls)
    return _concurrency_limiter


class ConcurrencyContext:
    """Context manager for controlling LLM API call concurrency."""

    def __init__(self, limiter: LLMConcurrencyLimiter, timeout: Optional[float] = None):
        """
        Initialize the context manager.

        Args:
            limiter: The concurrency limiter to use
            timeout: Maximum time to wait for a slot
        """
        self.limiter = limiter
        self.timeout = timeout
        self.acquired = False

    def __enter__(self) -> "ConcurrencyContext":
        """Acquire a concurrency slot."""
        self.acquired = self.limiter.acquire(timeout=self.timeout)
        if not self.acquired:
            raise RuntimeError(
                f"Could not acquire LLM concurrency slot within {self.timeout}s"
            )
        return self

    def __exit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[BaseException],
        exc_tb: Optional[Any],
    ) -> None:
        """Release the concurrency slot."""
        if self.acquired:
            self.limiter.release()
