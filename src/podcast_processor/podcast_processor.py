import logging
import os
import shutil
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import litellm
from jinja2 import Template
from sqlalchemy.orm import object_session

from app.extensions import db
from app.models import Post, ProcessingJob, TranscriptSegment
from app.writer.client import writer_client
from podcast_processor.ad_classifier import AdClassifier
from podcast_processor.audio import clip_segments_exact
from podcast_processor.audio_processor import AudioProcessor
from podcast_processor.chapter_ad_detector import (
    ChapterAdDetector,
    ChapterDetectionError,
)
from podcast_processor.chapter_filter import parse_filter_strings
from podcast_processor.chapter_writer import write_adjusted_chapters
from podcast_processor.podcast_downloader import PodcastDownloader, sanitize_title
from podcast_processor.processing_status_manager import ProcessingStatusManager
from podcast_processor.prompt import (
    DEFAULT_SYSTEM_PROMPT_PATH,
    DEFAULT_USER_PROMPT_TEMPLATE_PATH,
)
from podcast_processor.transcription_manager import TranscriptionManager
from shared.config import Config
from shared.processing_paths import (
    ProcessingPaths,
    get_job_unprocessed_path,
    get_srv_root,
    paths_from_unprocessed_path,
)

logger = logging.getLogger("global_logger")


def get_post_processed_audio_path(post: Post) -> Optional[ProcessingPaths]:
    """
    Generate the processed audio path based on the post's unprocessed audio path.
    Returns None if unprocessed_audio_path is not set.
    """
    unprocessed_path = post.unprocessed_audio_path
    if not unprocessed_path or not isinstance(unprocessed_path, str):
        logger.warning(f"Post {post.id} has no unprocessed_audio_path.")
        return None

    title = post.feed.title
    if not title or not isinstance(title, str):
        logger.warning(f"Post {post.id} has no feed title.")
        return None

    return paths_from_unprocessed_path(unprocessed_path, title)


def get_post_processed_audio_path_cached(
    post: Post, feed_title: str
) -> Optional[ProcessingPaths]:
    """
    Generate the processed audio path using cached feed title to avoid ORM access.
    Returns None if unprocessed_audio_path is not set.
    """
    unprocessed_path = post.unprocessed_audio_path
    if not unprocessed_path or not isinstance(unprocessed_path, str):
        logger.warning(f"Post {post.id} has no unprocessed_audio_path.")
        return None

    if not feed_title or not isinstance(feed_title, str):
        logger.warning(f"Post {post.id} has no feed title.")
        return None

    return paths_from_unprocessed_path(unprocessed_path, feed_title)


class PodcastProcessor:
    """
    Main coordinator for podcast processing workflow.
    Delegates to specialized components for transcription, ad classification, and audio processing.
    """

    lock_lock = threading.Lock()
    locks: Dict[str, threading.Lock] = {}  # Now keyed by post GUID instead of file path

    def __init__(
        self,
        config: Config,
        logger: Optional[logging.Logger] = None,
        transcription_manager: Optional[TranscriptionManager] = None,
        ad_classifier: Optional[AdClassifier] = None,
        audio_processor: Optional[AudioProcessor] = None,
        status_manager: Optional[ProcessingStatusManager] = None,
        db_session: Optional[Any] = None,
        downloader: Optional[PodcastDownloader] = None,
    ) -> None:
        super().__init__()
        self.logger = logger or logging.getLogger("global_logger")
        self.output_dir = str(get_srv_root())
        self.config: Config = config
        self.db_session = db_session or db.session

        # Initialize downloader
        self.downloader = downloader or PodcastDownloader(logger=self.logger)

        # Initialize status manager
        self.status_manager = status_manager or ProcessingStatusManager(
            self.db_session, self.logger
        )

        litellm.api_base = self.config.openai_base_url
        litellm.api_key = self.config.llm_api_key

        # Initialize components with default implementations if not provided
        if transcription_manager is None:
            self.transcription_manager = TranscriptionManager(self.logger, config)
        else:
            self.transcription_manager = transcription_manager

        if ad_classifier is None:
            self.ad_classifier = AdClassifier(config)
        else:
            self.ad_classifier = ad_classifier

        if audio_processor is None:
            self.audio_processor = AudioProcessor(config=config, logger=self.logger)
        else:
            self.audio_processor = audio_processor

    # pylint: disable=too-many-branches, too-many-statements
    def process(
        self,
        post: Post,
        job_id: str,
        cancel_callback: Optional[Callable[[], bool]] = None,
    ) -> str:
        """
        Process a podcast by downloading, transcribing, identifying ads, and removing ad segments.
        Updates the existing job record for tracking progress.

        Args:
            post: The Post object containing the podcast to process
            job_id: Job ID of the existing job to update (required)
            cancel_callback: Optional callback to check for cancellation

        Returns:
            Path to the processed audio file
        """
        job = self.db_session.get(ProcessingJob, job_id)
        if not job:
            raise ProcessorException(f"Job with ID {job_id} not found")

        # Cache job and post attributes early to avoid ORM access after expire_all()
        # This includes relationship access like post.feed.title
        cached_post_guid = post.guid
        cached_post_title = post.title
        cached_feed_title = post.feed.title
        cached_job_id = job.id
        cached_current_step = job.current_step
        cached_ad_detection_strategy = getattr(
            post.feed, "ad_detection_strategy", "llm"
        )
        cached_chapter_filter_strings = getattr(
            post.feed, "chapter_filter_strings", None
        )

        try:
            self.logger.debug(
                "processor.process enter: job_id=%s post_guid=%s job_bound=%s",
                job_id,
                getattr(post, "guid", None),
                object_session(job) is not None,
            )
            # Update job to running status
            self.status_manager.update_job_status(
                job, "running", 0, "Starting processing"
            )

            # Validate post
            if not post.whitelisted:
                raise ProcessorException(
                    f"Post with GUID {cached_post_guid} not whitelisted"
                )

            # Check if processed audio already exists (database or disk)
            if self._check_existing_processed_audio(post):
                self.status_manager.update_job_status(
                    job, "completed", 4, "Processing complete", 100.0
                )
                return str(post.processed_audio_path)

            simulated_path = self._simulate_developer_processing(
                post,
                job,
                cached_post_guid,
                cached_post_title,
                cached_feed_title,
                cached_job_id,
            )
            if simulated_path:
                return simulated_path

            # Step 1: Download (if needed)
            self._handle_download_step(
                post, job, cached_post_guid, cached_post_title, cached_job_id
            )
            self._raise_if_cancelled(job, 1, cancel_callback)

            # Get processing paths and acquire lock
            processed_audio_path = self._acquire_processing_lock(
                post, job, cached_post_guid, cached_job_id, cached_feed_title
            )

            try:
                if os.path.exists(processed_audio_path):
                    self.logger.info(f"Audio already processed: {post}")
                    # Update the database with the processed audio path
                    self._remove_unprocessed_audio(post)
                    result = writer_client.update(
                        "Post",
                        post.id,
                        {
                            "processed_audio_path": processed_audio_path,
                            "unprocessed_audio_path": None,
                        },
                        wait=True,
                    )
                    if not result or not result.success:
                        raise RuntimeError(
                            getattr(result, "error", "Failed to update post")
                        )
                    self.status_manager.update_job_status(
                        job, "completed", 4, "Processing complete", 100.0
                    )
                    return processed_audio_path

                # Perform the main processing steps
                self._perform_processing_steps(
                    post,
                    job,
                    processed_audio_path,
                    cancel_callback,
                    cached_ad_detection_strategy,
                    cached_chapter_filter_strings,
                )

                self.logger.info(f"Processing podcast: {post} complete")
                return processed_audio_path
            finally:
                # Release lock using cached GUID without touching ORM state after potential rollback
                try:
                    if cached_post_guid is not None:
                        lock = PodcastProcessor.locks.get(cached_post_guid)
                        if lock is not None and lock.locked():
                            lock.release()
                except Exception:
                    # Best-effort lock release; avoid masking original exceptions
                    pass

        except ProcessorException as e:
            error_msg = str(e)
            if "Processing job in progress" in error_msg:
                self.status_manager.update_job_status(
                    job,
                    "failed",
                    cached_current_step,
                    "Another processing job is already running for this episode",
                )
            else:
                self.status_manager.update_job_status(
                    job, "failed", cached_current_step, error_msg
                )
            raise

        except Exception as e:
            self.logger.error(
                "processor.process unexpected error: job_id=%s %s",
                job_id,
                e,
                exc_info=True,
            )
            self.status_manager.update_job_status(
                job, "failed", cached_current_step, f"Unexpected error: {str(e)}"
            )
            raise

    def _acquire_processing_lock(
        self,
        post: Post,
        job: ProcessingJob,
        post_guid: str,
        job_id: str,
        feed_title: str,
    ) -> str:
        """
        Acquire processing lock for the post and return the processed audio path.
        Lock is now based on post GUID for better granularity and reliability.

        Args:
            post: The Post object to process
            job: The ProcessingJob for tracking
            post_guid: Cached post GUID to avoid ORM access
            job_id: Cached job ID to avoid ORM access
            feed_title: Cached feed title to avoid ORM access

        Returns:
            Path to the processed audio file

        Raises:
            ProcessorException: If lock cannot be acquired or paths are invalid
        """
        # Get processing paths
        working_paths = get_post_processed_audio_path_cached(post, feed_title)
        if working_paths is None:
            raise ProcessorException("Processed audio path not found")

        processed_audio_path = str(working_paths.post_processed_audio_path)

        # Use post GUID as lock key instead of file path for better granularity
        lock_key = post_guid

        # Acquire lock (this is where we cancel existing jobs if we can get the lock)
        locked = False
        with PodcastProcessor.lock_lock:
            if lock_key not in PodcastProcessor.locks:
                PodcastProcessor.locks[lock_key] = threading.Lock()
                PodcastProcessor.locks[lock_key].acquire(blocking=False)
                locked = True

        if not locked and not PodcastProcessor.locks[lock_key].acquire(blocking=False):
            raise ProcessorException("Processing job in progress")

        # Cancel existing jobs since we got the lock
        self.status_manager.cancel_existing_jobs(post_guid, job_id)

        self.make_dirs(working_paths)
        return processed_audio_path

    def _perform_processing_steps(
        self,
        post: Post,
        job: ProcessingJob,
        processed_audio_path: str,
        cancel_callback: Optional[Callable[[], bool]] = None,
        ad_detection_strategy: str = "llm",
        chapter_filter_strings: Optional[str] = None,
    ) -> None:
        """
        Perform the main processing steps based on the ad detection strategy.

        Args:
            post: The Post object to process
            job: The ProcessingJob for tracking
            processed_audio_path: Path where the processed audio will be saved
            cancel_callback: Optional callback to check for cancellation
            ad_detection_strategy: "llm" or "chapter"
            chapter_filter_strings: Comma-separated filter strings for chapter strategy
        """
        if ad_detection_strategy == "chapter":
            self._perform_chapter_based_processing(
                post, job, processed_audio_path, cancel_callback, chapter_filter_strings
            )
        else:
            self._perform_llm_based_processing(
                post, job, processed_audio_path, cancel_callback
            )

    def _perform_llm_based_processing(
        self,
        post: Post,
        job: ProcessingJob,
        processed_audio_path: str,
        cancel_callback: Optional[Callable[[], bool]] = None,
    ) -> None:
        """
        Perform LLM-based ad detection: transcription, classification, and audio processing.
        """
        # Step 2: Transcribe audio
        self.status_manager.update_job_status(
            job, "running", 2, "Transcribing audio", 50.0
        )
        transcript_segments = self.transcription_manager.transcribe(post)
        self._raise_if_cancelled(job, 2, cancel_callback)

        # Step 3: Classify ad segments
        self._classify_ad_segments(post, job, transcript_segments)
        self._raise_if_cancelled(job, 3, cancel_callback)

        # Step 4: Process audio (remove ad segments)
        self.status_manager.update_job_status(
            job, "running", 4, "Processing audio", 90.0
        )
        self.audio_processor.process_audio(post, processed_audio_path)

        self._finalize_processing(post, job, processed_audio_path)

    def _perform_chapter_based_processing(
        self,
        post: Post,
        job: ProcessingJob,
        processed_audio_path: str,
        cancel_callback: Optional[Callable[[], bool]] = None,
        chapter_filter_strings: Optional[str] = None,
    ) -> None:
        """
        Perform chapter-based ad detection: read chapters, filter by title, remove ads.
        Skips transcription and LLM classification.
        """
        from shared import defaults as DEFAULTS

        # Step 2: Read and filter chapters (skipping transcription)
        self.status_manager.update_job_status(
            job, "running", 2, "Reading chapters", 50.0
        )

        # Get filter strings (per-feed or global default)
        filter_csv = chapter_filter_strings or DEFAULTS.CHAPTER_FILTER_DEFAULT_STRINGS
        filter_strings = parse_filter_strings(filter_csv)

        detector = ChapterAdDetector(filter_strings=filter_strings, logger=self.logger)

        try:
            ad_segments, chapters_to_keep, chapters_to_remove = detector.detect(
                str(post.unprocessed_audio_path)
            )
        except ChapterDetectionError as e:
            raise ProcessorException(str(e)) from e

        self._raise_if_cancelled(job, 2, cancel_callback)

        # Step 3: Skip LLM classification (chapters already filtered)
        self.status_manager.update_job_status(
            job, "running", 3, "Chapters filtered", 75.0
        )
        self._raise_if_cancelled(job, 3, cancel_callback)

        # Step 4: Process audio (remove ad segments)
        self.status_manager.update_job_status(
            job, "running", 4, "Processing audio", 90.0
        )

        # Convert ad segments to milliseconds for audio processing
        ad_segments_ms = [(int(s * 1000), int(e * 1000)) for s, e in ad_segments]

        if ad_segments_ms:
            clip_segments_exact(
                ad_segments_ms=ad_segments_ms,
                in_path=str(post.unprocessed_audio_path),
                out_path=processed_audio_path,
            )
        else:
            # No ads found, copy the original file
            shutil.copyfile(str(post.unprocessed_audio_path), processed_audio_path)

        # Write adjusted chapters to the processed file
        write_adjusted_chapters(
            audio_path=processed_audio_path,
            chapters_to_keep=chapters_to_keep,
            removed_segments=ad_segments,
        )

        # Build chapter data for stats
        import json

        chapter_data = {
            "filter_strings": filter_strings,
            "chapters_kept": [
                {
                    "title": ch.title,
                    "start_time": round(ch.start_time_ms / 1000.0, 1),
                    "end_time": round(ch.end_time_ms / 1000.0, 1),
                }
                for ch in chapters_to_keep
            ],
            "chapters_removed": [
                {
                    "title": ch.title,
                    "start_time": round(ch.start_time_ms / 1000.0, 1),
                    "end_time": round(ch.end_time_ms / 1000.0, 1),
                }
                for ch in chapters_to_remove
            ],
        }

        self._finalize_processing(
            post, job, processed_audio_path, chapter_data=json.dumps(chapter_data)
        )

    def _finalize_processing(
        self,
        post: Post,
        job: ProcessingJob,
        processed_audio_path: str,
        chapter_data: Optional[str] = None,
    ) -> None:
        """
        Finalize processing: update database and mark job complete.
        """
        # Update the database with the processed audio path
        self._remove_unprocessed_audio(post)
        update_data = {
            "processed_audio_path": processed_audio_path,
            "unprocessed_audio_path": None,
        }
        if chapter_data is not None:
            update_data["chapter_data"] = chapter_data
        result = writer_client.update(
            "Post",
            post.id,
            update_data,
            wait=True,
        )
        if not result or not result.success:
            raise RuntimeError(getattr(result, "error", "Failed to update post"))

        # Mark job complete
        self.status_manager.update_job_status(
            job, "completed", 4, "Processing complete", 100.0
        )

    def _raise_if_cancelled(
        self,
        job: ProcessingJob,
        current_step: int,
        cancel_callback: Optional[Callable[[], bool]],
    ) -> None:
        """Helper to centralize cancellation checking and update job state."""
        if cancel_callback and cancel_callback():
            self.status_manager.update_job_status(
                job, "cancelled", current_step, "Cancellation requested"
            )
            raise ProcessorException("Cancelled")

    def _classify_ad_segments(
        self,
        post: Post,
        job: ProcessingJob,
        transcript_segments: List[TranscriptSegment],
    ) -> None:
        """
        Classify ad segments in the transcript.

        Args:
            post: The Post object being processed
            job: The ProcessingJob for tracking
            transcript_segments: The transcript segments to classify
        """
        self.status_manager.update_job_status(
            job, "running", 3, "Identifying ads", 75.0
        )
        user_prompt_template = self.get_user_prompt_template(
            DEFAULT_USER_PROMPT_TEMPLATE_PATH
        )
        system_prompt = self.get_system_prompt(DEFAULT_SYSTEM_PROMPT_PATH)
        self.ad_classifier.classify(
            transcript_segments=transcript_segments,
            system_prompt=system_prompt,
            user_prompt_template=user_prompt_template,
            post=post,
        )

    def _simulate_developer_processing(
        self,
        post: Post,
        job: ProcessingJob,
        post_guid: str,
        post_title: str,
        feed_title: str,
        job_id: str,
    ) -> Optional[str]:
        """Short-circuit processing for developer-mode test feeds.

        When developer mode is enabled and a post comes from a synthetic test feed
        (download_url contains "test-feed"), skip the full pipeline and copy a
        tiny bundled MP3 into the expected processed/unprocessed locations. This
        keeps the UI happy without relying on external downloads or LLM calls.
        """

        download_url = (post.download_url or "").lower()
        is_test_feed = "test-feed" in download_url or post_guid.startswith("test-guid")
        if not (self.config.developer_mode or is_test_feed):
            return None

        sample_audio = (
            Path(__file__).resolve().parent.parent / "tests" / "data" / "count_0_99.mp3"
        )
        if not sample_audio.exists():
            self.status_manager.update_job_status(
                job,
                "failed",
                job.current_step or 0,
                "Developer sample audio missing",
            )
            raise ProcessorException("Developer sample audio missing")

        self.status_manager.update_job_status(
            job,
            "running",
            1,
            "Simulating processing (developer mode)",
            25.0,
        )

        unprocessed_path = get_job_unprocessed_path(post_guid, job_id, post_title)
        unprocessed_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(sample_audio, unprocessed_path)

        processed_path = (
            get_srv_root()
            / sanitize_title(feed_title)
            / f"{sanitize_title(post_title)}.mp3"
        )
        processed_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(sample_audio, processed_path)

        result = writer_client.update(
            "Post",
            post.id,
            {
                "unprocessed_audio_path": str(unprocessed_path),
                "processed_audio_path": str(processed_path),
            },
            wait=True,
        )
        if not result or not result.success:
            raise RuntimeError(getattr(result, "error", "Failed to update post"))

        self.status_manager.update_job_status(
            job,
            "completed",
            4,
            "Processing complete (developer mode)",
            100.0,
        )

        return str(processed_path)

    def _handle_download_step(
        self,
        post: Post,
        job: ProcessingJob,
        post_guid: str,
        post_title: str,
        job_id: str,
    ) -> None:
        """
        Handle the download step with progress tracking and robust file checking.
        This method checks for existing files on disk before downloading.

        Args:
            post: The Post object being processed
            job: The ProcessingJob for tracking
            post_guid: Cached post GUID to avoid ORM access
            post_title: Cached post title to avoid ORM access
            job_id: Cached job ID to avoid ORM access
        """
        # If we have a path in the database, check if the file actually exists
        if post.unprocessed_audio_path is not None:
            if (
                os.path.exists(post.unprocessed_audio_path)
                and os.path.getsize(post.unprocessed_audio_path) > 0
            ):
                self.logger.debug(
                    f"Unprocessed audio already available at: {post.unprocessed_audio_path}"
                )
                return
            self.logger.info(
                f"Database path {post.unprocessed_audio_path} doesn't exist or is empty, resetting"
            )
            result = writer_client.update(
                "Post", post.id, {"unprocessed_audio_path": None}, wait=True
            )
            if not result or not result.success:
                raise RuntimeError(getattr(result, "error", "Failed to update post"))

        # Compute a unique per-job expected path
        expected_unprocessed_path = get_job_unprocessed_path(
            post_guid, job_id, post_title
        )

        if (
            expected_unprocessed_path.exists()
            and expected_unprocessed_path.stat().st_size > 0
        ):
            # Found a local unprocessed file
            unprocessed_path_str = str(expected_unprocessed_path.resolve())
            self.logger.info(
                f"Found existing unprocessed audio for post '{post_title}' at '{unprocessed_path_str}'. "
                "Updated the database path."
            )
            result = writer_client.update(
                "Post",
                post.id,
                {"unprocessed_audio_path": unprocessed_path_str},
                wait=True,
            )
            if not result or not result.success:
                raise RuntimeError(getattr(result, "error", "Failed to update post"))
            return

        # Need to download the file
        self.status_manager.update_job_status(
            job, "running", 1, "Downloading episode", 25.0
        )
        self.logger.info(f"Downloading post: {post_title}")
        download_path = self.downloader.download_episode(
            post, dest_path=str(expected_unprocessed_path)
        )
        if download_path is None:
            raise ProcessorException("Download failed")
        result = writer_client.update(
            "Post", post.id, {"unprocessed_audio_path": download_path}, wait=True
        )
        if not result or not result.success:
            raise RuntimeError(getattr(result, "error", "Failed to update post"))

    def make_dirs(self, processing_paths: ProcessingPaths) -> None:
        """Create necessary directories for output files."""
        if processing_paths.post_processed_audio_path:
            processing_paths.post_processed_audio_path.parent.mkdir(
                parents=True, exist_ok=True
            )

    def get_system_prompt(self, system_prompt_path: str) -> str:
        """Load the system prompt from a file."""
        with open(system_prompt_path, "r") as f:
            return f.read()

    def get_user_prompt_template(self, prompt_template_path: str) -> Template:
        """Load the user prompt template from a file."""
        with open(prompt_template_path, "r") as f:
            return Template(f.read())

    def remove_audio_files_and_reset_db(self, post_id: Optional[int]) -> None:
        """
        Removes unprocessed/processed audio for the given post from disk,
        and resets the DB fields so the next run will re-download the files.
        """
        if post_id is None:
            return

        post = self.db_session.get(Post, post_id)
        if not post:
            self.logger.warning(
                f"Could not find Post with ID {post_id} to remove files."
            )
            return

        if post.unprocessed_audio_path and os.path.isfile(post.unprocessed_audio_path):
            try:
                os.remove(post.unprocessed_audio_path)
                self.logger.info(
                    f"Removed unprocessed file: {post.unprocessed_audio_path}"
                )
            except OSError as e:
                self.logger.error(
                    f"Failed to remove unprocessed file '{post.unprocessed_audio_path}': {e}"
                )

        if post.processed_audio_path and os.path.isfile(post.processed_audio_path):
            try:
                os.remove(post.processed_audio_path)
                self.logger.info(f"Removed processed file: {post.processed_audio_path}")
            except OSError as e:
                self.logger.error(
                    f"Failed to remove processed file '{post.processed_audio_path}': {e}"
                )

        result = writer_client.update(
            "Post",
            post.id,
            {"unprocessed_audio_path": None, "processed_audio_path": None},
            wait=True,
        )
        if not result or not result.success:
            raise RuntimeError(getattr(result, "error", "Failed to update post"))

    def _remove_unprocessed_audio(self, post: Post) -> None:
        """
        Delete the downloaded source audio and clear its DB reference.

        Used after we have a finalized processed file so stale downloads do not
        accumulate on disk.
        """
        path = post.unprocessed_audio_path
        if not path:
            return

        if os.path.isfile(path):
            try:
                os.remove(path)
                self.logger.info("Removed unprocessed file after processing: %s", path)
            except OSError as exc:  # best-effort cleanup
                self.logger.warning(
                    "Failed to remove unprocessed file '%s': %s", path, exc
                )
        post.unprocessed_audio_path = None

    def _check_existing_processed_audio(self, post: Post) -> bool:
        """
        Check if processed audio already exists, either in database or on disk.
        Updates the database path if found on disk.

        Returns:
            True if processed audio exists and is valid, False otherwise
        """
        # If we have a path in the database, check if the file actually exists
        if post.processed_audio_path is not None:
            if (
                os.path.exists(post.processed_audio_path)
                and os.path.getsize(post.processed_audio_path) > 0
            ):
                self.logger.info(
                    f"Processed audio already available at: {post.processed_audio_path}"
                )
                return True
            self.logger.info(
                f"Database path {post.processed_audio_path} doesn't exist or is empty, resetting"
            )
            result = writer_client.update(
                "Post", post.id, {"processed_audio_path": None}, wait=True
            )
            if not result or not result.success:
                raise RuntimeError(getattr(result, "error", "Failed to update post"))

        # Check if file exists on disk at expected location
        safe_feed_title = sanitize_title(post.feed.title)
        safe_post_title = sanitize_title(post.title)
        expected_processed_path = (
            get_srv_root() / safe_feed_title / f"{safe_post_title}.mp3"
        )

        if (
            expected_processed_path.exists()
            and expected_processed_path.stat().st_size > 0
        ):
            # Found a local processed file
            processed_path_str = str(expected_processed_path.resolve())
            self.logger.info(
                f"Found existing processed audio for post '{post.title}' at '{processed_path_str}'. "
                "Updated the database path."
            )
            result = writer_client.update(
                "Post",
                post.id,
                {"processed_audio_path": processed_path_str},
                wait=True,
            )
            if not result or not result.success:
                raise RuntimeError(getattr(result, "error", "Failed to update post"))
            return True

        return False


class ProcessorException(Exception):
    """Exception raised for podcast processing errors."""
