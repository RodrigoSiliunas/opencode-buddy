# Plano de Implementacao do OpenCode Buddy

## Objetivo

Transformar o OpenCode Buddy de um scaffolder com boas opinioes locais em uma camada extensivel para criar projetos OpenCode com:

- descoberta e validacao real de providers/modelos;
- escolha de modelos por trabalho, baseada nas chaves e OAuth disponiveis;
- wizard por capacidades do projeto;
- contexto de projeto rico para os agents;
- scaffold mais seguro e pronto para uso diario.

O foco e utilidade real. O projeto deve continuar simples de instalar, simples de rodar e facil de extender sem alterar codigo Python para cada provider ou modelo novo.

## Fora de escopo

- Perfis salvos de usuario, como `profile save` ou `create --profile`.

Esse ponto fica fora porque ainda nao esta claro qual problema concreto ele resolve melhor do que um arquivo declarativo de projeto/spec.

## Estado atual

O projeto ja possui:

- CLI com `init`, `create`, `validate` e `doctor`;
- wizard interativo com banner, cores, selecao multipla de capacidades e selecao de modelos por papel;
- geracao de `opencode.json`, `litellm-config.yaml`, `.env.example`, `start-proxy.ps1` e prompts em `.opencode/agents`;
- catalogo inicial de modelos em Python;
- deteccao basica de ChatGPT OAuth via `opencode auth list`;
- validacao estrutural do projeto gerado;
- testes cobrindo builder, wizard, validator, doctor e catalogo.

As principais limitacoes atuais:

- providers, custos, modelos recomendados e fallbacks ainda estao concentrados em codigo Python;
- `validate` nao valida se chaves realmente funcionam;
- descoberta OAuth ainda e superficial;
- wizard ainda nao pergunta detalhes suficientes por capacidade;
- projeto gerado ainda nao inclui `.gitignore`;
- `init` e `create` estao virando dois fluxos diferentes;
- documentacao precisa acompanhar melhor o novo desenho.

## Principios de implementacao

- O wizard deve recomendar modelos, nao recomendar o tipo de projeto que a pessoa quer criar.
- Capacidades do projeto devem ser escolhidas por selecao multipla.
- Confirmacoes em PT-BR devem usar `[S/n]` e `[s/N]`.
- O nome do modelo nao deve depender somente de valores hardcoded no codigo.
- Providers e modelos devem ser configuraveis por dados.
- O projeto gerado deve ser seguro por padrao, especialmente quanto a secrets.
- `create` deve ser amigavel para humanos; `init` deve ser scriptavel, mas ambos devem usar o mesmo motor interno.

## Fase 1 - Registry declarativo de providers e modelos

### Objetivo

Mover o conhecimento sobre providers/modelos para um arquivo declarativo versionado.

### Entregas

- Criar um arquivo de registry, por exemplo:
  - `src/opencode_buddy/model_registry.yaml`
- Definir schema inicial com campos como:
  - `provider.key`
  - `provider.name`
  - `provider.transport`
  - `provider.api_key_env`
  - `provider.api_base`
  - `provider.api_base_env`
  - `provider.discovery.kind`
  - `provider.discovery.url`
  - `models[].id`
  - `models[].litellm_model`
  - `models[].cost_label`
  - `models[].recommended_for`
  - `models[].tags`
  - `models[].available_when`
- Refatorar `src/opencode_buddy/model_catalog.py` para carregar o registry.
- Manter funcoes de descoberta live por provider, mas guiadas pelo registry.
- Remover duplicacao entre fallback local e descoberta live.

### Exemplo de schema

```yaml
providers:
  - key: deepseek
    name: DeepSeek
    transport: API
    api_key_env: DEEPSEEK_API_KEY
    discovery:
      kind: openai-compatible
      url: https://api.deepseek.com/models
    models:
      - id: deepseek-chat
        litellm_model: deepseek/deepseek-chat
        cost_label: low
        recommended_for: [build, backend, default]
      - id: deepseek-reasoner
        litellm_model: deepseek/deepseek-reasoner
        cost_label: low-medium
        recommended_for: [deep]
```

### Criterios de aceite

- Adicionar um novo modelo recomendado deve exigir alteracao somente no registry e nos testes.
- `build_model_catalog(live=False)` deve continuar funcionando sem rede.
- `build_model_catalog(live=True)` deve complementar dados locais com modelos descobertos.
- Testes existentes de catalogo devem continuar passando.

## Fase 2 - Validacao real de chaves e descoberta de modelos

### Objetivo

Adicionar uma camada explicita para validar providers antes do `create`.

### Entregas

- Criar comando:

```bash
opencode-buddy keys validate
```

- Opcoes sugeridas:

```bash
opencode-buddy keys validate --cwd .
opencode-buddy keys validate --json
opencode-buddy keys validate --provider deepseek
```

- Validar:
  - variaveis presentes no ambiente;
  - variaveis presentes em `.env`;
  - autenticacao basica por provider;
  - listagem de modelos quando a API permitir;
  - status de OAuth via OpenCode.
- Retornar status por provider:
  - `ok`
  - `missing-env`
  - `auth-failed`
  - `network-failed`
  - `unsupported-discovery`
- Criar estrutura de resultado reutilizavel pelo wizard.

### Saida esperada

```text
Providers
  [OK]   DeepSeek        API     2 modelos encontrados
  [MISS] Anthropic       API     falta ANTHROPIC_API_KEY
  [OK]   ChatGPT OAuth   OAuth   login detectado no OpenCode
  [WARN] CommandCode     API     falta COMMANDCODE_API_BASE
```

### Criterios de aceite

- O comando nao deve vazar valores de chaves.
- Em modo `--json`, deve produzir saida facil de consumir em testes ou scripts.
- Falha de rede nao deve quebrar o wizard quando houver fallback local.
- `create` deve poder reaproveitar a mesma logica de validacao.

## Fase 3 - Melhor descoberta OAuth do OpenCode

### Objetivo

Separar OAuth como transporte de primeira classe, nao como excecao hardcoded.

### Entregas

- Modelar providers OAuth no registry.
- Manter deteccao via `opencode auth list`.
- Investigar comandos disponiveis do OpenCode para listar modelos OAuth reais.
- Caso nao exista listagem real, manter uma tabela declarativa de modelos OAuth conhecidos.
- Exibir modelos OAuth com o mesmo formato dos demais:

```text
Provider - Modelo - Custo estimado - API/OAuth - [recomendado]
```

### Criterios de aceite

- ChatGPT OAuth nao deve aparecer se `opencode auth list` nao detectar login.
- Modelos OAuth nao devem exigir entrada em `.env.example`.
- `validate` deve tratar modelos OAuth separadamente de aliases LiteLLM.

## Fase 4 - Wizard por capacidades com subperguntas

### Objetivo

Fazer o `create` entender melhor o projeto sem voltar para presets rigidos.

### Entregas

- Expandir capacidades iniciais:
  - frontend/UI
  - backend/API
  - audio/speech
  - video/multimodal
  - mobile
  - CLI/tooling
  - desktop
  - data/ETL
  - ML/AI
  - DevOps/infra
  - QA/testes
  - docs
  - security
  - integracoes externas
- Manter selecao multipla sem recomendacao.
- Para cada capacidade selecionada, fazer subperguntas objetivas.

### Exemplos de subperguntas

Frontend:

- framework: React, Vue, Nuxt, Svelte, Solid, outro;
- TypeScript: `[S/n]`;
- CSS: Tailwind, CSS Modules, CSS puro, design system existente;
- app type: dashboard, editor, landing, ferramenta interna, jogo.

Backend:

- runtime: Node, Python, Go, outro;
- API: REST, GraphQL, gRPC, webhooks;
- banco: Postgres, SQLite, MySQL, MongoDB, nenhum;
- auth: OAuth/OIDC, JWT, session, nenhuma.

Audio:

- tarefas: transcricao, traducao, TTS, diarizacao, captura em tempo real;
- entrada: microfone, arquivo, streaming;
- idioma principal.

Video:

- tarefas: frames, legendas, analise visual, multimodal;
- entrada: arquivo, camera, streaming.

### Criterios de aceite

- O wizard nao deve ficar cansativo para projetos simples.
- Cada subpergunta deve alimentar `.opencode/project.md`.
- Capacidades selecionadas devem gerar agents somente quando fizer sentido.
- Modelos recomendados devem ser calculados a partir dos papeis/capacidades.

## Fase 5 - Contexto de projeto mais rico

### Objetivo

Transformar `.opencode/project.md` na fonte principal de contexto para os agents.

### Entregas

- Melhorar `ProjectContext` em `src/opencode_buddy/config_builder.py`.
- Incluir secoes como:
  - visao geral;
  - capacidades selecionadas;
  - stack tecnica;
  - comandos conhecidos;
  - providers/modelos escolhidos;
  - restricoes;
  - convencoes de codigo;
  - decisoes de arquitetura;
  - riscos e pontos de atencao.
- Fazer os prompts dos agents referenciarem esse contexto de forma mais forte.

### Exemplo de saida

```md
# Contexto do projeto

## Capacidades

- Frontend/UI: React, TypeScript, Tailwind
- Backend/API: Node, REST, Postgres
- Audio/Speech: transcricao e traducao

## Modelos

- build: OpenCode Go - deepseek-v4-flash
- frontend: Moonshot/Kimi - kimi-k2
- backend: ChatGPT OAuth - gpt-5.5
- deep: DeepSeek - deepseek-reasoner

## Convencoes

- Priorizar alteracoes pequenas e testaveis.
- Nunca incluir secrets no repositorio.
- Preferir bibliotecas maduras para parsing, audio, video e auth.
```

### Criterios de aceite

- O arquivo deve ser util para humanos e agents.
- O conteudo deve refletir escolhas reais do wizard.
- Projetos criados sem capacidades extras ainda devem ter contexto limpo.

## Fase 6 - Scaffold mais seguro

### Objetivo

Reduzir risco operacional no projeto gerado.

### Entregas

- Gerar `.gitignore` no projeto criado.
- Incluir por padrao:

```gitignore
.env
.env.*
!.env.example
*.log
.litellm/
__pycache__/
.pytest_cache/
node_modules/
dist/
build/
```

- Validar no `validate`:
  - `.env` ignorado quando `.gitignore` existir;
  - `.env.example` presente;
  - `LITELLM_MASTER_KEY` declarado;
  - prompts referenciados existem;
  - aliases LiteLLM resolvem.
- Opcional: gerar `README.md` minimo dentro do projeto criado com proximos passos.

### Criterios de aceite

- Projeto novo nao deve induzir commit acidental de secrets.
- `validate --strict` deve avisar se `.gitignore` nao protege `.env`.

## Fase 7 - Unificar `init` e `create`

### Objetivo

Evitar dois motores de geracao divergentes.

### Entregas

- Criar uma estrutura intermediaria unica, por exemplo `ProjectSpec`.
- Fazer `create` produzir `ProjectSpec`.
- Fazer `init` produzir `ProjectSpec` a partir de flags.
- Fazer `_scaffold_project` receber somente essa estrutura final.
- Opcional: permitir arquivo declarativo:

```bash
opencode-buddy init . --spec opencode-buddy.yaml
```

Esse `--spec` substitui parcialmente a ideia de perfil salvo, mas com semantica melhor: e uma especificacao do projeto, nao uma preferencia global escondida.

### Criterios de aceite

- Toda capacidade suportada pelo wizard deve ser representavel em estrutura interna.
- `init` nao deve depender de perguntas interativas.
- Testes devem cobrir `create -> spec -> scaffold` e `init flags -> spec -> scaffold`.

## Fase 8 - UX de terminal e localizacao

### Objetivo

Consolidar a experiencia PT-BR atual e preparar EN-US futuro sem espalhar strings pelo codigo.

### Entregas

- Criar modulo simples de mensagens, por exemplo:
  - `src/opencode_buddy/i18n.py`
- Comecar com `pt-BR`.
- Preparar chaves para `en-US`.
- Padronizar:
  - `[S/n]`
  - `[s/N]`
  - `[recomendado]`
  - `[falta ENV]`
  - `[live]`
- Garantir cores consistentes:
  - pergunta/titulo: cyan;
  - numero de opcao: amarelo;
  - recomendado/ok: verde;
  - warning: amarelo;
  - erro/falta chave: vermelho;
  - transporte API/OAuth: cyan/verde.

### Criterios de aceite

- Strings principais do wizard nao devem ficar soltas em multiplos arquivos.
- O wizard deve continuar legivel sem suporte a cor.
- Testes devem validar prompts criticos sem depender de cor ANSI.

## Fase 9 - Documentacao e encoding

### Objetivo

Deixar README e docs alinhados com o produto real.

### Entregas

- Revisar README em UTF-8.
- Corrigir qualquer texto com encoding quebrado.
- Documentar:
  - fluxo recomendado;
  - `keys validate`;
  - registry de modelos;
  - providers suportados;
  - capacidades do wizard;
  - scaffold gerado;
  - como adicionar provider/modelo;
  - como rodar testes.
- Adicionar exemplos de:
  - projeto simples;
  - projeto frontend + backend;
  - projeto audio + backend;
  - projeto com ChatGPT OAuth.

### Criterios de aceite

- README deve refletir comandos reais.
- Nenhum exemplo deve depender de modelo inexistente sem aviso.
- Documentacao deve explicar claramente a diferenca entre API e OAuth.

## Ordem recomendada

1. Registry declarativo de modelos.
2. `keys validate`.
3. OAuth como transporte de primeira classe.
4. Wizard com subperguntas por capacidade.
5. `.opencode/project.md` mais rico.
6. `.gitignore` e seguranca do scaffold.
7. Unificacao interna de `init` e `create`.
8. UX/i18n.
9. README e docs.

Essa ordem reduz risco porque primeiro estabiliza o modelo de dados. Depois o wizard passa a ser uma interface sobre esse modelo, em vez de concentrar regra de negocio.

## Plano de testes

- Unit tests para carregar registry.
- Unit tests para ranking de modelos por papel.
- Unit tests para validacao de chaves com mocks de HTTP.
- Unit tests para deteccao OAuth com mock de `subprocess.run`.
- Unit tests para geracao de `.gitignore`.
- Unit tests para `.opencode/project.md`.
- Smoke test do `create` com entrada simulada.
- Smoke test do `validate` sobre projeto gerado.
- Smoke test de `keys validate --json`.

## Riscos

- APIs de providers mudam formatos de listagem de modelos.
- OpenCode pode nao expor modelos OAuth de forma consultavel.
- Wizard pode ficar longo demais se todas as capacidades abrirem muitas perguntas.
- Custos estimados podem ficar desatualizados.
- Registry grande demais pode virar manutencao manual pesada.

## Mitigacoes

- Manter fallback local mesmo quando live discovery falhar.
- Tratar custo como `cost_label`, nao como preco exato.
- Fazer subperguntas somente para capacidades selecionadas.
- Permitir respostas default sensatas, mas sem recomendar capacidades.
- Separar dados de providers do codigo de UI.

## Definicao de pronto

O plano pode ser considerado implementado quando:

- `opencode-buddy keys validate` existe e valida providers sem vazar secrets;
- modelos exibidos no `create` vem do registry + descoberta live quando possivel;
- OAuth aparece como transporte proprio;
- wizard cria agents e contexto com base nas capacidades e subrespostas;
- projeto gerado inclui protecao contra commit de `.env`;
- `init` e `create` compartilham o mesmo motor de geracao;
- README explica como extender providers/modelos;
- testes passam em ambiente limpo.
