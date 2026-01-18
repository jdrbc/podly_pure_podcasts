"""LLM-based word-boundary refiner.

Note: We intentionally share some call-setup patterns with BoundaryRefiner.
Pylint may flag these as R0801 (duplicate-code); we ignore that for this module.
"""

# pylint: disable=duplicate-code

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, cast

import litellm
from jinja2 import Template

from podcast_processor.llm_model_call_utils import (
    extract_litellm_content,
    render_prompt_and_upsert_model_call,
    try_update_model_call,
)
from shared.config import Config

# Keep the same internal bounds as the existing BoundaryRefiner.
MAX_START_EXTENSION_SECONDS = 30.0
MAX_END_EXTENSION_SECONDS = 15.0


@dataclass
class WordBoundaryRefinement:
    refined_start: float
    refined_end: float
    start_adjustment_reason: str
    end_adjustment_reason: str


class WordBoundaryRefiner:
    """Refine ad start boundary by finding the first ad word and estimating its time.

    This refiner is intentionally heuristic-timed because we only have segment-level
    timestamps today.
    """

    def __init__(self, config: Config, logger: Optional[logging.Logger] = None):
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        self.template = self._load_template()

    def _load_template(self) -> Template:
        path = (
            Path(__file__).resolve().parent.parent  # project src root
            / "word_boundary_refinement_prompt.jinja"
        )
        if path.exists():
            return Template(path.read_text())
        return Template(
            """Find start/end phrases for the ad break.
Ad: {{ad_start}}s-{{ad_end}}s
{% for seg in context_segments %}[seq={{seg.sequence_num}} start={{seg.start_time}} end={{seg.end_time}}] {{seg.text}}
{% endfor %}
    Return JSON: {"refined_start_segment_seq": 0, "refined_start_phrase": "", "refined_end_segment_seq": 0, "refined_end_phrase": "", "start_adjustment_reason": "", "end_adjustment_reason": ""}
"""
        )

    def refine(
        self,
        ad_start: float,
        ad_end: float,
        confidence: float,
        all_segments: List[Dict[str, Any]],
        *,
        post_id: Optional[int] = None,
        first_seq_num: Optional[int] = None,
        last_seq_num: Optional[int] = None,
    ) -> WordBoundaryRefinement:
        context = self._get_context(
            ad_start,
            ad_end,
            all_segments,
            first_seq_num=first_seq_num,
            last_seq_num=last_seq_num,
        )

        prompt, model_call_id = render_prompt_and_upsert_model_call(
            template=self.template,
            ad_start=ad_start,
            ad_end=ad_end,
            confidence=confidence,
            context_segments=context,
            post_id=post_id,
            first_seq_num=first_seq_num,
            last_seq_num=last_seq_num,
            model_name=self.config.llm_model,
            logger=self.logger,
            log_prefix="Word boundary refine",
        )

        raw_response: Optional[str] = None

        try:
            response = litellm.completion(
                model=self.config.llm_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=2048,
                timeout=self.config.openai_timeout,
                api_key=self.config.llm_api_key,
                base_url=self.config.openai_base_url,
            )

            content = extract_litellm_content(response)
            raw_response = content
            self._update_model_call(
                model_call_id,
                status="received_response",
                response=raw_response,
                error_message=None,
            )

            parsed = self._parse_json(content)
            if not parsed:
                self.logger.warning(
                    "Word boundary refine: no parseable JSON; falling back to original start",
                    extra={"content_preview": (content or "")[:200]},
                )
                self._update_model_call(
                    model_call_id,
                    status="success_heuristic",
                    response=raw_response,
                    error_message="parse_failed",
                )
                return self._fallback(ad_start, ad_end)

            payload = self._extract_payload(parsed)

            refined_start, start_changed, start_reason, start_err = self._refine_start(
                ad_start=ad_start,
                all_segments=all_segments,
                context_segments=context,
                start_segment_seq=payload["start_segment_seq"],
                start_phrase=payload["start_phrase"],
                start_word=payload["start_word"],
                start_occurrence=payload["start_occurrence"],
                start_word_index=payload["start_word_index"],
                start_reason=payload["start_reason"],
            )
            refined_end, end_changed, end_reason, end_err = self._refine_end(
                ad_end=ad_end,
                all_segments=all_segments,
                context_segments=context,
                end_segment_seq=payload["end_segment_seq"],
                end_phrase=payload["end_phrase"],
                end_reason=payload["end_reason"],
            )

            partial_errors = [e for e in [start_err, end_err] if e]

            # If caller didn't provide reasons, default to unchanged for untouched sides.
            start_reason = self._default_reason(start_reason, changed=start_changed)
            end_reason = self._default_reason(end_reason, changed=end_changed)

            # Guardrail: never return an invalid window.
            if refined_end <= refined_start:
                self._update_model_call(
                    model_call_id,
                    status="success_heuristic",
                    response=raw_response,
                    error_message="invalid_refined_window",
                )
                return self._fallback(ad_start, ad_end)

            self._update_model_call(
                model_call_id,
                status=self._result_status(start_changed, end_changed, partial_errors),
                response=raw_response,
                error_message=(",".join(partial_errors) if partial_errors else None),
            )

            result = WordBoundaryRefinement(
                refined_start=refined_start,
                refined_end=refined_end,
                start_adjustment_reason=start_reason,
                end_adjustment_reason=end_reason,
            )

            self._update_model_call(
                model_call_id,
                status="success",
                response=raw_response,
                error_message=None,
            )
            return result

        except Exception as exc:
            self._update_model_call(
                model_call_id,
                status="failed_permanent",
                response=raw_response,
                error_message=str(exc),
            )
            self.logger.warning("Word boundary refine failed: %s", exc)
            return self._fallback(ad_start, ad_end)

    def _fallback(self, ad_start: float, ad_end: float) -> WordBoundaryRefinement:
        return WordBoundaryRefinement(
            refined_start=ad_start,
            refined_end=ad_end,
            start_adjustment_reason="heuristic_fallback",
            end_adjustment_reason="unchanged",
        )

    def _constrain_start(self, estimated_start: float, orig_start: float) -> float:
        return max(estimated_start, orig_start - MAX_START_EXTENSION_SECONDS)

    def _constrain_end(self, estimated_end: float, orig_end: float) -> float:
        # Allow slight forward extension (for late boundary) but cap it.
        return min(estimated_end, orig_end + MAX_END_EXTENSION_SECONDS)

    def _parse_json(self, content: str) -> Optional[Dict[str, Any]]:
        cleaned = re.sub(r"```json|```", "", (content or "").strip())
        json_candidates = re.findall(r"\{.*?\}", cleaned, re.DOTALL)
        for candidate in json_candidates:
            try:
                loaded = json.loads(candidate)
                if isinstance(loaded, dict):
                    return cast(Dict[str, Any], loaded)
            except Exception:
                continue
        return None

    @staticmethod
    def _has_text(value: Any) -> bool:
        if value is None:
            return False
        try:
            return bool(str(value).strip())
        except Exception:
            return False

    def _extract_payload(self, parsed: Dict[str, Any]) -> Dict[str, Any]:
        occurrence = parsed.get("occurrence")
        if occurrence is None:
            occurrence = parsed.get("occurance")

        return {
            "start_segment_seq": parsed.get("refined_start_segment_seq"),
            "start_phrase": parsed.get("refined_start_phrase"),
            "end_segment_seq": parsed.get("refined_end_segment_seq"),
            "end_phrase": parsed.get("refined_end_phrase"),
            "start_word": parsed.get("refined_start_word"),
            "start_occurrence": occurrence,
            "start_word_index": parsed.get("refined_start_word_index"),
            "start_reason": str(parsed.get("start_adjustment_reason") or ""),
            "end_reason": str(parsed.get("end_adjustment_reason") or ""),
        }

    @staticmethod
    def _default_reason(reason: str, *, changed: bool) -> str:
        if reason:
            return reason
        return "refined" if changed else "unchanged"

    @staticmethod
    def _result_status(
        start_changed: bool, end_changed: bool, partial_errors: List[str]
    ) -> str:
        if partial_errors and not start_changed and not end_changed:
            return "success_heuristic"
        return "success"

    def _refine_start(
        self,
        *,
        ad_start: float,
        all_segments: List[Dict[str, Any]],
        context_segments: List[Dict[str, Any]],
        start_segment_seq: Any,
        start_phrase: Any,
        start_word: Any,
        start_occurrence: Any,
        start_word_index: Any,
        start_reason: str,
    ) -> Tuple[float, bool, str, Optional[str]]:
        if self._has_text(start_phrase):
            estimated_start = self._estimate_phrase_time(
                all_segments=all_segments,
                context_segments=context_segments,
                preferred_segment_seq=start_segment_seq,
                phrase=start_phrase,
                direction="start",
            )
            if estimated_start is None:
                return float(ad_start), False, start_reason, "start_phrase_not_found"
            return (
                self._constrain_start(float(estimated_start), ad_start),
                True,
                start_reason,
                None,
            )

        if self._has_text(start_word) or start_word_index is not None:
            estimated_start = self._estimate_word_time(
                all_segments=all_segments,
                segment_seq=start_segment_seq,
                word=start_word,
                occurrence=start_occurrence,
                word_index=start_word_index,
            )
            return (
                self._constrain_start(float(estimated_start), ad_start),
                True,
                start_reason,
                None,
            )

        return float(ad_start), False, (start_reason or "unchanged"), None

    def _refine_end(
        self,
        *,
        ad_end: float,
        all_segments: List[Dict[str, Any]],
        context_segments: List[Dict[str, Any]],
        end_segment_seq: Any,
        end_phrase: Any,
        end_reason: str,
    ) -> Tuple[float, bool, str, Optional[str]]:
        if not self._has_text(end_phrase):
            return float(ad_end), False, (end_reason or "unchanged"), None

        estimated_end = self._estimate_phrase_time(
            all_segments=all_segments,
            context_segments=context_segments,
            preferred_segment_seq=end_segment_seq,
            phrase=end_phrase,
            direction="end",
        )
        if estimated_end is None:
            return float(ad_end), False, end_reason, "end_phrase_not_found"

        return (
            self._constrain_end(float(estimated_end), ad_end),
            True,
            end_reason,
            None,
        )

    def _get_context(
        self,
        ad_start: float,
        ad_end: float,
        all_segments: List[Dict[str, Any]],
        *,
        first_seq_num: Optional[int],
        last_seq_num: Optional[int],
    ) -> List[Dict[str, Any]]:
        selected = self._context_by_seq_window(
            all_segments,
            first_seq_num=first_seq_num,
            last_seq_num=last_seq_num,
        )
        if selected:
            return selected

        return self._context_by_time_overlap(ad_start, ad_end, all_segments)

    def _context_by_seq_window(
        self,
        all_segments: List[Dict[str, Any]],
        *,
        first_seq_num: Optional[int],
        last_seq_num: Optional[int],
    ) -> List[Dict[str, Any]]:
        if first_seq_num is None or last_seq_num is None or not all_segments:
            return []

        seq_values: List[int] = []
        for segment in all_segments:
            try:
                seq_values.append(int(segment.get("sequence_num", -1)))
            except Exception:
                continue
        if not seq_values:
            return []

        min_seq = min(seq_values)
        max_seq = max(seq_values)
        start_seq = max(min_seq, int(first_seq_num) - 2)
        end_seq = min(max_seq, int(last_seq_num) + 2)

        selected: List[Dict[str, Any]] = []
        for segment in all_segments:
            try:
                seq = int(segment.get("sequence_num", -1))
            except Exception:
                continue
            if start_seq <= seq <= end_seq:
                selected.append(segment)

        return selected

    def _context_by_time_overlap(
        self,
        ad_start: float,
        ad_end: float,
        all_segments: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        ad_segs = [
            s for s in all_segments if self._segment_overlaps(s, ad_start, ad_end)
        ]
        if not ad_segs:
            return []

        first_idx = all_segments.index(ad_segs[0])
        last_idx = all_segments.index(ad_segs[-1])
        start_idx = max(0, first_idx - 2)
        end_idx = min(len(all_segments), last_idx + 3)
        return all_segments[start_idx:end_idx]

    @staticmethod
    def _segment_overlaps(
        segment: Dict[str, Any], ad_start: float, ad_end: float
    ) -> bool:
        try:
            seg_start = float(segment.get("start_time", 0.0))
        except Exception:
            seg_start = 0.0
        try:
            seg_end = float(segment.get("end_time", seg_start))
        except Exception:
            seg_end = seg_start
        return seg_start <= float(ad_end) and seg_end >= float(ad_start)

    def _estimate_phrase_times(
        self,
        *,
        all_segments: List[Dict[str, Any]],
        context_segments: List[Dict[str, Any]],
        start_segment_seq: Any,
        start_phrase: Any,
        end_segment_seq: Any,
        end_phrase: Any,
    ) -> Tuple[Optional[float], Optional[float]]:
        start_time = self._estimate_phrase_time(
            all_segments=all_segments,
            context_segments=context_segments,
            preferred_segment_seq=start_segment_seq,
            phrase=start_phrase,
            direction="start",
        )
        end_time = self._estimate_phrase_time(
            all_segments=all_segments,
            context_segments=context_segments,
            preferred_segment_seq=end_segment_seq,
            phrase=end_phrase,
            direction="end",
        )
        return start_time, end_time

    def _estimate_phrase_time(
        self,
        *,
        all_segments: List[Dict[str, Any]],
        context_segments: List[Dict[str, Any]],
        preferred_segment_seq: Any,
        phrase: Any,
        direction: str,
    ) -> Optional[float]:
        phrase_tokens = self._split_words(str(phrase or ""))
        phrase_tokens = [t.lower() for t in phrase_tokens if t]
        if not phrase_tokens:
            return None

        # Search order:
        # 1) preferred segment (if provided)
        # 2) other provided context segments (ad-range ±2)
        candidates: List[Dict[str, Any]] = []
        preferred_seg = self._find_segment(all_segments, preferred_segment_seq)
        if preferred_seg is not None:
            candidates.append(preferred_seg)

        # De-duplicate and order additional candidates.
        ordered_context = list(context_segments or [])
        try:
            ordered_context.sort(key=lambda s: int(s.get("sequence_num", -1)))
        except Exception:
            pass
        if direction == "end":
            ordered_context = list(reversed(ordered_context))

        preferred_seq_int: Optional[int]
        try:
            preferred_seq_int = int(preferred_segment_seq)
        except Exception:
            preferred_seq_int = None

        for seg in ordered_context:
            try:
                seq = int(seg.get("sequence_num", -1))
            except Exception:
                seq = None
            if preferred_seq_int is not None and seq == preferred_seq_int:
                continue
            candidates.append(seg)

        for seg in candidates:
            start_time = float(seg.get("start_time", 0.0))
            end_time = float(seg.get("end_time", start_time))
            duration = max(0.0, end_time - start_time)
            words = [w.lower() for w in self._split_words(str(seg.get("text", "")))]
            if not words or duration <= 0.0:
                continue

            match = self._find_phrase_match(
                words=words,
                phrase_tokens=phrase_tokens,
                direction=direction,
                max_words=4,
            )
            if match is None:
                continue

            match_start_idx, match_end_idx = match
            seconds_per_word = duration / float(len(words))
            if direction == "start":
                estimated = start_time + (float(match_start_idx) * seconds_per_word)
                return min(estimated, end_time)

            # direction == "end": end boundary at the end of the last matched word.
            estimated = start_time + (float(match_end_idx + 1) * seconds_per_word)
            return min(estimated, end_time)

        return None

    def _find_phrase_match(
        self,
        *,
        words: List[str],
        phrase_tokens: List[str],
        direction: str,
        max_words: int,
    ) -> Optional[Tuple[int, int]]:
        if not words or not phrase_tokens:
            return None

        if direction == "start":
            base = phrase_tokens[:max_words]
            for k in range(len(base), 0, -1):
                target = base[:k]
                match = self._find_subsequence(words, target, choose="first")
                if match is not None:
                    return match
            return None

        # direction == "end"
        base = phrase_tokens[-max_words:]
        for k in range(len(base), 0, -1):
            target = base[-k:]
            match = self._find_subsequence(words, target, choose="last")
            if match is not None:
                return match
        return None

    def _find_subsequence(
        self, words: List[str], target: List[str], *, choose: str
    ) -> Optional[Tuple[int, int]]:
        if not target or len(target) > len(words):
            return None

        matches: List[Tuple[int, int]] = []
        k = len(target)
        for i in range(0, len(words) - k + 1):
            if words[i : i + k] == target:
                matches.append((i, i + k - 1))

        if not matches:
            return None
        if choose == "last":
            return matches[-1]
        return matches[0]

    def _estimate_word_time(
        self,
        *,
        all_segments: List[Dict[str, Any]],
        segment_seq: Any,
        word: Any,
        occurrence: Any,
        word_index: Any,
    ) -> float:
        seg = self._find_segment(all_segments, segment_seq)
        if not seg:
            return float(all_segments[0]["start_time"]) if all_segments else 0.0

        start_time = float(seg.get("start_time", 0.0))
        end_time = float(seg.get("end_time", start_time))
        duration = max(0.0, end_time - start_time)

        words = self._split_words(str(seg.get("text", "")))
        if not words or duration <= 0.0:
            return start_time

        resolved_index = self._resolve_word_index(
            words,
            word=word,
            occurrence=occurrence,
            word_index=word_index,
        )

        # Heuristic timing: constant word duration within the segment.
        # words_per_second = num_words / segment_duration
        # seconds_per_word = 1 / words_per_second = segment_duration / num_words
        seconds_per_word = duration / float(len(words))
        estimated = start_time + (float(resolved_index) * seconds_per_word)
        # Guardrail: never return a start after the block end.
        return min(estimated, float(seg.get("end_time", end_time)))

    def _find_segment(
        self, all_segments: List[Dict[str, Any]], segment_seq: Any
    ) -> Optional[Dict[str, Any]]:
        if segment_seq is None:
            return None
        try:
            seq_int = int(segment_seq)
        except Exception:
            return None

        for seg in all_segments:
            if int(seg.get("sequence_num", -1)) == seq_int:
                return seg
        return None

    def _split_words(self, text: str) -> List[str]:
        # Word count/indexing heuristic: split on whitespace, then normalize away
        # leading/trailing punctuation to keep indices stable.
        raw_tokens = [t for t in re.split(r"\s+", (text or "").strip()) if t]
        normalized = [self._normalize_token(t) for t in raw_tokens]
        return [t for t in normalized if t]

    def _normalize_token(self, token: str) -> str:
        # Strip leading/trailing punctuation; keep internal apostrophes.
        # Examples:
        #   "(brought" -> "brought"
        #   "you..." -> "you"
        #   "don't" -> "don't"
        return re.sub(r"(^[^A-Za-z0-9']+)|([^A-Za-z0-9']+$)", "", token)

    def _resolve_word_index(
        self, words: List[str], *, word: Any, occurrence: Any, word_index: Any
    ) -> int:
        # Prefer the verbatim word match if provided.
        # `occurance` chooses which matching instance to use.
        # Defaults to "first" if missing/invalid.
        target_raw = str(word).strip() if word is not None else ""
        target = self._normalize_token(target_raw).lower()
        if target:
            match_indexes = [
                idx for idx, w in enumerate(words) if (w or "").lower() == target
            ]
            if match_indexes:
                occ = str(occurrence).strip().lower() if occurrence is not None else ""
                if occ == "last":
                    return match_indexes[-1]
                # Default to first if LLM response is missing/invalid.
                return match_indexes[0]

        try:
            idx_int = int(word_index)
        except Exception:
            idx_int = 0

        idx_int = max(0, min(idx_int, len(words) - 1))
        return idx_int

    def _update_model_call(
        self,
        model_call_id: Optional[int],
        *,
        status: str,
        response: Optional[str],
        error_message: Optional[str],
    ) -> None:
        try_update_model_call(
            model_call_id,
            status=status,
            response=response,
            error_message=error_message,
            logger=self.logger,
            log_prefix="Word boundary refine",
        )
