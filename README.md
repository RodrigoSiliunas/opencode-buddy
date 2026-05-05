# opencode-buddy

[![tests](https://github.com/RodrigoSiliunas/opencode-buddy/actions/workflows/test.yml/badge.svg)](https://github.com/RodrigoSiliunas/opencode-buddy/actions/workflows/test.yml)
[![license](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org)

Scaffolder de projetos [OpenCode](https://opencode.ai) com proxy [LiteLLM](https://docs.litellm.ai) e roteamento inteligente entre **OpenCode Go**, **DeepSeek** direto e **ChatGPT OAuth**.

> **EN:** Project scaffolder for [OpenCode](https://opencode.ai) with [LiteLLM](https://docs.litellm.ai) proxy and smart routing across **OpenCode Go**, direct **DeepSeek**, and **ChatGPT OAuth**. Generates `opencode.json`, `litellm-config.yaml`, `.env.example`, helper PowerShell script, and 5 specialist agent prompts in one command.

[Português](#português) · [English](#english)

---

## Português

### O que faz

`opencode-buddy init <pasta>` gera num projeto OpenCode pronto pra rodar:

- `opencode.json` com 5 subagents pinados em modelos diferentes + agent orquestrador que delega automaticamente
- `litellm-config.yaml` com 5 entries e regras de **fallback**: se OpenCode Go falhar, cai pra DeepSeek direto; se DeepSeek-reasoner falhar, cai pra Qwen via Go
- `.env.example` com as 3 chaves necessárias (master key local + Go + DeepSeek)
- `start-proxy.ps1` — helper Windows que carrega o `.env`, força UTF-8 (workaround pra bug do banner LiteLLM em cp1252) e sobe o proxy
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

### Uso

```bash
mkdir meu-projeto && cd meu-projeto
opencode-buddy init .
cp .env.example .env
# editar .env com chaves reais
.\start-proxy.ps1            # terminal A — sobe LiteLLM
opencode                     # terminal B — abre OpenCode
```

Dentro do OpenCode, agent `build` (default) classifica seu pedido e delega:

- "crie um botão React com hover" → `@frontend` (Kimi K2.6)
- "crie endpoint POST /upload com auth" → `@backend` (GPT-5.5 via OAuth)
- "explica esse arquivo" → `@default` (DeepSeek V4 Flash)
- "qual arquitetura de fila pra job assíncrono" → `@deep` (DeepSeek Reasoner)

Pra forçar um agent específico: `/agent frontend` antes do prompt.

### Flags do init

```
opencode-buddy init <pasta>
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
  --force                               # sobrescreve arquivos existentes
```

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

`opencode-buddy init <folder>` scaffolds a ready-to-run OpenCode project:

- `opencode.json` with 5 subagents pinned to different models + an orchestrator agent that auto-delegates
- `litellm-config.yaml` with 5 entries and **fallback** rules: if OpenCode Go fails, fall back to direct DeepSeek; if DeepSeek-reasoner fails, fall back to Qwen via Go
- `.env.example` with the 3 required keys (local master key + Go + DeepSeek)
- `start-proxy.ps1` — Windows helper that loads `.env`, forces UTF-8 (workaround for LiteLLM banner cp1252 bug), and starts the proxy
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

### Use

```bash
mkdir my-project && cd my-project
opencode-buddy init .
cp .env.example .env
# fill in keys
.\start-proxy.ps1            # terminal A — start LiteLLM
opencode                     # terminal B — open OpenCode
```

Inside OpenCode, the `build` agent (default) classifies your prompt and delegates. Force a specific agent with `/agent <name>` before the prompt.

### Known limitations

- **Windows + LiteLLM**: the LiteLLM banner contains Unicode that cp1252 rejects. `start-proxy.ps1` sets `PYTHONIOENCODING=utf-8`. Not an issue on Linux/Mac.
- **OpenCode Go catalog may shift**: model IDs are placeholders; verify with `curl -H "Authorization: Bearer $OPENCODE_GO_API_KEY" https://opencode.ai/zen/go/v1/models | jq` and override with `--go-*-model` flags.
- **DeepSeek Reasoner isn't in Go**: the `deep` agent uses DeepSeek API directly with Qwen3.6 from Go as fallback.

### License

[MIT](LICENSE)
