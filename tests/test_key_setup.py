import json
from unittest.mock import MagicMock

import pytest

from opencode_buddy.key_setup import (
    has_ok_api_provider,
    run_key_setup_interactive,
    write_env_values,
)
from opencode_buddy.keys_validator import ProviderStatus


@pytest.fixture(autouse=True)
def _clear_provider_env(monkeypatch):
    for var in [
        "OPENCODE_GO_API_KEY",
        "DEEPSEEK_API_KEY",
        "MOONSHOT_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "COMMANDCODE_API_KEY",
        "COMMANDCODE_API_BASE",
    ]:
        monkeypatch.delenv(var, raising=False)


def _http_response(payload: dict) -> MagicMock:
    response = MagicMock()
    response.read.return_value = json.dumps(payload).encode("utf-8")
    response.__enter__.return_value = response
    response.__exit__.return_value = None
    return response


def test_write_env_values_preserves_comments_and_replaces_existing(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "# local secrets\nOPENCODE_GO_API_KEY=old\nUNCHANGED=value\n",
        encoding="utf-8",
    )

    write_env_values(env_path, {"OPENCODE_GO_API_KEY": "new", "DEEPSEEK_API_KEY": "deep"})

    text = env_path.read_text(encoding="utf-8")
    assert "# local secrets" in text
    assert "OPENCODE_GO_API_KEY=new" in text
    assert "UNCHANGED=value" in text
    assert "DEEPSEEK_API_KEY=deep" in text
    assert "old" not in text


def test_run_key_setup_interactive_writes_env_and_validates_provider(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "opencode_buddy.model_catalog.urllib.request.urlopen",
        lambda req, timeout=None: _http_response({"data": [{"id": "deepseek-v4-flash"}]}),
    )
    messages: list[str] = []

    result = run_key_setup_interactive(
        tmp_path,
        provider_keys=("opencode-go",),
        output_fn=messages.append,
        secret_prompt_fn=lambda label: "secret-go-key",
    )

    assert result.env_path == tmp_path / ".env"
    assert result.updated_env_vars == ("OPENCODE_GO_API_KEY",)
    assert "OPENCODE_GO_API_KEY=secret-go-key" in result.env_path.read_text(encoding="utf-8")
    assert has_ok_api_provider(result.statuses) is True
    assert all("secret-go-key" not in message for message in messages)


def test_run_key_setup_interactive_rejects_unknown_provider(tmp_path):
    with pytest.raises(ValueError) as excinfo:
        run_key_setup_interactive(tmp_path, provider_keys=("invented",), validate=False)
    assert "invented" in str(excinfo.value)
    assert "deepseek" in str(excinfo.value)


def test_has_ok_api_provider_ignores_oauth_and_missing_states():
    statuses = (
        ProviderStatus("chatgpt", "ChatGPT OAuth", "OAuth", "ok", "login detectado"),
        ProviderStatus("deepseek", "DeepSeek", "API", "missing-env", "falta DEEPSEEK_API_KEY"),
    )
    assert has_ok_api_provider(statuses) is False

    statuses += (ProviderStatus("opencode-go", "OpenCode Go", "API", "ok", "1 modelo"),)
    assert has_ok_api_provider(statuses) is True
