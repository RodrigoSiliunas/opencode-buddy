from opencode_buddy.config_builder import (
    InitOptions,
    build_env_example,
    build_litellm_config,
    build_opencode_config,
    build_start_proxy_script,
)


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


def test_start_proxy_script_loads_env_and_sets_utf8():
    script = build_start_proxy_script(InitOptions())
    assert "PYTHONIOENCODING" in script
    assert "utf-8" in script
    assert ".env" in script
    assert "litellm --config litellm-config.yaml --port 4000" in script


def test_start_proxy_script_uses_custom_port():
    script = build_start_proxy_script(InitOptions(litellm_port=8123))
    assert "--port 8123" in script
