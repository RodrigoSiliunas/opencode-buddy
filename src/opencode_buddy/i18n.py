"""Catalogo simples de mensagens i18n.

Formato:
- Locale default: pt-BR (todas as chaves preenchidas).
- Locale en-US: stub progressivo. Chaves ausentes caem no fallback pt-BR.
- Locale ativa pode ser sobrescrita via env `OPENCODE_BUDDY_LANG`.

Uso:
    from opencode_buddy.i18n import t
    typer.secho(t("keys.report.header"), bold=True)

Para parametros, use placeholders Python format:
    t("keys.report.missing_env", env="DEEPSEEK_API_KEY")
    -> "falta DEEPSEEK_API_KEY"

Mantenha as chaves em pt-BR sempre populadas. Adicionar uma string nova:
1. Adicione a chave em `_PT_BR`.
2. Opcional: traduza em `_EN_US`.
3. Use `t("nova.chave")` no codigo em vez do literal.
"""
from __future__ import annotations

import os

DEFAULT_LOCALE = "pt-BR"
SUPPORTED_LOCALES = ("pt-BR", "en-US")
ENV_VAR = "OPENCODE_BUDDY_LANG"


_PT_BR: dict[str, str] = {
    # Tags de status (validador, keys validate, scaffolder)
    "tag.ok": "[OK]  ",
    "tag.warn": "[WARN]",
    "tag.error": "[ERR] ",
    "tag.info": "[INFO]",
    "tag.skip": "[SKIP]",
    "tag.miss": "[MISS]",
    "tag.auth": "[AUTH]",
    "tag.net": "[NET] ",
    "tag.recommended": "[recomendado]",
    "tag.live": "[live]",
    "tag.missing_env": "[falta {env}]",
    # Confirmacoes
    "confirm.yes_default": "[S/n]",
    "confirm.no_default": "[s/N]",
    "confirm.invalid": "Responda com s ou n.",
    # keys validate
    "keys.report.header": "Providers",
    "keys.report.empty": "Nenhum provider para validar.",
    "keys.unknown_provider": "[ERRO] provider '{provider}' nao existe no registry.",
    "keys.unknown_provider.available": "       providers disponiveis: {available}",
    # Scaffolder
    "scaffold.next_steps.header": "Proximos passos:",
    "scaffold.next_steps.env": "1. cp .env.example .env  &&  preencher as chaves necessarias",
    "scaffold.next_steps.validate": "2. opencode-buddy validate .   (confere arquivos, prompts, modelos e .env)",
    "scaffold.next_steps.proxy": "3. .\\start-proxy.ps1   (sobe LiteLLM com .env carregado e UTF-8 forcado)",
    "scaffold.next_steps.oauth": "{step}. opencode auth login   (escolher {provider} - so primeira vez)",
    "scaffold.next_steps.run": "{step}. opencode   (em outro terminal, dentro desta pasta)",
    # Wizard
    "wizard.banner.subtitle": "OpenCode Buddy create",
    "wizard.intro": "Vamos montar o projeto em poucos passos.",
    "wizard.target.label": "Pasta do projeto",
    "wizard.target.default": "my-opencode-project",
    "wizard.capabilities.title": "Capacidades do projeto",
    "wizard.capabilities.help": "Selecione todas que se aplicam (separadas por virgula). Apenas as capacidades selecionadas",
    "wizard.capabilities.help2": "vao gerar subperguntas e contexto.",
    "wizard.capabilities.none_option": "Nenhuma dessas",
    "wizard.capabilities.prompt": "Escolha uma ou mais opções (ex: 1,2,4)",
    "wizard.subquestions.title": "Subperguntas por capacidade",
    "wizard.subquestions.help": "Pressione Enter para aceitar o default.",
    "wizard.subquestions.free_text_marker": "(texto livre)",
    "wizard.subquestions.free_prompt": "Resposta livre",
    "wizard.subquestions.choose": "Escolha",
    "wizard.subquestions.unknown": "Resposta nao reconhecida.",
    "wizard.subquestions.out_of_range": "Indice fora da lista.",
    "wizard.providers.detected": "Chaves detectadas: ",
    "wizard.providers.none_detected": "Nenhuma chave de provider detectada no ambiente ou .env local.",
    "wizard.live.confirm": "Consultar modelos disponíveis nos providers detectados agora?",
    "wizard.summary.title": "Resumo",
    "wizard.confirm.generate": "Gerar projeto?",
    # Validator (parciais — restantes seguem em PT-BR fixo no validator.py)
    "validator.summary.ok": "Tudo consistente.",
    "validator.summary.warn": "Valido com {count} aviso(s).",
    "validator.summary.error": "{errors} erro(s), {warnings} aviso(s). Corrija antes de rodar o OpenCode.",
    # Agent Driven Mode
    "agent_driven.title": "OpenCode Buddy - Agent Driven",
    "agent_driven.banner": "Agent Driven Plan",
    "agent_driven.detected.title": "Projeto detectado:",
    "agent_driven.proposed_capabilities.title": "Capacidades propostas:",
    "agent_driven.proposed_models.title": "Modelos propostos:",
    "agent_driven.reasons.title": "Justificativas:",
    "agent_driven.risks.title": "Riscos:",
    "agent_driven.commands.title": "Comandos sugeridos:",
    "agent_driven.choices.approve": "Aprovar e criar",
    "agent_driven.choices.debate": "Debater/alterar plano",
    "agent_driven.choices.cancel": "Cancelar",
    "agent_driven.debate.prompt": "Descreva a alteracao desejada",
    "agent_driven.cancelled": "Cancelado pelo usuario.",
    "agent_driven.planner.using": "Planner ativo: {name}",
    "agent_driven.planner.deterministic": "Planner deterministico (sem LLM).",
    "agent_driven.planner.fallback": "Planner LLM falhou ({reason}); caindo para o deterministico.",
    "agent_driven.planner.error": "Erro no planner: {error}",
    "agent_driven.objective.prompt": "Descreva o objetivo do projeto",
    "agent_driven.target.prompt": "Pasta destino do projeto",
    "agent_driven.scan.summary": "Scan: {files} arquivos detectados, {languages}.",
    "agent_driven.choose.prompt": "Escolha (1=aprovar, 2=debater, 3=cancelar)",
    "agent_driven.dry_run.skip_scaffold": "Dry-run ativo: scaffold_project nao sera chamado.",
    "agent_driven.dry_run.no_files_written": "Dry-run: arquivos NAO foram escritos.",
    "agent_driven.json.requires_dry_run": (
        "[ERRO] --json exige --dry-run para evitar mistura de output humano + JSON. "
        "Use: --dry-run --json."
    ),
}


_EN_US: dict[str, str] = {
    "tag.ok": "[OK]  ",
    "tag.warn": "[WARN]",
    "tag.error": "[ERR] ",
    "tag.info": "[INFO]",
    "tag.skip": "[SKIP]",
    "tag.miss": "[MISS]",
    "tag.auth": "[AUTH]",
    "tag.net": "[NET] ",
    "tag.recommended": "[recommended]",
    "tag.live": "[live]",
    "tag.missing_env": "[missing {env}]",
    "confirm.yes_default": "[Y/n]",
    "confirm.no_default": "[y/N]",
    "confirm.invalid": "Please answer with y or n.",
    "keys.report.header": "Providers",
    "keys.report.empty": "No providers to validate.",
    "keys.unknown_provider": "[ERROR] provider '{provider}' is not in the registry.",
    "keys.unknown_provider.available": "        available providers: {available}",
    "scaffold.next_steps.header": "Next steps:",
    "scaffold.next_steps.env": "1. cp .env.example .env  &&  fill in the required keys",
    "scaffold.next_steps.validate": "2. opencode-buddy validate .   (checks files, prompts, models and .env)",
    "scaffold.next_steps.proxy": "3. .\\start-proxy.ps1   (starts LiteLLM with .env loaded and UTF-8 forced)",
    "scaffold.next_steps.oauth": "{step}. opencode auth login   (choose {provider} - first time only)",
    "scaffold.next_steps.run": "{step}. opencode   (in another terminal, inside this folder)",
    "wizard.banner.subtitle": "OpenCode Buddy create",
    "wizard.intro": "Let's set up the project in a few steps.",
    "wizard.target.label": "Project folder",
    "wizard.target.default": "my-opencode-project",
    "wizard.capabilities.title": "Project capabilities",
    "wizard.capabilities.help": "Select all that apply (comma-separated). Only the selected capabilities",
    "wizard.capabilities.help2": "will trigger sub-questions and context.",
    "wizard.capabilities.none_option": "None of these",
    "wizard.capabilities.prompt": "Pick one or more (e.g. 1,2,4)",
    "wizard.subquestions.title": "Sub-questions by capability",
    "wizard.subquestions.help": "Press Enter to accept the default.",
    "wizard.subquestions.free_text_marker": "(free text)",
    "wizard.subquestions.free_prompt": "Free answer",
    "wizard.subquestions.choose": "Choose",
    "wizard.subquestions.unknown": "Answer not recognized.",
    "wizard.subquestions.out_of_range": "Index out of range.",
    "wizard.providers.detected": "Detected keys: ",
    "wizard.providers.none_detected": "No provider keys detected in environment or local .env.",
    "wizard.live.confirm": "Query available models from detected providers now?",
    "wizard.summary.title": "Summary",
    "wizard.confirm.generate": "Generate project?",
    "validator.summary.ok": "Everything consistent.",
    "validator.summary.warn": "Valid with {count} warning(s).",
    "validator.summary.error": "{errors} error(s), {warnings} warning(s). Fix before running OpenCode.",
    "agent_driven.title": "OpenCode Buddy - Agent Driven",
    "agent_driven.banner": "Agent Driven Plan",
    "agent_driven.detected.title": "Detected project:",
    "agent_driven.proposed_capabilities.title": "Proposed capabilities:",
    "agent_driven.proposed_models.title": "Proposed models:",
    "agent_driven.reasons.title": "Reasoning:",
    "agent_driven.risks.title": "Risks:",
    "agent_driven.commands.title": "Suggested commands:",
    "agent_driven.choices.approve": "Approve and create",
    "agent_driven.choices.debate": "Discuss/edit plan",
    "agent_driven.choices.cancel": "Cancel",
    "agent_driven.debate.prompt": "Describe the change you want",
    "agent_driven.cancelled": "Cancelled by user.",
    "agent_driven.planner.using": "Active planner: {name}",
    "agent_driven.planner.deterministic": "Deterministic planner (no LLM).",
    "agent_driven.planner.fallback": "LLM planner failed ({reason}); falling back to deterministic.",
    "agent_driven.planner.error": "Planner error: {error}",
    "agent_driven.objective.prompt": "Describe the project goal",
    "agent_driven.target.prompt": "Project destination folder",
    "agent_driven.scan.summary": "Scan: {files} files detected, {languages}.",
    "agent_driven.choose.prompt": "Choose (1=approve, 2=discuss, 3=cancel)",
    "agent_driven.dry_run.skip_scaffold": "Dry-run active: scaffold_project will not be called.",
    "agent_driven.dry_run.no_files_written": "Dry-run: no files were written.",
    "agent_driven.json.requires_dry_run": (
        "[ERROR] --json requires --dry-run to avoid mixing human output with JSON. "
        "Use: --dry-run --json."
    ),
}


_CATALOG: dict[str, dict[str, str]] = {
    "pt-BR": _PT_BR,
    "en-US": _EN_US,
}


_active_locale: str = DEFAULT_LOCALE


def _resolve_initial_locale() -> str:
    raw = os.environ.get(ENV_VAR, "").strip()
    if not raw:
        return DEFAULT_LOCALE
    if raw in SUPPORTED_LOCALES:
        return raw
    # Tenta normalizar pt_BR -> pt-BR ou en_US -> en-US
    normalized = raw.replace("_", "-")
    if normalized in SUPPORTED_LOCALES:
        return normalized
    # Match por prefixo (pt -> pt-BR, en -> en-US)
    prefix = normalized.split("-")[0].lower()
    for code in SUPPORTED_LOCALES:
        if code.lower().startswith(prefix):
            return code
    return DEFAULT_LOCALE


_active_locale = _resolve_initial_locale()


def get_locale() -> str:
    return _active_locale


def set_locale(code: str) -> None:
    global _active_locale
    if code not in SUPPORTED_LOCALES:
        raise ValueError(f"locale nao suportado: {code} (esperado: {', '.join(SUPPORTED_LOCALES)})")
    _active_locale = code


def t(msgid: str, /, **kwargs: object) -> str:
    """Retorna a string traduzida no locale ativo, com fallback para pt-BR.

    Primeiro argumento e positional-only (msgid) para nao colidir com placeholders
    chamados `key`, `id`, etc. Se a chave nao existir em nenhum catalogo, retorna
    a propria chave (debug-friendly).
    """
    catalog = _CATALOG.get(_active_locale, {})
    template = catalog.get(msgid)
    if template is None and _active_locale != DEFAULT_LOCALE:
        template = _CATALOG[DEFAULT_LOCALE].get(msgid)
    if template is None:
        return msgid
    if kwargs:
        try:
            return template.format(**kwargs)
        except (KeyError, IndexError):
            return template
    return template


def all_keys(locale: str = DEFAULT_LOCALE) -> tuple[str, ...]:
    return tuple(sorted(_CATALOG.get(locale, {}).keys()))


def missing_in_locale(locale: str) -> tuple[str, ...]:
    """Chaves do pt-BR ainda nao traduzidas em `locale`."""
    if locale == DEFAULT_LOCALE:
        return ()
    target = _CATALOG.get(locale, {})
    return tuple(sorted(key for key in _PT_BR if key not in target))
