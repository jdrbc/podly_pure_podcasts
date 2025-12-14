"""
Token-based rate limiting for LLM API calls.

This module provides client-side rate limiting based on input token consumption
to prevent hitting API provider rate limits (e.g., Anthropic's 30,000 tokens/minute).
"""

import logging
import threading
import time
from collections import deque
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)


class TokenRateLimiter:
    """
    Client-side rate limiter that tracks token usage over time windows.

    Prevents hitting API rate limits by calculating token usage and waiting
    when necessary before making API calls.
    """

    def __init__(self, tokens_per_minute: int = 30000, window_minutes: int = 1):
        """
        Initialize the rate limiter.

        Args:
            tokens_per_minute: Maximum tokens allowed per minute
            window_minutes: Time window for rate limiting (default: 1 minute)
        """
        self.tokens_per_minute = tokens_per_minute
        self.window_seconds = window_minutes * 60
        self.token_usage: deque[Tuple[float, int]] = (
            deque()
        )  # [(timestamp, token_count), ...]
        self.lock = threading.Lock()

        logger.info(
            f"Initialized TokenRateLimiter: {tokens_per_minute} tokens/{window_minutes}min"
        )

    def count_tokens(self, messages: List[Dict[str, str]], model: str) -> int:
        """
        Count tokens in messages using litellm's token counting.

        Args:
            messages: List of message dicts with 'role' and 'content'
            model: Model name for accurate token counting

        Returns:
            Number of input tokens
        """
        try:
            # Simple token estimation: ~4 characters per token
            total_chars = sum(len(msg.get("content", "")) for msg in messages)
            estimated_tokens = total_chars // 4
            logger.debug(f"Estimated {estimated_tokens} tokens for model {model}")
            return estimated_tokens
        except Exception as e:
            # Fallback: conservative estimate
            logger.warning(f"Token counting failed, using fallback. Error: {e}")
            return 1000  # Conservative fallback

    def _cleanup_old_usage(self, current_time: float) -> None:
        """Remove token usage records outside the time window."""
        cutoff_time = current_time - self.window_seconds
        while self.token_usage and self.token_usage[0][0] < cutoff_time:
            self.token_usage.popleft()

    def _get_current_usage(self, current_time: float) -> int:
        """Get total token usage within the current time window."""
        self._cleanup_old_usage(current_time)
        return sum(count for _, count in self.token_usage)

    def check_rate_limit(
        self, messages: List[Dict[str, str]], model: str
    ) -> Tuple[bool, float]:
        """
        Check if we can make an API call without hitting rate limits.

        Args:
            messages: Messages to send to the API
            model: Model name

        Returns:
            Tuple of (can_proceed, wait_seconds)
            - can_proceed: True if call can be made immediately
            - wait_seconds: Seconds to wait if can_proceed is False
        """
        token_count = self.count_tokens(messages, model)
        current_time = time.time()

        with self.lock:
            current_usage = self._get_current_usage(current_time)

            # Check if adding this request would exceed the limit
            if current_usage + token_count <= self.tokens_per_minute:
                return True, 0.0

            # Calculate wait time: find when oldest tokens will expire
            if not self.token_usage:
                return True, 0.0

            oldest_time = self.token_usage[0][0]
            wait_seconds = (oldest_time + self.window_seconds) - current_time
            wait_seconds = max(0, wait_seconds)

            logger.info(
                f"Rate limit check: current={current_usage}, "
                f"requested={token_count}, "
                f"limit={self.tokens_per_minute}, "
                f"wait={wait_seconds:.1f}s"
            )

            return False, wait_seconds

    def record_usage(self, messages: List[Dict[str, str]], model: str) -> None:
        """
        Record token usage for a successful API call.

        Args:
            messages: Messages that were sent to the API
            model: Model name that was used
        """
        token_count = self.count_tokens(messages, model)
        current_time = time.time()

        with self.lock:
            self.token_usage.append((current_time, token_count))
            logger.debug(
                f"Recorded {token_count} tokens at {datetime.fromtimestamp(current_time)}"
            )

    def wait_if_needed(self, messages: List[Dict[str, str]], model: str) -> None:
        """
        Wait if necessary to avoid hitting rate limits, then record usage.

        Args:
            messages: Messages to send to the API
            model: Model name
        """
        can_proceed, wait_seconds = self.check_rate_limit(messages, model)

        if not can_proceed and wait_seconds > 0:
            logger.info(
                f"Rate limiting: waiting {wait_seconds:.1f}s to avoid API limits"
            )
            time.sleep(wait_seconds)

        # Record the usage immediately before making the call
        self.record_usage(messages, model)

    def get_usage_stats(self) -> Dict[str, Union[int, float]]:
        """Get current usage statistics."""
        current_time = time.time()
        with self.lock:
            current_usage = self._get_current_usage(current_time)
            usage_percentage = (current_usage / self.tokens_per_minute) * 100

            return {
                "current_usage": current_usage,
                "limit": self.tokens_per_minute,
                "usage_percentage": usage_percentage,
                "window_seconds": self.window_seconds,
                "active_records": len(self.token_usage),
            }


# Global rate limiter instance
_RATE_LIMITER: Optional[TokenRateLimiter] = None  # pylint: disable=invalid-name


def get_rate_limiter(tokens_per_minute: int = 30000) -> TokenRateLimiter:
    """Get or create the global rate limiter instance."""
    global _RATE_LIMITER  # pylint: disable=global-statement
    if _RATE_LIMITER is None or _RATE_LIMITER.tokens_per_minute != tokens_per_minute:
        _RATE_LIMITER = TokenRateLimiter(tokens_per_minute=tokens_per_minute)
    return _RATE_LIMITER


def configure_rate_limiter_for_model(model: str) -> TokenRateLimiter:
    """
    Configure rate limiter with appropriate limits for the given model.

    Args:
        model: Model name (e.g., "anthropic/claude-sonnet-4-20250514")

    Returns:
        Configured TokenRateLimiter instance
    """
    # Model-specific rate limits (tokens per minute)
    model_limits = {
        # Anthropic models
        "anthropic/claude-3-5-sonnet-20240620": 30000,
        "anthropic/claude-sonnet-4-20250514": 30000,
        "anthropic/claude-3-opus-20240229": 30000,
        # OpenAI models
        "gpt-4o-mini": 200000,
        "gpt-4o": 150000,
        "gpt-4": 40000,
        # Google Gemini models
        "gemini/gemini-2.5-flash": 60000,
        "gemini/gemini-2.5-pro": 30000,
    }

    # Extract base model name and find limit
    tokens_per_minute = 30000  # Conservative default
    for model_pattern, limit in model_limits.items():
        if model_pattern in model:
            tokens_per_minute = limit
            break

    logger.info(
        f"Configured rate limiter for {model}: {tokens_per_minute} tokens/minute"
    )
    return get_rate_limiter(tokens_per_minute)
