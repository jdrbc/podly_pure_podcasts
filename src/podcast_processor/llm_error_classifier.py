"""
Enhanced error classification for LLM API calls.

Provides more robust and extensible error handling beyond simple string matching.
"""

import re
from typing import Union

from litellm.exceptions import InternalServerError


class LLMErrorClassifier:
    """Classifies LLM API errors into retryable and non-retryable categories."""

    # Rate limiting error patterns
    RATE_LIMIT_PATTERNS = [
        re.compile(r"rate.?limit", re.IGNORECASE),
        re.compile(r"too many requests", re.IGNORECASE),
        re.compile(r"quota.?exceeded", re.IGNORECASE),
        re.compile(r"429", re.IGNORECASE),  # HTTP 429 status
    ]

    # Timeout error patterns
    TIMEOUT_PATTERNS = [
        re.compile(r"timeout", re.IGNORECASE),
        re.compile(r"timed.?out", re.IGNORECASE),
        re.compile(r"408", re.IGNORECASE),  # HTTP 408 status
        re.compile(r"504", re.IGNORECASE),  # HTTP 504 status
    ]

    # Server error patterns (retryable)
    SERVER_ERROR_PATTERNS = [
        re.compile(r"internal.?server.?error", re.IGNORECASE),
        re.compile(r"502", re.IGNORECASE),  # Bad Gateway
        re.compile(r"503", re.IGNORECASE),  # Service Unavailable
        re.compile(r"500", re.IGNORECASE),  # Internal Server Error
    ]

    # Non-retryable error patterns
    NON_RETRYABLE_PATTERNS = [
        re.compile(r"authentication", re.IGNORECASE),
        re.compile(r"authorization", re.IGNORECASE),
        re.compile(r"invalid.?api.?key", re.IGNORECASE),
        re.compile(r"401", re.IGNORECASE),  # Unauthorized
        re.compile(r"403", re.IGNORECASE),  # Forbidden
        re.compile(r"400", re.IGNORECASE),  # Bad Request
        re.compile(r"invalid.?parameter", re.IGNORECASE),
    ]

    @classmethod
    def is_retryable_error(cls, error: Union[Exception, str]) -> bool:
        """
        Determine if an error should be retried.

        Args:
            error: Exception instance or error string

        Returns:
            True if the error should be retried, False otherwise
        """
        # Handle specific exception types
        if isinstance(error, InternalServerError):
            return True

        # Convert to string for pattern matching
        error_str = str(error)

        # Check for non-retryable errors first (higher priority)
        if cls._matches_patterns(error_str, cls.NON_RETRYABLE_PATTERNS):
            return False

        # Check for retryable error patterns
        retryable_patterns = (
            cls.RATE_LIMIT_PATTERNS + cls.TIMEOUT_PATTERNS + cls.SERVER_ERROR_PATTERNS
        )

        return cls._matches_patterns(error_str, retryable_patterns)

    @classmethod
    def get_error_category(cls, error: Union[Exception, str]) -> str:
        """
        Categorize the error type for better handling.

        Returns:
            One of: 'rate_limit', 'timeout', 'server_error', 'auth_error', 'client_error', 'unknown'
        """
        error_str = str(error)

        if cls._matches_patterns(error_str, cls.RATE_LIMIT_PATTERNS):
            return "rate_limit"
        if cls._matches_patterns(error_str, cls.TIMEOUT_PATTERNS):
            return "timeout"
        if cls._matches_patterns(error_str, cls.SERVER_ERROR_PATTERNS):
            return "server_error"
        if cls._matches_patterns(error_str, cls.NON_RETRYABLE_PATTERNS):
            if any(
                pattern.search(error_str)
                for pattern in [
                    re.compile(r"authentication", re.IGNORECASE),
                    re.compile(r"authorization", re.IGNORECASE),
                    re.compile(r"401", re.IGNORECASE),
                    re.compile(r"403", re.IGNORECASE),
                ]
            ):
                return "auth_error"
            return "client_error"
        return "unknown"

    @classmethod
    def get_suggested_backoff(cls, error: Union[Exception, str], attempt: int) -> float:
        """
        Get suggested backoff time based on error type and attempt number.

        Args:
            error: The error that occurred
            attempt: Current attempt number (0-based)

        Returns:
            Suggested backoff time in seconds
        """
        category = cls.get_error_category(error)
        base_backoff = float(2**attempt)  # Exponential backoff

        # Adjust based on error type
        if category == "rate_limit":
            return base_backoff * 2.0  # Longer backoff for rate limits
        if category == "timeout":
            return base_backoff * 1.5  # Moderate backoff for timeouts
        if category == "server_error":
            return base_backoff  # Standard backoff for server errors
        return base_backoff

    @staticmethod
    def _matches_patterns(text: str, patterns: list[re.Pattern[str]]) -> bool:
        """Check if text matches any of the provided regex patterns."""
        return any(pattern.search(text) for pattern in patterns)
