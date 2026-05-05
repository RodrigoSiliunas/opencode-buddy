import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from opencode_buddy.cli import app


REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = REPO_ROOT / "examples"


runner = CliRunner()


def test_examples_dir_exists():
    assert EXAMPLES_DIR.is_dir()


def test_examples_agent_driven_existing_vite_has_required_files():
    base = EXAMPLES_DIR / "agent-driven-existing-vite"
    assert (base / "package.json").is_file()
    assert (base / "vite.config.ts").is_file()
    assert (base / "tsconfig.json").is_file()
    assert (base / "README.md").is_file()


def test_examples_agent_driven_existing_vite_readme_mentions_command():
    readme = (EXAMPLES_DIR / "agent-driven-existing-vite" / "README.md").read_text(encoding="utf-8")
    assert "agent-driven" in readme
    assert "--scan" in readme
    assert "--offline" in readme
    assert "--dry-run" in readme
    assert "--json" in readme


def test_examples_agent_driven_new_project_readme_mentions_objective():
    readme = (EXAMPLES_DIR / "agent-driven-new-project" / "README.md").read_text(encoding="utf-8")
    assert "--objective" in readme
    assert "--target" in readme


def test_examples_model_registry_extension_yaml_parses():
    path = EXAMPLES_DIR / "model-registry-extension.yaml"
    assert path.is_file()
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert data.get("version") == 1
    assert "providers" in data


def test_examples_existing_vite_scaffolds_via_agent_driven_offline_dry_run(tmp_path):
    """Smoke real: comando documentado no README do exemplo deve funcionar end-to-end."""
    target = tmp_path / "example-out"
    result = runner.invoke(
        app,
        [
            "agent-driven",
            "--scan",
            str(EXAMPLES_DIR / "agent-driven-existing-vite"),
            "--target",
            str(target),
            "--offline",
            "--dry-run",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert "decisions" in payload
    assert "model_choices" in payload
    # Sem raw_response no payload publico
    assert "raw_response" not in payload
    # Frontend deve aparecer como capacidade habilitada (sinais react+vite presentes)
    enabled_caps = {d["capability"] for d in payload["decisions"] if d.get("enabled")}
    assert "frontend" in enabled_caps


def test_examples_opencode_buddy_spec_yaml_still_aligned():
    """Garante que o exemplo declarativo do init --spec continua parseando."""
    path = EXAMPLES_DIR / "opencode-buddy.spec.yaml"
    assert path.is_file()
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert "litellm_url" in data
    assert "project_context" in data
