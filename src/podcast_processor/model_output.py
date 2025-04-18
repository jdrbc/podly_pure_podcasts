import json
from typing import List

from pydantic import BaseModel


class AdSegmentPrediction(BaseModel):
    segment_id: float
    confidence: float


def clean_and_parse_model_output(model_output: str) -> List[AdSegmentPrediction]:
    assert model_output.count("[") == 1, f"{model_output}"
    assert model_output.count("]") == 1, f"{model_output}"
    model_output = model_output[model_output.index("[") : 1 + model_output.index("]")]

    model_output = model_output.replace("'", '"')
    model_output = model_output.replace("\n", "")
    model_output = model_output.strip()

    data = json.loads(model_output)

    try:
        return [AdSegmentPrediction(**item) for item in data]
    except TypeError:
        print(f"{model_output=}")
        raise
