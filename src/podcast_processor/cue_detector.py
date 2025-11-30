import re
from typing import Dict, Pattern


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
