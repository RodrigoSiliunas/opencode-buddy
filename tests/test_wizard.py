from opencode_buddy.model_catalog import AvailableModel
from opencode_buddy.wizard import (
    CAPABILITIES,
    _parse_multi_select,
    _roles_for_capabilities,
    build_options_from_selections,
    ensure_utf8_output,
    render_create_banner,
)


def _model(
    role,
    *,
    provider="DeepSeek",
    model_id="deepseek-chat",
    litellm_model="deepseek/deepseek-chat",
    env="DEEPSEEK_API_KEY",
    recommended=True,
):
    return AvailableModel(
        key=f"{provider}:{model_id}",
        provider=provider,
        model_id=model_id,
        litellm_model=litellm_model,
        display_name=f"{provider} - {model_id}",
        api_key_env=env,
        transport="API",
        source="suggested",
        recommended_for=(role,) if recommended else (),
    )


def test_build_options_from_selections_uses_capabilities():
    opts = build_options_from_selections(
        capabilities={"frontend": True, "backend": True, "audio": True, "video": False},
        selections={
            "build": _model("build"),
            "frontend": _model("frontend", provider="OpenCode Go", model_id="kimi-k2.6", litellm_model="openai/kimi-k2.6", env="OPENCODE_GO_API_KEY"),
            "backend": _model("backend", provider="Anthropic", model_id="claude-sonnet", litellm_model="anthropic/claude-sonnet", env="ANTHROPIC_API_KEY"),
            "audio": _model("audio", provider="Google Gemini", model_id="gemini-2.5-flash", litellm_model="gemini/gemini-2.5-flash", env="GEMINI_API_KEY"),
            "default": _model("default"),
            "deep": _model("deep", model_id="deepseek-reasoner", litellm_model="deepseek/deepseek-reasoner"),
        },
        detected_env=("DEEPSEEK_API_KEY",),
    )

    assert opts.enable_frontend_agent is True
    assert opts.enable_backend_agent is True
    assert opts.frontend_model == "litellm/frontend-model"
    assert opts.backend_model == "litellm/backend-model"
    assert any(agent.name == "audio" for agent in opts.extra_agents)
    assert not any(agent.name == "video" for agent in opts.extra_agents)
    assert {spec.alias for spec in opts.model_specs} == {
        "build-model",
        "frontend-model",
        "backend-model",
        "audio-model",
        "default-model",
        "deep-model",
    }


def test_build_options_from_selections_allows_oauth_model():
    oauth = AvailableModel(
        key="oauth-chatgpt",
        provider="ChatGPT OAuth",
        model_id="gpt-5.5",
        litellm_model="chatgpt/gpt-5.5",
        display_name="ChatGPT OAuth - GPT-5.5",
        api_key_env=None,
        transport="OAuth",
        source="opencode auth",
        recommended_for=("backend",),
    )
    opts = build_options_from_selections(
        capabilities={"frontend": False, "backend": True, "audio": False, "video": False},
        selections={
            "build": _model("build"),
            "backend": oauth,
            "default": _model("default"),
            "deep": _model("deep"),
        },
    )

    assert opts.enable_chatgpt is True
    assert opts.enable_frontend_agent is False
    assert opts.backend_model == "chatgpt/gpt-5.5"
    assert "backend-model" not in {spec.alias for spec in opts.model_specs}


def test_render_create_banner_includes_product_name():
    banner = render_create_banner()
    assert "OpenCode Buddy create" in banner
    assert "▒█████" in banner
    assert "▄▄▄▄" in banner


def test_ensure_utf8_output_is_safe_to_call():
    ensure_utf8_output()


def test_parse_multi_select_accepts_commas_spaces_and_zero():
    assert _parse_multi_select("1, 2 4", max_value=4) == (1, 2, 4)
    assert _parse_multi_select("0", max_value=4) == ()


def test_parse_multi_select_rejects_invalid_values():
    try:
        _parse_multi_select("5", max_value=4)
    except ValueError as exc:
        assert "fora da lista" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_parse_multi_select_rejects_empty_choice():
    try:
        _parse_multi_select("", max_value=4)
    except ValueError as exc:
        assert "pelo menos uma" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_capabilities_include_expanded_set():
    keys = {capability.key for capability in CAPABILITIES}
    assert {"frontend", "backend", "audio", "video"} <= keys
    assert {"mobile", "cli", "desktop", "data", "ml", "devops", "qa", "docs", "security", "integrations"} <= keys


def test_capabilities_with_subquestions_have_choices():
    frontend = next(cap for cap in CAPABILITIES if cap.key == "frontend")
    assert any(question.key == "framework" for question in frontend.subquestions)
    assert "React" in next(q.choices for q in frontend.subquestions if q.key == "framework")


def test_capabilities_without_dedicated_agent_skip_role():
    capabilities = {cap.key: False for cap in CAPABILITIES}
    capabilities["mobile"] = True
    capabilities["docs"] = True
    roles = _roles_for_capabilities(capabilities)
    assert roles == ["build", "default", "deep"]  # neither mobile nor docs add roles


def test_capabilities_with_dedicated_agent_add_role():
    capabilities = {cap.key: False for cap in CAPABILITIES}
    capabilities["frontend"] = True
    capabilities["audio"] = True
    roles = _roles_for_capabilities(capabilities)
    assert "frontend" in roles
    assert "audio" in roles


def test_build_options_includes_capability_answers_in_notes():
    selections = {
        "build": _model("build"),
        "default": _model("default"),
        "deep": _model("deep"),
    }
    opts = build_options_from_selections(
        capabilities={cap.key: False for cap in CAPABILITIES},
        selections=selections,
        capability_answers={"docs": {"generator": "MkDocs"}},
    )
    joined = "\n".join(opts.project_context.notes)
    assert "Documentacao" in joined
    assert "generator=MkDocs" in joined


def test_build_options_skips_extra_agent_for_context_only_capabilities():
    capabilities = {cap.key: False for cap in CAPABILITIES}
    capabilities["mobile"] = True
    selections = {
        "build": _model("build"),
        "default": _model("default"),
        "deep": _model("deep"),
    }
    opts = build_options_from_selections(capabilities=capabilities, selections=selections)
    assert all(agent.name != "mobile" for agent in opts.extra_agents)
