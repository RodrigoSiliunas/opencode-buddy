from dataclasses import dataclass, field


@dataclass(frozen=True)
class InitOptions:
    litellm_url: str = "http://localhost:4000/v1"
    litellm_port: int = 4000
    enable_chatgpt: bool = True

    # OpenCode Go gateway (https://opencode.ai/docs/pt-br/go/)
    opencode_go_api_base: str = "https://opencode.ai/zen/go/v1"
    go_kimi_model: str = "kimi-k2.6"
    go_deepseek_fast_model: str = "deepseek-v4-flash"
    go_heavy_fallback_model: str = "qwen3.6-plus"  # quando deep direto falha

    # DeepSeek direct API (fallback para fast, primary para deep)
    deepseek_fast_direct_model: str = "deepseek/deepseek-chat"
    deepseek_pro_direct_model: str = "deepseek/deepseek-reasoner"

    routing_strategy: str = "simple-shuffle"
    backend_model: str = "chatgpt/gpt-5.5"
    drop_params: tuple[str, ...] = field(default_factory=lambda: ("reasoningSummary",))


def build_opencode_config(opts: InitOptions) -> dict:
    config: dict = {
        "$schema": "https://opencode.ai/config.json",
        "provider": {
            "litellm": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "LiteLLM Proxy",
                "options": {
                    "baseURL": opts.litellm_url,
                    "apiKey": "{env:LITELLM_MASTER_KEY}",
                },
                "models": {
                    "deepseek-fast": {"name": "DeepSeek V4 Flash (Go → direto)"},
                    "deepseek-pro": {"name": "DeepSeek Reasoner (direto → Qwen3.6 Go)"},
                    "kimi": {"name": "Kimi K2.6 (Go)"},
                },
            }
        },
        "agent": {
            "build": {
                "description": "Orquestrador: classifica pedido e delega ao subagent certo",
                "model": "litellm/deepseek-fast",
                "prompt": "{file:.opencode/agents/orchestrator.md}",
            },
            "frontend": {
                "description": "UI/UX, React, CSS, componentes visuais",
                "model": "litellm/kimi",
                "prompt": "{file:.opencode/agents/frontend.md}",
            },
            "default": {
                "description": "Tarefas gerais rápidas: refactor pequeno, leitura, perguntas",
                "model": "litellm/deepseek-fast",
                "prompt": "{file:.opencode/agents/default.md}",
            },
            "deep": {
                "description": "Raciocínio pesado: arquitetura, debug complexo, planejamento longo",
                "model": "litellm/deepseek-pro",
                "prompt": "{file:.opencode/agents/deep.md}",
            },
        },
        "model": "litellm/deepseek-fast",
    }

    if opts.enable_chatgpt:
        config["agent"]["backend"] = {
            "description": "APIs, banco, auth, infraestrutura server-side",
            "model": opts.backend_model,
            "prompt": "{file:.opencode/agents/backend.md}",
        }

    return config


def build_litellm_config(opts: InitOptions) -> dict:
    drop = lambda: list(opts.drop_params)

    model_list = [
        # deepseek-fast: primary via Go, fallback direto
        {
            "model_name": "deepseek-fast",
            "litellm_params": {
                "model": f"openai/{opts.go_deepseek_fast_model}",
                "api_key": "os.environ/OPENCODE_GO_API_KEY",
                "api_base": opts.opencode_go_api_base,
                "drop_params": drop(),
            },
        },
        {
            "model_name": "deepseek-fast-fallback",
            "litellm_params": {
                "model": opts.deepseek_fast_direct_model,
                "api_key": "os.environ/DEEPSEEK_API_KEY",
                "drop_params": drop(),
            },
        },
        # deepseek-pro: primary direto (Go não tem reasoner), fallback Qwen3.6 via Go
        {
            "model_name": "deepseek-pro",
            "litellm_params": {
                "model": opts.deepseek_pro_direct_model,
                "api_key": "os.environ/DEEPSEEK_API_KEY",
                "drop_params": drop(),
            },
        },
        {
            "model_name": "deepseek-pro-fallback",
            "litellm_params": {
                "model": f"openai/{opts.go_heavy_fallback_model}",
                "api_key": "os.environ/OPENCODE_GO_API_KEY",
                "api_base": opts.opencode_go_api_base,
                "drop_params": drop(),
            },
        },
        # kimi: só Go
        {
            "model_name": "kimi",
            "litellm_params": {
                "model": f"openai/{opts.go_kimi_model}",
                "api_key": "os.environ/OPENCODE_GO_API_KEY",
                "api_base": opts.opencode_go_api_base,
                "drop_params": drop(),
            },
        },
    ]

    return {
        "model_list": model_list,
        "router_settings": {
            "routing_strategy": opts.routing_strategy,
            "fallbacks": [
                {"deepseek-fast": ["deepseek-fast-fallback"]},
                {"deepseek-pro": ["deepseek-pro-fallback"]},
            ],
        },
        "general_settings": {
            "master_key": "os.environ/LITELLM_MASTER_KEY",
        },
    }


def build_start_proxy_script(opts: InitOptions) -> str:
    """PowerShell helper: carrega .env, força UTF-8 (bug Windows do banner LiteLLM), sobe proxy."""
    return f"""# start-proxy.ps1 — sobe LiteLLM com .env carregado
# Uso: .\\start-proxy.ps1
$ErrorActionPreference = "Stop"

$envFile = Join-Path $PSScriptRoot ".env"
if (-not (Test-Path $envFile)) {{
    Write-Error "Arquivo .env não encontrado. Rode: cp .env.example .env e preencha as chaves."
}}

Get-Content $envFile | ForEach-Object {{
    if ($_ -match '^\\s*([^#=\\s]+)\\s*=\\s*(.+?)\\s*$') {{
        [Environment]::SetEnvironmentVariable($matches[1], $matches[2], 'Process')
    }}
}}

# Bug Windows: banner LiteLLM tem chars Unicode que cp1252 rejeita
$env:PYTHONIOENCODING = "utf-8"

Write-Host "Subindo LiteLLM em http://localhost:{opts.litellm_port}" -ForegroundColor Cyan
litellm --config litellm-config.yaml --port {opts.litellm_port}
"""


def build_env_example(opts: InitOptions) -> str:
    lines = [
        "# LiteLLM proxy (gere uma string aleatória, ex: openssl rand -hex 24)",
        "LITELLM_MASTER_KEY=sk-CHANGE-ME",
        "",
        "# OpenCode Go (https://opencode.ai/auth — subscription $10/mês)",
        "# Fornece DeepSeek V4 Flash, Kimi K2.6, Qwen3.6 Plus, GLM-5.1, etc.",
        "OPENCODE_GO_API_KEY=",
        "",
        "# DeepSeek direto (https://platform.deepseek.com/api_keys)",
        "# Usado como fallback de deepseek-fast e primary de deepseek-pro (reasoner)",
        "DEEPSEEK_API_KEY=",
        "",
    ]
    if opts.enable_chatgpt:
        lines.append("# Nota: GPT-5.5 (backend agent) usa OAuth ChatGPT — sem chave aqui")
        lines.append("# Verifique com: opencode auth list")
    return "\n".join(lines) + "\n"
