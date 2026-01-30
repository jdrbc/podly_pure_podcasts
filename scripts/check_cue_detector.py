#!/usr/bin/env python3
"""Standalone test script for CueDetector.

Run directly: python scripts/check_cue_detector.py
"""

import os
import sys

from podcast_processor.cue_detector import CueDetector
from podcast_processor.prompt import transcript_excerpt_for_prompt
from podcast_processor.transcribe import Segment

# Add src directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))


def test_highlight_cues_url():
    detector = CueDetector()
    text = "Check out example.com for more info."
    # "Check out" is a CTA, "example.com" is a URL. Both should be highlighted.
    expected = "*** Check out *** *** example.com *** for more info."
    result = detector.highlight_cues(text)
    assert result == expected, f"Expected: {expected!r}, got: {result!r}"
    print("✓ test_highlight_cues_url passed")


def test_highlight_cues_promo():
    detector = CueDetector()
    text = "Use promo code SAVE20 now."
    # "promo code" matches promo_pattern.
    # "code SAVE20" would also match promo_pattern, but re.finditer is non-overlapping for a single pattern.
    # So only "promo code" is captured.
    expected = "Use *** promo code *** SAVE20 now."
    result = detector.highlight_cues(text)
    assert result == expected, f"Expected: {expected!r}, got: {result!r}"
    print("✓ test_highlight_cues_promo passed")


def test_highlight_cues_cta():
    detector = CueDetector()
    text = "Please visit our website."
    expected = "Please *** visit *** our website."
    result = detector.highlight_cues(text)
    assert result == expected, f"Expected: {expected!r}, got: {result!r}"
    print("✓ test_highlight_cues_cta passed")


def test_highlight_cues_multiple():
    detector = CueDetector()
    text = "Visit example.com and use code TEST."
    # "Visit" -> cta
    # "example.com" -> url
    # "use code" -> cta
    # "code TEST" -> promo
    # "use code TEST" -> "use code" (cta) overlaps with "code TEST" (promo)
    # "use code" (22, 30)
    # "code TEST" (26, 35)
    # Merged: (22, 35) -> "use code TEST"
    expected = "*** Visit *** *** example.com *** and *** use code TEST ***."
    result = detector.highlight_cues(text)
    assert result == expected, f"Expected: {expected!r}, got: {result!r}"
    print("✓ test_highlight_cues_multiple passed")


def test_highlight_cues_no_cues():
    detector = CueDetector()
    text = "Just a normal sentence."
    result = detector.highlight_cues(text)
    assert result == text, f"Expected: {text!r}, got: {result!r}"
    print("✓ test_highlight_cues_no_cues passed")


def test_integration_prompt():
    segments = [
        Segment(start=10.0, end=15.0, text="Welcome back to the show."),
        Segment(start=15.0, end=20.0, text="Go to mywebsite.com today."),
    ]
    result = transcript_excerpt_for_prompt(
        segments, includes_start=False, includes_end=False
    )

    # "back to the show" is a transition cue
    expected_line1 = "[10.0] Welcome *** back to the show ***."
    # "Go to" is CTA, "mywebsite.com" is URL
    expected_line2 = "[15.0] *** Go to *** *** mywebsite.com *** today."

    assert (
        expected_line1 in result
    ), f"Expected to find {expected_line1!r} in {result!r}"
    assert (
        expected_line2 in result
    ), f"Expected to find {expected_line2!r} in {result!r}"
    print("✓ test_integration_prompt passed")


def main():
    """Run all tests."""
    print("Running CueDetector checks...")
    print()

    test_highlight_cues_url()
    test_highlight_cues_promo()
    test_highlight_cues_cta()
    test_highlight_cues_multiple()
    test_highlight_cues_no_cues()
    test_integration_prompt()

    print()
    print("All CueDetector checks passed! ✓")


if __name__ == "__main__":
    main()
