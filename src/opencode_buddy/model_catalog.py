import json
import os
import subprocess
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from opencode_buddy.registry import OAuthProviderEntry, ProviderEntry, load_registry

HTTP_USER_AGENT = "opencode-buddy/0.5.0 (+https://github.com/RodrigoSiliunas/opencode-buddy)"
DEFAULT_HTTP_HEADERS = {
    "User-Agent": HTTP_USER_AGENT,
    "Accept": "application/json",
}


@dataclass(frozen=True)
class AvailableModel:
    key: str
    provider: str
    model_id: str
    litellm_model: str
    display_name: str
    api_key_env: str | None
    transport: str
    source: str
    cost: str = "unknown"
    api_base: str | None = None
    api_base_env: str | None = None
    recommended_for: tuple[str, ...] = ()
    available: bool = True

    def is_recommended_for(self, role: str) -> bool:
        return role in self.recommended_for


@dataclass(frozen=True)
class CatalogResult:
    models: tuple[AvailableModel, ...]
    detected_env: tuple[str, ...]
    discovery_notes: tuple[str, ...]


def known_env_vars() -> frozenset[str]:
    registry = load_registry()
    names: set[str] = set()
    for provider in registry.providers:
        if provider.api_key_env:
            names.add(provider.api_key_env)
        if provider.api_base_env:
            names.add(provider.api_base_env)
    return frozenset(names)


def load_env_sources(cwd: Path | None = None) -> dict[str, str]:
    values = dict(os.environ)
    env_file = (cwd or Path.cwd()) / ".env"
    if env_file.exists():
        values.update(_read_env_file(env_file))
    return values


def build_model_catalog(env: dict[str, str] | None = None, *, live: bool = False) -> CatalogResult:
    env = load_env_sources() if env is None else env
    registry = load_registry()
    known = known_env_vars()
    detected = tuple(sorted(name for name in known if env.get(name)))
    notes: list[str] = []
    models: list[AvailableModel] = []

    for provider in registry.providers:
        provider_models: list[AvailableModel] = []
        if live and _provider_available(provider, env):
            provider_models, provider_notes = _discover_provider(provider, env)
            notes.extend(provider_notes)
        if not provider_models:
            provider_models = [_suggested_model(provider, model, env) for model in provider.models]
        models.extend(provider_models)

    oauth_models, oauth_notes = discover_opencode_oauth_models()
    notes.extend(oauth_notes)
    models.extend(oauth_models)

    return CatalogResult(models=tuple(_dedupe_models(models)), detected_env=detected, discovery_notes=tuple(notes))


def discover_opencode_oauth_models() -> tuple[tuple[AvailableModel, ...], tuple[str, ...]]:
    registry = load_registry()
    if not registry.oauth_providers:
        return (), ()

    output, error_note = _run_opencode_auth_list()
    if error_note is not None:
        return (), (error_note,)

    notes: list[str] = []
    models: list[AvailableModel] = []
    for provider in registry.oauth_providers:
        provider_models, provider_note = _detect_oauth_provider(provider, output)
        if provider_note:
            notes.append(provider_note)
        models.extend(provider_models)
    return tuple(models), tuple(notes)


def choices_for_role(models: tuple[AvailableModel, ...], role: str) -> tuple[AvailableModel, ...]:
    return tuple(
        sorted(
            models,
            key=lambda model: (
                not model.available,
                not model.is_recommended_for(role),
                model.provider.lower(),
                model.model_id.lower(),
            ),
        )
    )


# ---- Internals ----------------------------------------------------------


def _run_opencode_auth_list() -> tuple[str, str | None]:
    try:
        result = subprocess.run(
            ["opencode", "auth", "list"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "", "OpenCode OAuth: nao foi possivel executar `opencode auth list`."

    if result.returncode != 0:
        return "", "OpenCode OAuth: `opencode auth list` retornou erro."
    return f"{result.stdout}\n{result.stderr}".lower(), None


def _detect_oauth_provider(
    provider: OAuthProviderEntry, output_lower: str
) -> tuple[list[AvailableModel], str | None]:
    if provider.detect_kind != "opencode-auth-list":
        return [], f"OpenCode OAuth: kind '{provider.detect_kind}' nao suportado."
    if provider.detect_match.lower() not in output_lower:
        return [], f"OpenCode OAuth: {provider.name} nao detectado em `opencode auth list`."

    models = [
        AvailableModel(
            key=f"oauth-{provider.key}-{model.id}",
            provider=provider.name,
            model_id=model.id,
            litellm_model=model.litellm_model,
            display_name=f"{provider.name} - {model.id}",
            api_key_env=None,
            transport="OAuth",
            source="opencode auth",
            cost=model.cost_label,
            recommended_for=model.recommended_for,
        )
        for model in provider.models
    ]
    return models, f"OpenCode OAuth: {provider.name} detectado."


def _provider_available(provider: ProviderEntry, env: dict[str, str]) -> bool:
    if provider.api_key_env and not env.get(provider.api_key_env):
        return False
    if provider.api_base_env and not env.get(provider.api_base_env):
        return False
    return True


def _discover_provider(provider: ProviderEntry, env: dict[str, str]) -> tuple[list[AvailableModel], list[str]]:
    discoverer = _DISCOVERERS.get(provider.discovery_kind)
    if discoverer is None:
        return [], [f"{provider.name}: discovery '{provider.discovery_kind}' nao suportado. Usando sugestoes locais."]
    try:
        raw_ids = discoverer(provider, env)
    except Exception as exc:
        return [], [f"{provider.name}: descoberta falhou ({exc.__class__.__name__}). Usando sugestoes locais."]

    models = [
        AvailableModel(
            key=f"{provider.key}:{model_id}",
            provider=provider.name,
            model_id=model_id,
            litellm_model=f"{provider.litellm_prefix}/{model_id}",
            display_name=f"{provider.name} - {model_id}",
            api_key_env=provider.api_key_env,
            api_base=provider.api_base,
            api_base_env=provider.api_base_env,
            transport="API",
            source="live",
            cost=provider.cost_label,
            recommended_for=provider.recommended_for,
            available=True,
        )
        for model_id in raw_ids[:25]
    ]
    return models, [f"{provider.name}: {len(models)} modelo(s) consultados via API."]


def _suggested_model(provider: ProviderEntry, model: Any, env: dict[str, str]) -> AvailableModel:
    available = _provider_available(provider, env)
    return AvailableModel(
        key=f"{provider.key}:{model.id}",
        provider=provider.name,
        model_id=model.id,
        litellm_model=model.litellm_model,
        display_name=f"{provider.name} - {model.id}",
        api_key_env=provider.api_key_env,
        api_base=provider.api_base,
        api_base_env=provider.api_base_env,
        transport="API",
        source="suggested",
        cost=model.cost_label or provider.cost_label,
        recommended_for=model.recommended_for or provider.recommended_for,
        available=available,
    )


def _dedupe_models(models: list[AvailableModel]) -> list[AvailableModel]:
    seen: set[tuple[str, str]] = set()
    deduped: list[AvailableModel] = []
    for model in models:
        identity = (model.transport, model.litellm_model)
        if identity in seen:
            continue
        seen.add(identity)
        deduped.append(model)
    return deduped


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


class HTTPDiscoveryError(RuntimeError):
    def __init__(self, status_code: int):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


def _request_json(url: str, *, headers: dict[str, str] | None = None, timeout: float = 5.0) -> dict[str, Any]:
    merged_headers = dict(DEFAULT_HTTP_HEADERS)
    merged_headers.update(headers or {})
    request = urllib.request.Request(url, headers=merged_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise HTTPDiscoveryError(exc.code) from exc


def _discover_openai_compatible(provider: ProviderEntry, env: dict[str, str], *, timeout: float = 5.0) -> list[str]:
    if provider.api_base:
        api_base = provider.api_base
    elif provider.api_base_env:
        api_base = env[provider.api_base_env]
    else:
        raise RuntimeError("openai-compatible discovery exige api_base ou api_base_env")
    if not provider.api_key_env:
        raise RuntimeError("openai-compatible discovery exige api_key_env")
    url = f"{api_base.rstrip('/')}/models"
    data = _request_json(url, headers={"Authorization": f"Bearer {env[provider.api_key_env]}"}, timeout=timeout)
    return _ids_from_openai_compatible(data)


def _discover_deepseek(provider: ProviderEntry, env: dict[str, str], *, timeout: float = 5.0) -> list[str]:
    if not provider.api_key_env:
        raise RuntimeError("deepseek discovery exige api_key_env")
    data = _request_json(
        "https://api.deepseek.com/models",
        headers={"Authorization": f"Bearer {env[provider.api_key_env]}"},
        timeout=timeout,
    )
    return _ids_from_openai_compatible(data)


def _discover_anthropic(provider: ProviderEntry, env: dict[str, str], *, timeout: float = 5.0) -> list[str]:
    if not provider.api_key_env:
        raise RuntimeError("anthropic discovery exige api_key_env")
    data = _request_json(
        "https://api.anthropic.com/v1/models",
        headers={
            "x-api-key": env[provider.api_key_env],
            "anthropic-version": "2023-06-01",
        },
        timeout=timeout,
    )
    return _ids_from_openai_compatible(data)


def _discover_gemini(provider: ProviderEntry, env: dict[str, str], *, timeout: float = 5.0) -> list[str]:
    if not provider.api_key_env:
        raise RuntimeError("gemini discovery exige api_key_env")
    data = _request_json(
        f"https://generativelanguage.googleapis.com/v1beta/models?key={env[provider.api_key_env]}",
        timeout=timeout,
    )
    ids = []
    for item in data.get("models", []):
        name = item.get("name", "")
        if name.startswith("models/"):
            ids.append(name.split("/", 1)[1])
    return ids


def _ids_from_openai_compatible(data: dict[str, Any]) -> list[str]:
    return [item["id"] for item in data.get("data", []) if isinstance(item, dict) and isinstance(item.get("id"), str)]


def _discover_none(_provider: ProviderEntry, _env: dict[str, str], *, timeout: float = 5.0) -> list[str]:
    return []


_DISCOVERERS: dict[str, Callable[..., list[str]]] = {
    "openai-compatible": _discover_openai_compatible,
    "deepseek": _discover_deepseek,
    "anthropic": _discover_anthropic,
    "gemini": _discover_gemini,
    "none": _discover_none,
}


# Compat: nome publico antigo. Use known_env_vars() para chamadas novas.
KNOWN_ENV_VARS = known_env_vars()
