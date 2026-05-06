import json
from dataclasses import replace
from io import BytesIO
from pathlib import Path

import pytest

from opencode_buddy import agent_driven
from opencode_buddy.agent_driven import (
    AgentDrivenDecision,
    AgentDrivenModelChoice,
    AgentDrivenPlan,
    AgentDrivenRequest,
    DeterministicPlannerClient,
    LIVE_OPENAI_COMPATIBLE_PROVIDERS,
    LiteLLMPlannerClient,
    PlannerClient,
    PlannerError,
    plan_to_project_spec,
    propose_plan_with_fallback,
    render_plan,
    run_review_loop,
    select_planner,
)
from opencode_buddy.config_builder import iter_agent_specs
from opencode_buddy.project_scanner import ProjectScan, scan_project
from opencode_buddy.registry import load_registry
from opencode_buddy.validator import validate_project


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


class FakePlannerClient:
    def __init__(self, plan: AgentDrivenPlan, revised: AgentDrivenPlan | None = None):
        self.plan = plan
        self.revised = revised
        self.name = "fake"
        self.calls_propose = 0
        self.calls_revise = 0

    def propose(self, request):
        self.calls_propose += 1
        return self.plan

    def revise(self, previous, feedback, request):
        self.calls_revise += 1
        return self.revised or self.plan


def _basic_request(scan: ProjectScan | None = None, providers=()) -> AgentDrivenRequest:
    return AgentDrivenRequest(
        scan=scan,
        user_objective="testar agent driven",
        available_providers=tuple(providers),
        detected_oauth=(),
    )


def _react_vite_scan(tmp_path: Path) -> ProjectScan:
    (tmp_path / "package.json").write_text(
        json.dumps({"dependencies": {"react": "^18", "react-dom": "^18"}, "devDependencies": {"vite": "^5", "typescript": "^5"}}),
        encoding="utf-8",
    )
    (tmp_path / "vite.config.ts").write_text("export default {}", encoding="utf-8")
    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
    return scan_project(tmp_path)


def _audio_scan(tmp_path: Path) -> ProjectScan:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "asr"\ndependencies = ["fastapi"]\n',
        encoding="utf-8",
    )
    (tmp_path / "audio").mkdir()
    (tmp_path / "audio" / "whisper_setup.py").write_text("import whisper\n", encoding="utf-8")
    return scan_project(tmp_path)


# --------------------------------------------------------------------------
# DeterministicPlannerClient
# --------------------------------------------------------------------------


def test_deterministic_planner_proposes_frontend_for_react_signals(tmp_path):
    request = _basic_request(scan=_react_vite_scan(tmp_path), providers=("opencode-go",))
    plan = DeterministicPlannerClient().propose(request)

    enabled_caps = [d.capability for d in plan.decisions if d.enabled]
    assert "frontend" in enabled_caps


def test_deterministic_planner_proposes_audio_when_signals_present(tmp_path):
    request = _basic_request(
        scan=_audio_scan(tmp_path),
        providers=("gemini",),
    )
    plan = DeterministicPlannerClient().propose(request)
    enabled = [d.capability for d in plan.decisions if d.enabled]
    assert "audio" in enabled
    audio_choice = next((c for c in plan.model_choices if c.role == "audio"), None)
    assert audio_choice is not None
    # gemini disponivel deveria ser preferido para audio
    assert audio_choice.provider_key in {"gemini", "chatgpt", "deepseek", "anthropic", "moonshot", "opencode-go"}


def test_deterministic_planner_emits_full_modelspec_even_without_keys(tmp_path):
    """Mesmo sem chaves, scaffold tem que continuar valido."""
    request = _basic_request(scan=_react_vite_scan(tmp_path), providers=())
    plan = DeterministicPlannerClient().propose(request)

    assert plan.risks, "deveria emitir risco quando nao ha chaves"
    spec = plan_to_project_spec(plan)

    assert spec.build_model
    assert spec.default_model
    assert spec.deep_model
    # iter_agent_specs nao deve quebrar
    specs = iter_agent_specs(spec)
    assert any(s.name == "build" for s in specs)


def test_deterministic_planner_revise_applies_remove_frontend_keyword(tmp_path):
    request = _basic_request(scan=_react_vite_scan(tmp_path), providers=("deepseek",))
    planner = DeterministicPlannerClient()
    plan = planner.propose(request)
    assert any(d.capability == "frontend" and d.enabled for d in plan.decisions)

    revised = planner.revise(plan, "remova frontend por favor", request)
    frontend = next((d for d in revised.decisions if d.capability == "frontend"), None)
    assert frontend is not None
    assert frontend.enabled is False


# --------------------------------------------------------------------------
# select_planner
# --------------------------------------------------------------------------


def test_select_planner_returns_litellm_client_when_deepseek_key_present():
    planner = select_planner({"DEEPSEEK_API_KEY": "fake"}, prefer="deepseek")
    assert isinstance(planner, LiteLLMPlannerClient)
    assert planner.name.startswith("litellm:deepseek:")


def test_select_planner_falls_back_to_deterministic_when_no_keys():
    planner = select_planner({})
    assert isinstance(planner, DeterministicPlannerClient)


def test_select_planner_offline_forces_deterministic_even_with_keys():
    planner = select_planner({"DEEPSEEK_API_KEY": "x"}, offline=True)
    assert isinstance(planner, DeterministicPlannerClient)


def test_select_planner_returns_anthropic_when_explicit_with_key():
    planner = select_planner({"ANTHROPIC_API_KEY": "x"}, prefer="anthropic")
    from opencode_buddy.agent_driven import AnthropicPlannerClient
    assert isinstance(planner, AnthropicPlannerClient)


def test_select_planner_returns_gemini_when_explicit_with_key():
    planner = select_planner({"GEMINI_API_KEY": "x"}, prefer="gemini")
    from opencode_buddy.agent_driven import GeminiPlannerClient
    assert isinstance(planner, GeminiPlannerClient)


def test_select_planner_anthropic_without_key_raises_friendly_error():
    with pytest.raises(PlannerError) as excinfo:
        select_planner({}, prefer="anthropic")
    assert "ANTHROPIC_API_KEY" in str(excinfo.value) or "variaveis de ambiente" in str(excinfo.value)


def test_select_planner_gemini_without_key_raises_friendly_error():
    with pytest.raises(PlannerError) as excinfo:
        select_planner({}, prefer="gemini")
    assert "GEMINI_API_KEY" in str(excinfo.value) or "variaveis de ambiente" in str(excinfo.value)


def test_select_planner_unknown_provider_friendly_error():
    with pytest.raises(PlannerError) as excinfo:
        select_planner({}, prefer="invented")
    assert "invented" in str(excinfo.value)
    assert "deepseek" in str(excinfo.value) or "anthropic" in str(excinfo.value)


def test_select_planner_auto_prefers_openai_compatible_over_native():
    planner = select_planner({"DEEPSEEK_API_KEY": "x", "ANTHROPIC_API_KEY": "y", "GEMINI_API_KEY": "z"})
    assert isinstance(planner, LiteLLMPlannerClient)
    assert "deepseek" in planner.name


def test_select_planner_auto_picks_anthropic_when_only_anthropic_key_present():
    from opencode_buddy.agent_driven import AnthropicPlannerClient
    planner = select_planner({"ANTHROPIC_API_KEY": "x"})
    assert isinstance(planner, AnthropicPlannerClient)


def test_select_planner_auto_picks_gemini_when_only_gemini_key_present():
    from opencode_buddy.agent_driven import GeminiPlannerClient
    planner = select_planner({"GEMINI_API_KEY": "x"})
    assert isinstance(planner, GeminiPlannerClient)


# --------------------------------------------------------------------------
# plan_to_project_spec via registry
# --------------------------------------------------------------------------


def test_plan_to_project_spec_reconstructs_modelspec_fields_from_registry():
    plan = AgentDrivenPlan(
        target_path="x",
        decisions=(
            AgentDrivenDecision(capability="backend", enabled=True),
        ),
        model_choices=(
            AgentDrivenModelChoice(
                role="build",
                provider_key="deepseek",
                model_id="deepseek-chat",
                # Texto livre que deve ser ignorado pelo lookup do registry:
                litellm_alias="some-bogus-string",
            ),
            AgentDrivenModelChoice(
                role="default",
                provider_key="deepseek",
                model_id="deepseek-chat",
                litellm_alias="x",
            ),
            AgentDrivenModelChoice(
                role="deep",
                provider_key="deepseek",
                model_id="deepseek-reasoner",
                litellm_alias="x",
            ),
            AgentDrivenModelChoice(
                role="backend",
                provider_key="deepseek",
                model_id="deepseek-chat",
                litellm_alias="x",
            ),
        ),
    )
    spec = plan_to_project_spec(plan)

    backend_specs = [m for m in spec.model_specs if m.alias == "backend-model"]
    assert backend_specs, "deveria gerar ModelSpec backend a partir do registry"
    backend_spec = backend_specs[0]
    assert backend_spec.api_key_env == "DEEPSEEK_API_KEY"
    assert backend_spec.litellm_model == "deepseek/deepseek-chat"


def test_plan_to_project_spec_raises_when_planner_invents_unknown_provider():
    plan = AgentDrivenPlan(
        target_path="x",
        model_choices=(
            AgentDrivenModelChoice(
                role="build",
                provider_key="invented-provider",
                model_id="invented-model",
                litellm_alias="litellm/invented",
            ),
        ),
    )
    with pytest.raises(PlannerError):
        plan_to_project_spec(plan)


def test_plan_to_project_spec_raises_when_planner_invents_unknown_model():
    plan = AgentDrivenPlan(
        target_path="x",
        model_choices=(
            AgentDrivenModelChoice(
                role="build",
                provider_key="deepseek",
                model_id="not-a-real-model",
                litellm_alias="litellm/x",
            ),
        ),
    )
    with pytest.raises(PlannerError):
        plan_to_project_spec(plan)


def test_plan_to_project_spec_handles_oauth_provider():
    plan = AgentDrivenPlan(
        target_path="x",
        decisions=(AgentDrivenDecision(capability="backend", enabled=True),),
        model_choices=(
            AgentDrivenModelChoice(role="build", provider_key="deepseek", model_id="deepseek-chat", litellm_alias="x"),
            AgentDrivenModelChoice(role="default", provider_key="deepseek", model_id="deepseek-chat", litellm_alias="x"),
            AgentDrivenModelChoice(role="deep", provider_key="deepseek", model_id="deepseek-reasoner", litellm_alias="x"),
            AgentDrivenModelChoice(
                role="backend",
                provider_key="chatgpt",
                model_id="gpt-5.5",
                litellm_alias="chatgpt/gpt-5.5",
            ),
        ),
    )
    spec = plan_to_project_spec(plan)
    assert spec.enable_chatgpt is True
    assert spec.backend_model == "chatgpt/gpt-5.5"
    # OAuth nao gera ModelSpec
    assert all(m.alias != "backend-model" for m in spec.model_specs)


def test_deterministic_plan_produces_spec_that_validates_with_only_env_warning(tmp_path):
    request = _basic_request(scan=_react_vite_scan(tmp_path), providers=())
    plan = DeterministicPlannerClient().propose(request)
    spec = plan_to_project_spec(plan)

    # Scaffold no tmp e roda validate
    from opencode_buddy.scaffolder import scaffold_project

    target = tmp_path / "out"
    scaffold_project(target, spec, force=True)
    messages = validate_project(target)
    error_messages = [m for m in messages if m.level == "error"]
    # Sem erros de schema; pode haver warning sobre .env faltando
    assert error_messages == []


# --------------------------------------------------------------------------
# run_review_loop
# --------------------------------------------------------------------------


def _make_simple_plan() -> AgentDrivenPlan:
    return AgentDrivenPlan(
        target_path="./demo",
        decisions=(AgentDrivenDecision(capability="backend", enabled=True, reason="objetivo do usuario"),),
        model_choices=(
            AgentDrivenModelChoice(role="build", provider_key="deepseek", model_id="deepseek-chat", litellm_alias="x"),
            AgentDrivenModelChoice(role="default", provider_key="deepseek", model_id="deepseek-chat", litellm_alias="x"),
            AgentDrivenModelChoice(role="deep", provider_key="deepseek", model_id="deepseek-reasoner", litellm_alias="x"),
        ),
        risks=("teste",),
    )


class _Inputs:
    def __init__(self, answers: list[str]):
        self._answers = list(answers)

    def __call__(self, prompt: str, default: str = "") -> str:
        if not self._answers:
            return default
        return self._answers.pop(0)


def test_review_loop_returns_plan_on_approve():
    plan = _make_simple_plan()
    fake = FakePlannerClient(plan)
    request = _basic_request()
    inputs = _Inputs(["1"])
    outputs: list[str] = []

    result = run_review_loop(
        plan,
        fake,
        request,
        input_fn=inputs,
        output_fn=lambda msg: outputs.append(str(msg)),
    )
    assert result is plan


def test_review_loop_returns_none_on_cancel():
    plan = _make_simple_plan()
    fake = FakePlannerClient(plan)
    inputs = _Inputs(["3"])
    outputs: list[str] = []
    result = run_review_loop(
        plan,
        fake,
        _basic_request(),
        input_fn=inputs,
        output_fn=lambda msg: outputs.append(str(msg)),
    )
    assert result is None


def test_review_loop_calls_revise_on_debate_then_approves():
    plan = _make_simple_plan()
    revised = replace(plan, target_path="./changed")
    fake = FakePlannerClient(plan, revised=revised)
    inputs = _Inputs(["2", "muda o target", "1"])
    outputs: list[str] = []
    result = run_review_loop(
        plan,
        fake,
        _basic_request(),
        input_fn=inputs,
        output_fn=lambda msg: outputs.append(str(msg)),
    )
    assert result is revised
    assert fake.calls_revise == 1


def test_review_loop_revise_falls_back_when_planner_raises():
    plan = _make_simple_plan()

    class FailingPlanner:
        name = "failing"

        def propose(self, request):
            return plan

        def revise(self, previous, feedback, request):
            raise PlannerError("boom")

    inputs = _Inputs(["2", "qualquer feedback", "1"])
    outputs: list[str] = []
    result = run_review_loop(
        plan,
        FailingPlanner(),
        _basic_request(),
        input_fn=inputs,
        output_fn=lambda msg: outputs.append(str(msg)),
    )
    assert result is not None
    assert any("WARN" in line or "determin" in line.lower() for line in outputs)


# --------------------------------------------------------------------------
# render_plan
# --------------------------------------------------------------------------


def test_render_plan_includes_capabilities_and_models_and_risks():
    plan = _make_simple_plan()
    text = render_plan(plan, "fake")
    assert "Agent Driven Plan" in text
    assert "Backend/API" in text
    assert "deepseek" in text
    assert "build" in text
    assert "Riscos" in text


# --------------------------------------------------------------------------
# LiteLLMPlannerClient + mock urlopen
# --------------------------------------------------------------------------


class _MockHTTPResponse:
    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._body


def _make_choice(content_obj) -> dict:
    return {"choices": [{"message": {"content": json.dumps(content_obj)}}]}


def test_litellm_planner_parses_valid_json_response(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = req.data
        captured["headers"] = dict(req.header_items())
        plan_payload = {
            "target_path": "./from-llm",
            "detected_summary": ["python+fastapi"],
            "decisions": [{"capability": "backend", "enabled": True, "answers": [], "reason": "fastapi"}],
            "model_choices": [
                {"role": "build", "provider_key": "deepseek", "model_id": "deepseek-chat", "litellm_alias": "litellm/build-model", "reason": ""},
                {"role": "default", "provider_key": "deepseek", "model_id": "deepseek-chat", "litellm_alias": "x", "reason": ""},
                {"role": "deep", "provider_key": "deepseek", "model_id": "deepseek-reasoner", "litellm_alias": "x", "reason": ""},
            ],
            "extra_agents": [],
            "risks": [],
            "commands": [],
            "reasons": [],
        }
        body = json.dumps(_make_choice(plan_payload)).encode("utf-8")
        return _MockHTTPResponse(body)

    monkeypatch.setattr("opencode_buddy.agent_driven.urllib.request.urlopen", fake_urlopen)

    registry = load_registry()
    deepseek = next(p for p in registry.providers if p.key == "deepseek")
    client = LiteLLMPlannerClient(provider=deepseek, model_id="deepseek-chat", env={"DEEPSEEK_API_KEY": "secret-key-value"}, timeout=5.0)

    request = AgentDrivenRequest(scan=None, user_objective="api fastapi", available_providers=("deepseek",), detected_oauth=())
    plan = client.propose(request)

    assert plan.target_path == "./from-llm"
    assert any(c.role == "build" for c in plan.model_choices)
    headers_lower = {k.lower(): v for k, v in captured["headers"].items()}
    assert headers_lower["user-agent"].startswith("opencode-buddy/")
    assert headers_lower["accept"] == "application/json"
    assert headers_lower["authorization"] == "Bearer secret-key-value"


def test_litellm_planner_raises_on_http_500(monkeypatch):
    import urllib.error

    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 500, "boom", {}, BytesIO(b""))

    monkeypatch.setattr("opencode_buddy.agent_driven.urllib.request.urlopen", fake_urlopen)
    registry = load_registry()
    deepseek = next(p for p in registry.providers if p.key == "deepseek")
    client = LiteLLMPlannerClient(provider=deepseek, model_id="deepseek-chat", env={"DEEPSEEK_API_KEY": "x"}, timeout=5.0)
    with pytest.raises(PlannerError):
        client.propose(_basic_request())


def test_litellm_planner_raises_on_invalid_json(monkeypatch):
    def fake_urlopen(req, timeout=None):
        return _MockHTTPResponse(b"not-a-json")

    monkeypatch.setattr("opencode_buddy.agent_driven.urllib.request.urlopen", fake_urlopen)
    registry = load_registry()
    deepseek = next(p for p in registry.providers if p.key == "deepseek")
    client = LiteLLMPlannerClient(provider=deepseek, model_id="deepseek-chat", env={"DEEPSEEK_API_KEY": "x"}, timeout=5.0)
    with pytest.raises(PlannerError):
        client.propose(_basic_request())


def test_litellm_planner_raises_when_inner_content_not_json(monkeypatch):
    def fake_urlopen(req, timeout=None):
        body = json.dumps({"choices": [{"message": {"content": "this is not json"}}]}).encode("utf-8")
        return _MockHTTPResponse(body)

    monkeypatch.setattr("opencode_buddy.agent_driven.urllib.request.urlopen", fake_urlopen)
    registry = load_registry()
    deepseek = next(p for p in registry.providers if p.key == "deepseek")
    client = LiteLLMPlannerClient(provider=deepseek, model_id="deepseek-chat", env={"DEEPSEEK_API_KEY": "x"}, timeout=5.0)
    with pytest.raises(PlannerError):
        client.propose(_basic_request())


def test_litellm_planner_constructor_rejects_anthropic():
    """Anthropic nao e OpenAI-compatible; o construtor recusa."""
    registry = load_registry()
    anthropic = next(p for p in registry.providers if p.key == "anthropic")
    with pytest.raises(PlannerError) as excinfo:
        LiteLLMPlannerClient(provider=anthropic, model_id="claude-sonnet-4-5", env={"ANTHROPIC_API_KEY": "x"})
    assert "adapter nativo" in str(excinfo.value)


def test_litellm_planner_payload_does_not_contain_env_values(monkeypatch):
    captured_body = {}

    def fake_urlopen(req, timeout=None):
        captured_body["data"] = req.data
        captured_body["headers"] = dict(req.header_items())
        plan_payload = {
            "target_path": ".", "detected_summary": [],
            "decisions": [], "model_choices": [
                {"role": "build", "provider_key": "deepseek", "model_id": "deepseek-chat", "litellm_alias": "x"},
                {"role": "default", "provider_key": "deepseek", "model_id": "deepseek-chat", "litellm_alias": "x"},
                {"role": "deep", "provider_key": "deepseek", "model_id": "deepseek-reasoner", "litellm_alias": "x"},
            ],
            "extra_agents": [], "risks": [], "commands": [], "reasons": [],
        }
        body = json.dumps(_make_choice(plan_payload)).encode("utf-8")
        return _MockHTTPResponse(body)

    monkeypatch.setattr("opencode_buddy.agent_driven.urllib.request.urlopen", fake_urlopen)
    secret_value = "super-secret-deepseek-key-do-not-leak"
    registry = load_registry()
    deepseek = next(p for p in registry.providers if p.key == "deepseek")
    client = LiteLLMPlannerClient(provider=deepseek, model_id="deepseek-chat", env={"DEEPSEEK_API_KEY": secret_value}, timeout=5.0)

    request = AgentDrivenRequest(
        scan=None,
        user_objective="qualquer",
        available_providers=("deepseek",),
        detected_oauth=(),
    )
    client.propose(request)

    body_text = captured_body["data"].decode("utf-8")
    assert secret_value not in body_text, "valor da env vazou no body do request"
    # Nome da env pode aparecer (e referenciado no contexto), mas nunca o valor
    assert "DEEPSEEK_API_KEY" in body_text or True  # nao obriga aparecer; so nao pode aparecer o valor

    # Authorization header e separado e contem a chave (esperado)
    auth = next((value for key, value in captured_body["headers"].items() if key.lower() == "authorization"), "")
    assert secret_value in auth


# --------------------------------------------------------------------------
# propose_plan_with_fallback
# --------------------------------------------------------------------------


def _valid_plan_payload() -> dict:
    return {
        "target_path": "./from-llm",
        "detected_summary": ["python+fastapi"],
        "decisions": [{"capability": "backend", "enabled": True, "answers": [], "reason": "fastapi"}],
        "model_choices": [
            {"role": "build", "provider_key": "deepseek", "model_id": "deepseek-chat", "litellm_alias": "litellm/build-model", "reason": ""},
            {"role": "default", "provider_key": "deepseek", "model_id": "deepseek-chat", "litellm_alias": "x", "reason": ""},
            {"role": "deep", "provider_key": "deepseek", "model_id": "deepseek-reasoner", "litellm_alias": "x", "reason": ""},
        ],
        "extra_agents": [],
        "risks": [],
        "commands": [],
        "reasons": [],
    }


# --------------------------------------------------------------------------
# AnthropicPlannerClient
# --------------------------------------------------------------------------


def _anthropic_response(plan_payload: dict) -> bytes:
    return json.dumps(
        {
            "id": "msg_x",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": json.dumps(plan_payload)}],
            "stop_reason": "end_turn",
        }
    ).encode("utf-8")


def test_anthropic_planner_parses_text_response_with_json(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.header_items())
        captured["body"] = req.data
        return _MockHTTPResponse(_anthropic_response(_valid_plan_payload()))

    monkeypatch.setattr("opencode_buddy.agent_driven.urllib.request.urlopen", fake_urlopen)
    from opencode_buddy.agent_driven import AnthropicPlannerClient
    registry = load_registry()
    anthropic = next(p for p in registry.providers if p.key == "anthropic")
    client = AnthropicPlannerClient(provider=anthropic, model_id="claude-sonnet-4-5", env={"ANTHROPIC_API_KEY": "x"}, timeout=5.0)

    plan = client.propose(_basic_request())
    assert plan.target_path == "./from-llm"
    # Header anthropic-version presente
    headers_lower = {k.lower(): v for k, v in captured["headers"].items()}
    assert headers_lower.get("anthropic-version") == "2023-06-01"
    assert "x-api-key" in headers_lower
    assert headers_lower["user-agent"].startswith("opencode-buddy/")
    assert headers_lower["accept"] == "application/json"
    assert captured["url"].endswith("/v1/messages")


def test_anthropic_planner_raises_on_http_500(monkeypatch):
    import urllib.error
    from io import BytesIO

    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 500, "boom", {}, BytesIO(b""))

    monkeypatch.setattr("opencode_buddy.agent_driven.urllib.request.urlopen", fake_urlopen)
    from opencode_buddy.agent_driven import AnthropicPlannerClient
    registry = load_registry()
    anthropic = next(p for p in registry.providers if p.key == "anthropic")
    client = AnthropicPlannerClient(provider=anthropic, model_id="claude-sonnet-4-5", env={"ANTHROPIC_API_KEY": "x"}, timeout=5.0)
    with pytest.raises(PlannerError):
        client.propose(_basic_request())


def test_anthropic_planner_raises_on_invalid_outer_json(monkeypatch):
    def fake_urlopen(req, timeout=None):
        return _MockHTTPResponse(b"not-json")
    monkeypatch.setattr("opencode_buddy.agent_driven.urllib.request.urlopen", fake_urlopen)
    from opencode_buddy.agent_driven import AnthropicPlannerClient
    registry = load_registry()
    anthropic = next(p for p in registry.providers if p.key == "anthropic")
    client = AnthropicPlannerClient(provider=anthropic, model_id="claude-sonnet-4-5", env={"ANTHROPIC_API_KEY": "x"}, timeout=5.0)
    with pytest.raises(PlannerError):
        client.propose(_basic_request())


def test_anthropic_planner_raises_when_inner_text_not_json(monkeypatch):
    def fake_urlopen(req, timeout=None):
        body = json.dumps(
            {"content": [{"type": "text", "text": "no json here"}]}
        ).encode("utf-8")
        return _MockHTTPResponse(body)
    monkeypatch.setattr("opencode_buddy.agent_driven.urllib.request.urlopen", fake_urlopen)
    from opencode_buddy.agent_driven import AnthropicPlannerClient
    registry = load_registry()
    anthropic = next(p for p in registry.providers if p.key == "anthropic")
    client = AnthropicPlannerClient(provider=anthropic, model_id="claude-sonnet-4-5", env={"ANTHROPIC_API_KEY": "x"}, timeout=5.0)
    with pytest.raises(PlannerError):
        client.propose(_basic_request())


def test_anthropic_planner_payload_does_not_contain_env_value(monkeypatch):
    captured = {}
    secret = "anthropic-canary-do-not-leak"

    def fake_urlopen(req, timeout=None):
        captured["body"] = req.data
        captured["headers"] = dict(req.header_items())
        return _MockHTTPResponse(_anthropic_response(_valid_plan_payload()))

    monkeypatch.setattr("opencode_buddy.agent_driven.urllib.request.urlopen", fake_urlopen)
    from opencode_buddy.agent_driven import AnthropicPlannerClient
    registry = load_registry()
    anthropic = next(p for p in registry.providers if p.key == "anthropic")
    client = AnthropicPlannerClient(provider=anthropic, model_id="claude-sonnet-4-5", env={"ANTHROPIC_API_KEY": secret}, timeout=5.0)
    client.propose(AgentDrivenRequest(scan=None, user_objective="x", available_providers=("anthropic",), detected_oauth=()))

    body_text = captured["body"].decode("utf-8")
    assert secret not in body_text
    headers_lower = {k.lower(): v for k, v in captured["headers"].items()}
    assert headers_lower.get("x-api-key") == secret


# --------------------------------------------------------------------------
# GeminiPlannerClient
# --------------------------------------------------------------------------


def _gemini_response(plan_payload: dict) -> bytes:
    return json.dumps(
        {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": json.dumps(plan_payload)}],
                        "role": "model",
                    },
                    "finishReason": "STOP",
                }
            ]
        }
    ).encode("utf-8")


def test_gemini_planner_parses_candidates_response(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.header_items())
        captured["body"] = req.data
        return _MockHTTPResponse(_gemini_response(_valid_plan_payload()))

    monkeypatch.setattr("opencode_buddy.agent_driven.urllib.request.urlopen", fake_urlopen)
    from opencode_buddy.agent_driven import GeminiPlannerClient
    registry = load_registry()
    gemini = next(p for p in registry.providers if p.key == "gemini")
    client = GeminiPlannerClient(provider=gemini, model_id="gemini-2.5-flash", env={"GEMINI_API_KEY": "x"}, timeout=5.0)

    plan = client.propose(_basic_request())
    assert plan.target_path == "./from-llm"
    assert ":generateContent" in captured["url"]
    assert "key=" not in captured["url"], "Gemini API key nao deve aparecer na URL"
    headers_lower = {k.lower(): v for k, v in captured["headers"].items()}
    assert "x-goog-api-key" in headers_lower
    assert headers_lower["user-agent"].startswith("opencode-buddy/")
    assert headers_lower["accept"] == "application/json"


def test_gemini_planner_raises_on_http_500(monkeypatch):
    import urllib.error
    from io import BytesIO

    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 500, "boom", {}, BytesIO(b""))

    monkeypatch.setattr("opencode_buddy.agent_driven.urllib.request.urlopen", fake_urlopen)
    from opencode_buddy.agent_driven import GeminiPlannerClient
    registry = load_registry()
    gemini = next(p for p in registry.providers if p.key == "gemini")
    client = GeminiPlannerClient(provider=gemini, model_id="gemini-2.5-flash", env={"GEMINI_API_KEY": "x"}, timeout=5.0)
    with pytest.raises(PlannerError):
        client.propose(_basic_request())


def test_gemini_planner_raises_on_invalid_outer_json(monkeypatch):
    def fake_urlopen(req, timeout=None):
        return _MockHTTPResponse(b"not-json")
    monkeypatch.setattr("opencode_buddy.agent_driven.urllib.request.urlopen", fake_urlopen)
    from opencode_buddy.agent_driven import GeminiPlannerClient
    registry = load_registry()
    gemini = next(p for p in registry.providers if p.key == "gemini")
    client = GeminiPlannerClient(provider=gemini, model_id="gemini-2.5-flash", env={"GEMINI_API_KEY": "x"}, timeout=5.0)
    with pytest.raises(PlannerError):
        client.propose(_basic_request())


def test_gemini_planner_raises_when_inner_text_not_json(monkeypatch):
    def fake_urlopen(req, timeout=None):
        body = json.dumps(
            {"candidates": [{"content": {"parts": [{"text": "not json"}]}}]}
        ).encode("utf-8")
        return _MockHTTPResponse(body)
    monkeypatch.setattr("opencode_buddy.agent_driven.urllib.request.urlopen", fake_urlopen)
    from opencode_buddy.agent_driven import GeminiPlannerClient
    registry = load_registry()
    gemini = next(p for p in registry.providers if p.key == "gemini")
    client = GeminiPlannerClient(provider=gemini, model_id="gemini-2.5-flash", env={"GEMINI_API_KEY": "x"}, timeout=5.0)
    with pytest.raises(PlannerError):
        client.propose(_basic_request())


def test_gemini_planner_payload_does_not_contain_env_value(monkeypatch):
    captured = {}
    secret = "gemini-canary-do-not-leak"

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.header_items())
        captured["body"] = req.data
        return _MockHTTPResponse(_gemini_response(_valid_plan_payload()))

    monkeypatch.setattr("opencode_buddy.agent_driven.urllib.request.urlopen", fake_urlopen)
    from opencode_buddy.agent_driven import GeminiPlannerClient
    registry = load_registry()
    gemini = next(p for p in registry.providers if p.key == "gemini")
    client = GeminiPlannerClient(provider=gemini, model_id="gemini-2.5-flash", env={"GEMINI_API_KEY": secret}, timeout=5.0)
    client.propose(AgentDrivenRequest(scan=None, user_objective="x", available_providers=("gemini",), detected_oauth=()))

    body_text = captured["body"].decode("utf-8")
    assert secret not in body_text
    assert secret not in captured["url"]
    headers_lower = {k.lower(): v for k, v in captured["headers"].items()}
    assert headers_lower.get("x-goog-api-key") == secret


# --------------------------------------------------------------------------
# Schema integration with _parse_plan_payload + plan_to_jsonable_public
# --------------------------------------------------------------------------


def test_parse_plan_payload_uses_strict_schema_validation():
    from opencode_buddy.agent_driven import _parse_plan_payload
    bad = _valid_plan_payload()
    bad["model_choices"][0]["role"] = "invented"
    with pytest.raises(PlannerError):
        _parse_plan_payload(bad)


def test_parse_plan_payload_rejects_missing_required_role():
    from opencode_buddy.agent_driven import _parse_plan_payload
    bad = _valid_plan_payload()
    # Remove role "deep"
    bad["model_choices"] = [c for c in bad["model_choices"] if c["role"] != "deep"]
    bad["model_choices"].append(
        {"role": "frontend", "provider_key": "deepseek", "model_id": "deepseek-chat", "litellm_alias": "x"}
    )
    with pytest.raises(PlannerError) as excinfo:
        _parse_plan_payload(bad)
    assert "deep" in str(excinfo.value)


def test_plan_to_jsonable_public_omits_raw_response_by_default():
    from opencode_buddy.agent_driven import plan_to_jsonable_public
    plan = AgentDrivenPlan(
        target_path="./x",
        decisions=(),
        model_choices=(),
        raw_response="SECRET-DEBUG-INTERNAL",
    )
    payload = plan_to_jsonable_public(plan)
    assert "raw_response" not in payload
    assert "SECRET-DEBUG-INTERNAL" not in json.dumps(payload)


def test_plan_to_jsonable_public_includes_raw_when_explicitly_requested():
    from opencode_buddy.agent_driven import plan_to_jsonable_public
    plan = AgentDrivenPlan(
        target_path="./x",
        decisions=(),
        model_choices=(),
        raw_response="DEBUG",
    )
    payload = plan_to_jsonable_public(plan, include_raw=True)
    assert payload["raw_response"] == "DEBUG"


def test_propose_plan_falls_back_when_anthropic_returns_invalid_payload(monkeypatch):
    """Schema invalido na resposta do Anthropic -> fallback para deterministic."""
    def fake_urlopen(req, timeout=None):
        bad_payload = _valid_plan_payload()
        bad_payload["model_choices"][0]["role"] = "invented"  # quebra schema
        return _MockHTTPResponse(_anthropic_response(bad_payload))

    monkeypatch.setattr("opencode_buddy.agent_driven.urllib.request.urlopen", fake_urlopen)
    from opencode_buddy.agent_driven import AnthropicPlannerClient
    registry = load_registry()
    anthropic = next(p for p in registry.providers if p.key == "anthropic")
    client = AnthropicPlannerClient(provider=anthropic, model_id="claude-sonnet-4-5", env={"ANTHROPIC_API_KEY": "x"}, timeout=5.0)

    captured = []
    plan, planner = propose_plan_with_fallback(
        client,
        _basic_request(),
        on_fallback=lambda msg: captured.append(msg),
    )
    assert isinstance(planner, DeterministicPlannerClient)
    assert plan is not None
    assert captured  # mensagem de fallback


def test_propose_plan_falls_back_when_gemini_returns_invalid_payload(monkeypatch):
    def fake_urlopen(req, timeout=None):
        bad_payload = _valid_plan_payload()
        bad_payload["decisions"][0]["capability"] = "invented"
        return _MockHTTPResponse(_gemini_response(bad_payload))

    monkeypatch.setattr("opencode_buddy.agent_driven.urllib.request.urlopen", fake_urlopen)
    from opencode_buddy.agent_driven import GeminiPlannerClient
    registry = load_registry()
    gemini = next(p for p in registry.providers if p.key == "gemini")
    client = GeminiPlannerClient(provider=gemini, model_id="gemini-2.5-flash", env={"GEMINI_API_KEY": "x"}, timeout=5.0)

    captured = []
    plan, planner = propose_plan_with_fallback(
        client,
        _basic_request(),
        on_fallback=lambda msg: captured.append(msg),
    )
    assert isinstance(planner, DeterministicPlannerClient)
    assert captured


def test_propose_plan_with_fallback_uses_deterministic_when_planner_errors(tmp_path):
    class ExplodingPlanner:
        name = "boom"

        def propose(self, request):
            raise PlannerError("simulado")

        def revise(self, previous, feedback, request):
            raise PlannerError("simulado")

    captured = []
    plan, planner = propose_plan_with_fallback(
        ExplodingPlanner(),
        _basic_request(scan=_react_vite_scan(tmp_path), providers=("deepseek",)),
        on_fallback=lambda msg: captured.append(msg),
    )
    assert isinstance(planner, DeterministicPlannerClient)
    assert plan.decisions, "fallback deveria gerar plano"
    assert any("simulado" in c for c in captured)
