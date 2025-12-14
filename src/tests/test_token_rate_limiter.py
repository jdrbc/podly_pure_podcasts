"""
Tests for the TokenRateLimiter class and related functionality.
"""

import threading
import time
from unittest.mock import patch

from podcast_processor.token_rate_limiter import (
    TokenRateLimiter,
    configure_rate_limiter_for_model,
    get_rate_limiter,
)


class TestTokenRateLimiter:
    """Test cases for the TokenRateLimiter class."""

    def test_initialization(self) -> None:
        """Test rate limiter initialization with default and custom parameters."""
        # Test default initialization
        limiter = TokenRateLimiter()
        assert limiter.tokens_per_minute == 30000
        assert limiter.window_seconds == 60
        assert len(limiter.token_usage) == 0

        # Test custom initialization
        limiter = TokenRateLimiter(tokens_per_minute=15000, window_minutes=2)
        assert limiter.tokens_per_minute == 15000
        assert limiter.window_seconds == 120

    def test_count_tokens(self) -> None:
        """Test token counting functionality."""
        limiter = TokenRateLimiter()

        # Test empty messages
        messages: list[dict[str, str]] = []
        tokens = limiter.count_tokens(messages, "gpt-4")
        assert tokens == 0

        # Test single message
        messages = [{"role": "user", "content": "Hello world"}]
        tokens = limiter.count_tokens(messages, "gpt-4")
        assert tokens > 0  # Should estimate some tokens

        # Test multiple messages
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "What is the weather like today?"},
        ]
        tokens = limiter.count_tokens(messages, "gpt-4")
        assert tokens > 0

    def test_token_counting_fallback(self) -> None:
        """Test token counting fallback on error."""
        limiter = TokenRateLimiter()

        # Test with malformed message (should use fallback)
        messages: list[dict[str, str]] = [{"role": "user"}]  # Missing content
        tokens = limiter.count_tokens(messages, "gpt-4")
        assert tokens == 0  # Should return 0 for missing content

    def test_cleanup_old_usage(self) -> None:
        """Test cleanup of old token usage records."""
        limiter = TokenRateLimiter(tokens_per_minute=1000, window_minutes=1)

        current_time = time.time()

        # Add some old usage records
        limiter.token_usage.append((current_time - 120, 100))  # 2 minutes ago
        limiter.token_usage.append((current_time - 30, 200))  # 30 seconds ago
        limiter.token_usage.append((current_time - 10, 300))  # 10 seconds ago

        # Cleanup should remove the 2-minute-old record
        limiter._cleanup_old_usage(current_time)

        assert len(limiter.token_usage) == 2
        assert limiter.token_usage[0][1] == 200  # 30 seconds ago should remain
        assert limiter.token_usage[1][1] == 300  # 10 seconds ago should remain

    def test_get_current_usage(self) -> None:
        """Test getting current token usage within time window."""
        limiter = TokenRateLimiter(tokens_per_minute=1000, window_minutes=1)

        current_time = time.time()

        # Add usage records
        limiter.token_usage.append((current_time - 120, 100))  # Outside window
        limiter.token_usage.append((current_time - 30, 200))  # Within window
        limiter.token_usage.append((current_time - 10, 300))  # Within window

        usage = limiter._get_current_usage(current_time)
        assert usage == 500  # 200 + 300 (only records within window)

    def test_check_rate_limit_within_limits(self) -> None:
        """Test rate limit check when within limits."""
        limiter = TokenRateLimiter(tokens_per_minute=1000)

        messages: list[dict[str, str]] = [{"role": "user", "content": "Short message"}]
        can_proceed, wait_seconds = limiter.check_rate_limit(messages, "gpt-4")

        assert can_proceed is True
        assert wait_seconds == 0.0

    def test_check_rate_limit_exceeds_limits(self) -> None:
        """Test rate limit check when exceeding limits."""
        limiter = TokenRateLimiter(tokens_per_minute=100)  # Very low limit

        current_time = time.time()

        # Add usage that nearly fills the limit
        limiter.token_usage.append((current_time - 30, 90))

        # Try to add more tokens that would exceed the limit
        messages: list[dict[str, str]] = [
            {
                "role": "user",
                "content": "This is a longer message that should exceed the token limit",
            }
        ]
        can_proceed, wait_seconds = limiter.check_rate_limit(messages, "gpt-4")

        assert can_proceed is False
        assert wait_seconds > 0

    def test_record_usage(self) -> None:
        """Test recording token usage."""
        limiter = TokenRateLimiter()

        messages: list[dict[str, str]] = [{"role": "user", "content": "Test message"}]
        initial_count = len(limiter.token_usage)

        limiter.record_usage(messages, "gpt-4")

        assert len(limiter.token_usage) == initial_count + 1
        timestamp, token_count = limiter.token_usage[-1]
        assert timestamp > 0
        assert token_count > 0

    def test_wait_if_needed_no_wait(self) -> None:
        """Test wait_if_needed when no waiting is required."""
        limiter = TokenRateLimiter(tokens_per_minute=10000)  # High limit

        messages: list[dict[str, str]] = [{"role": "user", "content": "Short message"}]
        start_time = time.time()

        limiter.wait_if_needed(messages, "gpt-4")

        end_time = time.time()
        elapsed = end_time - start_time

        # Should not have waited significantly
        assert elapsed < 1.0

        # Should have recorded usage
        assert len(limiter.token_usage) > 0

    def test_wait_if_needed_with_wait(self) -> None:
        """Test wait_if_needed when waiting is required."""
        limiter = TokenRateLimiter(tokens_per_minute=50)  # Very low limit

        # Fill up the rate limit
        current_time = time.time()
        limiter.token_usage.append((current_time - 10, 45))

        messages: list[dict[str, str]] = [
            {"role": "user", "content": "This message should trigger waiting"}
        ]

        # Mock time.sleep to avoid actual waiting in tests
        with patch("time.sleep") as mock_sleep:
            limiter.wait_if_needed(messages, "gpt-4")

            # Should have called sleep
            mock_sleep.assert_called_once()
            call_args = mock_sleep.call_args[0]
            assert call_args[0] > 0  # Should have waited some positive amount

    def test_get_usage_stats(self) -> None:
        """Test getting usage statistics."""
        limiter = TokenRateLimiter(tokens_per_minute=1000)

        # Add some usage
        current_time = time.time()
        limiter.token_usage.append((current_time - 30, 200))
        limiter.token_usage.append((current_time - 10, 300))

        stats = limiter.get_usage_stats()

        assert "current_usage" in stats
        assert "limit" in stats
        assert "usage_percentage" in stats
        assert "window_seconds" in stats
        assert "active_records" in stats

        assert stats["current_usage"] == 500
        assert stats["limit"] == 1000
        assert stats["usage_percentage"] == 50.0
        assert stats["window_seconds"] == 60
        assert stats["active_records"] == 2

    def test_thread_safety(self) -> None:
        """Test that the rate limiter is thread-safe."""
        limiter = TokenRateLimiter(tokens_per_minute=10000)
        messages: list[dict[str, str]] = [{"role": "user", "content": "Test message"}]

        def worker() -> None:
            for _ in range(10):
                limiter.wait_if_needed(messages, "gpt-4")

        # Run multiple threads concurrently
        threads = []
        for _ in range(5):
            thread = threading.Thread(target=worker)
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # Should have recorded usage from all threads
        assert len(limiter.token_usage) == 50  # 5 threads * 10 calls each


class TestGlobalRateLimiter:
    """Test cases for global rate limiter functions."""

    def test_get_rate_limiter_singleton(self) -> None:
        """Test that get_rate_limiter returns the same instance."""
        limiter1 = get_rate_limiter(5000)
        limiter2 = get_rate_limiter(5000)

        assert limiter1 is limiter2  # Should be the same instance
        assert limiter1.tokens_per_minute == 5000

    def test_get_rate_limiter_different_limits(self) -> None:
        """Test that get_rate_limiter creates new instance for different limits."""
        limiter1 = get_rate_limiter(5000)
        limiter2 = get_rate_limiter(8000)

        assert limiter1 is not limiter2  # Should be different instances
        assert limiter1.tokens_per_minute == 5000
        assert limiter2.tokens_per_minute == 8000

    def test_configure_rate_limiter_for_model_anthropic(self) -> None:
        """Test model-specific configuration for Anthropic models."""
        limiter = configure_rate_limiter_for_model(
            "anthropic/claude-3-5-sonnet-20240620"
        )
        assert limiter.tokens_per_minute == 30000

    def test_configure_rate_limiter_for_model_openai(self) -> None:
        """Test model-specific configuration for OpenAI models."""
        # Test each model in isolation to avoid singleton issues
        import podcast_processor.token_rate_limiter as trl_module

        # Test gpt-4o-mini first (higher limit)
        trl_module._RATE_LIMITER = None
        limiter = configure_rate_limiter_for_model("gpt-4o-mini")
        assert limiter.tokens_per_minute == 200000

        # Test gpt-4o (lower limit)
        trl_module._RATE_LIMITER = None
        limiter = configure_rate_limiter_for_model("gpt-4o")
        assert limiter.tokens_per_minute == 150000

    def test_configure_rate_limiter_for_model_gemini(self) -> None:
        """Test model-specific configuration for Gemini models."""
        limiter = configure_rate_limiter_for_model("gemini/gemini-2.5-flash")
        assert limiter.tokens_per_minute == 60000

    def test_configure_rate_limiter_for_model_unknown(self) -> None:
        """Test model-specific configuration for unknown models."""
        limiter = configure_rate_limiter_for_model("unknown/model-name")
        assert limiter.tokens_per_minute == 30000  # Should use default

    def test_configure_rate_limiter_partial_match(self) -> None:
        """Test model-specific configuration with partial model names."""
        # Test that partial matches work
        limiter = configure_rate_limiter_for_model("some-prefix/gpt-4o/some-suffix")
        assert limiter.tokens_per_minute == 150000  # Should match gpt-4o
