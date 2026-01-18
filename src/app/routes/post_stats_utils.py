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
