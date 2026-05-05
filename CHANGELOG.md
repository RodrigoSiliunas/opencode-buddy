# Changelog

Todas as mudanças notáveis do projeto vão aqui. Formato baseado em
[Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/), versionamento
seguindo [SemVer](https://semver.org/lang/pt-BR/).

## [Unreleased]

### Added (Agent Driven Mode — Refinements Round)
- **Adapter nativo Anthropic** (`AnthropicPlannerClient`): chama `POST /v1/messages` com headers `x-api-key` + `anthropic-version: 2023-06-01`. `ANTHROPIC_API_KEY` agora é planner válido (`--planner=anthropic` ou auto-pick).
- **Adapter nativo Gemini** (`GeminiPlannerClient`): chama `generateContent` com header `x-goog-api-key`. `GEMINI_API_KEY` agora é planner válido. **API key não vai pela URL** (`?key=...`); só por header.
- **Schema JSON formal** (`src/opencode_buddy/agent_driven_schema.py`): JSON Schema draft-07 + validador manual estrito (sem dependência de `jsonschema`). Cobre tipos, campos obrigatórios, enums (capability/role), `additionalProperties: false`, regra "model_choices precisa cobrir build/default/deep". Schema é embutido no `PLANNER_SYSTEM_PROMPT` para o LLM.
- **`--dry-run` e `--json`** no `agent-driven`:
  - `--dry-run`: gera plano, pode rodar review interativo, **não** chama `scaffold_project`.
  - `--dry-run --json`: pula review, imprime JSON em stdout (sem `raw_response`), exit 0. Stdout limpo; mensagens informativas vão a stderr.
  - `--json` sem `--dry-run`: erro amigável (exit 2) pedindo `--dry-run`.
  - Helper público `plan_to_jsonable_public(plan, include_raw=False)`.
- **`examples/`**:
  - `examples/agent-driven-existing-vite/` (`package.json`, `vite.config.ts`, `tsconfig.json`, `README.md`).
  - `examples/agent-driven-new-project/README.md`.
  - `examples/model-registry-extension.yaml` (documentação viva, não carregado).
- 30+ testes novos (schema, adapters Anthropic/Gemini, dry-run/json, examples).

### Changed (Agent Driven Mode — Refinements Round)
- `select_planner` agora aceita `--planner=anthropic`/`--planner=gemini`. Auto-pick: OpenAI-compatible primeiro (deepseek > moonshot > opencode-go > commandcode), depois Anthropic > Gemini. Sem chave + provider explícito → erro amigável apontando a env esperada.
- `_parse_plan_payload` faz validação estrita via `validate_plan_payload`; payload off-schema vira `PlannerError` e dispara fallback automático.
- README pt+en atualizado (planners suportados, `--dry-run --json`, links para `examples/`).

### Added
- **Agent Driven Mode** (`opencode-buddy agent-driven`): comando novo que vasculha um projeto local (ou conversa em modo "novo projeto"), pede a um LLM planner que proponha capacidades, agents, modelos por papel, riscos e comandos, exibe o plano em estilo "plan mode" e só executa `scaffold_project` ao aprovar. Suporta `--scan`, `--target`, `--planner`, `--offline`, `--objective`, `--force`. Scanner ignora `.git`/`node_modules`/`.venv`/`dist`/`build`/caches e nunca lê `.env` ou arquivos sensíveis (`*.key`/`*.pem`/`*credential*`).
- `src/opencode_buddy/project_scanner.py`: walk com skip-list, classificação de arquivos (package_manager, framework_config, ci, iac, doc, test, container, env_example), extração de signals (`framework`, `js_frameworks`, `python_libs`, `bundler`, `containerized`, `multimodal_hints`, etc).
- `src/opencode_buddy/agent_driven.py`: dataclasses (`AgentDrivenRequest`/`Decision`/`ModelChoice`/`Plan`), `PlannerClient` Protocol, `DeterministicPlannerClient` (fallback sem rede que sempre produz spec válido via registry), `LiteLLMPlannerClient` (HTTP via `urllib`, OpenAI-compatible only), `select_planner`, `plan_to_project_spec` (reconstrução de `ModelSpec` 100% pelo registry), `run_review_loop`, `propose_plan_with_fallback`, `PLANNER_SYSTEM_PROMPT`.
- 41 testes novos (`tests/test_project_scanner.py`, `tests/test_agent_driven.py`, smoke no `tests/test_cli.py`).
- Chaves i18n `agent_driven.*` em pt-BR + en-US.

### Notes / segurança
- O Agent Driven Mode original nasceu com live planner apenas para providers genuinamente OpenAI-compatible (`deepseek`, `moonshot`, `opencode-go`, `commandcode`). A rodada de refinamentos em `[Unreleased]` adiciona adapters nativos para Anthropic e Gemini.
- O body enviado ao LLM contém apenas **nomes** de env vars detectadas, jamais valores. Teste explícito garante que o valor não vaza no payload.
- JSON malformado ou HTTP error caem automaticamente no `DeterministicPlannerClient` com aviso visível.
- Cancelamento na revisão emite `Exit(1)` e não escreve arquivos.

## [0.5.0] - 2026-05-05

### Added
- Registry declarativo de providers e modelos em `src/opencode_buddy/model_registry.yaml`. Adicionar provider/modelo agora exige só editar YAML.
- Comando `opencode-buddy keys validate` (com `--json`, `--provider`, `--strict`, `--timeout`). Valida ENV, autentica com providers, lista modelos. Nunca vaza valores de chave.
- `.gitignore` automático no scaffold + `validate` checa proteção de `.env`.
- 14 capacidades no wizard (4 com agent dedicado + 10 context-only). Subperguntas objetivas por capacidade.
- `.opencode/project.md` rico: visão geral, capacidades, modelos por papel, comandos, convenções, restrições, riscos.
- OAuth como transporte de primeira classe — múltiplos providers OAuth suportados via registry.
- `init --spec project-spec.yaml` carrega defaults declarativos (YAML ou JSON). Veja `examples/opencode-buddy.spec.yaml`.
- Módulo `i18n` (`src/opencode_buddy/i18n.py`) com pt-BR completo + en-US progressivo. Switch via `OPENCODE_BUDDY_LANG`.
- Engine de scaffolding extraído para `src/opencode_buddy/scaffolder.py`. `init` e `create` compartilham `scaffold_project()`.
- Metadata completa do pacote em `pyproject.toml` (`authors`, `urls`, `classifiers`, `readme`).
- Smoke de empacotamento no CI: build do wheel + install + checagem de que `model_registry.yaml` e `templates/` estão dentro.
- 122 testes (era 54 em 0.4.0).

### Changed
- Defaults de `InitOptions` (modelos OpenCode Go, DeepSeek) agora vêm do registry. Flags do `init` continuam funcionando como overrides.
- `validate --strict` agora falha quando `.env` está ausente. Mensagem do warning indica o comportamento estrito.
- Templates dos agents (`default.md`, `backend.md`, `frontend.md`, `deep.md`) reforçam leitura de `.opencode/project.md`.

### Fixed
- Wheel agora empacota `model_registry.yaml` corretamente (`pyproject.toml` `force-include`).

### Verificação manual recomendada antes de tag

```powershell
uv sync --all-extras
uv build
uv tool install --editable . --force
opencode-buddy --help
opencode-buddy doctor
opencode-buddy init test-release --force
opencode-buddy validate test-release
opencode-buddy keys validate --json | python -c "import json,sys; print(len(json.load(sys.stdin)), 'providers')"
Remove-Item -Recurse -Force test-release
uv tool uninstall opencode-buddy
```

## [0.4.0] - 2026-04-30

Release inicial. Wizard básico, `init`, `validate`, `doctor`.

[0.5.0]: https://github.com/RodrigoSiliunas/opencode-buddy/releases/tag/v0.5.0
[0.4.0]: https://github.com/RodrigoSiliunas/opencode-buddy/releases/tag/v0.4.0
