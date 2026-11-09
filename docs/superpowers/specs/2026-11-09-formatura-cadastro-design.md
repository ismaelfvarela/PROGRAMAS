# Formatura: clipes funcionando (etapas 2.1 + 2.2), design

Data: 2026-11-09. Esta etapa vem depois da plataforma
(`docs/superpowers/specs/2026-11-09-areas-de-trabalho-design.md`, merge `bfca6f4`). As decisões
e o histórico estão em `docs/formaturas/briefing.md`.

A 2.1 (cadastro e preparação) e a 2.2 (roteiro dos clipes) entram juntas. Sem o Iniciar, a 2.1
sozinha não grava nada. O usuário autorizou: "faça o que for preciso para deixar as formaturas
funcionando sem interferir no casamento".

## Objetivo

Na área Formatura, o editor:

1. cadastra a formatura: escola, logo, ano e semestre, cursos com suas turmas e pasta de
   grafismos;
2. prepara um **clipe** (Oficina, Feira, Prova de toga ou Escolha do paraninfo) ligado a uma
   formatura e a uma turma, com as funções de pasta da Formatura;
3. clica em **Iniciar** e recebe o mesmo que no Casamento: análise, pré-roteiro do clipe, PDF e
   XML e painel do Premiere;
4. duplica uma oficina para outra turma, mantendo a ideia e trocando a música;
5. prepara a **colação** (formatura, local, cidade e turmas). O processamento da colação é a
   etapa 2.3, e até lá o Iniciar dela fica desligado com um aviso.

## Regras

- **O Casamento não se mexe.** O comportamento, os prompts e os arquivos dele ficam idênticos.
  Os testes do Casamento não são editados.
- O código novo fica em `src/roteiro_ia/areas/formatura/`.
- Mudanças em código comum só como **acréscimo com valor padrão** que reproduz o Casamento
  exatamente (seção "Ganchos").
- **Testes provisórios da plataforma.** Três testes de `tests/ui/test_areas.py` descrevem a
  Formatura "ainda sem processar" e são **substituídos** pelos testes do comportamento novo:
  - `test_areas_registradas_em_ordem`, que verifica `not pode_iniciar`;
  - `test_formatura_nao_inicia`;
  - `test_formatura_numera_gemini_como_5`, se a numeração mudar.

  É a única edição em teste existente, e nenhum deles é do Casamento.
- Nomes de evento sempre `AAAA-MM-DD NOME`.

## Interface

A janela da plataforma tem as abas fixas Projeto, Trilhas, Estilo e Configurações, garantidas
por `test_trilhas_e_config_sao_uma_so_instancia`, e a fila roda **um projeto por vez** em todas
as áreas. Por isso a Formatura **não ganha abas novas**. Tudo acontece dentro da aba Projeto:

- Card **"Trabalho"**, logo abaixo da pasta do evento:
  - seletor em segmentos: **Clipes | Colação**;
  - Clipes: tipo (Oficina, Feira, Prova de toga, Escolha do paraninfo), **formatura** (lista
    do cadastro, com os botões **Formaturas…** e **+ Nova**), curso e turma (listas tiradas da
    ficha) e **duração alvo** em minutos;
  - botão **"Duplicar de uma oficina…"**;
  - Colação: formatura, local, cidade e as turmas da noite (caixas de marcar, na ordem da
    ficha).
- **Formaturas…** abre o `DialogoCadastro`: a lista das fichas, com Nova, Editar e Duplicar.
  Editar abre o `DialogoFormatura`, com instituição, logo, ano, semestre, uma tabela de cursos
  e turmas, e pasta de grafismos.
- A tabela "O que é cada pasta" passa a usar as **funções da Formatura** e lista dois níveis
  quando a pasta tem dias.
- O card Entregas, que é do Casamento, continua escondido.

## Componentes (`src/roteiro_ia/areas/formatura/`)

### `cadastro.py`

```python
class Curso(BaseModel):
    nome: str
    turmas: list[str]

class Formatura(BaseModel):
    id: str = ""                  # gerado ao salvar: slug(instituição)-AAAA-S-xxxx
    instituicao: str
    logo_escola: str | None = None
    ano: int
    semestre: Literal[1, 2]
    cursos: list[Curso]
    pasta_grafismos: str | None = None
```

- **Arquivo:** `<system_dir>\FORMATURAS\<id>.json`, gravado com `safe_write_text`.
- `listar(s)`: ordem por ano e semestre, do mais novo ao mais antigo, depois instituição. Um
  arquivo ilegível é pulado.
- `carregar(s, id)` devolve `None` se o arquivo não existir ou não puder ser lido.
- `salvar(s, f)` gera o id se faltar e valida antes de gravar. `ValueError` com mensagem em
  português quando:
  - a instituição está vazia;
  - não há curso;
  - um curso está sem turma;
  - há turma repetida no mesmo curso.
- `avisos(f)`: logo ou grafismos que não existem. Não bloqueia a gravação.
- `duplicar(f)`: id vazio e o semestre seguinte (2026/2 → 2027/1).
- `nome_exibicao(f)`: por exemplo "ESCOLA X — 2026/2".

### `tipos.py`

| Tipo | Grupo | Turma | Duração padrão |
|---|---|---|---|
| `oficina` | clipe | obrigatória | 4 min (3 a 5; o editor pode passar disso) |
| `feira` | clipe | sem turma; curso opcional (vazio = escola inteira) | 8 min |
| `prova_toga` | clipe | opcional | 3 min |
| `paraninfo` | clipe | opcional | 3 min |
| `colacao` | colação | pelo menos uma turma da noite | — |

### `funcoes.py`

| Função | Grupo | `Role` comum |
|---|---|---|
| Câmera | clipe | `camera` |
| Câmera ISO | colação | `camera` |
| Câmera com áudio principal | colação | `camera` |
| Mesa de corte (programa) | colação | `mesa` |
| Gravador / lapela | ambos | `audio_ambiente` |
| Imagens extras / frias | ambos | `drone` |
| Drone | ambos | `drone` |
| Ignorar | ambos | `ignorar` |

**Sugestão pelo nome da pasta.** Considera a última parte de `DIA\PASTA`, sem diferença entre
maiúsculas e minúsculas, e procura palavras inteiras:

- `PGM`, `CORTE`, `ATEM` → Mesa de corte.
- `H1`, `H4`, `H5`, `H6`, `ZOOM`, `LAPELA`, `MIC`, `GRAVADOR` → Gravador.
- `FRIAS`, `DECORAÇÃO`, `DECORACAO`, `BASTIDORES`, `AMBIENTE`, `EXTRAS` → Imagens extras.
- `DRONE` → Drone.
- `PROXIES`, `ADOBE PREMIERE PRO…` → Ignorar.
- O resto → Câmera (clipe) ou Câmera ISO (colação).

**Pastas com dias:** `listar_pastas(source) -> list[tuple[str, str]]` devolve pares (pasta
relativa, dia).

- Uma subpasta direta é um **dia** quando tem subpastas e nenhum arquivo de mídia solto. Nesse
  caso entram as subpastas dela, como `DIA\CAM A`, com dia = nome da pasta do dia.
- As outras subpastas entram com dia `"principal"`.

O inventário comum já aceita caminhos relativos em `FolderAssignment.folder`.

### `projeto.py`

```python
class ProjetoFormatura(BaseModel):
    tipo: TipoTrabalho
    formatura_id: str
    curso: str | None = None
    turma: str | None = None
    duracao_min: float | None = None
    funcoes: dict[str, FuncaoFormatura] = {}
    canais_mesa: Literal["misturado", "L_mesa_R_ambiente"] = "misturado"
    duplicado_de: str | None = None
    seguir_ideia: bool = True
    musica: str | None = None          # trilha da biblioteca usada (gravada após o roteiro)
    local: str | None = None
    cidade: str | None = None
    turmas_colacao: list[tuple[str, str]] = []
```

- **Arquivo:** `ANALISE\formatura.json`, ao lado do `projeto.json`. Funções `salvar_projeto`,
  `carregar_projeto(analysis_dir)` e `caminho(analysis_dir)`.
- **`RequestFormatura(ProjectRequest)`** (dataclass) leva o `ProjetoFormatura` em memória do
  formulário até o pipeline. O `projeto.json` é o mesmo do comum.
- `musicas_usadas(s, formatura_id, exceto)`: as `musica` de outros projetos da mesma formatura,
  achados por `recentes.listar(s, discos, area="formatura")`.

### `momentos.py`

- `MOMENTOS_FORMATURA` fica como está.
- `MOMENTOS_POR_TIPO` traz as listas aprovadas (seção 3 do briefing), cada uma terminando em
  "extra".
- `PROBLEMAS_TECNICOS = ["chicote", "desfocado", "mal enquadrado", "tremido", "escuro"]`.

### `estilo.py`: prompts de estilo da Formatura

- **Reaproveita os modelos comuns.** `VideoStyleNotes` e `StyleProfile` servem bem:
  "episódio" = clipe, "gancho" = fechamento, "teaser/trailer" = estrutura por tipo. Assim a
  análise e o roteiro usam o perfil sem conversão.
- **Prompts próprios** de vídeo e de agregado, para vídeos de formatura da Fokuss: clipe de
  oficina, feira, prova de toga, escolha do paraninfo, abertura ou encerramento da colação, e
  íntegra. São registrados no `gemini/style.py` por `registrar_area("formatura", PROMPT_VIDEO,
  PROMPT_AGG)`.
- **Cache próprio** em `estilo_cache\formatura\`.

### `analise.py`: textos da análise

`TEXTOS_POR_TIPO: dict[TipoTrabalho, TextosAnalise]`:

- papel: "Você é um assistente de edição de vídeos de formatura da produtora Fokuss. Este
  material é de um clipe de <tipo>.";
- evento: "da mesma formatura";
- momentos do tipo;
- linha de problemas: "falhas técnicas (chicote, desfocado, mal enquadrado, tremido, escuro,
  áudio ruim)".

### `roteiro.py`: contexto do roteiro do clipe

`contexto_clipe(pf, ficha, ideia_json, excluir) -> Callable` devolve a função de contexto que
`generate_roteiro` usa no lugar do texto do Casamento. As regras:

1. **Uma peça só:** `tipo "episodio"`, `numero 1`, `gancho null`. O título é "<Tipo> —
   <Curso> <Turma>".
2. **Duração** perto de `duracao_min` minutos.
3. **Abertura:** os primeiros segundos ficam reservados para a cartela com instituição,
   curso, turma, semestre e ano. Os dados vêm no prompt. O roteiro indica a cena de fundo.
4. **Qualidade:** nada de chicote, desfocado ou mal enquadrado. O assunto vale mais que a
   técnica: se um momento importante só existe numa imagem imperfeita, ele entra, pelo menor
   tempo possível, com alerta.
5. **Música comercial, popular e moderna** (público jovem):
   - 2 a 3 opções da biblioteca, só da pasta de músicas do projeto;
   - sugestões pelo nome com `origem "popular"`, avisando que podem não ser as da semana;
   - cortes no ritmo da trilha.
6. **Por tipo:**
   - Oficina: trabalho na oficina, mais depoimentos.
   - Feira: documental, guiada pelas falas dos alunos explicando os projetos.
   - Prova de toga e Paraninfo: trilha e só os áudios de assuntos importantes.
7. **Duplicado com `seguir_ideia`:** o roteiro aprovado da original entra como "IDEIA DA
   ORIGINAL". O clipe mantém os assuntos e a ordem dos blocos, mas usa **outra música**, e o
   ritmo e as cenas seguem a trilha nova.

As trilhas em `excluir` (`musicas_usadas`) saem da lista enviada ao Gemini.

### `pipeline.py`

`PipelineFormatura(Pipeline)` reaproveita todas as etapas e muda só estas:

- `prepare` e `run` gravam também o `formatura.json`.
- `_st_estilo` e `_perfil` continuam os do comum. O `area="formatura"` faz o `style.py` usar os
  prompts e o cache registrados.
- `_st_analise` chama `analyze_event(..., textos=TEXTOS_POR_TIPO[tipo])`.
- `_st_roteiro`:
  - usa o índice filtrado pela pasta de músicas e sem as músicas usadas;
  - chama `generate_roteiro(..., n_episodios=1, derivados=set(), contexto=contexto_clipe(...))`;
  - depois grava `musica` no `formatura.json`.
- Tipo `colacao`: `PipelineError("A colação chega na próxima etapa (2.3).")` antes de qualquer
  etapa. Na prática o formulário já impede o Iniciar.

## Ganchos no código comum (acréscimos com padrão)

| Arquivo | Acréscimo | Padrão = Casamento |
|---|---|---|
| `areas/base.py` | `Area.pipeline: Callable \| None = None` (fábrica `(req, s, eventos, settings_path) -> Pipeline`) | `None` = `Pipeline` |
| `ui/projeto.py` | `_pipeline_padrao` usa `area.pipeline` quando existe; `abrir_existente` deixa o formulário completar o pedido (`form.load_request` recebe o `req` lido, e o formulário da Formatura lê o `formatura.json`) | igual |
| `gemini/analysis.py` | `TextosAnalise` (papel, evento, momentos, problemas) e o parâmetro `textos` em `build_prompt`, `build_pack_prompt` e `analyze_event` | `TEXTOS_CASAMENTO`, com os textos atuais idênticos |
| `script/generate.py` | parâmetro `contexto: Callable[..., str] \| None` em `generate_roteiro` | `_context` |
| `gemini/style.py` | `registrar_area(area, prompt_video, prompt_agg)`; cache em `estilo_cache\<area>\` para área registrada; `video_em_cache(s, url, area="casamento")` | Casamento: prompts e cache de hoje |
| `ui/abas.py` | `EstiloTab._icones` passa `**self._kw_area()` a `video_em_cache` | igual no Casamento |

`FORMATURA` passa a ter `pode_iniciar=True` e `pipeline=PipelineFormatura`. O formulário
desliga o Iniciar quando falta algo, ou na colação, e mostra o motivo em `lbl_aviso`.

## Erros e casos de borda

- **Ficha não encontrada ao abrir um projeto:** aviso "Formatura não encontrada. Escolha
  outra." Iniciar fica desligado até escolher outra.
- **Turma que saiu da ficha:** continua no projeto, com o aviso "turma não está mais na ficha".
- **Oficina sem turma, clipe sem formatura ou colação sem turma:** Iniciar desligado, com o
  que falta em `lbl_aviso`.
- **Duplicar com a mesma pasta da original:** recusado com a mensagem "Escolha a pasta da nova
  turma."
- **Nenhuma oficina para duplicar:** mensagem "Ainda não há oficina preparada para duplicar."
- **Pasta de músicas vazia, ou todas as músicas já usadas:** o roteiro segue só com sugestões
  pelo nome, e entra um alerta no roteiro.
- **Logo ou grafismos sumiram:** aviso, sem bloquear.

## Testes

- Todos os testes atuais passam, menos os provisórios citados nas Regras, que são substituídos.
- Novos testes, em `tests/areas/formatura/`:
  - cadastro;
  - tipos;
  - sugestão de função e listagem com dias;
  - `formatura.json` e `musicas_usadas`;
  - textos da análise: o prompt da Formatura cita formatura e os momentos do tipo, e o do
    Casamento fica idêntico;
  - contexto do roteiro: uma peça, duração, cartela, qualidade, música comercial, ideia da
    original, trilhas excluídas;
  - pipeline: grava `formatura.json`, usa os textos e o contexto, grava `musica`, recusa a
    colação;
  - formulário: tipo e turma ligam o Iniciar, a colação mostra o aviso, o pedido leva o
    `ProjetoFormatura`, o projeto reaberto preenche tudo, o duplicar copia e recusa a mesma
    pasta;
  - diálogos do cadastro;
  - estilo: cache separado e prompts da Formatura.
- **Por último:** abrir o programa, criar uma ficha, preparar uma oficina de dois dias e rodar
  com um material curto de teste até o PDF e o XML.

## Fora desta etapa

- Íntegra da colação (2.3), abertura e encerramento (2.4), cartela visual (2.5) e várias
  máquinas (etapa 3).
- O campo "Logo da produtora" entra na 2.4, que é quem usa.
