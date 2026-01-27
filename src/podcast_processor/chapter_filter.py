"""Filter chapters by title strings to identify ad segments."""

import logging
from typing import List, Tuple

from podcast_processor.chapter_reader import Chapter

logger = logging.getLogger("global_logger")


def filter_chapters_by_strings(
    chapters: List[Chapter],
    filter_strings: List[str],
) -> Tuple[List[Chapter], List[Chapter]]:
    """
    Filter chapters by title containing any filter string (case-insensitive).

    Args:
        chapters: List of Chapter objects to filter
        filter_strings: List of strings to match against chapter titles

    Returns:
        Tuple of (chapters_to_keep, chapters_to_remove)
    """
    if not chapters:
        return [], []

    if not filter_strings:
        return chapters, []

    # Normalize filter strings to lowercase
    normalized_filters = [f.strip().lower() for f in filter_strings if f.strip()]

    chapters_to_keep: List[Chapter] = []
    chapters_to_remove: List[Chapter] = []

    for chapter in chapters:
        title_lower = chapter.title.lower()
        is_ad = any(f in title_lower for f in normalized_filters)

        if is_ad:
            chapters_to_remove.append(chapter)
            logger.debug("Marking chapter as ad: %s", chapter.title)
        else:
            chapters_to_keep.append(chapter)

    logger.info(
        "Filtered chapters: %d to keep, %d to remove",
        len(chapters_to_keep),
        len(chapters_to_remove),
    )

    return chapters_to_keep, chapters_to_remove


def parse_filter_strings(filter_strings_csv: str) -> List[str]:
    """
    Parse comma-separated filter strings into a list.

    Args:
        filter_strings_csv: Comma-separated string of filter terms

    Returns:
        List of individual filter strings, trimmed
    """
    if not filter_strings_csv:
        return []

    return [s.strip() for s in filter_strings_csv.split(",") if s.strip()]
