import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import typer

from opencode_buddy.config_builder import (
    AgentSpec,
    CapabilityDetail,
    InitOptions,
    ModelSpec,
    ProjectContext,
    default_commands,
    default_constraints,
    default_conventions,
    default_risks,
)
from opencode_buddy.model_catalog import AvailableModel, build_model_catalog, choices_for_role, load_env_sources


@dataclass(frozen=True)
class SubQuestion:
    key: str
    label: str
    choices: tuple[str, ...]
    default: str | None = None
    allow_custom: bool = True


@dataclass(frozen=True)
class Capability:
    key: str
    label: str
    description: str
    default: bool = False
    agent_name: str | None = None
    subquestions: tuple[SubQuestion, ...] = field(default_factory=tuple)


ROLE_LABELS = {
    "build": "orquestrador/classificador",
    "frontend": "frontend/UI",
    "backend": "backend/API",
    "audio": "audio/speech",
    "video": "video/multimodal",
    "default": "tarefas rapidas/default",
    "deep": "raciocinio pesado/deep",
}

AGENT_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
YES_WORDS = {"s", "sim", "y", "yes"}
NO_WORDS = {"n", "nao", "não", "no"}

CREATE_BANNER = """
 ▒█████  ██▓███ ▓█████ ███▄    █ ▄████▄  ▒█████ ▓█████▄▓█████
▒██▒  ██▓██░  ██▓█   ▀ ██ ▀█   █▒██▀ ▀█ ▒██▒  ██▒██▀ ██▓█   ▀
▒██░  ██▓██░ ██▓▒███  ▓██  ▀█ ██▒▓█    ▄▒██░  ██░██   █▒███
▒██   ██▒██▄█▓▒ ▒▓█  ▄▓██▒  ▐▌██▒▓▓▄ ▄██▒██   ██░▓█▄   ▒▓█  ▄
░ ████▓▒▒██▒ ░  ░▒████▒██░   ▓██▒ ▓███▀ ░ ████▓▒░▒████▓░▒████▒
░ ▒░▒░▒░▒▓▒░ ░  ░░ ▒░ ░ ▒░   ▒ ▒░ ░▒ ▒  ░ ▒░▒░▒░ ▒▒▓  ▒░░ ▒░ ░
  ░ ▒ ▒░░▒ ░     ░ ░  ░ ░░   ░ ▒░ ░  ▒    ░ ▒ ▒░ ░ ▒  ▒ ░ ░  ░
░ ░ ░ ▒ ░░         ░     ░   ░ ░░       ░ ░ ░ ▒  ░ ░  ░   ░
    ░ ░            ░  ░        ░░ ░         ░ ░    ░      ░  ░
                                ░                ░
 ▄▄▄▄   █    ██▓█████▄▓█████▓██   ██▓ ▐██▌
▓█████▄ ██  ▓██▒██▀ ██▒██▀ ██▒██  ██▒ ▐██▌
▒██▒ ▄█▓██  ▒██░██   █░██   █▌▒██ ██░ ▐██▌
▒██░█▀ ▓▓█  ░██░▓█▄   ░▓█▄   ▌░ ▐██▓░ ▓██▒
░▓█  ▀█▒▒█████▓░▒████▓░▒████▓ ░ ██▒▓░ ▒▄▄
░▒▓███▀░▒▓▒ ▒ ▒ ▒▒▓  ▒ ▒▒▓  ▒  ██▒▒▒  ░▀▀▒
▒░▒   ░░░▒░ ░ ░ ░ ▒  ▒ ░ ▒  ▒▓██ ░▒░  ░  ░
 ░    ░ ░░░ ░ ░ ░ ░  ░ ░ ░  ░▒ ▒ ░░      ░
 ░        ░       ░      ░   ░ ░      ░
      ░         ░      ░     ░ ░
"""

CAPABILITIES = (
    Capability(
        key="frontend",
        label="Frontend/UI",
        agent_name="frontend",
        description="UI/UX, componentes visuais, CSS, acessibilidade e apps web",
        default=True,
        subquestions=(
            SubQuestion(
                key="framework",
                label="Framework principal",
                choices=("React", "Vue", "Svelte", "Solid", "Nuxt", "Nenhum/vanilla"),
                default="React",
            ),
            SubQuestion(
                key="typescript",
                label="Usa TypeScript?",
                choices=("Sim", "Nao"),
                default="Sim",
                allow_custom=False,
            ),
            SubQuestion(
                key="styling",
                label="Estilizacao",
                choices=("Tailwind", "CSS Modules", "CSS puro", "Design system existente"),
                default="Tailwind",
            ),
        ),
    ),
    Capability(
        key="backend",
        label="Backend/API",
        agent_name="backend",
        description="APIs, banco, auth, filas, integrações server-side e infraestrutura",
        default=True,
        subquestions=(
            SubQuestion(
                key="runtime",
                label="Runtime principal",
                choices=("Node", "Python", "Go", "Rust", "Java/Kotlin"),
                default="Python",
            ),
            SubQuestion(
                key="api_style",
                label="Estilo de API",
                choices=("REST", "GraphQL", "gRPC", "Webhooks", "Misto"),
                default="REST",
            ),
            SubQuestion(
                key="database",
                label="Banco principal",
                choices=("Postgres", "MySQL", "SQLite", "MongoDB", "Nenhum"),
                default="Postgres",
            ),
            SubQuestion(
                key="auth",
                label="Autenticacao",
                choices=("OAuth/OIDC", "JWT", "Session", "Nenhuma"),
                default="JWT",
            ),
        ),
    ),
    Capability(
        key="audio",
        label="Audio/speech",
        agent_name="audio",
        description="Captura, transcrição, tradução, TTS, diarização e pipelines de áudio",
        default=False,
        subquestions=(
            SubQuestion(
                key="tasks",
                label="Tarefas principais",
                choices=("Transcricao", "Traducao", "TTS", "Diarizacao", "Captura tempo real"),
                default="Transcricao",
            ),
            SubQuestion(
                key="input",
                label="Entrada de audio",
                choices=("Microfone", "Arquivo", "Streaming"),
                default="Arquivo",
            ),
            SubQuestion(
                key="language",
                label="Idioma principal",
                choices=("pt-BR", "en-US", "Multilingual"),
                default="pt-BR",
            ),
        ),
    ),
    Capability(
        key="video",
        label="Video/multimodal",
        agent_name="video",
        description="Frames, análise visual, legendas, multimodalidade e pipelines de vídeo",
        default=False,
        subquestions=(
            SubQuestion(
                key="tasks",
                label="Tarefas principais",
                choices=("Frames", "Legendas", "Analise visual", "Multimodal"),
                default="Analise visual",
            ),
            SubQuestion(
                key="input",
                label="Entrada de video",
                choices=("Arquivo", "Camera", "Streaming"),
                default="Arquivo",
            ),
        ),
    ),
    Capability(
        key="mobile",
        label="Mobile",
        description="Apps iOS/Android nativos ou cross-platform",
        subquestions=(
            SubQuestion(
                key="platform",
                label="Plataformas",
                choices=("iOS+Android", "iOS", "Android"),
                default="iOS+Android",
            ),
            SubQuestion(
                key="framework",
                label="Framework",
                choices=("React Native", "Flutter", "Swift/Kotlin nativo", "Capacitor/Ionic"),
                default="React Native",
            ),
        ),
    ),
    Capability(
        key="cli",
        label="CLI/tooling",
        description="Ferramentas de linha de comando, scripts, automacao",
        subquestions=(
            SubQuestion(
                key="language",
                label="Linguagem",
                choices=("Python", "Go", "Rust", "Node", "Bash"),
                default="Python",
            ),
            SubQuestion(
                key="distribution",
                label="Distribuicao",
                choices=("pipx/uv tool", "npm global", "homebrew", "binario standalone"),
                default="pipx/uv tool",
            ),
        ),
    ),
    Capability(
        key="desktop",
        label="Desktop",
        description="Apps desktop (Windows/macOS/Linux)",
        subquestions=(
            SubQuestion(
                key="framework",
                label="Framework",
                choices=("Electron", "Tauri", "Qt", "Nativo per OS"),
                default="Tauri",
            ),
        ),
    ),
    Capability(
        key="data",
        label="Data/ETL",
        description="Pipelines de dados, ETL, ingestao, transformacao",
        subquestions=(
            SubQuestion(
                key="pipeline",
                label="Orquestrador",
                choices=("Airflow", "Prefect", "Dagster", "Cron simples", "Nenhum"),
                default="Cron simples",
            ),
            SubQuestion(
                key="warehouse",
                label="Destino dos dados",
                choices=("Postgres", "BigQuery", "Snowflake", "DuckDB", "S3/parquet"),
                default="Postgres",
            ),
        ),
    ),
    Capability(
        key="ml",
        label="ML/AI",
        description="Treinamento, inferencia, prompts, RAG, fine-tuning",
        subquestions=(
            SubQuestion(
                key="task",
                label="Tarefa principal",
                choices=("RAG/busca", "Classificacao", "Geracao", "Fine-tuning", "Inferencia LLM"),
                default="RAG/busca",
            ),
            SubQuestion(
                key="stack",
                label="Stack",
                choices=("PyTorch", "scikit-learn", "Hugging Face", "LangChain/LlamaIndex", "Custom"),
                default="Hugging Face",
            ),
        ),
    ),
    Capability(
        key="devops",
        label="DevOps/infra",
        description="CI/CD, IaC, observabilidade, deploys",
        subquestions=(
            SubQuestion(
                key="cloud",
                label="Cloud principal",
                choices=("AWS", "GCP", "Azure", "Self-hosted", "Nenhuma"),
                default="AWS",
            ),
            SubQuestion(
                key="iac",
                label="Infrastructure as Code",
                choices=("Terraform", "Pulumi", "CloudFormation", "Ansible", "Nenhum"),
                default="Terraform",
            ),
        ),
    ),
    Capability(
        key="qa",
        label="QA/testes",
        description="Estrategia de testes (unit, integration, e2e), automacao",
        subquestions=(
            SubQuestion(
                key="strategy",
                label="Estrategia",
                choices=("Pyramid (unit-heavy)", "Diamond (integration-heavy)", "E2E-only", "Smoke + manual"),
                default="Pyramid (unit-heavy)",
            ),
            SubQuestion(
                key="e2e",
                label="Ferramenta E2E",
                choices=("Playwright", "Cypress", "Selenium", "Nenhuma"),
                default="Playwright",
            ),
        ),
    ),
    Capability(
        key="docs",
        label="Documentacao",
        description="Docs publicas, API reference, tutorials",
        subquestions=(
            SubQuestion(
                key="generator",
                label="Gerador",
                choices=("MkDocs", "Docusaurus", "Sphinx", "VitePress", "README so"),
                default="MkDocs",
            ),
        ),
    ),
    Capability(
        key="security",
        label="Security",
        description="Auditoria, threat modeling, hardening, compliance",
        subquestions=(
            SubQuestion(
                key="focus",
                label="Foco",
                choices=("AppSec/OWASP", "Cloud security", "Compliance (SOC2/ISO)", "Pentest interno"),
                default="AppSec/OWASP",
            ),
        ),
    ),
    Capability(
        key="integrations",
        label="Integracoes externas",
        description="Webhooks, APIs de terceiros, SSO, pagamentos",
        subquestions=(
            SubQuestion(
                key="kind",
                label="Tipo principal",
                choices=("Pagamentos", "SSO/Auth", "Webhooks/eventos", "Email/SMS", "CRM/ERP"),
                default="Webhooks/eventos",
            ),
        ),
    ),
)


def render_create_banner() -> str:
    return f"{CREATE_BANNER.strip()}\n\nOpenCode Buddy create"


def ensure_utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


def print_create_banner() -> None:
    ensure_utf8_output()
    colors = (
        typer.colors.RED,
        typer.colors.BRIGHT_RED,
        typer.colors.MAGENTA,
        typer.colors.RED,
    )
    for index, line in enumerate(CREATE_BANNER.strip("\n").splitlines()):
        typer.secho(line, fg=colors[index % len(colors)], bold=index < 5)
    typer.echo("")
    typer.secho("OpenCode Buddy create", fg=typer.colors.CYAN, bold=True)


def run_create_wizard(
    default_path: str | None = None,
    *,
    prepare_env: Callable[[str], dict[str, str]] | None = None,
) -> tuple[str, InitOptions]:
    print_create_banner()
    typer.secho("Vamos montar o projeto em poucos passos.\n", fg=typer.colors.WHITE, bold=True)

    target = typer.prompt("Pasta do projeto", default=default_path or "my-opencode-project")
    selected_capabilities = _ask_capabilities()
    capability_answers = _ask_subquestions(selected_capabilities)

    env = prepare_env(target) if prepare_env is not None else load_env_sources(Path(target).resolve())
    detected = tuple(name for name in sorted(env) if name.endswith("_API_KEY") and env.get(name))
    if detected:
        typer.echo("")
        typer.echo(
            typer.style("Chaves detectadas: ", fg=typer.colors.CYAN, bold=True)
            + ", ".join(typer.style(name, fg=typer.colors.GREEN) for name in detected)
        )
    else:
        typer.echo("")
        typer.secho("Nenhuma chave de provider detectada no ambiente ou .env local.", fg=typer.colors.YELLOW)

    live = bool(detected) and _confirm("Consultar modelos disponíveis nos providers detectados agora?", default=True)
    catalog = build_model_catalog(env, live=live)
    for note in catalog.discovery_notes:
        typer.secho(f"  {note}", fg=typer.colors.BLUE)

    roles = _roles_for_capabilities(selected_capabilities)
    selections = {role: _choose_model(role, choices_for_role(catalog.models, role)) for role in roles}

    extra = typer.prompt(
        "Agents extras (nome=modelo[:descricao], separados por virgula)",
        default="",
        show_default=False,
    )
    user_extra_agents = tuple(_parse_extra_agents(extra))
    opts = build_options_from_selections(
        capabilities=selected_capabilities,
        selections=selections,
        user_extra_agents=user_extra_agents,
        detected_env=catalog.detected_env,
        discovery_notes=catalog.discovery_notes,
        capability_answers=capability_answers,
    )

    _print_summary(target, opts, selections)
    if not _confirm("Gerar projeto?", default=True):
        raise typer.Exit(1)
    return target, opts


def build_options_from_selections(
    *,
    capabilities: dict[str, bool],
    selections: dict[str, AvailableModel],
    user_extra_agents: tuple[AgentSpec, ...] = (),
    detected_env: tuple[str, ...] = (),
    discovery_notes: tuple[str, ...] = (),
    capability_answers: dict[str, dict[str, str]] | None = None,
) -> InitOptions:
    capability_answers = capability_answers or {}
    specs: list[ModelSpec] = []
    role_models: dict[str, str] = {}

    for role, model in selections.items():
        if model.transport == "OAuth":
            role_models[role] = model.litellm_model
            continue
        alias = f"{role}-model"
        specs.append(_model_spec_from_available(alias, model))
        role_models[role] = f"litellm/{alias}"

    generated_agents = _extra_agents_for_capabilities(capabilities, role_models)
    all_extra_agents = generated_agents + user_extra_agents

    notes = [
        "Gerado pelo wizard interativo `opencode-buddy create`.",
    ]
    for cap_key, answers in capability_answers.items():
        if not answers:
            continue
        cap = next((c for c in CAPABILITIES if c.key == cap_key), None)
        cap_label = cap.label if cap else cap_key
        rendered = ", ".join(f"{key}={value}" for key, value in answers.items())
        notes.append(f"{cap_label}: {rendered}")
    if detected_env:
        notes.append("Chaves detectadas durante criação: " + ", ".join(detected_env))
    notes.extend(discovery_notes)

    capability_details = tuple(
        CapabilityDetail(
            key=cap.key,
            label=cap.label,
            answers=tuple((q.key, capability_answers.get(cap.key, {}).get(q.key, "")) for q in cap.subquestions),
        )
        for cap in CAPABILITIES
        if capabilities.get(cap.key)
    )

    role_models_list: list[tuple[str, str]] = []
    for role, model in selections.items():
        role_label = ROLE_LABELS.get(role, role)
        role_models_list.append((role_label, f"{model.provider} - {model.model_id}"))

    summary = _build_summary_text(capabilities, capability_answers)

    return InitOptions(
        enable_chatgpt=any(model.transport == "OAuth" for model in selections.values()),
        enable_frontend_agent=capabilities.get("frontend", False),
        enable_backend_agent=capabilities.get("backend", False),
        build_model=role_models.get("build", "litellm/build-model"),
        frontend_model=role_models.get("frontend", "litellm/frontend-model"),
        backend_model=role_models.get("backend", "litellm/backend-model"),
        default_model=role_models.get("default", "litellm/default-model"),
        deep_model=role_models.get("deep", "litellm/deep-model"),
        extra_agents=all_extra_agents,
        model_specs=tuple(specs),
        project_context=ProjectContext(
            preset="custom",
            stack=_stack_label(capabilities),
            summary=summary,
            notes=tuple(notes),
            capabilities=capability_details,
            role_models=tuple(role_models_list),
            commands=default_commands(),
            conventions=default_conventions(),
            constraints=default_constraints(),
            risks=default_risks(),
        ),
    )


def _build_summary_text(capabilities: dict[str, bool], answers: dict[str, dict[str, str]]) -> str:
    selected_labels = [cap.label for cap in CAPABILITIES if capabilities.get(cap.key)]
    if not selected_labels:
        return "Projeto OpenCode generico, sem capacidades extras selecionadas."
    head = "Projeto OpenCode com capacidades: " + ", ".join(selected_labels) + "."
    highlights: list[str] = []
    for cap in CAPABILITIES:
        if not capabilities.get(cap.key):
            continue
        cap_answers = answers.get(cap.key) or {}
        if not cap_answers:
            continue
        first_answer_value = next(iter(cap_answers.values()))
        highlights.append(f"{cap.label}: {first_answer_value}")
    if highlights:
        return head + " " + "; ".join(highlights) + "."
    return head


def _model_spec_from_available(alias: str, model: AvailableModel) -> ModelSpec:
    return ModelSpec(
        alias=alias,
        litellm_model=model.litellm_model,
        display_name=f"{ROLE_LABELS.get(alias.removesuffix('-model'), alias)} - {model.display_name}",
        api_key_env=model.api_key_env,
        api_base=model.api_base,
        api_base_env=model.api_base_env,
    )


def _ask_capabilities() -> dict[str, bool]:
    typer.secho("Capacidades do projeto", fg=typer.colors.CYAN, bold=True)
    typer.secho(
        "Selecione todas que se aplicam (separadas por virgula). Apenas as capacidades selecionadas",
        fg=typer.colors.WHITE,
    )
    typer.secho("vao gerar subperguntas e contexto.", fg=typer.colors.WHITE)
    typer.echo("")
    for index, capability in enumerate(CAPABILITIES, start=1):
        number = typer.style(str(index), fg=typer.colors.YELLOW, bold=True)
        agent_marker = " [agent dedicado]" if capability.agent_name else ""
        typer.echo(f"  {number}. {capability.label}{agent_marker} - {capability.description}")
    typer.echo("  " + typer.style("0", fg=typer.colors.YELLOW, bold=True) + ". Nenhuma dessas")

    while True:
        raw = typer.prompt("Escolha uma ou mais opções (ex: 1,2,4)", default="", show_default=False)
        try:
            selected_indexes = _parse_multi_select(raw, max_value=len(CAPABILITIES))
        except ValueError as exc:
            typer.secho(str(exc), fg=typer.colors.RED)
            continue
        selected = {capability.key: False for capability in CAPABILITIES}
        for index in selected_indexes:
            selected[CAPABILITIES[index - 1].key] = True
        break
    typer.echo("")
    return selected


def _ask_subquestions(capabilities: dict[str, bool]) -> dict[str, dict[str, str]]:
    answers: dict[str, dict[str, str]] = {}
    selected = [cap for cap in CAPABILITIES if capabilities.get(cap.key) and cap.subquestions]
    if not selected:
        return answers

    typer.secho("Subperguntas por capacidade", fg=typer.colors.CYAN, bold=True)
    typer.secho("Pressione Enter para aceitar o default.", fg=typer.colors.WHITE)
    typer.echo("")

    for cap in selected:
        typer.secho(f"== {cap.label} ==", fg=typer.colors.MAGENTA, bold=True)
        cap_answers: dict[str, str] = {}
        for question in cap.subquestions:
            cap_answers[question.key] = _ask_subquestion(question)
        answers[cap.key] = cap_answers
        typer.echo("")
    return answers


def _ask_subquestion(question: SubQuestion) -> str:
    default_label = question.default or question.choices[0]
    typer.secho(question.label, fg=typer.colors.CYAN)
    for index, choice in enumerate(question.choices, start=1):
        marker = "*" if choice == default_label else " "
        typer.echo(f"  {marker}{typer.style(str(index), fg=typer.colors.YELLOW, bold=True)}. {choice}")
    if question.allow_custom:
        typer.echo(f"   {typer.style('t', fg=typer.colors.YELLOW, bold=True)}. (texto livre)")

    while True:
        raw = typer.prompt("Escolha", default=default_label, show_default=True).strip()
        if not raw:
            return default_label
        if question.allow_custom and raw.lower() == "t":
            free = typer.prompt("Resposta livre", default="").strip()
            if free:
                return free
            return default_label
        if raw.isdigit():
            value = int(raw)
            if 1 <= value <= len(question.choices):
                return question.choices[value - 1]
            typer.secho("Indice fora da lista.", fg=typer.colors.RED)
            continue
        # Texto livre direto: aceita como resposta se permitido, senao tenta match case-insensitive
        if question.allow_custom:
            return raw
        match = next((choice for choice in question.choices if choice.lower() == raw.lower()), None)
        if match:
            return match
        typer.secho("Resposta nao reconhecida.", fg=typer.colors.RED)


def _roles_for_capabilities(capabilities: dict[str, bool]) -> list[str]:
    roles = ["build"]
    for capability in CAPABILITIES:
        if capabilities.get(capability.key) and capability.agent_name:
            roles.append(capability.agent_name)
    roles.extend(["default", "deep"])
    return roles


def _extra_agents_for_capabilities(capabilities: dict[str, bool], role_models: dict[str, str]) -> tuple[AgentSpec, ...]:
    agents = []
    for capability in CAPABILITIES:
        if not capability.agent_name:
            continue
        if capability.key in {"frontend", "backend"}:
            continue
        if capabilities.get(capability.key):
            agents.append(
                AgentSpec(
                    name=capability.agent_name,
                    description=capability.description,
                    model=role_models[capability.agent_name],
                    prompt_file=f"{capability.agent_name}.md",
                )
            )
    return tuple(agents)


def _choose_model(role: str, choices: tuple[AvailableModel, ...]) -> AvailableModel:
    if not choices:
        raise typer.BadParameter("Nenhum modelo disponível para seleção.")

    default_index = next(
        (index for index, model in enumerate(choices, start=1) if model.available and model.is_recommended_for(role)),
        1,
    )
    typer.secho(f"Modelo para {ROLE_LABELS[role]}", fg=typer.colors.CYAN, bold=True)
    for index, model in enumerate(choices, start=1):
        typer.echo(f"  {typer.style(str(index), fg=typer.colors.YELLOW, bold=True)}. {_format_model_choice(model, role)}")

    while True:
        raw = typer.prompt("Escolha", default=str(default_index))
        try:
            selected = choices[int(raw) - 1]
        except (ValueError, IndexError):
            typer.secho("Escolha invalida.", fg=typer.colors.RED)
            continue
        typer.echo("")
        return selected


def _format_model_choice(model: AvailableModel, role: str) -> str:
    provider = typer.style(model.provider, fg=typer.colors.BRIGHT_BLUE, bold=True)
    model_id = typer.style(model.model_id, fg=typer.colors.WHITE, bold=True)
    cost = typer.style(model.cost, fg=typer.colors.MAGENTA)
    transport_color = typer.colors.GREEN if model.transport == "OAuth" else typer.colors.CYAN
    transport = typer.style(model.transport, fg=transport_color, bold=True)
    parts = [provider, model_id, f"custo: {cost}", transport]
    if model.is_recommended_for(role):
        parts.append(typer.style("[Recommended]", fg=typer.colors.GREEN, bold=True))
    if not model.available and model.api_key_env:
        parts.append(typer.style(f"[falta {model.api_key_env}]", fg=typer.colors.RED))
    if model.source == "live":
        parts.append(typer.style("[live]", fg=typer.colors.GREEN))
    return " - ".join(parts)


def _confirm(label: str, *, default: bool) -> bool:
    yes = typer.style("S", fg=typer.colors.GREEN, bold=True)
    no = typer.style("n", fg=typer.colors.RED, bold=True)
    suffix = f"[{yes}/{no}]" if default else f"[{typer.style('s', fg=typer.colors.GREEN, bold=True)}/{typer.style('N', fg=typer.colors.RED, bold=True)}]"
    while True:
        raw = typer.prompt(f"{typer.style(label, fg=typer.colors.WHITE, bold=True)} {suffix}", default="", show_default=False)
        normalized = raw.strip().lower()
        if not normalized:
            return default
        if normalized in YES_WORDS:
            return True
        if normalized in NO_WORDS:
            return False
        typer.secho("Responda com s ou n.", fg=typer.colors.RED)


def _parse_multi_select(raw: str, *, max_value: int) -> tuple[int, ...]:
    normalized = raw.replace(";", ",").replace(" ", ",")
    if not normalized.strip():
        raise ValueError("Escolha pelo menos uma opção ou 0.")
    values: list[int] = []
    for part in [item.strip() for item in normalized.split(",") if item.strip()]:
        if not part.isdigit():
            raise ValueError(f"Opção inválida: {part}")
        value = int(part)
        if value == 0:
            return ()
        if value < 1 or value > max_value:
            raise ValueError(f"Opção fora da lista: {value}")
        if value not in values:
            values.append(value)
    return tuple(values)


def _print_summary(target: str, opts: InitOptions, selections: dict[str, AvailableModel]) -> None:
    typer.echo("")
    typer.secho("Resumo", fg=typer.colors.CYAN, bold=True)
    typer.echo(f"  Pasta: {target}")
    typer.echo(f"  Stack: {opts.project_context.stack}")
    for role, model in selections.items():
        alias = {
            "build": opts.build_model,
            "frontend": opts.frontend_model,
            "backend": opts.backend_model,
            "default": opts.default_model,
            "deep": opts.deep_model,
        }.get(role, f"litellm/{role}-model")
        typer.echo(f"  {role}: {model.provider} - {model.model_id} ({alias})")


def _stack_label(capabilities: dict[str, bool]) -> str:
    enabled = [capability.label for capability in CAPABILITIES if capabilities.get(capability.key)]
    return ", ".join(enabled) if enabled else "Projeto generico"


def _parse_extra_agents(raw: str) -> list[AgentSpec]:
    agents: list[AgentSpec] = []
    for item in [part.strip() for part in raw.split(",") if part.strip()]:
        if "=" not in item:
            raise typer.BadParameter(f"agent extra invalido: {item}")
        name, model_and_description = item.split("=", 1)
        name = name.strip()
        if not AGENT_NAME_RE.fullmatch(name):
            raise typer.BadParameter(f"nome de agent invalido: {name}")
        if ":" in model_and_description:
            model, description = model_and_description.split(":", 1)
        else:
            model, description = model_and_description, f"Agent customizado: {name}"
        agents.append(
            AgentSpec(
                name=name,
                description=description.strip(),
                model=model.strip(),
                prompt_file=f"{name}.md",
            )
        )
    return agents
