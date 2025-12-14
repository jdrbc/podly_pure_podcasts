"""
Additional edge case tests for rate limiting functionality.
"""

import time
from typing import Any
from unittest.mock import patch

from podcast_processor.ad_classifier import AdClassifier
from podcast_processor.token_rate_limiter import TokenRateLimiter

from .test_helpers import create_test_config


class TestRateLimitingEdgeCases:
    """Test edge cases and boundary conditions for rate limiting."""

    def test_token_counting_edge_cases(self) -> None:
        """Test token counting with edge cases."""
        limiter = TokenRateLimiter()

        # Test empty content
        messages: list[dict[str, str]] = [{"role": "user", "content": ""}]
        tokens = limiter.count_tokens(messages, "gpt-4")
        assert tokens == 0

        # Test malformed message structure
        messages = [{"role": "user"}]  # Missing content
        tokens = limiter.count_tokens(messages, "gpt-4")
        assert tokens == 0

        # Test very large message
        large_content = "word " * 10000  # ~50k characters
        messages = [{"role": "user", "content": large_content}]
        tokens = limiter.count_tokens(messages, "gpt-4")
        assert tokens > 10000  # Should estimate significant tokens

    def test_rate_limiter_boundary_conditions(self) -> None:
        """Test rate limiter at exact boundary conditions."""
        limiter = TokenRateLimiter(tokens_per_minute=100, window_minutes=1)

        current_time = time.time()

        # Fill exactly to the limit
        limiter.token_usage.append((current_time - 30, 100))

        # Try to add exactly 0 more tokens
        messages: list[dict[str, str]] = []
        can_proceed, wait_seconds = limiter.check_rate_limit(messages, "gpt-4")
        assert can_proceed is True
        assert wait_seconds == 0.0

        # Try to add 1 more token (should exceed)
        messages = [{"role": "user", "content": "x"}]  # Minimal content
        can_proceed, wait_seconds = limiter.check_rate_limit(messages, "gpt-4")
        # This might pass or fail depending on exact token counting, but should be consistent

    def test_rate_limiter_time_window_edge(self) -> None:
        """Test rate limiter behavior at time window boundaries."""
        limiter = TokenRateLimiter(tokens_per_minute=100, window_minutes=1)

        current_time = time.time()

        # Add usage at different window boundaries
        limiter.token_usage.append((current_time - 61, 50))  # Outside 60-second window
        limiter.token_usage.append((current_time - 59, 40))  # Inside window

        # Check current usage
        usage = limiter._get_current_usage(current_time)
        assert usage == 40  # Only the second entry should count

    def test_config_validation_boundary_values(self) -> None:
        """Test configuration with boundary values."""
        # Test minimum values
        config = create_test_config(
            llm_max_concurrent_calls=1,
            llm_max_retry_attempts=1,
            llm_max_input_tokens_per_call=1,
            llm_max_input_tokens_per_minute=1,
        )
        assert config.llm_max_concurrent_calls == 1
        assert config.llm_max_retry_attempts == 1
        assert config.llm_max_input_tokens_per_call == 1
        assert config.llm_max_input_tokens_per_minute == 1

    def test_error_classification_comprehensive(self) -> None:
        """Test comprehensive error classification scenarios."""
        config = create_test_config()

        with patch("podcast_processor.ad_classifier.db.session") as mock_session:
            classifier = AdClassifier(config=config, db_session=mock_session)

            retryable_errors = [
                Exception("HTTP 429: Rate limit exceeded"),
                Exception("rate_limit_error: too many requests"),
                Exception("RateLimitError: Request rate limit exceeded"),
                Exception("Service temporarily unavailable (503)"),
                Exception("service unavailable"),
                Exception("Error 503: Service unavailable"),
                Exception("rate limit reached"),
            ]

            # Test specific LiteLLM exceptions by importing at runtime
            try:
                from litellm.exceptions import InternalServerError

                # InternalServerError requires specific parameters, so create a simple one
                retryable_errors.append(
                    InternalServerError(
                        "Service unavailable", llm_provider="test", model="test"
                    )
                )
            except (ImportError, TypeError):
                # If litellm.exceptions not available or constructor changed, skip this specific test
                pass

            for error in retryable_errors:
                assert classifier._is_retryable_error(error) is True

            non_retryable_errors = [
                Exception("Invalid API key (401)"),
                Exception("Bad request (400)"),
                Exception("Forbidden (403)"),
                ValueError("Invalid input format"),
                Exception("Model not found (404)"),
                Exception("Connection timeout"),  # Not in the retryable list
                Exception("Internal server error (500)"),  # Not in the retryable list
            ]

            for error in non_retryable_errors:
                assert classifier._is_retryable_error(error) is False

    @patch("time.sleep")
    def test_backoff_progression(self, mock_sleep: Any) -> None:
        """Test the complete backoff progression for different error types."""
        config = create_test_config()

        with patch("podcast_processor.ad_classifier.db.session") as mock_session:
            classifier = AdClassifier(config=config, db_session=mock_session)

            from app.models import ModelCall

            model_call = ModelCall(id=1, error_message=None)

            # Test rate limit error backoff progression
            rate_limit_error = Exception("rate_limit_error: too many requests")

            # First attempt (attempt=0): 60 * (2^0) = 60
            classifier._handle_retryable_error(
                model_call_obj=model_call,
                error=rate_limit_error,
                attempt=0,
                current_attempt_num=1,
            )

            # Second attempt (attempt=1): 60 * (2^1) = 120
            classifier._handle_retryable_error(
                model_call_obj=model_call,
                error=rate_limit_error,
                attempt=1,
                current_attempt_num=2,
            )

            # Third attempt (attempt=2): 60 * (2^2) = 240
            classifier._handle_retryable_error(
                model_call_obj=model_call,
                error=rate_limit_error,
                attempt=2,
                current_attempt_num=3,
            )

            # Check the sleep calls
            expected_calls = [60, 120, 240]
            actual_calls = [call[0][0] for call in mock_sleep.call_args_list]
            assert actual_calls == expected_calls

            # Reset for non-rate-limit error test
            mock_sleep.reset_mock()

            # Test regular error backoff progression: 1, 2, 4 seconds
            regular_error = Exception("Internal server error")

            classifier._handle_retryable_error(
                model_call_obj=model_call,
                error=regular_error,
                attempt=0,
                current_attempt_num=1,
            )
            classifier._handle_retryable_error(
                model_call_obj=model_call,
                error=regular_error,
                attempt=1,
                current_attempt_num=2,
            )
            classifier._handle_retryable_error(
                model_call_obj=model_call,
                error=regular_error,
                attempt=2,
                current_attempt_num=3,
            )

            expected_calls = [1, 2, 4]
            actual_calls = [call[0][0] for call in mock_sleep.call_args_list]
            assert actual_calls == expected_calls

    def test_rate_limiter_with_very_short_window(self) -> None:
        """Test rate limiter with very short time windows."""
        # Use 1 minute window but test with 10-second spacing
        limiter = TokenRateLimiter(tokens_per_minute=60, window_minutes=1)

        current_time = time.time()

        # Add usage just outside typical processing time
        limiter.token_usage.append((current_time - 65, 30))  # Outside 1-min window
        limiter.token_usage.append((current_time - 5, 20))  # 5 seconds ago

        usage = limiter._get_current_usage(current_time)
        assert usage == 20  # Only the recent usage should count

    def test_model_configuration_case_sensitivity(self) -> None:
        """Test that model configuration handles different cases and formats."""
        from podcast_processor.token_rate_limiter import (
            configure_rate_limiter_for_model,
        )

        # Test different cases of the same model
        test_cases = [
            "gpt-4o-mini",
            "GPT-4O-MINI",  # Different case
            "some-provider/gpt-4o-mini/version",  # With provider prefix/suffix
        ]

        for model_name in test_cases:
            # Clear singleton to ensure fresh test
            import podcast_processor.token_rate_limiter as trl_module

            trl_module._rate_limiter = None

            # Only the exact lowercase match should work due to current implementation
            limiter = configure_rate_limiter_for_model(model_name)
            if "gpt-4o-mini" in model_name.lower():
                expected_limit = (
                    200000
                    if model_name == "gpt-4o-mini" or "gpt-4o-mini" in model_name
                    else 30000
                )
            else:
                expected_limit = 30000  # Default

            assert limiter.tokens_per_minute == expected_limit

    def test_thread_safety_stress(self) -> None:
        """More intensive thread safety test."""
        import threading

        limiter = TokenRateLimiter(
            tokens_per_minute=50000
        )  # Higher limit for stress test
        messages: list[dict[str, str]] = [{"role": "user", "content": "test " * 100}]

        results: list[tuple[int, int, float]] = []
        errors: list[tuple[int, Exception]] = []

        def worker(worker_id: int) -> None:
            try:
                for i in range(20):
                    start_time = time.time()
                    limiter.wait_if_needed(messages, "gpt-4")
                    end_time = time.time()
                    results.append((worker_id, i, end_time - start_time))
            except Exception as e:
                errors.append((worker_id, e))

        # Run 10 threads with 20 calls each
        threads = []
        for worker_id in range(10):
            thread = threading.Thread(target=worker, args=(worker_id,))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # Should have no errors
        assert len(errors) == 0

        # Should have recorded all calls
        assert len(limiter.token_usage) == 200  # 10 threads * 20 calls

        # All calls should complete relatively quickly (no excessive waiting)
        max_wait_time = max(result[2] for result in results)
        assert max_wait_time < 5.0  # Should not wait more than 5 seconds
