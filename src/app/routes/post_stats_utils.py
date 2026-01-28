from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple


def count_model_calls(
    model_calls: Iterable[Any],
) -> Tuple[Dict[str, int], Dict[str, int]]:
    model_call_statuses: Dict[str, int] = {}
    model_types: Dict[str, int] = {}

    for call in model_calls:
        status = getattr(call, "status", None)
        model_name = getattr(call, "model_name", None)

        if status is not None:
            model_call_statuses[status] = model_call_statuses.get(status, 0) + 1
        if model_name is not None:
            model_types[model_name] = model_types.get(model_name, 0) + 1

    return model_call_statuses, model_types


def group_identifications_by_segment(
    identifications: Iterable[Any],
) -> Dict[int, List[Any]]:
    grouped: Dict[int, List[Any]] = {}
    for ident in identifications:
        seg_id = getattr(ident, "transcript_segment_id", None)
        if seg_id is None:
            continue
        grouped.setdefault(int(seg_id), []).append(ident)
    return grouped


def count_primary_labels(
    transcript_segments: Iterable[Any],
    identifications_by_segment: Dict[int, List[Any]],
) -> Tuple[int, int]:
    content_segments = 0
    ad_segments = 0
    for segment in transcript_segments:
        seg_id = getattr(segment, "id", None)
        if seg_id is None:
            continue
        segment_identifications = identifications_by_segment.get(int(seg_id), [])
        has_ad_label = any(
            getattr(ident, "label", None) == "ad" for ident in segment_identifications
        )
        if has_ad_label:
            ad_segments += 1
        else:
            content_segments += 1
    return content_segments, ad_segments


def parse_refined_windows(raw_refined: Any) -> List[Tuple[float, float]]:
    refined_windows: List[Tuple[float, float]] = []
    if not isinstance(raw_refined, list):
        return refined_windows

    for item in raw_refined:
        if not isinstance(item, dict):
            continue

        start_raw = item.get("refined_start")
        end_raw = item.get("refined_end")
        if start_raw is None or end_raw is None:
            continue

        try:
            start_v = float(start_raw)
            end_v = float(end_raw)
        except Exception:
            continue

        if end_v > start_v:
            refined_windows.append((start_v, end_v))

    return refined_windows


def merge_time_windows(
    windows: List[Tuple[float, float]], gap_seconds: float = 1.0
) -> List[Tuple[float, float]]:
    if not windows:
        return []

    windows_sorted = sorted(windows, key=lambda w: w[0])
    merged: List[Tuple[float, float]] = []
    current_start, current_end = windows_sorted[0]

    for start, end in windows_sorted[1:]:
        if start <= current_end + gap_seconds:
            current_end = max(current_end, end)
        else:
            merged.append((current_start, current_end))
            current_start, current_end = start, end

    merged.append((current_start, current_end))
    return merged


def is_mixed_segment(
    *, seg_start: float, seg_end: float, refined_windows: List[Tuple[float, float]]
) -> bool:
    for win_start, win_end in refined_windows:
        overlaps = seg_start <= win_end and seg_end >= win_start
        if not overlaps:
            continue

        fully_contained = seg_start >= win_start and seg_end <= win_end
        if not fully_contained:
            return True

    return False
