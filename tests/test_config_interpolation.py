import pytest

from llm.utils import interpolate_env_vars, _interpolate_env_vars_in_string


class TestInterpolateEnvVarsInString:
    def test_resolves_set_env_var(self, monkeypatch):
        monkeypatch.setenv("MY_VAR", "hello")
        assert _interpolate_env_vars_in_string("${MY_VAR}") == "hello"

    def test_leaves_undefined_env_var_unchanged(self, monkeypatch, capsys):
        monkeypatch.delenv("UNDEFINED_VAR", raising=False)
        result = _interpolate_env_vars_in_string("${UNDEFINED_VAR}")
        assert result == "${UNDEFINED_VAR}"
        captured = capsys.readouterr()
        assert "Warning: environment variable 'UNDEFINED_VAR' is not set" in captured.err

    def test_multiple_vars_in_string(self, monkeypatch):
        monkeypatch.setenv("A", "alpha")
        monkeypatch.setenv("B", "beta")
        result = _interpolate_env_vars_in_string("${A}-${B}")
        assert result == "alpha-beta"

    def test_leaves_plain_text_unchanged(self):
        assert _interpolate_env_vars_in_string("$HOME") == "$HOME"

    def test_leaves_double_dollar_unchanged(self):
        assert _interpolate_env_vars_in_string("$$HOME") == "$$HOME"

    def test_mixed_text_and_var(self, monkeypatch):
        monkeypatch.setenv("NAME", "world")
        result = _interpolate_env_vars_in_string("Hello, ${NAME}!")
        assert result == "Hello, world!"


class TestInterpolateEnvVars:
    def test_dict_resolution(self, monkeypatch):
        monkeypatch.setenv("KEY1", "value1")
        monkeypatch.setenv("KEY2", "value2")
        data = {"a": "${KEY1}", "b": "${KEY2}", "c": 42}
        result = interpolate_env_vars(data)
        assert result == {"a": "value1", "b": "value2", "c": 42}

    def test_list_resolution(self, monkeypatch):
        monkeypatch.setenv("ITEM", "x")
        data = ["${ITEM}", "plain", 99]
        result = interpolate_env_vars(data)
        assert result == ["x", "plain", 99]

    def test_nested_dict_recursive(self, monkeypatch):
        monkeypatch.setenv("NESTED", "deep")
        data = {"outer": {"inner": "${NESTED}"}}
        result = interpolate_env_vars(data)
        assert result == {"outer": {"inner": "deep"}}

    def test_non_string_values_passthrough(self):
        data = {"num": 123, "flag": True, "none": None}
        result = interpolate_env_vars(data)
        assert result == {"num": 123, "flag": True, "none": None}

    def test_undefined_var_in_nested_dict_warns(self, monkeypatch, capsys):
        monkeypatch.delenv("MISSING", raising=False)
        data = {"a": {"b": "${MISSING}"}}
        result = interpolate_env_vars(data)
        assert result == {"a": {"b": "${MISSING}"}}
        captured = capsys.readouterr()
        assert "Warning: environment variable 'MISSING' is not set" in captured.err

    def test_no_false_positive_on_dollar_prefix(self):
        data = {"price": "$10"}
        result = interpolate_env_vars(data)
        assert result == {"price": "$10"}

    def test_complex_nesting(self, monkeypatch):
        monkeypatch.setenv("URL", "https://api.example.com")
        monkeypatch.setenv("TOKEN", "secret")
        data = {
            "endpoint": "${URL}",
            "headers": {
                "Authorization": "Bearer ${TOKEN}",
                "Content-Type": "application/json",
            },
            "options": ["${URL}", 8080, True],
        }
        result = interpolate_env_vars(data)
        assert result == {
            "endpoint": "https://api.example.com",
            "headers": {
                "Authorization": "Bearer secret",
                "Content-Type": "application/json",
            },
            "options": ["https://api.example.com", 8080, True],
        }
