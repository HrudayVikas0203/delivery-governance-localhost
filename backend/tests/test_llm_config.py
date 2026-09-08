from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.config import BACKEND_ROOT, ENV_FILES, Settings
from app.services import llm


REAL_GENERATE_TEXT = llm.generate_text


def test_settings_load_groq_and_gemini_from_env_file_independent_of_cwd(tmp_path, monkeypatch) -> None:
    fake_groq_key = "test-groq-secret"
    fake_gemini_key = "test-gemini-secret"
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            (
                f"GROQ_API_KEY={fake_groq_key}",
                "GROQ_DEFAULT_MODEL=openai/gpt-oss-20b",
                f"GEMINI_API_KEY={fake_gemini_key}",
                "GEMINI_MODEL=gemini-test-model",
            )
        ),
        encoding="utf-8",
    )
    other_cwd = tmp_path / "other"
    other_cwd.mkdir()
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_DEFAULT_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.chdir(other_cwd)

    settings = Settings(_env_file=env_file)

    assert settings.groq_api_key == fake_groq_key
    assert settings.groq_default_model == "openai/gpt-oss-20b"
    assert settings.gemini_api_key == fake_gemini_key
    assert settings.gemini_default_model == "gemini-test-model"
    assert fake_groq_key not in repr(settings)
    assert fake_gemini_key not in repr(settings)


def test_application_env_files_are_absolute_and_include_backend_env() -> None:
    assert all(path.is_absolute() for path in ENV_FILES)
    assert BACKEND_ROOT / ".env" in ENV_FILES
    assert str(BACKEND_ROOT / ".env") in Settings.model_config["env_file"]


def test_missing_groq_key_is_distinct_and_does_not_expose_other_secrets(monkeypatch) -> None:
    hidden_secret = "must-not-appear"
    settings = SimpleNamespace(
        groq_api_key=None,
        groq_default_model="openai/gpt-oss-120b",
        gemini_api_key=hidden_secret,
        gemini_default_model="gemini-test-model",
    )
    monkeypatch.setattr(llm, "get_settings", lambda: settings)

    with pytest.raises(HTTPException) as caught:
        llm.require_provider("groq")

    assert caught.value.status_code == 503
    assert caught.value.detail == llm.GROQ_MISSING_KEY_MESSAGE
    assert hidden_secret not in caught.value.detail


@pytest.mark.parametrize(
    ("exception_name", "provider_status", "expected_status", "expected_detail"),
    (
        ("AuthenticationError", 401, 502, llm.GROQ_AUTH_MESSAGE),
        ("NotFoundError", 404, 503, llm.GROQ_MODEL_MESSAGE),
        ("RateLimitError", 429, 429, llm.GROQ_RATE_LIMIT_MESSAGE),
        ("APIConnectionError", None, 502, llm.GROQ_NETWORK_MESSAGE),
        ("APIError", 500, 502, llm.GROQ_API_MESSAGE),
    ),
)
def test_groq_errors_are_safe_and_distinct(exception_name, provider_status, expected_status, expected_detail) -> None:
    hidden_secret = "must-not-appear"
    error_type = type(exception_name, (Exception,), {})
    error = error_type("provider failure")
    error.status_code = provider_status
    error.body = {"error": hidden_secret}

    mapped = llm._safe_groq_error(error)

    assert mapped.status_code == expected_status
    assert mapped.detail == expected_detail
    assert hidden_secret not in mapped.detail


def test_generate_text_passes_configured_groq_model(monkeypatch) -> None:
    configured_model = "openai/gpt-oss-20b"
    settings = SimpleNamespace(
        groq_api_key="test-groq-key",
        groq_default_model=configured_model,
        gemini_api_key=None,
        gemini_default_model="gemini-test-model",
    )
    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            message = SimpleNamespace(content="Safe chatbot response")
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    class FakeGroq:
        def __init__(self, **kwargs):
            assert kwargs["api_key"] == "test-groq-key"
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(llm, "get_settings", lambda: settings)
    monkeypatch.setattr(llm, "resolve_available_groq_model", lambda model: model)
    monkeypatch.setattr("groq.Groq", FakeGroq)

    answer, selected_model = REAL_GENERATE_TEXT("groq", "Hello", configured_model)

    assert answer == "Safe chatbot response"
    assert selected_model == configured_model
    assert captured["model"] == configured_model
