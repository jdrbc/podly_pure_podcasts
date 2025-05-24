"""Utility functions for rendering content to display formats."""

import bleach
from markupsafe import Markup

from app.models import Post


def render_transcript_html(post: Post) -> Markup:
    """Create an HTML representation of the transcript segments, highlighting ads.

    Args:
        post: The Post object containing transcript segments to render

    Returns:
        HTML markup of the transcript with ads highlighted
    """
    all_segments = post.segments.all()
    if not all_segments:
        return Markup("<p>No transcript segments available.</p>")

    rendered_html_parts = []
    for segment in all_segments:
        is_ad = any(ident.label == "ad" for ident in segment.identifications)
        segment_text_cleaned = bleach.clean(segment.text, tags=[], strip=True)

        if is_ad:
            rendered_html_parts.append(
                f'<p class="ad-segment"><strong>{segment.start_time:.1f}s - {segment.end_time:.1f}s (Ad):</strong> {segment_text_cleaned}</p>'
            )
        else:
            rendered_html_parts.append(
                f"<p><strong>{segment.start_time:.1f}s - {segment.end_time:.1f}s:</strong> {segment_text_cleaned}</p>"
            )

    return Markup("".join(rendered_html_parts))
