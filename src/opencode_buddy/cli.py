import json
import sys
from importlib import resources
from pathlib import Path

import typer
import yaml

from opencode_buddy.config_builder import (
    InitOptions,
    build_env_example,
    build_litellm_config,
    build_opencode_config,
    build_start_proxy_script,
)
from opencode_buddy.doctor import format_report, run_doctor

app = typer.Typer(
    add_completion=False,
    help="Scaffolder de projetos OpenCode com proxy LiteLLM (DeepSeek + Kimi + ChatGPT OAuth).",
)

AGENT_FILES = ("orchestrator.md", "frontend.md", "backend.md", "default.md", "deep.md")


def _write(path: Path, content: str, force: bool) -> None:
    if path.exists() and not force:
        typer.secho(f"[SKIP] {path} já existe (use --force para sobrescrever)", fg=typer.colors.YELLOW)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    typer.secho(f"[OK]   {path}", fg=typer.colors.GREEN)


def _copy_template(name: str, dest: Path, force: bool) -> None:
    src = resources.files("opencode_buddy.templates").joinpath(name)
    content = src.read_text(encoding="utf-8")
    _write(dest, content, force)


@app.command()
def init(
    path: Path = typer.Argument(Path("."), help="Diretório destino do projeto"),
    litellm_url: str = typer.Option("http://localhost:4000/v1", help="Base URL do proxy LiteLLM"),
    litellm_port: int = typer.Option(4000, help="Porta do proxy LiteLLM"),
    no_chatgpt: bool = typer.Option(False, "--no-chatgpt", help="Desabilita subagent backend (ChatGPT OAuth)"),
    opencode_go_api_base: str = typer.Option("https://opencode.ai/zen/go/v1"),
    go_kimi_model: str = typer.Option("kimi-k2.6"),
    go_deepseek_fast_model: str = typer.Option("deepseek-v4-flash"),
    go_heavy_fallback_model: str = typer.Option("qwen3.6-plus"),
    deepseek_fast_direct_model: str = typer.Option("deepseek/deepseek-chat"),
    deepseek_pro_direct_model: str = typer.Option("deepseek/deepseek-reasoner"),
    routing_strategy: str = typer.Option("simple-shuffle"),
    backend_model: str = typer.Option("chatgpt/gpt-5.5"),
    force: bool = typer.Option(False, "--force", help="Sobrescreve arquivos existentes"),
) -> None:
    """Gera opencode.json + litellm-config.yaml + .env.example + .opencode/agents/."""

    opts = InitOptions(
        litellm_url=litellm_url,
        litellm_port=litellm_port,
        enable_chatgpt=not no_chatgpt,
        opencode_go_api_base=opencode_go_api_base,
        go_kimi_model=go_kimi_model,
        go_deepseek_fast_model=go_deepseek_fast_model,
        go_heavy_fallback_model=go_heavy_fallback_model,
        deepseek_fast_direct_model=deepseek_fast_direct_model,
        deepseek_pro_direct_model=deepseek_pro_direct_model,
        routing_strategy=routing_strategy,
        backend_model=backend_model,
    )

    target = path.resolve()
    target.mkdir(parents=True, exist_ok=True)

    opencode_json = json.dumps(build_opencode_config(opts), indent=2, ensure_ascii=False) + "\n"
    litellm_yaml = yaml.safe_dump(build_litellm_config(opts), sort_keys=False)
    env_example = build_env_example(opts)
    start_proxy = build_start_proxy_script(opts)

    _write(target / "opencode.json", opencode_json, force)
    _write(target / "litellm-config.yaml", litellm_yaml, force)
    _write(target / ".env.example", env_example, force)
    _write(target / "start-proxy.ps1", start_proxy, force)

    agents_dir = target / ".opencode" / "agents"
    for fname in AGENT_FILES:
        if fname == "backend.md" and not opts.enable_chatgpt:
            continue
        _copy_template(fname, agents_dir / fname, force)

    typer.echo("")
    typer.secho("Próximos passos:", fg=typer.colors.CYAN, bold=True)
    typer.echo("  1. cp .env.example .env  &&  preencher OPENCODE_GO_API_KEY + DEEPSEEK_API_KEY + LITELLM_MASTER_KEY")
    typer.echo("  2. .\\start-proxy.ps1   (sobe LiteLLM com .env carregado e UTF-8 forçado)")
    if opts.enable_chatgpt:
        typer.echo("  3. opencode auth login   (escolher chatgpt — só primeira vez)")
    typer.echo(f"  {'4' if opts.enable_chatgpt else '3'}. opencode   (em outro terminal, dentro desta pasta)")


@app.command()
def doctor() -> None:
    """Verifica se opencode, litellm e node estão instalados."""
    results = run_doctor()
    typer.echo(format_report(results))
    if any(not r.found for r in results):
        sys.exit(1)


if __name__ == "__main__":
    app()
