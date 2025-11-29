import re
from typing import Pattern


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

    def has_cue(self, text: str) -> bool:
        return bool(
            self.url_pattern.search(text)
            or self.promo_pattern.search(text)
            or self.phone_pattern.search(text)
        )
