from typing import List, Literal, Optional

from pydantic import BaseModel


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


def clean_and_parse_model_output(model_output: str) -> AdSegmentPredictionList:
    start_marker, end_marker = "{", "}"

    assert model_output.count(start_marker) >= 1, f"{model_output}"
    assert model_output.count(end_marker) >= 1, f"{model_output}"
    model_output = model_output[
        model_output.index(start_marker) : 1 + model_output.rindex(end_marker)
    ]

    model_output = model_output.replace("'", '"')
    model_output = model_output.replace("\n", "")
    model_output = model_output.strip()

    return AdSegmentPredictionList.parse_raw(model_output)
