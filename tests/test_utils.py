import pytest
from llm.utils import simplify_usage_dict, extract_fenced_code_block, schema_dsl


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
    "input,last,expected",
    [
        ["This is a sample text without any code blocks.", False, None],
        [
            "Here is some text.\n\n```\ndef foo():\n    return 'bar'\n```\n\nMore text.",
            False,
            "def foo():\n    return 'bar'\n",
        ],
        [
            "Here is some text.\n\n```python\ndef foo():\n    return 'bar'\n```\n\nMore text.",
            False,
            "def foo():\n    return 'bar'\n",
        ],
        [
            "Here is some text.\n\n````\ndef foo():\n    return 'bar'\n````\n\nMore text.",
            False,
            "def foo():\n    return 'bar'\n",
        ],
        [
            "Here is some text.\n\n````javascript\nfunction foo() {\n    return 'bar';\n}\n````\n\nMore text.",
            False,
            "function foo() {\n    return 'bar';\n}\n",
        ],
        [
            "Here is some text.\n\n```python\ndef foo():\n    return 'bar'\n````\n\nMore text.",
            False,
            None,
        ],
        [
            "First code block:\n\n```python\ndef foo():\n    return 'bar'\n```\n\n"
            "Second code block:\n\n```javascript\nfunction foo() {\n    return 'bar';\n}\n```",
            False,
            "def foo():\n    return 'bar'\n",
        ],
        [
            "First code block:\n\n```python\ndef foo():\n    return 'bar'\n```\n\n"
            "Second code block:\n\n```javascript\nfunction foo() {\n    return 'bar';\n}\n```",
            True,
            "function foo() {\n    return 'bar';\n}\n",
        ],
        [
            "First code block:\n\n```python\ndef foo():\n    return 'bar'\n```\n\n"
            # This one has trailing whitespace after the second code block:
            # https://github.com/simonw/llm/pull/718#issuecomment-2613177036
            "Second code block:\n\n```javascript\nfunction foo() {\n    return 'bar';\n}\n``` ",
            True,
            "function foo() {\n    return 'bar';\n}\n",
        ],
        [
            "Here is some text.\n\n```python\ndef foo():\n    return `bar`\n```\n\nMore text.",
            False,
            "def foo():\n    return `bar`\n",
        ],
    ],
)
def test_extract_fenced_code_block(input, last, expected):
    actual = extract_fenced_code_block(input, last=last)
    assert actual == expected


@pytest.mark.parametrize(
    "schema, expected",
    [
        # Test case 1: Basic comma-separated fields, default string type
        (
            "name, bio",
            {
                "type": "object",
                "properties": {"name": {"type": "string"}, "bio": {"type": "string"}},
                "required": ["name", "bio"],
            },
        ),
        # Test case 2: Comma-separated fields with types
        (
            "name, age int, balance float, active bool",
            {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "age": {"type": "integer"},
                    "balance": {"type": "number"},
                    "active": {"type": "boolean"},
                },
                "required": ["name", "age", "balance", "active"],
            },
        ),
        # Test case 3: Comma-separated fields with descriptions
        (
            "name: full name, age int: years old",
            {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "full name"},
                    "age": {"type": "integer", "description": "years old"},
                },
                "required": ["name", "age"],
            },
        ),
        # Test case 4: Newline-separated fields
        (
            """
        name
        bio
        age int
        """,
            {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "bio": {"type": "string"},
                    "age": {"type": "integer"},
                },
                "required": ["name", "bio", "age"],
            },
        ),
        # Test case 5: Newline-separated with descriptions containing commas
        (
            """
        name: the person's name
        age int: their age in years, must be positive
        bio: a short bio, no more than three sentences
        """,
            {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "the person's name"},
                    "age": {
                        "type": "integer",
                        "description": "their age in years, must be positive",
                    },
                    "bio": {
                        "type": "string",
                        "description": "a short bio, no more than three sentences",
                    },
                },
                "required": ["name", "age", "bio"],
            },
        ),
        # Test case 6: Empty schema
        ("", {"type": "object", "properties": {}, "required": []}),
        # Test case 7: Explicit string type
        (
            "name str, description str",
            {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["name", "description"],
            },
        ),
        # Test case 8: Extra whitespace
        (
            "  name  ,  age   int  :  person's age  ",
            {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "age": {"type": "integer", "description": "person's age"},
                },
                "required": ["name", "age"],
            },
        ),
    ],
)
def test_schema_dsl(schema, expected):
    result = schema_dsl(schema)
    assert result == expected


def test_schema_dsl_multi():
    result = schema_dsl("name, age int: The age", multi=True)
    assert result == {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "age": {"type": "integer", "description": "The age"},
                    },
                    "required": ["name", "age"],
                },
            }
        },
        "required": ["items"],
    }
