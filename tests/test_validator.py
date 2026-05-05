import json

import yaml

from opencode_buddy.config_builder import (
    AgentSpec,
    InitOptions,
    build_env_example,
    build_gitignore,
    build_litellm_config,
    build_opencode_config,
    build_start_proxy_script,
    iter_agent_specs,
)
from opencode_buddy.validator import format_validation_report, validate_project


def _write_project(tmp_path, opts=None, write_env=True, write_gitignore=True):
    opts = opts or InitOptions()
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
    if write_gitignore:
        (tmp_path / ".gitignore").write_text(build_gitignore(), encoding="utf-8")

    agents_dir = tmp_path / ".opencode" / "agents"
    agents_dir.mkdir(parents=True)
    for spec in iter_agent_specs(opts):
        (agents_dir / spec.prompt_file).write_text(f"Prompt for {spec.name}", encoding="utf-8")

    if write_env:
        (tmp_path / ".env").write_text(
            "\n".join(
                [
                    "LITELLM_MASTER_KEY=sk-test",
                    "OPENCODE_GO_API_KEY=go-test",
                    "DEEPSEEK_API_KEY=deepseek-test",
                    "",
                ]
            ),
            encoding="utf-8",
        )
    return tmp_path


def test_validate_project_accepts_generated_project(tmp_path):
    project = _write_project(tmp_path)
    messages = validate_project(project)
    assert not [msg for msg in messages if msg.level in {"error", "warn"}]


def test_validate_project_warns_when_env_is_missing(tmp_path):
    project = _write_project(tmp_path, write_env=False)
    messages = validate_project(project)
    assert not [msg for msg in messages if msg.level == "error"]
    assert any(msg.level == "warn" and msg.subject == ".env" for msg in messages)


def test_validate_project_reports_missing_prompt_file(tmp_path):
    project = _write_project(tmp_path)
    (project / ".opencode" / "agents" / "frontend.md").unlink()
    messages = validate_project(project)
    assert any("frontend" in msg.subject and msg.level == "error" for msg in messages)


def test_validate_project_reports_prompt_escape(tmp_path):
    project = _write_project(tmp_path)
    data = json.loads((project / "opencode.json").read_text(encoding="utf-8"))
    data["agent"]["frontend"]["prompt"] = "{file:../frontend.md}"
    (project / "opencode.json").write_text(json.dumps(data), encoding="utf-8")
    messages = validate_project(project)
    assert any("fora do projeto" in msg.detail and msg.level == "error" for msg in messages)


def test_validate_project_reports_unknown_litellm_alias(tmp_path):
    extra = AgentSpec(
        name="qa",
        description="Qualidade",
        model="litellm/unknown",
        prompt_file="qa.md",
    )
    project = _write_project(tmp_path, InitOptions(extra_agents=(extra,)))
    messages = validate_project(project)
    assert any("unknown" in msg.detail and msg.level == "error" for msg in messages)


def test_format_validation_report_summarizes_warnings():
    report = format_validation_report([])
    assert "Tudo consistente" in report


def test_validate_project_warns_when_gitignore_missing(tmp_path):
    project = _write_project(tmp_path, write_gitignore=False)
    messages = validate_project(project)
    assert any(
        msg.subject == ".gitignore" and msg.level == "warn" and "ausente" in msg.detail for msg in messages
    )


def test_validate_project_warns_when_gitignore_does_not_protect_env(tmp_path):
    project = _write_project(tmp_path, write_gitignore=False)
    (project / ".gitignore").write_text("node_modules/\ndist/\n", encoding="utf-8")
    messages = validate_project(project)
    assert any(
        msg.subject == ".gitignore" and msg.level == "warn" and "nao protege" in msg.detail for msg in messages
    )


def test_validate_project_warns_when_gitignore_unignores_env(tmp_path):
    project = _write_project(tmp_path, write_gitignore=False)
    (project / ".gitignore").write_text(".env\n.env.*\n!.env\n", encoding="utf-8")
    messages = validate_project(project)
    assert any(
        msg.subject == ".gitignore" and msg.level == "warn" and "desfaz ignore" in msg.detail for msg in messages
    )


def test_validate_project_ok_when_gitignore_protects_env(tmp_path):
    project = _write_project(tmp_path)
    messages = validate_project(project)
    assert any(msg.subject == ".gitignore" and msg.level == "ok" for msg in messages)
