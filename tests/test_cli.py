import json
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from opencode_buddy.agent_driven import (
    AgentDrivenDecision,
    AgentDrivenModelChoice,
    AgentDrivenPlan,
    DeterministicPlannerClient,
)
from opencode_buddy.cli import app
from opencode_buddy.config_builder import (
    InitOptions,
    build_env_example,
    build_gitignore,
    build_litellm_config,
    build_opencode_config,
    build_start_proxy_script,
    iter_agent_specs,
)
from opencode_buddy.keys_validator import ProviderStatus


runner = CliRunner()


def _http_response(payload: dict) -> MagicMock:
    response = MagicMock()
    response.read.return_value = json.dumps(payload).encode("utf-8")
    response.__enter__.return_value = response
    response.__exit__.return_value = None
    return response


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    for var in [
        "OPENCODE_GO_API_KEY",
        "DEEPSEEK_API_KEY",
        "MOONSHOT_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "COMMANDCODE_API_KEY",
        "COMMANDCODE_API_BASE",
    ]:
        monkeypatch.delenv(var, raising=False)


def _scaffold(tmp_path, write_env=False):
    opts = InitOptions()
    import yaml

    (tmp_path / "opencode.json").write_text(
        json.dumps(build_opencode_config(opts), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (tmp_path / "litellm-config.yaml").write_text(
        yaml.safe_dump(build_litellm_config(opts), sort_keys=False),
        encoding="utf-8",
    )
    (tmp_path / ".env.example").write_text(build_env_example(opts), encoding="utf-8")
    (tmp_path / "start-proxy.ps1").write_text(build_start_proxy_script(opts), encoding="utf-8")
    (tmp_path / ".gitignore").write_text(build_gitignore(), encoding="utf-8")
    agents_dir = tmp_path / ".opencode" / "agents"
    agents_dir.mkdir(parents=True)
    for spec in iter_agent_specs(opts):
        (agents_dir / spec.prompt_file).write_text(f"Prompt for {spec.name}", encoding="utf-8")
    if write_env:
        (tmp_path / ".env").write_text(
            "LITELLM_MASTER_KEY=sk-test\nOPENCODE_GO_API_KEY=go-test\nDEEPSEEK_API_KEY=ds-test\n",
            encoding="utf-8",
        )
    return tmp_path


def test_keys_validate_unknown_provider_returns_friendly_error(tmp_path):
    result = runner.invoke(app, ["keys", "validate", "--cwd", str(tmp_path), "--provider", "naoexiste"])
    assert result.exit_code == 2
    assert "naoexiste" in result.stderr
    assert "providers disponiveis" in result.stderr.lower() or "providers disponiveis" in result.stderr
    assert "deepseek" in result.stderr


def test_keys_validate_unknown_provider_lists_all_keys(tmp_path):
    result = runner.invoke(app, ["keys", "validate", "--cwd", str(tmp_path), "--provider", "xyz"])
    for known in ("opencode-go", "deepseek", "moonshot", "anthropic", "gemini", "commandcode", "chatgpt"):
        assert known in result.stderr


def test_keys_validate_known_provider_runs_normally(tmp_path):
    result = runner.invoke(app, ["keys", "validate", "--cwd", str(tmp_path), "--provider", "deepseek", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert len(payload) == 1
    assert payload[0]["provider_key"] == "deepseek"
    assert payload[0]["state"] == "missing-env"


def test_keys_setup_writes_env_and_does_not_echo_secret(tmp_path, monkeypatch):
    secret = "super-secret-opencode-go"
    monkeypatch.setattr(
        "opencode_buddy.model_catalog.urllib.request.urlopen",
        lambda req, timeout=None: _http_response({"data": [{"id": "deepseek-v4-flash"}]}),
    )

    result = runner.invoke(
        app,
        ["keys", "setup", "--cwd", str(tmp_path), "--provider", "opencode-go"],
        input=f"{secret}\n",
    )

    assert result.exit_code == 0, result.output
    assert f"OPENCODE_GO_API_KEY={secret}" in (tmp_path / ".env").read_text(encoding="utf-8")
    assert secret not in result.stdout
    assert secret not in result.stderr
    assert "OpenCode Go" in result.stdout


def test_init_setup_keys_creates_env_after_scaffold(tmp_path, monkeypatch):
    secret = "init-secret-opencode-go"
    target = tmp_path / "init-with-keys"
    monkeypatch.setattr(
        "opencode_buddy.model_catalog.urllib.request.urlopen",
        lambda req, timeout=None: _http_response({"data": [{"id": "deepseek-v4-flash"}]}),
    )

    result = runner.invoke(
        app,
        ["init", str(target), "--setup-keys", "--force"],
        input=f"s\n{secret}\nn\nn\nn\nn\nn\n",
    )

    assert result.exit_code == 0, result.output
    assert (target / "opencode.json").exists()
    assert f"OPENCODE_GO_API_KEY={secret}" in (target / ".env").read_text(encoding="utf-8")
    assert secret not in result.stdout
    assert secret not in result.stderr


def test_validate_strict_fails_when_env_missing(tmp_path):
    project = _scaffold(tmp_path, write_env=False)
    result = runner.invoke(app, ["validate", str(project), "--strict"])
    assert result.exit_code == 1
    assert ".env" in result.stdout
    assert "aviso" in result.stdout.lower() or "warn" in result.stdout.lower()


def test_validate_non_strict_passes_with_env_warning(tmp_path):
    project = _scaffold(tmp_path, write_env=False)
    result = runner.invoke(app, ["validate", str(project)])
    assert result.exit_code == 0
    assert "WARN" in result.stdout or "aviso" in result.stdout.lower()


def test_validate_strict_passes_with_real_env(tmp_path):
    project = _scaffold(tmp_path, write_env=True)
    result = runner.invoke(app, ["validate", str(project), "--strict"])
    assert result.exit_code == 0


def test_validate_strict_warning_message_mentions_strict(tmp_path):
    project = _scaffold(tmp_path, write_env=False)
    result = runner.invoke(app, ["validate", str(project)])
    assert "--strict" in result.stdout


# ---- Agent Driven Mode -------------------------------------------------------


def _make_minimal_react_project(tmp_path):
    """Cria um pseudo-projeto React+Vite para o scanner detectar."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "name": "demo",
                "dependencies": {"react": "^18", "react-dom": "^18"},
                "devDependencies": {"vite": "^5", "typescript": "^5"},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "vite.config.ts").write_text("export default {}\n", encoding="utf-8")
    (tmp_path / "tsconfig.json").write_text("{}\n", encoding="utf-8")
    return tmp_path


def test_agent_driven_command_offline_smoke(tmp_path):
    project = _make_minimal_react_project(tmp_path / "src-project")
    target = tmp_path / "out"
    result = runner.invoke(
        app,
        [
            "agent-driven",
            "--scan",
            str(project),
            "--target",
            str(target),
            "--offline",
            "--force",
        ],
        input="1\n",
    )
    assert result.exit_code == 0, result.output
    assert (target / "opencode.json").exists()
    assert (target / ".opencode" / "project.md").exists()


def test_agent_driven_command_cancel_writes_no_files(tmp_path):
    project = _make_minimal_react_project(tmp_path / "src-project")
    target = tmp_path / "out-cancel"
    result = runner.invoke(
        app,
        [
            "agent-driven",
            "--scan",
            str(project),
            "--target",
            str(target),
            "--offline",
        ],
        input="3\n",
    )
    # Cancel emite Exit(1)
    assert result.exit_code == 1
    assert not target.exists() or not (target / "opencode.json").exists()


def test_agent_driven_command_anthropic_without_key_friendly_error(tmp_path):
    project = _make_minimal_react_project(tmp_path / "src-project")
    result = runner.invoke(
        app,
        [
            "agent-driven",
            "--scan",
            str(project),
            "--planner",
            "anthropic",
        ],
        input="n\n",
    )
    assert result.exit_code == 2
    combined = result.stdout + result.stderr
    assert "ANTHROPIC_API_KEY" in combined or "variaveis" in combined.lower()


def test_agent_driven_dry_run_json_offline_emits_json_and_writes_no_files(tmp_path):
    project = _make_minimal_react_project(tmp_path / "src-project")
    target = tmp_path / "out-dry-json"
    result = runner.invoke(
        app,
        [
            "agent-driven",
            "--scan",
            str(project),
            "--target",
            str(target),
            "--offline",
            "--dry-run",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert "target_path" in payload
    assert "decisions" in payload
    assert "model_choices" in payload
    assert "raw_response" not in payload
    assert not (target / "opencode.json").exists()


def test_agent_driven_requires_live_key_unless_offline(tmp_path):
    project = _make_minimal_react_project(tmp_path / "src-project")
    target = tmp_path / "out-live-required"
    result = runner.invoke(
        app,
        [
            "agent-driven",
            "--scan",
            str(project),
            "--target",
            str(target),
            "--dry-run",
            "--json",
        ],
    )

    assert result.exit_code == 2
    combined = result.stdout + result.stderr
    assert "Nenhum provider API valido" in combined or "No providers" in combined
    assert not (target / "opencode.json").exists()


def test_agent_driven_new_project_uses_target_env_for_live_preflight(tmp_path, monkeypatch):
    target = tmp_path / "new-project"
    target.mkdir()
    (target / ".env").write_text("OPENCODE_GO_API_KEY=target-secret\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_validate(cwd, *, provider_keys=(), timeout=5.0):
        captured["cwd"] = cwd
        return (
            ProviderStatus(
                "opencode-go",
                "OpenCode Go",
                "API",
                "ok",
                "1 modelo encontrado",
                ("deepseek-v4-flash",),
            ),
        )

    plan = AgentDrivenPlan(
        target_path=str(target),
        decisions=(AgentDrivenDecision("frontend", True, reason="teste"),),
        model_choices=(
            AgentDrivenModelChoice("build", "opencode-go", "deepseek-v4-flash", "litellm/build-model"),
            AgentDrivenModelChoice("frontend", "opencode-go", "kimi-k2.6", "litellm/frontend-model"),
            AgentDrivenModelChoice("default", "opencode-go", "deepseek-v4-flash", "litellm/default-model"),
            AgentDrivenModelChoice("deep", "opencode-go", "qwen3.6-plus", "litellm/deep-model"),
        ),
    )
    planner = DeterministicPlannerClient()

    monkeypatch.setattr("opencode_buddy.cli.validate_selected_providers", fake_validate)
    monkeypatch.setattr("opencode_buddy.cli.select_planner", lambda *args, **kwargs: planner)
    monkeypatch.setattr("opencode_buddy.cli.propose_plan_with_fallback", lambda *args, **kwargs: (plan, planner))

    result = runner.invoke(
        app,
        [
            "agent-driven",
            "--target",
            str(target),
            "--objective",
            "novo app",
            "--dry-run",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["cwd"] == target.resolve()
    assert json.loads(result.stdout)["target_path"] == str(target)


def test_agent_driven_json_without_dry_run_returns_friendly_error(tmp_path):
    project = _make_minimal_react_project(tmp_path / "src-project")
    result = runner.invoke(
        app,
        [
            "agent-driven",
            "--scan",
            str(project),
            "--offline",
            "--json",
        ],
    )
    assert result.exit_code == 2
    combined = result.stdout + result.stderr
    assert "--dry-run" in combined


def test_agent_driven_dry_run_without_json_runs_review_and_skips_scaffold(tmp_path):
    project = _make_minimal_react_project(tmp_path / "src-project")
    target = tmp_path / "out-dry-only"
    result = runner.invoke(
        app,
        [
            "agent-driven",
            "--scan",
            str(project),
            "--target",
            str(target),
            "--offline",
            "--dry-run",
        ],
        input="1\n",
    )
    assert result.exit_code == 0, result.output
    assert "NAO foram" in result.stdout or "no files" in result.stdout.lower()
    assert not (target / "opencode.json").exists()


def test_agent_driven_dry_run_json_does_not_contain_env_values(tmp_path, monkeypatch):
    canary = "super-secret-leak-canary-deepseek"
    monkeypatch.setenv("DEEPSEEK_API_KEY", canary)

    project = _make_minimal_react_project(tmp_path / "src-project")
    target = tmp_path / "out-canary"
    result = runner.invoke(
        app,
        [
            "agent-driven",
            "--scan",
            str(project),
            "--target",
            str(target),
            "--offline",
            "--dry-run",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert canary not in result.stdout
    assert canary not in result.stderr


def test_agent_driven_command_unknown_planner_provider_friendly_error(tmp_path):
    project = _make_minimal_react_project(tmp_path / "src-project")
    result = runner.invoke(
        app,
        [
            "agent-driven",
            "--scan",
            str(project),
            "--planner",
            "naoexiste",
        ],
    )
    assert result.exit_code == 2
    combined = result.stdout + result.stderr
    assert "naoexiste" in combined

