import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from opencode_buddy.cli import app
from opencode_buddy.config_builder import InitOptions
from opencode_buddy.scaffolder import ProjectSpec, SpecFileError, load_spec_file, scaffold_project


runner = CliRunner()


def test_project_spec_is_alias_of_init_options():
    assert ProjectSpec is InitOptions
    spec = ProjectSpec(litellm_port=5050)
    assert isinstance(spec, InitOptions)
    assert spec.litellm_port == 5050


def test_load_spec_file_yaml(tmp_path):
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(
        "litellm_url: http://localhost:5000/v1\nlitellm_port: 5000\nbackend_model: litellm/x\n",
        encoding="utf-8",
    )
    data = load_spec_file(spec_path)
    assert data["litellm_url"] == "http://localhost:5000/v1"
    assert data["litellm_port"] == 5000
    assert data["backend_model"] == "litellm/x"


def test_load_spec_file_json(tmp_path):
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(
        json.dumps({"litellm_url": "http://x/v1", "routing_strategy": "least-busy"}),
        encoding="utf-8",
    )
    data = load_spec_file(spec_path)
    assert data["routing_strategy"] == "least-busy"


def test_load_spec_file_rejects_unknown_extension(tmp_path):
    bad = tmp_path / "spec.txt"
    bad.write_text("nope", encoding="utf-8")
    with pytest.raises(SpecFileError):
        load_spec_file(bad)


def test_load_spec_file_rejects_missing_file(tmp_path):
    with pytest.raises(SpecFileError):
        load_spec_file(tmp_path / "absent.yaml")


def test_load_spec_file_rejects_non_object(tmp_path):
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text("- 1\n- 2\n", encoding="utf-8")
    with pytest.raises(SpecFileError):
        load_spec_file(spec_path)


def test_scaffold_project_uses_shared_engine(tmp_path):
    target = tmp_path / "demo"
    spec = ProjectSpec()
    scaffold_project(target, spec, force=True)
    assert (target / "opencode.json").exists()
    assert (target / "litellm-config.yaml").exists()
    assert (target / ".env.example").exists()
    assert (target / ".gitignore").exists()
    assert (target / "start-proxy.ps1").exists()
    assert (target / ".opencode" / "project.md").exists()


def test_init_command_accepts_spec_file(tmp_path):
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(
        yaml.safe_dump({"litellm_port": 5555, "routing_strategy": "least-busy"}),
        encoding="utf-8",
    )
    target = tmp_path / "init-from-spec"
    result = runner.invoke(
        app,
        ["init", str(target), "--spec", str(spec_path), "--force"],
    )
    assert result.exit_code == 0, result.output
    config = json.loads((target / "opencode.json").read_text(encoding="utf-8"))
    assert config["provider"]["litellm"]["options"]["baseURL"].startswith("http://localhost:4000")
    litellm = yaml.safe_load((target / "litellm-config.yaml").read_text(encoding="utf-8"))
    assert litellm["router_settings"]["routing_strategy"] == "least-busy"


def test_init_command_accepts_nested_spec_dataclasses(tmp_path):
    spec_path = tmp_path / "nested-spec.yaml"
    spec_path.write_text(
        yaml.safe_dump(
            {
                "enable_chatgpt": False,
                "enable_frontend_agent": False,
                "enable_backend_agent": True,
                "build_model": "litellm/build-model",
                "backend_model": "litellm/backend-model",
                "default_model": "litellm/default-model",
                "deep_model": "litellm/deep-model",
                "model_specs": [
                    {
                        "alias": "build-model",
                        "litellm_model": "deepseek/deepseek-chat",
                        "display_name": "Build",
                        "api_key_env": "DEEPSEEK_API_KEY",
                    },
                    {
                        "alias": "backend-model",
                        "litellm_model": "deepseek/deepseek-chat",
                        "display_name": "Backend",
                        "api_key_env": "DEEPSEEK_API_KEY",
                    },
                    {
                        "alias": "default-model",
                        "litellm_model": "deepseek/deepseek-chat",
                        "display_name": "Default",
                        "api_key_env": "DEEPSEEK_API_KEY",
                    },
                    {
                        "alias": "deep-model",
                        "litellm_model": "deepseek/deepseek-reasoner",
                        "display_name": "Deep",
                        "api_key_env": "DEEPSEEK_API_KEY",
                    },
                ],
                "fallback_rules": [{"alias": "deep-model", "fallbacks": ["default-model"]}],
                "extra_agents": [
                    {
                        "name": "reviewer",
                        "description": "Revisao critica",
                        "model": "litellm/deep-model",
                        "prompt_file": "reviewer.md",
                    }
                ],
                "project_context": {
                    "summary": "Projeto via spec aninhado",
                    "stack": "Backend/API",
                    "commands": ["pytest"],
                    "capabilities": [
                        {
                            "key": "backend",
                            "label": "Backend/API",
                            "answers": {"runtime": "Python", "api": "REST"},
                        }
                    ],
                    "role_models": [["backend", "DeepSeek"]],
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    target = tmp_path / "init-nested"
    result = runner.invoke(app, ["init", str(target), "--spec", str(spec_path), "--force"])
    assert result.exit_code == 0, result.output

    config = json.loads((target / "opencode.json").read_text(encoding="utf-8"))
    assert set(config["agent"]) == {"build", "backend", "default", "deep", "reviewer"}
    assert config["agent"]["backend"]["model"] == "litellm/backend-model"

    litellm = yaml.safe_load((target / "litellm-config.yaml").read_text(encoding="utf-8"))
    assert {"deep-model": ["default-model"]} in litellm["router_settings"]["fallbacks"]

    project_md = (target / ".opencode" / "project.md").read_text(encoding="utf-8")
    assert "Projeto via spec aninhado" in project_md
    assert "runtime: Python" in project_md
    assert "Nunca incluir secrets" in project_md


def test_init_command_flag_overrides_spec_file(tmp_path):
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(
        yaml.safe_dump({"litellm_port": 5000, "litellm_url": "http://from-spec/v1"}),
        encoding="utf-8",
    )
    target = tmp_path / "init-flag-wins"
    result = runner.invoke(
        app,
        [
            "init",
            str(target),
            "--spec",
            str(spec_path),
            "--litellm-url",
            "http://from-flag/v1",
            "--force",
        ],
    )
    assert result.exit_code == 0, result.output
    config = json.loads((target / "opencode.json").read_text(encoding="utf-8"))
    assert config["provider"]["litellm"]["options"]["baseURL"] == "http://from-flag/v1"


def test_init_command_rejects_unknown_spec_field(tmp_path):
    spec_path = tmp_path / "bad.yaml"
    spec_path.write_text(yaml.safe_dump({"unknown_field": "x"}), encoding="utf-8")
    result = runner.invoke(app, ["init", str(tmp_path / "out"), "--spec", str(spec_path), "--force"])
    assert result.exit_code == 2
    assert "unknown_field" in (result.stdout + result.stderr)


def test_examples_spec_yaml_parses_into_valid_project_spec(tmp_path):
    """O exemplo canonico em examples/ deve continuar batendo com o schema do init."""
    repo_root = Path(__file__).resolve().parent.parent
    example_path = repo_root / "examples" / "opencode-buddy.spec.yaml"
    assert example_path.exists(), f"exemplo ausente: {example_path}"

    target = tmp_path / "init-from-example"
    result = runner.invoke(
        app,
        ["init", str(target), "--spec", str(example_path), "--force"],
    )
    assert result.exit_code == 0, result.output

    config = json.loads((target / "opencode.json").read_text(encoding="utf-8"))
    assert "reviewer" in config["agent"]
    assert config["agent"]["backend"]["model"] == "chatgpt/gpt-5.5"

    project_md = (target / ".opencode" / "project.md").read_text(encoding="utf-8")
    assert "pipeline de inferencia LLM" in project_md
    assert "framework: React" in project_md
    assert "runtime: Python" in project_md


def test_init_command_appends_extra_agent_to_spec_extra_agents(tmp_path):
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.safe_dump({"litellm_port": 4000}), encoding="utf-8")
    target = tmp_path / "init-extra"
    result = runner.invoke(
        app,
        [
            "init",
            str(target),
            "--spec",
            str(spec_path),
            "--extra-agent",
            "reviewer=litellm/deepseek-pro:revisao",
            "--force",
        ],
    )
    assert result.exit_code == 0, result.output
    config = json.loads((target / "opencode.json").read_text(encoding="utf-8"))
    assert "reviewer" in config["agent"]
