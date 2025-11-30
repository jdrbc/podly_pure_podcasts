import logging
from typing import Any, List, Optional, cast

from sqlalchemy.exc import IntegrityError

from app.db_concurrency import commit_with_profile
from app.extensions import db
from app.models import Identification, ModelCall, Post, TranscriptSegment
from shared.config import (
    Config,
    GroqWhisperConfig,
    LocalWhisperConfig,
    RemoteWhisperConfig,
    TestWhisperConfig,
)

from .transcribe import (
    GroqWhisperTranscriber,
    LocalWhisperTranscriber,
    OpenAIWhisperTranscriber,
    TestWhisperTranscriber,
    Transcriber,
)


class TranscriptionManager:
    """Handles the transcription of podcast audio files."""

    def __init__(
        self,
        logger: logging.Logger,
        config: Config,
        model_call_query: Optional[Any] = None,
        segment_query: Optional[Any] = None,
        db_session: Optional[Any] = None,
        transcriber: Optional[Transcriber] = None,
    ):
        self.logger = logger
        self.config = config
        self.transcriber = transcriber or self._create_transcriber()
        self.model_call_query = model_call_query or ModelCall.query
        self.segment_query = segment_query or TranscriptSegment.query
        self.db_session = db_session or db.session

    def _create_transcriber(self) -> Transcriber:
        """Create the appropriate transcriber based on configuration."""
        assert self.config.whisper is not None, (
            "validate_whisper_config ensures that even if old style whisper "
            "config is given, it will be translated and config.whisper set."
        )

        if isinstance(self.config.whisper, TestWhisperConfig):
            return TestWhisperTranscriber(self.logger)
        if isinstance(self.config.whisper, RemoteWhisperConfig):
            return OpenAIWhisperTranscriber(self.logger, self.config.whisper)
        if isinstance(self.config.whisper, LocalWhisperConfig):
            return LocalWhisperTranscriber(self.logger, self.config.whisper.model)
        if isinstance(self.config.whisper, GroqWhisperConfig):
            return GroqWhisperTranscriber(self.logger, self.config.whisper)
        raise ValueError(f"unhandled whisper config {self.config.whisper}")

    def _check_existing_transcription(
        self, post: Post
    ) -> Optional[List[TranscriptSegment]]:
        """Checks for existing successful transcription and returns segments if valid."""
        existing_whisper_call = (
            self.model_call_query.filter_by(
                post_id=post.id,
                model_name=self.transcriber.model_name,
                status="success",
            )
            .order_by(ModelCall.timestamp.desc())
            .first()
        )

        if existing_whisper_call:
            self.logger.info(
                f"Found existing successful Whisper ModelCall {existing_whisper_call.id} for post {post.id}."
            )
            db_segments: List[TranscriptSegment] = (
                self.segment_query.filter_by(post_id=post.id)
                .order_by(TranscriptSegment.sequence_num)
                .all()
            )
            if db_segments:
                if (
                    existing_whisper_call.last_segment_sequence_num
                    == len(db_segments) - 1
                ):
                    self.logger.info(
                        f"Returning {len(db_segments)} existing transcript segments from database for post {post.id}."
                    )
                    return db_segments
                self.logger.warning(
                    f"ModelCall {existing_whisper_call.id} for post {post.id} indicates {existing_whisper_call.last_segment_sequence_num + 1} segments, but found {len(db_segments)} in DB. Re-transcribing."
                )
            else:
                self.logger.warning(
                    f"Successful ModelCall {existing_whisper_call.id} found for post {post.id}, but no transcript segments in DB. Re-transcribing."
                )
        else:
            self.logger.info(
                f"No existing successful Whisper ModelCall found for post {post.id} with model {self.transcriber.model_name}. Proceeding to transcribe."
            )
        return None

    def _get_or_create_whisper_model_call(self, post: Post) -> ModelCall:
        """Create or reuse the placeholder ModelCall row for a Whisper run."""
        placeholder_filters = {
            "post_id": post.id,
            "model_name": self.transcriber.model_name,
            "first_segment_sequence_num": 0,
            "last_segment_sequence_num": -1,
        }
        reset_fields = {
            "status": "pending",
            "prompt": "Whisper transcription job",
            "retry_attempts": 0,
            "error_message": None,
            "response": None,
        }

        existing = cast(
            Optional[ModelCall],
            self.model_call_query.filter_by(**placeholder_filters)
            .order_by(ModelCall.timestamp.desc())
            .first(),
        )
        if existing:
            self.logger.info(
                "Reusing existing Whisper ModelCall %s for post %s (status=%s). Resetting to pending if needed.",
                existing.id,
                post.id,
                existing.status,
            )
            needs_update = any(
                getattr(existing, field) != value
                for field, value in reset_fields.items()
            )
            if not needs_update:
                return existing

            # Atomic single update to minimize lock churn
            self.model_call_query.filter_by(id=existing.id).update(
                reset_fields, synchronize_session=False
            )
            commit_with_profile(
                self.db_session,
                must_succeed=True,
                context="reuse_whisper_model_call",
                logger_obj=self.logger,
            )
            self.db_session.expire(existing)
            return existing

        current_whisper_call = ModelCall(
            post_id=post.id,
            model_name=self.transcriber.model_name,
            first_segment_sequence_num=0,  # Placeholder, will be updated
            last_segment_sequence_num=-1,  # Placeholder, indicates no segments yet
            prompt="Whisper transcription job",  # Standardized prompt for Whisper calls
            status="pending",
        )
        try:
            self.db_session.add(current_whisper_call)
            commit_with_profile(
                self.db_session,
                must_succeed=True,
                context="create_whisper_model_call",
                logger_obj=self.logger,
            )
        except IntegrityError:
            # Another process/thread created the same unique ModelCall concurrently
            self.db_session.rollback()
            current_whisper_call = cast(
                Optional[ModelCall],
                self.model_call_query.filter_by(**placeholder_filters)
                .order_by(ModelCall.timestamp.desc())
                .first(),
            )
            if not current_whisper_call:
                # If not found despite conflict, re-raise
                raise
            self.logger.info(
                "Found concurrent Whisper ModelCall %s for post %s after IntegrityError. Resetting to pending if needed.",
                current_whisper_call.id,
                post.id,
            )
            needs_update = any(
                getattr(current_whisper_call, field) != value
                for field, value in reset_fields.items()
            )
            if needs_update:
                self.model_call_query.filter_by(id=current_whisper_call.id).update(
                    reset_fields, synchronize_session=False
                )
                commit_with_profile(
                    self.db_session,
                    must_succeed=True,
                    context="recover_whisper_model_call",
                    logger_obj=self.logger,
                )

        return current_whisper_call

    def transcribe(self, post: Post) -> List[TranscriptSegment]:
        """
        Transcribes a podcast audio file, or retrieves existing transcription.

        Args:
            post: The Post object containing the podcast audio to transcribe

        Returns:
            A list of TranscriptSegment objects with the transcription results
        """
        self.logger.info(
            f"Starting transcription process for post {post.id} using {self.transcriber.model_name}"
        )

        existing_segments = self._check_existing_transcription(post)
        if existing_segments is not None:
            return existing_segments

        # Create or reuse the ModelCall record for this transcription attempt
        current_whisper_call = self._get_or_create_whisper_model_call(post)
        self.logger.info(
            f"Prepared Whisper ModelCall {current_whisper_call.id} for post {post.id}."
        )

        try:
            self.logger.info(
                f"[TRANSCRIBE_START] Calling transcriber {self.transcriber.model_name} for post {post.id}, audio: {post.unprocessed_audio_path}"
            )
            # Expire session state before long-running transcription to avoid stale locks
            self.db_session.expire_all()

            pydantic_segments = self.transcriber.transcribe(post.unprocessed_audio_path)
            self.logger.info(
                f"[TRANSCRIBE_COMPLETE] Transcription by {self.transcriber.model_name} for post {post.id} resulted in {len(pydantic_segments)} segments."
            )

            self._delete_existing_segments_for_post(post.id)

            db_transcript_segments = self._persist_segments(post.id, pydantic_segments)

            # Update ModelCall with success status and details
            current_whisper_call.first_segment_sequence_num = 0
            current_whisper_call.last_segment_sequence_num = (
                len(db_transcript_segments) - 1
            )
            current_whisper_call.response = (
                f"{len(db_transcript_segments)} segments transcribed."
            )
            current_whisper_call.status = "success"

            commit_with_profile(
                self.db_session,
                must_succeed=True,
                context="transcription_success",
                logger_obj=self.logger,
            )
            self.logger.info(
                f"Successfully stored {len(db_transcript_segments)} transcript segments and updated ModelCall {current_whisper_call.id} for post {post.id}."
            )
            return db_transcript_segments

        except Exception as e:
            self.logger.error(
                f"Transcription failed for post {post.id} using {self.transcriber.model_name}. Error: {e}",
                exc_info=True,
            )
            self.db_session.rollback()  # Rollback any potential partial additions from the try block

            # Re-fetch the ModelCall using session.get() to avoid cross-session conflicts
            call_to_update = (
                self.db_session.get(ModelCall, current_whisper_call.id)
                if current_whisper_call.id
                else None
            )
            if call_to_update:
                call_to_update.status = "failed_permanent"
                call_to_update.error_message = str(e)
                commit_with_profile(
                    self.db_session,
                    must_succeed=True,
                    context="transcription_failed",
                    logger_obj=self.logger,
                )
                self.logger.info(
                    f"Updated ModelCall {call_to_update.id} to status 'failed_permanent' for post {post.id}."
                )
            else:
                # This case should be rare if the initial commit of pending status was successful.
                self.logger.error(
                    f"Could not find ModelCall to update failure status for post {post.id} after transcription error."
                )

            raise

    # ------------------------ Internal helpers ------------------------
    def _delete_existing_segments_for_post(self, post_id: int) -> None:
        """Delete existing transcript segments and their identifications for a post."""
        # Expire (don't rollback!) to release any stale state without detaching objects.
        # A rollback would detach the ModelCall we just committed, causing
        # "not persistent within this Session" errors later.
        self.db_session.expire_all()

        # Smaller batches reduce SQLite lock hold times; no_autoflush prevents unrelated
        # dirty objects from being flushed as part of the delete.
        batch_size = 50
        batch_num = 0
        with self.db_session.no_autoflush:
            while True:
                ids_batch = [
                    row[0]
                    for row in self.db_session.query(TranscriptSegment.id)
                    .filter_by(post_id=post_id)
                    .limit(batch_size)
                    .all()
                ]
                if not ids_batch:
                    break

                batch_num += 1
                self.logger.info(
                    "[TRANSCRIPT_DELETE] post_id=%s batch=%s size=%s",
                    post_id,
                    batch_num,
                    len(ids_batch),
                )
                # Delete identifications for this batch
                try:
                    self.logger.debug(
                        "[TRANSCRIPT_DELETE] post_id=%s batch=%s deleting identifications and segments",
                        post_id,
                        batch_num,
                    )
                    self.db_session.query(Identification).filter(
                        Identification.transcript_segment_id.in_(ids_batch)
                    ).delete(synchronize_session=False)

                    # Delete transcript segments for this batch
                    # NOTE: Must use self.db_session.query() instead of self.segment_query
                    # to ensure we use the same session. Using TranscriptSegment.query
                    # (the Flask-SQLAlchemy scoped session) causes deadlock with SQLite
                    # pessimistic locking when another query on self.db_session holds
                    # the write lock.
                    self.db_session.query(TranscriptSegment).filter(
                        TranscriptSegment.id.in_(ids_batch)
                    ).delete(synchronize_session=False)

                    # Commit per batch to release locks quickly
                    commit_with_profile(
                        self.db_session,
                        must_succeed=True,
                        context="delete_transcript_segments_batch",
                        logger_obj=self.logger,
                    )
                    self.logger.info(
                        "[TRANSCRIPT_DELETE] post_id=%s batch=%s committed",
                        post_id,
                        batch_num,
                    )
                except Exception as exc:  # pylint: disable=broad-except
                    self.logger.error(
                        "[TRANSCRIPT_DELETE] post_id=%s batch=%s failed during delete/commit: %s",
                        post_id,
                        batch_num,
                        exc,
                        exc_info=True,
                    )
                    try:
                        self.db_session.rollback()
                    except Exception:  # pylint: disable=broad-except
                        self.logger.error(
                            "[TRANSCRIPT_DELETE] post_id=%s batch=%s rollback failed after error",
                            post_id,
                            batch_num,
                            exc_info=True,
                        )
                    raise

    def _persist_segments(
        self, post_id: int, pydantic_segments: List[Any]
    ) -> List[TranscriptSegment]:
        """Persist pydantic segments to DB and return created ORM objects."""
        db_transcript_segments: List[TranscriptSegment] = []
        for i, segment_data in enumerate(pydantic_segments or []):
            start_time = round(segment_data.start, 1)
            end_time = round(segment_data.end, 1)
            db_segment = TranscriptSegment(
                post_id=post_id,
                sequence_num=i,
                start_time=start_time,
                end_time=end_time,
                text=segment_data.text,
            )
            db_transcript_segments.append(db_segment)
        if db_transcript_segments:
            self.db_session.add_all(db_transcript_segments)
        return db_transcript_segments
