"""Engine de scaffolding compartilhado por `init` e `create`.

Tanto `init` (CLI scriptavel via flags) quanto `create` (wizard interativo)
constroem um `ProjectSpec` (= `InitOptions`) e o passam para
`scaffold_project()`. Esta funcao gera todos os arquivos do projeto.

Backward compat: a funcao privada `cli._scaffold_project` continua disponivel
como wrapper sobre `scaffold_project` para nao quebrar imports existentes.
"""
from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Any

import typer
import yaml

from opencode_buddy.config_builder import (
    AgentSpec,
    InitOptions,
    build_custom_agent_prompt,
    build_env_example,
    build_gitignore,
    build_litellm_config,
    build_opencode_config,
    build_orchestrator_prompt,
    build_project_context,
    build_start_proxy_script,
    iter_agent_specs,
    oauth_providers_used,
)
from opencode_buddy.i18n import t


# Alias publico: ProjectSpec e o nome conceitual do contrato compartilhado.
# InitOptions e o nome historico do dataclass; ambos referem ao mesmo tipo.
ProjectSpec = InitOptions


class SpecFileError(ValueError):
    pass


def scaffold_project(target: Path, spec: ProjectSpec, force: bool) -> None:
    """Gera todos os arquivos do projeto OpenCode em `target`."""
    specs = iter_agent_specs(spec)
    _ensure_unique_agent_names(specs)

    target.mkdir(parents=True, exist_ok=True)

    opencode_json = json.dumps(build_opencode_config(spec), indent=2, ensure_ascii=False) + "\n"
    litellm_yaml = yaml.safe_dump(build_litellm_config(spec), sort_keys=False, allow_unicode=True)
    env_example = build_env_example(spec)
    start_proxy = build_start_proxy_script(spec)

    _write(target / "opencode.json", opencode_json, force)
    _write(target / "litellm-config.yaml", litellm_yaml, force)
    _write(target / ".env.example", env_example, force)
    _write(target / ".gitignore", build_gitignore(), force)
    _write(target / "start-proxy.ps1", start_proxy, force)
    _write(target / ".opencode" / "project.md", build_project_context(spec), force)

    agents_dir = target / ".opencode" / "agents"
    for agent in specs:
        dest = agents_dir / agent.prompt_file
        if agent.name == "build":
            _write(dest, build_orchestrator_prompt(spec), force)
        elif agent.template_file:
            _copy_template(agent.template_file, dest, force)
        else:
            _write(dest, build_custom_agent_prompt(agent), force)

    _print_next_steps(spec)


def load_spec_file(path: Path) -> dict[str, Any]:
    """Carrega um arquivo declarativo (YAML ou JSON) com campos de `InitOptions`."""
    if not path.exists():
        raise SpecFileError(f"arquivo de spec nao encontrado: {path}")
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    try:
        if suffix in {".yaml", ".yml"}:
            data = yaml.safe_load(text)
        elif suffix == ".json":
            data = json.loads(text)
        else:
            raise SpecFileError(
                f"extensao nao suportada: {suffix}. Use .yaml, .yml ou .json"
            )
    except (yaml.YAMLError, json.JSONDecodeError) as exc:
        raise SpecFileError(f"falha ao ler {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SpecFileError(f"{path}: conteudo deve ser um objeto/dict")
    return data


def merge_spec_overrides(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Mescla overrides em base. Valores nao-None em overrides ganham."""
    merged = dict(base)
    for key, value in overrides.items():
        if value is None:
            continue
        merged[key] = value
    return merged


def _write(path: Path, content: str, force: bool) -> None:
    if path.exists() and not force:
        typer.secho(f"[SKIP] {path} ja existe (use --force para sobrescrever)", fg=typer.colors.YELLOW)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    typer.secho(f"[OK]   {path}", fg=typer.colors.GREEN)


def _copy_template(name: str, dest: Path, force: bool) -> None:
    src = resources.files("opencode_buddy.templates").joinpath(name)
    content = src.read_text(encoding="utf-8")
    _write(dest, content, force)


def _ensure_unique_agent_names(specs: tuple[AgentSpec, ...]) -> None:
    seen: set[str] = set()
    for spec in specs:
        if spec.name in seen:
            raise ValueError(f"agent duplicado: {spec.name}")
        seen.add(spec.name)


def _print_next_steps(spec: ProjectSpec) -> None:
    typer.echo("")
    typer.secho(t("scaffold.next_steps.header"), fg=typer.colors.CYAN, bold=True)
    typer.echo("  " + t("scaffold.next_steps.env"))
    typer.echo("  " + t("scaffold.next_steps.validate"))
    typer.echo("  " + t("scaffold.next_steps.proxy"))
    oauth = oauth_providers_used(spec)
    step = 4
    for provider in oauth:
        typer.echo("  " + t("scaffold.next_steps.oauth", step=step, provider=provider.key))
        step += 1
    typer.echo("  " + t("scaffold.next_steps.run", step=step))
