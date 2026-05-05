import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from opencode_buddy.i18n import t


@dataclass(frozen=True)
class ValidationMessage:
    level: str
    subject: str
    detail: str


def validate_project(path: Path) -> list[ValidationMessage]:
    target = path.resolve()
    messages: list[ValidationMessage] = []

    if not target.exists():
        return [_message("error", str(target), "diretorio nao encontrado")]
    if not target.is_dir():
        return [_message("error", str(target), "nao e um diretorio")]

    opencode_path = target / "opencode.json"
    litellm_path = target / "litellm-config.yaml"

    _check_required_files(target, messages)
    opencode = _load_json(opencode_path, messages) if opencode_path.exists() else None
    litellm = _load_yaml(litellm_path, messages) if litellm_path.exists() else None

    if isinstance(opencode, dict):
        _validate_opencode(target, opencode, messages)
    if isinstance(litellm, dict):
        _validate_litellm(litellm, messages)
    if isinstance(opencode, dict) and isinstance(litellm, dict):
        _validate_agent_model_aliases(opencode, litellm, messages)
    if isinstance(litellm, dict):
        _validate_env(target, litellm, messages)
    _validate_gitignore(target, messages)

    return messages


def format_validation_report(messages: list[ValidationMessage]) -> str:
    label_keys = {
        "ok": "tag.ok",
        "warn": "tag.warn",
        "error": "tag.error",
    }
    lines = [f"{t(label_keys.get(msg.level, 'tag.info')).strip()} {msg.subject}: {msg.detail}" for msg in messages]
    errors = sum(msg.level == "error" for msg in messages)
    warnings = sum(msg.level == "warn" for msg in messages)

    lines.append("")
    if errors:
        lines.append(t("validator.summary.error", errors=errors, warnings=warnings))
    elif warnings:
        lines.append(t("validator.summary.warn", count=warnings))
    else:
        lines.append(t("validator.summary.ok"))
    return "\n".join(lines)


def _message(level: str, subject: str, detail: str) -> ValidationMessage:
    return ValidationMessage(level=level, subject=subject, detail=detail)


def _check_required_files(target: Path, messages: list[ValidationMessage]) -> None:
    required = [
        "opencode.json",
        "litellm-config.yaml",
        ".env.example",
        "start-proxy.ps1",
    ]
    for name in required:
        path = target / name
        if path.exists():
            messages.append(_message("ok", name, "encontrado"))
        else:
            messages.append(_message("error", name, "arquivo obrigatorio ausente"))

    agents_dir = target / ".opencode" / "agents"
    if agents_dir.is_dir():
        messages.append(_message("ok", ".opencode/agents", "diretorio encontrado"))
    else:
        messages.append(_message("error", ".opencode/agents", "diretorio de prompts ausente"))


def _load_json(path: Path, messages: list[ValidationMessage]) -> Any:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        messages.append(_message("error", path.name, f"JSON invalido: {exc.msg}"))
        return None
    messages.append(_message("ok", path.name, "JSON valido"))
    return data


def _load_yaml(path: Path, messages: list[ValidationMessage]) -> Any:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        messages.append(_message("error", path.name, f"YAML invalido: {exc}"))
        return None
    messages.append(_message("ok", path.name, "YAML valido"))
    return data


def _validate_opencode(target: Path, config: dict[str, Any], messages: list[ValidationMessage]) -> None:
    agents = config.get("agent")
    if not isinstance(agents, dict) or not agents:
        messages.append(_message("error", "opencode.json", "campo 'agent' ausente ou vazio"))
        return

    checked_prompts = 0
    for agent_name, agent_config in agents.items():
        if not isinstance(agent_config, dict):
            messages.append(_message("error", f"agent {agent_name}", "configuracao precisa ser um objeto"))
            continue

        model = agent_config.get("model")
        if not isinstance(model, str) or not model:
            messages.append(_message("error", f"agent {agent_name}", "modelo ausente"))

        prompt_ref = agent_config.get("prompt")
        prompt_path = _prompt_ref_to_path(target, prompt_ref)
        if prompt_path is None:
            messages.append(_message("warn", f"agent {agent_name}", "prompt nao usa referencia {file:...}; nao foi checado"))
            continue
        if not _is_inside(target, prompt_path):
            messages.append(
                _message(
                    "error",
                    f"agent {agent_name}",
                    f"prompt aponta para fora do projeto: {_display_path(target, prompt_path)}",
                )
            )
            continue
        if prompt_path.exists():
            checked_prompts += 1
        else:
            messages.append(
                _message(
                    "error",
                    f"agent {agent_name}",
                    f"prompt referenciado nao encontrado: {_display_path(target, prompt_path)}",
                )
            )

    if checked_prompts:
        messages.append(_message("ok", "agent prompts", f"{checked_prompts} prompt(s) encontrados"))


def _validate_litellm(config: dict[str, Any], messages: list[ValidationMessage]) -> None:
    model_list = config.get("model_list")
    if not isinstance(model_list, list) or not model_list:
        messages.append(_message("error", "litellm-config.yaml", "campo 'model_list' ausente ou vazio"))
        return

    aliases = _litellm_aliases(config)
    duplicate_aliases = sorted({alias for alias in aliases if aliases.count(alias) > 1})
    if duplicate_aliases:
        messages.append(_message("error", "litellm model_list", f"aliases duplicados: {', '.join(duplicate_aliases)}"))
    else:
        messages.append(_message("ok", "litellm model_list", f"{len(aliases)} alias(es) configurados"))

    if "general_settings" not in config:
        messages.append(_message("warn", "litellm-config.yaml", "general_settings ausente; master_key pode nao ser exigida"))


def _validate_agent_model_aliases(
    opencode: dict[str, Any], litellm: dict[str, Any], messages: list[ValidationMessage]
) -> None:
    litellm_aliases = set(_litellm_aliases(litellm))
    used_aliases = sorted(_opencode_litellm_aliases(opencode))
    missing = [alias for alias in used_aliases if alias not in litellm_aliases]
    if missing:
        messages.append(_message("error", "agent models", f"aliases LiteLLM sem model_list: {', '.join(missing)}"))
    else:
        messages.append(_message("ok", "agent models", f"{len(used_aliases)} alias(es) LiteLLM resolvidos"))


def _validate_env(target: Path, litellm: dict[str, Any], messages: list[ValidationMessage]) -> None:
    expected = _required_env_vars(litellm)
    if not expected:
        messages.append(_message("warn", ".env", "nenhuma variavel os.environ/... encontrada no LiteLLM"))
        return

    env_path = target / ".env"
    example_path = target / ".env.example"
    using_example = not env_path.exists()
    source = example_path if using_example else env_path

    if using_example:
        messages.append(
            _message(
                "warn",
                ".env",
                "arquivo .env nao encontrado; validando apenas .env.example "
                "(em --strict este aviso vira erro)",
            )
        )

    if not source.exists():
        messages.append(_message("error", source.name, "arquivo de variaveis ausente"))
        return

    values = _read_env(source)
    missing = sorted(var for var in expected if var not in values)
    if missing:
        messages.append(_message("error", source.name, f"variaveis ausentes: {', '.join(missing)}"))

    if using_example:
        declared = len(expected) - len(missing)
        if declared:
            messages.append(_message("ok", source.name, f"{declared} variavel(is) esperadas declaradas"))
        return

    placeholders = sorted(var for var in expected if _is_placeholder(values.get(var, "")))
    if placeholders:
        messages.append(_message("warn", source.name, f"preencha valores reais para: {', '.join(placeholders)}"))
    elif not missing:
        messages.append(_message("ok", source.name, f"{len(expected)} variavel(is) esperadas preenchidas"))


def _prompt_ref_to_path(target: Path, value: Any) -> Path | None:
    if not isinstance(value, str):
        return None
    if not value.startswith("{file:") or not value.endswith("}"):
        return None
    rel = value[len("{file:") : -1]
    return target / rel


def _is_inside(base: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(base.resolve())
    except ValueError:
        return False
    return True


def _display_path(base: Path, path: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def _litellm_aliases(config: dict[str, Any]) -> list[str]:
    aliases = []
    model_list = config.get("model_list", [])
    if not isinstance(model_list, list):
        return aliases
    for entry in model_list:
        if isinstance(entry, dict) and isinstance(entry.get("model_name"), str):
            aliases.append(entry["model_name"])
    return aliases


def _opencode_litellm_aliases(config: dict[str, Any]) -> set[str]:
    aliases: set[str] = set()
    agents = config.get("agent", {})
    if isinstance(agents, dict):
        for agent_config in agents.values():
            if isinstance(agent_config, dict):
                _add_litellm_alias(agent_config.get("model"), aliases)
    _add_litellm_alias(config.get("model"), aliases)
    return aliases


def _add_litellm_alias(model: Any, aliases: set[str]) -> None:
    if isinstance(model, str) and model.startswith("litellm/"):
        aliases.add(model.split("/", 1)[1])


def _required_env_vars(config: dict[str, Any]) -> set[str]:
    values = _walk_values(config)
    prefix = "os.environ/"
    return {value.removeprefix(prefix) for value in values if isinstance(value, str) and value.startswith(prefix)}


def _walk_values(value: Any) -> list[Any]:
    if isinstance(value, dict):
        items: list[Any] = []
        for child in value.values():
            items.extend(_walk_values(child))
        return items
    if isinstance(value, list):
        items = []
        for child in value:
            items.extend(_walk_values(child))
        return items
    return [value]


def _read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def _is_placeholder(value: str) -> bool:
    normalized = value.strip().lower()
    return normalized in {"", "change-me", "changeme", "sk-change-me"} or "change-me" in normalized


def _validate_gitignore(target: Path, messages: list[ValidationMessage]) -> None:
    gitignore = target / ".gitignore"
    if not gitignore.exists():
        messages.append(
            _message("warn", ".gitignore", "ausente; risco de commit acidental de .env")
        )
        return
    content = gitignore.read_text(encoding="utf-8", errors="replace")
    if not _gitignore_protects_env(content):
        messages.append(
            _message(
                "warn",
                ".gitignore",
                "presente mas nao protege .env (adicione `.env` e `.env.*` ao arquivo)",
            )
        )
        return
    if _gitignore_unignores_env(content):
        messages.append(
            _message(
                "warn",
                ".gitignore",
                "contem regra que desfaz ignore de .env (`!.env` ou similar)",
            )
        )
        return
    messages.append(_message("ok", ".gitignore", "protege .env"))


def _gitignore_patterns(content: str) -> list[str]:
    patterns: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        patterns.append(stripped)
    return patterns


def _gitignore_protects_env(content: str) -> bool:
    protective = {".env", ".env.*", "*.env", "**/.env"}
    return any(pattern in protective for pattern in _gitignore_patterns(content))


def _gitignore_unignores_env(content: str) -> bool:
    danger = {"!.env", "!.env.*"}
    return any(pattern in danger for pattern in _gitignore_patterns(content))
