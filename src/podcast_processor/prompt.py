from typing import List

from podcast_processor.model_output import AdSegmentPrediction, AdSegmentPredictionList
from podcast_processor.transcribe import Segment

DEFAULT_SYSTEM_PROMPT_PATH = "src/system_prompt.txt"
DEFAULT_USER_PROMPT_TEMPLATE_PATH = "src/user_prompt.jinja"


def transcript_excerpt_for_prompt(
    segments: List[Segment], includes_start: bool, includes_end: bool
) -> str:

    excerpts = [f"[{segment.start}] {segment.text}" for segment in segments]
    if includes_start:
        excerpts.insert(0, "[TRANSCRIPT START]")
    if includes_end:
        excerpts.append("[TRANSCRIPT END]")

    return "\n".join(excerpts)


def generate_system_prompt() -> str:
    valid_non_empty_example = AdSegmentPredictionList(
        ad_segments=[
            AdSegmentPrediction(segment_offset=12.34, confidence=0.9),
            AdSegmentPrediction(segment_offset=56.78, confidence=0.8),
        ]
    ).model_dump_json()

    valid_empty_example = AdSegmentPredictionList(ad_segments=[]).model_dump_json()

    output_for_one_shot_example = AdSegmentPredictionList(
        ad_segments=[
            AdSegmentPrediction(segment_offset=59.8, confidence=0.9),
            AdSegmentPrediction(segment_offset=64.8, confidence=0.8),
            AdSegmentPrediction(segment_offset=73.8, confidence=0.9),
            AdSegmentPrediction(segment_offset=77.8, confidence=0.98),
            AdSegmentPrediction(segment_offset=79.8, confidence=0.88),
        ]
    ).model_dump_json()

    example_output_for_prompt = (
        output_for_one_shot_example[:-1]
        if output_for_one_shot_example.endswith("}")
        else output_for_one_shot_example
    )

    one_shot_transcript_example = transcript_excerpt_for_prompt(
        [
            Segment(start=53.8, end=-1, text="That's all coming after the break."),
            Segment(
                start=59.8,
                end=-1,
                text="On this week's episode of Wildcard, actor Chris Pine tells "
                "us, it's okay not to be perfect.",
            ),
            Segment(
                start=64.8,
                end=-1,
                text="My film got absolutely decimated when it premiered, which "
                "brings up for me one of my primary triggers or whatever it was "
                "like, not being liked.",
            ),
            Segment(
                start=73.8,
                end=-1,
                text="I'm Rachel Martin, Chris Pine on How to Find Joy in Imperfection.",
            ),
            Segment(
                start=77.8,
                end=-1,
                text="That's on the new podcast, Wildcard.",
            ),
            Segment(
                start=79.8,
                end=-1,
                text="The Game Where Cards control the conversation.",
            ),
            Segment(
                start=83.8,
                end=-1,
                text="And welcome back to the show, today we're talking to Professor Hopkins",
            ),
        ],
        includes_start=False,
        includes_end=False,
    )

    # pylint: disable=line-too-long
    return f"""Your job is to identify ads in excerpts of podcast transcripts. Ads are for other network podcasts and products or services.

There may be a pre-roll ad before the intro, as well as mid-roll and an end-roll ad after the outro.

Ad breaks are between 15 seconds and 120 seconds long.

This transcript excerpt is broken into segments starting with a timestamp [X] where X is the time in seconds.

Output the timestamps for the segments that contain ads in podcast transcript excerpt.

Include a confidence score out of 1 for the the classification, with 1 being the most confident and 0 being the least confident.

Respond with valid JSON: {valid_non_empty_example}.

If there are no ads respond: {valid_empty_example}. Do not respond with anything else.

For example, given the transcript excerpt:

{one_shot_transcript_example}

Output: {example_output_for_prompt}.\n\n"""
