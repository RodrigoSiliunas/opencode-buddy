import dataclasses
import json
import re
import sys
from pathlib import Path

import typer

from opencode_buddy.config_builder import (
    AgentSpec,
    CapabilityDetail,
    FallbackRule,
    InitOptions,
    ModelSpec,
    ProjectContext,
)
from opencode_buddy.doctor import format_report, run_doctor
from opencode_buddy.i18n import t
from opencode_buddy.keys_validator import (
    STATE_AUTH_FAILED,
    STATE_MISSING_ENV,
    STATE_NETWORK_FAILED,
    STATE_OK,
    STATE_SKIPPED,
    STATE_UNSUPPORTED,
    ProviderStatus,
    UnknownProviderError,
    has_failures,
    validate_providers,
)
from opencode_buddy.key_setup import (
    has_ok_api_provider,
    run_key_setup_interactive,
    validate_selected_providers,
)
from opencode_buddy.agent_driven import (
    AgentDrivenRequest,
    DEFAULT_PLANNER_TIMEOUT,
    DeterministicPlannerClient,
    LIVE_SUPPORTED_PROVIDERS,
    PlannerError,
    plan_to_jsonable_public,
    plan_to_project_spec,
    propose_plan_with_fallback,
    run_review_loop,
    select_planner,
)
from opencode_buddy.model_catalog import load_env_sources
from opencode_buddy.project_scanner import scan_project
from opencode_buddy.registry import load_registry
from opencode_buddy.scaffolder import ProjectSpec, SpecFileError, load_spec_file, scaffold_project
from opencode_buddy.validator import format_validation_report, validate_project
from opencode_buddy.wizard import run_create_wizard

app = typer.Typer(
    add_completion=False,
    help="Scaffolder de projetos OpenCode com proxy LiteLLM (DeepSeek + Kimi + ChatGPT OAuth).",
)

AGENT_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")


def _parse_extra_agent(raw: str) -> AgentSpec:
    if "=" not in raw:
        raise ValueError("use o formato nome=modelo[:descricao]")

    name, model_and_description = raw.split("=", 1)
    name = name.strip()
    model_and_description = model_and_description.strip()

    if not name or not AGENT_NAME_RE.fullmatch(name):
        raise ValueError(f"nome de agent invalido: {name!r}")
    if not model_and_description:
        raise ValueError(f"modelo ausente para agent {name!r}")

    if ":" in model_and_description:
        model, description = model_and_description.split(":", 1)
        description = description.strip()
    else:
        model = model_and_description
        description = ""

    model = model.strip()
    if not model:
        raise ValueError(f"modelo ausente para agent {name!r}")

    return AgentSpec(
        name=name,
        description=description or f"Agent customizado: {name}",
        model=model,
        prompt_file=f"{name}.md",
    )


def _scaffold_project(target: Path, opts: InitOptions, force: bool) -> None:
    """Wrapper de compat sobre `scaffolder.scaffold_project`."""
    scaffold_project(target, opts, force)


_INITOPTIONS_FIELDS = {field.name for field in dataclasses.fields(InitOptions)}


def _coerce_spec_data(raw: dict[str, object]) -> dict[str, object]:
    data = dict(raw)

    if "drop_params" in data:
        data["drop_params"] = _coerce_str_tuple("drop_params", data["drop_params"])
    if "extra_agents" in data:
        data["extra_agents"] = _coerce_dataclass_tuple("extra_agents", data["extra_agents"], AgentSpec)
    if "model_specs" in data:
        data["model_specs"] = _coerce_dataclass_tuple("model_specs", data["model_specs"], ModelSpec)
    if "fallback_rules" in data:
        data["fallback_rules"] = _coerce_fallback_rules(data["fallback_rules"])
    if "project_context" in data:
        data["project_context"] = _coerce_project_context(data["project_context"])

    return data


def _coerce_dataclass_tuple(field_name: str, value: object, cls: type) -> tuple[object, ...]:
    if not isinstance(value, list | tuple):
        raise SpecFileError(f"{field_name}: esperado lista")
    return tuple(_coerce_dataclass(field_name, item, cls) for item in value)


def _coerce_dataclass(field_name: str, value: object, cls: type) -> object:
    if isinstance(value, cls):
        return value
    if not isinstance(value, dict):
        raise SpecFileError(f"{field_name}: item precisa ser objeto")
    allowed = {field.name for field in dataclasses.fields(cls)}
    unknown = set(value) - allowed
    if unknown:
        raise SpecFileError(f"{field_name}: campos desconhecidos: {', '.join(sorted(unknown))}")
    try:
        return cls(**value)
    except TypeError as exc:
        raise SpecFileError(f"{field_name}: campos invalidos: {exc}") from exc


def _coerce_fallback_rules(value: object) -> tuple[FallbackRule, ...]:
    if not isinstance(value, list | tuple):
        raise SpecFileError("fallback_rules: esperado lista")
    rules: list[FallbackRule] = []
    for item in value:
        if isinstance(item, FallbackRule):
            rules.append(item)
            continue
        if not isinstance(item, dict):
            raise SpecFileError("fallback_rules: item precisa ser objeto")
        raw = dict(item)
        if "fallbacks" in raw:
            raw["fallbacks"] = _coerce_str_tuple("fallback_rules.fallbacks", raw["fallbacks"])
        rules.append(_coerce_dataclass("fallback_rules", raw, FallbackRule))  # type: ignore[arg-type]
    return tuple(rules)


def _coerce_project_context(value: object) -> ProjectContext:
    if isinstance(value, ProjectContext):
        return value
    if not isinstance(value, dict):
        raise SpecFileError("project_context: esperado objeto")

    raw = dict(value)
    allowed = {field.name for field in dataclasses.fields(ProjectContext)}
    unknown = set(raw) - allowed
    if unknown:
        raise SpecFileError(f"project_context: campos desconhecidos: {', '.join(sorted(unknown))}")

    for key in ("notes", "commands", "constraints", "conventions", "risks"):
        if key in raw:
            raw[key] = _coerce_str_tuple(f"project_context.{key}", raw[key])
    if "role_models" in raw:
        raw["role_models"] = _coerce_pair_tuple("project_context.role_models", raw["role_models"])
    if "capabilities" in raw:
        raw["capabilities"] = _coerce_capability_details(raw["capabilities"])

    base = {
        field.name: getattr(InitOptions().project_context, field.name)
        for field in dataclasses.fields(ProjectContext)
    }
    base.update(raw)

    try:
        return ProjectContext(**base)
    except TypeError as exc:
        raise SpecFileError(f"project_context: campos invalidos: {exc}") from exc


def _coerce_capability_details(value: object) -> tuple[CapabilityDetail, ...]:
    if not isinstance(value, list | tuple):
        raise SpecFileError("project_context.capabilities: esperado lista")
    details: list[CapabilityDetail] = []
    for item in value:
        if isinstance(item, CapabilityDetail):
            details.append(item)
            continue
        if not isinstance(item, dict):
            raise SpecFileError("project_context.capabilities: item precisa ser objeto")
        raw = dict(item)
        if "answers" in raw:
            raw["answers"] = _coerce_answer_tuple(raw["answers"])
        details.append(_coerce_dataclass("project_context.capabilities", raw, CapabilityDetail))  # type: ignore[arg-type]
    return tuple(details)


def _coerce_answer_tuple(value: object) -> tuple[tuple[str, str], ...]:
    if isinstance(value, dict):
        return tuple((str(key), str(item)) for key, item in value.items())
    return _coerce_pair_tuple("project_context.capabilities.answers", value)


def _coerce_pair_tuple(field_name: str, value: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, list | tuple):
        raise SpecFileError(f"{field_name}: esperado lista de pares")
    pairs: list[tuple[str, str]] = []
    for item in value:
        if not isinstance(item, list | tuple) or len(item) != 2:
            raise SpecFileError(f"{field_name}: item precisa ser par [chave, valor]")
        pairs.append((str(item[0]), str(item[1])))
    return tuple(pairs)


def _coerce_str_tuple(field_name: str, value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if not isinstance(value, list | tuple):
        raise SpecFileError(f"{field_name}: esperado lista de strings")
    items: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise SpecFileError(f"{field_name}: esperado lista de strings")
        items.append(item)
    return tuple(items)


def _build_init_spec(
    *,
    spec_path: Path | None,
    flag_overrides: dict[str, object],
    extra_agents: tuple[AgentSpec, ...],
) -> ProjectSpec:
    """Combina --spec file (defaults) com flags do init (overrides)."""
    base: dict[str, object] = {}
    if spec_path is not None:
        raw = load_spec_file(spec_path)
        unknown = set(raw) - _INITOPTIONS_FIELDS
        if unknown:
            raise SpecFileError(
                f"{spec_path}: campos desconhecidos: {', '.join(sorted(unknown))}"
            )
        base = _coerce_spec_data(raw)

    merged = dict(base)
    for key, value in flag_overrides.items():
        if value is None:
            continue
        merged[key] = value

    if extra_agents:
        existing = tuple(base.get("extra_agents") or ())
        merged["extra_agents"] = existing + extra_agents

    try:
        return ProjectSpec(**merged)
    except TypeError as exc:
        raise SpecFileError(f"campos invalidos no spec: {exc}") from exc


def _confirm_pt(label: str, default: bool = True) -> bool:
    suffix = t("confirm.yes_default") if default else t("confirm.no_default")
    yes_words = {"s", "sim", "y", "yes"}
    no_words = {"n", "nao", "não", "no"}
    while True:
        raw = typer.prompt(f"{label} {suffix}", default="", show_default=False).strip().lower()
        if not raw:
            return default
        if raw in yes_words:
            return True
        if raw in no_words:
            return False
        typer.secho(t("confirm.invalid"), fg=typer.colors.RED)


def _validate_keys_for_cwd(
    cwd: Path,
    *,
    provider_keys: tuple[str, ...] = (),
    timeout: float = 5.0,
) -> tuple[ProviderStatus, ...]:
    try:
        return validate_selected_providers(cwd.resolve(), provider_keys=provider_keys, timeout=timeout)
    except UnknownProviderError as exc:
        typer.secho(
            t("keys.unknown_provider", provider=exc.key),
            fg=typer.colors.RED,
            err=True,
        )
        typer.secho(
            t("keys.unknown_provider.available", available=", ".join(exc.available)),
            fg=typer.colors.YELLOW,
            err=True,
        )
        raise typer.Exit(2) from exc
    except ValueError as exc:
        typer.secho(f"[ERRO] {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc


def _run_keys_setup(
    cwd: Path,
    *,
    provider_keys: tuple[str, ...] = (),
    overwrite: bool = False,
    timeout: float = 5.0,
) -> tuple[ProviderStatus, ...]:
    try:
        result = run_key_setup_interactive(
            cwd.resolve(),
            provider_keys=provider_keys,
            overwrite=overwrite,
            timeout=timeout,
        )
    except ValueError as exc:
        typer.secho(f"[ERRO] {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc

    if result.statuses:
        typer.echo(_format_keys_report(result.statuses))
    return result.statuses


def _ensure_live_keys_or_exit(
    cwd: Path,
    *,
    provider_keys: tuple[str, ...] = (),
    timeout: float = 5.0,
    allow_prompt: bool = True,
    json_mode: bool = False,
) -> dict[str, str]:
    cwd = cwd.resolve()
    cwd.mkdir(parents=True, exist_ok=True)

    statuses = _validate_keys_for_cwd(cwd, provider_keys=provider_keys, timeout=timeout)
    if has_ok_api_provider(statuses):
        return load_env_sources(cwd)

    if not json_mode:
        typer.echo(_format_keys_report(statuses))

    provider_hint = ", ".join(provider_keys) if provider_keys else "OpenCode Go/DeepSeek/etc."
    if allow_prompt and not json_mode:
        should_setup = _confirm_pt(
            f"Nenhuma chave API valida foi encontrada em {cwd}. Configurar {provider_hint} agora?",
            default=True,
        )
        if should_setup:
            statuses = _run_keys_setup(
                cwd,
                provider_keys=provider_keys,
                overwrite=False,
                timeout=timeout,
            )
            if has_ok_api_provider(statuses):
                return load_env_sources(cwd)

    typer.secho(
        (
            "[ERRO] Nenhum provider API valido disponivel. "
            "Configure um .env nesta pasta com `opencode-buddy keys setup --cwd .`, "
            "ou rode `opencode-buddy keys validate --cwd .` para diagnosticar."
        ),
        fg=typer.colors.RED,
        err=True,
    )
    raise typer.Exit(2)


def _planner_provider_or_exit(planner: str) -> str | None:
    if planner == "auto":
        return None
    if planner not in LIVE_SUPPORTED_PROVIDERS:
        available = ", ".join(("auto",) + LIVE_SUPPORTED_PROVIDERS)
        typer.secho(
            t("agent_driven.planner.error", error=f"provider '{planner}' nao suportado. Use: {available}"),
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(2)
    return planner


@app.command()
def init(
    path: Path = typer.Argument(Path("."), help="Diretorio destino do projeto"),
    spec: Path | None = typer.Option(
        None,
        "--spec",
        help="Arquivo YAML/JSON com campos de InitOptions (defaults). Flags ainda tem precedencia.",
    ),
    litellm_url: str | None = typer.Option(None, help="Base URL do proxy LiteLLM"),
    litellm_port: int | None = typer.Option(None, help="Porta do proxy LiteLLM"),
    no_chatgpt: bool = typer.Option(False, "--no-chatgpt", help="Desabilita subagent backend (ChatGPT OAuth)"),
    opencode_go_api_base: str | None = typer.Option(None),
    go_kimi_model: str | None = typer.Option(None),
    go_deepseek_fast_model: str | None = typer.Option(None),
    go_heavy_fallback_model: str | None = typer.Option(None),
    deepseek_fast_direct_model: str | None = typer.Option(None),
    deepseek_pro_direct_model: str | None = typer.Option(None),
    routing_strategy: str | None = typer.Option(None),
    backend_model: str | None = typer.Option(None),
    extra_agent: list[str] | None = typer.Option(
        None,
        "--extra-agent",
        help="Adiciona agent customizado: nome=modelo[:descricao]. Ex: reviewer=litellm/deepseek-pro:Revisao de codigo",
    ),
    setup_keys: bool = typer.Option(
        False,
        "--setup-keys",
        help="Depois do scaffold, cria/atualiza .env com chaves de provider e valida.",
    ),
    validate_keys: bool = typer.Option(
        False,
        "--validate-keys",
        help="Depois do scaffold, valida as chaves do .env/ambiente da pasta destino.",
    ),
    keys_timeout: float = typer.Option(
        5.0,
        "--keys-timeout",
        help="Timeout em segundos por provider durante setup/validacao de chaves.",
    ),
    force: bool = typer.Option(False, "--force", help="Sobrescreve arquivos existentes"),
) -> None:
    """Gera opencode.json + litellm-config.yaml + .env.example + .opencode/agents/."""

    try:
        extra_agents = tuple(_parse_extra_agent(raw) for raw in (extra_agent or ()))
    except ValueError as exc:
        typer.secho(f"[ERRO] {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc

    flag_overrides: dict[str, object] = {
        "litellm_url": litellm_url,
        "litellm_port": litellm_port,
        "opencode_go_api_base": opencode_go_api_base,
        "go_kimi_model": go_kimi_model,
        "go_deepseek_fast_model": go_deepseek_fast_model,
        "go_heavy_fallback_model": go_heavy_fallback_model,
        "deepseek_fast_direct_model": deepseek_fast_direct_model,
        "deepseek_pro_direct_model": deepseek_pro_direct_model,
        "routing_strategy": routing_strategy,
        "backend_model": backend_model,
    }
    if no_chatgpt:
        flag_overrides["enable_chatgpt"] = False

    try:
        project_spec = _build_init_spec(
            spec_path=spec,
            flag_overrides=flag_overrides,
            extra_agents=extra_agents,
        )
    except SpecFileError as exc:
        typer.secho(f"[ERRO] {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc

    try:
        scaffold_project(path.resolve(), project_spec, force)
    except ValueError as exc:
        typer.secho(f"[ERRO] {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc

    target_path = path.resolve()
    if setup_keys:
        statuses = _run_keys_setup(target_path, timeout=keys_timeout)
        if has_failures(statuses, strict=False):
            raise typer.Exit(1)
    elif validate_keys:
        statuses = _validate_keys_for_cwd(target_path, timeout=keys_timeout)
        typer.echo(_format_keys_report(statuses))
        if has_failures(statuses, strict=False):
            raise typer.Exit(1)


@app.command()
def create(
    path: Path | None = typer.Argument(None, help="Diretorio destino do projeto"),
    setup_keys: bool = typer.Option(
        True,
        "--setup-keys/--no-setup-keys",
        help="Antes de escolher modelos, garante pelo menos uma chave API valida no .env do projeto.",
    ),
    keys_timeout: float = typer.Option(
        5.0,
        "--keys-timeout",
        help="Timeout em segundos por provider durante validacao de chaves.",
    ),
    force: bool = typer.Option(False, "--force", help="Sobrescreve arquivos existentes"),
) -> None:
    """Wizard interativo estilo Vite para criar um projeto OpenCode customizado."""

    def prepare_env(target_text: str) -> dict[str, str]:
        target_path = Path(target_text).resolve()
        return _ensure_live_keys_or_exit(
            target_path,
            timeout=keys_timeout,
            allow_prompt=setup_keys,
        )

    target_text, project_spec = run_create_wizard(str(path) if path else None, prepare_env=prepare_env)
    try:
        scaffold_project(Path(target_text).resolve(), project_spec, force)
    except ValueError as exc:
        typer.secho(f"[ERRO] {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc


@app.command()
def validate(
    path: Path = typer.Argument(Path("."), help="Diretorio do projeto gerado"),
    strict: bool = typer.Option(False, "--strict", help="Retorna erro tambem quando houver avisos"),
) -> None:
    """Valida um projeto gerado pelo opencode-buddy."""

    messages = validate_project(path.resolve())
    typer.echo(format_validation_report(messages))
    has_errors = any(message.level == "error" for message in messages)
    has_warnings = any(message.level == "warn" for message in messages)
    if has_errors or (strict and has_warnings):
        sys.exit(1)


@app.command("agent-driven")
def agent_driven(
    scan: Path | None = typer.Option(
        None,
        "--scan",
        help="Pasta a vasculhar (modo projeto existente). Sem --scan, abre modo novo projeto.",
    ),
    target: Path | None = typer.Option(
        None,
        "--target",
        help="Pasta destino do scaffold. Default: --scan se presente, senao perguntado.",
    ),
    planner: str = typer.Option(
        "auto",
        "--planner",
        help=(
            "Planner: auto, ou um dos providers suportados ("
            + "/".join(LIVE_SUPPORTED_PROVIDERS)
            + "). Use --offline para forcar o deterministico."
        ),
    ),
    offline: bool = typer.Option(
        False,
        "--offline",
        help="Forca planner deterministico (sem chamar LLM, sem rede).",
    ),
    objective: str | None = typer.Option(
        None,
        "--objective",
        help="Texto livre descrevendo o projeto (modo novo). Se ausente, sera perguntado.",
    ),
    force: bool = typer.Option(False, "--force", help="Sobrescreve arquivos existentes no target"),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Gera o plano mas nao chama scaffold_project. Combinado com --json, pula o review interativo.",
    ),
    json_out: bool = typer.Option(
        False,
        "--json",
        help="Saida JSON do plano (para automacao). Exige --dry-run.",
    ),
    planner_timeout: float = typer.Option(
        DEFAULT_PLANNER_TIMEOUT,
        "--planner-timeout",
        help="Timeout em segundos para a chamada live do planner LLM.",
    ),
    keys_timeout: float = typer.Option(
        5.0,
        "--keys-timeout",
        help="Timeout em segundos por provider durante validacao de chaves.",
    ),
) -> None:
    """Modo Agent Driven: LLM (ou heuristica determinista) propoe ProjectSpec + revisao + scaffold."""

    if json_out and not dry_run:
        typer.secho(
            t("agent_driven.json.requires_dry_run"),
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(2)

    # Em --json, toda mensagem informativa vai a stderr para nao poluir stdout.
    info_err = json_out

    def info(message: str, *, color: str | None = None, bold: bool = False) -> None:
        typer.secho(message, fg=color, bold=bold, err=info_err)

    cwd_for_env = (scan if scan is not None else target if target is not None else Path.cwd()).resolve()
    explicit_provider = None if offline else _planner_provider_or_exit(planner)
    if offline:
        env = load_env_sources(cwd_for_env)
    else:
        env = _ensure_live_keys_or_exit(
            cwd_for_env,
            provider_keys=(explicit_provider,) if explicit_provider else (),
            timeout=keys_timeout,
            allow_prompt=not (json_out and dry_run),
            json_mode=json_out and dry_run,
        )

    try:
        client = select_planner(
            env,
            prefer=None if planner == "auto" else planner,
            offline=offline,
            timeout=planner_timeout,
        )
    except PlannerError as exc:
        typer.secho(t("agent_driven.planner.error", error=str(exc)), fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc

    info(t("agent_driven.planner.using", name=client.name), color=typer.colors.CYAN, bold=True)

    if scan is not None:
        scan_resolved = scan.resolve()
        scan_data = scan_project(scan_resolved)
        info(
            t(
                "agent_driven.scan.summary",
                files=len(scan_data.detected_files),
                languages=", ".join(scan_data.languages) or "(nenhuma)",
            ),
            color=typer.colors.WHITE,
        )
    else:
        scan_data = None

    if scan_data is None and not objective:
        if json_out and dry_run:
            objective = ""  # modo automacao: nao prompta
        else:
            objective = typer.prompt(t("agent_driven.objective.prompt"), default="")

    available_providers = _detected_provider_keys(env)
    detected_oauth = _detected_oauth_keys()

    request = AgentDrivenRequest(
        scan=scan_data,
        user_objective=objective or "",
        available_providers=available_providers,
        detected_oauth=detected_oauth,
    )

    plan, active_planner = propose_plan_with_fallback(
        client,
        request,
        on_fallback=lambda reason: typer.secho(
            t("agent_driven.planner.fallback", reason=reason),
            fg=typer.colors.YELLOW,
            err=True,
        ),
    )

    # Resolve target_path
    if target is not None:
        plan = dataclasses.replace(plan, target_path=str(target))
    elif plan.target_path:
        pass
    elif scan is not None:
        plan = dataclasses.replace(plan, target_path=str(scan.resolve()))
    elif json_out and dry_run:
        plan = dataclasses.replace(plan, target_path=".")
    else:
        prompted = typer.prompt(t("agent_driven.target.prompt"), default="my-opencode-project")
        plan = dataclasses.replace(plan, target_path=prompted)

    # Modo automacao: pula review, imprime JSON, nao escreve.
    if json_out and dry_run:
        payload = plan_to_jsonable_public(plan, include_raw=False)
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    final_plan = run_review_loop(plan, active_planner, request)
    if final_plan is None:
        typer.secho(t("agent_driven.cancelled"), fg=typer.colors.YELLOW)
        raise typer.Exit(1)

    if dry_run:
        typer.secho(t("agent_driven.dry_run.no_files_written"), fg=typer.colors.CYAN, bold=True)
        return

    try:
        spec = plan_to_project_spec(final_plan)
    except PlannerError as exc:
        typer.secho(t("agent_driven.planner.error", error=str(exc)), fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc

    target_path = Path(final_plan.target_path).resolve()
    try:
        scaffold_project(target_path, spec, force)
    except ValueError as exc:
        typer.secho(f"[ERRO] {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc


def _detected_provider_keys(env: dict[str, str]) -> tuple[str, ...]:
    registry = load_registry()
    detected: list[str] = []
    for provider in registry.providers:
        if provider.api_key_env and env.get(provider.api_key_env):
            detected.append(provider.key)
    return tuple(detected)


def _detected_oauth_keys() -> tuple[str, ...]:
    # Lazy: chamada a opencode auth list e cara; o planner deterministico nao depende dela.
    # Aqui retornamos vazio e deixamos o usuario sinalizar via flags futuras se necessario.
    return ()


@app.command()
def doctor() -> None:
    """Verifica se opencode, litellm e node estao instalados."""
    results = run_doctor()
    typer.echo(format_report(results))
    if any(not r.found for r in results):
        sys.exit(1)


keys_app = typer.Typer(
    add_completion=False,
    help="Valida chaves de provider e descoberta de modelos.",
    no_args_is_help=True,
)
app.add_typer(keys_app, name="keys")


@keys_app.command("validate")
def keys_validate(
    cwd: Path = typer.Option(Path("."), "--cwd", help="Diretorio onde procurar .env"),
    provider: str | None = typer.Option(None, "--provider", help="Filtra por chave do provider (ex: deepseek)"),
    json_out: bool = typer.Option(False, "--json", help="Saida em JSON estruturado"),
    timeout: float = typer.Option(5.0, "--timeout", help="Timeout em segundos por requisicao HTTP"),
    strict: bool = typer.Option(False, "--strict", help="Falha tambem em missing-env e network-failed"),
) -> None:
    """Valida providers do registry checando ENV e listagem de modelos."""

    try:
        statuses = validate_providers(cwd=cwd.resolve(), only=provider, timeout=timeout)
    except UnknownProviderError as exc:
        typer.secho(
            t("keys.unknown_provider", provider=exc.key),
            fg=typer.colors.RED,
            err=True,
        )
        typer.secho(
            t("keys.unknown_provider.available", available=", ".join(exc.available)),
            fg=typer.colors.YELLOW,
            err=True,
        )
        raise typer.Exit(2) from exc

    if json_out:
        payload = [status.to_dict() for status in statuses]
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        typer.echo(_format_keys_report(statuses))

    if has_failures(statuses, strict=strict):
        sys.exit(1)


@keys_app.command("setup")
def keys_setup(
    cwd: Path = typer.Option(Path("."), "--cwd", help="Diretorio onde criar/atualizar .env"),
    provider: list[str] | None = typer.Option(
        None,
        "--provider",
        help="Provider a configurar (pode repetir). Ex: --provider opencode-go --provider deepseek",
    ),
    overwrite: bool = typer.Option(False, "--overwrite", help="Pergunta e permite substituir chaves existentes"),
    timeout: float = typer.Option(5.0, "--timeout", help="Timeout em segundos por requisicao HTTP"),
) -> None:
    """Cria/atualiza .env com chaves de provider sem vazar valores no terminal."""

    statuses = _run_keys_setup(
        cwd.resolve(),
        provider_keys=tuple(provider or ()),
        overwrite=overwrite,
        timeout=timeout,
    )
    if has_failures(statuses, strict=False):
        raise typer.Exit(1)


_STATE_TAG_KEYS: dict[str, tuple[str, str]] = {
    STATE_OK: ("tag.ok", typer.colors.GREEN),
    STATE_MISSING_ENV: ("tag.miss", typer.colors.YELLOW),
    STATE_AUTH_FAILED: ("tag.auth", typer.colors.RED),
    STATE_NETWORK_FAILED: ("tag.net", typer.colors.RED),
    STATE_UNSUPPORTED: ("tag.skip", typer.colors.YELLOW),
    STATE_SKIPPED: ("tag.skip", typer.colors.YELLOW),
}


def _format_keys_report(statuses: tuple[ProviderStatus, ...]) -> str:
    if not statuses:
        return t("keys.report.empty")

    name_width = max(len(status.provider_name) for status in statuses)
    transport_width = max(len(status.transport) for status in statuses)

    lines = [typer.style(t("keys.report.header"), fg=typer.colors.CYAN, bold=True)]
    for status in statuses:
        tag_key, color = _STATE_TAG_KEYS.get(status.state, ("tag.info", typer.colors.WHITE))
        tag_styled = typer.style(t(tag_key), fg=color, bold=True)
        name = status.provider_name.ljust(name_width)
        transport = status.transport.ljust(transport_width)
        lines.append(f"  {tag_styled} {name}  {transport}  {status.detail}")
    return "\n".join(lines)


if __name__ == "__main__":
    app()
