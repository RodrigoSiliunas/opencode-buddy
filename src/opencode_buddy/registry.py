from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Any

import yaml


@dataclass(frozen=True)
class ModelEntry:
    id: str
    litellm_model: str
    cost_label: str
    recommended_for: tuple[str, ...]


@dataclass(frozen=True)
class ProviderEntry:
    key: str
    name: str
    transport: str
    api_key_env: str | None
    api_base: str | None
    api_base_env: str | None
    litellm_prefix: str
    discovery_kind: str
    cost_label: str
    recommended_for: tuple[str, ...]
    models: tuple[ModelEntry, ...]


@dataclass(frozen=True)
class OAuthModelEntry:
    id: str
    litellm_model: str
    cost_label: str
    recommended_for: tuple[str, ...]


@dataclass(frozen=True)
class OAuthProviderEntry:
    key: str
    name: str
    detect_kind: str
    detect_match: str
    models: tuple[OAuthModelEntry, ...]


@dataclass(frozen=True)
class Registry:
    version: int
    providers: tuple[ProviderEntry, ...]
    oauth_providers: tuple[OAuthProviderEntry, ...]


class RegistryError(ValueError):
    pass


def load_registry() -> Registry:
    return _load_registry_cached()


def reload_registry() -> Registry:
    _load_registry_cached.cache_clear()
    return _load_registry_cached()


def parse_registry(data: dict[str, Any]) -> Registry:
    if not isinstance(data, dict):
        raise RegistryError("registry deve ser um objeto YAML")

    version = data.get("version", 1)
    if not isinstance(version, int):
        raise RegistryError("version deve ser inteiro")

    providers = tuple(_parse_provider(item) for item in data.get("providers") or ())
    oauth_providers = tuple(_parse_oauth_provider(item) for item in data.get("oauth_providers") or ())

    return Registry(version=version, providers=providers, oauth_providers=oauth_providers)


@lru_cache(maxsize=1)
def _load_registry_cached() -> Registry:
    raw = resources.files("opencode_buddy").joinpath("model_registry.yaml").read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    return parse_registry(data)


def _parse_provider(raw: Any) -> ProviderEntry:
    if not isinstance(raw, dict):
        raise RegistryError("provider deve ser um objeto")

    key = _required_str(raw, "key", "provider")
    name = _required_str(raw, "name", f"provider {key}")
    transport = raw.get("transport", "API")
    if transport not in {"API"}:
        raise RegistryError(f"provider {key}: transport invalido (esperado API): {transport}")

    api_key_env = _optional_str(raw, "api_key_env")
    api_base = _optional_str(raw, "api_base")
    api_base_env = _optional_str(raw, "api_base_env")
    litellm_prefix = _required_str(raw, "litellm_prefix", f"provider {key}")

    discovery = raw.get("discovery") or {}
    if not isinstance(discovery, dict):
        raise RegistryError(f"provider {key}: discovery deve ser objeto")
    discovery_kind = _required_str(discovery, "kind", f"provider {key} discovery")

    cost_label = raw.get("cost_label", "unknown")
    if not isinstance(cost_label, str):
        raise RegistryError(f"provider {key}: cost_label deve ser string")

    recommended_for = _parse_string_tuple(raw.get("recommended_for"), f"provider {key}.recommended_for")

    models_raw = raw.get("models")
    if models_raw is None:
        models_raw = []
    if not isinstance(models_raw, list):
        raise RegistryError(f"provider {key}: models deve ser lista")
    models = tuple(_parse_model(item, key, litellm_prefix, cost_label) for item in models_raw)

    return ProviderEntry(
        key=key,
        name=name,
        transport=transport,
        api_key_env=api_key_env,
        api_base=api_base,
        api_base_env=api_base_env,
        litellm_prefix=litellm_prefix,
        discovery_kind=discovery_kind,
        cost_label=cost_label,
        recommended_for=recommended_for,
        models=models,
    )


def _parse_model(raw: Any, provider_key: str, litellm_prefix: str, provider_cost: str) -> ModelEntry:
    if not isinstance(raw, dict):
        raise RegistryError(f"provider {provider_key}: modelo deve ser objeto")

    model_id = _required_str(raw, "id", f"provider {provider_key} model")
    explicit = _optional_str(raw, "litellm_model")
    litellm_model = explicit or f"{litellm_prefix}/{model_id}"
    cost_label = raw.get("cost_label", provider_cost)
    if not isinstance(cost_label, str):
        raise RegistryError(f"provider {provider_key} model {model_id}: cost_label deve ser string")
    recommended_for = _parse_string_tuple(
        raw.get("recommended_for"),
        f"provider {provider_key} model {model_id}.recommended_for",
    )
    return ModelEntry(id=model_id, litellm_model=litellm_model, cost_label=cost_label, recommended_for=recommended_for)


def _parse_oauth_provider(raw: Any) -> OAuthProviderEntry:
    if not isinstance(raw, dict):
        raise RegistryError("oauth_provider deve ser objeto")
    key = _required_str(raw, "key", "oauth_provider")
    name = _required_str(raw, "name", f"oauth_provider {key}")

    detect = raw.get("detect") or {}
    if not isinstance(detect, dict):
        raise RegistryError(f"oauth_provider {key}: detect deve ser objeto")
    detect_kind = _required_str(detect, "kind", f"oauth_provider {key} detect")
    detect_match = _required_str(detect, "match", f"oauth_provider {key} detect")

    models_raw = raw.get("models")
    if models_raw is None:
        models_raw = []
    if not isinstance(models_raw, list):
        raise RegistryError(f"oauth_provider {key}: models deve ser lista")
    models = tuple(_parse_oauth_model(item, key) for item in models_raw)

    return OAuthProviderEntry(
        key=key,
        name=name,
        detect_kind=detect_kind,
        detect_match=detect_match,
        models=models,
    )


def _parse_oauth_model(raw: Any, provider_key: str) -> OAuthModelEntry:
    if not isinstance(raw, dict):
        raise RegistryError(f"oauth_provider {provider_key}: modelo deve ser objeto")
    model_id = _required_str(raw, "id", f"oauth_provider {provider_key} model")
    litellm_model = _required_str(raw, "litellm_model", f"oauth_provider {provider_key} model {model_id}")
    cost_label = raw.get("cost_label", "unknown")
    if not isinstance(cost_label, str):
        raise RegistryError(f"oauth_provider {provider_key} model {model_id}: cost_label deve ser string")
    recommended_for = _parse_string_tuple(
        raw.get("recommended_for"),
        f"oauth_provider {provider_key} model {model_id}.recommended_for",
    )
    return OAuthModelEntry(
        id=model_id, litellm_model=litellm_model, cost_label=cost_label, recommended_for=recommended_for
    )


def _required_str(raw: dict[str, Any], field: str, owner: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or not value.strip():
        raise RegistryError(f"{owner}: campo '{field}' obrigatorio e nao vazio")
    return value


def _optional_str(raw: dict[str, Any], field: str) -> str | None:
    value = raw.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise RegistryError(f"campo '{field}' deve ser string ou ausente")
    return value


def _parse_string_tuple(value: Any, owner: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise RegistryError(f"{owner} deve ser lista de strings")
    items: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise RegistryError(f"{owner} deve conter apenas strings")
        items.append(item)
    return tuple(items)
