import logging
import re
from typing import List, Literal, Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class AdSegmentPrediction(BaseModel):
    segment_offset: float
    confidence: float


class AdSegmentPredictionList(BaseModel):
    ad_segments: List[AdSegmentPrediction]
    content_type: Optional[
        Literal[
            "technical_discussion",
            "educational/self_promo",
            "promotional_external",
            "transition",
        ]
    ] = None
    confidence: Optional[float] = None


def _attempt_json_repair(json_str: str) -> str:
    """
    Attempt to repair truncated JSON by adding missing closing brackets.

    This handles cases where the LLM response was cut off mid-JSON,
    e.g., '{"ad_segments":[{"segment_offset":10.5,"confidence":0.92}'
    """
    # Count opening and closing brackets/braces
    open_braces = json_str.count("{")
    close_braces = json_str.count("}")
    open_brackets = json_str.count("[")
    close_brackets = json_str.count("]")

    # If brackets are balanced, no repair needed
    if open_braces == close_braces and open_brackets == close_brackets:
        return json_str

    logger.warning(
        f"Detected unbalanced JSON: {open_braces} '{{' vs {close_braces} '}}', "
        f"{open_brackets} '[' vs {close_brackets} ']'. Attempting repair."
    )

    # Remove any trailing incomplete key-value pair
    # e.g., '..."confidence":0.9' or '..."key":"val' or '..."key":'
    # First, try to find the last complete value
    repaired = json_str.rstrip()

    # If ends with a comma, remove it (incomplete next element)
    repaired = repaired.rstrip(",")

    # If ends with a colon or incomplete string, try to truncate to last complete element
    # Pattern: ends with "key": or "key":"incomplete or similar
    incomplete_patterns = [
        r',"[^"]*":\s*$',  # ,"key":
        r',"[^"]*":\s*"[^"]*$',  # ,"key":"incomplete
    ]

    for pattern in incomplete_patterns:
        match = re.search(pattern, repaired)
        if match:
            repaired = repaired[: match.start()]
            logger.debug(f"Removed incomplete trailing content: {match.group()}")
            break

    # Recount after cleanup
    open_braces = repaired.count("{")
    close_braces = repaired.count("}")
    open_brackets = repaired.count("[")
    close_brackets = repaired.count("]")

    # Add missing closing brackets/braces in the right order
    # We need to determine the order based on the structure
    # Typically for our schema it's: ]} to close ad_segments array and outer object
    missing_brackets = close_brackets - open_brackets  # negative means we need more ]
    missing_braces = close_braces - open_braces  # negative means we need more }

    if missing_brackets < 0:
        repaired += "]" * abs(missing_brackets)
    if missing_braces < 0:
        repaired += "}" * abs(missing_braces)

    logger.info("Repaired JSON by adding missing closing brackets/braces")

    return repaired


def clean_and_parse_model_output(model_output: str) -> AdSegmentPredictionList:
    start_marker, end_marker = "{", "}"

    assert (
        model_output.count(start_marker) >= 1
    ), f"No opening brace found in: {model_output[:200]}"

    start_idx = model_output.index(start_marker)
    model_output = model_output[start_idx:]

    # If we have at least as many closing braces as opening braces, trim to the last
    # closing brace to drop any trailing non-JSON content. Otherwise, keep the
    # content as-is so we can attempt repair on truncated JSON.
    open_braces = model_output.count(start_marker)
    close_braces = model_output.count(end_marker)
    if close_braces >= open_braces and close_braces > 0:
        model_output = model_output[: 1 + model_output.rindex(end_marker)]

    model_output = model_output.replace("'", '"')
    model_output = model_output.replace("\n", "")
    model_output = model_output.strip()

    # First attempt: try to parse as-is
    try:
        return AdSegmentPredictionList.parse_raw(model_output)
    except Exception as first_error:
        logger.debug(f"Initial parse failed: {first_error}")

        # Second attempt: try to repair truncated JSON
        try:
            repaired_output = _attempt_json_repair(model_output)
            result = AdSegmentPredictionList.parse_raw(repaired_output)
            logger.info("Successfully parsed model output after JSON repair")
            return result
        except Exception as repair_error:
            logger.error(
                f"JSON repair also failed. Original output (first 500 chars): {model_output[:500]}"
            )
            # Re-raise the original error with more context
            raise first_error from repair_error
