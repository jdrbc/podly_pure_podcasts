from typing import List

from pydantic import BaseModel, RootModel


class AdSegmentPrediction(BaseModel):
    segment_offset: float
    confidence: float


class AdSegmentPredictionList(RootModel[List[AdSegmentPrediction]]):
    pass


def clean_and_parse_model_output(model_output: str) -> AdSegmentPredictionList:
    assert model_output.count("[") == 1, f"{model_output}"
    assert model_output.count("]") == 1, f"{model_output}"
    model_output = model_output[model_output.index("[") : 1 + model_output.index("]")]

    model_output = model_output.replace("'", '"')
    model_output = model_output.replace("\n", "")
    model_output = model_output.strip()

    return AdSegmentPredictionList.parse_raw(model_output)
