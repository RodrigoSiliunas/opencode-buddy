"""Scanner local de projetos para alimentar o Agent Driven Mode.

Walk recursivo aplicando skip-list de diretorios e arquivos sensiveis.
Le no maximo `max_lines_per_file` linhas de cada arquivo reconhecido.
Nunca le `.env`, secrets ou conteudo de pastas ignoradas.

Saida `ProjectScan` agrega:
- `detected_files`: tipo + path + excerpt curto.
- `signals`: pares (chave, valor) ja deduplicados/ordenados.
- `languages`: linguagens encontradas.
- `summary_markdown`: bloco pronto pra ir como contexto pro planner.
- `skipped_paths`: amostra de paths ignorados (diagnostico).
"""
from __future__ import annotations

import fnmatch
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_MAX_FILES = 100
DEFAULT_MAX_LINES_PER_FILE = 40
DEFAULT_MAX_FILE_BYTES = 1_000_000  # 1 MB hard cap
DEFAULT_SUMMARY_BUDGET_BYTES = 30_000

SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        ".venv",
        "venv",
        "env",
        "__pycache__",
        "dist",
        "build",
        "target",
        ".next",
        ".nuxt",
        ".cache",
        ".parcel-cache",
        "coverage",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
        ".idea",
        ".vscode",
        ".gradle",
        "out",
        "bin",
        "obj",
    }
)

SECRET_GLOBS: tuple[str, ...] = (
    ".env",
    ".env.local",
    ".env.*.local",
    ".env.production",
    ".env.development",
    ".env.test",
    "*.key",
    "*.pem",
    "*.p12",
    "*.crt",
    "*.cer",
    "*.pfx",
    "id_rsa*",
    "id_ed25519*",
    "*.secret",
    "*credential*",
    "*credentials*",
    "*_token",
    "*.token",
    "secrets.yaml",
    "secrets.yml",
    "secrets.json",
)

ENV_EXAMPLE_GLOBS: tuple[str, ...] = (".env.example", ".env.sample", ".env.template")


# Trechos que indicam dominios audio/video/multimodal por nomenclatura.
MULTIMODAL_HINTS: tuple[str, ...] = (
    "audio",
    "speech",
    "transcrib",
    "video",
    "frame",
    "vision",
    "image",
    "multimodal",
    "asr",
    "tts",
    "whisper",
    "ocr",
)


@dataclass(frozen=True)
class DetectedFile:
    path: str
    role: str
    excerpt: str = ""


@dataclass(frozen=True)
class ProjectScan:
    root: Path
    detected_files: tuple[DetectedFile, ...] = field(default_factory=tuple)
    signals: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    languages: tuple[str, ...] = field(default_factory=tuple)
    summary_markdown: str = ""
    skipped_paths: tuple[str, ...] = field(default_factory=tuple)


def scan_project(
    root: Path,
    *,
    max_files: int = DEFAULT_MAX_FILES,
    max_lines_per_file: int = DEFAULT_MAX_LINES_PER_FILE,
) -> ProjectScan:
    root = root.resolve()
    if not root.exists() or not root.is_dir():
        return ProjectScan(root=root)

    detected: list[DetectedFile] = []
    skipped: list[str] = []
    languages: set[str] = set()
    signals: dict[str, str] = {}
    audio_video_hits: set[str] = set()

    file_count = 0
    for file_path in _iter_candidate_files(root, skipped):
        if file_count >= max_files:
            skipped.append(f"{_rel(root, file_path)} (cap max_files)")
            break
        try:
            size = file_path.stat().st_size
        except OSError:
            continue
        if size > DEFAULT_MAX_FILE_BYTES:
            skipped.append(f"{_rel(root, file_path)} (>1MB)")
            continue

        rel = _rel(root, file_path)
        rel_lower = rel.lower()
        for hint in MULTIMODAL_HINTS:
            if hint in rel_lower:
                audio_video_hits.add(hint)

        role = _classify_file(file_path.name, rel)
        if role is None:
            continue

        excerpt = _read_head(file_path, max_lines=max_lines_per_file) if _should_read(role) else ""
        detected.append(DetectedFile(path=rel, role=role, excerpt=excerpt))
        file_count += 1

        _enrich_signals_and_languages(role, file_path.name, excerpt, signals, languages)

    if audio_video_hits:
        signals.setdefault("multimodal_hints", ",".join(sorted(audio_video_hits)))

    sorted_signals = tuple(sorted(signals.items()))
    sorted_languages = tuple(sorted(languages))

    summary = _render_summary_markdown(root, detected, sorted_signals, sorted_languages)
    if len(summary.encode("utf-8")) > DEFAULT_SUMMARY_BUDGET_BYTES:
        summary = summary.encode("utf-8")[:DEFAULT_SUMMARY_BUDGET_BYTES].decode("utf-8", errors="ignore") + "\n…"

    return ProjectScan(
        root=root,
        detected_files=tuple(detected),
        signals=sorted_signals,
        languages=sorted_languages,
        summary_markdown=summary,
        skipped_paths=tuple(skipped[:50]),
    )


# --- walk + filtros ---------------------------------------------------------


def _iter_candidate_files(root: Path, skipped: list[str]):
    yield from _walk(root, root, skipped, depth=0, max_depth=8)


def _walk(root: Path, current: Path, skipped: list[str], depth: int, max_depth: int):
    if depth > max_depth:
        skipped.append(f"{_rel(root, current)} (max_depth)")
        return
    try:
        entries = sorted(current.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except (PermissionError, OSError):
        return
    for entry in entries:
        if entry.is_symlink():
            continue
        if entry.is_dir():
            if entry.name in SKIP_DIRS:
                skipped.append(_rel(root, entry))
                continue
            yield from _walk(root, entry, skipped, depth + 1, max_depth)
            continue
        if entry.is_file():
            if _is_secret_file(entry.name) and not _is_env_example(entry.name):
                skipped.append(_rel(root, entry))
                continue
            yield entry


def _is_secret_file(name: str) -> bool:
    name_lower = name.lower()
    for pattern in SECRET_GLOBS:
        if fnmatch.fnmatch(name_lower, pattern):
            return True
    return False


def _is_env_example(name: str) -> bool:
    name_lower = name.lower()
    return any(fnmatch.fnmatch(name_lower, pattern) for pattern in ENV_EXAMPLE_GLOBS)


# --- classificacao + leitura -----------------------------------------------


_ROLE_RULES: tuple[tuple[str, str], ...] = (
    # (role, glob)
    ("package_manager", "package.json"),
    ("package_manager", "pyproject.toml"),
    ("package_manager", "requirements.txt"),
    ("package_manager", "Pipfile"),
    ("package_manager", "uv.lock"),
    ("package_manager", "poetry.lock"),
    ("package_manager", "Cargo.toml"),
    ("package_manager", "go.mod"),
    ("package_manager", "pom.xml"),
    ("package_manager", "build.gradle"),
    ("package_manager", "build.gradle.kts"),
    ("package_manager", "Gemfile"),
    ("package_manager", "composer.json"),
    ("framework_config", "tsconfig.json"),
    ("framework_config", "tsconfig.*.json"),
    ("framework_config", "vite.config.ts"),
    ("framework_config", "vite.config.js"),
    ("framework_config", "vite.config.mjs"),
    ("framework_config", "next.config.ts"),
    ("framework_config", "next.config.js"),
    ("framework_config", "next.config.mjs"),
    ("framework_config", "nuxt.config.ts"),
    ("framework_config", "nuxt.config.js"),
    ("framework_config", "astro.config.ts"),
    ("framework_config", "astro.config.js"),
    ("framework_config", "astro.config.mjs"),
    ("framework_config", "svelte.config.js"),
    ("framework_config", "svelte.config.ts"),
    ("framework_config", "vue.config.js"),
    ("framework_config", "remix.config.js"),
    ("framework_config", "tailwind.config.*"),
    ("framework_config", "postcss.config.*"),
    ("container", "Dockerfile"),
    ("container", "docker-compose.yml"),
    ("container", "docker-compose.yaml"),
    ("ci", ".github/workflows/*.yml"),
    ("ci", ".github/workflows/*.yaml"),
    ("test", "playwright.config.ts"),
    ("test", "playwright.config.js"),
    ("test", "cypress.config.ts"),
    ("test", "cypress.config.js"),
    ("test", "vitest.config.ts"),
    ("test", "vitest.config.js"),
    ("test", "jest.config.ts"),
    ("test", "jest.config.js"),
    ("test", "pytest.ini"),
    ("test", "tox.ini"),
    ("iac", "*.tf"),
    ("iac", "pulumi.yaml"),
    ("iac", "pulumi.yml"),
    ("env_example", ".env.example"),
    ("env_example", ".env.sample"),
    ("env_example", ".env.template"),
    ("doc", "README.md"),
    ("doc", "README.rst"),
)


def _classify_file(name: str, rel_path: str) -> str | None:
    name_lower = name.lower()
    rel_lower = rel_path.replace("\\", "/").lower()
    for role, pattern in _ROLE_RULES:
        if "/" in pattern:
            if fnmatch.fnmatch(rel_lower, pattern.lower()):
                return role
        else:
            if fnmatch.fnmatch(name_lower, pattern.lower()):
                return role
    return None


_READ_ROLES: frozenset[str] = frozenset(
    {"package_manager", "framework_config", "container", "ci", "doc", "test", "iac", "env_example"}
)


def _should_read(role: str) -> bool:
    return role in _READ_ROLES


def _read_head(path: Path, *, max_lines: int) -> str:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            lines = []
            for index, line in enumerate(handle):
                if index >= max_lines:
                    break
                lines.append(line.rstrip("\n"))
        return "\n".join(lines)
    except OSError:
        return ""


# --- enriquecimento de signals + languages ---------------------------------


_PYPROJECT_LIB_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bfastapi\b", "fastapi"),
    (r"\bdjango\b", "django"),
    (r"\bflask\b", "flask"),
    (r"\btorch\b", "pytorch"),
    (r"\btransformers\b", "transformers"),
    (r"\bstreamlit\b", "streamlit"),
    (r"\btyper\b", "typer"),
    (r"\bcelery\b", "celery"),
    (r"\bsqlalchemy\b", "sqlalchemy"),
    (r"\bpydantic\b", "pydantic"),
)

_PACKAGE_JSON_FRAMEWORKS: tuple[tuple[str, str], ...] = (
    ("react", "react"),
    ("next", "next"),
    ("vue", "vue"),
    ("nuxt", "nuxt"),
    ("svelte", "svelte"),
    ("solid-js", "solid"),
    ("astro", "astro"),
    ("expo", "expo"),
    ("react-native", "react-native"),
    ("vite", "vite"),
    ("vitest", "vitest"),
    ("playwright", "playwright"),
    ("cypress", "cypress"),
    ("jest", "jest"),
    ("tailwindcss", "tailwind"),
)


def _enrich_signals_and_languages(
    role: str,
    name: str,
    excerpt: str,
    signals: dict[str, str],
    languages: set[str],
) -> None:
    name_lower = name.lower()

    if name_lower == "package.json":
        languages.add("javascript")
        frameworks = _detect_package_json_frameworks(excerpt)
        if "typescript" in frameworks:
            languages.add("typescript")
            frameworks.discard("typescript")
        if frameworks:
            signals["js_frameworks"] = ",".join(sorted(frameworks))
        if "react" in frameworks and "vite" in frameworks:
            signals.setdefault("framework", "react+vite")
        elif "next" in frameworks:
            signals.setdefault("framework", "next")
        elif "nuxt" in frameworks:
            signals.setdefault("framework", "nuxt")
        elif "vue" in frameworks:
            signals.setdefault("framework", "vue")
        elif "svelte" in frameworks:
            signals.setdefault("framework", "svelte")
        elif "astro" in frameworks:
            signals.setdefault("framework", "astro")
        elif "expo" in frameworks or "react-native" in frameworks:
            signals.setdefault("framework", "react-native")
        elif "react" in frameworks:
            signals.setdefault("framework", "react")
        signals.setdefault("package_manager_js", "npm")

    elif name_lower == "pyproject.toml":
        languages.add("python")
        libs = _detect_pyproject_libs(excerpt)
        if libs:
            signals["python_libs"] = ",".join(sorted(libs))
        signals.setdefault("package_manager_py", "uv-or-poetry")

    elif name_lower == "uv.lock":
        languages.add("python")
        signals["package_manager_py"] = "uv"

    elif name_lower == "poetry.lock":
        languages.add("python")
        signals["package_manager_py"] = "poetry"

    elif name_lower == "requirements.txt":
        languages.add("python")
        signals.setdefault("package_manager_py", "pip")

    elif name_lower == "cargo.toml":
        languages.add("rust")
        signals["package_manager_rust"] = "cargo"

    elif name_lower == "go.mod":
        languages.add("go")
        signals["package_manager_go"] = "go-modules"

    elif name_lower in {"pom.xml", "build.gradle", "build.gradle.kts"}:
        languages.add("java")

    elif name_lower == "gemfile":
        languages.add("ruby")

    elif name_lower in {"tsconfig.json"} or fnmatch.fnmatch(name_lower, "tsconfig.*.json"):
        languages.add("typescript")
        signals.setdefault("typescript", "yes")

    elif name_lower.startswith("vite.config."):
        signals["bundler"] = "vite"

    elif name_lower.startswith("next.config."):
        signals["framework"] = "next"

    elif name_lower.startswith("nuxt.config."):
        signals["framework"] = "nuxt"

    elif name_lower.startswith("astro.config."):
        signals["framework"] = "astro"

    elif name_lower == "dockerfile" or name_lower.startswith("docker-compose."):
        signals["containerized"] = "yes"

    elif role == "ci":
        signals.setdefault("ci", "github-actions")

    elif role == "test":
        existing = signals.get("test_tools", "")
        tool = name_lower.split(".")[0]
        merged = ",".join(sorted({*filter(None, existing.split(",")), tool}))
        signals["test_tools"] = merged

    elif role == "iac":
        signals.setdefault("iac", "terraform")


def _detect_package_json_frameworks(excerpt: str) -> set[str]:
    frameworks: set[str] = set()
    if not excerpt.strip():
        return frameworks
    try:
        data = json.loads(excerpt)
    except json.JSONDecodeError:
        # Pode ter sido truncado; fallback regex sobre dependencies brutas.
        for needle, label in _PACKAGE_JSON_FRAMEWORKS:
            if re.search(rf'"{re.escape(needle)}"\s*:', excerpt):
                frameworks.add(label)
        if "typescript" in excerpt:
            frameworks.add("typescript")
        return frameworks

    deps: dict[str, str] = {}
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        section = data.get(key)
        if isinstance(section, dict):
            deps.update(section)
    for needle, label in _PACKAGE_JSON_FRAMEWORKS:
        if needle in deps:
            frameworks.add(label)
    if "typescript" in deps:
        frameworks.add("typescript")
    return frameworks


def _detect_pyproject_libs(excerpt: str) -> set[str]:
    found: set[str] = set()
    for pattern, label in _PYPROJECT_LIB_PATTERNS:
        if re.search(pattern, excerpt, flags=re.IGNORECASE):
            found.add(label)
    return found


# --- saida -----------------------------------------------------------------


def _render_summary_markdown(
    root: Path,
    detected: list[DetectedFile],
    signals: tuple[tuple[str, str], ...],
    languages: tuple[str, ...],
) -> str:
    lines: list[str] = []
    lines.append(f"# Project scan: {root.name}")
    lines.append("")
    if languages:
        lines.append("## Languages")
        lines.append(", ".join(languages))
        lines.append("")
    if signals:
        lines.append("## Signals")
        for key, value in signals:
            lines.append(f"- **{key}**: {value}")
        lines.append("")
    if detected:
        lines.append("## Detected files")
        for entry in detected:
            head = f"- `{entry.path}` _{entry.role}_"
            if entry.excerpt:
                snippet_lines = entry.excerpt.splitlines()[:8]
                snippet = "\n    ".join(snippet_lines)
                head += f"\n    ```\n    {snippet}\n    ```"
            lines.append(head)
    return "\n".join(lines)


def _rel(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path)
