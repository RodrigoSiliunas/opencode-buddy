import json

import pytest

from opencode_buddy.agent_driven_schema import (
    CAPABILITY_KEYS,
    PLAN_JSON_SCHEMA,
    REQUIRED_ROLES,
    ROLE_KEYS,
    SchemaValidationError,
    validate_plan_payload,
)


def _valid_payload() -> dict:
    return {
        "target_path": "./demo",
        "detected_summary": ["React + Vite"],
        "decisions": [
            {"capability": "frontend", "enabled": True, "answers": [["framework", "React"]], "reason": "vite"},
        ],
        "model_choices": [
            {"role": "build", "provider_key": "deepseek", "model_id": "deepseek-chat", "litellm_alias": "x"},
            {"role": "default", "provider_key": "deepseek", "model_id": "deepseek-chat", "litellm_alias": "x"},
            {"role": "deep", "provider_key": "deepseek", "model_id": "deepseek-reasoner", "litellm_alias": "x"},
        ],
        "extra_agents": [],
        "risks": [],
        "commands": ["npm run dev"],
        "reasons": [],
    }


def test_validate_accepts_valid_payload():
    validate_plan_payload(_valid_payload())  # nao levanta


def test_validate_rejects_missing_target_path():
    payload = _valid_payload()
    payload.pop("target_path")
    with pytest.raises(SchemaValidationError) as excinfo:
        validate_plan_payload(payload)
    assert "target_path" in str(excinfo.value)
    assert "obrigatorio" in str(excinfo.value)


def test_validate_rejects_missing_decisions():
    payload = _valid_payload()
    payload.pop("decisions")
    with pytest.raises(SchemaValidationError) as excinfo:
        validate_plan_payload(payload)
    assert "decisions" in str(excinfo.value)


def test_validate_rejects_missing_model_choices():
    payload = _valid_payload()
    payload.pop("model_choices")
    with pytest.raises(SchemaValidationError) as excinfo:
        validate_plan_payload(payload)
    assert "model_choices" in str(excinfo.value)


def test_validate_rejects_unknown_capability():
    payload = _valid_payload()
    payload["decisions"][0]["capability"] = "invented"
    with pytest.raises(SchemaValidationError) as excinfo:
        validate_plan_payload(payload)
    assert "invented" in str(excinfo.value)
    assert "capability" in str(excinfo.value)


def test_validate_rejects_unknown_role():
    payload = _valid_payload()
    payload["model_choices"][0]["role"] = "invented"
    with pytest.raises(SchemaValidationError) as excinfo:
        validate_plan_payload(payload)
    assert "invented" in str(excinfo.value)


def test_validate_rejects_non_bool_enabled():
    payload = _valid_payload()
    payload["decisions"][0]["enabled"] = "true"  # string em vez de bool
    with pytest.raises(SchemaValidationError) as excinfo:
        validate_plan_payload(payload)
    assert "boolean" in str(excinfo.value)


def test_validate_rejects_non_string_target_path():
    payload = _valid_payload()
    payload["target_path"] = 123
    with pytest.raises(SchemaValidationError) as excinfo:
        validate_plan_payload(payload)
    assert "string" in str(excinfo.value)


def test_validate_rejects_extra_agents_without_name():
    payload = _valid_payload()
    payload["extra_agents"] = [{"description": "sem nome", "model": "x"}]
    with pytest.raises(SchemaValidationError) as excinfo:
        validate_plan_payload(payload)
    assert "name" in str(excinfo.value)


def test_validate_rejects_model_choices_missing_build():
    payload = _valid_payload()
    payload["model_choices"] = [
        {"role": "default", "provider_key": "deepseek", "model_id": "deepseek-chat", "litellm_alias": "x"},
        {"role": "deep", "provider_key": "deepseek", "model_id": "deepseek-reasoner", "litellm_alias": "x"},
        {"role": "frontend", "provider_key": "deepseek", "model_id": "deepseek-chat", "litellm_alias": "x"},
    ]
    with pytest.raises(SchemaValidationError) as excinfo:
        validate_plan_payload(payload)
    assert "build" in str(excinfo.value)
    assert "obrigatorios" in str(excinfo.value).lower() or "ausentes" in str(excinfo.value).lower()


def test_validate_rejects_model_choices_missing_default():
    payload = _valid_payload()
    payload["model_choices"] = [
        {"role": "build", "provider_key": "deepseek", "model_id": "deepseek-chat", "litellm_alias": "x"},
        {"role": "deep", "provider_key": "deepseek", "model_id": "deepseek-reasoner", "litellm_alias": "x"},
        {"role": "frontend", "provider_key": "deepseek", "model_id": "deepseek-chat", "litellm_alias": "x"},
    ]
    with pytest.raises(SchemaValidationError) as excinfo:
        validate_plan_payload(payload)
    assert "default" in str(excinfo.value)


def test_validate_rejects_model_choices_missing_deep():
    payload = _valid_payload()
    payload["model_choices"] = [
        {"role": "build", "provider_key": "deepseek", "model_id": "deepseek-chat", "litellm_alias": "x"},
        {"role": "default", "provider_key": "deepseek", "model_id": "deepseek-chat", "litellm_alias": "x"},
        {"role": "frontend", "provider_key": "deepseek", "model_id": "deepseek-chat", "litellm_alias": "x"},
    ]
    with pytest.raises(SchemaValidationError) as excinfo:
        validate_plan_payload(payload)
    assert "deep" in str(excinfo.value)


def test_validate_rejects_extra_top_level_field():
    payload = _valid_payload()
    payload["raw_response"] = "leak"
    with pytest.raises(SchemaValidationError) as excinfo:
        validate_plan_payload(payload)
    assert "raw_response" in str(excinfo.value)


def test_validate_rejects_model_choices_below_minimum():
    payload = _valid_payload()
    payload["model_choices"] = payload["model_choices"][:2]
    with pytest.raises(SchemaValidationError) as excinfo:
        validate_plan_payload(payload)
    # Falha pode ser minItems OU pelo missing role; ambos sao aceitaveis
    msg = str(excinfo.value)
    assert "model_choices" in msg


def test_plan_json_schema_top_level_keys():
    assert isinstance(PLAN_JSON_SCHEMA, dict)
    assert PLAN_JSON_SCHEMA.get("type") == "object"
    assert "target_path" in PLAN_JSON_SCHEMA["properties"]
    assert "decisions" in PLAN_JSON_SCHEMA["properties"]
    assert "model_choices" in PLAN_JSON_SCHEMA["properties"]
    assert "raw_response" not in PLAN_JSON_SCHEMA["properties"]


def test_plan_json_schema_serializes_to_json():
    # Sanidade: o dict tem que ser serializavel pra ir embutido no prompt
    rendered = json.dumps(PLAN_JSON_SCHEMA, ensure_ascii=False, indent=2)
    assert "target_path" in rendered
    assert "raw_response" not in rendered


def test_capability_and_role_constants_match_schema():
    assert set(CAPABILITY_KEYS) == set(PLAN_JSON_SCHEMA["properties"]["decisions"]["items"]["properties"]["capability"]["enum"])
    assert set(ROLE_KEYS) == set(PLAN_JSON_SCHEMA["properties"]["model_choices"]["items"]["properties"]["role"]["enum"])
    assert set(REQUIRED_ROLES) <= set(ROLE_KEYS)
