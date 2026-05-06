from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import typer

from opencode_buddy.keys_validator import ProviderStatus, validate_providers
from opencode_buddy.model_catalog import load_env_sources
from opencode_buddy.registry import ProviderEntry, load_registry

YES_WORDS = {"s", "sim", "y", "yes"}
NO_WORDS = {"n", "nao", "não", "no"}
DEFAULT_SETUP_PROVIDER_KEYS = ("opencode-go", "deepseek")


@dataclass(frozen=True)
class KeySetupResult:
    env_path: Path
    updated_env_vars: tuple[str, ...]
    statuses: tuple[ProviderStatus, ...]


def has_ok_api_provider(statuses: tuple[ProviderStatus, ...]) -> bool:
    return any(status.transport == "API" and status.state == "ok" for status in statuses)


def provider_keys_with_credentials(env: dict[str, str]) -> tuple[str, ...]:
    registry = load_registry()
    keys: list[str] = []
    for provider in registry.providers:
        if provider.api_key_env and env.get(provider.api_key_env):
            keys.append(provider.key)
    return tuple(keys)


def validate_selected_providers(
    cwd: Path,
    *,
    provider_keys: tuple[str, ...] = (),
    timeout: float = 5.0,
) -> tuple[ProviderStatus, ...]:
    if not provider_keys:
        return validate_providers(cwd=cwd, timeout=timeout)

    statuses: list[ProviderStatus] = []
    for key in provider_keys:
        statuses.extend(validate_providers(cwd=cwd, only=key, timeout=timeout))
    return tuple(statuses)


def run_key_setup_interactive(
    cwd: Path,
    *,
    provider_keys: tuple[str, ...] = (),
    overwrite: bool = False,
    validate: bool = True,
    timeout: float = 5.0,
    output_fn: Callable[[str], None] = typer.echo,
    confirm_fn: Callable[[str, bool], bool] | None = None,
    secret_prompt_fn: Callable[[str], str] | None = None,
    text_prompt_fn: Callable[[str, str], str] | None = None,
) -> KeySetupResult:
    cwd = cwd.resolve()
    cwd.mkdir(parents=True, exist_ok=True)
    env_path = cwd / ".env"

    registry = load_registry()
    providers = _select_providers(registry.providers, provider_keys)
    env = load_env_sources(cwd)
    confirm = confirm_fn or _confirm
    secret_prompt = secret_prompt_fn or _prompt_secret
    text_prompt = text_prompt_fn or _prompt_text

    updates: dict[str, str] = {}
    explicit = bool(provider_keys)

    output_fn(f"Configurando chaves em {env_path}")
    for provider in providers:
        if not provider.api_key_env:
            continue

        if env.get(provider.api_key_env) and not overwrite:
            if not confirm(f"{provider.api_key_env} ja existe. Substituir?", False):
                continue
        elif not explicit and provider.key not in DEFAULT_SETUP_PROVIDER_KEYS:
            if not confirm(f"Configurar {provider.name} ({provider.api_key_env}) agora?", False):
                continue
        elif not explicit:
            if not confirm(f"Configurar {provider.name} ({provider.api_key_env}) agora?", True):
                continue

        value = secret_prompt(f"{provider.name} - {provider.api_key_env}")
        if value:
            updates[provider.api_key_env] = value

        if provider.api_base_env and (value or env.get(provider.api_base_env)):
            current = env.get(provider.api_base_env, "")
            base_value = text_prompt(f"{provider.name} - {provider.api_base_env}", current)
            if base_value:
                updates[provider.api_base_env] = base_value

    if updates:
        write_env_values(env_path, updates)
        output_fn("Chaves salvas em .env.")
    else:
        output_fn("Nenhuma chave nova foi salva.")

    statuses: tuple[ProviderStatus, ...] = ()
    if validate:
        selected = provider_keys or tuple(provider.key for provider in providers)
        statuses = validate_selected_providers(cwd, provider_keys=selected, timeout=timeout)

    return KeySetupResult(
        env_path=env_path,
        updated_env_vars=tuple(updates),
        statuses=statuses,
    )


def write_env_values(path: Path, updates: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen: set[str] = set()
    lines: list[str] = []

    for line in existing:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            lines.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in updates:
            lines.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            lines.append(line)

    if updates:
        if lines and lines[-1].strip():
            lines.append("")
        for key, value in updates.items():
            if key not in seen:
                lines.append(f"{key}={value}")

    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _select_providers(
    providers: tuple[ProviderEntry, ...],
    provider_keys: tuple[str, ...],
) -> tuple[ProviderEntry, ...]:
    if not provider_keys:
        return providers

    by_key = {provider.key: provider for provider in providers}
    unknown = [key for key in provider_keys if key not in by_key]
    if unknown:
        available = ", ".join(sorted(by_key))
        raise ValueError(f"provider desconhecido: {', '.join(unknown)}. Disponiveis: {available}")
    return tuple(by_key[key] for key in provider_keys)


def _confirm(label: str, default: bool) -> bool:
    suffix = "[S/n]" if default else "[s/N]"
    while True:
        raw = typer.prompt(f"{label} {suffix}", default="", show_default=False).strip().lower()
        if not raw:
            return default
        if raw in YES_WORDS:
            return True
        if raw in NO_WORDS:
            return False
        typer.secho("Responda com s ou n.", fg=typer.colors.RED)


def _prompt_secret(label: str) -> str:
    return typer.prompt(label, default="", show_default=False, hide_input=True).strip()


def _prompt_text(label: str, default: str = "") -> str:
    return typer.prompt(label, default=default, show_default=bool(default)).strip()
