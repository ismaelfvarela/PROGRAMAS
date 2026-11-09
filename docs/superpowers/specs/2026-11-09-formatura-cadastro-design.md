# Formatura 2.1: cadastro, sub-abas, funções das pastas, momentos e estilo (design)

Data: 2026-11-09. Etapa 2.1 da área Formatura. Ela vem depois da parte 1, as áreas de trabalho
(`docs/superpowers/specs/2026-11-09-areas-de-trabalho-design.md`, merge `bfca6f4`). As decisões
e o histórico das perguntas estão em `docs/formaturas/briefing.md`.

## Objetivo

Ao fim da 2.1, o editor consegue:

- cadastrar uma formatura (escola, ano e semestre, cursos com suas turmas, logo e grafismos);
- preparar projetos de clipe (Oficina, Feira, Prova de toga, Escolha do paraninfo) e de
  colação, ligados a essa formatura, com as funções de pasta da Formatura;
- duplicar uma oficina já preparada para outra turma;
- estudar o estilo de formatura a partir de vídeos de referência, com um prompt próprio.

O **Iniciar continua desligado** (`FORMATURA.pode_iniciar = False`). Ele liga na 2.2, junto com
o roteiro dos clipes.

## Regras herdadas da plataforma

- **O Casamento não se mexe.** Nenhum teste existente é editado. Todo código novo fica em
  `src/roteiro_ia/areas/formatura/`.
- Se uma etapa comum tiver algo de casamento por dentro, a Formatura faz a própria versão
  nessa pasta.
- Mudanças em código comum só quando não há outro jeito. Elas devem ser **acréscimos com valor
  padrão** que deixam o Casamento exatamente como está. As mudanças desse tipo estão
  listadas na seção "Ganchos na plataforma".
- Nomes de evento sempre `AAAA-MM-DD NOME`.

## Visão geral

```
Área FORMATURA
 ├─ Clipes      → projetos de Oficina, Feira, Prova de toga e Escolha do paraninfo
 ├─ Colação     → projeto da cerimônia (chega por último)
 ├─ Formaturas  → cadastro (a ficha), usado pelos clipes e pela colação
 ├─ Estilo      → links de formatura (estudo de estilo próprio da Formatura)
 ├─ Trilhas     → comum
 └─ Configurações → comum (+ "Logo da produtora")
```

Uma oficina pode ser gravada até um ano antes da colação. Por isso o cadastro fica **fora dos
projetos**, e cada projeto guarda só a referência a ele.

## Componentes (`src/roteiro_ia/areas/formatura/`)

### `cadastro.py`: a ficha da formatura

```python
class Curso(BaseModel):
    nome: str                 # "Curso Técnico em Eletrônica"
    turmas: list[str]         # ["Manhã", "Tarde", "T106", "T107"], texto livre

class Formatura(BaseModel):
    id: str                   # gerado: slug(instituição)-AAAA-S-xxxx (4 caracteres aleatórios)
    instituicao: str
    logo_escola: str | None   # caminho do arquivo; opcional
    ano: int
    semestre: Literal[1, 2]
    cursos: list[Curso]
    pasta_grafismos: str | None  # vinhetas e logos da escola; opcional
```

- Gravada em `<system_dir>\FORMATURAS\<id>.json`, com `safe_write_text`.
- Funções: `listar(s) -> list[Formatura]` (ordem: ano e semestre, do mais novo ao mais antigo,
  depois instituição), `carregar(s, id) -> Formatura | None`, `salvar(s, f)`,
  `duplicar(f) -> Formatura` e `nome_exibicao(f)`.
  - `duplicar` cria um id novo e sugere o semestre seguinte (2026/2 → 2027/1).
  - `nome_exibicao` devolve, por exemplo, "ESCOLA X — 2026/2".
- **Validação ao salvar:** instituição não vazia, pelo menos um curso, cada curso com pelo menos
  uma turma, sem turma repetida no mesmo curso. Logo e grafismos são opcionais. Se o caminho
  informado não existir, aparece um aviso, mas a gravação não é bloqueada.
- Os arquivos de logo e grafismos **nunca são escritos**, só lidos.

### `tipos.py`: tipos de trabalho

| Tipo | Sub-aba | Pertence a |
|---|---|---|
| `oficina` | Clipes | **uma turma** (obrigatória) |
| `feira` | Clipes | um curso, ou a escola inteira (curso opcional) |
| `prova_toga` | Clipes | uma turma, ou a formatura inteira (turma opcional) |
| `paraninfo` | Clipes | uma turma, ou a formatura inteira (turma opcional) |
| `colacao` | Colação | a lista de turmas que se formam naquela noite (pelo menos uma) |

Cada tipo tem um nome para exibir e a lista de momentos (ver `momentos.py`).

### `funcoes.py`: funções das pastas

A Formatura tem **as próprias funções**. Cada uma é traduzida para um `Role` comum, para que as
etapas comuns (inventário, sincronização, transcrição, Premiere) funcionem sem mudança:

| Função da Formatura | Sub-aba | `Role` comum | Observação |
|---|---|---|---|
| Câmera | Clipes | `camera` | áudio embutido (microfone direcional) é a fonte dos depoimentos |
| Câmera ISO | Colação | `camera` | reserva para a íntegra (2.3) |
| Câmera com áudio principal | Colação | `camera` | cópia de segurança do áudio |
| Mesa de corte (programa) | Colação | `mesa` | linha principal da íntegra; prioridade máxima na sincronização e na transcrição |
| Gravador / lapela | ambas | `audio_ambiente` | H1, H4, MIC LAPELA, microfone do mestre de cerimônias; melhor fonte que a câmera |
| Imagens extras / frias | ambas | `drone` | só imagem; na colação, alimenta o banco de imagens frias (2.3) |
| Drone | ambas | `drone` | |
| Ignorar | ambas | `ignorar` | |

**Sugestão pelo nome da pasta** (sem diferença entre maiúsculas e minúsculas, olhando palavras
inteiras):

- `PGM`, `CORTE`, `ATEM` → Mesa de corte.
- `CAM A`…`CAM Z`, `CAM 1`… e `CAMERA` → Câmera (nos Clipes) ou Câmera ISO (na Colação).
- `H1`, `H4`, `H5`, `H6`, `ZOOM`, `LAPELA`, `MIC`, `GRAVADOR` → Gravador / lapela.
- `FRIAS`, `DECORAÇÃO`, `DECORACAO`, `BASTIDORES`, `AMBIENTE` → Imagens extras / frias.
- `DRONE` → Drone.
- `PROXIES` e `ADOBE PREMIERE PRO…` → Ignorar.
- Qualquer outro nome → Câmera.

**Canais da mesa de corte:** "Já misturado" (padrão) ou "L = mesa de som / R = ambiente". O
valor é guardado no projeto para a 2.3 usar.

**Oficina com vários dias:** a pasta do projeto leva a data do primeiro dia
(`2026-03-10 OFICINA ESCOLA X T106`), e cada dia fica numa subpasta. A tabela de pastas lista
os **dois níveis**: as subpastas de cada dia aparecem como `DIA\CAM A`.

- `FolderAssignment.folder` recebe esse caminho relativo, e `day_label` recebe o nome da pasta
  do dia.
- O inventário comum já aceita isso, porque usa `source_dir / folder` e `os.walk`.
- **Detecção:** uma subpasta direta é tratada como "dia" quando contém outras pastas e nenhum
  arquivo de mídia solto. Nos outros casos a listagem fica com um nível só, como no Casamento.

### `projeto.py`: dados próprios do projeto da Formatura

O `projeto.json` comum (`ProjectRequest`) não muda. A Formatura grava **ao lado dele** um
`formatura.json`:

```python
class ProjetoFormatura(BaseModel):
    tipo: TipoTrabalho
    formatura_id: str
    curso: str | None = None          # oficina/feira/prova_toga/paraninfo
    turma: str | None = None
    funcoes: dict[str, FuncaoFormatura]   # pasta relativa → função da Formatura
    canais_mesa: Literal["misturado", "L_mesa_R_ambiente"] = "misturado"
    duplicado_de: str | None = None   # pasta do evento da oficina original
    seguir_ideia: bool = True         # usado pela 2.2
    # só na colação:
    local: str | None = None
    cidade: str | None = None
    turmas_colacao: list[tuple[str, str]] = []   # (curso, turma), na ordem da cerimônia
```

- A data do evento vem do nome da pasta (`AAAA-MM-DD`), como nas outras áreas.
- `ProjectRequest.assignments` recebe as funções já traduzidas para `Role`, e o pipeline comum
  lê só isso.

### `momentos.py`: momentos por tipo

`MOMENTOS_FORMATURA` fica como está, porque é usado pelos testes da plataforma. Entram:

- `MOMENTOS_POR_TIPO: dict[TipoTrabalho, list[str]]`:
  - **Oficina:** chegada e ambiente, alunos trabalhando, detalhes (mãos, ferramentas, peças),
    professor ensinando, depoimento, interação e risadas, turma reunida, momento final.
  - **Feira:** visão geral da feira, estande ou projeto, aluno explicando o projeto,
    demonstração funcionando, visitantes, equipe reunida.
  - **Prova de toga:** vestindo a beca, ajudando o colega, espelho e detalhes, reações, fotos em
    grupo, falas.
  - **Escolha do paraninfo:** anúncio, reação do escolhido, falas, turma reunida.
  - **Colação:** as 10 partes da cerimônia do briefing, mais plateia e família, emoção, beca
    jogada e comemoração.
- `PROBLEMAS_TECNICOS = ["chicote", "desfocado", "mal enquadrado", "tremido", "escuro"]`,
  vocabulário que a análise da 2.2 usa para aplicar a regra de qualidade.

A análise do Gemini com esses momentos é feita na 2.2, numa versão própria de
`gemini/analysis.py` dentro desta pasta.

### `estilo.py`: estudo de estilo da Formatura (pendência da plataforma)

Hoje `gemini/style.py` usa um prompt de **casamento**, e o cache por vídeo
(`<system_dir>\estilo_cache\<id>.json`) é **comum às áreas**. A Formatura passa a ter a própria
versão:

- Reaproveita sem mudança `expand_playlists`, `urls_estilo(s, "formatura")`, o cliente Gemini,
  o `controle` (Pausar/Parar) e a gravação segura.
- **Prompts próprios.**
  - Por vídeo: "vídeo de formatura publicado pela Fokuss (clipe de oficina, feira, prova de
    toga, escolha do paraninfo, abertura ou encerramento da colação, ou íntegra)". Ele descreve
    ritmo, abertura e cartela, uso de falas e depoimentos, trilha e energia, cor e fechamento,
    sem descrever pessoas.
  - Agregado: perfil por tipo de clipe.
- **Notas e perfil próprios:**
  - `NotasEstiloFormatura` com `tipo` de formatura e os mesmos campos técnicos, menos o
    "gancho para o próximo episódio".
  - `PerfilEstiloFormatura` com duração média e ritmo **por tipo**, padrões de abertura e
    cartela, uso de falas, trilhas, cor, fechamento e resumo.
- **Cache próprio:** `<system_dir>\estilo_cache\formatura\<id>.json`. Um vídeo estudado como
  casamento não serve para a Formatura, e vice-versa.
- **Perfil:** `<system_dir>\perfil_estilo_formatura.json`, o mesmo nome que a plataforma já
  usa para a área.
- Funções com a mesma assinatura das comuns: `video_em_cache`, `load_style_profile`,
  `build_style_profile`.

## Ganchos na plataforma (acréscimos com padrão)

1. **`Area` ganha três campos opcionais** (`areas/base.py`):
   - `abas_projeto: tuple[tuple[str, type], ...] = ()`: abas de projeto da área, no formato
     (nome, formulário). Vazio quer dizer uma aba "Projeto" com `formulario`, que é o
     comportamento atual.
   - `abas_extras: tuple[tuple[str, Callable], ...] = ()`: abas que não são de projeto, no
     formato (nome, fábrica do widget). A Formatura usa para "Formaturas".
   - `estilo: ModuleType | None = None`: módulo de estudo de estilo da área. `None` quer dizer
     `gemini.style`.

   O Casamento não passa nenhum deles e fica igual.
2. **`MainWindow` e `ProjetoTab`** (`ui/app.py`, `ui/projeto.py`):
   - `MainWindow` cria uma `ProjetoTab` para cada item de `abas_projeto` e depois as
     `abas_extras`.
   - `ProjetoTab` aceita um `formulario` opcional (padrão `area.formulario`).
   - A lista de recentes de cada aba de projeto usa `formulario.aceita_projeto(pasta_trabalho)`,
     um método de classe opcional que por padrão aceita tudo. Assim a aba Clipes mostra só
     clipes, e a Colação só colações.
   - `projetos()`, a fila e as marcas do seletor passam a contar todas as abas de projeto.
3. **Estudo de estilo e pipeline** (`ui/abas.py` `EstiloTab`, `pipeline.py`): onde hoje chamam
   `gemini.style`, passam a chamar `area_por_id(area).estilo or gemini.style`.
4. **Configurações** (`config.py`, `ui/abas.py` `ConfigTab`): novo
   `Settings.logo_produtora: str = ""`, com um campo para escolher o arquivo. O Casamento não lê
   esse campo.

Nenhuma dessas mudanças altera o comportamento do Casamento, e os testes atuais seguem
passando sem edição.

## Interface (`areas/formatura/ui/`)

- **`SeletorFormatura`** (widget comum às duas sub-abas): lista de formaturas do cadastro, com
  os botões "+ Nova" e "Editar", que abrem o `DialogoFormatura`. Abaixo dela vêm os campos que
  dependem do tipo: curso e turma em listas preenchidas pela ficha, ou, na colação, a lista de
  turmas com caixas de marcar.
- **`DialogoFormatura`**: edita a ficha, com instituição, logo (escolher arquivo), ano,
  semestre, cursos e turmas (tabela com acrescentar, remover e renomear) e pasta de grafismos.
- **`FormularioClipe(FormularioFormatura)`**: aba Clipes.
  - Escolhe o tipo (Oficina, Feira, Prova de toga, Paraninfo), a formatura, o curso e a turma.
  - Tem a tabela de pastas com as funções da Formatura (dois níveis quando houver dias), a
    pasta de músicas (campo comum) e o modo Gemini.
  - Botão **"Duplicar de uma oficina…"**:
    - lista as oficinas já preparadas da mesma área;
    - copia formatura, tipo, pasta de músicas, modo Gemini e grafismos;
    - pede a pasta nova e a turma nova;
    - grava `duplicado_de` e `seguir_ideia` (marcado por padrão, com o texto "Seguir a ideia da
      original: mesmos assuntos e ordem, com música nova, e ritmo e cenas pela trilha nova").
  - `aceita_projeto`: o `formatura.json` existe e o tipo é de clipe.
- **`FormularioColacao(FormularioFormatura)`**: aba Colação.
  - Escolhe a formatura, local, cidade e as turmas da noite (ordem arrastável).
  - Tem a tabela de pastas com as funções da Colação, os canais da mesa de corte e a pasta de
    músicas.
  - Mostra, só para leitura, as oficinas já preparadas daquelas turmas.
  - `aceita_projeto`: o tipo é colação.
- **`CadastroTab`** (aba Formaturas): lista com Nova, Editar e Duplicar, e quantos projetos usam
  cada ficha.
- `FORMATURA.formulario` passa a ser `FormularioClipe`, que herda de `FormularioFormatura`.
  Assim os testes da plataforma (Iniciar desligado com o aviso, numeração do card Gemini, pasta
  fora do padrão recusada) continuam valendo.
- `FORMATURA` ganha `abas_projeto=(("Clipes", FormularioClipe), ("Colação",
  FormularioColacao))`, `abas_extras=(("Formaturas", CadastroTab),)` e
  `estilo=areas.formatura.estilo`.

## Fluxo de dados

1. O editor cria ou escolhe a formatura, e a ficha é gravada em `FORMATURAS\`.
2. Na aba Clipes ou Colação, escolhe a pasta do evento. O sistema lista as pastas (um ou dois
   níveis), sugere as funções e o editor confirma.
3. O editor salva a preparação. O sistema grava `projeto.json` (comum, com `area="formatura"`
   e os `Role` traduzidos) e `formatura.json` (dados da Formatura).
4. Na 2.2, o pipeline da Formatura lê os dois arquivos e a ficha.

## Erros e casos de borda

- **Ficha não encontrada** (apagada ou movida): o projeto abre com o aviso "Formatura não
  encontrada. Escolha outra." e os demais dados ficam intactos.
- **Turma removida da ficha mas usada num projeto:** o projeto mantém o nome antigo e mostra
  "turma não está mais na ficha".
- **Logo, grafismos ou logo da produtora que sumiram:** aviso, sem bloquear.
- **Duplicar com a mesma pasta da original:** recusado com a mensagem "Escolha a pasta da nova
  turma".
- **Oficina sem turma, colação sem turmas ou clipe sem formatura:** o formulário não permite
  salvar e diz o que falta.
- **Pasta fora do padrão `AAAA-MM-DD NOME`:** recusada com a mensagem de sempre.
- **Edição da mesma ficha em duas máquinas:** vale a última gravação. Isso fica para a etapa 3.

## Testes

- **Todos os testes atuais passam sem edição**, incluindo `tests/ui/test_areas.py`.
- Novos testes, em `tests/areas/formatura/`:
  - cadastro: criar, salvar, carregar, listar em ordem, duplicar (id novo e semestre
    seguinte), validação (sem curso, turma repetida), logo inexistente como aviso;
  - sugestão de função: `CAM A`, `CAM 1`, `PGM`, `CORTE`, `ATEM`, `H1`, `H4`, `MIC LAPELA`,
    `FRIAS`, `DRONE`, `Proxies`; Câmera nos Clipes e Câmera ISO na Colação;
  - tradução função → `Role`;
  - oficina com vários dias: detecção dos dias, `folder` como `DIA\CAM A` e `day_label`, e o
    inventário comum achando as mídias;
  - `formatura.json`: gravar e ler; projeto com ficha apagada; turma removida;
  - duplicar oficina: campos copiados, pasta igual recusada, `seguir_ideia` marcado;
  - estilo: prompts de formatura, cache em `estilo_cache\formatura\`, vídeo no cache de
    casamento que não conta para a Formatura;
  - ganchos: Casamento com uma aba "Projeto", Formatura com Clipes, Colação e Formaturas;
    recentes filtrados por aba; `EstiloTab` da Formatura chamando o estudo da Formatura;
    campo Logo da produtora salvo.
- Por último, abrir o programa de verdade, criar uma ficha, preparar uma oficina de dois dias,
  duplicá-la para outra turma e preparar uma colação.

## Fora da 2.1

- Roteiro e montagem dos clipes, música nova ao duplicar, regra de qualidade aplicada e
  análise Gemini com os momentos da Formatura (2.2). **Na 2.2, ligar o Iniciar contradiz dois
  testes da plataforma** (`test_areas_registradas_em_ordem` e `test_formatura_nao_inicia`),
  que descrevem o estado provisório. A 2.2 precisa decidir com o usuário como tratar isso.
- Íntegra da colação: correção automática, imagens frias, separação em partes e entrega no
  G (2.3).
- Abertura com o grande final e encerramento (2.4).
- Cartela (2.5, depois dos vídeos de referência).
- Várias máquinas (etapa 3).
