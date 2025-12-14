import pytest
from pydantic import ValidationError

from podcast_processor.model_output import (
    AdSegmentPrediction,
    AdSegmentPredictionList,
    clean_and_parse_model_output,
)


def test_clean_parse_output() -> None:
    model_outupt = """
extra stuff bla bla
{"ad_segments": [{"segment_offset": 123.45, "confidence": 0.7}]}. Note: Advertisements in the above podcast excerpt are identified with a moderate level of confidence due to their promotional nature, but not being from within the core content (i.e., discussing the movie or artwork) which suggests these segments could be a
"""
    assert clean_and_parse_model_output(model_outupt) == AdSegmentPredictionList(
        ad_segments=[
            AdSegmentPrediction(
                segment_offset=123.45,
                confidence=0.7,
            )
        ]
    )


def test_parse_multiple_segments_output() -> None:
    model_outupt = """
{"ad_segments": [
    {"segment_offset": 123.45, "confidence": 0.7},
    {"segment_offset": 23.45, "confidence": 0.8},
    {"segment_offset": 45.67, "confidence": 0.9}
]
}"""
    assert clean_and_parse_model_output(model_outupt) == AdSegmentPredictionList(
        ad_segments=[
            AdSegmentPrediction(segment_offset=123.45, confidence=0.7),
            AdSegmentPrediction(segment_offset=23.45, confidence=0.8),
            AdSegmentPrediction(segment_offset=45.67, confidence=0.9),
        ]
    )


def test_clean_parse_output_malformed() -> None:
    model_outupt = """
{"ad_segments": uhoh1.7, 1114.8, 1116.4, 1118.2, 1119.5, 1121.0, 1123.2, 1125.2], "confidence": 0.7}. Note: Advertisements in the above podcast excerpt are identified with a moderate level of confidence due to their promotional nature, but not being from within the core content (i.e., discussing the movie or artwork) which suggests these segments could be a
"""
    with pytest.raises(ValidationError):
        clean_and_parse_model_output(model_outupt)


def test_clean_parse_output_with_content_type() -> None:
    model_output = """
{"ad_segments": [{"segment_offset": 12.0, "confidence": 0.86}], "content_type": "promotional_external", "confidence": 0.91}
"""

    assert clean_and_parse_model_output(model_output) == AdSegmentPredictionList(
        ad_segments=[AdSegmentPrediction(segment_offset=12.0, confidence=0.86)],
        content_type="promotional_external",
        confidence=0.91,
    )


def test_clean_parse_output_truncated_missing_closing_brackets() -> None:
    """Test parsing truncated JSON missing closing ]} at the end."""
    model_output = '{"ad_segments":[{"segment_offset":10.5,"confidence":0.92}'
    result = clean_and_parse_model_output(model_output)
    assert result == AdSegmentPredictionList(
        ad_segments=[AdSegmentPrediction(segment_offset=10.5, confidence=0.92)]
    )


def test_clean_parse_output_truncated_multiple_segments() -> None:
    """Test parsing truncated JSON with multiple complete segments but missing closing."""
    model_output = '{"ad_segments":[{"segment_offset":10.5,"confidence":0.92},{"segment_offset":25.0,"confidence":0.85}'
    result = clean_and_parse_model_output(model_output)
    assert result == AdSegmentPredictionList(
        ad_segments=[
            AdSegmentPrediction(segment_offset=10.5, confidence=0.92),
            AdSegmentPrediction(segment_offset=25.0, confidence=0.85),
        ]
    )


def test_clean_parse_output_truncated_with_content_type() -> None:
    """Test parsing truncated JSON that includes content_type but is missing final }."""
    model_output = '{"ad_segments":[{"segment_offset":12.0,"confidence":0.86}],"content_type":"promotional_external","confidence":0.92'
    result = clean_and_parse_model_output(model_output)
    assert result == AdSegmentPredictionList(
        ad_segments=[AdSegmentPrediction(segment_offset=12.0, confidence=0.86)],
        content_type="promotional_external",
        confidence=0.92,
    )
