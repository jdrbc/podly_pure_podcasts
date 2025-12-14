import json
import sys
import time

import requests

BASE_URL = "http://localhost:5001"


def log(msg):
    print(f"[TEST] {msg}")


def check_health():
    try:
        # Assuming there's a health check or just checking root
        # If no explicit health check, we can try listing feeds
        response = requests.get(f"{BASE_URL}/feeds")
        if response.status_code == 200:
            log("Server is up and running.")
            return True
    except requests.exceptions.ConnectionError:
        pass
    return False


def add_feed(url):
    log(f"Adding feed: {url}")
    response = requests.post(f"{BASE_URL}/feed", data={"url": url})
    if response.status_code == 302:  # Redirects to index on success
        log("Feed added successfully (redirected).")
        return True
    elif response.status_code == 200:
        log("Feed added successfully.")
        return True
    else:
        log(
            f"Failed to add feed. Status: {response.status_code}, Body: {response.text}"
        )
        return False


def get_feeds():
    log("Fetching feeds...")
    response = requests.get(f"{BASE_URL}/feeds")
    if response.status_code == 200:
        feeds = response.json()
        log(f"Found {len(feeds)} feeds.")
        return feeds
    else:
        log(f"Failed to fetch feeds. Status: {response.status_code}")
        return []


def get_posts(feed_id):
    log(f"Fetching posts for feed {feed_id}...")
    response = requests.get(f"{BASE_URL}/api/feeds/{feed_id}/posts")
    if response.status_code == 200:
        posts = response.json()
        log(f"Found {len(posts)} posts.")
        return posts
    else:
        log(f"Failed to fetch posts. Status: {response.status_code}")
        return []


def whitelist_post(guid):
    log(f"Whitelisting post {guid}...")
    # Assuming admin auth is not strictly enforced for localhost/dev mode or we need to handle it.
    # The code checks for current_user. If auth is disabled, it might pass.
    # If auth is enabled, we might need to login first.
    # For now, let's try without auth headers, assuming dev environment.

    response = requests.post(
        f"{BASE_URL}/api/posts/{guid}/whitelist",
        json={"whitelisted": True, "trigger_processing": True},
    )

    if response.status_code == 200:
        log("Post whitelisted and processing triggered.")
        return True
    else:
        log(
            f"Failed to whitelist post. Status: {response.status_code}, Body: {response.text}"
        )
        return False


def check_status(guid):
    response = requests.get(f"{BASE_URL}/api/posts/{guid}/status")
    if response.status_code == 200:
        return response.json()
    return None


def wait_for_processing(guid, timeout=300):
    log(f"Waiting for processing of {guid}...")
    start_time = time.time()
    while time.time() - start_time < timeout:
        status_data = check_status(guid)
        if status_data:
            status = status_data.get("status")
            progress = status_data.get("progress_percentage", 0)
            step = status_data.get("step_name", "unknown")
            log(f"Status: {status}, Step: {step}, Progress: {progress}%")

            if status == "completed":
                log("Processing completed successfully!")
                return True
            elif status == "failed":
                log(f"Processing failed: {status_data.get('error_message')}")
                return False
            elif status == "error":
                log(f"Processing error: {status_data.get('message')}")
                return False

        time.sleep(5)

    log("Timeout waiting for processing.")
    return False


def main():
    if not check_health():
        log("Server is not reachable. Please start the server first.")
        sys.exit(1)

    # 1. Add a test feed
    # Using a known stable feed or a mock one if available.
    # Let's use a popular tech podcast that usually works.
    test_feed_url = "http://test-feed/1"  # Developer mode test feed

    # Check if feed already exists
    feeds = get_feeds()
    target_feed = None
    for feed in feeds:
        if feed["rss_url"] == test_feed_url:
            target_feed = feed
            break

    if not target_feed:
        if add_feed(test_feed_url):
            # Fetch feeds again to get the ID
            feeds = get_feeds()
            for feed in feeds:
                if feed["rss_url"] == test_feed_url:
                    target_feed = feed
                    break

    if not target_feed:
        log("Could not find or add the test feed.")
        sys.exit(1)

    log(f"Working with feed: {target_feed['title']} (ID: {target_feed['id']})")

    # 2. Get posts
    posts = get_posts(target_feed["id"])
    if not posts:
        log("No posts found.")
        sys.exit(1)

    # 3. Pick the latest post
    # Posts are usually sorted by release date desc
    target_post = posts[0]
    log(f"Selected post: {target_post['title']} (GUID: {target_post['guid']})")

    # 4. Trigger processing (Whitelist + Trigger)
    if not target_post["whitelisted"]:
        if not whitelist_post(target_post["guid"]):
            log("Failed to trigger processing.")
            sys.exit(1)
    else:
        log("Post already whitelisted. Checking status...")
        # If already whitelisted, maybe trigger reprocess or just check status?
        # Let's try to trigger process explicitly if it's not processed
        if not target_post["has_processed_audio"]:
            response = requests.post(
                f"{BASE_URL}/api/posts/{target_post['guid']}/process"
            )
            log(f"Trigger process response: {response.status_code}")

    # 5. Wait for completion
    if wait_for_processing(target_post["guid"]):
        # 6. Verify output
        log("Verifying output...")
        # Check if we can get the audio link
        response = requests.get(
            f"{BASE_URL}/api/posts/{target_post['guid']}/audio", stream=True
        )
        if response.status_code == 200:
            log("Audio file is accessible.")
        else:
            log(f"Failed to access audio file. Status: {response.status_code}")

        # Check JSON details
        response = requests.get(f"{BASE_URL}/post/{target_post['guid']}/json")
        if response.status_code == 200:
            data = response.json()
            log(
                f"Post JSON retrieved. Transcript segments: {data.get('transcript_segment_count')}"
            )
        else:
            log("Failed to retrieve post JSON.")


if __name__ == "__main__":
    main()
