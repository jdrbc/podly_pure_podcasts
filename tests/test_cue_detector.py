import unittest

from podcast_processor.cue_detector import CueDetector
from podcast_processor.prompt import transcript_excerpt_for_prompt
from podcast_processor.transcribe import Segment


class TestCueDetector(unittest.TestCase):
    def setUp(self) -> None:
        self.detector = CueDetector()

    def test_highlight_cues_url(self) -> None:
        text = "Check out example.com for more info."
        # "Check out" is a CTA, "example.com" is a URL. Both should be highlighted.
        expected = "*** Check out *** *** example.com *** for more info."
        self.assertEqual(self.detector.highlight_cues(text), expected)

    def test_highlight_cues_promo(self) -> None:
        text = "Use promo code SAVE20 now."
        # "promo code" matches promo_pattern.
        # "code SAVE20" would also match promo_pattern, but re.finditer is non-overlapping for a single pattern.
        # So only "promo code" is captured.
        expected = "Use *** promo code *** SAVE20 now."
        self.assertEqual(self.detector.highlight_cues(text), expected)

    def test_highlight_cues_cta(self) -> None:
        text = "Please visit our website."
        expected = "Please *** visit *** our website."
        self.assertEqual(self.detector.highlight_cues(text), expected)

    def test_highlight_cues_multiple(self) -> None:
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
        self.assertEqual(self.detector.highlight_cues(text), expected)

    def test_highlight_cues_no_cues(self) -> None:
        text = "Just a normal sentence."
        self.assertEqual(self.detector.highlight_cues(text), text)

    def test_integration_prompt(self) -> None:
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

        self.assertIn(expected_line1, result)
        self.assertIn(expected_line2, result)


if __name__ == "__main__":
    unittest.main()
