import pytest


@pytest.fixture
def log_path(tmpdir):
    return tmpdir / "logs.db"


@pytest.fixture
def keys_path(tmpdir):
    return tmpdir / "keys.json"


@pytest.fixture(autouse=True)
def env_setup(monkeypatch, log_path, keys_path):
    monkeypatch.setenv("LLM_KEYS_PATH", str(keys_path))
    monkeypatch.setenv("LLM_LOG_PATH", str(log_path))


@pytest.fixture
def mocked_openai(requests_mock):
    return requests_mock.post(
        "https://api.openai.com/v1/chat/completions",
        json={
            "model": "gpt-3.5-turbo",
            "usage": {},
            "choices": [{"message": {"content": "Bob, Alice, Eve"}}],
        },
        headers={"Content-Type": "application/json"},
    )
