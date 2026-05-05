from dataclasses import dataclass, field

from opencode_buddy.registry import OAuthProviderEntry, ProviderEntry, load_registry


def _registry_provider(provider_key: str) -> ProviderEntry | None:
    registry = load_registry()
    return next((provider for provider in registry.providers if provider.key == provider_key), None)


def _registry_model_id(provider_key: str, role: str, fallback: str) -> str:
    provider = _registry_provider(provider_key)
    if provider is None:
        return fallback
    for model in provider.models:
        if role in model.recommended_for:
            return model.id
    return provider.models[0].id if provider.models else fallback


def _registry_litellm_model(provider_key: str, role: str, fallback: str) -> str:
    provider = _registry_provider(provider_key)
    if provider is None:
        return fallback
    for model in provider.models:
        if role in model.recommended_for:
            return model.litellm_model
    return provider.models[0].litellm_model if provider.models else fallback


def _registry_api_base(provider_key: str, fallback: str) -> str:
    provider = _registry_provider(provider_key)
    if provider is None or not provider.api_base:
        return fallback
    return provider.api_base


@dataclass(frozen=True)
class AgentSpec:
    name: str
    description: str
    model: str
    prompt_file: str
    template_file: str | None = None

    @property
    def prompt_ref(self) -> str:
        return f"{{file:.opencode/agents/{self.prompt_file}}}"


@dataclass(frozen=True)
class ModelSpec:
    alias: str
    litellm_model: str
    display_name: str
    api_key_env: str | None = None
    api_base: str | None = None
    api_base_env: str | None = None
    expose_in_opencode: bool = True


@dataclass(frozen=True)
class FallbackRule:
    alias: str
    fallbacks: tuple[str, ...]


@dataclass(frozen=True)
class CapabilityDetail:
    key: str
    label: str
    answers: tuple[tuple[str, str], ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ProjectContext:
    preset: str = "generic"
    stack: str = "Projeto generico"
    summary: str = ""
    notes: tuple[str, ...] = field(default_factory=tuple)
    capabilities: tuple[CapabilityDetail, ...] = field(default_factory=tuple)
    role_models: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    commands: tuple[str, ...] = field(default_factory=tuple)
    constraints: tuple[str, ...] = field(default_factory=tuple)
    conventions: tuple[str, ...] = field(default_factory=tuple)
    risks: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class InitOptions:
    litellm_url: str = "http://localhost:4000/v1"
    litellm_port: int = 4000
    enable_chatgpt: bool = True
    enable_frontend_agent: bool = True
    enable_backend_agent: bool | None = None

    # OpenCode Go gateway (https://opencode.ai/docs/pt-br/go/)
    # Defaults vem do registry (src/opencode_buddy/model_registry.yaml).
    opencode_go_api_base: str = field(
        default_factory=lambda: _registry_api_base("opencode-go", "https://opencode.ai/zen/go/v1")
    )
    go_kimi_model: str = field(default_factory=lambda: _registry_model_id("opencode-go", "frontend", "kimi-k2.6"))
    go_deepseek_fast_model: str = field(
        default_factory=lambda: _registry_model_id("opencode-go", "build", "deepseek-v4-flash")
    )
    go_heavy_fallback_model: str = field(
        default_factory=lambda: _registry_model_id("opencode-go", "deep", "qwen3.6-plus")
    )

    # DeepSeek direct API (fallback para fast, primary para deep)
    deepseek_fast_direct_model: str = field(
        default_factory=lambda: _registry_litellm_model("deepseek", "build", "deepseek/deepseek-chat")
    )
    deepseek_pro_direct_model: str = field(
        default_factory=lambda: _registry_litellm_model("deepseek", "deep", "deepseek/deepseek-reasoner")
    )

    routing_strategy: str = "simple-shuffle"
    build_model: str = "litellm/deepseek-fast"
    frontend_model: str = "litellm/kimi"
    backend_model: str = "chatgpt/gpt-5.5"
    default_model: str = "litellm/deepseek-fast"
    deep_model: str = "litellm/deepseek-pro"
    drop_params: tuple[str, ...] = field(default_factory=lambda: ("reasoningSummary",))
    extra_agents: tuple[AgentSpec, ...] = field(default_factory=tuple)
    model_specs: tuple[ModelSpec, ...] = field(default_factory=tuple)
    fallback_rules: tuple[FallbackRule, ...] = field(default_factory=tuple)
    project_context: ProjectContext = field(default_factory=lambda: _default_project_context())


def backend_agent_enabled(opts: InitOptions) -> bool:
    if opts.enable_backend_agent is not None:
        return opts.enable_backend_agent
    return opts.enable_chatgpt


def oauth_providers_used(opts: InitOptions) -> tuple[OAuthProviderEntry, ...]:
    """Retorna os providers OAuth que os agents do projeto usam."""
    registry = load_registry()
    used_models = {spec.model for spec in iter_agent_specs(opts)}
    matched: list[OAuthProviderEntry] = []
    for provider in registry.oauth_providers:
        if any(model.litellm_model in used_models for model in provider.models):
            matched.append(provider)
    return tuple(matched)


def uses_chatgpt_oauth(opts: InitOptions) -> bool:
    return any(provider.key == "chatgpt" for provider in oauth_providers_used(opts))


def uses_any_oauth(opts: InitOptions) -> bool:
    return bool(oauth_providers_used(opts))


def iter_agent_specs(opts: InitOptions) -> tuple[AgentSpec, ...]:
    specs = [
        AgentSpec(
            name="build",
            description="Orquestrador: classifica pedido e delega ao subagent certo",
            model=opts.build_model,
            prompt_file="orchestrator.md",
            template_file="orchestrator.md",
        ),
    ]

    if opts.enable_frontend_agent:
        specs.append(
            AgentSpec(
                name="frontend",
                description="UI/UX, React, CSS, componentes visuais",
                model=opts.frontend_model,
                prompt_file="frontend.md",
                template_file="frontend.md",
            )
        )

    if backend_agent_enabled(opts):
        specs.append(
            AgentSpec(
                name="backend",
                description="APIs, banco, auth, infraestrutura server-side",
                model=opts.backend_model,
                prompt_file="backend.md",
                template_file="backend.md",
            )
        )

    specs.extend(
        [
            AgentSpec(
                name="default",
                description="Tarefas gerais rápidas: refactor pequeno, leitura, perguntas",
                model=opts.default_model,
                prompt_file="default.md",
                template_file="default.md",
            ),
            AgentSpec(
                name="deep",
                description="Raciocínio pesado: arquitetura, debug complexo, planejamento longo",
                model=opts.deep_model,
                prompt_file="deep.md",
                template_file="deep.md",
            ),
        ]
    )

    specs.extend(opts.extra_agents)
    return tuple(specs)


def default_model_specs(opts: InitOptions) -> tuple[ModelSpec, ...]:
    return (
        ModelSpec(
            alias="deepseek-fast",
            litellm_model=f"openai/{opts.go_deepseek_fast_model}",
            display_name="DeepSeek V4 Flash (Go -> direto)",
            api_key_env="OPENCODE_GO_API_KEY",
            api_base=opts.opencode_go_api_base,
        ),
        ModelSpec(
            alias="deepseek-fast-fallback",
            litellm_model=opts.deepseek_fast_direct_model,
            display_name="DeepSeek Chat direto",
            api_key_env="DEEPSEEK_API_KEY",
            expose_in_opencode=False,
        ),
        ModelSpec(
            alias="deepseek-pro",
            litellm_model=opts.deepseek_pro_direct_model,
            display_name="DeepSeek Reasoner (direto -> Qwen3.6 Go)",
            api_key_env="DEEPSEEK_API_KEY",
        ),
        ModelSpec(
            alias="deepseek-pro-fallback",
            litellm_model=f"openai/{opts.go_heavy_fallback_model}",
            display_name="Qwen3.6 Plus (Go)",
            api_key_env="OPENCODE_GO_API_KEY",
            api_base=opts.opencode_go_api_base,
            expose_in_opencode=False,
        ),
        ModelSpec(
            alias="kimi",
            litellm_model=f"openai/{opts.go_kimi_model}",
            display_name="Kimi K2.6 (Go)",
            api_key_env="OPENCODE_GO_API_KEY",
            api_base=opts.opencode_go_api_base,
        ),
    )


def default_fallback_rules() -> tuple[FallbackRule, ...]:
    return (
        FallbackRule("deepseek-fast", ("deepseek-fast-fallback",)),
        FallbackRule("deepseek-pro", ("deepseek-pro-fallback",)),
    )


def iter_model_specs(opts: InitOptions) -> tuple[ModelSpec, ...]:
    return opts.model_specs or default_model_specs(opts)


def iter_fallback_rules(opts: InitOptions) -> tuple[FallbackRule, ...]:
    if opts.model_specs:
        return opts.fallback_rules
    return opts.fallback_rules or default_fallback_rules()


def build_custom_agent_prompt(spec: AgentSpec) -> str:
    return f"""Você é o agente `{spec.name}`.

Missão:

- {spec.description}

Modelo configurado: `{spec.model}`.

Comportamento:

- **Antes de agir**, leia `.opencode/project.md` se existir. Respeite `Capacidades selecionadas`, `Convencoes` e `Restricoes` - elas tem precedencia sobre defaults.
- Trabalhe dentro do escopo da sua missão.
- Se a tarefa depender claramente de outro domínio, explique o bloqueio e peça reroteamento ao orquestrador.
- Prefira mudanças pequenas, verificáveis e alinhadas ao padrão do projeto atual.
"""


def build_orchestrator_prompt(opts: InitOptions) -> str:
    backend_target = "@backend" if backend_agent_enabled(opts) else "@deep"
    frontend_rule = (
        "- Pedido sobre UI, componente visual, CSS, React/Vue/Svelte, layout, design system, animação, acessibilidade visual -> `task` em `@frontend`\n"
        if opts.enable_frontend_agent
        else ""
    )
    extra_rules = [
        f"- Pedido que combine claramente com \"{spec.description}\" -> `task` em `@{spec.name}`"
        for spec in opts.extra_agents
    ]
    custom_section = "\n".join(extra_rules)
    if custom_section:
        custom_section = f"\nAgents customizados:\n\n{custom_section}\n"

    return f"""Você é o orquestrador. Seu único trabalho é classificar o pedido do usuário e delegar via tool `task` ao subagent correto.

Contexto:

- **Sempre** consulte `.opencode/project.md` antes de delegar. As secoes `Capacidades selecionadas` e `Modelos por papel` te dizem quais subagents existem e o que cada um cobre.

Regras de roteamento:

{frontend_rule}- Pedido sobre API, banco de dados, auth, microsserviço, fila, infraestrutura server-side, integração externa -> `task` em `{backend_target}`
- Pedido sobre arquitetura, decisão técnica complexa, debug profundo, planejamento longo, refactor amplo -> `task` em `@deep`
{custom_section}
- Resto (perguntas curtas, refactor trivial, listagens, leitura simples, dúvidas conceituais) -> `task` em `@default`

Comportamento:

1. NUNCA execute a tarefa diretamente - sempre delegue.
2. Se o domínio for ambíguo, faça UMA pergunta curta de clarificação antes de delegar.
3. Após o subagent retornar, repasse o resultado ao usuário sem reescrever - você é só o roteador.
4. Se o usuário invocar manualmente `/agent <nome>`, respeite a escolha dele e não interfira.
"""


def build_project_context(opts: InitOptions) -> str:
    ctx = opts.project_context
    lines: list[str] = ["# Contexto do projeto", ""]

    if ctx.summary:
        lines.append("## Visao geral")
        lines.append("")
        lines.append(ctx.summary)
        lines.append("")

    lines.append("## Stack")
    lines.append("")
    lines.append(f"- Preset: {ctx.preset}")
    lines.append(f"- Capacidades: {ctx.stack}")
    lines.append("")

    if ctx.capabilities:
        lines.append("## Capacidades selecionadas")
        lines.append("")
        for capability in ctx.capabilities:
            lines.append(f"### {capability.label}")
            if capability.answers:
                for key, value in capability.answers:
                    lines.append(f"- {key}: {value}")
            else:
                lines.append("- (sem detalhes adicionais)")
            lines.append("")

    if ctx.role_models:
        lines.append("## Modelos por papel")
        lines.append("")
        for role, model in ctx.role_models:
            lines.append(f"- {role}: {model}")
        lines.append("")

    if ctx.commands:
        lines.append("## Comandos uteis")
        lines.append("")
        for command in ctx.commands:
            lines.append(f"- `{command}`")
        lines.append("")

    if ctx.conventions:
        lines.append("## Convencoes")
        lines.append("")
        for convention in ctx.conventions:
            lines.append(f"- {convention}")
        lines.append("")

    if ctx.constraints:
        lines.append("## Restricoes")
        lines.append("")
        for constraint in ctx.constraints:
            lines.append(f"- {constraint}")
        lines.append("")

    if ctx.risks:
        lines.append("## Riscos e pontos de atencao")
        lines.append("")
        for risk in ctx.risks:
            lines.append(f"- {risk}")
        lines.append("")

    if ctx.notes:
        lines.append("## Notas do scaffold")
        lines.append("")
        for note in ctx.notes:
            lines.append(f"- {note}")
        lines.append("")

    lines.append(
        "Use este arquivo como fonte de preferencias do projeto ao decidir implementacao, bibliotecas e trade-offs."
    )
    return "\n".join(lines).rstrip() + "\n"


def default_conventions() -> tuple[str, ...]:
    return (
        "Priorizar mudancas pequenas e testaveis.",
        "Nunca incluir secrets no repositorio (.env protegido pelo .gitignore).",
        "Preferir bibliotecas maduras para auth, parsing, audio, video e crypto.",
        "Validar entrada apenas em fronteiras do sistema; confiar em codigo interno.",
    )


def default_constraints() -> tuple[str, ...]:
    return (
        "Modelos LiteLLM passam pelo proxy local em http://localhost:4000.",
        "Modelos OAuth (chatgpt/...) NAO passam pelo LiteLLM - sao chamados direto pelo OpenCode.",
        ".env nunca deve ser commitado; usar `.env.example` como template.",
    )


def default_risks() -> tuple[str, ...]:
    return (
        "OpenCode Go pode mudar nomes de modelos sem aviso - validar com `opencode-buddy keys validate`.",
        "Custos estimados (cost_label) sao indicativos, nao precos exatos.",
        "Live discovery pode falhar offline; sempre ha fallback para sugestoes do registry.",
    )


def default_commands() -> tuple[str, ...]:
    return (
        "opencode-buddy validate .",
        "opencode-buddy keys validate",
        ".\\start-proxy.ps1",
        "opencode",
    )


def _default_project_context() -> ProjectContext:
    return ProjectContext(
        commands=default_commands(),
        conventions=default_conventions(),
        constraints=default_constraints(),
        risks=default_risks(),
    )


def build_opencode_config(opts: InitOptions) -> dict:
    agents = {
        spec.name: {
            "description": spec.description,
            "model": spec.model,
            "prompt": spec.prompt_ref,
        }
        for spec in iter_agent_specs(opts)
    }
    models = {
        spec.alias: {"name": spec.display_name}
        for spec in iter_model_specs(opts)
        if spec.expose_in_opencode
    }

    return {
        "$schema": "https://opencode.ai/config.json",
        "provider": {
            "litellm": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "LiteLLM Proxy",
                "options": {
                    "baseURL": opts.litellm_url,
                    "apiKey": "{env:LITELLM_MASTER_KEY}",
                },
                "models": models,
            }
        },
        "agent": agents,
        "model": opts.default_model,
    }


def build_litellm_config(opts: InitOptions) -> dict:
    model_list = []
    for spec in iter_model_specs(opts):
        params = {
            "model": spec.litellm_model,
            "drop_params": list(opts.drop_params),
        }
        if spec.api_key_env:
            params["api_key"] = f"os.environ/{spec.api_key_env}"
        if spec.api_base:
            params["api_base"] = spec.api_base
        elif spec.api_base_env:
            params["api_base"] = f"os.environ/{spec.api_base_env}"
        model_list.append({"model_name": spec.alias, "litellm_params": params})

    router_settings = {"routing_strategy": opts.routing_strategy}
    fallback_rules = iter_fallback_rules(opts)
    if fallback_rules:
        router_settings["fallbacks"] = [{rule.alias: list(rule.fallbacks)} for rule in fallback_rules]

    return {
        "model_list": model_list,
        "router_settings": router_settings,
        "general_settings": {
            "master_key": "os.environ/LITELLM_MASTER_KEY",
        },
    }


def build_gitignore() -> str:
    return """\
# Secrets
.env
.env.*
!.env.example

# Logs e cache
*.log
.litellm/
__pycache__/
.pytest_cache/

# Builds
node_modules/
dist/
build/
"""


def build_start_proxy_script(opts: InitOptions) -> str:
    """PowerShell helper: carrega .env, força UTF-8 (bug Windows do banner LiteLLM), sobe proxy."""
    return f"""# start-proxy.ps1 - sobe LiteLLM com .env carregado
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
    env_vars = _collect_env_vars(opts)
    lines = [
        "# LiteLLM proxy (gere uma string aleatória, ex: openssl rand -hex 24)",
        "LITELLM_MASTER_KEY=sk-CHANGE-ME",
        "",
    ]

    for env_var in env_vars:
        lines.extend(_env_var_block(env_var))
        lines.append("")

    oauth = oauth_providers_used(opts)
    if oauth:
        for provider in oauth:
            lines.append(f"# Nota: {provider.name} usa OAuth - nenhuma chave aqui")
        lines.append("# Verifique sessoes ativas com: opencode auth list")
        lines.append("# Faça login (uma vez por provider) com: opencode auth login")
    return "\n".join(lines).rstrip() + "\n"


def _collect_env_vars(opts: InitOptions) -> tuple[str, ...]:
    names: list[str] = []
    for spec in iter_model_specs(opts):
        if spec.api_key_env:
            names.append(spec.api_key_env)
        if spec.api_base_env:
            names.append(spec.api_base_env)
    return tuple(dict.fromkeys(names))


def _env_var_block(env_var: str) -> list[str]:
    hints = {
        "OPENCODE_GO_API_KEY": [
            "# OpenCode Go (https://opencode.ai/auth - subscription $10/mês)",
            "# Fornece modelos via gateway OpenCode Go.",
            "OPENCODE_GO_API_KEY=",
        ],
        "DEEPSEEK_API_KEY": [
            "# DeepSeek direto (https://platform.deepseek.com/api_keys)",
            "DEEPSEEK_API_KEY=",
        ],
        "MOONSHOT_API_KEY": [
            "# Moonshot/Kimi direto (https://platform.moonshot.ai)",
            "MOONSHOT_API_KEY=",
        ],
        "ANTHROPIC_API_KEY": [
            "# Anthropic Claude (https://console.anthropic.com)",
            "ANTHROPIC_API_KEY=",
        ],
        "GEMINI_API_KEY": [
            "# Google Gemini (https://aistudio.google.com/apikey)",
            "GEMINI_API_KEY=",
        ],
        "COMMANDCODE_API_KEY": [
            "# CommandCode ou endpoint OpenAI-compatible equivalente",
            "COMMANDCODE_API_KEY=",
        ],
        "COMMANDCODE_API_BASE": [
            "# Base URL do endpoint CommandCode/OpenAI-compatible",
            "COMMANDCODE_API_BASE=",
        ],
    }
    return hints.get(env_var, [f"# Valor usado por modelos LiteLLM ({env_var})", f"{env_var}="])
