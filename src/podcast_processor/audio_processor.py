import logging
from typing import Any, List, Optional, Tuple

from app.extensions import db
from app.models import Identification, ModelCall, Post, TranscriptSegment
from app.writer.client import writer_client
from podcast_processor.ad_merger import AdMerger
from podcast_processor.audio import clip_segments_with_fade, get_audio_duration_ms
from shared.config import Config


class AudioProcessor:
    """Handles audio processing and ad segment removal from podcast files."""

    def __init__(
        self,
        config: Config,
        logger: Optional[logging.Logger] = None,
        identification_query: Optional[Any] = None,
        transcript_segment_query: Optional[Any] = None,
        model_call_query: Optional[Any] = None,
        db_session: Optional[Any] = None,
    ):
        self.logger = logger or logging.getLogger("global_logger")
        self.config = config
        self._identification_query_provided = identification_query is not None
        self.identification_query = identification_query or Identification.query
        self.transcript_segment_query = (
            transcript_segment_query or TranscriptSegment.query
        )
        self.model_call_query = model_call_query or ModelCall.query
        self.db_session = db_session or db.session
        self.ad_merger = AdMerger()

    def get_ad_segments(self, post: Post) -> List[Tuple[float, float]]:
        """
        Retrieves ad segments from the database for a given post.

        NOTE: Uses self.db_session.query() instead of self.identification_query
        to ensure all operations use the same session consistently.

        Args:
            post: The Post object to retrieve ad segments for

        Returns:
            A list of tuples containing start and end times (in seconds) of ad segments
        """
        self.logger.info(f"Retrieving ad segments from database for post {post.id}.")

        query = (
            self.identification_query
            if self._identification_query_provided
            else self.db_session.query(Identification)
        )

        ad_identifications = (
            query.join(
                TranscriptSegment,
                Identification.transcript_segment_id == TranscriptSegment.id,
            )
            .join(ModelCall, Identification.model_call_id == ModelCall.id)
            .filter(
                TranscriptSegment.post_id == post.id,
                Identification.label == "ad",
                Identification.confidence >= self.config.output.min_confidence,
                ModelCall.status
                == "success",  # Only consider identifications from successful LLM calls
            )
            .all()
        )

        if not ad_identifications:
            self.logger.info(
                f"No ad segments found meeting criteria for post {post.id}."
            )
            return []

        # Get full segment objects with text for content analysis
        # Filter out any identifications with missing segments (DB integrity check)
        ad_segments_with_text = []
        valid_identifications = []
        for ident in ad_identifications:
            segment = ident.transcript_segment
            if segment:
                ad_segments_with_text.append(segment)
                valid_identifications.append(ident)
            else:
                # This should ideally not happen if DB integrity is maintained
                self.logger.warning(
                    f"Identification {ident.id} for post {post.id} refers to a missing TranscriptSegment {ident.transcript_segment_id}. Skipping."
                )

        if not ad_segments_with_text:
            self.logger.info(
                f"No valid ad segments with transcript data for post {post.id}."
            )
            return []

        # Content-aware merge
        ad_groups = self.ad_merger.merge(
            ad_segments=ad_segments_with_text,
            identifications=valid_identifications,
            max_gap=float(self.config.output.min_ad_segment_separation_seconds),
            min_content_gap=12.0,
        )

        # If boundary refinement persisted refined windows on the post, prefer those
        # refined timestamps for audio cutting (this allows word-level refinement to
        # affect the actual cut start time).
        if getattr(self.config, "enable_boundary_refinement", False):
            self._apply_refined_boundaries(post, ad_groups)

        self.logger.info(
            f"Merged {len(ad_segments_with_text)} segments into {len(ad_groups)} groups for post {post.id}"
        )

        # Convert to time tuples for merge_ad_segments()
        ad_segments_times = [(g.start_time, g.end_time) for g in ad_groups]
        ad_segments_times.sort(key=lambda x: x[0])
        return ad_segments_times

    def _apply_refined_boundaries(self, post: Post, ad_groups: Any) -> None:
        post_row = self._safe_get_post_row(post)
        refined = getattr(post_row, "refined_ad_boundaries", None) if post_row else None
        parsed = self._parse_refined_boundaries(refined)
        if not parsed:
            return

        for group in ad_groups:
            overlap_window = self._refined_overlap_window_for_group(group, parsed)
            if overlap_window is None:
                continue
            refined_start_min, refined_end_max = overlap_window

            new_start = max(group.start_time, refined_start_min)
            new_end = min(group.end_time, refined_end_max)
            if new_end > new_start:
                group.start_time = new_start
                group.end_time = new_end

    def _safe_get_post_row(self, post: Post) -> Optional[Post]:
        try:
            return self.db_session.get(Post, post.id)
        except Exception:  # pylint: disable=broad-except
            return None

    @staticmethod
    def _parse_refined_boundaries(
        refined: Any,
    ) -> List[Tuple[float, float, float, float]]:
        if not refined or not isinstance(refined, list):
            return []

        parsed: List[Tuple[float, float, float, float]] = []
        for item in refined:
            if not isinstance(item, dict):
                continue

            orig_start_raw = item.get("orig_start")
            orig_end_raw = item.get("orig_end")
            refined_start_raw = item.get("refined_start")
            refined_end_raw = item.get("refined_end")
            if (
                orig_start_raw is None
                or orig_end_raw is None
                or refined_start_raw is None
                or refined_end_raw is None
            ):
                continue

            try:
                orig_start = float(orig_start_raw)
                orig_end = float(orig_end_raw)
                refined_start = float(refined_start_raw)
                refined_end = float(refined_end_raw)
            except Exception:  # pylint: disable=broad-except
                continue

            if refined_end <= refined_start:
                continue

            parsed.append((orig_start, orig_end, refined_start, refined_end))

        return parsed

    @staticmethod
    def _refined_overlap_window_for_group(
        group: Any,
        parsed: List[Tuple[float, float, float, float]],
    ) -> Optional[Tuple[float, float]]:
        overlaps: List[Tuple[float, float]] = []
        for orig_start, orig_end, refined_start, refined_end in parsed:
            overlap = max(
                0.0,
                min(group.end_time, orig_end) - max(group.start_time, orig_start),
            )
            if overlap > 0.0:
                overlaps.append((refined_start, refined_end))

        if not overlaps:
            return None

        refined_start_min = min(s for s, _ in overlaps)
        refined_end_max = max(e for _, e in overlaps)
        return refined_start_min, refined_end_max

    def merge_ad_segments(
        self,
        *,
        duration_ms: int,
        ad_segments: List[Tuple[float, float]],
        min_ad_segment_length_seconds: float,
        min_ad_segment_separation_seconds: float,
    ) -> List[Tuple[int, int]]:
        """
        Merges nearby ad segments and filters out segments that are too short.

        Args:
            duration_ms: Duration of the audio in milliseconds
            ad_segments: List of ad segments as (start, end) tuples in seconds
            min_ad_segment_length_seconds: Minimum length of an ad segment to retain
            min_ad_segment_separation_seconds: Minimum separation between segments before merging

        Returns:
            List of merged ad segments as (start, end) tuples in milliseconds
        """
        audio_duration_seconds = duration_ms / 1000.0

        self.logger.info(
            f"Creating new audio with ads segments removed between: {ad_segments}"
        )
        if not ad_segments:
            return []

        ad_segments = sorted(ad_segments)

        last_segment = self._get_last_segment_if_near_end(
            ad_segments,
            audio_duration_seconds=audio_duration_seconds,
            min_separation=min_ad_segment_separation_seconds,
        )

        ad_segments = self._merge_close_segments(
            ad_segments, min_separation=min_ad_segment_separation_seconds
        )
        ad_segments = self._filter_short_segments(
            ad_segments, min_length=min_ad_segment_length_seconds
        )
        ad_segments = self._restore_last_segment_if_needed(ad_segments, last_segment)
        ad_segments = self._extend_last_segment_to_end_if_needed(
            ad_segments,
            audio_duration_seconds=audio_duration_seconds,
            min_separation=min_ad_segment_separation_seconds,
        )

        self.logger.info(f"Joined ad segments into: {ad_segments}")
        return [(int(start * 1000), int(end * 1000)) for start, end in ad_segments]

    def _get_last_segment_if_near_end(
        self,
        ad_segments: List[Tuple[float, float]],
        *,
        audio_duration_seconds: float,
        min_separation: float,
    ) -> Optional[Tuple[float, float]]:
        if not ad_segments:
            return None
        if (audio_duration_seconds - ad_segments[-1][1]) < min_separation:
            return ad_segments[-1]
        return None

    def _merge_close_segments(
        self,
        ad_segments: List[Tuple[float, float]],
        *,
        min_separation: float,
    ) -> List[Tuple[float, float]]:
        merged = list(ad_segments)
        i = 0
        while i < len(merged) - 1:
            if merged[i][1] + min_separation >= merged[i + 1][0]:
                merged[i] = (merged[i][0], merged[i + 1][1])
                merged.pop(i + 1)
            else:
                i += 1
        return merged

    def _filter_short_segments(
        self,
        ad_segments: List[Tuple[float, float]],
        *,
        min_length: float,
    ) -> List[Tuple[float, float]]:
        return [s for s in ad_segments if (s[1] - s[0]) >= min_length]

    def _restore_last_segment_if_needed(
        self,
        ad_segments: List[Tuple[float, float]],
        last_segment: Optional[Tuple[float, float]],
    ) -> List[Tuple[float, float]]:
        if last_segment is None:
            return ad_segments
        if not ad_segments or ad_segments[-1] != last_segment:
            return [*ad_segments, last_segment]
        return ad_segments

    def _extend_last_segment_to_end_if_needed(
        self,
        ad_segments: List[Tuple[float, float]],
        *,
        audio_duration_seconds: float,
        min_separation: float,
    ) -> List[Tuple[float, float]]:
        if not ad_segments:
            return ad_segments
        if (audio_duration_seconds - ad_segments[-1][1]) < min_separation:
            return [*ad_segments[:-1], (ad_segments[-1][0], audio_duration_seconds)]
        return ad_segments

    def process_audio(self, post: Post, output_path: str) -> None:
        """
        Process the podcast audio by removing ad segments.

        Args:
            post: The Post object containing the podcast to process
            output_path: Path where the processed audio file should be saved
        """
        ad_segments = self.get_ad_segments(post)

        duration_ms = get_audio_duration_ms(post.unprocessed_audio_path)
        if duration_ms is None:
            raise ValueError(
                f"Could not determine duration for audio: {post.unprocessed_audio_path}"
            )

        # Store duration in seconds
        post.duration = duration_ms / 1000.0

        merged_ad_segments = self.merge_ad_segments(
            duration_ms=duration_ms,
            ad_segments=ad_segments,
            min_ad_segment_length_seconds=float(
                self.config.output.min_ad_segment_length_seconds
            ),
            min_ad_segment_separation_seconds=float(
                self.config.output.min_ad_segement_separation_seconds
            ),
        )

        clip_segments_with_fade(
            in_path=post.unprocessed_audio_path,
            ad_segments_ms=merged_ad_segments,
            fade_ms=self.config.output.fade_ms,
            out_path=output_path,
        )

        post.processed_audio_path = output_path
        result = writer_client.update(
            "Post",
            post.id,
            {"processed_audio_path": output_path, "duration": post.duration},
            wait=True,
        )
        if not result or not result.success:
            raise RuntimeError(getattr(result, "error", "Failed to update post"))
        try:
            self.db_session.expire(post)
        except Exception:  # pylint: disable=broad-except
            pass

        self.logger.info(
            f"Audio processing complete for post {post.id}, saved to {output_path}"
        )
