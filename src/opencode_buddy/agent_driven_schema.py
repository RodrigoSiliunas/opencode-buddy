"""Schema formal do payload do Agent Driven Planner.

Estrutura:
- `PLAN_JSON_SCHEMA` e um dict compativel com JSON Schema draft-07. Ele e
  embutido no PLANNER_SYSTEM_PROMPT para o LLM saber exatamente o que devolver.
- `validate_plan_payload(data)` faz validacao manual estrita (sem dependencia
  externa de `jsonschema`) cobrindo `type`, `required`, `enum`,
  `additionalProperties` e `minItems`. Tambem valida a regra de negocio
  "model_choices precisa cobrir build/default/deep".

Erros viram `SchemaValidationError(ValueError)` com mensagem que inclui o
caminho do campo + motivo curto. O caller (em `agent_driven._parse_plan_payload`)
converte em `PlannerError`, o que aciona o fallback automatico para o
DeterministicPlannerClient via `propose_plan_with_fallback`.

NOTA: o schema NAO inclui `raw_response`. Esse campo so existe no dataclass
interno (`AgentDrivenPlan.raw_response`) para debug; nao deve cruzar a
fronteira pro LLM nem pro output publico em `--json`.
"""
from __future__ import annotations

from typing import Any


CAPABILITY_KEYS: tuple[str, ...] = (
    "frontend",
    "backend",
    "audio",
    "video",
    "mobile",
    "cli",
    "desktop",
    "data",
    "ml",
    "devops",
    "qa",
    "docs",
    "security",
    "integrations",
)

ROLE_KEYS: tuple[str, ...] = (
    "build",
    "frontend",
    "backend",
    "audio",
    "video",
    "default",
    "deep",
)

REQUIRED_ROLES: tuple[str, ...] = ("build", "default", "deep")


PLAN_JSON_SCHEMA: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "AgentDrivenPlan",
    "type": "object",
    "required": ["target_path", "decisions", "model_choices"],
    "additionalProperties": False,
    "properties": {
        "target_path": {"type": "string"},
        "detected_summary": {
            "type": "array",
            "items": {"type": "string"},
        },
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["capability", "enabled"],
                "additionalProperties": False,
                "properties": {
                    "capability": {"type": "string", "enum": list(CAPABILITY_KEYS)},
                    "enabled": {"type": "boolean"},
                    "answers": {
                        "type": "array",
                        "items": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 2,
                            "maxItems": 2,
                        },
                    },
                    "reason": {"type": "string"},
                },
            },
        },
        "model_choices": {
            "type": "array",
            "minItems": 3,
            "items": {
                "type": "object",
                "required": ["role", "provider_key", "model_id", "litellm_alias"],
                "additionalProperties": False,
                "properties": {
                    "role": {"type": "string", "enum": list(ROLE_KEYS)},
                    "provider_key": {"type": "string"},
                    "model_id": {"type": "string"},
                    "litellm_alias": {"type": "string"},
                    "reason": {"type": "string"},
                },
            },
        },
        "extra_agents": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "model"],
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "model": {"type": "string"},
                    "prompt_file": {"type": "string"},
                },
            },
        },
        "risks": {"type": "array", "items": {"type": "string"}},
        "commands": {"type": "array", "items": {"type": "string"}},
        "reasons": {"type": "array", "items": {"type": "string"}},
    },
}


class SchemaValidationError(ValueError):
    """Falha de validacao do payload do planner."""


def validate_plan_payload(data: object) -> None:
    """Valida `data` contra `PLAN_JSON_SCHEMA`. Levanta `SchemaValidationError`."""
    _validate(data, PLAN_JSON_SCHEMA, path="$")
    _check_required_roles(data)


def _validate(value: object, schema: dict[str, Any], *, path: str) -> None:
    expected_type = schema.get("type")
    if expected_type == "object":
        _validate_object(value, schema, path=path)
    elif expected_type == "array":
        _validate_array(value, schema, path=path)
    elif expected_type == "string":
        if not isinstance(value, str):
            raise SchemaValidationError(f"{path}: esperado string, recebido {_type_label(value)}")
        _check_enum(value, schema, path=path)
    elif expected_type == "boolean":
        if not isinstance(value, bool):
            raise SchemaValidationError(f"{path}: esperado boolean, recebido {_type_label(value)}")
    elif expected_type == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            raise SchemaValidationError(f"{path}: esperado integer, recebido {_type_label(value)}")
    elif expected_type == "number":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise SchemaValidationError(f"{path}: esperado number, recebido {_type_label(value)}")
    else:
        # tipo nao especificado/extension: aceita
        return


def _validate_object(value: object, schema: dict[str, Any], *, path: str) -> None:
    if not isinstance(value, dict):
        raise SchemaValidationError(f"{path}: esperado object, recebido {_type_label(value)}")

    required = schema.get("required", []) or []
    for field in required:
        if field not in value:
            raise SchemaValidationError(f"{path}.{field}: campo obrigatorio ausente")

    properties = schema.get("properties", {}) or {}
    additional = schema.get("additionalProperties", True)
    if additional is False:
        unknown = sorted(set(value.keys()) - set(properties.keys()))
        if unknown:
            raise SchemaValidationError(
                f"{path}: campo(s) nao permitido(s): {', '.join(unknown)}"
            )

    for field_name, sub_schema in properties.items():
        if field_name not in value:
            continue
        _validate(value[field_name], sub_schema, path=f"{path}.{field_name}")


def _validate_array(value: object, schema: dict[str, Any], *, path: str) -> None:
    if not isinstance(value, list):
        raise SchemaValidationError(f"{path}: esperado array, recebido {_type_label(value)}")

    min_items = schema.get("minItems")
    if isinstance(min_items, int) and len(value) < min_items:
        raise SchemaValidationError(
            f"{path}: minimo {min_items} item(ns), recebido {len(value)}"
        )
    max_items = schema.get("maxItems")
    if isinstance(max_items, int) and len(value) > max_items:
        raise SchemaValidationError(
            f"{path}: maximo {max_items} item(ns), recebido {len(value)}"
        )

    item_schema = schema.get("items")
    if item_schema is None:
        return
    for index, item in enumerate(value):
        _validate(item, item_schema, path=f"{path}[{index}]")


def _check_enum(value: str, schema: dict[str, Any], *, path: str) -> None:
    enum = schema.get("enum")
    if enum is None:
        return
    if value not in enum:
        joined = ", ".join(repr(option) for option in enum)
        raise SchemaValidationError(
            f"{path}: valor invalido {value!r} (esperado um de: {joined})"
        )


def _type_label(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _check_required_roles(data: object) -> None:
    if not isinstance(data, dict):
        return
    choices = data.get("model_choices")
    if not isinstance(choices, list):
        return
    seen_roles: set[str] = set()
    for item in choices:
        if isinstance(item, dict):
            role = item.get("role")
            if isinstance(role, str):
                seen_roles.add(role)
    missing = [role for role in REQUIRED_ROLES if role not in seen_roles]
    if missing:
        raise SchemaValidationError(
            f"model_choices: roles obrigatorios ausentes: {', '.join(missing)}"
        )
