# pylint: disable=too-many-lines
import logging
import time
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import litellm
from jinja2 import Template
from litellm.exceptions import InternalServerError
from litellm.types.utils import Choices
from pydantic import ValidationError
from sqlalchemy import and_
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Identification, ModelCall, Post, TranscriptSegment
from podcast_processor.boundary_refiner import BoundaryRefiner
from podcast_processor.cue_detector import CueDetector
from podcast_processor.llm_concurrency_limiter import (
    ConcurrencyContext,
    LLMConcurrencyLimiter,
    get_concurrency_limiter,
)
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
from shared.llm_utils import model_uses_max_completion_tokens


class ClassifyParams:
    def __init__(
        self,
        system_prompt: str,
        user_prompt_template: Template,
        post: Post,
        num_segments_per_prompt: int,
        max_overlap_segments: int,
    ):
        self.system_prompt = system_prompt
        self.user_prompt_template = user_prompt_template
        self.post = post
        self.num_segments_per_prompt = num_segments_per_prompt
        self.max_overlap_segments = max_overlap_segments


class ClassifyException(Exception):
    """Custom exception for classification errors."""


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

        # Initialize concurrency limiter for LLM API calls
        self.concurrency_limiter: Optional[LLMConcurrencyLimiter]
        max_concurrent = getattr(self.config, "llm_max_concurrent_calls", 3)
        if max_concurrent > 0:
            self.concurrency_limiter = get_concurrency_limiter(max_concurrent)
            self.logger.info(
                f"LLM concurrency limiting enabled: max {max_concurrent} concurrent calls"
            )
        else:
            self.concurrency_limiter = None
            self.logger.info("LLM concurrency limiting disabled")

        # Initialize cue detector for neighbor expansion
        self.cue_detector = CueDetector()

        # Initialize boundary refiner
        self.boundary_refiner: Optional[BoundaryRefiner]
        if getattr(config, "boundary_refinement_enabled", False):
            self.boundary_refiner = BoundaryRefiner(config, self.logger)
        else:
            self.boundary_refiner = None

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

        classify_params = ClassifyParams(
            system_prompt=system_prompt,
            user_prompt_template=user_prompt_template,
            post=post,
            num_segments_per_prompt=self.config.processing.num_segments_to_input_to_prompt,
            max_overlap_segments=self.config.processing.max_overlap_segments,
        )

        total_segments = len(transcript_segments)

        try:
            current_index = 0
            next_overlap_segments: List[TranscriptSegment] = []
            max_iterations = (
                total_segments + 10
            )  # Safety limit to prevent infinite loops
            iteration_count = 0
            while current_index < total_segments and iteration_count < max_iterations:
                consumed_segments, next_overlap_segments = self._step(
                    classify_params,
                    next_overlap_segments,
                    current_index,
                    transcript_segments,
                )
                current_index += consumed_segments
                iteration_count += 1
                if consumed_segments == 0:
                    self.logger.error(
                        f"No progress made in iteration {iteration_count} for post {post.id}. "
                        "Breaking to avoid infinite loop."
                    )
                    break

            # Expand neighbors using bulk operations
            ad_identifications = (
                self.identification_query.join(TranscriptSegment)
                .filter(
                    TranscriptSegment.post_id == post.id,
                    Identification.label == "ad",
                )
                .all()
            )

            if ad_identifications:
                # Get model_call from first identification
                model_call = (
                    ad_identifications[0].model_call if ad_identifications else None
                )
                if model_call:
                    created = self.expand_neighbors_bulk(
                        ad_identifications=ad_identifications,
                        model_call=model_call,
                        post_id=post.id,
                        window=5,
                    )
                    self.logger.info(
                        f"Created {created} neighbor identifications via bulk ops"
                    )

            # Pass 2: Refine boundaries
            if self.boundary_refiner:
                self._refine_boundaries(transcript_segments, post)

        except ClassifyException as e:
            self.logger.error(f"Classification failed for post {post.id}: {e}")
            return

    def _step(
        self,
        classify_params: ClassifyParams,
        prev_overlap_segments: List[TranscriptSegment],
        current_index: int,
        transcript_segments: List[TranscriptSegment],
    ) -> Tuple[int, List[TranscriptSegment]]:
        overlap_segments = self._apply_overlap_cap(prev_overlap_segments)
        remaining_segments = transcript_segments[current_index:]

        (
            chunk_segments,
            user_prompt_str,
            consumed_segments,
            token_limit_trimmed,
        ) = self._build_chunk_payload(
            overlap_segments=overlap_segments,
            remaining_segments=remaining_segments,
            total_segments=transcript_segments,
            post=classify_params.post,
            system_prompt=classify_params.system_prompt,
            user_prompt_template=classify_params.user_prompt_template,
            max_new_segments=classify_params.num_segments_per_prompt,
        )

        if not chunk_segments or consumed_segments <= 0:
            self.logger.error(
                "No progress made while building classification chunk for post %s. "
                "Stopping to avoid infinite loop.",
                classify_params.post.id,
            )
            raise ClassifyException(
                "No progress made while building classification chunk."
            )

        if token_limit_trimmed:
            self.logger.debug(
                "Token limit trimming applied for post %s at transcript index %s. "
                "Processing chunk with %s new segments across %s total segments.",
                classify_params.post.id,
                current_index,
                consumed_segments,
                len(chunk_segments),
            )

        identified_segments = self._process_chunk(
            chunk_segments=chunk_segments,
            system_prompt=classify_params.system_prompt,
            user_prompt_str=user_prompt_str,
            post=classify_params.post,
        )

        next_overlap_segments = self._compute_next_overlap_segments(
            chunk_segments=chunk_segments,
            identified_segments=identified_segments,
            max_overlap_segments=classify_params.max_overlap_segments,
        )

        if next_overlap_segments:
            self.logger.debug(
                "Carrying forward %s overlap segments for post %s: %s",
                len(next_overlap_segments),
                classify_params.post.id,
                [seg.sequence_num for seg in next_overlap_segments],
            )

        return consumed_segments, next_overlap_segments

    def _process_chunk(
        self,
        *,
        chunk_segments: List[TranscriptSegment],
        system_prompt: str,
        post: Post,
        user_prompt_str: str,
    ) -> List[TranscriptSegment]:
        """Process a chunk of transcript segments for classification."""
        if not chunk_segments:
            return []

        first_seq_num = chunk_segments[0].sequence_num
        last_seq_num = chunk_segments[-1].sequence_num

        self.logger.info(
            f"Processing classification for post {post.id}, segments {first_seq_num}-{last_seq_num}."
        )

        model_call = self._get_or_create_model_call(
            post=post,
            first_seq_num=first_seq_num,
            last_seq_num=last_seq_num,
            user_prompt_str=user_prompt_str,
        )

        if not model_call:
            self.logger.error("ModelCall object is unexpectedly None. Skipping chunk.")
            return []

        if self._should_call_llm(model_call):
            self._perform_llm_call(
                model_call=model_call,
                system_prompt=system_prompt,
            )

        if model_call.status == "success" and model_call.response:
            return self._process_successful_response(
                model_call=model_call,
                current_chunk_db_segments=chunk_segments,
            )
        if model_call.status != "success":
            self.logger.info(
                f"LLM call for ModelCall {model_call.id} was not successful (status: {model_call.status}). No identifications to process."
            )
        return []

    def _build_chunk_payload(
        self,
        *,
        overlap_segments: List[TranscriptSegment],
        remaining_segments: List[TranscriptSegment],
        total_segments: List[TranscriptSegment],
        post: Post,
        system_prompt: str,
        user_prompt_template: Template,
        max_new_segments: int,
    ) -> Tuple[List[TranscriptSegment], str, int, bool]:
        """Construct chunk data while enforcing overlap and token constraints."""
        if not remaining_segments:
            return ([], "", 0, False)

        capped_overlap = self._apply_overlap_cap(overlap_segments)
        new_segment_count = min(max_new_segments, len(remaining_segments))
        token_limit_trimmed = False

        while new_segment_count > 0:
            base_segments = remaining_segments[:new_segment_count]
            chunk_segments = self._combine_overlap_segments(
                overlap_segments=capped_overlap,
                base_segments=base_segments,
            )

            if not chunk_segments:
                return ([], "", 0, token_limit_trimmed)

            includes_start = (
                chunk_segments[0].id == total_segments[0].id
                if total_segments
                else False
            )
            includes_end = (
                chunk_segments[-1].id == total_segments[-1].id
                if total_segments
                else False
            )

            user_prompt_str = self._generate_user_prompt(
                current_chunk_db_segments=chunk_segments,
                post=post,
                user_prompt_template=user_prompt_template,
                includes_start=includes_start,
                includes_end=includes_end,
            )

            if (
                self.config.llm_max_input_tokens_per_call is not None
                and not self._validate_token_limit(user_prompt_str, system_prompt)
            ):
                token_limit_trimmed = True
                if new_segment_count == 1:
                    self.logger.warning(
                        "Even single segment at transcript index %s exceeds token limit "
                        "for post %s. Proceeding with minimal chunk.",
                        base_segments[0].sequence_num,
                        post.id,
                    )
                    return (chunk_segments, user_prompt_str, new_segment_count, True)
                new_segment_count -= 1
                continue

            return (
                chunk_segments,
                user_prompt_str,
                new_segment_count,
                token_limit_trimmed,
            )

        return ([], "", 0, token_limit_trimmed)

    def _combine_overlap_segments(
        self,
        *,
        overlap_segments: List[TranscriptSegment],
        base_segments: List[TranscriptSegment],
    ) -> List[TranscriptSegment]:
        """Combine overlap and new segments while preserving order and removing duplicates."""
        combined: List[TranscriptSegment] = []
        seen_ids: Set[int] = set()

        for segment in overlap_segments:
            if segment.id not in seen_ids:
                combined.append(segment)
                seen_ids.add(segment.id)

        for segment in base_segments:
            if segment.id not in seen_ids:
                combined.append(segment)
                seen_ids.add(segment.id)

        self.logger.debug(
            "Combined overlap (%s segments) and base (%s segments) into %s total segments. "
            "Overlap seq nums: %s, Base seq nums: %s",
            len(overlap_segments),
            len(base_segments),
            len(combined),
            [seg.sequence_num for seg in overlap_segments],
            [seg.sequence_num for seg in base_segments],
        )

        return combined

    def _compute_next_overlap_segments(
        self,
        *,
        chunk_segments: List[TranscriptSegment],
        identified_segments: List[TranscriptSegment],
        max_overlap_segments: int,
    ) -> List[TranscriptSegment]:
        """Determine which segments should be carried forward to the next chunk."""
        if not identified_segments or max_overlap_segments <= 0:
            self.logger.debug(
                "Skipping overlap computation: identified_segments=%s, max_overlap=%s",
                len(identified_segments) if identified_segments else 0,
                max_overlap_segments,
            )
            return []

        # Find the earliest identified ad segment in the chunk
        identified_ids = {seg.id for seg in identified_segments}
        earliest_index = None
        for i, seg in enumerate(chunk_segments):
            if seg.id in identified_ids:
                earliest_index = i
                break

        if earliest_index is None:
            self.logger.debug(
                "No ad segments found in chunk; no overlap to carry forward"
            )
            return []

        self.logger.debug(
            "Found earliest ad segment at index %s (seq_num %s)",
            earliest_index,
            chunk_segments[earliest_index].sequence_num,
        )

        # Take from earliest ad to end of chunk
        overlap_segments = chunk_segments[earliest_index:]

        self.logger.debug(
            "Taking from earliest ad to end: %s segments (seq_nums %s-%s)",
            len(overlap_segments),
            overlap_segments[0].sequence_num,
            overlap_segments[-1].sequence_num,
        )

        # Cap at max_overlap_segments from the end
        if len(overlap_segments) > max_overlap_segments:
            trimmed = overlap_segments[-max_overlap_segments:]
            self.logger.debug(
                "Trimming overlap from %s to %s segments (max=%s). "
                "Keeping seq_nums: %s",
                len(overlap_segments),
                len(trimmed),
                max_overlap_segments,
                [seg.sequence_num for seg in trimmed],
            )
            return trimmed

        self.logger.debug(
            "Carrying forward %s overlap segments: seq_nums %s",
            len(overlap_segments),
            [seg.sequence_num for seg in overlap_segments],
        )
        return overlap_segments

    def _apply_overlap_cap(
        self, overlap_segments: List[TranscriptSegment]
    ) -> List[TranscriptSegment]:
        """Ensure stored overlap obeys configured limits."""
        max_overlap = self.config.processing.max_overlap_segments
        if max_overlap <= 0 or not overlap_segments:
            if max_overlap <= 0 and overlap_segments:
                self.logger.debug(
                    "Discarding %s overlap segments because max_overlap_segments is %s.",
                    len(overlap_segments),
                    max_overlap,
                )
            return [] if max_overlap <= 0 else list(overlap_segments)

        if len(overlap_segments) <= max_overlap:
            self.logger.debug(
                "Overlap cap check: %s segments within limit of %s, no trimming needed",
                len(overlap_segments),
                max_overlap,
            )
            return list(overlap_segments)

        trimmed = overlap_segments[-max_overlap:]
        self.logger.debug(
            "Overlap cap enforcement: trimming from %s to %s segments (max=%s). "
            "Keeping seq_nums: %s",
            len(overlap_segments),
            len(trimmed),
            max_overlap,
            [seg.sequence_num for seg in trimmed],
        )
        return trimmed

    def _validate_token_limit(self, user_prompt_str: str, system_prompt: str) -> bool:
        """Validate that the prompt doesn't exceed the configured token limit."""
        if self.config.llm_max_input_tokens_per_call is None:
            return True

        # Create messages as they would be sent to the API
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt_str},
        ]

        # Count tokens (reuse the existing token counting logic from rate limiter)
        if self.rate_limiter:
            token_count = self.rate_limiter.count_tokens(
                messages, self.config.llm_model
            )
        else:
            # Fallback token estimation if no rate limiter
            total_chars = len(system_prompt) + len(user_prompt_str)
            token_count = total_chars // 4  # ~4 characters per token

        is_valid = token_count <= self.config.llm_max_input_tokens_per_call

        if not is_valid:
            self.logger.debug(
                f"Prompt exceeds token limit: {token_count} > {self.config.llm_max_input_tokens_per_call}"
            )
        else:
            self.logger.debug(
                f"Prompt within token limit: {token_count} <= {self.config.llm_max_input_tokens_per_call}"
            )

        return is_valid

    def _prepare_api_call(
        self, model_call_obj: ModelCall, system_prompt: str
    ) -> Optional[Dict[str, Any]]:
        """Prepare API call arguments and validate token limits."""
        # Prepare messages for the API call
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": model_call_obj.prompt},
        ]

        # Use rate limiter to wait if necessary and track token usage
        if self.rate_limiter:
            self.rate_limiter.wait_if_needed(messages, model_call_obj.model_name)

            # Get usage stats for logging
            usage_stats = self.rate_limiter.get_usage_stats()
            self.logger.info(
                f"Token usage: {usage_stats['current_usage']}/{usage_stats['limit']} "
                f"({usage_stats['usage_percentage']:.1f}%) for ModelCall {model_call_obj.id}"
            )

        # Final validation: Check per-call token limit before making API call
        if self.config.llm_max_input_tokens_per_call is not None:
            if not self._validate_token_limit(model_call_obj.prompt, system_prompt):
                error_msg = (
                    f"Prompt for ModelCall {model_call_obj.id} exceeds configured "
                    f"token limit of {self.config.llm_max_input_tokens_per_call}. "
                    f"Consider reducing num_segments_to_input_to_prompt."
                )
                self.logger.error(error_msg)
                model_call_obj.status = "failed"
                model_call_obj.error_message = error_msg
                self.db_session.add(model_call_obj)
                self.db_session.commit()
                return None

        # Prepare completion arguments
        completion_args = {
            "model": model_call_obj.model_name,
            "messages": messages,
            "timeout": self.config.openai_timeout,
        }

        # Use max_completion_tokens for newer OpenAI models (o1, gpt-5, gpt-4o variants)
        # OpenAI deprecated max_tokens for these models in favor of max_completion_tokens
        # Check if this is a model that requires max_completion_tokens
        # This includes: gpt-5, gpt-4o variants, o1 series, and latest chatgpt models
        uses_max_completion_tokens = model_uses_max_completion_tokens(
            model_call_obj.model_name
        )

        # Debug logging to help diagnose model parameter issues
        self.logger.info(
            f"Model: '{model_call_obj.model_name}', using max_completion_tokens: {uses_max_completion_tokens}"
        )

        if uses_max_completion_tokens:
            completion_args["max_completion_tokens"] = self.config.openai_max_tokens
        else:
            # For older models and non-OpenAI models, use max_tokens
            completion_args["max_tokens"] = self.config.openai_max_tokens

        return completion_args

    def _generate_user_prompt(
        self,
        *,
        current_chunk_db_segments: List[TranscriptSegment],
        post: Post,
        user_prompt_template: Template,
        includes_start: bool,
        includes_end: bool,
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
                includes_start=includes_start,
                includes_end=includes_end,
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
    ) -> List[TranscriptSegment]:
        """Process a successful LLM response and create Identification records."""
        self.logger.info(
            f"LLM call for ModelCall {model_call.id} was successful. Parsing response."
        )
        try:
            prediction_list = clean_and_parse_model_output(model_call.response)
            created_identification_count, matched_segments = (
                self._create_identifications(
                    prediction_list=prediction_list,
                    current_chunk_db_segments=current_chunk_db_segments,
                    model_call=model_call,
                )
            )

            if created_identification_count > 0:
                self.logger.info(
                    f"Created {created_identification_count} new Identification records for ModelCall {model_call.id}."
                )
            self.db_session.commit()
            return matched_segments
        except (ValidationError, AssertionError) as e:
            self.logger.error(
                f"Error processing LLM response for ModelCall {model_call.id}: {e}",
                exc_info=True,
            )
        return []

    def _create_identifications(
        self,
        *,
        prediction_list: AdSegmentPredictionList,
        current_chunk_db_segments: List[TranscriptSegment],
        model_call: ModelCall,
    ) -> Tuple[int, List[TranscriptSegment]]:
        """Create Identification records from the prediction list."""
        created_count = 0
        matched_segments: List[TranscriptSegment] = []
        processed_segment_ids: Set[int] = set()

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

            if matched_segment.id in processed_segment_ids:
                continue

            processed_segment_ids.add(matched_segment.id)
            matched_segments.append(matched_segment)

            if self._segment_has_ad_identification(matched_segment.id):
                self.logger.debug(
                    "Segment %s for post %s already has an ad identification; skipping new record.",
                    matched_segment.id,
                    model_call.post_id,
                )
                continue

            identification = Identification(
                transcript_segment_id=matched_segment.id,
                model_call_id=model_call.id,
                label="ad",
                confidence=pred.confidence,
            )
            self.db_session.add(identification)
            created_count += 1

        return created_count, matched_segments

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

    def _segment_has_ad_identification(self, transcript_segment_id: int) -> bool:
        """Check if a transcript segment already has an ad identification."""
        return (
            self.identification_query.filter_by(
                transcript_segment_id=transcript_segment_id,
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

                # Prepare API call and validate token limits
                completion_args = self._prepare_api_call(model_call_obj, system_prompt)
                if completion_args is None:
                    return None  # Token limit exceeded

                # Use concurrency limiter if available
                if self.concurrency_limiter:
                    with ConcurrencyContext(self.concurrency_limiter, timeout=30.0):
                        response = litellm.completion(**completion_args)
                else:
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

    def _get_segments_bulk(
        self, post_id: int, sequence_numbers: List[int]
    ) -> Dict[int, TranscriptSegment]:
        """Fetch multiple segments in one query"""
        segments = TranscriptSegment.query.filter(
            and_(
                TranscriptSegment.post_id == post_id,
                TranscriptSegment.sequence_num.in_(sequence_numbers),
            )
        ).all()
        return {seg.sequence_num: seg for seg in segments}

    def _get_existing_ids_bulk(
        self, post_id: int, model_call_id: int
    ) -> Set[Tuple[int, int, str]]:
        """Fetch all existing identifications as a set for O(1) lookup"""
        ids = (
            self.identification_query.join(TranscriptSegment)
            .filter(
                and_(
                    TranscriptSegment.post_id == post_id,
                    Identification.model_call_id == model_call_id,
                )
            )
            .all()
        )
        return {(i.transcript_segment_id, i.model_call_id, i.label) for i in ids}

    def _create_identifications_bulk(
        self, identifications: List[Dict[str, Any]]
    ) -> int:
        """Bulk insert identifications"""
        if not identifications:
            return 0
        self.db_session.bulk_insert_mappings(Identification.__mapper__, identifications)
        self.db_session.commit()
        return len(identifications)

    def expand_neighbors_bulk(
        self,
        ad_identifications: List[Identification],
        model_call: ModelCall,
        post_id: int,
        window: int = 5,
    ) -> int:
        """Expand neighbors using bulk operations (3 queries instead of 900)"""

        # PHASE 1: Bulk data collection (2 queries)

        # Collect all sequence numbers we need
        sequence_numbers = set()
        for ident in ad_identifications:
            base_seq = ident.transcript_segment.sequence_num
            for offset in range(-window, window + 1):
                sequence_numbers.add(base_seq + offset)

        # Query 1: Bulk fetch segments
        segments_by_seq = self._get_segments_bulk(post_id, list(sequence_numbers))

        # Query 2: Bulk fetch existing identifications
        existing = self._get_existing_ids_bulk(post_id, model_call.id)

        # PHASE 2: In-memory processing (0 queries)

        to_create = []
        for ident in ad_identifications:
            base_seq = ident.transcript_segment.sequence_num

            for offset in range(-window, window + 1):
                if offset == 0:
                    continue

                neighbor_seq = base_seq + offset
                seg = segments_by_seq.get(neighbor_seq)
                if not seg:
                    continue

                # Check if already exists (O(1) lookup)
                key = (seg.id, model_call.id, "ad")
                if key in existing:
                    continue

                # Check for promotional cues
                text = (seg.text or "").lower()
                if self.cue_detector.has_cue(text):
                    to_create.append(
                        {
                            "transcript_segment_id": seg.id,
                            "model_call_id": model_call.id,
                            "label": "ad",
                            "confidence": 0.75,
                        }
                    )
                    existing.add(key)  # Avoid duplicates in this batch

        # PHASE 3: Bulk insert (1 query)

        if to_create:
            return self._create_identifications_bulk(to_create)
        return 0

    def _refine_boundaries(
        self, transcript_segments: List[TranscriptSegment], post: Post
    ) -> None:
        """Apply boundary refinement to detected ads"""
        if not self.boundary_refiner:
            return

        # Get ad identifications
        identifications = (
            self.identification_query.join(TranscriptSegment)
            .filter(TranscriptSegment.post_id == post.id, Identification.label == "ad")
            .all()
        )

        # Group into ad blocks
        ad_blocks = self._group_into_blocks(identifications)

        for block in ad_blocks:
            # Skip low confidence or very short blocks
            if block["confidence"] < 0.6 or (block["end"] - block["start"]) < 15.0:
                continue

            # Refine
            refinement = self.boundary_refiner.refine(
                ad_start=block["start"],
                ad_end=block["end"],
                confidence=block["confidence"],
                all_segments=[
                    {"start_time": s.start_time, "text": s.text, "end_time": s.end_time}
                    for s in transcript_segments
                ],
            )

            # Apply refinement: delete old identifications, create new ones
            # Note: Get model_call from block identifications
            model_call = (
                block["identifications"][0].model_call
                if block["identifications"]
                else None
            )
            if model_call:
                self._apply_refinement(
                    block, refinement, transcript_segments, post, model_call
                )

    def _group_into_blocks(
        self, identifications: List[Identification]
    ) -> List[Dict[str, Any]]:
        """Group adjacent identifications into ad blocks"""
        if not identifications:
            return []

        identifications = sorted(
            identifications, key=lambda i: i.transcript_segment.start_time
        )
        blocks: List[Dict[str, Any]] = []
        current: List[Identification] = []

        for ident in identifications:
            if (
                not current
                or ident.transcript_segment.start_time
                - current[-1].transcript_segment.end_time
                <= 10.0
            ):
                current.append(ident)
            else:
                blocks.append(self._create_block(current))
                current = [ident]

        if current:
            blocks.append(self._create_block(current))

        return blocks

    def _create_block(self, identifications: List[Identification]) -> Dict[str, Any]:
        return {
            "start": min(i.transcript_segment.start_time for i in identifications),
            "end": max(i.transcript_segment.end_time for i in identifications),
            "confidence": sum(i.confidence for i in identifications)
            / len(identifications),
            "identifications": identifications,
        }

    def _apply_refinement(
        self,
        block: Dict[str, Any],
        refinement: Any,
        transcript_segments: List[TranscriptSegment],
        post: Post,
        model_call: ModelCall,
    ) -> None:
        """Update identifications based on refined boundaries"""
        # Delete old identifications
        for ident in block["identifications"]:
            self.db_session.delete(ident)

        # Create new identifications for refined region
        for seg in transcript_segments:
            if refinement.refined_start <= seg.start_time <= refinement.refined_end:
                new_ident = Identification(
                    transcript_segment_id=seg.id,
                    model_call_id=model_call.id,
                    label="ad",
                    confidence=block["confidence"],
                )
                self.db_session.add(new_ident)

        self.db_session.commit()
