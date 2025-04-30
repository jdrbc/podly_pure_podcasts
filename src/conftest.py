"""
Duplicate the mocking code from tests/conftest.py to ensure mocks are properly set up.
This file handles the case where tests are run from a different directory.
"""

import sys
from unittest.mock import MagicMock

whisper_mock = MagicMock()
whisper_mock.available_models.return_value = [
    "tiny",
    "base",
    "small",
    "medium",
    "large",
]
whisper_mock.load_model.return_value = MagicMock()
whisper_mock.load_model.return_value.transcribe.return_value = {"segments": []}

torch_mock = MagicMock()
torch_mock.cuda = MagicMock()
torch_mock.device = MagicMock()

# Pre-mock the modules to avoid imports during test collection
sys.modules["whisper"] = whisper_mock
sys.modules["torch"] = torch_mock
