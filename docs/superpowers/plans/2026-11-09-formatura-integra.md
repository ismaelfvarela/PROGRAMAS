# Formatura 2.3: íntegra da colação, plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** a colação processa até a íntegra corrigida no Premiere, com as partes separadas e as
entregas no G pelo painel.

**Architecture:** um pacote novo, `areas/formatura/colacao/`, com funções puras e testáveis
(defeitos, silêncio, partes, frias, plano e XML). O `PipelineFormatura` troca as etapas estilo,
análise, roteiro, pdf e premiere quando o tipo é colação.

**Spec:** `docs/superpowers/specs/2026-11-09-formatura-integra-colacao-design.md`

## Global Constraints

- Os testes rodam com `PYTHONPATH=src ../../.venv/Scripts/python.exe -m pytest`.
- O Casamento não muda. No código comum, só `analyze_event(incluir=None)`.
- O `montar.jsx` continua ASCII puro e ES3 (o teste `test_jsx_ascii_e_es3` já cobre).
- Toda gravação usa `safe_write_text` ou `safe_mkdir`.

## Review Focus

1. **PGM em vários arquivos**, quando a mesa grava em pedaços: os tempos de cada arquivo entram
   na linha do tempo pela sincronização. Teste na Tarefa 3, com dois arquivos PGM.
2. **Espaço morto dentro de uma troca:** o corte vale para as duas coisas, sem trecho
   negativo. Teste na Tarefa 3.
3. **Turma da noite que o Gemini não achou:** alerta, e as outras partes seguem. Teste na Tarefa 2.
4. **ISO que cobre só parte do defeito:** a ISO cobre o que pode e o resto vai para a fria ou
   fica sem cobertura. Teste na Tarefa 3.
5. **Ajuste do editor:** o pedido entra no prompt das partes e os defeitos não são recalculados.
   Teste na Tarefa 5.

---

### Task 1: Defeitos e silêncio

**Files:** criar `colacao/__init__.py`, `colacao/defeitos.py` e `colacao/silencio.py`; testes
em `tests/areas/formatura/colacao/test_defeitos.py`.

**Produces:**
- `Defeito(BaseModel: inicio_s, fim_s, tipo: Literal["escuro","desfocado","chicote","tremido"])`;
- `Amostras(brilho: np.ndarray, nitidez: np.ndarray, diferenca: np.ndarray)`;
- `classificar(a: Amostras, fps: float) -> list[Defeito]`;
- `medir(video: Path, fps=4) -> Amostras` (ffmpeg em fluxo);
- `silencios(audio: Path, limite_db: float, min_s=4.0) -> list[tuple[float, float]]`.

- [ ] Testes do classificador: amostras sintéticas para escuro, desfocado, chicote e tremido; um
  pico de uma amostra só (corte) não vira defeito; intervalos próximos se juntam com a folga.
- [ ] `medir` num vídeo de 4 s, metade preta (gerado com ffmpeg `color=black` + `testsrc`): o
  defeito "escuro" aparece entre 0 e 2 s, mais ou menos 0,5 s.
- [ ] `silencios` num WAV com ruído, 6 s de silêncio e ruído de novo: um intervalo de cerca de 6 s.
- [ ] Implementar, rodar os testes e gravar o commit.

### Task 2: Partes e imagens frias

**Files:** `colacao/partes.py`, `colacao/frias.py` e o acréscimo `incluir` em
`gemini/analysis.py`; os testes `test_partes.py` e `test_frias.py`, mais um teste de `incluir` em
`test_ganchos.py`.

**Produces:**
- `PARTES_PADRAO: list[tuple[str, str]]` (código, nome);
- `ParteDetectada(BaseModel: codigo, curso: str|None, turma: str|None, inicio_s: float)`;
- `RespostaPartes(BaseModel: partes: list[ParteDetectada])`;
- `transcricao_em_linhas(palavras: list[tuple[float, str]], passo=15) -> str`;
- `detectar_partes(c, model, linhas, turmas, duracao_s, pedido=None) -> tuple[list[ParteNomeada], list[str]]`,
  com `ParteNomeada(nome, inicio_s)`, já validada e ordenada, e os alertas;
- `nome_parte(codigo, curso, turma) -> str`;
- `BancoFrias(itens: list[ItemFria(midia_rel, inicio_s, fim_s, momento, qualidade)])` e
  `banco_frias(db, rels_frias) -> BancoFrias`;
- `BancoFrias.escolher(assunto: str, duracao_s: float) -> list[tuple[str, float, float]]` (lembra
  os trechos já usados).

- [ ] Teste de `incluir`: com `analyze_event(incluir=lambda m: m.rel_path.startswith("FRIAS"))`,
  só as mídias de FRIAS vão ao cliente falso.
- [ ] Testes das partes:
  - o prompt traz as turmas e a transcrição;
  - fora de ordem é ordenado;
  - código desconhecido sai;
  - início além da duração sai;
  - turma da noite que não veio → alerta "Não achei a colação da turma …";
  - exceção comum → uma parte só, "Cerimônia Completa", com alerta;
  - `QuotaPaused` propaga;
  - o pedido do editor aparece no prompt.
- [ ] Testes das frias: hino prefere decoração; colação prefere plateia; não repete; junta
  trechos para cobrir a duração.
- [ ] Implementar, rodar os testes e gravar o commit.

### Task 3: Plano da íntegra

**Files:** `colacao/plano.py` e `test_plano.py`.

**Produces:**
- `Troca(inicio_s, fim_s, motivo, fonte: str)`; a fonte é `"pgm"`, `"iso:<rel>"`,
  `"fria:<rel>@<ini>-<fim>"` ou `"sem"`;
- `ParteIntegra(numero, nome, inicio_s, fim_s, trechos: list[tuple[float, float]], trocas:
  list[Troca], cortes: list[tuple[float, float]])`;
- `PlanoIntegra(partes, alertas)`;
- `montar_plano(partes: list[ParteNomeada], fim_s, defeitos_tl: list[Defeito], mortos_tl,
  isos: list[tuple[str, float, float]], frias: BancoFrias, assunto_da_parte) -> PlanoIntegra`.
  Todos os tempos estão na linha do tempo da mesa.

- [ ] Testes:
  - parte vai de um início ao próximo; a última vai até `fim_s`;
  - trechos = parte menos os espaços mortos (com 0,5 s de margem);
  - defeito coberto por ISO → `iso:`;
  - ISO cobre metade → metade ISO e metade fria;
  - sem ISO nem fria → `sem`;
  - trocas a menos de 0,5 s se juntam;
  - defeito dentro de um espaço morto cortado não gera troca.
- [ ] Implementar, rodar os testes e gravar o commit.

### Task 4: XML da íntegra, job com entregas e painel

**Files:** `colacao/xml_integra.py`, `colacao/entrega.py`, `premiere_panel/host/montar.jsx`,
`premiere_panel/main.js` e `premiere_panel/index.html`; os testes `test_xml_integra.py` e um
acréscimo em `tests/premiere/test_panel_files.py` (teste novo, sem editar os antigos).

**Produces:**
- `build_xml_integra(plano, db, source_root, pgm_rels: list[str]) -> str`;
- `write_job_integra(p, s, xml_path, db, plano) -> Path`, que grava o job comum mais
  `entregas`.

- [ ] Testes do XML:
  - uma sequência por parte, com o nome `NN - Nome`;
  - V1 tem o PGM e a ISO no intervalo da troca;
  - MESA L/R com o PGM em todos os trechos;
  - marcador "TROCA: chicote → …";
  - marcador "CORTE: …";
  - o XML é válido (`ET.fromstring`).
- [ ] Teste do job: as `entregas` com `G:\…\03 - Hino Nacional.mp4`, na ordem.
- [ ] Teste do painel: `exportarEntregas`, `encodeSequence` e `startBatch` no jsx; `btnExportar`
  no html e no js.
- [ ] Implementar, rodar os testes e gravar o commit.

### Task 5: Pipeline da colação, interface e PDF

**Files:** `areas/formatura/pipeline.py`, `areas/formatura/formulario.py`,
`colacao/relatorio.py`; os testes `test_pipeline_colacao.py` e a integração
`test_integracao_colacao.py`; trocar o teste `test_colacao_recusada` (agora ela inicia) e
`test_colacao_avisa` na interface.

- [ ] Testes:
  - etapas da colação chamadas;
  - estilo não roda;
  - análise com `incluir` só para as frias;
  - roteiro grava `integra.json` e `defeitos.json` (o ajuste não recalcula os defeitos e manda o
    pedido);
  - pdf e premiere gerados;
  - sem PGM → `PipelineError`.
- [ ] Interface: a colação com turma marcada liga o Iniciar; sem pasta PGM →
  "Marque a pasta da mesa de corte (PGM).".
- [ ] Integração: evento sintético com PGM, ISO e FRIAS, Gemini e Whisper falsos, até o XML.
- [ ] Suíte inteira, briefing, merge e push.
