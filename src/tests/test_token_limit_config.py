"""
Simple integration test for the llm_max_input_tokens_per_call feature.
"""

from shared.test_utils import create_standard_test_config


def test_config_validation():
    """Test that the config validation works with the new setting."""
    # Test with token limit
    config_with_limit = create_standard_test_config(llm_max_input_tokens_per_call=50000)

    assert config_with_limit.llm_max_input_tokens_per_call == 50000
    assert config_with_limit.processing.num_segments_to_input_to_prompt == 400

    # Test without token limit
    config_without_limit = create_standard_test_config()

    assert config_without_limit.llm_max_input_tokens_per_call is None
    assert config_without_limit.processing.num_segments_to_input_to_prompt == 400


if __name__ == "__main__":
    test_config_validation()
    print("✓ Config validation test passed!")
