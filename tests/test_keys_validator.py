import io
import json
import socket
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from opencode_buddy.keys_validator import (
    STATE_AUTH_FAILED,
    STATE_MISSING_ENV,
    STATE_NETWORK_FAILED,
    STATE_OK,
    STATE_SKIPPED,
    STATE_UNSUPPORTED,
    has_failures,
    validate_providers,
)


def _http_response(payload: dict) -> MagicMock:
    response = MagicMock()
    response.read.return_value = json.dumps(payload).encode("utf-8")
    response.__enter__.return_value = response
    response.__exit__.return_value = None
    return response


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="http://example", code=code, msg="error", hdrs=None, fp=io.BytesIO(b"")
    )


def test_validate_providers_reports_missing_env_when_no_keys(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    statuses = validate_providers(cwd=tmp_path, timeout=0.1)
    deepseek = next(status for status in statuses if status.provider_key == "deepseek")
    assert deepseek.state == STATE_MISSING_ENV
    assert "DEEPSEEK_API_KEY" in deepseek.detail


def test_validate_providers_filters_by_only(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    statuses = validate_providers(cwd=tmp_path, only="deepseek", timeout=0.1)
    keys = {status.provider_key for status in statuses}
    assert keys == {"deepseek"}


def test_validate_providers_marks_ok_on_successful_listing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-secret-do-not-leak")

    payload = {"data": [{"id": "deepseek-chat"}, {"id": "deepseek-reasoner"}]}
    with patch("opencode_buddy.model_catalog.urllib.request.urlopen", return_value=_http_response(payload)):
        statuses = validate_providers(cwd=tmp_path, only="deepseek", timeout=0.5)

    deepseek = next(status for status in statuses if status.provider_key == "deepseek")
    assert deepseek.state == STATE_OK
    assert deepseek.discovered_models == ("deepseek-chat", "deepseek-reasoner")
    assert "2 modelo" in deepseek.detail


def test_validate_providers_returns_auth_failed_on_401(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-bad")
    with patch("opencode_buddy.model_catalog.urllib.request.urlopen", side_effect=_http_error(401)):
        statuses = validate_providers(cwd=tmp_path, only="deepseek", timeout=0.5)
    deepseek = next(status for status in statuses if status.provider_key == "deepseek")
    assert deepseek.state == STATE_AUTH_FAILED
    assert "401" in deepseek.detail


def test_validate_providers_returns_network_failed_on_socket_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    with patch(
        "opencode_buddy.model_catalog.urllib.request.urlopen",
        side_effect=urllib.error.URLError(socket.timeout("timeout")),
    ):
        statuses = validate_providers(cwd=tmp_path, only="deepseek", timeout=0.5)
    deepseek = next(status for status in statuses if status.provider_key == "deepseek")
    assert deepseek.state == STATE_NETWORK_FAILED


def test_validate_providers_does_not_leak_api_key(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    secret = "sk-this-is-a-very-secret-value-9999"
    monkeypatch.setenv("DEEPSEEK_API_KEY", secret)
    with patch("opencode_buddy.model_catalog.urllib.request.urlopen", side_effect=_http_error(401)):
        statuses = validate_providers(cwd=tmp_path, only="deepseek", timeout=0.5)
    for status in statuses:
        assert secret not in status.detail
        for model in status.discovered_models:
            assert secret not in model


def test_validate_providers_oauth_ok_when_chatgpt_detected(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    completed = type("Completed", (), {"returncode": 0, "stdout": "chatgpt logged in", "stderr": ""})()
    with patch("opencode_buddy.model_catalog.subprocess.run", return_value=completed):
        statuses = validate_providers(cwd=tmp_path, only="chatgpt", timeout=0.5)
    chatgpt = next(status for status in statuses if status.provider_key == "chatgpt")
    assert chatgpt.transport == "OAuth"
    assert chatgpt.state == STATE_OK


def test_validate_providers_oauth_skipped_when_chatgpt_absent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    completed = type("Completed", (), {"returncode": 0, "stdout": "no providers", "stderr": ""})()
    with patch("opencode_buddy.model_catalog.subprocess.run", return_value=completed):
        statuses = validate_providers(cwd=tmp_path, only="chatgpt", timeout=0.5)
    chatgpt = next(status for status in statuses if status.provider_key == "chatgpt")
    assert chatgpt.state == STATE_SKIPPED


def test_provider_status_serializes_to_json_dict(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    statuses = validate_providers(cwd=tmp_path, only="deepseek", timeout=0.1)
    payload = [status.to_dict() for status in statuses]
    text = json.dumps(payload)  # ensure serializable
    parsed = json.loads(text)
    assert parsed[0]["provider_key"] == "deepseek"
    assert isinstance(parsed[0]["discovered_models"], list)


def test_has_failures_only_blocks_on_auth_by_default(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    statuses = validate_providers(cwd=tmp_path, timeout=0.1)
    # No env setup => mostly missing-env. Should NOT count as failure (non-strict).
    assert has_failures(statuses, strict=False) is False
    assert has_failures(statuses, strict=True) is True


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    """Garante que nenhuma env var de provider real vaze para os testes."""
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
