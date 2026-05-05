import shutil
from dataclasses import dataclass


@dataclass(frozen=True)
class ToolCheck:
    name: str
    found: bool
    path: str | None
    install_hint: str


CHECKS = [
    ("opencode", "npm i -g opencode-ai  # ou: brew install sst/tap/opencode"),
    ("litellm", "uv tool install 'litellm[proxy]'"),
    ("node", "https://nodejs.org/  (>=20)"),
]


def check_path(cmd: str, install_hint: str) -> ToolCheck:
    path = shutil.which(cmd)
    return ToolCheck(name=cmd, found=path is not None, path=path, install_hint=install_hint)


def run_doctor() -> list[ToolCheck]:
    return [check_path(name, hint) for name, hint in CHECKS]


def format_report(results: list[ToolCheck]) -> str:
    lines = []
    for r in results:
        if r.found:
            lines.append(f"[OK]   {r.name:10} -> {r.path}")
        else:
            lines.append(f"[MISS] {r.name:10} -> install: {r.install_hint}")
    missing = [r for r in results if not r.found]
    if missing:
        lines.append("")
        lines.append(f"{len(missing)} ferramenta(s) faltando. Instale antes de rodar o proxy + opencode.")
    else:
        lines.append("")
        lines.append("Tudo pronto.")
    return "\n".join(lines)
