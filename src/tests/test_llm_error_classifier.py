"""
Tests for the LLM error classifier.
"""

import pytest

from podcast_processor.llm_error_classifier import LLMErrorClassifier


class TestLLMErrorClassifier:
    """Test suite for LLMErrorClassifier."""

    def test_rate_limit_errors(self):
        """Test identification of rate limiting errors."""
        rate_limit_errors = [
            "Rate limit exceeded",
            "Too many requests",
            "Quota exceeded",
            "HTTP 429 error",
            "API rate limit hit",
        ]

        for error in rate_limit_errors:
            assert LLMErrorClassifier.is_retryable_error(error)
            assert LLMErrorClassifier.get_error_category(error) == "rate_limit"

    def test_timeout_errors(self):
        """Test identification of timeout errors."""
        timeout_errors = [
            "Request timeout",
            "Connection timed out",
            "HTTP 408 error",
            "HTTP 504 Gateway Timeout",
        ]

        for error in timeout_errors:
            assert LLMErrorClassifier.is_retryable_error(error)
            assert LLMErrorClassifier.get_error_category(error) == "timeout"

    def test_server_errors(self):
        """Test identification of server errors."""
        server_errors = [
            "Internal server error",
            "HTTP 500 error",
            "HTTP 502 Bad Gateway",
            "HTTP 503 Service Unavailable",
        ]

        for error in server_errors:
            assert LLMErrorClassifier.is_retryable_error(error)
            assert LLMErrorClassifier.get_error_category(error) == "server_error"

    def test_non_retryable_errors(self):
        """Test identification of non-retryable errors."""
        non_retryable_errors = [
            "Authentication failed",
            "Invalid API key",
            "Authorization denied",
            "HTTP 401 Unauthorized",
            "HTTP 403 Forbidden",
            "HTTP 400 Bad Request",
        ]

        for error in non_retryable_errors:
            assert not LLMErrorClassifier.is_retryable_error(error)
            category = LLMErrorClassifier.get_error_category(error)
            assert category in ["auth_error", "client_error"]

    def test_auth_vs_client_errors(self):
        """Test distinction between auth errors and other client errors."""
        auth_errors = [
            "Authentication failed",
            "Authorization denied",
            "HTTP 401 error",
            "HTTP 403 error",
        ]

        for error in auth_errors:
            assert LLMErrorClassifier.get_error_category(error) == "auth_error"

        client_errors = [
            "HTTP 400 Bad Request",
            "Invalid parameter",
        ]

        for error in client_errors:
            assert LLMErrorClassifier.get_error_category(error) == "client_error"

    def test_unknown_errors(self):
        """Test handling of unknown error types."""
        unknown_errors = [
            "Something weird happened",
            "Unexpected error",
            "HTTP 418 I'm a teapot",
        ]

        for error in unknown_errors:
            assert not LLMErrorClassifier.is_retryable_error(error)
            assert LLMErrorClassifier.get_error_category(error) == "unknown"

    def test_suggested_backoff(self):
        """Test suggested backoff times for different error types."""
        # Rate limit errors should have longer backoff
        rate_limit_backoff = LLMErrorClassifier.get_suggested_backoff(
            "Rate limit exceeded", 1
        )
        server_error_backoff = LLMErrorClassifier.get_suggested_backoff(
            "Internal server error", 1
        )
        assert rate_limit_backoff > server_error_backoff

        # Timeout errors should have moderate backoff
        timeout_backoff = LLMErrorClassifier.get_suggested_backoff("Request timeout", 1)
        assert timeout_backoff > server_error_backoff
        assert timeout_backoff < rate_limit_backoff

        # Backoff should increase with attempt number
        backoff_attempt_1 = LLMErrorClassifier.get_suggested_backoff(
            "Rate limit exceeded", 1
        )
        backoff_attempt_2 = LLMErrorClassifier.get_suggested_backoff(
            "Rate limit exceeded", 2
        )
        assert backoff_attempt_2 > backoff_attempt_1

    def test_exception_objects(self):
        """Test handling of actual exception objects."""
        try:
            # Test with a basic exception since LiteLLM constructor may vary
            error = Exception("Internal server error")
            assert LLMErrorClassifier.is_retryable_error(error)

            # Test with a more specific pattern
            server_error_msg = "HTTP 500 Internal Server Error"
            assert LLMErrorClassifier.is_retryable_error(server_error_msg)
        except ImportError:
            # Skip if litellm not available
            pytest.skip("litellm not available")

    def test_case_insensitive_matching(self):
        """Test that error classification is case insensitive."""
        assert LLMErrorClassifier.is_retryable_error("RATE LIMIT EXCEEDED")
        assert LLMErrorClassifier.is_retryable_error("Rate Limit Exceeded")
        assert LLMErrorClassifier.is_retryable_error("rate limit exceeded")

        assert not LLMErrorClassifier.is_retryable_error("AUTHENTICATION FAILED")
        assert not LLMErrorClassifier.is_retryable_error("Authentication Failed")
        assert not LLMErrorClassifier.is_retryable_error("authentication failed")
