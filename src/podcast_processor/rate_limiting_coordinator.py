"""
Unified rate limiting coordinator for LLM API calls.

This module provides a single point of control for all rate limiting concerns,
making the system more maintainable and easier to configure.
"""

import logging
from typing import Any, Dict, List, Optional

from podcast_processor.llm_concurrency_limiter import (
    ConcurrencyContext,
    LLMConcurrencyLimiter,
    get_concurrency_limiter,
)
from podcast_processor.token_rate_limiter import (
    TokenRateLimiter,
    configure_rate_limiter_for_model,
    get_rate_limiter,
)
from shared.config import Config

logger = logging.getLogger(__name__)


class LLMRateLimitingCoordinator:
    """
    Coordinates all rate limiting concerns for LLM API calls.

    This class provides a unified interface for:
    - Token-based rate limiting
    - Concurrency control
    - Per-call token validation
    - Usage statistics and monitoring
    """

    def __init__(
        self, config: Config, logger_instance: Optional[logging.Logger] = None
    ):
        """
        Initialize the rate limiting coordinator.

        Args:
            config: Application configuration
            logger_instance: Optional logger instance
        """
        self.config = config
        self.logger = logger_instance or logger

        # Initialize token rate limiter
        self.token_limiter: Optional[TokenRateLimiter] = None
        if config.llm_enable_token_rate_limiting:
            self._initialize_token_limiter()

        # Initialize concurrency limiter
        self.concurrency_limiter: Optional[LLMConcurrencyLimiter] = None
        if getattr(config, "llm_max_concurrent_calls", 3) > 0:
            self._initialize_concurrency_limiter()

        self.logger.info(
            f"Rate limiting coordinator initialized: "
            f"token_limiting={self.token_limiter is not None}, "
            f"concurrency_limiting={self.concurrency_limiter is not None}"
        )

    def _initialize_token_limiter(self) -> None:
        """Initialize the token rate limiter."""
        tokens_per_minute = self.config.llm_max_input_tokens_per_minute
        if tokens_per_minute is None:
            self.token_limiter = configure_rate_limiter_for_model(self.config.llm_model)
        else:
            self.token_limiter = get_rate_limiter(tokens_per_minute)
            self.logger.info(f"Using custom token rate limit: {tokens_per_minute}/min")

    def _initialize_concurrency_limiter(self) -> None:
        """Initialize the concurrency limiter."""
        max_concurrent = getattr(self.config, "llm_max_concurrent_calls", 3)
        self.concurrency_limiter = get_concurrency_limiter(max_concurrent)
        self.logger.info(
            f"LLM concurrency limiting: max {max_concurrent} concurrent calls"
        )

    def validate_per_call_token_limit(
        self, messages: List[Dict[str, str]], model: str
    ) -> tuple[bool, Optional[str]]:
        """
        Validate that messages don't exceed per-call token limit.

        Returns:
            Tuple of (is_valid, error_message)
        """
        if self.config.llm_max_input_tokens_per_call is None:
            return True, None

        if self.token_limiter:
            token_count = self.token_limiter.count_tokens(messages, model)
        else:
            # Fallback estimation
            total_chars = sum(len(msg.get("content", "")) for msg in messages)
            token_count = total_chars // 4

        if token_count <= self.config.llm_max_input_tokens_per_call:
            return True, None

        error_msg = (
            f"Messages exceed token limit: {token_count} > "
            f"{self.config.llm_max_input_tokens_per_call}"
        )
        return False, error_msg

    def prepare_for_api_call(
        self, messages: List[Dict[str, str]], model: str, call_id: Optional[str] = None
    ) -> tuple[bool, Optional[str]]:
        """
        Prepare for an API call by applying all rate limiting checks.

        Returns:
            Tuple of (can_proceed, error_message)
        """
        # 1. Validate per-call token limit
        is_valid, error_msg = self.validate_per_call_token_limit(messages, model)
        if not is_valid:
            return False, error_msg

        # 2. Apply token rate limiting (includes waiting if needed)
        if self.token_limiter:
            self.token_limiter.wait_if_needed(messages, model)

            # Log usage statistics
            usage_stats = self.token_limiter.get_usage_stats()
            call_info = f" for call {call_id}" if call_id else ""
            self.logger.info(
                f"Token usage: {usage_stats['current_usage']}/{usage_stats['limit']} "
                f"({usage_stats['usage_percentage']:.1f}%){call_info}"
            )

        return True, None

    def get_concurrency_context(
        self, timeout: float = 30.0
    ) -> Optional[ConcurrencyContext]:
        """
        Get a concurrency context manager for the API call.

        Returns:
            ConcurrencyContext if concurrency limiting is enabled, None otherwise
        """
        if self.concurrency_limiter:
            return ConcurrencyContext(self.concurrency_limiter, timeout=timeout)
        return None

    def get_usage_statistics(self) -> Dict[str, Any]:
        """Get comprehensive usage statistics."""
        stats = {}

        if self.token_limiter:
            stats["token_usage"] = self.token_limiter.get_usage_stats()

        if self.concurrency_limiter:
            stats["concurrency"] = {
                "max_concurrent": self.concurrency_limiter.max_concurrent_calls,
                "available_slots": self.concurrency_limiter.get_available_slots(),
                "active_calls": self.concurrency_limiter.get_active_calls(),
            }

        return stats
