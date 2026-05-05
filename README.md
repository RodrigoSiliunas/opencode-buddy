# opencode-buddy

[![tests](https://github.com/RodrigoSiliunas/opencode-buddy/actions/workflows/test.yml/badge.svg)](https://github.com/RodrigoSiliunas/opencode-buddy/actions/workflows/test.yml)
[![license](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org)
[![version](https://img.shields.io/badge/version-0.5.0-blue.svg)](CHANGELOG.md)

Scaffolder de projetos [OpenCode](https://opencode.ai) com proxy [LiteLLM](https://docs.litellm.ai), wizard estilo Vite, modo **Agent Driven** e roteamento inteligente entre **OpenCode Go**, **DeepSeek**, **Moonshot**, **Anthropic**, **Gemini**, endpoints OpenAI-compatible e **ChatGPT OAuth**.

> **EN:** Project scaffolder for [OpenCode](https://opencode.ai) with [LiteLLM](https://docs.litellm.ai), a Vite-like wizard, **Agent Driven Mode**, and smart routing across **OpenCode Go**, **DeepSeek**, **Moonshot**, **Anthropic**, **Gemini**, OpenAI-compatible endpoints, and **ChatGPT OAuth**. Generates `opencode.json`, `litellm-config.yaml`, `.env.example`, helper PowerShell script, project context, and specialist agent prompts.

[Português](#português) · [English](#english)

---

## Português

### O que faz

O OpenCode Buddy gera um workspace OpenCode pronto para usar com agents, modelos por papel, proxy LiteLLM e contexto de projeto. Existem três fluxos principais:

- `opencode-buddy init <pasta>`: modo direto/scriptável, com flags ou `--spec`.
- `opencode-buddy create`: wizard interativo estilo Vite, com capacidades e subperguntas.
- `opencode-buddy agent-driven`: planner por IA ou heurística determinística, com scan do projeto, plano revisável e scaffold só após aprovação.

- `opencode.json` com agents conforme as capacidades do projeto + agent orquestrador que delega automaticamente
- `litellm-config.yaml` com aliases por papel e providers escolhidos no wizard
- `.env.example` só com as chaves necessárias para os providers escolhidos
- `.gitignore` que protege `.env`/`.env.*` e libera apenas `.env.example` (evita commit acidental de secrets)
- `start-proxy.ps1` — helper Windows que carrega o `.env`, força UTF-8 (workaround pra bug do banner LiteLLM em cp1252) e sobe o proxy
- `.opencode/project.md` com contexto rico — visão geral, capacidades selecionadas (com subrespostas), modelos por papel, comandos úteis, convenções, restrições e riscos. Cada agent é instruído a respeitar este arquivo
- `.opencode/agents/*.md` — system prompts pra cada specialist

### Arquitetura de roteamento

```
                     ┌─────────────────────┐
   /agent frontend ─→│  Kimi K2.6 via Go   │
                     ├─────────────────────┤
   /agent backend  ─→│  GPT-5.5 (ChatGPT   │  ← OAuth, fora do LiteLLM
                     │   OAuth nativo)     │
                     ├─────────────────────┤
   /agent default  ─→│  DeepSeek V4 Flash  │ → falhou? → DeepSeek direto
                     │       via Go        │
                     ├─────────────────────┤
   /agent deep     ─→│  DeepSeek Reasoner  │ → falhou? → Qwen3.6 via Go
                     │      direto         │
                     └─────────────────────┘
                              ↑
                     ┌─────────────────────┐
   prompt qualquer ─→│  build (orquestr.)  │ → classifica e delega
                     │  DeepSeek-fast cls. │   via tool `task`
                     └─────────────────────┘
```

GPT vai por OAuth direto do OpenCode (não passa pelo LiteLLM). Todo o resto passa pelo proxy local em `http://localhost:4000`.

### Pré-requisitos

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (`pipx install uv` ou `winget install astral-sh.uv`)
- [OpenCode CLI](https://opencode.ai) (`npm i -g opencode-ai`)
- LiteLLM proxy (`uv tool install 'litellm[proxy]'`)
- Conta [OpenCode Go](https://opencode.ai/auth) ($10/mês) — gera `OPENCODE_GO_API_KEY`
- (opcional) Chave [DeepSeek](https://platform.deepseek.com) — usado como fallback
- (opcional) Login OAuth ChatGPT pelo OpenCode (`opencode auth login`)

### Instalação

```bash
git clone https://github.com/RodrigoSiliunas/opencode-buddy.git
cd opencode-buddy
uv tool install --editable .
```

Verifica deps externos:

```bash
opencode-buddy doctor
```

### Começo rápido

Projeto novo com wizard:

```bash
opencode-buddy create meu-app
```

Projeto existente com plano automático, sem chamar LLM:

```bash
opencode-buddy agent-driven --scan . --offline --dry-run --json
opencode-buddy agent-driven --scan . --target . --offline
```

Uso scriptável/reprodutível:

```bash
opencode-buddy init meu-app --spec examples/opencode-buddy.spec.yaml
```

### Criação interativa

```bash
opencode-buddy create
```

O wizard pergunta a pasta e quais capacidades o projeto inclui. As capacidades suportadas hoje são:

- **Com agent dedicado** (geram model picker + prompt especializado): Frontend/UI, Backend/API, Audio/speech, Video/multimodal.
- **Apenas contexto** (alimentam `.opencode/project.md` mas não criam agent): Mobile, CLI/tooling, Desktop, Data/ETL, ML/AI, DevOps/infra, QA/testes, Documentacao, Security, Integracoes externas.

Para cada capacidade selecionada, o wizard faz subperguntas objetivas (framework, runtime, banco, auth, etc) e usa as respostas para preencher o `.opencode/project.md`, que vira fonte de verdade para os agents.

Quando existem chaves no ambiente ou em um `.env` local, o wizard pode consultar os modelos disponíveis dos providers. Se a consulta falhar ou nenhuma chave existir, ele mostra sugestões locais e marca quais chaves faltam.

Providers disponíveis no wizard:

- OpenCode Go
- DeepSeek direto
- Moonshot/Kimi direto
- Anthropic Claude
- Google Gemini
- CommandCode/OpenAI-compatible
- ChatGPT OAuth detectado via `opencode auth list`

Exemplo de fluxo:

```bash
opencode-buddy create meu-app
```

### Uso direto

```bash
mkdir meu-projeto && cd meu-projeto
opencode-buddy init .
cp .env.example .env
# editar .env com chaves reais
opencode-buddy validate .      # confere arquivos, modelos, prompts e .env
.\start-proxy.ps1            # terminal A — sobe LiteLLM
opencode                     # terminal B — abre OpenCode
```

Dentro do OpenCode, agent `build` (default) classifica seu pedido e delega:

- "crie um botão React com hover" → `@frontend` (Kimi K2.6)
- "crie endpoint POST /upload com auth" → `@backend` (GPT-5.5 via OAuth)
- "explica esse arquivo" → `@default` (DeepSeek V4 Flash)
- "qual arquitetura de fila pra job assíncrono" → `@deep` (DeepSeek Reasoner)

Pra forçar um agent específico: `/agent frontend` antes do prompt.

Para estender o scaffold com um agent próprio:

```bash
opencode-buddy init . --extra-agent reviewer=litellm/deepseek-pro:"revisão crítica de código"
```

Isso adiciona o agent em `opencode.json`, gera `.opencode/agents/reviewer.md` e ensina o orquestrador a delegar para ele quando o pedido combinar com a descrição.

### Flags do init

```
opencode-buddy init <pasta>
  --spec project-spec.yaml             # carrega defaults declarativos (YAML ou JSON)
  --litellm-url http://localhost:4000/v1
  --litellm-port 4000
  --no-chatgpt                          # pula subagent backend
  --opencode-go-api-base https://opencode.ai/zen/go/v1
  --go-kimi-model kimi-k2.6
  --go-deepseek-fast-model deepseek-v4-flash
  --go-heavy-fallback-model qwen3.6-plus
  --deepseek-fast-direct-model deepseek/deepseek-chat
  --deepseek-pro-direct-model deepseek/deepseek-reasoner
  --backend-model chatgpt/gpt-5.5
  --routing-strategy simple-shuffle
  --extra-agent nome=modelo[:descrição]     # adiciona agent customizado
  --force                               # sobrescreve arquivos existentes
```

`init` e `create` compartilham o mesmo motor (`opencode_buddy.scaffolder.scaffold_project`). Ambos constroem um `ProjectSpec` (= `InitOptions`) e o passam para o engine. A diferença e somente como o `ProjectSpec` e produzido: flags vs. wizard interativo.

### Spec declarativo (`--spec`)

`opencode-buddy init . --spec project-spec.yaml` carrega defaults de um arquivo YAML ou JSON com campos de `InitOptions`. Flags ainda tem precedencia. Util para versionar a configuracao de scaffold do projeto e reproduzir o setup em outras maquinas/CI.

```yaml
# project-spec.yaml — minimo
litellm_url: http://localhost:5000/v1
litellm_port: 5000
backend_model: litellm/deepseek-pro
routing_strategy: simple-shuffle
```

Campos nao reconhecidos abortam com erro listando os campos validos.

Exemplo completo com todos os campos suportados (`extra_agents`, `model_specs`, `fallback_rules`, `project_context.capabilities`, `role_models`, `conventions`, `constraints`, `risks`): [`examples/opencode-buddy.spec.yaml`](examples/opencode-buddy.spec.yaml).

### Modo Agent Driven

```bash
opencode-buddy agent-driven --scan .                          # vasculha o projeto atual
opencode-buddy agent-driven --scan ./apps/web --target ./apps/web --offline
opencode-buddy agent-driven --planner deepseek                # OpenAI-compatible
opencode-buddy agent-driven --planner anthropic               # adapter nativo
opencode-buddy agent-driven --planner gemini                  # adapter nativo
opencode-buddy agent-driven --offline                         # 100% determinista, sem LLM
opencode-buddy agent-driven --scan . --offline --dry-run --json   # automacao: JSON puro em stdout
```

O comando vasculha a pasta indicada (ou conversa pra montar projeto novo), passa um resumo curto + nomes das chaves detectadas pra um planner LLM, e exibe um plano com capacidades, modelos por papel, justificativas e riscos. O usuário pode **aprovar**, **debater/alterar** (texto livre) ou **cancelar**. Só ao aprovar o `scaffold_project` escreve arquivos.

Planners suportados (live):

| Provider | Transporte | Auth |
|---|---|---|
| `deepseek` | OpenAI-compatible (`/chat/completions`) | `DEEPSEEK_API_KEY` |
| `moonshot` | OpenAI-compatible | `MOONSHOT_API_KEY` |
| `opencode-go` | OpenAI-compatible | `OPENCODE_GO_API_KEY` |
| `commandcode` | OpenAI-compatible | `COMMANDCODE_API_KEY` + `COMMANDCODE_API_BASE` |
| `anthropic` | Adapter nativo `/v1/messages` (`x-api-key` + `anthropic-version`) | `ANTHROPIC_API_KEY` |
| `gemini` | Adapter nativo `generateContent` (`x-goog-api-key`) | `GEMINI_API_KEY` |

Auto-pick (`--planner=auto`): tenta OpenAI-compatible primeiro, depois Anthropic, depois Gemini. Sem chaves disponíveis, cai no determinístico.

Modos de saída:

- **default**: review interativo + scaffold após aprovação.
- **`--dry-run`**: review interativo, plano impresso, **sem** escrever arquivos.
- **`--dry-run --json`**: pula review, JSON do plano em stdout, sem arquivos. Ideal para automação. Stdout só JSON; mensagens informativas vão a stderr.
- **`--json` sozinho**: erro amigável pedindo `--dry-run` (evita stdout sujo).

Schema formal: `src/opencode_buddy/agent_driven_schema.py` define um JSON Schema (draft-07) que valida toda resposta do planner. Schema é embutido no prompt do LLM e usado para rejeitar payloads inválidos antes de virar `ProjectSpec`. Se o LLM responde algo fora do schema (ex: role inventada), o orquestrador cai no determinístico com aviso.

Restrições de segurança:

- O scanner ignora `.git`, `node_modules`, `.venv`, `dist`, `build`, caches; nunca lê `.env` ou arquivos do tipo `*.key`/`*.pem`/`*credential*`.
- O payload enviado ao LLM contém apenas **nomes** de variáveis de ambiente detectadas (ex: `DEEPSEEK_API_KEY`), nunca os valores. A chave vai apenas em headers (`Authorization` no OpenAI-compatible, `x-api-key` no Anthropic, `x-goog-api-key` no Gemini). Gemini **não** usa `?key=...` na URL.
- `--json` nunca inclui `raw_response` (debug interno). Output público é construído via `plan_to_jsonable_public(plan, include_raw=False)`.
- Sem chaves detectadas, o planner determinístico gera spec **válido** preenchido pelos defaults do registry com risco visível pedindo `.env`.
- JSON malformado / HTTP error / schema inválido cai automaticamente no determinístico com aviso visível em stderr; nada é escrito antes da aprovação.

Exemplos prontos em [`examples/`](examples/):

- [`examples/agent-driven-existing-vite/`](examples/agent-driven-existing-vite/) — fixture React+Vite para `--scan`.
- [`examples/agent-driven-new-project/`](examples/agent-driven-new-project/) — referência para `--objective`.
- [`examples/model-registry-extension.yaml`](examples/model-registry-extension.yaml) — como adicionar provider no registry.
- [`examples/opencode-buddy.spec.yaml`](examples/opencode-buddy.spec.yaml) — spec declarativo para `init --spec`.

### Validação

```bash
opencode-buddy validate <pasta>
opencode-buddy validate <pasta> --strict
```

O comando valida se `opencode.json` e `litellm-config.yaml` fazem parse, se os prompts referenciados existem, se os aliases `litellm/...` usados pelos agents existem no `model_list`, se `.env`/`.env.example` declaram as chaves esperadas e se `.gitignore` está presente e protege `.env`.

Em modo `--strict`, qualquer aviso vira erro (exit 1). Em particular, **`--strict` falha quando o arquivo `.env` ainda não existe** (apenas `.env.example` está presente) — esse é o caso típico logo após `init`/`create`. Use `--strict` em CI para garantir que o operador já criou e preencheu o `.env` real, e use sem `--strict` durante o setup local.

### Validar chaves de provider (`keys validate`)

```bash
opencode-buddy keys validate
opencode-buddy keys validate --provider deepseek
opencode-buddy keys validate --json
opencode-buddy keys validate --strict --timeout 10
```

Para cada provider do registry, o comando verifica:

- presença das ENV vars necessárias (`api_key_env`, `api_base_env`);
- listagem real de modelos via API (quando `discovery.kind` suporta);
- detecção de OAuth via `opencode auth list`.

Saída texto:

```
Providers
  [OK]   DeepSeek        API    2 modelos encontrados
  [MISS] Anthropic       API    falta ANTHROPIC_API_KEY
  [AUTH] OpenCode Go     API    chave rejeitada (HTTP 401)
  [SKIP] ChatGPT OAuth   OAuth  login nao detectado em `opencode auth list`
```

States: `ok`, `missing-env`, `auth-failed`, `network-failed`, `unsupported-discovery`, `skipped`. Em modo padrão só `auth-failed` causa exit 1; com `--strict`, `missing-env` e `network-failed` também falham. Valores de chave **nunca** aparecem na saída.

`--json` produz uma lista parseável para CI/scripts.

### Registry de modelos

Providers e modelos sugeridos vivem em `src/opencode_buddy/model_registry.yaml`. Para adicionar um modelo novo basta editar o YAML — não precisa mexer em código Python:

```yaml
providers:
  - key: meu-provider
    name: Meu Provider
    transport: API
    api_key_env: MEUPROVIDER_API_KEY
    api_base: https://api.meuprovider.com/v1
    litellm_prefix: openai
    discovery:
      kind: openai-compatible       # openai-compatible | deepseek | anthropic | gemini | none
    cost_label: low
    recommended_for: [backend, default]
    models:
      - id: meu-modelo-flash
        recommended_for: [backend, default]
```

Para OAuth (ex: ChatGPT), use a seção `oauth_providers` com `detect.kind: opencode-auth-list`. As flags do `init` continuam funcionando — quando ausentes, os defaults vêm do registry.

### Internacionalização (i18n)

A CLI roda em pt-BR por padrão. O catálogo de mensagens vive em `src/opencode_buddy/i18n.py` (chaves no formato `categoria.subchave`). Para experimentar en-US:

```bash
$env:OPENCODE_BUDDY_LANG = "en-US"   # PowerShell
# ou
export OPENCODE_BUDDY_LANG=en-US     # bash
opencode-buddy keys validate
```

en-US é um stub progressivo: chaves não traduzidas caem no fallback pt-BR. Para contribuir traduções, edite o dict `_EN_US` em `i18n.py`. Use `opencode_buddy.i18n.missing_in_locale("en-US")` para listar chaves faltantes.

### Desenvolvimento

```bash
uv sync --all-extras
uv run pytest -v
```

### Limitações conhecidas

- **Windows + LiteLLM**: o banner ASCII do LiteLLM contém Unicode que cp1252 rejeita. `start-proxy.ps1` força `PYTHONIOENCODING=utf-8` automaticamente. Em Linux/Mac não há esse problema.
- **Catálogo do OpenCode Go pode mudar**: nomes como `kimi-k2.6`, `deepseek-v4-flash`, `qwen3.6-plus` são placeholders. Confira modelos atuais com `curl -H "Authorization: Bearer $OPENCODE_GO_API_KEY" https://opencode.ai/zen/go/v1/models | jq` e ajuste com as flags `--go-*-model`.
- **DeepSeek Reasoner não está no Go**: por isso `deep` agent vai direto pra API DeepSeek e usa Qwen3.6 do Go como fallback.

### Contribuindo

PRs bem-vindos. Antes:

1. `uv run pytest` deve passar
2. Adicione teste pra mudança de comportamento
3. Atualize o README se a CLI mudar

### Licença

[MIT](LICENSE)

---

## English

### What it does

OpenCode Buddy generates a ready-to-use OpenCode workspace with agents, per-role models, a LiteLLM proxy, and project context. There are three main flows:

- `opencode-buddy init <folder>`: direct/scriptable mode, with flags or `--spec`.
- `opencode-buddy create`: Vite-like interactive wizard with capabilities and sub-questions.
- `opencode-buddy agent-driven`: AI or deterministic planner, project scan, reviewable plan, and scaffold only after approval.

- `opencode.json` with agents generated from project capabilities + an orchestrator agent that auto-delegates
- `litellm-config.yaml` with aliases per role, selected providers and fallback rules when configured
- `.env.example` with only the keys required by the selected providers
- `.gitignore` that protects `.env`/`.env.*` and only allows `.env.example` (prevents accidental secret commits)
- `start-proxy.ps1` — Windows helper that loads `.env`, forces UTF-8 (workaround for LiteLLM banner cp1252 bug), and starts the proxy
- `.opencode/project.md` with rich project context: overview, selected capabilities, per-role models, useful commands, conventions, constraints and risks
- `.opencode/agents/*.md` — system prompts for each specialist

### Routing architecture

```
                     ┌─────────────────────┐
   /agent frontend ─→│  Kimi K2.6 via Go   │
                     ├─────────────────────┤
   /agent backend  ─→│  GPT-5.5 (ChatGPT   │  ← OAuth, bypasses LiteLLM
                     │     OAuth)          │
                     ├─────────────────────┤
   /agent default  ─→│  DeepSeek V4 Flash  │ → fails? → DeepSeek direct
                     │      via Go         │
                     ├─────────────────────┤
   /agent deep     ─→│  DeepSeek Reasoner  │ → fails? → Qwen3.6 via Go
                     │      direct         │
                     └─────────────────────┘
                              ↑
                     ┌─────────────────────┐
   any prompt      ─→│  build (orchestr.)  │ → classifies and delegates
                     │  DeepSeek-fast cls. │   via `task` tool
                     └─────────────────────┘
```

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- [OpenCode CLI](https://opencode.ai)
- LiteLLM proxy (`uv tool install 'litellm[proxy]'`)
- [OpenCode Go](https://opencode.ai/auth) account ($10/month)
- (optional) Direct [DeepSeek](https://platform.deepseek.com) API key for fallback
- (optional) ChatGPT OAuth via `opencode auth login`

### Install

```bash
git clone https://github.com/RodrigoSiliunas/opencode-buddy.git
cd opencode-buddy
uv tool install --editable .
opencode-buddy doctor
```

### Quickstart

New project with the wizard:

```bash
opencode-buddy create my-app
```

Existing project with an automatic plan and no LLM call:

```bash
opencode-buddy agent-driven --scan . --offline --dry-run --json
opencode-buddy agent-driven --scan . --target . --offline
```

Scriptable/reproducible setup:

```bash
opencode-buddy init my-app --spec examples/opencode-buddy.spec.yaml
```

### Interactive Create

```bash
opencode-buddy create
```

The wizard asks for a folder and which capabilities the project includes. Capabilities split into two groups:

- **With dedicated agent** (model picker + specialized prompt): Frontend/UI, Backend/API, Audio/speech, Video/multimodal.
- **Context-only** (enrich `.opencode/project.md` without spawning an agent): Mobile, CLI/tooling, Desktop, Data/ETL, ML/AI, DevOps/infra, QA/testing, Documentation, Security, External integrations.

For each selected capability the wizard asks objective sub-questions (framework, runtime, database, auth, etc.) and the answers feed `.opencode/project.md`, which agents treat as the source of truth.

When API keys are available in the environment or a local `.env`, the wizard can query provider model catalogs. If discovery fails or no keys exist yet, it shows local suggestions and marks the missing keys. It also detects ChatGPT OAuth through `opencode auth list` when available.

### Direct Use

```bash
mkdir my-project && cd my-project
opencode-buddy init .
cp .env.example .env
# fill in keys
opencode-buddy validate .
.\start-proxy.ps1            # terminal A — start LiteLLM
opencode                     # terminal B — open OpenCode
```

Inside OpenCode, the `build` agent (default) classifies your prompt and delegates. Force a specific agent with `/agent <name>` before the prompt.

Add custom agents at scaffold time:

```bash
opencode-buddy init . --extra-agent reviewer=litellm/deepseek-pro:"critical code review"
```

This adds the agent to `opencode.json`, creates `.opencode/agents/reviewer.md`, and updates the generated orchestrator prompt so matching requests can be delegated to it.

Validate generated projects with:

```bash
opencode-buddy validate .
opencode-buddy validate . --strict
```

`--strict` turns warnings into exit 1. Note: **`--strict` fails when `.env` is missing** (only `.env.example` present), which is the normal state right after `init`/`create`. Use `--strict` in CI to assert the operator filled in `.env`; skip it during local setup.

### Validate provider keys (`keys validate`)

```bash
opencode-buddy keys validate
opencode-buddy keys validate --provider deepseek
opencode-buddy keys validate --json
opencode-buddy keys validate --strict --timeout 10
```

For each provider in the registry, the command checks the required ENV vars, performs a real model-listing call when supported, and detects OAuth providers via `opencode auth list`. States are `ok`, `missing-env`, `auth-failed`, `network-failed`, `unsupported-discovery`, `skipped`. Default exit 1 on `auth-failed`; `--strict` also fails on `missing-env`/`network-failed`. Key values are never echoed.

### Model registry

Providers and suggested models live in `src/opencode_buddy/model_registry.yaml`. Add a new model by editing the YAML — no Python changes required. `init` flags still work; defaults come from the registry when flags are omitted.

### Agent Driven Mode

```bash
opencode-buddy agent-driven --scan .                          # scan current project
opencode-buddy agent-driven --scan ./apps/web --target ./apps/web --offline
opencode-buddy agent-driven --planner deepseek                # OpenAI-compatible
opencode-buddy agent-driven --planner anthropic               # native adapter
opencode-buddy agent-driven --planner gemini                  # native adapter
opencode-buddy agent-driven --offline                         # 100% deterministic, no LLM call
opencode-buddy agent-driven --scan . --offline --dry-run --json    # automation: clean JSON to stdout
```

The command scans the target folder (or chats to build a new project), feeds a short summary + the **names** of detected env vars to an LLM planner, and prints a plan with capabilities, per-role models, reasoning and risks. The user can **approve**, **discuss/edit** (free text), or **cancel**. Files are only written on approval.

Supported live planners:

| Provider | Transport | Auth |
|---|---|---|
| `deepseek` | OpenAI-compatible (`/chat/completions`) | `DEEPSEEK_API_KEY` |
| `moonshot` | OpenAI-compatible | `MOONSHOT_API_KEY` |
| `opencode-go` | OpenAI-compatible | `OPENCODE_GO_API_KEY` |
| `commandcode` | OpenAI-compatible | `COMMANDCODE_API_KEY` + `COMMANDCODE_API_BASE` |
| `anthropic` | Native adapter `/v1/messages` (`x-api-key` + `anthropic-version`) | `ANTHROPIC_API_KEY` |
| `gemini` | Native adapter `generateContent` (`x-goog-api-key` header) | `GEMINI_API_KEY` |

Auto-pick (`--planner=auto`): OpenAI-compatible first, then Anthropic, then Gemini. No keys → deterministic.

Output modes:

- **default**: interactive review + scaffold on approval.
- **`--dry-run`**: interactive review, prints plan, does **not** write files.
- **`--dry-run --json`**: skips review, prints clean JSON of the plan to stdout (informational messages go to stderr). Built for automation.
- **`--json` alone**: friendly error asking for `--dry-run` (avoids polluting stdout).

Formal schema: `src/opencode_buddy/agent_driven_schema.py` ships a JSON Schema (draft-07) that validates every planner response. The schema is embedded in the LLM prompt and used to reject malformed payloads before they reach `ProjectSpec`. If the LLM emits something off-schema (e.g. an invented role), the orchestrator falls back to the deterministic planner with a visible warning.

Security guarantees:

- The scanner skips `.git`, `node_modules`, `.venv`, `dist`, `build`, caches; it never reads `.env` or `*.key`/`*.pem`/`*credential*` files.
- The payload sent to the LLM contains only **names** of detected env vars, never their values. The actual key flows only through headers (`Authorization`, `x-api-key`, or `x-goog-api-key`). Gemini **never** receives the key via the URL `?key=` query string.
- `--json` never includes `raw_response` (internal debug). Public output goes through `plan_to_jsonable_public(plan, include_raw=False)`.
- With no keys detected, the deterministic planner still produces a **valid** spec from the registry defaults plus a visible risk asking for `.env`.
- Malformed JSON / HTTP errors / schema violations automatically fall back to the deterministic planner with a visible warning to stderr; nothing is written before approval.

Examples in [`examples/`](examples/):

- [`examples/agent-driven-existing-vite/`](examples/agent-driven-existing-vite/) — React+Vite fixture for `--scan`.
- [`examples/agent-driven-new-project/`](examples/agent-driven-new-project/) — reference for `--objective`.
- [`examples/model-registry-extension.yaml`](examples/model-registry-extension.yaml) — how to extend the registry.
- [`examples/opencode-buddy.spec.yaml`](examples/opencode-buddy.spec.yaml) — declarative spec for `init --spec`.

### Declarative spec (`--spec`)

`opencode-buddy init . --spec project-spec.yaml` loads defaults from a YAML or JSON file with `InitOptions` fields. Flags still take precedence. Both `init` and `create` produce a `ProjectSpec` (= `InitOptions`) and feed the same `scaffolder.scaffold_project` engine — only the way the spec is built differs (flags vs. wizard).

A canonical example exercising every supported field (`extra_agents`, `model_specs`, `fallback_rules`, nested `project_context.capabilities` / `role_models` / `conventions` / `constraints` / `risks`) lives at [`examples/opencode-buddy.spec.yaml`](examples/opencode-buddy.spec.yaml).

### Internationalization (i18n)

The CLI ships in pt-BR by default. Switch via `OPENCODE_BUDDY_LANG=en-US` env var. en-US is a progressive stub — untranslated keys fall back to pt-BR. Catalog: `src/opencode_buddy/i18n.py`. Use `opencode_buddy.i18n.missing_in_locale("en-US")` to list missing keys.

### Known limitations

- **Windows + LiteLLM**: the LiteLLM banner contains Unicode that cp1252 rejects. `start-proxy.ps1` sets `PYTHONIOENCODING=utf-8`. Not an issue on Linux/Mac.
- **OpenCode Go catalog may shift**: model IDs are placeholders; verify with `curl -H "Authorization: Bearer $OPENCODE_GO_API_KEY" https://opencode.ai/zen/go/v1/models | jq` and override with `--go-*-model` flags.
- **DeepSeek Reasoner isn't in Go**: the `deep` agent uses DeepSeek API directly with Qwen3.6 from Go as fallback.

### License

[MIT](LICENSE)
