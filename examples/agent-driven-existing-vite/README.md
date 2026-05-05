# Agent Driven Mode — projeto existente (React + Vite)

Fixture mínima para o Agent Driven Mode reconhecer um projeto frontend
React/Vite/TypeScript. Não é um app rodável — apenas estrutura suficiente
para o `project_scanner` extrair os signals corretos.

## Uso

Modo automação (sem review interativo, sem escrever arquivos, JSON parseável em stdout):

```bash
opencode-buddy agent-driven \
  --scan examples/agent-driven-existing-vite \
  --offline \
  --dry-run \
  --json
```

Modo review interativo + dry-run (não escreve arquivos):

```bash
opencode-buddy agent-driven \
  --scan examples/agent-driven-existing-vite \
  --target ./out \
  --offline \
  --dry-run
```

Modo real (com aprovação manual + scaffold):

```bash
opencode-buddy agent-driven \
  --scan examples/agent-driven-existing-vite \
  --target ./my-app \
  --offline \
  --force
```

## O que esperar

Detecção:
- `framework: react+vite`
- `bundler: vite`
- linguagens: `javascript`, `typescript`
- libs JS: `react`, `vite` (e companheiros)

Plano determinístico tipico:
- Capacidade habilitada: `Frontend/UI` (com `framework=React`, `typescript=Sim`).
- Modelos por papel via registry; sem chaves detectadas, sai um risco pedindo `.env`.
