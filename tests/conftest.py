import pytest


def pytest_configure(config):
    import sys

    sys._called_from_test = True


@pytest.fixture
def user_path(tmpdir):
    dir = tmpdir / "llm.datasette.io"
    dir.mkdir()
    return dir


@pytest.fixture
def templates_path(user_path):
    dir = user_path / "templates"
    dir.mkdir()
    return dir


@pytest.fixture(autouse=True)
def env_setup(monkeypatch, user_path):
    monkeypatch.setenv("LLM_USER_PATH", str(user_path))


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
