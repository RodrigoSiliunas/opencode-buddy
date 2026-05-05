from __future__ import annotations

import socket
import urllib.error
from dataclasses import asdict, dataclass
from pathlib import Path

from opencode_buddy.model_catalog import (
    _DISCOVERERS,
    HTTPDiscoveryError,
    discover_opencode_oauth_models,
    load_env_sources,
)
from opencode_buddy.registry import OAuthProviderEntry, ProviderEntry, load_registry

# States possiveis de cada provider:
STATE_OK = "ok"
STATE_MISSING_ENV = "missing-env"
STATE_AUTH_FAILED = "auth-failed"
STATE_NETWORK_FAILED = "network-failed"
STATE_UNSUPPORTED = "unsupported-discovery"
STATE_SKIPPED = "skipped"


@dataclass(frozen=True)
class ProviderStatus:
    provider_key: str
    provider_name: str
    transport: str
    state: str
    detail: str
    discovered_models: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["discovered_models"] = list(self.discovered_models)
        return data


def known_provider_keys() -> tuple[str, ...]:
    registry = load_registry()
    keys = [provider.key for provider in registry.providers]
    keys.extend(provider.key for provider in registry.oauth_providers)
    return tuple(keys)


class UnknownProviderError(ValueError):
    def __init__(self, key: str, available: tuple[str, ...]):
        super().__init__(f"provider desconhecido: {key}")
        self.key = key
        self.available = available


def validate_providers(
    *,
    cwd: Path | None = None,
    only: str | None = None,
    timeout: float = 5.0,
) -> tuple[ProviderStatus, ...]:
    env = load_env_sources(cwd)
    registry = load_registry()

    if only is not None:
        available = known_provider_keys()
        if only not in available:
            raise UnknownProviderError(only, available)

    statuses: list[ProviderStatus] = []

    for provider in registry.providers:
        if only and provider.key != only:
            continue
        statuses.append(_validate_api_provider(provider, env, timeout))

    for oauth in registry.oauth_providers:
        if only and oauth.key != only:
            continue
        statuses.append(_validate_oauth_provider(oauth))

    return tuple(statuses)


def _validate_api_provider(
    provider: ProviderEntry, env: dict[str, str], timeout: float
) -> ProviderStatus:
    base_status = _api_base_status(provider)

    if provider.api_key_env and not env.get(provider.api_key_env):
        return _replace(base_status, state=STATE_MISSING_ENV, detail=f"falta {provider.api_key_env}")
    if provider.api_base_env and not env.get(provider.api_base_env):
        return _replace(base_status, state=STATE_MISSING_ENV, detail=f"falta {provider.api_base_env}")

    if provider.discovery_kind == "none":
        return _replace(
            base_status,
            state=STATE_UNSUPPORTED,
            detail="provider sem endpoint de listagem (kind=none)",
        )

    discoverer = _DISCOVERERS.get(provider.discovery_kind)
    if discoverer is None:
        return _replace(
            base_status,
            state=STATE_UNSUPPORTED,
            detail=f"discovery '{provider.discovery_kind}' nao suportado",
        )

    try:
        raw_ids = discoverer(provider, env, timeout=timeout)
    except HTTPDiscoveryError as exc:
        if exc.status_code in {401, 403}:
            return _replace(base_status, state=STATE_AUTH_FAILED, detail=f"chave rejeitada (HTTP {exc.status_code})")
        if exc.status_code in {404}:
            return _replace(base_status, state=STATE_UNSUPPORTED, detail=f"endpoint de listagem ausente (HTTP {exc.status_code})")
        return _replace(base_status, state=STATE_NETWORK_FAILED, detail=f"HTTP {exc.status_code}")
    except (urllib.error.URLError, OSError, socket.timeout, TimeoutError) as exc:
        return _replace(base_status, state=STATE_NETWORK_FAILED, detail=f"falha de rede ({exc.__class__.__name__})")
    except Exception as exc:
        return _replace(
            base_status,
            state=STATE_NETWORK_FAILED,
            detail=f"erro inesperado ({exc.__class__.__name__})",
        )

    return _replace(
        base_status,
        state=STATE_OK,
        detail=f"{len(raw_ids)} modelo(s) encontrados",
        discovered_models=tuple(raw_ids[:25]),
    )


def _validate_oauth_provider(provider: OAuthProviderEntry) -> ProviderStatus:
    base_status = ProviderStatus(
        provider_key=provider.key,
        provider_name=provider.name,
        transport="OAuth",
        state=STATE_SKIPPED,
        detail="",
    )
    if provider.detect_kind != "opencode-auth-list":
        return _replace(
            base_status,
            state=STATE_UNSUPPORTED,
            detail=f"detect kind '{provider.detect_kind}' nao suportado",
        )

    models, notes = discover_opencode_oauth_models()
    matched = [model for model in models if model.provider == provider.name]
    if matched:
        return _replace(
            base_status,
            state=STATE_OK,
            detail="login detectado no OpenCode",
            discovered_models=tuple(model.model_id for model in matched),
        )

    detail = "login nao detectado em `opencode auth list`"
    for note in notes:
        if provider.name in note or "opencode auth list" in note.lower():
            detail = note
            break
    return _replace(base_status, state=STATE_SKIPPED, detail=detail)


def _api_base_status(provider: ProviderEntry) -> ProviderStatus:
    return ProviderStatus(
        provider_key=provider.key,
        provider_name=provider.name,
        transport="API",
        state=STATE_SKIPPED,
        detail="",
    )


def _replace(status: ProviderStatus, **changes: object) -> ProviderStatus:
    base = {
        "provider_key": status.provider_key,
        "provider_name": status.provider_name,
        "transport": status.transport,
        "state": status.state,
        "detail": status.detail,
        "discovered_models": status.discovered_models,
    }
    base.update(changes)
    return ProviderStatus(**base)  # type: ignore[arg-type]


def has_failures(statuses: tuple[ProviderStatus, ...], *, strict: bool = False) -> bool:
    for status in statuses:
        if status.state == STATE_AUTH_FAILED:
            return True
        if strict and status.state in {STATE_MISSING_ENV, STATE_NETWORK_FAILED}:
            return True
    return False
