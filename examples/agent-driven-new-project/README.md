# Agent Driven Mode — projeto novo

Quando ainda não há código, o Agent Driven Mode roda em modo "novo projeto":
sem `--scan`, conversa por `--objective` (ou prompt interativo) e gera o
plano a partir do objetivo + providers detectados.

## Uso

Direto via CLI com objetivo:

```bash
opencode-buddy agent-driven \
  --target ./my-fastapi-rag \
  --objective "API FastAPI servindo um pipeline de RAG sobre PDFs, com Postgres + Pgvector e Playwright para e2e da admin UI." \
  --offline \
  --force
```

JSON para automação (sem review interativo):

```bash
opencode-buddy agent-driven \
  --target ./my-fastapi-rag \
  --objective "API FastAPI com pipeline de RAG..." \
  --offline \
  --dry-run \
  --json | jq
```

Sem `--objective`, o comando vai perguntar pelo objetivo no terminal (a menos
que `--dry-run --json` esteja ativo, caso em que o objetivo vira string vazia
e o planner determinístico gera um spec genérico baseado nas chaves detectadas).

## Boas práticas para o `--objective`

- 1-3 frases.
- Mencione a stack principal (FastAPI, Next.js, Rust, etc).
- Mencione capacidades multimodais quando aplicáveis (audio/transcricao/video/vision).
- Liste constraints relevantes ("offline-first", "edge", "Postgres only").
- NÃO inclua valores de chave/segredos. O texto vai literalmente para o LLM.

## Saída

O plano gerado terá:
- `decisions`: capacidades inferidas a partir do objetivo + providers disponíveis.
- `model_choices`: papéis `build`/`default`/`deep` sempre presentes; outros conforme capacidades.
- `risks`: avisos sobre chaves faltando, capacidades não-cobertas, etc.

Ao aprovar, `scaffold_project` é chamado e o projeto novo aparece em `--target`.
