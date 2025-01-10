import pytest
from llm.utils import simplify_usage_dict, extract_first_fenced_code_block


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


@pytest.mark.parametrize(
    "input,expected",
    [
        ["This is a sample text without any code blocks.", None],
        [
            "Here is some text.\n\n```\ndef foo():\n    return 'bar'\n```\n\nMore text.",
            "def foo():\n    return 'bar'\n",
        ],
        [
            "Here is some text.\n\n```python\ndef foo():\n    return 'bar'\n```\n\nMore text.",
            "def foo():\n    return 'bar'\n",
        ],
        [
            "Here is some text.\n\n````\ndef foo():\n    return 'bar'\n````\n\nMore text.",
            "def foo():\n    return 'bar'\n",
        ],
        [
            "Here is some text.\n\n````javascript\nfunction foo() {\n    return 'bar';\n}\n````\n\nMore text.",
            "function foo() {\n    return 'bar';\n}\n",
        ],
        [
            "Here is some text.\n\n```python\ndef foo():\n    return 'bar'\n````\n\nMore text.",
            None,
        ],
        [
            "First code block:\n\n```python\ndef foo():\n    return 'bar'\n```\n\n"
            "Second code block:\n\n```javascript\nfunction foo() {\n    return 'bar';\n}\n```",
            "def foo():\n    return 'bar'\n",
        ],
        [
            "Here is some text.\n\n```python\ndef foo():\n    return `bar`\n```\n\nMore text.",
            "def foo():\n    return `bar`\n",
        ],
    ],
)
def test_extract_first_fenced_code_block(input, expected):
    actual = extract_first_fenced_code_block(input)
    assert actual == expected
