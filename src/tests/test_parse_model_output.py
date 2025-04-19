import pytest

from podcast_processor.model_output import (
    AdSegmentPrediction,
    AdSegmentPredictionList,
    clean_and_parse_model_output,
)


def test_clean_parse_output() -> None:
    model_outupt = """
extra stuff bla bla
[{"segment_offset": 123.45, "confidence": 0.7}]. Note: Advertisements in the above podcast excerpt are identified with a moderate level of confidence due to their promotional nature, but not being from within the core content (i.e., discussing the movie or artwork) which suggests these segments could be a
"""
    assert clean_and_parse_model_output(model_outupt) == AdSegmentPredictionList(
        [
            AdSegmentPrediction(
                segment_offset=123.45,
                confidence=0.7,
            )
        ]
    )


def test_parse_multiple_segments_output() -> None:
    model_outupt = """
[
    {"segment_offset": 123.45, "confidence": 0.7},
    {"segment_offset": 23.45, "confidence": 0.8},
    {"segment_offset": 45.67, "confidence": 0.9}
]
"""
    assert clean_and_parse_model_output(model_outupt) == AdSegmentPredictionList(
        [
            AdSegmentPrediction(segment_offset=123.45, confidence=0.7),
            AdSegmentPrediction(segment_offset=23.45, confidence=0.8),
            AdSegmentPrediction(segment_offset=45.67, confidence=0.9),
        ]
    )


def test_clean_parse_output_malformed() -> None:
    model_outupt = """
{"ad_segments": uhoh1.7, 1114.8, 1116.4, 1118.2, 1119.5, 1121.0, 1123.2, 1125.2], "confidence": 0.7}. Note: Advertisements in the above podcast excerpt are identified with a moderate level of confidence due to their promotional nature, but not being from within the core content (i.e., discussing the movie or artwork) which suggests these segments could be a
"""
    with pytest.raises(AssertionError):
        clean_and_parse_model_output(model_outupt)
