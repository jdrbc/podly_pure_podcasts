import re
from typing import Dict, List, Pattern, Tuple


class CueDetector:
    def __init__(self) -> None:
        self.url_pattern: Pattern[str] = re.compile(
            r"\b([a-z0-9\-\.]+\.(?:com|net|org|io))\b", re.I
        )
        self.promo_pattern: Pattern[str] = re.compile(
            r"\b(code|promo|save|discount)\s+\w+\b", re.I
        )
        self.phone_pattern: Pattern[str] = re.compile(
            r"\b(?:\+?1[ -]?)?\d{3}[ -]?\d{3}[ -]?\d{4}\b"
        )
        self.cta_pattern: Pattern[str] = re.compile(
            r"\b(visit|go to|check out|head over|sign up|start today|start now|use code|offer|deal|free trial)\b",
            re.I,
        )
        self.transition_pattern: Pattern[str] = re.compile(
            r"\b(back to the show|after the break|stay tuned|we'll be right back|now back)\b",
            re.I,
        )
        self.self_promo_pattern: Pattern[str] = re.compile(
            r"\b(my|our)\s+(book|course|newsletter|fund|patreon|substack|community|platform)\b",
            re.I,
        )

    def has_cue(self, text: str) -> bool:
        return bool(
            self.url_pattern.search(text)
            or self.promo_pattern.search(text)
            or self.phone_pattern.search(text)
            or self.cta_pattern.search(text)
        )

    def analyze(self, text: str) -> Dict[str, bool]:
        return {
            "url": bool(self.url_pattern.search(text)),
            "promo": bool(self.promo_pattern.search(text)),
            "phone": bool(self.phone_pattern.search(text)),
            "cta": bool(self.cta_pattern.search(text)),
            "transition": bool(self.transition_pattern.search(text)),
            "self_promo": bool(self.self_promo_pattern.search(text)),
        }

    def highlight_cues(self, text: str) -> str:
        """
        Highlights detected cues in the text by wrapping them in *** ***.
        Useful for drawing attention to cues in LLM prompts.
        """
        matches: List[Tuple[int, int]] = []
        patterns = [
            self.url_pattern,
            self.promo_pattern,
            self.phone_pattern,
            self.cta_pattern,
            self.transition_pattern,
            self.self_promo_pattern,
        ]

        for pattern in patterns:
            for match in pattern.finditer(text):
                matches.append(match.span())

        if not matches:
            return text

        # Sort by start, then end (descending) to handle containment
        matches.sort(key=lambda x: (x[0], -x[1]))

        # Merge overlapping intervals
        merged: List[Tuple[int, int]] = []
        if matches:
            curr_start, curr_end = matches[0]
            for next_start, next_end in matches[1:]:
                if next_start < curr_end:  # Overlap
                    curr_end = max(curr_end, next_end)
                else:
                    merged.append((curr_start, curr_end))
                    curr_start, curr_end = next_start, next_end
            merged.append((curr_start, curr_end))

        # Reconstruct string backwards to avoid index shifting
        result_parts = []
        last_idx = len(text)

        for start, end in reversed(merged):
            result_parts.append(text[end:last_idx])  # Unchanged suffix
            result_parts.append(" ***")
            result_parts.append(text[start:end])  # The match
            result_parts.append("*** ")
            last_idx = start

        result_parts.append(text[:last_idx])  # Remaining prefix

        return "".join(reversed(result_parts))
