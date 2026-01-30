"""Integration test client and shared types for workflow checks.

These checks run against a live Docker container with DEVELOPER_MODE=true.
The test feed system allows instant processing without hitting real APIs.
"""

import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests


@dataclass
class PostInfo:
    """Minimal post information from API responses."""

    guid: str
    title: str
    whitelisted: bool
    has_processed_audio: bool
    has_unprocessed_audio: bool
    duration: Optional[float] = None
    processed_audio_path: Optional[str] = None
    unprocessed_audio_path: Optional[str] = None


@dataclass
class FeedInfo:
    """Minimal feed information from API responses."""

    id: int
    title: str
    rss_url: str


class IntegrationTestClient:
    """HTTP client for Podly API integration tests."""

    def __init__(self, base_url: str, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _get(self, path: str, **kwargs: Any) -> requests.Response:
        kwargs.setdefault("timeout", self.timeout)
        return self.session.get(self._url(path), **kwargs)

    def _post(self, path: str, **kwargs: Any) -> requests.Response:
        kwargs.setdefault("timeout", self.timeout)
        return self.session.post(self._url(path), **kwargs)

    # --- Health ---

    def check_health(self) -> bool:
        """Check if the server is reachable."""
        try:
            resp = self._get("/feeds")
            return resp.status_code == 200
        except requests.exceptions.ConnectionError:
            return False

    # --- Feeds ---

    def add_feed(self, url: str) -> bool:
        """Add a feed by URL. Returns True on success."""
        resp = self._post("/feed", data={"url": url}, allow_redirects=False)
        if resp.status_code not in (200, 302):
            print(f"Add feed failed with status {resp.status_code}: {resp.text}")
        return resp.status_code in (200, 302)

    def get_feeds(self) -> List[FeedInfo]:
        """Get all feeds."""
        resp = self._get("/feeds")
        resp.raise_for_status()
        return [
            FeedInfo(id=f["id"], title=f["title"], rss_url=f["rss_url"])
            for f in resp.json()
        ]

    def get_feed_by_url(self, rss_url: str) -> Optional[FeedInfo]:
        """Find a feed by its RSS URL."""
        feeds = self.get_feeds()
        for feed in feeds:
            if feed.rss_url == rss_url:
                return feed
        return None

    def delete_feed(self, feed_id: int) -> bool:
        """Delete a feed by ID."""
        resp = self.session.delete(self._url(f"/feeds/{feed_id}"), timeout=self.timeout)
        return resp.status_code in (200, 204, 302)

    # --- Posts ---

    def get_posts(
        self, feed_id: int, page: int = 1, page_size: int = 50
    ) -> List[Dict[str, Any]]:
        """Get posts for a feed (raw dict for flexibility)."""
        resp = self._get(
            f"/api/feeds/{feed_id}/posts",
            params={"page": page, "page_size": page_size},
        )
        resp.raise_for_status()
        items: List[Dict[str, Any]] = resp.json().get("items", [])
        return items

    def get_post_info(self, guid: str) -> Optional[PostInfo]:
        """Get detailed post info by GUID."""
        resp = self._get(f"/post/{guid}/json")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        post = data.get("post", data)
        return PostInfo(
            guid=post.get("guid", guid),
            title=post.get("title", ""),
            whitelisted=post.get("whitelisted", False),
            has_processed_audio=post.get("processed_audio_path") is not None,
            has_unprocessed_audio=post.get("unprocessed_audio_path") is not None,
            duration=post.get("duration"),
            processed_audio_path=post.get("processed_audio_path"),
            unprocessed_audio_path=post.get("unprocessed_audio_path"),
        )

    def whitelist_post(
        self, guid: str, whitelisted: bool = True, trigger_processing: bool = True
    ) -> Dict[str, Any]:
        """Whitelist a post and optionally trigger processing."""
        resp = self._post(
            f"/api/posts/{guid}/whitelist",
            json={"whitelisted": whitelisted, "trigger_processing": trigger_processing},
        )
        resp.raise_for_status()
        result: Dict[str, Any] = resp.json()
        return result

    def process_post(self, guid: str) -> Dict[str, Any]:
        """Trigger processing for a post."""
        resp = self._post(f"/api/posts/{guid}/process")
        resp.raise_for_status()
        result: Dict[str, Any] = resp.json()
        return result

    def reprocess_post(self, guid: str) -> Dict[str, Any]:
        """Clear and reprocess a post (admin only)."""
        resp = self._post(f"/api/posts/{guid}/reprocess")
        resp.raise_for_status()
        result: Dict[str, Any] = resp.json()
        return result

    def get_post_status(self, guid: str) -> Optional[Dict[str, Any]]:
        """Get processing status for a post."""
        resp = self._get(f"/api/posts/{guid}/status")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        result: Dict[str, Any] = resp.json()
        return result

    def get_audio(self, guid: str) -> Optional[requests.Response]:
        """Get the processed audio file (returns response for streaming)."""
        resp = self._get(f"/api/posts/{guid}/audio", stream=True)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp

    # --- Cleanup ---

    def get_cleanup_preview(
        self, retention_days: Optional[int] = None
    ) -> Dict[str, Any]:
        """Preview cleanup candidates."""
        params = (
            {"retention_days": retention_days} if retention_days is not None else {}
        )
        resp = self._get("/api/jobs/cleanup/preview", params=params)
        resp.raise_for_status()
        result: Dict[str, Any] = resp.json()
        return result

    def run_cleanup(self, retention_days: Optional[int] = None) -> Dict[str, Any]:
        """Run cleanup job."""
        params = (
            {"retention_days": retention_days} if retention_days is not None else {}
        )
        resp = self._post("/api/jobs/cleanup/run", params=params)
        resp.raise_for_status()
        result: Dict[str, Any] = resp.json()
        return result

    # --- Polling helpers ---

    def wait_for_processing(
        self,
        guid: str,
        timeout: int = 120,
        poll_interval: float = 2.0,
    ) -> Dict[str, Any]:
        """
        Wait for post processing to complete.

        Returns the final status dict.
        Raises TimeoutError if processing doesn't complete in time.
        Raises RuntimeError if processing fails.
        """
        start = time.time()
        while time.time() - start < timeout:
            status = self.get_post_status(guid)
            if status is None:
                time.sleep(poll_interval)
                continue

            state = status.get("status", "")
            if state == "completed":
                return status
            if state in ("failed", "error"):
                error_msg = status.get("error_message") or status.get(
                    "message", "Unknown error"
                )
                raise RuntimeError(f"Processing failed for {guid}: {error_msg}")

            time.sleep(poll_interval)

        raise TimeoutError(f"Processing timed out for {guid} after {timeout}s")


def generate_test_feed_url() -> str:
    """Generate a unique test feed URL for developer mode."""
    unique_id = uuid.uuid4().hex[:8]
    return f"http://test-feed/{unique_id}"
