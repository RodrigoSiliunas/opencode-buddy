"""Agent Driven Mode core.

Orquestra um planner LLM (com fallback deterministico) que propoe um
ProjectSpec a partir de um scan local + objetivo do usuario, exibe num
"plan mode" para aprovacao/debate, e converte o plano aprovado num
ProjectSpec valido para `scaffold_project`.

Restricoes:
- Nao envia conteudo de .env. Apenas NOMES de env vars detectadas.
- Live LLM client suporta providers OpenAI-compatible
  (deepseek/moonshot/opencode-go/commandcode com COMMANDCODE_API_BASE)
  e adapters nativos para Anthropic/Gemini.
- Sem rede no DeterministicPlannerClient.
- plan_to_project_spec reconstroi ModelSpec via registry, ignora texto livre
  do LLM em campos como api_key_env/api_base/litellm_model.
"""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass, field, replace
from typing import Protocol

import typer

from opencode_buddy.agent_driven_schema import (
    PLAN_JSON_SCHEMA,
    SchemaValidationError,
    validate_plan_payload,
)
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
from opencode_buddy.model_catalog import DEFAULT_HTTP_HEADERS
from opencode_buddy.project_scanner import ProjectScan
from opencode_buddy.registry import (
    ModelEntry,
    OAuthModelEntry,
    OAuthProviderEntry,
    ProviderEntry,
    Registry,
    load_registry,
)
from opencode_buddy.scaffolder import ProjectSpec


# Providers cujo discovery e protocolo HTTP sao OpenAI-compatible.
LIVE_OPENAI_COMPATIBLE_PROVIDERS: tuple[str, ...] = (
    "deepseek",
    "moonshot",
    "opencode-go",
    "commandcode",
)

# Providers com adapter nativo separado.
LIVE_NATIVE_PROVIDERS: tuple[str, ...] = ("anthropic", "gemini")

# Ordem de auto-pick: OpenAI-compatible primeiro (mais barato/comum), depois nativos.
LIVE_PLANNER_PRIORITY: tuple[str, ...] = (
    "deepseek",
    "moonshot",
    "opencode-go",
    "commandcode",
    "anthropic",
    "gemini",
)

LIVE_SUPPORTED_PROVIDERS: tuple[str, ...] = LIVE_OPENAI_COMPATIBLE_PROVIDERS + LIVE_NATIVE_PROVIDERS

# Fallback de api_base para providers OpenAI-compatible quando o registry
# nao traz `api_base` explicito (ex: deepseek usa o discovery.kind dedicado e
# a URL e implicita no LiteLLM/openai client).
_DEFAULT_API_BASES: dict[str, str] = {
    "deepseek": "https://api.deepseek.com/v1",
}

ANTHROPIC_API_BASE = "https://api.anthropic.com"
ANTHROPIC_API_VERSION = "2023-06-01"
ANTHROPIC_MAX_TOKENS = 4096

GEMINI_API_BASE = "https://generativelanguage.googleapis.com"
GEMINI_API_VERSION = "v1beta"
DEFAULT_PLANNER_TIMEOUT = 90.0

ROLES: tuple[str, ...] = ("build", "frontend", "backend", "audio", "video", "default", "deep")


class PlannerError(RuntimeError):
    """Falha no planner (HTTP, JSON malformado, schema invalido, etc)."""


@dataclass(frozen=True)
class AgentDrivenRequest:
    scan: ProjectScan | None
    user_objective: str
    available_providers: tuple[str, ...]
    detected_oauth: tuple[str, ...]
    locale: str = "pt-BR"


@dataclass(frozen=True)
class AgentDrivenDecision:
    capability: str
    enabled: bool
    answers: tuple[tuple[str, str], ...] = ()
    reason: str = ""


@dataclass(frozen=True)
class AgentDrivenModelChoice:
    role: str
    provider_key: str
    model_id: str
    litellm_alias: str
    reason: str = ""


@dataclass(frozen=True)
class AgentDrivenPlan:
    target_path: str
    detected_summary: tuple[str, ...] = field(default_factory=tuple)
    decisions: tuple[AgentDrivenDecision, ...] = field(default_factory=tuple)
    model_choices: tuple[AgentDrivenModelChoice, ...] = field(default_factory=tuple)
    extra_agents: tuple[AgentSpec, ...] = field(default_factory=tuple)
    risks: tuple[str, ...] = field(default_factory=tuple)
    commands: tuple[str, ...] = field(default_factory=tuple)
    reasons: tuple[str, ...] = field(default_factory=tuple)
    raw_response: str = ""


class PlannerClient(Protocol):
    name: str

    def propose(self, request: AgentDrivenRequest) -> AgentDrivenPlan: ...

    def revise(
        self,
        previous: AgentDrivenPlan,
        feedback: str,
        request: AgentDrivenRequest,
    ) -> AgentDrivenPlan: ...


# ---------------------------------------------------------------------------
# DeterministicPlannerClient
# ---------------------------------------------------------------------------


class DeterministicPlannerClient:
    """Planner sem rede. Usa heuristicas + registry para propor spec valido."""

    name = "deterministic"

    def __init__(self, registry: Registry | None = None) -> None:
        self._registry = registry or load_registry()

    def propose(self, request: AgentDrivenRequest) -> AgentDrivenPlan:
        signals = dict(request.scan.signals) if request.scan else {}
        languages = set(request.scan.languages) if request.scan else set()
        objective_lower = request.user_objective.lower() if request.user_objective else ""

        decisions = self._infer_decisions(signals, languages, objective_lower)
        model_choices = self._pick_models(decisions, request)
        risks = self._collect_risks(request, decisions, model_choices)
        reasons = self._collect_reasons(decisions, model_choices, signals)
        commands = self._suggest_commands(signals, languages)
        extra_agents = tuple(
            AgentSpec(
                name=cap_to_agent_name(decision.capability),
                description=_capability_description(decision.capability),
                model=_resolve_role_alias(decision.capability, model_choices),
                prompt_file=f"{cap_to_agent_name(decision.capability)}.md",
            )
            for decision in decisions
            if decision.enabled and _capability_has_dedicated_agent(decision.capability)
            and decision.capability not in {"frontend", "backend"}
        )

        target_path = (
            str(request.scan.root) if request.scan else (request.user_objective.strip() or "my-opencode-project")
        )

        detected_summary = self._detected_summary(request, signals, languages)

        return AgentDrivenPlan(
            target_path=target_path,
            detected_summary=detected_summary,
            decisions=decisions,
            model_choices=model_choices,
            extra_agents=extra_agents,
            risks=risks,
            commands=commands,
            reasons=reasons,
            raw_response="",
        )

    def revise(
        self,
        previous: AgentDrivenPlan,
        feedback: str,
        request: AgentDrivenRequest,
    ) -> AgentDrivenPlan:
        feedback_lower = feedback.strip().lower()
        decisions = list(previous.decisions)
        risks = list(previous.risks)

        if "remova frontend" in feedback_lower or "no frontend" in feedback_lower:
            decisions = [
                replace(d, enabled=False) if d.capability == "frontend" else d
                for d in decisions
            ]
            risks.append("Frontend desabilitado por feedback do usuario.")
        if "remova backend" in feedback_lower or "no backend" in feedback_lower:
            decisions = [
                replace(d, enabled=False) if d.capability == "backend" else d
                for d in decisions
            ]
            risks.append("Backend desabilitado por feedback do usuario.")
        if "habilita backend" in feedback_lower or "enable backend" in feedback_lower:
            decisions = [
                replace(d, enabled=True) if d.capability == "backend" else d
                for d in decisions
            ]

        model_choices = list(previous.model_choices)
        for provider_key in self._registry_provider_keys():
            if f"use {provider_key}" in feedback_lower:
                model_choices = self._override_models_with_provider(model_choices, provider_key)
                risks.append(f"Modelos forcados para o provider {provider_key} via feedback.")

        risks.append(f"Revisao deterministica aplicada apos feedback: {feedback.strip()[:120]}")

        return replace(
            previous,
            decisions=tuple(decisions),
            model_choices=tuple(model_choices),
            risks=tuple(risks),
        )

    # --- helpers internos ------------------------------------------------

    def _infer_decisions(
        self,
        signals: dict[str, str],
        languages: set[str],
        objective: str,
    ) -> tuple[AgentDrivenDecision, ...]:
        decisions: list[AgentDrivenDecision] = []

        framework = signals.get("framework", "")
        js_frameworks = signals.get("js_frameworks", "")
        has_js_ui = bool(framework or "react" in js_frameworks or "vue" in js_frameworks or "svelte" in js_frameworks)
        if has_js_ui or "frontend" in objective or "ui" in objective:
            answers = []
            if framework:
                answers.append(("framework", framework))
            if "typescript" in languages:
                answers.append(("typescript", "Sim"))
            if "tailwind" in js_frameworks:
                answers.append(("styling", "Tailwind"))
            decisions.append(
                AgentDrivenDecision(
                    capability="frontend",
                    enabled=True,
                    answers=tuple(answers),
                    reason="Sinais de framework JS/UI detectados (package.json/vite/next/etc).",
                )
            )

        py_libs = signals.get("python_libs", "")
        has_backend = (
            "fastapi" in py_libs
            or "django" in py_libs
            or "flask" in py_libs
            or "go" in languages
            or "rust" in languages
            or "java" in languages
            or "backend" in objective
            or "api" in objective
        )
        if has_backend:
            answers = []
            if "python" in languages:
                answers.append(("runtime", "Python"))
            elif "go" in languages:
                answers.append(("runtime", "Go"))
            elif "rust" in languages:
                answers.append(("runtime", "Rust"))
            elif "java" in languages:
                answers.append(("runtime", "Java/Kotlin"))
            if "fastapi" in py_libs:
                answers.append(("api_style", "REST"))
            decisions.append(
                AgentDrivenDecision(
                    capability="backend",
                    enabled=True,
                    answers=tuple(answers),
                    reason="Sinais de backend (pyproject/cargo/go.mod/objetivo).",
                )
            )

        multimodal_hits = signals.get("multimodal_hints", "")
        if any(hit in multimodal_hits for hit in ("audio", "speech", "transcrib", "asr", "tts", "whisper")):
            decisions.append(
                AgentDrivenDecision(
                    capability="audio",
                    enabled=True,
                    answers=(("tasks", "Transcricao"),),
                    reason="Pasta/arquivo com nome sugestivo de audio detectado.",
                )
            )
        if any(hit in multimodal_hits for hit in ("video", "vision", "frame", "multimodal", "image", "ocr")):
            decisions.append(
                AgentDrivenDecision(
                    capability="video",
                    enabled=True,
                    answers=(("tasks", "Analise visual"),),
                    reason="Pasta/arquivo com nome sugestivo de video/multimodal detectado.",
                )
            )

        test_tools = signals.get("test_tools", "")
        if test_tools:
            decisions.append(
                AgentDrivenDecision(
                    capability="qa",
                    enabled=True,
                    answers=(("strategy", "Pyramid (unit-heavy)"), ("e2e", _qa_e2e_label(test_tools))),
                    reason=f"Configs de teste detectadas: {test_tools}.",
                )
            )

        if signals.get("containerized") == "yes":
            decisions.append(
                AgentDrivenDecision(
                    capability="devops",
                    enabled=True,
                    answers=(("cloud", "Self-hosted"),),
                    reason="Dockerfile/docker-compose presentes.",
                )
            )

        if not decisions:
            decisions.append(
                AgentDrivenDecision(
                    capability="frontend",
                    enabled=False,
                    reason="Sem sinais; planner deterministico nao infere capacidades.",
                )
            )

        return tuple(decisions)

    def _pick_models(
        self,
        decisions: tuple[AgentDrivenDecision, ...],
        request: AgentDrivenRequest,
    ) -> tuple[AgentDrivenModelChoice, ...]:
        roles = ["build", "default", "deep"]
        if any(d.capability == "frontend" and d.enabled for d in decisions):
            roles.insert(1, "frontend")
        if any(d.capability == "backend" and d.enabled for d in decisions):
            roles.append("backend")
        if any(d.capability == "audio" and d.enabled for d in decisions):
            roles.append("audio")
        if any(d.capability == "video" and d.enabled for d in decisions):
            roles.append("video")

        seen: set[str] = set()
        ordered_roles: list[str] = []
        for role in roles:
            if role not in seen:
                seen.add(role)
                ordered_roles.append(role)

        choices: list[AgentDrivenModelChoice] = []
        for role in ordered_roles:
            choice = self._pick_model_for_role(role, request)
            if choice is not None:
                choices.append(choice)
        return tuple(choices)

    def _pick_model_for_role(
        self,
        role: str,
        request: AgentDrivenRequest,
    ) -> AgentDrivenModelChoice | None:
        available_keys = set(request.available_providers)

        # Audio/video: prefere Gemini se disponivel, depois OAuth chatgpt, depois fallback registry-default.
        if role in {"audio", "video"}:
            preferred_order = ["gemini", "chatgpt", "deepseek", "anthropic", "moonshot", "opencode-go"]
        else:
            preferred_order = self._registry_role_priority(role)

        for provider_key in preferred_order:
            provider, model = self._lookup_provider_model(provider_key, role)
            if provider is None or model is None:
                continue
            if provider_key in self._oauth_keys():
                if provider_key not in (k for k in request.detected_oauth):
                    # OAuth so vale se detectado
                    continue
                return AgentDrivenModelChoice(
                    role=role,
                    provider_key=provider_key,
                    model_id=model.id,
                    litellm_alias=model.litellm_model,
                    reason=f"OAuth {provider.name} detectado e recommended_for={role}.",
                )
            # API: precisa de chave para ser preferido; fallback aceita sem chave (com risco).
            if available_keys and provider_key in available_keys:
                return AgentDrivenModelChoice(
                    role=role,
                    provider_key=provider_key,
                    model_id=model.id,
                    litellm_alias=f"litellm/{role}-model",
                    reason=f"{provider.name} com chave detectada e recommended_for={role}.",
                )

        # Sem nenhum provider com chave: cai no primeiro recomendado do registry (sem chave).
        for provider_key in preferred_order:
            provider, model = self._lookup_provider_model(provider_key, role)
            if provider is None or model is None:
                continue
            if provider_key in self._oauth_keys():
                continue
            return AgentDrivenModelChoice(
                role=role,
                provider_key=provider_key,
                model_id=model.id,
                litellm_alias=f"litellm/{role}-model",
                reason=f"{provider.name} sugerido pelo registry (chave ainda nao detectada).",
            )
        return None

    def _registry_role_priority(self, role: str) -> list[str]:
        ordered: list[str] = []
        for provider in self._registry.providers:
            if role in provider.recommended_for:
                ordered.append(provider.key)
        for oauth in self._registry.oauth_providers:
            if any(role in m.recommended_for for m in oauth.models):
                ordered.append(oauth.key)
        for provider in self._registry.providers:
            if provider.key not in ordered:
                ordered.append(provider.key)
        return ordered

    def _registry_provider_keys(self) -> list[str]:
        keys = [provider.key for provider in self._registry.providers]
        keys.extend(provider.key for provider in self._registry.oauth_providers)
        return keys

    def _oauth_keys(self) -> set[str]:
        return {provider.key for provider in self._registry.oauth_providers}

    def _lookup_provider_model(
        self,
        provider_key: str,
        role: str,
    ) -> tuple[ProviderEntry | OAuthProviderEntry | None, ModelEntry | OAuthModelEntry | None]:
        for provider in self._registry.providers:
            if provider.key != provider_key:
                continue
            if not provider.models:
                return provider, None
            for model in provider.models:
                if role in model.recommended_for:
                    return provider, model
            return provider, provider.models[0]
        for oauth in self._registry.oauth_providers:
            if oauth.key != provider_key:
                continue
            if not oauth.models:
                return oauth, None
            for model in oauth.models:
                if role in model.recommended_for:
                    return oauth, model
            return oauth, oauth.models[0]
        return None, None

    def _collect_risks(
        self,
        request: AgentDrivenRequest,
        decisions: tuple[AgentDrivenDecision, ...],
        choices: tuple[AgentDrivenModelChoice, ...],
    ) -> tuple[str, ...]:
        risks: list[str] = []
        if not request.available_providers and not request.detected_oauth:
            risks.append(
                "Nenhuma chave de provider detectada; preencha .env antes de rodar `start-proxy.ps1`. "
                "Modelos sugeridos seguem os defaults do registry."
            )
        used_provider_keys = {choice.provider_key for choice in choices}
        for provider_key in used_provider_keys:
            if provider_key in self._oauth_keys():
                continue
            if request.available_providers and provider_key not in request.available_providers:
                provider_entry = next((p for p in self._registry.providers if p.key == provider_key), None)
                if provider_entry and provider_entry.api_key_env:
                    risks.append(
                        f"Provider {provider_entry.name} sugerido sem chave detectada "
                        f"({provider_entry.api_key_env}); modelo sera escolhido mas o proxy falhara ate preencher."
                    )
        return tuple(risks)

    def _collect_reasons(
        self,
        decisions: tuple[AgentDrivenDecision, ...],
        choices: tuple[AgentDrivenModelChoice, ...],
        signals: dict[str, str],
    ) -> tuple[str, ...]:
        reasons: list[str] = []
        for decision in decisions:
            if decision.enabled and decision.reason:
                reasons.append(f"capacidade {decision.capability}: {decision.reason}")
        for choice in choices:
            if choice.reason:
                reasons.append(f"role {choice.role}: {choice.reason}")
        if not reasons and signals:
            reasons.append("Sinais detectados: " + ", ".join(f"{k}={v}" for k, v in signals.items()))
        return tuple(reasons)

    def _suggest_commands(self, signals: dict[str, str], languages: set[str]) -> tuple[str, ...]:
        commands: list[str] = []
        if signals.get("package_manager_js"):
            commands.append("npm run dev")
            if "playwright" in signals.get("test_tools", ""):
                commands.append("npx playwright test")
        if "python" in languages:
            commands.append("uv run pytest")
        if not commands:
            commands.append("opencode")
        return tuple(commands)

    def _detected_summary(
        self,
        request: AgentDrivenRequest,
        signals: dict[str, str],
        languages: set[str],
    ) -> tuple[str, ...]:
        if not request.scan:
            return (
                f"Modo novo projeto. Objetivo: {request.user_objective.strip() or '(sem objetivo informado)'}",
            )
        items: list[str] = []
        if signals.get("framework"):
            items.append(f"Framework: {signals['framework']}")
        if languages:
            items.append("Linguagens: " + ", ".join(sorted(languages)))
        if signals.get("python_libs"):
            items.append(f"Libs Python: {signals['python_libs']}")
        if signals.get("test_tools"):
            items.append(f"Testes: {signals['test_tools']}")
        if signals.get("containerized") == "yes":
            items.append("Containerizado (Docker)")
        if signals.get("ci"):
            items.append(f"CI: {signals['ci']}")
        if not items:
            items.append("Nenhum sinal claro de stack detectado.")
        return tuple(items)

    def _override_models_with_provider(
        self,
        choices: list[AgentDrivenModelChoice],
        provider_key: str,
    ) -> list[AgentDrivenModelChoice]:
        new_choices: list[AgentDrivenModelChoice] = []
        for choice in choices:
            provider, model = self._lookup_provider_model(provider_key, choice.role)
            if provider is None or model is None:
                new_choices.append(choice)
                continue
            new_choices.append(
                replace(
                    choice,
                    provider_key=provider_key,
                    model_id=model.id,
                    litellm_alias=(
                        model.litellm_model if provider_key in self._oauth_keys() else f"litellm/{choice.role}-model"
                    ),
                    reason=f"forcado para {provider.name} via feedback do usuario.",
                )
            )
        return new_choices


# ---------------------------------------------------------------------------
# select_planner
# ---------------------------------------------------------------------------


def select_planner(
    env: dict[str, str],
    *,
    prefer: str | None = None,
    offline: bool = False,
    timeout: float = DEFAULT_PLANNER_TIMEOUT,
) -> PlannerClient:
    if offline:
        return DeterministicPlannerClient()

    registry = load_registry()

    if prefer is not None:
        if prefer not in LIVE_SUPPORTED_PROVIDERS:
            supported = "/".join(LIVE_SUPPORTED_PROVIDERS)
            raise PlannerError(
                f"provider '{prefer}' nao tem adapter de planner suportado; "
                f"use --planner={supported} ou --offline"
            )
        provider = next((p for p in registry.providers if p.key == prefer), None)
        if provider is None:
            raise PlannerError(f"provider '{prefer}' nao existe no registry")
        if not _provider_has_credentials(provider, env):
            raise PlannerError(
                f"provider '{prefer}' selecionado mas suas variaveis de ambiente nao estao setadas; "
                f"defina {provider.api_key_env or '(env esperada)'} ou use --offline"
            )
        return _build_live_client(provider, env=env, timeout=timeout)

    for provider_key in LIVE_PLANNER_PRIORITY:
        provider = next((p for p in registry.providers if p.key == provider_key), None)
        if provider is None:
            continue
        if not _provider_has_credentials(provider, env):
            continue
        return _build_live_client(provider, env=env, timeout=timeout)

    return DeterministicPlannerClient()


def _build_live_client(
    provider: ProviderEntry,
    *,
    env: dict[str, str],
    timeout: float,
) -> PlannerClient:
    model_id = _pick_planner_model(provider)
    if provider.key in LIVE_OPENAI_COMPATIBLE_PROVIDERS:
        return LiteLLMPlannerClient(provider=provider, model_id=model_id, env=env, timeout=timeout)
    if provider.key == "anthropic":
        return AnthropicPlannerClient(provider=provider, model_id=model_id, env=env, timeout=timeout)
    if provider.key == "gemini":
        return GeminiPlannerClient(provider=provider, model_id=model_id, env=env, timeout=timeout)
    raise PlannerError(f"provider '{provider.key}' sem adapter de planner")


def _provider_has_credentials(provider: ProviderEntry, env: dict[str, str]) -> bool:
    if provider.api_key_env and not env.get(provider.api_key_env):
        return False
    if provider.api_base_env and not env.get(provider.api_base_env):
        return False
    return True


def _pick_planner_model(provider: ProviderEntry) -> str:
    for model in provider.models:
        if "default" in model.recommended_for or "build" in model.recommended_for:
            return model.id
    if provider.models:
        return provider.models[0].id
    raise PlannerError(f"provider {provider.key} nao tem modelos no registry")


# ---------------------------------------------------------------------------
# LiteLLMPlannerClient (HTTP via urllib, OpenAI-compatible chat/completions)
# ---------------------------------------------------------------------------


class LiteLLMPlannerClient:
    """Planner LLM live para providers OpenAI-compatible.

    Suportado MVP: deepseek, moonshot, opencode-go, commandcode (com COMMANDCODE_API_BASE).
    Anthropic/Gemini sao rejeitados em select_planner antes da requisicao.
    """

    def __init__(
        self,
        *,
        provider: ProviderEntry,
        model_id: str,
        env: dict[str, str],
        timeout: float = DEFAULT_PLANNER_TIMEOUT,
    ) -> None:
        if provider.key not in LIVE_OPENAI_COMPATIBLE_PROVIDERS:
            raise PlannerError(
                f"provider '{provider.key}' requer adapter nativo (fora do MVP); "
                f"use --planner=deepseek/moonshot/opencode-go/commandcode ou --offline"
            )
        self._provider = provider
        self._model_id = model_id
        self._timeout = timeout
        self._api_key = env.get(provider.api_key_env or "", "")
        if provider.api_base_env:
            api_base_value = env.get(provider.api_base_env, "") or provider.api_base or ""
        else:
            api_base_value = provider.api_base or ""
        if not api_base_value:
            api_base_value = _DEFAULT_API_BASES.get(provider.key, "")
        self._api_base = api_base_value.rstrip("/")
        if not self._api_base:
            raise PlannerError(f"provider '{provider.key}' sem api_base resolvido")
        self.name = f"litellm:{provider.key}:{model_id}"

    def propose(self, request: AgentDrivenRequest) -> AgentDrivenPlan:
        user_message = _render_user_message(request)
        plan = self._call(user_message)
        target = (
            str(request.scan.root)
            if request.scan
            else (request.user_objective.strip() or "my-opencode-project")
        )
        return replace(plan, target_path=plan.target_path or target)

    def revise(
        self,
        previous: AgentDrivenPlan,
        feedback: str,
        request: AgentDrivenRequest,
    ) -> AgentDrivenPlan:
        revision_message = (
            _render_user_message(request)
            + "\n\n# Plano anterior\n"
            + json.dumps(_plan_to_jsonable(previous), ensure_ascii=False, indent=2)
            + "\n\n# Feedback do usuario\n"
            + feedback.strip()
        )
        return self._call(revision_message)

    # --- internals --------------------------------------------------------

    def _call(self, user_message: str) -> AgentDrivenPlan:
        body = {
            "model": self._model_id,
            "messages": [
                {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        url = f"{self._api_base}/chat/completions"
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=encoded,
            headers={
                **DEFAULT_HTTP_HEADERS,
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise PlannerError(f"HTTP {exc.code} ao chamar planner: {exc.reason}") from exc
        except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as exc:
            raise PlannerError(f"falha de rede ao chamar planner: {exc}") from exc

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise PlannerError(f"resposta nao-JSON do planner: {exc}") from exc

        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise PlannerError("resposta do planner sem campo choices[0].message.content") from exc

        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise PlannerError(f"content do planner nao e JSON valido: {exc}") from exc

        return _parse_plan_payload(data, raw_response=raw)


# ---------------------------------------------------------------------------
# Native adapters: Anthropic, Gemini
# ---------------------------------------------------------------------------


class _NativeHTTPClientBase:
    """Helpers compartilhados pelos adapters nativos."""

    def _post_json(self, url: str, *, headers: dict[str, str], body: dict, timeout: float) -> dict:
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        merged_headers = dict(DEFAULT_HTTP_HEADERS)
        merged_headers.update(headers)
        req = urllib.request.Request(url, data=encoded, headers=merged_headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise PlannerError(f"HTTP {exc.code} ao chamar planner: {exc.reason}") from exc
        except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as exc:
            raise PlannerError(f"falha de rede ao chamar planner: {exc}") from exc
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise PlannerError(f"resposta nao-JSON do planner: {exc}") from exc

    def _parse_inner_json(self, content: str) -> AgentDrivenPlan:
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise PlannerError(f"content do planner nao e JSON valido: {exc}") from exc
        return _parse_plan_payload(data, raw_response=content)


class AnthropicPlannerClient(_NativeHTTPClientBase):
    """Adapter nativo para Anthropic /v1/messages."""

    def __init__(
        self,
        *,
        provider: ProviderEntry,
        model_id: str,
        env: dict[str, str],
        timeout: float = DEFAULT_PLANNER_TIMEOUT,
    ) -> None:
        if provider.key != "anthropic":
            raise PlannerError(
                f"AnthropicPlannerClient exige provider 'anthropic', recebido '{provider.key}'"
            )
        if not provider.api_key_env:
            raise PlannerError("provider 'anthropic' sem api_key_env no registry")
        api_key = env.get(provider.api_key_env, "")
        if not api_key:
            raise PlannerError(f"variavel {provider.api_key_env} nao definida")
        self._provider = provider
        self._model_id = model_id
        self._timeout = timeout
        self._api_key = api_key
        self._api_base = (provider.api_base or ANTHROPIC_API_BASE).rstrip("/")
        self.name = f"anthropic:{model_id}"

    def propose(self, request: AgentDrivenRequest) -> AgentDrivenPlan:
        return self._call(_render_user_message(request))

    def revise(
        self,
        previous: AgentDrivenPlan,
        feedback: str,
        request: AgentDrivenRequest,
    ) -> AgentDrivenPlan:
        revision_message = (
            _render_user_message(request)
            + "\n\n# Plano anterior\n"
            + json.dumps(_plan_to_jsonable(previous), ensure_ascii=False, indent=2)
            + "\n\n# Feedback do usuario\n"
            + feedback.strip()
        )
        return self._call(revision_message)

    def _call(self, user_message: str) -> AgentDrivenPlan:
        url = f"{self._api_base}/v1/messages"
        body = {
            "model": self._model_id,
            "max_tokens": ANTHROPIC_MAX_TOKENS,
            "system": PLANNER_SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user_message}],
        }
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": ANTHROPIC_API_VERSION,
            "Content-Type": "application/json",
        }
        payload = self._post_json(url, headers=headers, body=body, timeout=self._timeout)
        try:
            content_blocks = payload["content"]
            text_parts: list[str] = []
            if isinstance(content_blocks, list):
                for block in content_blocks:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "")
                        if isinstance(text, str):
                            text_parts.append(text)
            text = "".join(text_parts)
        except (KeyError, TypeError) as exc:
            raise PlannerError("resposta Anthropic sem campo 'content'") from exc
        if not text:
            raise PlannerError("resposta Anthropic com 'content' vazio")
        return self._parse_inner_json(text)


class GeminiPlannerClient(_NativeHTTPClientBase):
    """Adapter nativo para Google Gemini generateContent.

    A API key vai apenas no header `x-goog-api-key`; nunca na URL nem no body.
    """

    def __init__(
        self,
        *,
        provider: ProviderEntry,
        model_id: str,
        env: dict[str, str],
        timeout: float = DEFAULT_PLANNER_TIMEOUT,
    ) -> None:
        if provider.key != "gemini":
            raise PlannerError(
                f"GeminiPlannerClient exige provider 'gemini', recebido '{provider.key}'"
            )
        if not provider.api_key_env:
            raise PlannerError("provider 'gemini' sem api_key_env no registry")
        api_key = env.get(provider.api_key_env, "")
        if not api_key:
            raise PlannerError(f"variavel {provider.api_key_env} nao definida")
        self._provider = provider
        self._model_id = model_id
        self._timeout = timeout
        self._api_key = api_key
        self._api_base = (provider.api_base or GEMINI_API_BASE).rstrip("/")
        self.name = f"gemini:{model_id}"

    def propose(self, request: AgentDrivenRequest) -> AgentDrivenPlan:
        return self._call(_render_user_message(request))

    def revise(
        self,
        previous: AgentDrivenPlan,
        feedback: str,
        request: AgentDrivenRequest,
    ) -> AgentDrivenPlan:
        revision_message = (
            _render_user_message(request)
            + "\n\n# Plano anterior\n"
            + json.dumps(_plan_to_jsonable(previous), ensure_ascii=False, indent=2)
            + "\n\n# Feedback do usuario\n"
            + feedback.strip()
        )
        return self._call(revision_message)

    def _call(self, user_message: str) -> AgentDrivenPlan:
        url = f"{self._api_base}/{GEMINI_API_VERSION}/models/{self._model_id}:generateContent"
        body = {
            "systemInstruction": {"parts": [{"text": PLANNER_SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": user_message}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.2,
            },
        }
        headers = {
            "x-goog-api-key": self._api_key,
            "Content-Type": "application/json",
        }
        payload = self._post_json(url, headers=headers, body=body, timeout=self._timeout)
        try:
            candidates = payload["candidates"]
            if not isinstance(candidates, list) or not candidates:
                raise PlannerError("resposta Gemini sem 'candidates'")
            parts = candidates[0]["content"]["parts"]
            if not isinstance(parts, list) or not parts:
                raise PlannerError("resposta Gemini sem 'parts'")
            text_parts: list[str] = []
            for part in parts:
                if isinstance(part, dict):
                    text = part.get("text", "")
                    if isinstance(text, str):
                        text_parts.append(text)
            text = "".join(text_parts)
        except (KeyError, IndexError, TypeError) as exc:
            raise PlannerError("resposta Gemini com schema inesperado") from exc
        if not text:
            raise PlannerError("resposta Gemini com 'parts' vazio")
        return self._parse_inner_json(text)


# ---------------------------------------------------------------------------
# plan_to_project_spec
# ---------------------------------------------------------------------------


def plan_to_project_spec(plan: AgentDrivenPlan, *, registry: Registry | None = None) -> ProjectSpec:
    """Reconstrucao do ProjectSpec a partir do plano, com ModelSpec do registry."""
    registry = registry or load_registry()

    role_to_alias: dict[str, str] = {}
    role_to_choice: dict[str, AgentDrivenModelChoice] = {}
    model_specs: list[ModelSpec] = []
    used_oauth = False

    for choice in plan.model_choices:
        if choice.role not in ROLES:
            raise PlannerError(f"role desconhecido no plano: {choice.role}")
        provider, model_litellm, model_id_norm = _lookup_registry_entry(registry, choice)
        if isinstance(provider, OAuthProviderEntry):
            used_oauth = True
            alias = model_litellm  # ex "chatgpt/gpt-5.5"
            role_to_alias[choice.role] = alias
            role_to_choice[choice.role] = choice
            continue
        alias = f"{choice.role}-model"
        # provider e API: ProviderEntry
        api_provider: ProviderEntry = provider  # type: ignore[assignment]
        model_specs.append(
            ModelSpec(
                alias=alias,
                litellm_model=model_litellm,
                display_name=f"{api_provider.name} - {model_id_norm}",
                api_key_env=api_provider.api_key_env,
                api_base=api_provider.api_base,
                api_base_env=api_provider.api_base_env,
            )
        )
        role_to_alias[choice.role] = f"litellm/{alias}"
        role_to_choice[choice.role] = choice

    # Capabilities habilitadas
    enabled = {d.capability for d in plan.decisions if d.enabled}
    capabilities = tuple(
        CapabilityDetail(
            key=d.capability,
            label=_capability_label(d.capability),
            answers=d.answers,
        )
        for d in plan.decisions
        if d.enabled
    )

    role_models_pairs = tuple(
        (
            _role_label(choice.role),
            f"{_provider_display_name(registry, choice.provider_key)} - {choice.model_id}",
        )
        for choice in plan.model_choices
    )

    notes = list(plan.reasons)
    if plan.detected_summary:
        notes.append("Detectado: " + " | ".join(plan.detected_summary))

    project_context = ProjectContext(
        preset="agent-driven",
        stack=_stack_label(enabled),
        summary=_summary_text(plan, enabled),
        notes=tuple(notes),
        capabilities=capabilities,
        role_models=role_models_pairs,
        commands=plan.commands or default_commands(),
        constraints=default_constraints(),
        conventions=default_conventions(),
        risks=tuple(list(plan.risks) + list(default_risks())),
    )

    return InitOptions(
        enable_chatgpt=used_oauth or any(d.capability == "backend" and d.enabled for d in plan.decisions),
        enable_frontend_agent="frontend" in enabled,
        enable_backend_agent="backend" in enabled,
        build_model=role_to_alias.get("build", "litellm/build-model"),
        frontend_model=role_to_alias.get("frontend", "litellm/frontend-model"),
        backend_model=role_to_alias.get("backend", "litellm/backend-model"),
        default_model=role_to_alias.get("default", "litellm/default-model"),
        deep_model=role_to_alias.get("deep", "litellm/deep-model"),
        extra_agents=plan.extra_agents,
        model_specs=tuple(model_specs),
        project_context=project_context,
    )


def _lookup_registry_entry(
    registry: Registry,
    choice: AgentDrivenModelChoice,
) -> tuple[ProviderEntry | OAuthProviderEntry, str, str]:
    for provider in registry.providers:
        if provider.key != choice.provider_key:
            continue
        for model in provider.models:
            if model.id == choice.model_id:
                return provider, model.litellm_model, model.id
        raise PlannerError(
            f"model '{choice.model_id}' nao existe no provider '{choice.provider_key}'"
        )
    for oauth in registry.oauth_providers:
        if oauth.key != choice.provider_key:
            continue
        for model in oauth.models:
            if model.id == choice.model_id:
                return oauth, model.litellm_model, model.id
        raise PlannerError(
            f"oauth model '{choice.model_id}' nao existe no provider '{choice.provider_key}'"
        )
    raise PlannerError(f"provider '{choice.provider_key}' nao existe no registry")


# ---------------------------------------------------------------------------
# Orquestracao + review loop + propose-with-fallback
# ---------------------------------------------------------------------------


def propose_plan_with_fallback(
    planner: PlannerClient,
    request: AgentDrivenRequest,
    *,
    on_fallback: callable | None = None,  # type: ignore[valid-type]
) -> tuple[AgentDrivenPlan, PlannerClient]:
    """Tenta planner.propose; em PlannerError, cai pra DeterministicPlannerClient."""
    try:
        plan = planner.propose(request)
        return plan, planner
    except PlannerError as exc:
        fallback = DeterministicPlannerClient()
        if on_fallback is not None:
            on_fallback(str(exc))
        plan = fallback.propose(request)
        return plan, fallback


def render_plan(plan: AgentDrivenPlan, planner_name: str) -> str:
    lines: list[str] = []
    lines.append("== Agent Driven Plan ==")
    lines.append("")
    lines.append(f"Planner: {planner_name}   |   Target: {plan.target_path}")
    lines.append("")
    if plan.detected_summary:
        lines.append("Projeto detectado:")
        for item in plan.detected_summary:
            lines.append(f"  - {item}")
        lines.append("")

    enabled = [d for d in plan.decisions if d.enabled]
    if enabled:
        lines.append("Capacidades propostas:")
        for decision in enabled:
            answers = ", ".join(f"{k}={v}" for k, v in decision.answers) if decision.answers else ""
            suffix = f" -> {answers}" if answers else ""
            lines.append(f"  [x] {_capability_label(decision.capability)}{suffix}")
        lines.append("")

    if plan.model_choices:
        lines.append("Modelos propostos:")
        for choice in plan.model_choices:
            lines.append(
                f"  {choice.role:<8} {choice.provider_key:<12} {choice.model_id:<24} -> {choice.litellm_alias}"
            )
        lines.append("")

    if plan.reasons:
        lines.append("Justificativas:")
        for reason in plan.reasons:
            lines.append(f"  - {reason}")
        lines.append("")

    if plan.risks:
        lines.append("Riscos:")
        for risk in plan.risks:
            lines.append(f"  - {risk}")
        lines.append("")

    if plan.commands:
        lines.append("Comandos sugeridos:")
        for command in plan.commands:
            lines.append(f"  - {command}")
        lines.append("")

    return "\n".join(lines)


def run_review_loop(
    plan: AgentDrivenPlan,
    planner: PlannerClient,
    request: AgentDrivenRequest,
    *,
    input_fn=typer.prompt,
    output_fn=typer.echo,
) -> AgentDrivenPlan | None:
    current = plan
    current_planner = planner
    while True:
        output_fn(render_plan(current, current_planner.name))
        output_fn("O que deseja fazer?")
        output_fn("  1. Aprovar e criar")
        output_fn("  2. Debater/alterar plano")
        output_fn("  3. Cancelar")
        choice = str(input_fn("Escolha", default="1")).strip()
        if choice == "1":
            return current
        if choice == "3":
            return None
        if choice == "2":
            feedback = str(input_fn("Descreva a alteracao desejada", default="")).strip()
            if not feedback:
                output_fn("Sem feedback; mantendo plano atual.")
                continue
            try:
                current = current_planner.revise(current, feedback, request)
            except PlannerError as exc:
                output_fn(f"[WARN] Falha no planner ao revisar ({exc}); usando determinístico.")
                current_planner = DeterministicPlannerClient()
                current = current_planner.revise(current, feedback, request)
            continue
        output_fn("Opcao invalida.")


# ---------------------------------------------------------------------------
# Helpers de payload do planner (parse + render)
# ---------------------------------------------------------------------------


def _render_user_message(request: AgentDrivenRequest) -> str:
    sections: list[str] = []
    sections.append(f"Locale: {request.locale}")
    sections.append(f"Objetivo do usuario: {request.user_objective.strip() or '(nao informado)'}")
    sections.append("Providers com chave detectada (apenas nomes, NUNCA valores): "
                    + (", ".join(request.available_providers) or "nenhum"))
    sections.append("Providers OAuth detectados: "
                    + (", ".join(request.detected_oauth) or "nenhum"))
    if request.scan:
        sections.append("\n# Scan do projeto")
        sections.append(request.scan.summary_markdown)
    return "\n".join(sections)


def plan_to_jsonable_public(plan: AgentDrivenPlan, *, include_raw: bool = False) -> dict:
    """Serializa um AgentDrivenPlan para output publico (CLI --json).

    Por default NAO inclui `raw_response` — ele e debug interno e nao deve
    sair pelo --json. Use `include_raw=True` apenas em testes/depuracao.
    """
    payload = _plan_to_jsonable(plan)
    if include_raw:
        payload["raw_response"] = plan.raw_response
    return payload


def _plan_to_jsonable(plan: AgentDrivenPlan) -> dict:
    return {
        "target_path": plan.target_path,
        "detected_summary": list(plan.detected_summary),
        "decisions": [
            {
                "capability": d.capability,
                "enabled": d.enabled,
                "answers": [list(pair) for pair in d.answers],
                "reason": d.reason,
            }
            for d in plan.decisions
        ],
        "model_choices": [
            {
                "role": c.role,
                "provider_key": c.provider_key,
                "model_id": c.model_id,
                "litellm_alias": c.litellm_alias,
                "reason": c.reason,
            }
            for c in plan.model_choices
        ],
        "extra_agents": [
            {
                "name": a.name,
                "description": a.description,
                "model": a.model,
                "prompt_file": a.prompt_file,
            }
            for a in plan.extra_agents
        ],
        "risks": list(plan.risks),
        "commands": list(plan.commands),
        "reasons": list(plan.reasons),
    }


def _parse_plan_payload(data: object, *, raw_response: str = "") -> AgentDrivenPlan:
    try:
        validate_plan_payload(data)
    except SchemaValidationError as exc:
        raise PlannerError(f"payload do planner falhou no schema: {exc}") from exc

    assert isinstance(data, dict)  # garantido pelo schema (type=object)

    target_path = str(data.get("target_path", ""))

    decisions = tuple(
        AgentDrivenDecision(
            capability=str(item.get("capability", "")),
            enabled=bool(item.get("enabled", False)),
            answers=tuple(
                (str(pair[0]), str(pair[1]))
                for pair in item.get("answers", [])
                if isinstance(pair, (list, tuple)) and len(pair) == 2
            ),
            reason=str(item.get("reason", "")),
        )
        for item in data.get("decisions", [])
        if isinstance(item, dict)
    )

    model_choices = tuple(
        AgentDrivenModelChoice(
            role=str(item.get("role", "")),
            provider_key=str(item.get("provider_key", "")),
            model_id=str(item.get("model_id", "")),
            litellm_alias=str(item.get("litellm_alias", "")),
            reason=str(item.get("reason", "")),
        )
        for item in data.get("model_choices", [])
        if isinstance(item, dict)
    )

    extra_agents = tuple(
        AgentSpec(
            name=str(item.get("name", "")),
            description=str(item.get("description", "")),
            model=str(item.get("model", "")),
            prompt_file=str(item.get("prompt_file", f"{item.get('name', 'agent')}.md")),
        )
        for item in data.get("extra_agents", [])
        if isinstance(item, dict) and item.get("name")
    )

    return AgentDrivenPlan(
        target_path=target_path,
        detected_summary=tuple(str(x) for x in data.get("detected_summary", [])),
        decisions=decisions,
        model_choices=model_choices,
        extra_agents=extra_agents,
        risks=tuple(str(x) for x in data.get("risks", [])),
        commands=tuple(str(x) for x in data.get("commands", [])),
        reasons=tuple(str(x) for x in data.get("reasons", [])),
        raw_response=raw_response,
    )


# ---------------------------------------------------------------------------
# Helpers gerais
# ---------------------------------------------------------------------------


CAPABILITY_LABELS: dict[str, str] = {
    "frontend": "Frontend/UI",
    "backend": "Backend/API",
    "audio": "Audio/speech",
    "video": "Video/multimodal",
    "mobile": "Mobile",
    "cli": "CLI/tooling",
    "desktop": "Desktop",
    "data": "Data/ETL",
    "ml": "ML/AI",
    "devops": "DevOps/infra",
    "qa": "QA/testes",
    "docs": "Documentacao",
    "security": "Security",
    "integrations": "Integracoes externas",
}


CAPABILITY_DESCRIPTIONS: dict[str, str] = {
    "frontend": "UI/UX, componentes visuais, CSS, acessibilidade",
    "backend": "APIs, banco, auth, infraestrutura server-side",
    "audio": "Captura, transcricao, traducao, TTS, diarizacao",
    "video": "Frames, analise visual, multimodalidade",
    "qa": "Estrategia de testes (unit/integration/e2e)",
    "devops": "CI/CD, infra, containers, deploy",
}


CAPABILITIES_WITH_DEDICATED_AGENT: frozenset[str] = frozenset({"frontend", "backend", "audio", "video"})


def _capability_label(key: str) -> str:
    return CAPABILITY_LABELS.get(key, key)


def _capability_description(key: str) -> str:
    return CAPABILITY_DESCRIPTIONS.get(key, _capability_label(key))


def _capability_has_dedicated_agent(key: str) -> bool:
    return key in CAPABILITIES_WITH_DEDICATED_AGENT


def cap_to_agent_name(key: str) -> str:
    return key


def _role_label(role: str) -> str:
    return {
        "build": "build/orquestrador",
        "frontend": "frontend/UI",
        "backend": "backend/API",
        "audio": "audio/speech",
        "video": "video/multimodal",
        "default": "default/rapido",
        "deep": "deep/raciocinio",
    }.get(role, role)


def _stack_label(enabled: set[str]) -> str:
    if not enabled:
        return "Projeto generico"
    return ", ".join(_capability_label(key) for key in sorted(enabled))


def _summary_text(plan: AgentDrivenPlan, enabled: set[str]) -> str:
    base = "Projeto inferido pelo Agent Driven Mode"
    if enabled:
        base += " com capacidades " + ", ".join(_capability_label(k) for k in sorted(enabled))
    base += "."
    if plan.detected_summary:
        base += " Detectado: " + " | ".join(plan.detected_summary[:3]) + "."
    return base


def _provider_display_name(registry: Registry, provider_key: str) -> str:
    for provider in registry.providers:
        if provider.key == provider_key:
            return provider.name
    for oauth in registry.oauth_providers:
        if oauth.key == provider_key:
            return oauth.name
    return provider_key


def _resolve_role_alias(capability: str, choices: tuple[AgentDrivenModelChoice, ...]) -> str:
    for choice in choices:
        if choice.role == capability:
            return choice.litellm_alias
    return f"litellm/{capability}-model"


def _qa_e2e_label(test_tools: str) -> str:
    if "playwright" in test_tools:
        return "Playwright"
    if "cypress" in test_tools:
        return "Cypress"
    return "Nenhuma"


# ---------------------------------------------------------------------------
# Prompt do planner (system message)
# ---------------------------------------------------------------------------


_PLANNER_RULES = """Voce e o "OpenCode Buddy Agent Driven Planner". Sua missao e propor um ProjectSpec valido para um scaffolder de projetos OpenCode + LiteLLM.

Sempre responda APENAS com um objeto JSON estrito (sem texto, sem markdown, sem comentarios) que valide contra o schema abaixo.

Regras inviolaveis:
1. NUNCA solicite ou inclua valores de variaveis de ambiente. Apenas seus NOMES.
2. NUNCA invente provider_key/model_id fora do registry fornecido pelo contexto.
3. Sempre justifique cada decision e cada model_choice (campo reason).
4. Prefira providers cuja chave foi detectada (`available_providers`).
5. Para projetos com sinais de audio/transcricao/whisper -> habilite capability "audio" e prefira modelos com `audio`/`video`/`multimodal` em recommended_for.
6. Para projetos com sinais de imagem/video/vision -> habilite "video" similarmente.
7. Para projetos sem chaves detectadas: ainda assim escolha modelos do registry e adicione um item em "risks" pedindo .env.
8. Sempre inclua roles "build", "default" e "deep" em model_choices, mesmo se as capacidades especificas nao estiverem habilitadas.
9. Mantenha respostas curtas e operacionais: o JSON sera consumido por codigo, nao por humanos.
10. Nao adicione campos fora do schema (additionalProperties: false). Em particular, NAO inclua "raw_response" - esse campo e debug interno.

# Schema JSON formal da resposta

"""


PLANNER_SYSTEM_PROMPT = _PLANNER_RULES + json.dumps(PLAN_JSON_SCHEMA, ensure_ascii=False, indent=2)
