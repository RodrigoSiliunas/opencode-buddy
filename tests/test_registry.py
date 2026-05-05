import pytest

from opencode_buddy.registry import RegistryError, load_registry, parse_registry


def test_load_registry_returns_known_providers():
    registry = load_registry()
    keys = {provider.key for provider in registry.providers}
    assert {"opencode-go", "deepseek", "moonshot", "anthropic", "gemini", "commandcode"} <= keys


def test_load_registry_models_have_litellm_model_derived():
    registry = load_registry()
    deepseek = next(provider for provider in registry.providers if provider.key == "deepseek")
    chat = next(model for model in deepseek.models if model.id == "deepseek-chat")
    assert chat.litellm_model == "deepseek/deepseek-chat"


def test_load_registry_includes_oauth_chatgpt():
    registry = load_registry()
    assert any(provider.key == "chatgpt" for provider in registry.oauth_providers)
    chatgpt = next(provider for provider in registry.oauth_providers if provider.key == "chatgpt")
    assert chatgpt.detect_kind == "opencode-auth-list"
    assert chatgpt.detect_match == "chatgpt"
    assert any(model.litellm_model == "chatgpt/gpt-5.5" for model in chatgpt.models)


def test_parse_registry_uses_explicit_litellm_model_when_provided():
    data = {
        "version": 1,
        "providers": [
            {
                "key": "fake",
                "name": "Fake",
                "transport": "API",
                "api_key_env": "FAKE_API_KEY",
                "litellm_prefix": "openai",
                "discovery": {"kind": "openai-compatible"},
                "cost_label": "low",
                "recommended_for": ["build"],
                "models": [
                    {"id": "fake-1", "litellm_model": "custom/fake-1", "recommended_for": ["build"]},
                ],
            }
        ],
    }
    registry = parse_registry(data)
    assert registry.providers[0].models[0].litellm_model == "custom/fake-1"


def test_parse_registry_rejects_provider_without_key():
    data = {"version": 1, "providers": [{"name": "X", "litellm_prefix": "openai", "discovery": {"kind": "openai-compatible"}}]}
    with pytest.raises(RegistryError):
        parse_registry(data)


def test_parse_registry_rejects_invalid_recommended_for():
    data = {
        "version": 1,
        "providers": [
            {
                "key": "fake",
                "name": "Fake",
                "transport": "API",
                "litellm_prefix": "openai",
                "discovery": {"kind": "openai-compatible"},
                "recommended_for": [1, 2, 3],
                "models": [],
            }
        ],
    }
    with pytest.raises(RegistryError):
        parse_registry(data)


def test_parse_registry_accepts_provider_without_models():
    data = {
        "version": 1,
        "providers": [
            {
                "key": "empty",
                "name": "Empty",
                "transport": "API",
                "litellm_prefix": "openai",
                "discovery": {"kind": "none"},
            }
        ],
    }
    registry = parse_registry(data)
    assert registry.providers[0].models == ()


def test_parse_registry_oauth_requires_detect_kind():
    data = {
        "version": 1,
        "oauth_providers": [
            {
                "key": "x",
                "name": "X",
                "detect": {"match": "x"},
                "models": [],
            }
        ],
    }
    with pytest.raises(RegistryError):
        parse_registry(data)
