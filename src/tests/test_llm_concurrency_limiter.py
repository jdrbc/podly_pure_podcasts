"""
Test cases for LLM concurrency limiting functionality.
"""

import threading
import time

import pytest

from podcast_processor.llm_concurrency_limiter import (
    ConcurrencyContext,
    LLMConcurrencyLimiter,
    get_concurrency_limiter,
)


class TestLLMConcurrencyLimiter:
    """Test cases for the LLMConcurrencyLimiter class."""

    def test_initialization(self):
        """Test proper initialization of the concurrency limiter."""
        limiter = LLMConcurrencyLimiter(max_concurrent_calls=3)
        assert limiter.max_concurrent_calls == 3
        assert limiter.get_available_slots() == 3
        assert limiter.get_active_calls() == 0

    def test_initialization_invalid_value(self):
        """Test that invalid max_concurrent_calls raises ValueError."""
        with pytest.raises(
            ValueError, match="max_concurrent_calls must be greater than 0"
        ):
            LLMConcurrencyLimiter(max_concurrent_calls=0)

        with pytest.raises(
            ValueError, match="max_concurrent_calls must be greater than 0"
        ):
            LLMConcurrencyLimiter(max_concurrent_calls=-1)

    def test_acquire_and_release(self):
        """Test basic acquire and release functionality."""
        limiter = LLMConcurrencyLimiter(max_concurrent_calls=2)

        # Initially should have 2 available slots
        assert limiter.get_available_slots() == 2
        assert limiter.get_active_calls() == 0

        # Acquire first slot
        assert limiter.acquire() is True
        assert limiter.get_available_slots() == 1
        assert limiter.get_active_calls() == 1

        # Acquire second slot
        assert limiter.acquire() is True
        assert limiter.get_available_slots() == 0
        assert limiter.get_active_calls() == 2

        # Release first slot
        limiter.release()
        assert limiter.get_available_slots() == 1
        assert limiter.get_active_calls() == 1

        # Release second slot
        limiter.release()
        assert limiter.get_available_slots() == 2
        assert limiter.get_active_calls() == 0

    def test_acquire_timeout(self):
        """Test acquire with timeout when no slots available."""
        limiter = LLMConcurrencyLimiter(max_concurrent_calls=1)

        # Acquire the only slot
        assert limiter.acquire() is True

        # Try to acquire another slot with timeout
        start_time = time.time()
        assert limiter.acquire(timeout=0.1) is False
        elapsed = time.time() - start_time

        # Should timeout quickly
        assert elapsed < 0.2  # Allow some margin for test execution

    def test_context_manager(self):
        """Test the ConcurrencyContext context manager."""
        limiter = LLMConcurrencyLimiter(max_concurrent_calls=2)

        assert limiter.get_available_slots() == 2

        with ConcurrencyContext(limiter):
            assert limiter.get_available_slots() == 1
            assert limiter.get_active_calls() == 1

        assert limiter.get_available_slots() == 2
        assert limiter.get_active_calls() == 0

    def test_context_manager_timeout(self):
        """Test context manager with timeout when no slots available."""
        limiter = LLMConcurrencyLimiter(max_concurrent_calls=1)

        # Acquire the only slot
        limiter.acquire()

        # Try to use context manager with timeout
        with pytest.raises(
            RuntimeError, match="Could not acquire LLM concurrency slot"
        ):
            with ConcurrencyContext(limiter, timeout=0.1):
                pass

    def test_thread_safety(self):
        """Test that the limiter works correctly with multiple threads."""
        limiter = LLMConcurrencyLimiter(max_concurrent_calls=2)
        results = []
        errors = []

        def worker(worker_id):
            try:
                with ConcurrencyContext(limiter, timeout=1.0):
                    results.append(f"worker_{worker_id}_start")
                    # Simulate some work
                    time.sleep(0.1)
                    results.append(f"worker_{worker_id}_end")
            except Exception as e:
                errors.append(f"worker_{worker_id}_error: {e}")

        # Start 4 threads, but only 2 should run concurrently
        threads = []
        for i in range(4):
            thread = threading.Thread(target=worker, args=(i,))
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # Should have no errors
        assert len(errors) == 0

        # Should have 8 results total (start and end for each worker)
        assert len(results) == 8

        # Check that we have the expected results
        start_results = [r for r in results if r.endswith("_start")]
        end_results = [r for r in results if r.endswith("_end")]
        assert len(start_results) == 4
        assert len(end_results) == 4


class TestGlobalConcurrencyLimiter:
    """Test cases for global concurrency limiter functions."""

    def test_get_concurrency_limiter_singleton(self):
        """Test that get_concurrency_limiter returns the same instance."""
        # Clear any existing limiter
        import podcast_processor.llm_concurrency_limiter as limiter_module

        limiter_module._CONCURRENCY_LIMITER = None

        limiter1 = get_concurrency_limiter(max_concurrent_calls=3)
        limiter2 = get_concurrency_limiter(max_concurrent_calls=3)

        assert limiter1 is limiter2
        assert limiter1.max_concurrent_calls == 3

    def test_get_concurrency_limiter_different_limits(self):
        """Test that get_concurrency_limiter creates new instance for different limits."""
        # Clear any existing limiter
        import podcast_processor.llm_concurrency_limiter as limiter_module

        limiter_module._CONCURRENCY_LIMITER = None

        limiter1 = get_concurrency_limiter(max_concurrent_calls=3)
        limiter2 = get_concurrency_limiter(max_concurrent_calls=5)

        assert limiter1 is not limiter2
        assert limiter1.max_concurrent_calls == 3
        assert limiter2.max_concurrent_calls == 5
