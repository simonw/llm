import pytest
from llm.utils import simplify_usage_dict


@pytest.mark.parametrize(
    "input_data,expected_output",
    [
        (
            {
                "prompt_tokens_details": {"cached_tokens": 0, "audio_tokens": 0},
                "completion_tokens_details": {
                    "reasoning_tokens": 0,
                    "audio_tokens": 1,
                    "accepted_prediction_tokens": 0,
                    "rejected_prediction_tokens": 0,
                },
            },
            {"completion_tokens_details": {"audio_tokens": 1}},
        ),
        (
            {
                "details": {"tokens": 5, "audio_tokens": 2},
                "more_details": {"accepted_tokens": 3},
            },
            {
                "details": {"tokens": 5, "audio_tokens": 2},
                "more_details": {"accepted_tokens": 3},
            },
        ),
        ({"details": {"tokens": 0, "audio_tokens": 0}, "more_details": {}}, {}),
        ({"level1": {"level2": {"value": 0, "another_value": {}}}}, {}),
        (
            {
                "level1": {"level2": {"value": 0, "another_value": 1}},
                "level3": {"empty_dict": {}, "valid_token": 10},
            },
            {"level1": {"level2": {"another_value": 1}}, "level3": {"valid_token": 10}},
        ),
    ],
)
def test_simplify_usage_dict(input_data, expected_output):
    assert simplify_usage_dict(input_data) == expected_output
