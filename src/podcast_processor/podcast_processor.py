import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

import litellm
from jinja2 import Template

from app import db, logger
from app.models import Post, ProcessingJob, TranscriptSegment
from podcast_processor.ad_classifier import AdClassifier
from podcast_processor.audio_processor import AudioProcessor
from podcast_processor.podcast_downloader import PodcastDownloader, sanitize_title
from podcast_processor.processing_status_manager import ProcessingStatusManager
from podcast_processor.transcription_manager import TranscriptionManager
from shared.config import Config
from shared.processing_paths import ProcessingPaths, paths_from_unprocessed_path


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


class PodcastProcessor:
    """
    Main coordinator for podcast processing workflow.
    Delegates to specialized components for transcription, ad classification, and audio processing.
    """

    lock_lock = threading.Lock()
    locks: Dict[str, threading.Lock] = {}

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
        self.output_dir = "srv"
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

    def process_by_guid(self, p_guid: str) -> Optional[str]:
        """
        Process a podcast episode by GUID, handling post lookup and validation.
        This is a convenience method that wraps the main process method.

        Args:
            p_guid: The GUID of the post to process

        Returns:
            Path to the processed audio file, or None if processing failed

        Raises:
            ProcessorException: If the post is not found, not whitelisted, or processing fails
        """
        post = Post.query.filter_by(guid=p_guid).first()
        if post is None:
            self.logger.warning(f"Post with GUID: {p_guid} not found")
            raise ProcessorException(f"Post with GUID: {p_guid} not found")

        if not post.whitelisted:
            self.logger.warning(f"Post: {post.title} is not whitelisted")
            raise ProcessorException(f"Post with GUID: {p_guid} not whitelisted")

        self.logger.info(f"Processing post '{post.title}' (GUID: {p_guid})")

        # Use the existing process method which handles all the download and processing logic
        output_path = self.process(post)

        # Update the post's processed_audio_path in the database
        post.processed_audio_path = output_path
        self.db_session.commit()

        return output_path

    def process(self, post: Post, job_id: Optional[str] = None) -> str:
        """
        Process a podcast by downloading, transcribing, identifying ads, and removing ad segments.
        Creates a job record for tracking progress and handles all steps internally.

        Args:
            post: The Post object containing the podcast to process
            job_id: Optional job ID to use, if not provided one will be generated

        Returns:
            Path to the processed audio file
        """
        # Create job for tracking - generate ID if not provided
        if job_id is None:
            job_id = self.status_manager.generate_job_id()
        job = self.status_manager.create_job(post.guid, job_id)

        try:
            # Update job to running status
            self.status_manager.update_job_status(
                job, "running", 0, "Starting processing"
            )

            # Validate post
            if not post.whitelisted:
                raise ProcessorException(f"Post with GUID {post.guid} not whitelisted")

            # Check if processed audio already exists (database or disk)
            if self._check_existing_processed_audio(post):
                self.status_manager.update_job_status(
                    job, "completed", 4, "Processing complete", 100.0
                )
                return str(post.processed_audio_path)

            # Step 1: Download (if needed)
            self._handle_download_step(post, job)

            # Get processing paths and acquire lock
            processed_audio_path = self._acquire_processing_lock(post, job)

            try:
                if os.path.exists(processed_audio_path):
                    self.logger.info(f"Audio already processed: {post}")
                    # Update the database with the processed audio path
                    post.processed_audio_path = processed_audio_path
                    self.db_session.commit()
                    self.status_manager.update_job_status(
                        job, "completed", 4, "Processing complete", 100.0
                    )
                    return processed_audio_path

                # Perform the main processing steps
                self._perform_processing_steps(post, job, processed_audio_path)

                self.logger.info(f"Processing podcast: {post} complete")
                return processed_audio_path
            finally:
                PodcastProcessor.locks[processed_audio_path].release()

        except ProcessorException as e:
            error_msg = str(e)
            if "Processing job in progress" in error_msg:
                self.status_manager.update_job_status(
                    job,
                    "failed",
                    job.current_step,
                    "Another processing job is already running for this episode",
                )
            else:
                self.status_manager.update_job_status(
                    job, "failed", job.current_step, error_msg
                )
            raise

        except Exception as e:
            self.status_manager.update_job_status(
                job, "failed", job.current_step, f"Unexpected error: {str(e)}"
            )
            raise

    def _acquire_processing_lock(self, post: Post, job: ProcessingJob) -> str:
        """
        Acquire processing lock for the post and return the processed audio path.

        Args:
            post: The Post object to process
            job: The ProcessingJob for tracking

        Returns:
            Path to the processed audio file

        Raises:
            ProcessorException: If lock cannot be acquired or paths are invalid
        """
        # Get processing paths
        working_paths = get_post_processed_audio_path(post)
        if working_paths is None:
            raise ProcessorException("Processed audio path not found")

        processed_audio_path = str(working_paths.post_processed_audio_path)

        # Acquire lock (this is where we cancel existing jobs if we can get the lock)
        locked = False
        with PodcastProcessor.lock_lock:
            if processed_audio_path not in PodcastProcessor.locks:
                PodcastProcessor.locks[processed_audio_path] = threading.Lock()
                PodcastProcessor.locks[processed_audio_path].acquire(blocking=False)
                locked = True

        if not locked and not PodcastProcessor.locks[processed_audio_path].acquire(
            blocking=False
        ):
            raise ProcessorException("Processing job in progress")

        # Cancel existing jobs since we got the lock
        self.status_manager.cancel_existing_jobs(post.guid, job.id)

        self.make_dirs(working_paths)
        return processed_audio_path

    def _perform_processing_steps(
        self, post: Post, job: ProcessingJob, processed_audio_path: str
    ) -> None:
        """
        Perform the main processing steps: transcription, ad classification, and audio processing.

        Args:
            post: The Post object to process
            job: The ProcessingJob for tracking
            processed_audio_path: Path where the processed audio will be saved
        """
        # Step 2: Transcribe audio
        self.status_manager.update_job_status(
            job, "running", 2, "Transcribing audio", 50.0
        )
        transcript_segments = self.transcription_manager.transcribe(post)

        # Step 3: Classify ad segments
        self._classify_ad_segments(post, job, transcript_segments)

        # Step 4: Process audio (remove ad segments)
        self.status_manager.update_job_status(
            job, "running", 4, "Processing audio", 90.0
        )
        self.audio_processor.process_audio(post, processed_audio_path)

        # Update the database with the processed audio path
        post.processed_audio_path = processed_audio_path
        self.db_session.commit()

        # Mark job complete
        self.status_manager.update_job_status(
            job, "completed", 4, "Processing complete", 100.0
        )

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
            self.config.processing.user_prompt_template_path
        )
        system_prompt = self.get_system_prompt(
            self.config.processing.system_prompt_path
        )
        self.ad_classifier.classify(
            transcript_segments=transcript_segments,
            system_prompt=system_prompt,
            user_prompt_template=user_prompt_template,
            post=post,
        )

    def _handle_download_step(self, post: Post, job: ProcessingJob) -> None:
        """
        Handle the download step with progress tracking and robust file checking.
        This method checks for existing files on disk before downloading.
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
            post.unprocessed_audio_path = None
            self.db_session.commit()

        # Check if file exists on disk at expected location
        safe_post_title = sanitize_title(post.title)
        post_subdir = safe_post_title.replace(".mp3", "")
        expected_unprocessed_path = Path("in") / post_subdir / f"{safe_post_title}.mp3"

        if (
            expected_unprocessed_path.exists()
            and expected_unprocessed_path.stat().st_size > 0
        ):
            # Found a local unprocessed file
            post.unprocessed_audio_path = str(expected_unprocessed_path.resolve())
            self.logger.info(
                f"Found existing unprocessed audio for post '{post.title}' at '{post.unprocessed_audio_path}'. "
                "Updated the database path."
            )
            self.db_session.commit()
            return

        # Need to download the file
        self.status_manager.update_job_status(
            job, "running", 1, "Downloading episode", 25.0
        )
        self.logger.info(f"Downloading post: {post.title}")
        download_path = self.downloader.download_episode(post)
        if download_path is None:
            raise ProcessorException("Download failed")
        post.unprocessed_audio_path = download_path
        self.db_session.commit()

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

        post = Post.query.get(post_id)
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

        post.unprocessed_audio_path = None
        post.processed_audio_path = None
        self.db_session.commit()

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
            post.processed_audio_path = None
            self.db_session.commit()

        # Check if file exists on disk at expected location
        safe_feed_title = sanitize_title(post.feed.title)
        safe_post_title = sanitize_title(post.title)
        expected_processed_path = (
            Path("srv") / safe_feed_title / f"{safe_post_title}.mp3"
        )

        if (
            expected_processed_path.exists()
            and expected_processed_path.stat().st_size > 0
        ):
            # Found a local processed file
            post.processed_audio_path = str(expected_processed_path.resolve())
            self.logger.info(
                f"Found existing processed audio for post '{post.title}' at '{post.processed_audio_path}'. "
                "Updated the database path."
            )
            self.db_session.commit()
            return True

        return False


class ProcessorException(Exception):
    """Exception raised for podcast processing errors."""
