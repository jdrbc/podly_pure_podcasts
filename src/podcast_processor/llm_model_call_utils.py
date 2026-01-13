from __future__ import annotations

import logging
from typing import Any, Optional

from app.writer.client import writer_client


def render_prompt_and_upsert_model_call(
    *,
    template: Any,
    ad_start: float,
    ad_end: float,
    confidence: float,
    context_segments: Any,
    post_id: Optional[int],
    first_seq_num: Optional[int],
    last_seq_num: Optional[int],
    model_name: str,
    logger: logging.Logger,
    log_prefix: str,
) -> tuple[str, Optional[int]]:
    prompt = template.render(
        ad_start=ad_start,
        ad_end=ad_end,
        ad_confidence=confidence,
        context_segments=context_segments,
    )

    model_call_id = try_upsert_model_call(
        post_id=post_id,
        first_seq_num=first_seq_num,
        last_seq_num=last_seq_num,
        model_name=model_name,
        prompt=prompt,
        logger=logger,
        log_prefix=log_prefix,
    )

    return prompt, model_call_id


def try_upsert_model_call(
    *,
    post_id: Optional[int],
    first_seq_num: Optional[int],
    last_seq_num: Optional[int],
    model_name: str,
    prompt: str,
    logger: logging.Logger,
    log_prefix: str,
) -> Optional[int]:
    """Best-effort ModelCall creation.

    Returns model_call_id if successfully created/upserted, else None.
    """
    if post_id is None or first_seq_num is None or last_seq_num is None:
        return None

    try:
        res = writer_client.action(
            "upsert_model_call",
            {
                "post_id": post_id,
                "model_name": model_name,
                "first_segment_sequence_num": first_seq_num,
                "last_segment_sequence_num": last_seq_num,
                "prompt": prompt,
            },
            wait=True,
        )
        if res and res.success:
            return (res.data or {}).get("model_call_id")
    except Exception as exc:  # best-effort
        logger.warning("%s: failed to upsert ModelCall: %s", log_prefix, exc)

    return None


def try_update_model_call(
    model_call_id: Optional[int],
    *,
    status: str,
    response: Optional[str],
    error_message: Optional[str],
    logger: logging.Logger,
    log_prefix: str,
) -> None:
    """Best-effort ModelCall updater; no-op if call creation failed."""
    if model_call_id is None:
        return

    try:
        writer_client.update(
            "ModelCall",
            int(model_call_id),
            {
                "status": status,
                "response": response,
                "error_message": error_message,
                "retry_attempts": 1,
            },
            wait=True,
        )
    except Exception as exc:  # best-effort
        logger.warning(
            "%s: failed to update ModelCall %s: %s",
            log_prefix,
            model_call_id,
            exc,
        )


def extract_litellm_content(response: Any) -> str:
    """Extracts the primary text content from a litellm completion response."""
    choices = getattr(response, "choices", None) or []
    choice = choices[0] if choices else None
    if not choice:
        return ""

    # Prefer chat content; fall back to text for completion-style responses
    content = getattr(getattr(choice, "message", None), "content", None) or ""
    if not content:
        content = getattr(choice, "text", "") or ""
    return str(content)
