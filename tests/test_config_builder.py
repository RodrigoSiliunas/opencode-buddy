from opencode_buddy.config_builder import (
    AgentSpec,
    CapabilityDetail,
    InitOptions,
    ModelSpec,
    ProjectContext,
    build_custom_agent_prompt,
    build_env_example,
    build_gitignore,
    build_litellm_config,
    build_opencode_config,
    build_orchestrator_prompt,
    build_project_context,
    build_start_proxy_script,
    default_constraints,
    default_conventions,
    default_risks,
    iter_agent_specs,
    oauth_providers_used,
    uses_any_oauth,
    uses_chatgpt_oauth,
)
from opencode_buddy.registry import OAuthModelEntry, OAuthProviderEntry, Registry, load_registry


def test_opencode_default_includes_all_agents():
    cfg = build_opencode_config(InitOptions())
    agents = cfg["agent"]
    assert set(agents) == {"build", "frontend", "backend", "default", "deep"}
    assert agents["frontend"]["model"] == "litellm/kimi"
    assert agents["backend"]["model"] == "chatgpt/gpt-5.5"
    assert agents["default"]["model"] == "litellm/deepseek-fast"
    assert agents["deep"]["model"] == "litellm/deepseek-pro"
    assert agents["build"]["model"] == "litellm/deepseek-fast"
    assert cfg["model"] == "litellm/deepseek-fast"


def test_opencode_no_chatgpt_drops_backend():
    cfg = build_opencode_config(InitOptions(enable_chatgpt=False))
    assert "backend" not in cfg["agent"]
    assert {"build", "frontend", "default", "deep"} == set(cfg["agent"])


def test_opencode_can_drop_frontend_agent():
    cfg = build_opencode_config(InitOptions(enable_frontend_agent=False, enable_chatgpt=False))
    assert "frontend" not in cfg["agent"]
    assert {"build", "default", "deep"} == set(cfg["agent"])


def test_backend_agent_can_use_litellm_without_chatgpt():
    cfg = build_opencode_config(
        InitOptions(
            enable_chatgpt=False,
            enable_backend_agent=True,
            backend_model="litellm/backend-model",
            model_specs=(
                ModelSpec(
                    alias="backend-model",
                    litellm_model="anthropic/claude-sonnet-4-5",
                    display_name="Backend Claude",
                    api_key_env="ANTHROPIC_API_KEY",
                ),
            ),
        )
    )
    assert cfg["agent"]["backend"]["model"] == "litellm/backend-model"
    assert "backend-model" in cfg["provider"]["litellm"]["models"]


def test_iter_agent_specs_keeps_backend_order_when_enabled():
    names = [spec.name for spec in iter_agent_specs(InitOptions())]
    assert names == ["build", "frontend", "backend", "default", "deep"]


def test_iter_agent_specs_appends_extra_agents():
    extra = AgentSpec(
        name="reviewer",
        description="Revisao critica de codigo",
        model="litellm/deepseek-pro",
        prompt_file="reviewer.md",
    )
    cfg = build_opencode_config(InitOptions(extra_agents=(extra,)))
    assert cfg["agent"]["reviewer"] == {
        "description": "Revisao critica de codigo",
        "model": "litellm/deepseek-pro",
        "prompt": "{file:.opencode/agents/reviewer.md}",
    }


def test_build_custom_agent_prompt_mentions_scope_and_model():
    spec = AgentSpec(
        name="qa",
        description="Testes automatizados e qualidade",
        model="litellm/deepseek-fast",
        prompt_file="qa.md",
    )
    prompt = build_custom_agent_prompt(spec)
    assert "`qa`" in prompt
    assert "Testes automatizados e qualidade" in prompt
    assert "`litellm/deepseek-fast`" in prompt


def test_orchestrator_prompt_routes_backend_to_deep_without_chatgpt():
    prompt = build_orchestrator_prompt(InitOptions(enable_chatgpt=False))
    assert "`@backend`" not in prompt
    assert "infraestrutura server-side" in prompt
    assert "`@deep`" in prompt


def test_orchestrator_prompt_mentions_extra_agents():
    extra = AgentSpec(
        name="reviewer",
        description="Revisao critica de codigo",
        model="litellm/deepseek-pro",
        prompt_file="reviewer.md",
    )
    prompt = build_orchestrator_prompt(InitOptions(extra_agents=(extra,)))
    assert "Agents customizados" in prompt
    assert "`@reviewer`" in prompt
    assert "Revisao critica de codigo" in prompt


def test_orchestrator_prompt_omits_frontend_route_when_disabled():
    prompt = build_orchestrator_prompt(InitOptions(enable_frontend_agent=False))
    assert "`@frontend`" not in prompt


def test_opencode_provider_baseurl_uses_option():
    cfg = build_opencode_config(InitOptions(litellm_url="http://prox:9000/v1"))
    assert cfg["provider"]["litellm"]["options"]["baseURL"] == "http://prox:9000/v1"


def test_opencode_apikey_is_env_substitution():
    cfg = build_opencode_config(InitOptions())
    assert cfg["provider"]["litellm"]["options"]["apiKey"] == "{env:LITELLM_MASTER_KEY}"


def test_litellm_has_five_entries_with_fallbacks():
    cfg = build_litellm_config(InitOptions())
    aliases = [m["model_name"] for m in cfg["model_list"]]
    assert aliases == [
        "deepseek-fast",
        "deepseek-fast-fallback",
        "deepseek-pro",
        "deepseek-pro-fallback",
        "kimi",
    ]


def test_litellm_fallback_routing_rules():
    cfg = build_litellm_config(InitOptions())
    fallbacks = cfg["router_settings"]["fallbacks"]
    assert {"deepseek-fast": ["deepseek-fast-fallback"]} in fallbacks
    assert {"deepseek-pro": ["deepseek-pro-fallback"]} in fallbacks


def test_litellm_deepseek_fast_primary_via_go():
    cfg = build_litellm_config(InitOptions())
    fast = next(m for m in cfg["model_list"] if m["model_name"] == "deepseek-fast")
    assert fast["litellm_params"]["model"] == "openai/deepseek-v4-flash"
    assert fast["litellm_params"]["api_base"] == "https://opencode.ai/zen/go/v1"
    assert fast["litellm_params"]["api_key"] == "os.environ/OPENCODE_GO_API_KEY"


def test_litellm_deepseek_fast_fallback_direct():
    cfg = build_litellm_config(InitOptions())
    fb = next(m for m in cfg["model_list"] if m["model_name"] == "deepseek-fast-fallback")
    assert fb["litellm_params"]["model"] == "deepseek/deepseek-chat"
    assert fb["litellm_params"]["api_key"] == "os.environ/DEEPSEEK_API_KEY"
    assert "api_base" not in fb["litellm_params"]


def test_litellm_deepseek_pro_primary_direct_fallback_qwen():
    cfg = build_litellm_config(InitOptions())
    pro = next(m for m in cfg["model_list"] if m["model_name"] == "deepseek-pro")
    pro_fb = next(m for m in cfg["model_list"] if m["model_name"] == "deepseek-pro-fallback")
    assert pro["litellm_params"]["model"] == "deepseek/deepseek-reasoner"
    assert pro["litellm_params"]["api_key"] == "os.environ/DEEPSEEK_API_KEY"
    assert pro_fb["litellm_params"]["model"] == "openai/qwen3.6-plus"
    assert pro_fb["litellm_params"]["api_base"] == "https://opencode.ai/zen/go/v1"


def test_litellm_kimi_via_go_only():
    cfg = build_litellm_config(InitOptions())
    kimi = next(m for m in cfg["model_list"] if m["model_name"] == "kimi")
    assert kimi["litellm_params"]["model"] == "openai/kimi-k2.6"
    assert kimi["litellm_params"]["api_base"] == "https://opencode.ai/zen/go/v1"


def test_litellm_drop_params_per_entry():
    cfg = build_litellm_config(InitOptions())
    for entry in cfg["model_list"]:
        assert entry["litellm_params"]["drop_params"] == ["reasoningSummary"]


def test_litellm_routing_strategy_override():
    cfg = build_litellm_config(InitOptions(routing_strategy="latency-based-routing"))
    assert cfg["router_settings"]["routing_strategy"] == "latency-based-routing"


def test_litellm_uses_custom_model_specs_without_default_fallbacks():
    cfg = build_litellm_config(
        InitOptions(
            model_specs=(
                ModelSpec(
                    alias="gemini-pro",
                    litellm_model="gemini/gemini-2.5-pro",
                    display_name="Gemini Pro",
                    api_key_env="GEMINI_API_KEY",
                ),
            )
        )
    )
    assert cfg["model_list"] == [
        {
            "model_name": "gemini-pro",
            "litellm_params": {
                "model": "gemini/gemini-2.5-pro",
                "drop_params": ["reasoningSummary"],
                "api_key": "os.environ/GEMINI_API_KEY",
            },
        }
    ]
    assert "fallbacks" not in cfg["router_settings"]


def test_env_example_has_required_keys():
    text = build_env_example(InitOptions())
    assert "LITELLM_MASTER_KEY=sk-CHANGE-ME" in text
    assert "OPENCODE_GO_API_KEY=" in text
    assert "DEEPSEEK_API_KEY=" in text
    assert "MOONSHOT_API_KEY" not in text
    assert "OPENAI_API_KEY=" not in text


def test_env_example_no_chatgpt_drops_oauth_note():
    text = build_env_example(InitOptions(enable_chatgpt=False))
    assert "ChatGPT" not in text
    assert "OAuth" not in text


def test_env_example_includes_selected_provider_keys():
    text = build_env_example(
        InitOptions(
            enable_chatgpt=False,
            enable_backend_agent=True,
            backend_model="litellm/backend-model",
            model_specs=(
                ModelSpec(
                    alias="backend-model",
                    litellm_model="gemini/gemini-2.5-pro",
                    display_name="Gemini Pro",
                    api_key_env="GEMINI_API_KEY",
                ),
                ModelSpec(
                    alias="moonshot-model",
                    litellm_model="moonshot/kimi-k2",
                    display_name="Moonshot",
                    api_key_env="MOONSHOT_API_KEY",
                ),
            ),
        )
    )
    assert "GEMINI_API_KEY=" in text
    assert "MOONSHOT_API_KEY=" in text
    assert "DEEPSEEK_API_KEY=" not in text


def test_start_proxy_script_loads_env_and_sets_utf8():
    script = build_start_proxy_script(InitOptions())
    assert "PYTHONIOENCODING" in script
    assert "utf-8" in script
    assert ".env" in script
    assert "litellm --config litellm-config.yaml --port 4000" in script


def test_start_proxy_script_uses_custom_port():
    script = build_start_proxy_script(InitOptions(litellm_port=8123))
    assert "--port 8123" in script


def test_build_gitignore_protects_env_and_excludes_example():
    content = build_gitignore()
    lines = [line.strip() for line in content.splitlines()]
    assert ".env" in lines
    assert ".env.*" in lines
    assert "!.env.example" in lines
    assert "node_modules/" in lines
    assert "__pycache__/" in lines


def test_oauth_providers_used_returns_chatgpt_when_backend_uses_it():
    opts = InitOptions()  # default uses chatgpt/gpt-5.5 in backend
    providers = oauth_providers_used(opts)
    assert len(providers) == 1
    assert providers[0].key == "chatgpt"
    assert uses_any_oauth(opts) is True
    assert uses_chatgpt_oauth(opts) is True


def test_oauth_providers_used_empty_when_no_oauth_models():
    opts = InitOptions(
        enable_chatgpt=False,
        enable_backend_agent=True,
        backend_model="litellm/backend",
        model_specs=(
            ModelSpec(
                alias="backend",
                litellm_model="anthropic/claude-sonnet-4-5",
                display_name="Anthropic",
                api_key_env="ANTHROPIC_API_KEY",
            ),
        ),
    )
    assert oauth_providers_used(opts) == ()
    assert uses_any_oauth(opts) is False
    assert uses_chatgpt_oauth(opts) is False


def test_env_example_lists_each_used_oauth_provider(monkeypatch):
    real_registry = load_registry()
    fake_oauth = OAuthProviderEntry(
        key="github-copilot",
        name="GitHub Copilot",
        detect_kind="opencode-auth-list",
        detect_match="copilot",
        models=(
            OAuthModelEntry(
                id="copilot-gpt",
                litellm_model="copilot/gpt-x",
                cost_label="plan",
                recommended_for=("frontend",),
            ),
        ),
    )
    fake_registry = Registry(
        version=real_registry.version,
        providers=real_registry.providers,
        oauth_providers=real_registry.oauth_providers + (fake_oauth,),
    )
    monkeypatch.setattr("opencode_buddy.config_builder.load_registry", lambda: fake_registry)

    opts = InitOptions(frontend_model="copilot/gpt-x")  # backend default still chatgpt/gpt-5.5
    text = build_env_example(opts)
    assert "GitHub Copilot" in text
    assert "ChatGPT OAuth" in text
    assert text.count("opencode auth login") >= 1


def test_env_example_drops_oauth_note_when_no_oauth():
    opts = InitOptions(
        enable_chatgpt=False,
        enable_backend_agent=False,
    )
    text = build_env_example(opts)
    assert "OAuth" not in text


def test_env_example_mentions_chatgpt_oauth_by_default():
    opts = InitOptions()  # backend defaults to chatgpt/gpt-5.5
    text = build_env_example(opts)
    assert "ChatGPT OAuth" in text
    assert "opencode auth login" in text


def test_build_project_context_minimal_still_renders():
    opts = InitOptions()
    text = build_project_context(opts)
    assert "# Contexto do projeto" in text
    assert "## Stack" in text


def test_build_project_context_renders_rich_sections():
    ctx = ProjectContext(
        preset="custom",
        stack="Frontend/UI, Backend/API",
        summary="Projeto exemplo com frontend React e backend Python.",
        capabilities=(
            CapabilityDetail(
                key="frontend",
                label="Frontend/UI",
                answers=(("framework", "React"), ("typescript", "Sim"), ("styling", "Tailwind")),
            ),
            CapabilityDetail(
                key="backend",
                label="Backend/API",
                answers=(("runtime", "Python"), ("database", "Postgres"), ("auth", "JWT")),
            ),
        ),
        role_models=(("frontend/UI", "OpenCode Go - kimi-k2.6"), ("backend/API", "ChatGPT OAuth - gpt-5.5")),
        commands=("opencode-buddy validate .", ".\\start-proxy.ps1"),
        conventions=default_conventions(),
        constraints=default_constraints(),
        risks=default_risks(),
        notes=("Wizard generated.",),
    )
    opts = InitOptions(project_context=ctx)
    text = build_project_context(opts)

    assert "## Visao geral" in text
    assert "Projeto exemplo com frontend React" in text
    assert "## Capacidades selecionadas" in text
    assert "### Frontend/UI" in text
    assert "framework: React" in text
    assert "### Backend/API" in text
    assert "runtime: Python" in text
    assert "## Modelos por papel" in text
    assert "frontend/UI: OpenCode Go - kimi-k2.6" in text
    assert "## Comandos uteis" in text
    assert "## Convencoes" in text
    assert "## Restricoes" in text
    assert "## Riscos e pontos de atencao" in text
    assert "## Notas do scaffold" in text


def test_build_project_context_skips_empty_sections():
    opts = InitOptions(project_context=ProjectContext(preset="generic", stack="Projeto generico"))
    text = build_project_context(opts)
    assert "## Capacidades selecionadas" not in text
    assert "## Modelos por papel" not in text
    assert "## Riscos e pontos de atencao" not in text


def test_default_conventions_mentions_secrets_and_gitignore():
    convs = default_conventions()
    joined = "\n".join(convs)
    assert "secret" in joined.lower()
    assert ".gitignore" in joined.lower() or ".env" in joined.lower()


def test_default_constraints_explain_oauth_routing():
    constraints = default_constraints()
    joined = "\n".join(constraints)
    assert "litellm" in joined.lower()
    assert "oauth" in joined.lower()


def test_orchestrator_prompt_references_project_md_sections():
    prompt = build_orchestrator_prompt(InitOptions())
    assert ".opencode/project.md" in prompt
    assert "Capacidades selecionadas" in prompt or "Modelos por papel" in prompt


def test_custom_agent_prompt_references_project_md_sections():
    spec = AgentSpec(name="qa", description="QA", model="litellm/x", prompt_file="qa.md")
    prompt = build_custom_agent_prompt(spec)
    assert ".opencode/project.md" in prompt
    assert "Convencoes" in prompt or "Restricoes" in prompt
