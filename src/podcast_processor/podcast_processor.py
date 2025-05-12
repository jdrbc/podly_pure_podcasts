import logging
import os
import threading
from typing import Any, Dict, Optional

import litellm
from jinja2 import Template

from app import db, logger
from app.models import Post
from podcast_processor.ad_classifier import AdClassifier
from podcast_processor.audio_processor import AudioProcessor
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
        db_session: Optional[Any] = None,
    ) -> None:
        super().__init__()
        self.logger = logger or logging.getLogger("global_logger")
        self.output_dir = "srv"
        self.config: Config = config
        self.db_session = db_session or db.session

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

    def process(self, post: Post, blocking: bool) -> str:
        """
        Process a podcast by transcribing, identifying ads, and removing ad segments.

        Args:
            post: The Post object containing the podcast to process
            blocking: Whether to block if another process is already processing this podcast

        Returns:
            Path to the processed audio file
        """
        locked = False
        working_paths = get_post_processed_audio_path(post)
        if working_paths is None:
            raise ProcessorException("Processed audio path not found")

        processed_audio_path = str(working_paths.post_processed_audio_path)
        with PodcastProcessor.lock_lock:
            if processed_audio_path not in PodcastProcessor.locks:
                PodcastProcessor.locks[processed_audio_path] = threading.Lock()
                PodcastProcessor.locks[
                    processed_audio_path
                ].acquire()  # no contention expected
                locked = True

        if not locked and not PodcastProcessor.locks[processed_audio_path].acquire(
            blocking=blocking
        ):
            raise ProcessorException("Processing job in progress")

        try:
            if os.path.exists(processed_audio_path):
                self.logger.info(f"Audio already processed: {post}")
                return processed_audio_path

            self.make_dirs(working_paths)

            # Step 1: Transcribe audio
            transcript_segments = self.transcription_manager.transcribe(post)

            # Step 2: Classify ad segments
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

            # Step 3: Process audio (remove ad segments)
            self.audio_processor.process_audio(post, processed_audio_path)

            self.logger.info(f"Processing podcast: {post} complete")
            return processed_audio_path
        finally:
            PodcastProcessor.locks[processed_audio_path].release()

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


class ProcessorException(Exception):
    """Exception raised for podcast processing errors."""
