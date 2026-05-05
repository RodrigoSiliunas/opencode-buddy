import json
from pathlib import Path

import pytest

from opencode_buddy.project_scanner import (
    DEFAULT_MAX_FILES,
    DetectedFile,
    ProjectScan,
    scan_project,
)


def _write(path: Path, content: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_scan_returns_empty_when_root_missing(tmp_path):
    scan = scan_project(tmp_path / "absent")
    assert isinstance(scan, ProjectScan)
    assert scan.detected_files == ()
    assert scan.signals == ()


def test_scan_detects_react_vite_project(tmp_path):
    _write(
        tmp_path / "package.json",
        json.dumps(
            {
                "name": "demo",
                "dependencies": {"react": "^18.0.0", "react-dom": "^18.0.0"},
                "devDependencies": {"vite": "^5.0.0", "typescript": "^5.0.0"},
            }
        ),
    )
    _write(tmp_path / "vite.config.ts", "import { defineConfig } from 'vite'\nexport default defineConfig({})\n")
    _write(tmp_path / "tsconfig.json", "{}\n")

    scan = scan_project(tmp_path)
    signals = dict(scan.signals)

    assert signals.get("framework") == "react+vite"
    assert "vite" in signals.get("bundler", "")
    assert "typescript" in scan.languages
    assert "javascript" in scan.languages
    assert any(f.path == "package.json" for f in scan.detected_files)
    assert any(f.path == "vite.config.ts" for f in scan.detected_files)
    assert any(f.path == "tsconfig.json" for f in scan.detected_files)


def test_scan_detects_python_fastapi_project(tmp_path):
    _write(
        tmp_path / "pyproject.toml",
        '[project]\nname = "api"\ndependencies = ["fastapi>=0.110", "pydantic>=2"]\n',
    )
    _write(tmp_path / "uv.lock", "# uv lock placeholder\n")

    scan = scan_project(tmp_path)
    signals = dict(scan.signals)

    assert "python" in scan.languages
    assert "fastapi" in signals.get("python_libs", "")
    assert signals.get("package_manager_py") == "uv"


def test_scan_ignores_node_modules_and_venv(tmp_path):
    _write(tmp_path / "package.json", "{}")
    _write(tmp_path / "node_modules" / "react" / "package.json", "{}")
    _write(tmp_path / ".venv" / "lib" / "site-packages" / "ignored.py", "")
    _write(tmp_path / ".git" / "config", "")

    scan = scan_project(tmp_path)
    paths = {f.path for f in scan.detected_files}

    assert "package.json" in paths
    for path in paths:
        assert not path.startswith("node_modules/")
        assert not path.startswith(".venv/")
        assert not path.startswith(".git/")


def test_scan_skips_dotenv_files_but_keeps_example(tmp_path):
    _write(tmp_path / ".env", "SECRET_VALUE=do-not-leak\n")
    _write(tmp_path / ".env.example", "SECRET_VALUE=change-me\n")
    _write(tmp_path / "package.json", "{}")

    scan = scan_project(tmp_path)
    paths = {f.path for f in scan.detected_files}

    assert ".env" not in paths
    assert ".env.example" in paths
    # Garante que o conteudo do .env nao vazou pra summary
    assert "do-not-leak" not in scan.summary_markdown


def test_scan_caps_max_files(tmp_path):
    _write(tmp_path / "package.json", "{}")
    for i in range(DEFAULT_MAX_FILES + 50):
        _write(tmp_path / f"README{i}.md", f"# doc {i}\n")

    scan = scan_project(tmp_path, max_files=10)

    assert len(scan.detected_files) <= 10


def test_scan_detects_audio_signals(tmp_path):
    _write(tmp_path / "pyproject.toml", '[project]\nname="x"\ndependencies=[]\n')
    _write(tmp_path / "audio" / "whisper_setup.py", "import whisper\n")

    scan = scan_project(tmp_path)
    signals = dict(scan.signals)

    hits = signals.get("multimodal_hints", "")
    assert "audio" in hits or "whisper" in hits


def test_scan_includes_readme_excerpt(tmp_path):
    body = "\n".join(f"line {i}" for i in range(100))
    _write(tmp_path / "README.md", body)

    scan = scan_project(tmp_path, max_lines_per_file=40)
    readme = next((f for f in scan.detected_files if f.path == "README.md"), None)

    assert readme is not None
    excerpt_lines = readme.excerpt.splitlines()
    assert len(excerpt_lines) <= 40


def test_scan_signals_are_sorted_and_hashable(tmp_path):
    _write(
        tmp_path / "package.json",
        json.dumps({"dependencies": {"react": "*", "next": "*"}}),
    )
    _write(tmp_path / "Dockerfile", "FROM node\n")

    scan = scan_project(tmp_path)
    keys = [key for key, _ in scan.signals]
    assert keys == sorted(keys)
    # Tupla de pares, hashable
    assert hash(scan.signals) is not None


def test_scan_ignores_secret_files(tmp_path):
    _write(tmp_path / "secrets.yaml", "api_key: do-not-leak\n")
    _write(tmp_path / "id_rsa", "-----BEGIN PRIVATE KEY-----\n")
    _write(tmp_path / "deploy.pem", "-----BEGIN CERT-----\n")
    _write(tmp_path / "package.json", "{}")

    scan = scan_project(tmp_path)
    paths = {f.path for f in scan.detected_files}

    assert "secrets.yaml" not in paths
    assert "id_rsa" not in paths
    assert "deploy.pem" not in paths
    assert "do-not-leak" not in scan.summary_markdown


def test_scan_summary_markdown_contains_languages_and_signals(tmp_path):
    _write(tmp_path / "package.json", json.dumps({"dependencies": {"react": "*"}}))

    scan = scan_project(tmp_path)
    assert "javascript" in scan.summary_markdown
    assert "framework" in scan.summary_markdown
