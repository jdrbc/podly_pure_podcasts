"""Shared helpers for working with LLM provider quirks."""
from __future__ import annotations

from typing import Final

# Patterns for models that require the `max_completion_tokens` parameter
# instead of the legacy `max_tokens`. OpenAI began enforcing this on the
# newer gpt-4o / gpt-5 / o1 style models.
_MAX_COMPLETION_TOKEN_MODELS: Final[tuple[str, ...]] = (
    "gpt-5",
    "gpt-4o",
    "o1-",
    "o1_",
    "o1/",
    "chatgpt-4o-latest",
)


def model_uses_max_completion_tokens(model_name: str | None) -> bool:
    """Return True when the target model expects `max_completion_tokens`."""
    if not model_name:
        return False
    model_lower = model_name.lower()
    return any(pattern in model_lower for pattern in _MAX_COMPLETION_TOKEN_MODELS)
