"""Integration test script for Podly functionality."""

# mypy: ignore-errors=True

import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from typing import Any, Callable, Dict, List, Optional, Tuple, TypeVar

import requests

# Configuration
BASE_URL = "http://localhost:5001"  # As per config.yml comments
TEST_FEED_URL = "https://feeds.npr.org/510325/podcast.xml"  # NPR Indicator
REQUEST_TIMEOUT = 30  # Seconds for general requests
PROCESSING_TIMEOUT = 600  # 10 minutes for processing requests

T = TypeVar("T")


def api_request(
    method: str,
    endpoint: str,
    success_message: str,
    error_message: str,
    process_response: Callable[[requests.Response], T],
    expected_status_codes: Optional[List[int]] = None,
    timeout: Optional[int] = None,
    **kwargs: Any,
) -> T:
    """
    Helper function to make API requests with consistent error handling.
    Fails immediately by exiting the program if any exception occurs.
    """
    url = f"{BASE_URL}/{endpoint.lstrip('/')}"
    print(f"Making {method} request to {url}...")

    try:
        response = getattr(requests, method.lower())(
            url, timeout=timeout or REQUEST_TIMEOUT, **kwargs
        )

        if expected_status_codes and response.status_code not in expected_status_codes:
            print(
                f"{error_message} Status code: {response.status_code}, Response: {response.text}"
            )
            sys.exit(1)

        result = process_response(response)
        print(success_message)
        return result

    except Exception as e:
        print(f"{error_message}: {e}")
        sys.exit(1)


def check_server_health() -> None:
    """Checks if the Podly server is running and healthy."""
    api_request(
        method="get",
        endpoint="/",
        success_message="Server is healthy (status code 200).",
        error_message="Server health check failed",
        process_response=lambda r: None if r.status_code == 200 else sys.exit(1),
        expected_status_codes=[200],
    )


def get_all_feeds() -> List[Dict[str, Any]]:
    """Gets all feeds from the API."""
    return api_request(
        method="get",
        endpoint="/feeds",
        success_message="Successfully fetched feeds.",
        error_message="Could not fetch feeds from API",
        process_response=lambda r: r.json(),
    )


def delete_feed(f_id: int) -> None:
    """Deletes a feed by its ID via the API."""
    api_request(
        method="DELETE",
        endpoint=f"/feed/{f_id}",
        success_message=f"Successfully deleted feed ID: {f_id}.",
        error_message=f"Error deleting feed ID: {f_id}",
        process_response=lambda r: None,
        expected_status_codes=[204],
    )


def add_feed(feed_url: str) -> None:
    """Adds a new feed via the API."""
    api_request(
        method="post",
        endpoint="/feed",
        data={"url": feed_url},
        success_message=f"Successfully initiated add for feed URL: {feed_url}.",
        error_message=f"Error adding feed URL: {feed_url}",
        process_response=lambda r: None,
        expected_status_codes=[200, 201, 202, 204, 302],
    )


def find_feed_by_url(feeds: List[Dict[str, Any]], url: str) -> Dict[str, Any]:
    """Find a feed by URL or exit if not found."""
    for feed in feeds:
        if feed.get("rss_url") == url:
            return feed
    print(f"Feed with URL {url} not found.")
    sys.exit(1)


def get_feed_id(feed: Dict[str, Any]) -> int:
    """Extract feed ID or exit if not available."""
    feed_id = feed.get("id")
    if feed_id is None:
        print(f"Feed missing 'id' field. Feed data: {feed}")
        sys.exit(1)
    return int(feed_id)


def get_latest_episode_guid(f_id: int) -> str:
    """
    Gets the GUID of the latest episode from a feed.

    Args:
        f_id: The feed ID to get the latest episode from.

    Returns:
        The GUID of the latest episode.
    """
    return api_request(
        method="get",
        endpoint=f"/feed/{f_id}",
        success_message="Successfully fetched feed XML.",
        error_message=f"Could not fetch feed XML for feed ID: {f_id}",
        process_response=lambda r: extract_latest_episode_guid(r.text),
        expected_status_codes=[200],
    )


def extract_latest_episode_guid(xml_content: str) -> str:
    """
    Extracts the GUID of the latest episode from XML content.

    Args:
        xml_content: The XML content of the feed.

    Returns:
        The GUID of the latest episode.
    """
    try:
        # Parse the XML content
        root = ET.fromstring(xml_content)

        # Find all item elements (episodes)
        channel = root.find("channel")
        if channel is None:
            print("Error: No channel element found in feed XML.")
            sys.exit(1)

        items = channel.findall("item")
        if not items:
            print("Error: No episodes found in feed XML.")
            sys.exit(1)

        # Get the first item (latest episode)
        latest_item = items[0]

        # Extract the GUID
        guid_elem = latest_item.find("guid")
        if guid_elem is None or guid_elem.text is None:
            print("Error: No GUID found for latest episode.")
            sys.exit(1)

        guid = guid_elem.text.strip()
        print(f"Found latest episode with GUID: {guid}")
        return guid

    except ET.ParseError as e:
        print(f"Error parsing feed XML: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error extracting episode GUID: {e}")
        sys.exit(1)


def trigger_and_await_processing(p_guid: str) -> bool:
    """
    Triggers processing for an episode and waits for completion.

    Args:
        p_guid: The episode GUID to trigger processing for.

    Returns:
        True if processing succeeded, False otherwise.
    """
    try:
        print(f"Triggering processing for episode with GUID: {p_guid}")
        print(
            "This may take several minutes as the episode is downloaded and processed..."
        )

        # Use a longer timeout for this request
        response = requests.get(
            f"{BASE_URL}/post/{p_guid}.mp3",
            timeout=PROCESSING_TIMEOUT,
            stream=True,  # Use streaming to avoid loading the entire MP3 into memory
        )

        # Close the response to prevent memory issues
        response.close()

        if response.status_code == 200:
            print(f"Successfully processed episode with GUID: {p_guid}")
            return True
        print(f"Failed to process episode. Status code: {response.status_code}")
        print(f"Response: {response.text[:1000]}")  # Show first 1000 chars of response
        return False

    except requests.exceptions.Timeout:
        print(
            f"Timeout occurred while waiting for episode processing (timeout: {PROCESSING_TIMEOUT}s)."
        )
        return False
    except Exception as e:
        print(f"Error triggering episode processing: {e}")
        return False


def download_audio_files(p_guid: str) -> Tuple[str, str]:
    """
    Downloads both the original and processed audio files using the API.

    Args:
        p_guid: The episode GUID.

    Returns:
        A tuple of (original_path, processed_path) as temporary files.
    """
    # Create temporary directory for test files
    temp_dir = tempfile.mkdtemp(prefix="podly_test_")
    original_path = os.path.join(temp_dir, f"original_{p_guid}.mp3")
    processed_path = os.path.join(temp_dir, f"processed_{p_guid}.mp3")

    # Download original unprocessed file
    print(f"Downloading original unprocessed audio file for episode {p_guid}...")
    try:
        response = requests.get(
            f"{BASE_URL}/post/{p_guid}/original.mp3",
            timeout=REQUEST_TIMEOUT,
            stream=True,
        )

        if response.status_code != 200:
            print(
                f"Failed to download original audio file. Status: {response.status_code}"
            )
            sys.exit(1)

        with open(original_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        print(f"Successfully downloaded original audio to {original_path}")
    except Exception as e:  # pylint: disable=broad-exception-caught
        print(f"Error downloading original audio: {e}")
        sys.exit(1)

    # Download processed file
    print(f"Downloading processed audio file for episode {p_guid}...")
    try:
        response = requests.get(
            f"{BASE_URL}/post/{p_guid}.mp3", timeout=REQUEST_TIMEOUT, stream=True
        )

        if response.status_code != 200:
            print(
                f"Failed to download processed audio file. Status: {response.status_code}"
            )
            sys.exit(1)

        with open(processed_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        print(f"Successfully downloaded processed audio to {processed_path}")
    except Exception as e:  # pylint: disable=broad-exception-caught
        print(f"Error downloading processed audio: {e}")
        sys.exit(1)

    return original_path, processed_path


def get_mp3_duration(file_path: str) -> Optional[float]:
    """
    Gets the duration of an MP3 file in seconds.

    Args:
        file_path: Path to the MP3 file.

    Returns:
        Duration in seconds, or None if the file could not be read.
    """
    try:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            file_path,
        ]
        result = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True
        )
        duration = float(result.stdout.strip())
        return duration
    except (subprocess.SubprocessError, ValueError) as e:
        print(f"Error getting duration of {file_path}: {e}")
        return None


def get_post_details(p_guid: str) -> Dict[str, Any]:
    """
    Gets details about a post using the API.

    Args:
        p_guid: The episode GUID to get details for.

    Returns:
        A dictionary containing post details.
    """
    return api_request(
        method="get",
        endpoint=f"/post/{p_guid}/json",
        success_message=f"Successfully fetched post details for episode with GUID: {p_guid}",
        error_message=f"Error fetching post details for episode with GUID: {p_guid}",
        process_response=lambda r: r.json(),
        expected_status_codes=[200],
    )


if __name__ == "__main__":
    print("Starting Integration Test - Phase 1-7 (API-driven)...")

    # Step 0: Check server health
    check_server_health()

    # Step 1: Check for existing test feed and delete if present
    print("\nStep 1: Check for existing test feed and delete if present...")
    current_feeds = get_all_feeds()

    test_feed_exists = any(
        feed.get("rss_url") == TEST_FEED_URL for feed in current_feeds
    )
    if test_feed_exists:
        feed = find_feed_by_url(current_feeds, TEST_FEED_URL)
        feed_id = get_feed_id(feed)
        print(
            f"Test feed {TEST_FEED_URL} found with ID: {feed_id}. Attempting deletion..."
        )
        delete_feed(feed_id)
        print(f"Successfully deleted existing test feed (ID: {feed_id}).")
    else:
        print(
            f"Test feed {TEST_FEED_URL} not found in current feeds. No deletion needed."
        )

    # Step 2: Add the test feed
    print("\nStep 2: Add the test feed...")
    add_feed(TEST_FEED_URL)

    # Step 3: Retrieve ID for the newly added test feed
    print("\nStep 3: Retrieve ID for the newly added test feed...")
    updated_feeds = get_all_feeds()
    new_feed = find_feed_by_url(updated_feeds, TEST_FEED_URL)
    feed_to_process_id = get_feed_id(new_feed)

    print(f"Successfully found ID for new test feed: {feed_to_process_id}")

    # Step 4: Identify latest episode GUID
    print("\nStep 4: Identify latest episode GUID...")
    latest_episode_guid = get_latest_episode_guid(feed_to_process_id)
    print(f"Successfully identified latest episode GUID: {latest_episode_guid}")

    # Step 5: Trigger processing and await completion
    print("\nStep 5: Trigger processing and await completion...")
    PROCESSING_SUCCESS = trigger_and_await_processing(latest_episode_guid)

    if not PROCESSING_SUCCESS:
        print("ERROR: Episode processing failed. Test cannot continue.")
        sys.exit(1)
    else:
        print("SUCCESS: Episode processing completed successfully.")

    # Step 6: Download both audio files
    print("\nStep 6: Download audio files for comparison...")
    original_path, processed_path = download_audio_files(latest_episode_guid)

    # Step 7: Compare MP3 durations & Assert
    print("\nStep 7: Compare audio file durations...")

    # Get durations
    original_duration = get_mp3_duration(original_path)
    processed_duration = get_mp3_duration(processed_path)

    if original_duration is None or processed_duration is None:
        print("ERROR: Could not determine audio file durations.")
        sys.exit(1)

    print(f"Original audio duration: {original_duration:.2f} seconds")
    print(f"Processed audio duration: {processed_duration:.2f} seconds")
    print(f"Duration difference: {original_duration - processed_duration:.2f} seconds")

    # Assert that processed file is shorter
    if original_duration > processed_duration:
        print(
            "\nPASS: Processed MP3 is shorter than the original, indicating successful ad removal."
        )
    else:
        print("\nFAIL: Processed MP3 is NOT shorter than the original.")
        sys.exit(1)

    # Step 8: Get post data via API and validate processing
    print("\nStep 8: Get post data via API and validate processing...")
    post_details = get_post_details(latest_episode_guid)

    # Validate unprocessed audio path
    if not post_details.get("has_unprocessed_audio"):
        print("ERROR: Unprocessed audio path is not set.")
        sys.exit(1)
    else:
        print(
            f"PASS: Unprocessed audio path is set: {post_details.get('unprocessed_audio_path')}"
        )

    # Validate processed audio path
    if not post_details.get("has_processed_audio"):
        print("ERROR: Processed audio path is not set.")
        sys.exit(1)
    else:
        print(
            f"PASS: Processed audio path is set: {post_details.get('processed_audio_path')}"
        )

    # Check transcript segment status
    segment_count = post_details.get("transcript_segment_count", 0)
    if segment_count <= 0:
        # Check if Whisper transcription was attempted
        whisper_calls = post_details.get("whisper_model_calls", [])
        if not whisper_calls:
            print(
                "WARNING: No transcript segments found and no Whisper model calls recorded."
            )
            print("This may indicate an issue with the transcription process.")
        else:
            # Whisper was called but no segments
            whisper_statuses = [call.get("status") for call in whisper_calls]
            print(
                f"WARNING: No transcript segments found. Whisper model call statuses: {whisper_statuses}"
            )
            # If any Whisper call succeeded but no segments, this is unusual
            if "success" in whisper_statuses:
                print(
                    "WARNING: Whisper call succeeded but no transcript segments were created."
                )
            # Don't fail the test on this condition
            print("Continuing test despite transcript segment issues.")
    else:
        print(f"PASS: Found {segment_count} transcript segments.")
        # Print first segment as example
        if post_details.get("transcript_sample"):
            first_segment = post_details["transcript_sample"][0]
            print(f"Sample segment: {first_segment.get('text', 'No text')}")

    # Validate model calls
    model_call_count = post_details.get("model_call_count", 0)
    if model_call_count <= 0:
        print("WARNING: No model calls found. This may indicate a processing issue.")
    else:
        print(f"PASS: Found {model_call_count} model calls.")

    print("Audio processing validation successful!")
