from unittest.mock import patch

from opencode_buddy.model_catalog import build_model_catalog, choices_for_role
from opencode_buddy.registry import ModelEntry, ProviderEntry, Registry


def test_catalog_marks_models_available_from_env():
    catalog = build_model_catalog({"DEEPSEEK_API_KEY": "sk-test"}, live=False)
    deepseek = [model for model in catalog.models if model.provider == "DeepSeek"]
    assert deepseek
    assert all(model.available for model in deepseek)
    assert "DEEPSEEK_API_KEY" in catalog.detected_env


def test_catalog_keeps_missing_key_models_selectable():
    catalog = build_model_catalog({}, live=False)
    deepseek_chat = next(model for model in catalog.models if model.litellm_model == "deepseek/deepseek-chat")
    assert deepseek_chat.available is False
    assert deepseek_chat.api_key_env == "DEEPSEEK_API_KEY"


def test_choices_for_role_prioritizes_available_recommended_models():
    catalog = build_model_catalog({"GEMINI_API_KEY": "gemini-test"}, live=False)
    choices = choices_for_role(catalog.models, "audio")
    assert choices[0].available is True
    assert choices[0].is_recommended_for("audio")


def test_catalog_adds_oauth_models_when_opencode_auth_detects_chatgpt():
    completed = type("Completed", (), {"returncode": 0, "stdout": "chatgpt logged in", "stderr": ""})()
    with patch("opencode_buddy.model_catalog.subprocess.run", return_value=completed):
        catalog = build_model_catalog({}, live=False)
    assert any(model.transport == "OAuth" and model.provider == "ChatGPT OAuth" for model in catalog.models)


def test_catalog_picks_up_fake_provider_injected_via_registry(monkeypatch):
    fake_provider = ProviderEntry(
        key="fakeco",
        name="FakeCo",
        transport="API",
        api_key_env="FAKECO_API_KEY",
        api_base="https://fake.example.com/v1",
        api_base_env=None,
        litellm_prefix="openai",
        discovery_kind="openai-compatible",
        cost_label="zero",
        recommended_for=("backend",),
        models=(
            ModelEntry(
                id="fake-1",
                litellm_model="openai/fake-1",
                cost_label="zero",
                recommended_for=("backend",),
            ),
        ),
    )
    fake_registry = Registry(version=1, providers=(fake_provider,), oauth_providers=())
    monkeypatch.setattr("opencode_buddy.model_catalog.load_registry", lambda: fake_registry)
    catalog = build_model_catalog({"FAKECO_API_KEY": "x"}, live=False)
    assert any(model.provider == "FakeCo" and model.model_id == "fake-1" for model in catalog.models)
