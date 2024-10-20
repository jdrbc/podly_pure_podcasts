import json
from typing import Any, List

from pydantic import BaseModel


class AdSegmentPrediction(BaseModel):
    ad_segments: List[float]
    confidence: float


def clean_and_parse_model_output(model_output: str) -> AdSegmentPrediction:
    assert model_output.count("{") == 1, f"{model_output}"
    assert model_output.count("}") == 1, f"{model_output}"
    model_output = model_output[model_output.index("{") : 1 + model_output.index("}")]

    model_output = model_output.replace("'", '"')
    model_output = model_output.replace("\n", "")
    model_output = model_output.strip()

    return AdSegmentPrediction.model_validate_json(model_output)
