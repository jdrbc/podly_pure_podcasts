import logging
import time
from typing import Any, List, Optional, Union

import litellm
from jinja2 import Template
from litellm.exceptions import InternalServerError
from litellm.types.utils import Choices
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app import db
from app.models import Identification, ModelCall, Post, TranscriptSegment
from podcast_processor.model_output import (
    AdSegmentPredictionList,
    clean_and_parse_model_output,
)
from podcast_processor.prompt import transcript_excerpt_for_prompt
from podcast_processor.token_rate_limiter import (
    TokenRateLimiter,
    configure_rate_limiter_for_model,
)
from podcast_processor.transcribe import Segment
from shared.config import Config, TestWhisperConfig


class AdClassifier:
    """Handles the classification of ad segments in podcast transcripts."""

    def __init__(
        self,
        config: Config,
        logger: Optional[logging.Logger] = None,
        model_call_query: Optional[Any] = None,
        identification_query: Optional[Any] = None,
        db_session: Optional[Any] = None,
    ):
        self.config = config
        self.logger = logger or logging.getLogger("global_logger")
        self.model_call_query = model_call_query or ModelCall.query
        self.identification_query = identification_query or Identification.query
        self.db_session = db_session or db.session

        # Initialize rate limiter for the configured model
        self.rate_limiter: Optional[TokenRateLimiter]
        if self.config.llm_enable_token_rate_limiting:
            tokens_per_minute = self.config.llm_max_input_tokens_per_minute
            if tokens_per_minute is None:
                # Use model-specific defaults
                self.rate_limiter = configure_rate_limiter_for_model(
                    self.config.llm_model
                )
            else:
                # Use custom limit
                from podcast_processor.token_rate_limiter import get_rate_limiter

                self.rate_limiter = get_rate_limiter(tokens_per_minute)
                self.logger.info(
                    f"Using custom token rate limit: {tokens_per_minute}/min"
                )
        else:
            self.rate_limiter = None
            self.logger.info("Token rate limiting disabled")

    def classify(
        self,
        *,
        transcript_segments: List[TranscriptSegment],
        system_prompt: str,
        user_prompt_template: Template,
        post: Post,
    ) -> None:
        """
        Classifies transcript segments to identify ad segments.

        Args:
            transcript_segments: List of transcript segments to classify
            system_prompt: System prompt for the LLM
            user_prompt_template: User prompt template for the LLM
            post: Post containing the podcast to classify
        """
        self.logger.info(
            f"Starting ad classification for post {post.id} with {len(transcript_segments)} segments."
        )

        if not transcript_segments:
            self.logger.info(
                f"No transcript segments to classify for post {post.id}. Skipping."
            )
            return

        num_segments_per_prompt = self.config.processing.num_segments_to_input_to_prompt
        for i in range(0, len(transcript_segments), num_segments_per_prompt):
            self._process_segment_chunk(
                transcript_segments=transcript_segments,
                start_idx=i,
                end_idx=min(i + num_segments_per_prompt, len(transcript_segments)),
                system_prompt=system_prompt,
                user_prompt_template=user_prompt_template,
                post=post,
            )

    def _process_segment_chunk(
        self,
        *,
        transcript_segments: List[TranscriptSegment],
        start_idx: int,
        end_idx: int,
        system_prompt: str,
        user_prompt_template: Template,
        post: Post,
    ) -> None:
        """Process a chunk of transcript segments for classification."""
        current_chunk_db_segments = transcript_segments[start_idx:end_idx]
        if not current_chunk_db_segments:
            return

        first_seq_num = current_chunk_db_segments[0].sequence_num
        last_seq_num = current_chunk_db_segments[-1].sequence_num

        self.logger.info(
            f"Processing classification for post {post.id}, segments {first_seq_num}-{last_seq_num}."
        )

        user_prompt_str = self._generate_user_prompt(
            current_chunk_db_segments=current_chunk_db_segments,
            post=post,
            user_prompt_template=user_prompt_template,
            start_idx=start_idx,
            end_idx=end_idx,
            total_segments=len(transcript_segments),
        )

        model_call = self._get_or_create_model_call(
            post=post,
            first_seq_num=first_seq_num,
            last_seq_num=last_seq_num,
            user_prompt_str=user_prompt_str,
        )

        if not model_call:
            self.logger.error("ModelCall object is unexpectedly None. Skipping chunk.")
            return

        if self._should_call_llm(model_call):
            self._perform_llm_call(
                model_call=model_call,
                system_prompt=system_prompt,
            )

        if model_call.status == "success" and model_call.response:
            self._process_successful_response(
                model_call=model_call,
                current_chunk_db_segments=current_chunk_db_segments,
            )
        elif model_call.status != "success":
            self.logger.info(
                f"LLM call for ModelCall {model_call.id} was not successful (status: {model_call.status}). No identifications to process."
            )

    def _generate_user_prompt(
        self,
        *,
        current_chunk_db_segments: List[TranscriptSegment],
        post: Post,
        user_prompt_template: Template,
        start_idx: int,
        end_idx: int,
        total_segments: int,
    ) -> str:
        """Generate the user prompt string for the LLM."""
        temp_pydantic_segments_for_prompt = [
            Segment(start=db_seg.start_time, end=db_seg.end_time, text=db_seg.text)
            for db_seg in current_chunk_db_segments
        ]

        return user_prompt_template.render(
            podcast_title=post.title,
            podcast_topic=post.description if post.description else "",
            transcript=transcript_excerpt_for_prompt(
                segments=temp_pydantic_segments_for_prompt,
                includes_start=(start_idx == 0),
                includes_end=(end_idx == total_segments),
            ),
        )

    def _get_or_create_model_call(
        self,
        *,
        post: Post,
        first_seq_num: int,
        last_seq_num: int,
        user_prompt_str: str,
    ) -> Optional[ModelCall]:
        """Get an existing ModelCall or create a new one."""
        model = self.config.llm_model
        model_call: Optional[ModelCall] = (
            self.model_call_query.filter_by(
                post_id=post.id,
                model_name=model,
                first_segment_sequence_num=first_seq_num,
                last_segment_sequence_num=last_seq_num,
            )
            .order_by(ModelCall.timestamp.desc())
            .first()
        )

        if model_call:
            self.logger.info(
                f"Found existing ModelCall {model_call.id} (status: {model_call.status}) for post {post.id}, segments {first_seq_num}-{last_seq_num}."
            )
            if model_call.status in ["pending", "failed_retries"]:
                model_call.status = "pending"
                model_call.prompt = user_prompt_str
                model_call.retry_attempts = 0
                model_call.error_message = None
                model_call.response = None
        else:
            self.logger.info(
                f"Creating new ModelCall for post {post.id}, segments {first_seq_num}-{last_seq_num}, model {model}."
            )
            model_call = ModelCall(
                post_id=post.id,
                first_segment_sequence_num=first_seq_num,
                last_segment_sequence_num=last_seq_num,
                model_name=model,
                prompt=user_prompt_str,
                status="pending",
            )
            try:
                self.db_session.add(model_call)
                self.db_session.commit()
            except IntegrityError:
                # Someone else created the same unique row concurrently; fetch and reuse
                self.db_session.rollback()
                model_call = (
                    self.model_call_query.filter_by(
                        post_id=post.id,
                        model_name=model,
                        first_segment_sequence_num=first_seq_num,
                        last_segment_sequence_num=last_seq_num,
                    )
                    .order_by(ModelCall.timestamp.desc())
                    .first()
                )
                if not model_call:
                    raise
                # If found, update prompt/status to pending for retry
                model_call.status = "pending"
                model_call.prompt = user_prompt_str
                model_call.retry_attempts = 0
                model_call.error_message = None
                model_call.response = None

        # If we got here without creating, ensure commit for any field updates
        if self.db_session.is_active:
            self.db_session.commit()
        return model_call

    def _should_call_llm(self, model_call: ModelCall) -> bool:
        """Determine if an LLM call should be made."""
        return model_call.status not in ("success", "failed_permanent")

    def _perform_llm_call(self, *, model_call: ModelCall, system_prompt: str) -> None:
        """Perform the LLM call for classification."""
        self.logger.info(
            f"Calling LLM for ModelCall {model_call.id} (post {model_call.post_id}, segments {model_call.first_segment_sequence_num}-{model_call.last_segment_sequence_num})."
        )
        try:
            if isinstance(self.config.whisper, TestWhisperConfig):
                self._handle_test_mode_call(model_call)
            else:
                self._call_model(model_call_obj=model_call, system_prompt=system_prompt)
        except Exception as e:  # pylint: disable=broad-exception-caught
            self.logger.error(
                f"LLM interaction via _call_model for ModelCall {model_call.id} resulted in an exception: {e}",
                exc_info=True,
            )

    def _handle_test_mode_call(self, model_call: ModelCall) -> None:
        """Handle LLM call in test mode."""
        self.logger.info("Test mode: Simulating successful LLM call for classify.")
        model_call.response = AdSegmentPredictionList(ad_segments=[]).model_dump_json()
        model_call.status = "success"
        model_call.error_message = None
        model_call.retry_attempts = 1
        self.db_session.add(model_call)
        self.db_session.commit()

    def _process_successful_response(
        self,
        *,
        model_call: ModelCall,
        current_chunk_db_segments: List[TranscriptSegment],
    ) -> None:
        """Process a successful LLM response and create Identification records."""
        self.logger.info(
            f"LLM call for ModelCall {model_call.id} was successful. Parsing response."
        )
        try:
            prediction_list = clean_and_parse_model_output(model_call.response)
            created_identification_count = self._create_identifications(
                prediction_list=prediction_list,
                current_chunk_db_segments=current_chunk_db_segments,
                model_call=model_call,
            )

            if created_identification_count > 0:
                self.logger.info(
                    f"Created {created_identification_count} new Identification records for ModelCall {model_call.id}."
                )
            self.db_session.commit()
        except (ValidationError, AssertionError) as e:
            self.logger.error(
                f"Error processing LLM response for ModelCall {model_call.id}: {e}",
                exc_info=True,
            )

    def _create_identifications(
        self,
        *,
        prediction_list: AdSegmentPredictionList,
        current_chunk_db_segments: List[TranscriptSegment],
        model_call: ModelCall,
    ) -> int:
        """Create Identification records from the prediction list."""
        created_count = 0
        for pred in prediction_list.ad_segments:
            if pred.confidence < self.config.output.min_confidence:
                self.logger.info(
                    f"Ad prediction offset {pred.segment_offset:.2f} for post {model_call.post_id} ignored due to low confidence: {pred.confidence:.2f} (min: {self.config.output.min_confidence})"
                )
                continue

            matched_segment = self._find_matching_segment(
                segment_offset=pred.segment_offset,
                current_chunk_db_segments=current_chunk_db_segments,
            )

            if not matched_segment:
                self.logger.warning(
                    f"Could not find matching TranscriptSegment for ad prediction offset {pred.segment_offset:.2f} in post {model_call.post_id}, chunk {model_call.first_segment_sequence_num}-{model_call.last_segment_sequence_num}. Confidence: {pred.confidence:.2f}"
                )
                continue

            if not self._identification_exists(matched_segment.id, model_call.id):
                identification = Identification(
                    transcript_segment_id=matched_segment.id,
                    model_call_id=model_call.id,
                    label="ad",
                    confidence=pred.confidence,
                )
                self.db_session.add(identification)
                created_count += 1
            else:
                self.logger.info(
                    f"Identification for segment {matched_segment.id} from ModelCall {model_call.id} already exists. Skipping."
                )

        return created_count

    def _find_matching_segment(
        self,
        *,
        segment_offset: float,
        current_chunk_db_segments: List[TranscriptSegment],
    ) -> Optional[TranscriptSegment]:
        """Find the TranscriptSegment that matches the given segment offset."""
        min_diff = float("inf")
        matched_segment = None
        for ts_segment in current_chunk_db_segments:
            diff = abs(ts_segment.start_time - segment_offset)
            if diff < min_diff and diff < 0.5:  # Tolerance of 0.5 seconds
                matched_segment = ts_segment
                min_diff = diff
        return matched_segment

    def _identification_exists(
        self, transcript_segment_id: int, model_call_id: int
    ) -> bool:
        """Check if an Identification already exists."""
        return (
            self.identification_query.filter_by(
                transcript_segment_id=transcript_segment_id,
                model_call_id=model_call_id,
                label="ad",
            ).first()
            is not None
        )

    def _is_retryable_error(self, error: Exception) -> bool:
        """Determine if an error should be retried."""
        if isinstance(error, InternalServerError):
            return True

        # Check for retryable HTTP errors in other exception types
        error_str = str(error).lower()
        return (
            "503" in error_str
            or "service unavailable" in error_str
            or "rate_limit_error" in error_str
            or "ratelimiterror" in error_str
            or "429" in error_str
            or "rate limit" in error_str
        )

    def _call_model(
        self,
        model_call_obj: ModelCall,
        system_prompt: str,
        max_retries: Optional[int] = None,
    ) -> Optional[str]:
        """Call the LLM model with retry logic."""
        # Use configured retry count if not specified
        retry_count = (
            max_retries
            if max_retries is not None
            else getattr(self.config, "llm_max_retry_attempts", 3)
        )

        last_error: Optional[Exception] = None
        raw_response_content = None
        original_retry_attempts = (
            0
            if model_call_obj.retry_attempts is None
            else model_call_obj.retry_attempts
        )

        for attempt in range(retry_count):
            model_call_obj.retry_attempts = original_retry_attempts + attempt + 1
            current_attempt_num = attempt + 1

            self.logger.info(
                f"Calling model {model_call_obj.model_name} for ModelCall {model_call_obj.id} (attempt {current_attempt_num}/{retry_count})"
            )

            try:
                if model_call_obj.status != "pending":
                    model_call_obj.status = "pending"

                # Prepare messages for the API call
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": model_call_obj.prompt},
                ]

                # Use rate limiter to wait if necessary and track token usage
                if self.rate_limiter:
                    self.rate_limiter.wait_if_needed(
                        messages, model_call_obj.model_name
                    )

                    # Get usage stats for logging
                    usage_stats = self.rate_limiter.get_usage_stats()
                    self.logger.info(
                        f"Token usage: {usage_stats['current_usage']}/{usage_stats['limit']} "
                        f"({usage_stats['usage_percentage']:.1f}%) for ModelCall {model_call_obj.id}"
                    )

                # Prepare completion arguments
                completion_args = {
                    "model": model_call_obj.model_name,
                    "messages": messages,
                    "timeout": self.config.openai_timeout,
                }
                
                # Use max_completion_tokens for GPT-5 models, max_tokens for others
                if model_call_obj.model_name.lower().startswith("gpt-5"):
                    completion_args["max_completion_tokens"] = self.config.openai_max_tokens
                else:
                    completion_args["max_tokens"] = self.config.openai_max_tokens
                
                response = litellm.completion(**completion_args)

                response_first_choice = response.choices[0]
                assert isinstance(response_first_choice, Choices)
                content = response_first_choice.message.content
                assert content is not None
                raw_response_content = content

                model_call_obj.response = raw_response_content
                model_call_obj.status = "success"
                model_call_obj.error_message = None
                self.db_session.add(model_call_obj)
                self.db_session.commit()
                self.logger.info(
                    f"Model call {model_call_obj.id} successful on attempt {current_attempt_num}."
                )
                return raw_response_content

            except Exception as e:
                last_error = e
                if self._is_retryable_error(e):
                    self._handle_retryable_error(
                        model_call_obj=model_call_obj,
                        error=e,
                        attempt=attempt,
                        current_attempt_num=current_attempt_num,
                    )
                    # Continue to next retry
                else:
                    self.logger.error(
                        f"Non-retryable LLM error for ModelCall {model_call_obj.id} (attempt {current_attempt_num}): {e}",
                        exc_info=True,
                    )
                    model_call_obj.status = "failed_permanent"
                    model_call_obj.error_message = str(e)
                    self.db_session.add(model_call_obj)
                    self.db_session.commit()
                    raise  # Re-raise non-retryable exceptions immediately

        # If we get here, all retries were exhausted
        self._handle_retry_exhausted(model_call_obj, retry_count, last_error)

        if last_error:
            raise last_error
        raise RuntimeError(
            f"Maximum retries ({retry_count}) exceeded for ModelCall {model_call_obj.id}."
        )

    def _handle_retryable_error(
        self,
        *,
        model_call_obj: ModelCall,
        error: Union[InternalServerError, Exception],
        attempt: int,
        current_attempt_num: int,
    ) -> None:
        """Handle a retryable error during LLM call."""
        self.logger.error(
            f"LLM retryable error for ModelCall {model_call_obj.id} (attempt {current_attempt_num}): {error}"
        )
        model_call_obj.error_message = str(error)
        self.db_session.add(model_call_obj)
        self.db_session.commit()

        # Use longer backoff for rate limiting errors
        error_str = str(error).lower()
        if any(
            term in error_str
            for term in ["rate_limit_error", "ratelimiterror", "429", "rate limit"]
        ):
            # For rate limiting, use longer backoff: 60, 120, 240 seconds
            wait_time = 60 * (2**attempt)
            self.logger.info(
                f"Rate limit detected. Waiting {wait_time}s before retry for ModelCall {model_call_obj.id}."
            )
        else:
            # For other errors, use shorter exponential backoff: 1, 2, 4 seconds
            wait_time = (2**attempt) * 1
            self.logger.info(
                f"Waiting {wait_time}s before next retry for ModelCall {model_call_obj.id}."
            )

        time.sleep(wait_time)

    def _handle_retry_exhausted(
        self,
        model_call_obj: ModelCall,
        max_retries: int,
        last_error: Optional[Exception],
    ) -> None:
        """Handle the case when all retries are exhausted."""
        self.logger.error(
            f"Failed to call model for ModelCall {model_call_obj.id} after {max_retries} attempts."
        )
        model_call_obj.status = "failed_retries"
        if last_error:
            model_call_obj.error_message = str(last_error)
        else:
            model_call_obj.error_message = f"Maximum retries ({max_retries}) exceeded without a specific InternalServerError."
        self.db_session.add(model_call_obj)
        self.db_session.commit()
