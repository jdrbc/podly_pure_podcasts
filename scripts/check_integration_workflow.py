#!/usr/bin/env python3
"""Standalone integration workflow checks for Podly.

These checks verify:
1. Processing workflow: add feed → whitelist → process → verify audio
2. Reprocessing workflow: process → clear → reprocess → verify
3. Cleanup workflow: verify only audio files are removed, metadata preserved

Requires a running Podly container with DEVELOPER_MODE=true.
Run with: PODLY_TEST_URL=http://localhost:5001 python scripts/check_integration_workflow.py

Set SKIP_INTEGRATION=1 to skip these checks without error.
"""

import os
import sys
from typing import Any, Dict, List, Optional

from integration_check.client import (
    FeedInfo,
    IntegrationTestClient,
    PostInfo,
    generate_test_feed_url,
)

# Add src and scripts directories to path for imports
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(project_root, "src"))
sys.path.insert(0, os.path.join(project_root, "scripts"))


class SkipTest(Exception):
    """Exception to skip a test without failing."""

    pass


def get_api_client() -> IntegrationTestClient:
    """Get the API client or skip if server is not available."""
    api_base_url = os.environ.get("PODLY_TEST_URL", "http://localhost:5001")
    client = IntegrationTestClient(api_base_url)
    if not client.check_health():
        raise SkipTest(
            f"Podly server not reachable at {api_base_url}. "
            "Start the container with DEVELOPER_MODE=true."
        )
    return client


def create_test_feed(client: IntegrationTestClient) -> FeedInfo:
    """Create a test feed and return its info."""
    test_feed_url = generate_test_feed_url()

    # Add the feed
    success = client.add_feed(test_feed_url)
    assert success, f"Failed to add test feed: {test_feed_url}"

    # Retrieve the feed info
    feed = client.get_feed_by_url(test_feed_url)
    assert feed is not None, f"Feed not found after adding: {test_feed_url}"

    return feed


def cleanup_feed(client: IntegrationTestClient, feed: FeedInfo) -> None:
    """Clean up a test feed."""
    client.delete_feed(feed.id)


def get_processed_post(client: IntegrationTestClient, feed: FeedInfo) -> PostInfo:
    """Get the first post from a test feed and ensure it's processed."""
    posts = client.get_posts(feed.id)
    assert posts, f"No posts found in test feed {feed.id}"

    post_data = posts[0]
    guid = post_data["guid"]

    # If not processed, trigger processing and wait
    if not post_data.get("has_processed_audio"):
        if not post_data.get("whitelisted"):
            client.whitelist_post(guid, whitelisted=True, trigger_processing=True)
        else:
            client.process_post(guid)
        client.wait_for_processing(guid, timeout=60)

    # Return fresh post info
    post_info = client.get_post_info(guid)
    assert post_info is not None, f"Could not get post info for {guid}"
    assert post_info.has_processed_audio, f"Post {guid} should have processed audio"

    return post_info


# --- Test Functions ---


def test_add_feed_and_get_posts():
    """Test adding a feed and retrieving its posts."""
    print("  → test_add_feed_and_get_posts")
    client = get_api_client()
    feed = create_test_feed(client)

    try:
        posts = client.get_posts(feed.id)
        assert len(posts) > 0, "Test feed should have posts"

        # Developer mode creates posts with predictable structure
        post = posts[0]
        assert "guid" in post
        assert "title" in post
        assert "download_url" in post

        print("    ✓ passed")
    finally:
        cleanup_feed(client, feed)


def test_whitelist_and_process_post():
    """Test whitelisting a post triggers processing."""
    print("  → test_whitelist_and_process_post")
    client = get_api_client()
    feed = create_test_feed(client)

    try:
        posts = client.get_posts(feed.id)
        assert posts, "Need at least one post to test"

        # Find a non-whitelisted post or use the first one
        target_post: Dict[str, Any] = posts[0]
        for post in posts:
            if not post.get("whitelisted"):
                target_post = post
                break

        guid = target_post["guid"]

        # Whitelist and trigger processing
        result = client.whitelist_post(guid, whitelisted=True, trigger_processing=True)
        assert (
            result.get("whitelisted") is True
        ), f"Post should be whitelisted: {result}"
        assert "processing_job" in result, f"Should trigger processing job: {result}"
        assert result["processing_job"].get("status") in (
            "started",
            "running",
        ), f"Unexpected processing job status: {result}"

        # Wait for processing to complete
        status = client.wait_for_processing(guid, timeout=60)
        assert status["status"] == "completed", f"Expected completed, got {status}"

        # Verify audio is accessible
        post_info = client.get_post_info(guid)
        assert post_info is not None
        assert post_info.has_processed_audio, "Post should have processed audio"

        # Verify we can fetch the audio
        audio_resp = client.get_audio(guid)
        assert audio_resp is not None, "Should be able to fetch audio"
        assert audio_resp.status_code == 200

        print("    ✓ passed")
    finally:
        cleanup_feed(client, feed)


def test_process_explicit_trigger():
    """Test explicitly triggering processing on a whitelisted post."""
    print("  → test_process_explicit_trigger")
    client = get_api_client()
    feed = create_test_feed(client)

    try:
        posts = client.get_posts(feed.id)
        assert len(posts) >= 2, "Need at least 2 posts to test"

        # Use second post to avoid conflict with other tests
        target_post = posts[1]
        guid = target_post["guid"]

        # Ensure whitelisted
        if not target_post.get("whitelisted"):
            client.whitelist_post(guid, whitelisted=True, trigger_processing=False)

        # Explicitly trigger processing
        result = client.process_post(guid)
        assert result.get("status") in (
            "started",
            "completed",
            "already_processing",
        ), f"Unexpected process result: {result}"

        # Wait for completion if started
        if result.get("status") == "started":
            client.wait_for_processing(guid, timeout=60)

        # Verify
        post_info = client.get_post_info(guid)
        assert post_info is not None
        assert post_info.has_processed_audio

        print("    ✓ passed")
    finally:
        cleanup_feed(client, feed)


def test_reprocess_clears_and_reprocesses():
    """Test that reprocessing clears data and processes again."""
    print("  → test_reprocess_clears_and_reprocesses")
    client = get_api_client()
    feed = create_test_feed(client)

    try:
        processed_post = get_processed_post(client, feed)
        guid = processed_post.guid

        # Verify we start with processed audio
        assert processed_post.has_processed_audio, "Should start with processed audio"

        # Trigger reprocess
        result = client.reprocess_post(guid)
        assert result.get("status") in (
            "started",
            "completed",
        ), f"Unexpected reprocess result: {result}"

        # Wait for processing to complete
        if result.get("status") == "started":
            status = client.wait_for_processing(guid, timeout=60)
            assert status["status"] == "completed"

        # Verify audio is still accessible after reprocessing
        post_info = client.get_post_info(guid)
        assert post_info is not None
        assert (
            post_info.has_processed_audio
        ), "Should have processed audio after reprocess"

        # Verify audio endpoint works
        audio_resp = client.get_audio(guid)
        assert audio_resp is not None
        assert audio_resp.status_code == 200

        print("    ✓ passed")
    finally:
        cleanup_feed(client, feed)


def test_cleanup_preview():
    """Test the cleanup preview endpoint returns expected structure."""
    print("  → test_cleanup_preview")
    client = get_api_client()

    preview = client.get_cleanup_preview()

    assert "count" in preview, "Preview should include count"
    assert "retention_days" in preview, "Preview should include retention_days"
    # cutoff_utc may be None if retention is not configured
    assert "cutoff_utc" in preview, "Preview should include cutoff_utc"

    print("    ✓ passed")


def test_cleanup_removes_only_audio_files():
    """Test that cleanup removes audio but preserves metadata.

    NOTE: This test processes all posts in a feed. With retention_days=0
    (allowed in developer mode), all posts become eligible for cleanup except
    the most recent post for the feed which is always preserved.
    """
    print("  → test_cleanup_removes_only_audio_files")
    client = get_api_client()
    feed = create_test_feed(client)

    try:
        # Get all posts from the feed
        posts = client.get_posts(feed.id)
        if len(posts) < 2:
            raise SkipTest(
                f"Feed needs at least 2 posts for cleanup test, found {len(posts)}"
            )

        # Process all posts (they're ordered newest to oldest)
        for post in posts:
            if not post.get("has_processed_audio"):
                if not post.get("whitelisted"):
                    client.whitelist_post(
                        post["guid"], whitelisted=True, trigger_processing=True
                    )
                else:
                    client.process_post(post["guid"])
                client.wait_for_processing(post["guid"], timeout=60)

        # Use an older post (not the most recent) for testing cleanup
        # The most recent post will never be cleaned up
        test_post = posts[1] if len(posts) > 1 else posts[0]
        old_guid = test_post["guid"]

        # Capture initial state of a post
        initial_info = client.get_post_info(old_guid)
        assert initial_info is not None
        assert (
            initial_info.has_processed_audio
        ), "Should have processed audio before cleanup"

        # Store duration for later comparison (should be preserved)
        initial_duration = initial_info.duration

        # Preview cleanup with retention_days=0 (developer mode allows this)
        preview_before = client.get_cleanup_preview(retention_days=0)
        if preview_before.get("count", 0) == 0:
            raise SkipTest(
                "No posts eligible for cleanup. All posts may be the most recent for their feeds."
            )

        # Run cleanup with retention_days=0
        result = client.run_cleanup(retention_days=0)

        # Check result - cleanup may be disabled
        if result.get("status") == "disabled":
            raise SkipTest(f"Cleanup is disabled: {result.get('message')}")

        assert result.get("status") == "ok", f"Cleanup failed: {result}"

        # At least one post should have been removed
        removed = result.get("removed_posts", 0)
        assert removed >= 1, f"Expected at least 1 post removed, got {removed}"

        # Verify the older post state after cleanup
        post_after = client.get_post_info(old_guid)

        assert post_after is not None, "Post should still exist after cleanup"

        # Audio files should be removed from the old post
        assert (
            not post_after.has_processed_audio
        ), "Processed audio path should be cleared after cleanup"
        assert (
            not post_after.has_unprocessed_audio
        ), "Unprocessed audio path should be cleared after cleanup"

        # Whitelisted should be set to False
        assert (
            not post_after.whitelisted
        ), "Post should not be whitelisted after cleanup"

        # Duration should be preserved (metadata)
        assert (
            post_after.duration == initial_duration
        ), f"Duration should be preserved. Expected {initial_duration}, got {post_after.duration}"

        print("    ✓ passed")
    finally:
        cleanup_feed(client, feed)


def test_cleanup_disabled_when_no_retention():
    """Test that cleanup reports disabled status when retention <= 0."""
    print("  → test_cleanup_disabled_when_no_retention")
    client = get_api_client()

    preview = client.get_cleanup_preview()

    # If retention_days is None or 0, cleanup should be disabled
    retention = preview.get("retention_days")
    if retention is not None and retention > 0:
        raise SkipTest("Cleanup is enabled with retention_days > 0")

    result = client.run_cleanup()
    assert (
        result.get("status") == "disabled"
    ), f"Expected disabled status when retention <= 0, got: {result}"

    print("    ✓ passed")


def test_status_shows_progress():
    """Test that status endpoint returns meaningful progress info."""
    print("  → test_status_shows_progress")
    client = get_api_client()
    feed = create_test_feed(client)

    try:
        posts = client.get_posts(feed.id)
        assert posts, "Need posts to test"

        # Use last post to avoid conflicts
        target = posts[-1]
        guid = target["guid"]

        # Ensure processing starts
        if not target.get("whitelisted"):
            client.whitelist_post(guid, whitelisted=True, trigger_processing=True)
        elif not target.get("has_processed_audio"):
            client.process_post(guid)

        # Check status structure (may be completed quickly in dev mode)
        status = client.get_post_status(guid)
        assert status is not None, "Should get status for post"
        assert "status" in status, "Status should have 'status' field"

        # Status should be one of the expected values
        assert status["status"] in (
            "pending",
            "queued",
            "processing",
            "completed",
            "failed",
            "error",
            "not_started",
        ), f"Unexpected status: {status['status']}"

        print("    ✓ passed")
    finally:
        cleanup_feed(client, feed)


def main():
    """Run all integration checks."""
    # Check if we should skip integration tests
    if os.environ.get("SKIP_INTEGRATION") == "1":
        print("SKIP_INTEGRATION=1, skipping integration checks")
        return 0

    print("Running integration workflow checks...")
    print()

    tests = [
        (
            "Processing Workflow",
            [
                test_add_feed_and_get_posts,
                test_whitelist_and_process_post,
                test_process_explicit_trigger,
            ],
        ),
        (
            "Reprocessing Workflow",
            [
                test_reprocess_clears_and_reprocesses,
            ],
        ),
        (
            "Cleanup Workflow",
            [
                test_cleanup_preview,
                test_cleanup_removes_only_audio_files,
                test_cleanup_disabled_when_no_retention,
            ],
        ),
        (
            "Post Status Tracking",
            [
                test_status_shows_progress,
            ],
        ),
    ]

    total_run = 0
    total_skipped = 0
    total_failed = 0

    for group_name, group_tests in tests:
        print(f"{group_name}:")
        for test_func in group_tests:
            try:
                test_func()
                total_run += 1
            except SkipTest as e:
                print(f"    ⊘ skipped: {e}")
                total_skipped += 1
            except Exception as e:
                print(f"    ✗ FAILED: {e}")
                total_failed += 1
                import traceback

                traceback.print_exc()
        print()

    print(
        f"Integration checks: {total_run} passed, {total_skipped} skipped, {total_failed} failed"
    )
    print()

    if total_failed > 0:
        return 1
    if total_run == 0 and total_skipped > 0:
        print("All integration checks were skipped (server not available)")
        return 0

    print("All integration checks passed! ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
